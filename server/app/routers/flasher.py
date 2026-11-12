"""
Rotas de Reprogramação e Flasher UDS da Central.
Integração via WebSocket com o ESP32-S3 e API REST para upload de arquivos.
"""
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from typing import Dict, Any, List
import zlib
import hashlib

from app.flasher.seed_key import calculate_security_key, ALGORITHMS
from app.flasher.uds_flasher import UdsFlasherBuilder
from app.dependencies import verify_credentials

router = APIRouter(prefix="/api/flasher", tags=["ECU Flasher"])

@router.get("/algorithms")
async def get_algorithms(_: dict = Depends(verify_credentials)):
    """Lista os algoritmos de Seed/Key disponíveis no servidor."""
    return {
        "status": "success",
        "supported_algorithms": list(ALGORITHMS.keys()),
        "description": "Algoritmos matemáticos de desbloqueio de segurança (UDS Service 0x27)"
    }

@router.post("/calculate-key")
async def calculate_key_endpoint(
    algorithm: str = Form(...),
    seed_hex: str = Form(...),
    _: dict = Depends(verify_credentials)
):
    """Calcula a chave de segurança para um desafio recebido da ECU."""
    try:
        key = calculate_security_key(algorithm, seed_hex)
        return {
            "status": "success",
            "algorithm": algorithm,
            "seed": seed_hex,
            "key": key
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/prepare-package")
async def prepare_flasher_package(
    file: UploadFile = File(...),
    target_header: str = Form("7E0"),
    start_address: str = Form("0x00800000"),
    block_size: int = Form(1024),
    _: dict = Depends(verify_credentials)
):
    """
    Recebe o arquivo binário (.bin) de calibração/remap, valida checksum,
    e prepara a sequência completa de fatiamento UDS (0x34, 0x36, 0x37).
    """
    content = await file.read()
    total_size = len(content)
    
    if total_size == 0:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    
    # Validações de integridade
    md5_hash = hashlib.md5(content).hexdigest()
    sha256_hash = hashlib.sha256(content).hexdigest()
    crc32_val = zlib.crc32(content) & 0xFFFFFFFF
    
    addr_int = int(start_address, 16) if start_address.startswith("0x") else int(start_address)
    
    builder = UdsFlasherBuilder(target_ecu_header=target_header)
    
    session_step = builder.build_programming_session()
    seed_step = builder.build_request_seed(security_level=1)
    req_dl = builder.build_request_download(addr_int, total_size)
    blocks = builder.slice_into_transfer_blocks(content, block_size=block_size)
    exit_step = builder.build_transfer_exit()
    check_step = builder.build_checksum_routine(crc32_val)
    reset_step = builder.build_ecu_reset()
    
    return {
        "status": "success",
        "file_name": file.filename,
        "total_bytes": total_size,
        "total_blocks": len(blocks),
        "block_size": block_size,
        "hashes": {
            "md5": md5_hash,
            "sha256": sha256_hash,
            "crc32": f"0x{crc32_val:08X}"
        },
        "sequence_summary": [
            session_step["desc"],
            seed_step["desc"],
            req_dl["desc"],
            f"Fatiamento em {len(blocks)} blocos de dados (0x36)",
            exit_step["desc"],
            check_step["desc"],
            reset_step["desc"]
        ],
        "request_download_frame": req_dl,
        "first_block_preview": blocks[0] if blocks else None,
        "last_block_preview": blocks[-1] if blocks else None
    }
