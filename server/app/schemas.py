"""
schemas.py — Modelos de Dados Pydantic para Validação de Payloads
AgentCarDiag Server
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class DiagnosticPayload(BaseModel):
    oem_key: str = Field(..., description="Chave OEM do veículo (ex: 'VW_EA288', 'RENAULT_M9R')")
    can_telemetry: Dict[str, Any] = Field(default_factory=dict, description="Dados de telemetria CAN / OBD-II")
    scope_telemetry: Dict[str, Any] = Field(default_factory=dict, description="Dados de captura do osciloscópio")


class OtaUploadResponse(BaseModel):
    status: str
    msg: str


class VinDecodeResponse(BaseModel):
    vin: str
    valid: bool
    manufacturer: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    engine: Optional[str] = None
    fuel_type: Optional[str] = None
    detected_protocol: Optional[str] = None
    recommended_steps: Optional[List[str]] = None


class DtcLookupResponse(BaseModel):
    code: str
    found: bool
    description: str


class SystemHealthResponse(BaseModel):
    status: str
    service: str
    version: str
