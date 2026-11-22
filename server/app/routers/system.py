"""
system.py — Router de Status do Sistema, Health Check e Consultas Diagnósticas (VIN / DTC)
AgentCarDiag Server
"""

import json
import logging
from fastapi import APIRouter, Query, Depends
from fastapi.responses import JSONResponse

from app.config import DTC_DATABASE_PATH, REFERENCE_WAVEFORMS_PATH, WORKSHOP_MANUALS_PATH, SYSTEM_VERSION, SERVICE_NAME
from app import database as db
from app.websocket_manager import manager, gateway_manager
from app.vin_decoder import vin_service
from app.schemas import SystemHealthResponse, DtcLookupResponse
from app.dependencies import verify_credentials

logger = logging.getLogger("cardiag.system")

router = APIRouter(tags=["System & Vehicles"])


@router.get("/health", response_model=SystemHealthResponse, tags=["System"])
async def health_check():
    """Health check para Docker probes e balanceador de carga."""
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SYSTEM_VERSION
    }


@router.get("/status", tags=["System"])
async def get_status():
    """Retorna o status atual dos nós conectados, gateway e sessão ativa."""
    status_data = manager.get_status()

    # Adicionar o ESP32 atual à lista de nós HW
    for dtype, node in gateway_manager.nodes.items():
        if node.get("ws"):
            status_data["hardware_nodes"].append({
                "id": dtype,
                "connected_at": node.get("last_seen"),
                "messages_sent": 0
            })

    status_data["gateway_status"] = gateway_manager.get_status_payload()

    active_session_id = await db.get_active_session_id()
    if active_session_id:
        active_session = await db.get_session(active_session_id)
        status_data["active_session"] = active_session
    else:
        status_data["active_session"] = None

    return JSONResponse(content=status_data)


@router.get("/api/vin/decode", tags=["Vehicles"])
async def decode_vin_endpoint(vin: str = Query(..., description="17-character VIN")):
    """Decodifica VIN do veículo via NHTSA global API + tabela offline ISO 3779."""
    return vin_service.decode(vin)


@router.get("/api/dtc/lookup", response_model=DtcLookupResponse, tags=["Vehicles"])
async def lookup_dtc_endpoint(code: str = Query(..., description="DTC code (ex: P048B, P0117, U029D)")):
    """Busca descrição e diagnóstico na base local de 2.060+ DTCs automotivos."""
    clean_code = code.split("(", 1)[0].strip().upper()
    if DTC_DATABASE_PATH.exists():
        try:
            dtc_data = json.loads(DTC_DATABASE_PATH.read_text(encoding="utf-8"))
            desc = dtc_data.get(clean_code) or dtc_data.get(clean_code[:5]) or dtc_data.get(clean_code[:4])
            if desc:
                return {"code": clean_code, "found": True, "description": desc}
        except Exception as e:
            logger.error(f"Erro ao consultar dtc_database.json: {e}")

    return {
        "code": clean_code,
        "found": False,
        "description": "Falha diagnóstica registrada pela ECU"
    }


@router.get("/api/auth/me", tags=["Auth"])
async def get_current_user_info(auth_data: dict = Depends(verify_credentials)):
    """Retorna os dados cadastrais da oficina ou administrador autenticado."""
    return auth_data


@router.get("/api/oscilloscope/references", tags=["Oscilloscope"])
async def get_reference_waveforms():
    """Retorna catálogo de formas de onda automotivas de referência (Known Good Signals)."""
    if REFERENCE_WAVEFORMS_PATH.exists():
        try:
            data = json.loads(REFERENCE_WAVEFORMS_PATH.read_text(encoding="utf-8"))
            return JSONResponse(content=data)
        except Exception as e:
            logger.error(f"Erro ao carregar reference_waveforms.json: {e}")
            return JSONResponse(status_code=500, content={"error": "Erro ao carregar banco de referências"})
    return JSONResponse(status_code=404, content={"error": "Banco de referências não encontrado"})


@router.get("/api/manuals", tags=["Workshop Manuals"])
async def get_workshop_manuals(vehicle_id: str = Query(None, description="ID do veículo para filtrar manual específico")):
    """Retorna dados técnicos de oficina, torques, fluidos, sincronismo e guias de reparo."""
    if WORKSHOP_MANUALS_PATH.exists():
        try:
            data = json.loads(WORKSHOP_MANUALS_PATH.read_text(encoding="utf-8"))
            if vehicle_id:
                vehicle_manual = next((v for v in data.get("vehicles", []) if v["id"] == vehicle_id), None)
                if vehicle_manual:
                    return JSONResponse(content={"found": True, "manual": vehicle_manual})
                return JSONResponse(status_code=404, content={"found": False, "error": f"Manual não encontrado para veículo '{vehicle_id}'"})
            return JSONResponse(content=data)
        except Exception as e:
            logger.error(f"Erro ao carregar workshop_repair_manuals.json: {e}")
            return JSONResponse(status_code=500, content={"error": "Erro ao carregar manuais de oficina"})
    return JSONResponse(status_code=404, content={"error": "Banco de manuais de oficina não encontrado"})


@router.get("/api/oscilloscope/hantek/status", tags=["Oscilloscope"])
async def get_hantek1008_status():
    """Verifica se o Osciloscópio Automotivo Hantek 1008C (USB 0783:5725) está conectado via USB."""
    try:
        import sys
        from pathlib import Path
        root_dir = Path(__file__).resolve().parents[3]
        if str(root_dir / "hantek_tools") not in sys.path:
            sys.path.insert(0, str(root_dir / "hantek_tools"))
        from hantek1008_driver import Hantek1008C
        connected = Hantek1008C.is_connected()
        return {
            "connected": connected,
            "device": "Hantek 1008C (8-Channel Automotive Oscilloscope)",
            "usb_id": "0783:5725",
            "channels": 8,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.post("/api/oscilloscope/hantek/capture", tags=["Oscilloscope"])
async def trigger_hantek1008_capture(
    ch1: int = Query(1, ge=1, le=8, description="Canal primário 1..8"),
    ch2: int = Query(2, ge=1, le=8, description="Canal secundário 1..8"),
    ns_per_div: int = Query(500_000, description="Base de tempo em ns/div"),
    vscale: float = Query(1.0, description="Escala vertical (1.0, 0.125, 0.02)"),
    atten1: float = Query(1.0, description="Atenuação da ponta CH1 (ex: 1.0 ou 20.0)"),
    atten2: float = Query(1.0, description="Atenuação da ponta CH2 (ex: 1.0 ou 20.0)"),
):
    """Captura uma janela Burst direto do Hantek 1008C via USB, transmite via WebSocket para a UI e persiste na sessão."""
    try:
        import asyncio
        import sys
        from pathlib import Path
        root_dir = Path(__file__).resolve().parents[3]
        if str(root_dir / "hantek_tools") not in sys.path:
            sys.path.insert(0, str(root_dir / "hantek_tools"))
        from hantek1008_driver import Hantek1008C

        if not Hantek1008C.is_connected():
            return JSONResponse(
                status_code=404,
                content={"ok": False, "error": "Hantek 1008C (0783:5725) não detectado na porta USB."},
            )

        c1_idx = ch1 - 1
        c2_idx = ch2 - 1
        active_chs = sorted(list(set([c1_idx, c2_idx])))
        atten_list = [1.0] * 8
        atten_list[c1_idx] = atten1
        atten_list[c2_idx] = atten2

        def _capture_sync():
            scope = Hantek1008C(
                ns_per_div=ns_per_div,
                vertical_scale_factor=vscale,
                active_channels=active_chs,
                probe_attenuation=atten_list,
            )
            scope.connect()
            try:
                scope.init(calibrate_all_scales=True)
                sr = int(scope.get_effective_sample_rate_hz())
                data = scope.capture_burst(as_volts=True)
                s1 = [float(v) for v in data.get(c1_idx, [])][:512]
                s2 = [float(v) for v in data.get(c2_idx, [])][:512]
                m1 = scope.compute_channel_metrics(s1, sr)
                m2 = scope.compute_channel_metrics(s2, sr)
                return sr, s1, s2, m1, m2
            finally:
                scope.close()

        sr_hz, s1, s2, m1, m2 = await asyncio.to_thread(_capture_sync)
        burst_payload = {
            "type": "adc_burst",
            "serial": "o2001",
            "device": "Hantek_1008C",
            "sample_rate": sr_hz,
            "ch1": s1,
            "ch2": s2,
            "vmin": m1["vmin"],
            "vmax": m1["vmax"],
            "vmean": m1["vmean"],
            "metrics_ch1": m1,
            "metrics_ch2": m2,
        }

        session_id = await db.get_active_session_id()
        if session_id:
            await db.persist_osc_capture(session_id, burst_payload)
            await db.update_session_timestamp(session_id)

        await manager.broadcast_to_clients(burst_payload)
        await gateway_manager.broadcast_to_web(burst_payload)
        return {"ok": True, "sample_rate": sr_hz, "metrics_ch1": m1, "metrics_ch2": m2, "samples_count": len(s1)}
    except Exception as e:
        logger.error(f"Erro na captura Hantek 1008C: {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})



