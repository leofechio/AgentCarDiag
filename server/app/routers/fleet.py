"""
routers/fleet.py — Endpoints REST para o AguiaCar Fleet Guardian
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
import json
import logging
from datetime import datetime, timezone

from app.database import get_db
from app.fleet_engine import fleet_engine

logger = logging.getLogger("cardiag.fleet.router")

router = APIRouter(prefix="/api/fleet", tags=["AguiaCar Fleet"])

class FleetConfigUpdate(BaseModel):
    gps_interval_sec: int
    gps_standby_interval_sec: int
    dtc_scan_interval_min: int
    alert_email: str
    max_engine_temp: float
    max_rpm: float
    max_speed: float
    notify_disconnect: int
    geofence_enabled: Optional[int] = 1
    geofence_lat: Optional[float] = 40.4168
    geofence_lon: Optional[float] = -3.7038
    geofence_radius_km: Optional[float] = 15.0

class TelemetryPayload(BaseModel):
    device_id: str
    type: Optional[str] = "aguiacar_telemetry"
    fw_version: Optional[str] = "v2.5.2"
    gps: dict
    telemetry: dict

@router.post("/telemetry_ingest")
async def ingest_telemetry(payload: TelemetryPayload):
    """Recebe dados telemáticos 4G do AguiaCar."""
    logger.info(f"🛰️ [AGUIACAR 4G RECEBIDO] Dispositivo: {payload.device_id} | FW: {payload.fw_version} | GPS: {payload.gps} | OBD: {payload.telemetry}")
    
    # Atualiza o gateway de hardwares para refletir Online em tempo real no site
    from app.websocket_manager import gateway_manager
    clean_serial = payload.device_id.strip().lower()
    await gateway_manager.register_heartbeat(clean_serial, device_type="fleet_tracker", fw_version=payload.fw_version)
    
    res = await fleet_engine.process_telemetry(payload.dict())
    return res

@router.get("/vehicles")
async def list_vehicles():
    """Lista veículos da frota com último status e coordenadas."""
    async with get_db() as db:
        async with db.execute("SELECT * FROM fleet_vehicles ORDER BY last_seen DESC") as cur:
            rows = await cur.fetchall()
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in rows]

@router.get("/telemetry/{vehicle_id}")
async def get_vehicle_telemetry(vehicle_id: str, limit: int = 50):
    """Retorna histórico telemático recente de um veículo para mapa e gráficos."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM fleet_telemetry WHERE vehicle_id = ? ORDER BY id DESC LIMIT ?",
            (vehicle_id, limit)
        ) as cur:
            rows = await cur.fetchall()
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in reversed(rows)]

@router.get("/config/{vehicle_id}")
async def get_config(vehicle_id: str):
    """Consulta configurações remotas OTA do veículo."""
    cfg = await fleet_engine.get_or_create_config(vehicle_id)
    return cfg

@router.post("/config/{vehicle_id}")
async def update_config(vehicle_id: str, update: FleetConfigUpdate):
    """Atualiza configurações remotas pelo site."""
    now_ts = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO fleet_vehicles (id, name, plate, model, company, status, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (vehicle_id, f"Rastreador {vehicle_id}", "Aguardando", "Aguardando Leitura CAN", "Oficina Local", "DESCONECTADO", now_ts)
        )
        await db.execute(
            """
            INSERT INTO fleet_configs 
            (vehicle_id, gps_interval_sec, gps_standby_interval_sec, dtc_scan_interval_min, alert_email, max_engine_temp, max_rpm, max_speed, notify_disconnect, geofence_enabled, geofence_lat, geofence_lon, geofence_radius_km)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(vehicle_id) DO UPDATE SET
                gps_interval_sec = excluded.gps_interval_sec,
                gps_standby_interval_sec = excluded.gps_standby_interval_sec,
                dtc_scan_interval_min = excluded.dtc_scan_interval_min,
                alert_email = excluded.alert_email,
                max_engine_temp = excluded.max_engine_temp,
                max_rpm = excluded.max_rpm,
                max_speed = excluded.max_speed,
                notify_disconnect = excluded.notify_disconnect,
                geofence_enabled = excluded.geofence_enabled,
                geofence_lat = excluded.geofence_lat,
                geofence_lon = excluded.geofence_lon,
                geofence_radius_km = excluded.geofence_radius_km
            """,
            (
                vehicle_id, update.gps_interval_sec, update.gps_standby_interval_sec,
                update.dtc_scan_interval_min, update.alert_email, update.max_engine_temp,
                update.max_rpm, update.max_speed, update.notify_disconnect,
                update.geofence_enabled, update.geofence_lat, update.geofence_lon, update.geofence_radius_km
            )
        )
        await db.commit()

    logger.info(f"[FleetConfig] Configurações atualizadas para o veículo {vehicle_id}!")
    return {"status": "success", "msg": "Configurações sincronizadas com sucesso!"}

@router.get("/alerts")
async def list_alerts(status: Optional[str] = None):
    """Lista alertas e Ordens de Serviço geradas pela IA."""
    query = "SELECT * FROM fleet_alerts"
    params = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT 50"

    async with get_db() as db:
        async with db.execute(query, tuple(params)) as cur:
            rows = await cur.fetchall()
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in rows]

@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    """Marca uma ordem de serviço/alerta como resolvida pela oficina."""
    async with get_db() as db:
        await db.execute("UPDATE fleet_alerts SET status = 'RESOLVED' WHERE id = ?", (alert_id,))
        await db.commit()
    return {"status": "success", "msg": "Alerta resolvido!"}

@router.post("/simulate")
async def simulate_event(scenario: str = "normal"):
    """
    Endpoint de demonstração comercial:
    - 'normal': carro trafegando perfeitamente por Madrid
    - 'overheat': dispara superaquecimento a 112°C com alerta de Parada Imediata
    - 'cold_abuse': motor frio sendo forçado a 4.200 RPM
    - 'dtc': código P0117 detectado acionando o laudo da IA Gemini
    - 'disconnect': corte de 12V simulando furto com bateria LiPo
    """
    import random
    base_lat, base_lon = 40.4168, -3.7038 # Madrid Centro

    payload = {
        "device_id": "AGUIA-SPAIN-01",
        "type": "aguiacar_telemetry",
        "gps": {
            "valid": True,
            "lat": base_lat + random.uniform(-0.015, 0.015),
            "lon": base_lon + random.uniform(-0.015, 0.015),
            "speed_kmh": 68.0,
            "heading": 135.0,
            "alt": 650.0,
            "satellites": 9
        },
        "telemetry": {
            "rpm": 2150.0,
            "speed": 67.0,
            "temp_c": 90.0,
            "fuel_pct": 74.5,
            "engine_load_pct": 32.0,
            "throttle_pct": 25.0,
            "dtcs": "",
            "battery_v": 13.8,
            "backup_batt_v": 4.15
        }
    }

    if scenario == "overheat":
        payload["telemetry"]["temp_c"] = 112.5
        payload["telemetry"]["engine_load_pct"] = 88.0
    elif scenario == "cold_abuse":
        payload["telemetry"]["temp_c"] = 48.0
        payload["telemetry"]["rpm"] = 4200.0
    elif scenario == "dtc":
        payload["telemetry"]["dtcs"] = "P0117"
        payload["telemetry"]["temp_c"] = 108.0
    elif scenario == "disconnect":
        payload["type"] = "obd_disconnect_alert"
        payload["telemetry"]["battery_v"] = 0.0
        payload["telemetry"]["connected"] = False
    elif scenario == "geofence_exit":
        # Posiciona veículo a ~35km de Madrid (violando raio de 15km)
        payload["gps"]["lat"] = 40.7521
        payload["gps"]["lon"] = -3.7210
    elif scenario == "harsh_brake":
        payload["telemetry"]["accel_g"] = -0.65
        payload["telemetry"]["speed"] = 18.0
    elif scenario == "harsh_accel":
        payload["telemetry"]["accel_g"] = 0.45
        payload["telemetry"]["rpm"] = 4600.0
    elif scenario == "crash":
        payload["telemetry"]["accel_g"] = 3.20
        payload["telemetry"]["speed"] = 0.0

    res = await fleet_engine.process_telemetry(payload)
    return {"scenario": scenario, "result": res}
