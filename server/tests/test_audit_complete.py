"""
test_audit_complete.py — Auditoria Funcional Integral e Validação Real com ESP32
AgentCarDiag Full-Stack Automated Audit & Hardware Emulation Suite
"""

import asyncio
import json
import os
import time
import pytest
import websockets
from starlette.testclient import TestClient

from app.main import app
from app.config import WS_TOKEN, ADMIN_USER, ADMIN_PASSWORD
from app import database as db

PORT = os.getenv("CARDIAG_PORT", "8001")
BASE_HTTP = f"http://127.0.0.1:{PORT}"
WS_BASE = f"ws://127.0.0.1:{PORT}"


@pytest.fixture(scope="module")
def client():
    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(db.init_db())
    yield
    loop.close()


# ─── 1. AUDITORIA DE SISTEMA E STATUS ─────────────────────────────────────────

def test_system_status(client):
    """Verifica endpoint /status retornando estrutura completa do gateway e nós."""
    res = client.get("/status")
    assert res.status_code == 200
    data = res.json()
    assert "hardware_nodes" in data
    assert "web_clients" in data
    assert "gateway_status" in data


def test_system_health(client):
    """Verifica endpoint /health para monitorização de liveness."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "version" in data


# ─── 2. AUDITORIA DE AUTENTICAÇÃO MULTI-BOX HONEYPOT ──────────────────────────

def test_auth_login_honeypot_trap(client):
    """Tentativa com armadilha preenchida deve resultar em ban imediato (HTTP 403)."""
    res = client.post(
        "/api/auth/login",
        json={"boxes": ["attacker_input", "val", "trap", "", ""]},
        headers={"X-Forwarded-For": "192.168.200.1"}
    )
    assert res.status_code == 403
    detail = res.json()["detail"].lower()
    assert "bloqueado" in detail or "acesso negado" in detail or "trap" in detail


def test_auth_login_success_and_me(client):
    """Login legítimo com credenciais padrão deve retornar token e permitir /api/auth/me."""
    res = client.post(
        "/api/auth/login",
        json={"boxes": ["", "tomate", "", "10", "Fnglckh14p@"]},
        headers={"X-Forwarded-For": "127.0.0.1"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["user"] == "usuario1"

    # Inspeciona /api/auth/me usando o cookie de sessão retornado
    me_res = client.get("/api/auth/me")
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["authenticated"] is True
    assert me_data["user"] == "usuario1"


# ─── 3. AUDITORIA DE SESSÕES DIAGNÓSTICAS ─────────────────────────────────────

def test_sessions_lifecycle(client):
    """Criação, listagem, ativação, atualização e consulta de sessões diagnósticas."""
    create_res = client.post(
        "/api/sessions",
        json={
            "name": "Audi A4 2.0 TDI - Teste Automatizado",
            "vehicle_profile": "vag_edc17",
            "notes": "Veículo em teste de bancada com simulador ESP32-S3"
        }
    )
    assert create_res.status_code == 201
    session = create_res.json()
    session_id = session["id"]
    assert session["name"] == "Audi A4 2.0 TDI - Teste Automatizado"
    assert session["is_active"] == 1

    list_res = client.get("/api/sessions")
    assert list_res.status_code == 200
    sessions = list_res.json()
    assert any(s["id"] == session_id for s in sessions)

    get_res = client.get(f"/api/sessions/{session_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == session_id

    patch_res = client.patch(
        f"/api/sessions/{session_id}",
        json={"notes": "Atualizado durante auditoria funcional"}
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["notes"] == "Atualizado durante auditoria funcional"

    put_res = client.put(f"/api/sessions/{session_id}/activate")
    assert put_res.status_code == 200
    assert put_res.json()["is_active"] == 1


# ─── 4. AUDITORIA DE DTCs, MANUAIS E FORMAS DE ONDA ───────────────────────────

def test_dtc_lookup(client):
    """Consulta de código DTC com normalização."""
    res = client.get("/api/dtc/lookup?code=P0300")
    assert res.status_code == 200
    data = res.json()
    assert data["code"] == "P0300"
    assert "description" in data


def test_manuals_catalog(client):
    """Consulta aos manuais de oficina e diagramas elétricos."""
    res = client.get("/api/manuals")
    assert res.status_code == 200
    data = res.json()
    assert "vehicles" in data
    assert len(data["vehicles"]) > 0


def test_oscilloscope_reference_waveforms(client):
    """Consulta a formas de onda de referência para calibração de osciloscópio."""
    res = client.get("/api/oscilloscope/references")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, (list, dict))


# ─── 5. AUDITORIA DE FROTA ÁGUIACAR E REGRAS PREDITIVAS ────────────────────────

def test_fleet_lifecycle_and_telemetry_ingest(client):
    """Ingestão telemática 4G (AguiaCar), geração de alertas e resolução."""
    telemetry_payload = {
        "type": "aguiacar_telemetry",
        "device_id": "a2000",
        "fw_version": "v2.6.0-wifi-router",
        "gps": {
            "valid": True,
            "lat": 40.4168,
            "lon": -3.7038,
            "speed_kmh": 120.0,
            "heading": 90.0,
            "alt": 650.0,
            "satellites": 8
        },
        "telemetry": {
            "connected": True,
            "vin": "WVWZZZ3CZAE123456",
            "rpm": 3800.0,
            "speed_obd": 118.0,
            "temp_c": 112.0,  # Superaquecimento
            "fuel_pct": 45.0,
            "engine_load_pct": 85.0,
            "throttle_pct": 60.0,
            "dtcs": "P0117",
            "battery_v": 13.8,
            "backup_batt_v": 4.1
        }
    }
    ingest_res = client.post("/api/fleet/telemetry_ingest", json=telemetry_payload)
    assert ingest_res.status_code == 200
    assert ingest_res.json()["status"] in ("ok", "processed")

    veh_res = client.get("/api/fleet/vehicles")
    assert veh_res.status_code == 200

    alerts_res = client.get("/api/fleet/alerts")
    assert alerts_res.status_code == 200
    alerts = alerts_res.json()
    assert len(alerts) > 0
    first_alert = alerts[0]
    alert_id = first_alert["id"]

    resolve_res = client.post(f"/api/fleet/alerts/{alert_id}/resolve")
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] in ("ok", "success", "resolved")


# ─── 6. AUDITORIA DE FLASHER UDS E SEED/KEY ───────────────────────────────────

def test_flasher_algorithms_and_key_calculation(client):
    """Validação da lista de algoritmos de Seed/Key e cálculo de chave de segurança."""
    auth = (ADMIN_USER, ADMIN_PASSWORD)

    algos_res = client.get("/api/flasher/algorithms", auth=auth)
    assert algos_res.status_code == 200
    algos = algos_res.json()
    assert "supported_algorithms" in algos
    assert len(algos["supported_algorithms"]) > 0

    calc_res = client.post(
        "/api/flasher/calculate-key",
        data={
            "algorithm": "BOSCH_ME17_VAG",
            "seed_hex": "12345678"
        },
        auth=auth
    )
    assert calc_res.status_code == 200
    calc_data = calc_res.json()
    assert calc_data["status"] == "success"
    assert "key" in calc_data
    assert len(calc_data["key"]) > 0


# ─── 7. AUDITORIA DE DIAGNÓSTICO X-PRO5 / LAUNCH ENGINE ───────────────────────

def test_xpro5_brands_and_security(client):
    """Validação do catálogo de marcas e resolução de desafio criptográfico AuSCrypto."""
    brands_res = client.get("/api/xpro/brands")
    assert brands_res.status_code == 200
    brands_data = brands_res.json()
    assert "brands" in brands_data
    brands = brands_data["brands"]
    assert len(brands) > 0

    brand_id = brands[0]["id"]
    brand_res = client.get(f"/api/xpro/brand/{brand_id}")
    assert brand_res.status_code == 200
    assert brand_res.json()["id"] == brand_id

    challenge_res = client.post(
        "/api/xpro/security/solve-challenge",
        json={
            "sgbmid": "btld-00007653-00.00.00",
            "seed": "EF A4 17 E3 06 23 96 B6",
            "level": 1
        }
    )
    assert challenge_res.status_code == 200
    c_data = challenge_res.json()
    assert c_data["status"] == "success"
    assert "key_calculated" in c_data


# ─── 8. VALIDAÇÃO REAL WEBSOCKET: HARDWARE GATEWAY & ESP32-S3 EMULADO ──────────

@pytest.mark.asyncio
async def test_websocket_esp32_scanner_handshake_and_queries():
    """
    Emula um ESP32-S3 executando AgentCar_Scanner.ino conectado ao servidor real via WebSocket TCP.
    """
    ws_esp_url = f"{WS_BASE}/ws/esp32?token={WS_TOKEN}&type=Scanner_CAN&serial=s2000&fw=v2.5.2"
    ws_cli_url = f"{WS_BASE}/ws/client"

    async with websockets.connect(ws_esp_url) as ws_esp:
        # Handshake do ESP32
        await ws_esp.send(json.dumps({
            "type": "hw_info",
            "serial": "s2000",
            "fw_version": "v2.5.2",
            "proto": "can",
            "pin": 7,
            "module": "ECU"
        }))

        async with websockets.connect(ws_cli_url) as ws_cli:
            # Cliente web envia comando de troca de protocolo
            await ws_cli.send(json.dumps({
                "cmd": "set_protocol",
                "proto": "kline"
            }))

            # ESP32 recebe comando roteado
            raw_cmd = await asyncio.wait_for(ws_esp.recv(), timeout=3.0)
            esp_cmd = json.loads(raw_cmd)
            assert esp_cmd.get("cmd") == "set_protocol"
            assert esp_cmd.get("proto") == "kline"

            # ESP32 responde com proto_ack
            await ws_esp.send(json.dumps({
                "type": "proto_ack",
                "proto": "kline",
                "pin": 7
            }))

            # Cliente recebe confirmação
            ack = await asyncio.wait_for(ws_cli.recv(), timeout=3.0)
            ack_data = json.loads(ack)
            assert "cmd" in ack_data or "type" in ack_data


@pytest.mark.asyncio
async def test_websocket_esp32_oscilloscope_burst():
    """
    Emula um ESP32-S3 executando AgentCar_Oscilloscope.ino conectado ao servidor real.
    """
    ws_osc_url = f"{WS_BASE}/ws/esp32?token={WS_TOKEN}&type=Osciloscopio&serial=o2000&fw=v2.5.2"
    ws_cli_url = f"{WS_BASE}/ws/client"

    async with websockets.connect(ws_osc_url) as ws_osc:
        # Handshake
        await ws_osc.send(json.dumps({
            "type": "hw_info",
            "serial": "o2000",
            "fw_version": "v2.5.2"
        }))

        async with websockets.connect(ws_cli_url) as ws_cli:
            burst_payload = {
                "type": "adc_burst",
                "sample_rate": 5000,
                "ch1": [round(1.5 + 1.0 * (i % 10) / 10.0, 2) for i in range(100)],
                "ch2": [round(0.5 + 0.5 * ((i + 5) % 10) / 10.0, 2) for i in range(100)]
            }
            await ws_osc.send(json.dumps(burst_payload))

            raw_burst = await asyncio.wait_for(ws_cli.recv(), timeout=3.0)
            burst_data = json.loads(raw_burst)
            assert burst_data.get("type") in ("adc_burst", "hardware_status", "status")


@pytest.mark.asyncio
async def test_websocket_virtual_car_node():
    """
    Emula simulate_car.py conectando ao canal /ws/node/virtual_car_node.
    """
    ws_node_url = f"{WS_BASE}/ws/node/virtual_car_node"
    ws_cli_url = f"{WS_BASE}/ws/client"

    async with websockets.connect(ws_node_url) as ws_node:
        await ws_node.send(json.dumps({
            "type": "handshake",
            "node": "virtual_passat",
            "hw": "SIMULATOR",
            "rate": 10.0,
            "fw": "simulate_car.py/1.0"
        }))

        async with websockets.connect(ws_cli_url) as ws_cli:
            can_frame = {
                "type": "can_frame",
                "id": "0x7E8",
                "extended": False,
                "dlc": 8,
                "data": "04 41 0C 1F 40 AA AA AA",
                "timestamp": "2026-11-15T21:00:00Z"
            }
            await ws_node.send(json.dumps(can_frame))

            raw_frame = await asyncio.wait_for(ws_cli.recv(), timeout=3.0)
            frame_data = json.loads(raw_frame)
            assert "type" in frame_data or "id" in frame_data


@pytest.mark.asyncio
async def test_websocket_resilience_and_reconnection():
    """
    Valida a resiliência do gateway a desconexões abruptas de hardware e reconexão automática.
    """
    ws_esp_url = f"{WS_BASE}/ws/esp32?token={WS_TOKEN}&type=Scanner_CAN&serial=s2000&fw=v2.5.2"

    # Conexão 1
    ws1 = await websockets.connect(ws_esp_url)
    await ws1.send(json.dumps({"type": "hw_info", "serial": "s2000", "fw_version": "v2.5.2"}))
    await asyncio.sleep(0.1)
    # Fechamento abrupto
    await ws1.close()

    await asyncio.sleep(0.2)

    # Reconexão imediata (simulando auto-reconnect do firmware FreeRTOS)
    ws2 = await websockets.connect(ws_esp_url)
    await ws2.send(json.dumps({"type": "hw_info", "serial": "s2000", "fw_version": "v2.5.2"}))
    await asyncio.sleep(0.1)
    await ws2.close()
