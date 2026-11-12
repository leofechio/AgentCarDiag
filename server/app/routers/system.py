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
    clean_code = code.strip().upper().split("(")[0]
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


