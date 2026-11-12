"""
diagnosis.py — Router de Perícia e Validação Cruzada Diagnóstica
AgentCarDiag Server
"""

import logging
from fastapi import APIRouter

from app.schemas import DiagnosticPayload
from app.diagnostic_engine import DiagnosticEngine
from app.ai_agent import query_gemini_diagnostician

logger = logging.getLogger("cardiag.diagnosis")

router = APIRouter(prefix="/api/diagnose", tags=["Diagnostic Engine"])
engine = DiagnosticEngine()


@router.post("/inspect")
async def inspect_telemetry(data: DiagnosticPayload):
    """
    Executa perícia automotiva cruzando dados digitais (CAN/OBD-II) com anomalias físicas (Osciloscópio).
    1. Validação determinística local (Zero-Token).
    2. Fallback inteligente para IA Gemini Diagnostician sob demanda.
    """
    # 1. Executa validação determinística local (Zero-Token)
    local_analysis = engine.cross_validate(data.oem_key, data.can_telemetry, data.scope_telemetry)
    inconsistencies = local_analysis.get("inconsistencies", [])

    # 2. Verifica se existe alguma anomalia com causa física direta mapeada
    deterministic_systems = {"SINCRONISMO_DISTRIBUICAO", "AIRBAG_SRS", "DPF_SATURACAO"}
    direct_fault = next((inc for inc in inconsistencies if inc.get("system") in deterministic_systems), None)

    # Se o defeito for óbvio, responde imediatamente sem gastar tokens da API
    if direct_fault:
        return {
            "source": "LOCAL_DETERMINISTIC",
            "tokens_used": 0,
            "local_analysis": local_analysis,
            "ai_verdict": {
                "veredicto_principal": direct_fault["finding"],
                "certeza_pct": 99,
                "passos_oficina": [
                    f"Causa física confirmada: {direct_fault.get('correlation', 'N/A')}",
                    "Verificação mecânica/elétrica direta recomendada antes de substituir sensores.",
                    "Após o reparo físico, execute o reset de parâmetros e limpe a memória de avarias."
                ]
            }
        }

    # 3. Se não houver causa óbvia ou os dados forem ambíguos, aciona o Gemini Diagnostician
    ai_verdict = await query_gemini_diagnostician(
        oem_data={"name": local_analysis.get("oem_detected", "Genérico")},
        inconsistencies=inconsistencies,
        live_summary={
            "rpm": data.can_telemetry.get("engine_rpm"),
            "dtcs": data.can_telemetry.get("active_dtcs"),
            "dpf_diff_pressure": data.can_telemetry.get("dpf_diff_pressure_mbar"),
            "refrigerant_pressure": data.can_telemetry.get("refrigerant_pressure_bar"),
            "sync_tooth_offset": data.scope_telemetry.get("tooth_offset"),
            "vpp_ch1": data.scope_telemetry.get("vpp_ch1")
        }
    )

    return {
        "source": "GEMINI_DIAGNOSTICIAN",
        "tokens_used": "Sob demanda",
        "local_analysis": local_analysis,
        "ai_verdict": ai_verdict
    }
