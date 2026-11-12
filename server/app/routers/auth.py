"""
auth.py — Router de Autenticação Multi-Box Honeypot Defense
AgentCarDiag Security Subsystem
"""

import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Request, Response, HTTPException, status, Depends

from app.security.honeypot_auth import (
    get_client_ip,
    check_ip_blocked,
    validate_multi_box_credentials,
    SESSION_COOKIE_NAME,
    verify_session_token,
    unblock_ip_manual,
    get_all_blocked_ips,
    load_users_config
)
from app.dependencies import verify_admin_only

logger = logging.getLogger("cardiag.routers.auth")
router = APIRouter(prefix="/api/auth", tags=["Honeypot Authentication"])


class MultiBoxLoginPayload(BaseModel):
    boxes: List[str] = Field(
        ...,
        description="Array exato de 5 posições de caixas para o Multi-Box Honeypot Defense.",
        min_items=5,
        max_items=5
    )


class UnblockIPPayload(BaseModel):
    ip: str = Field(..., description="Endereço IP para desbloqueio manual.")


@router.post("/login")
async def login_multi_box(
    payload: MultiBoxLoginPayload,
    request: Request,
    response: Response
):
    """
    Processa a submissão assíncrona das 5 caixas de entrada.
    Aplica Honeypot Trap, Brute-Force Lockout e autenticação dinâmica.
    """
    client_ip = get_client_ip(request)

    # 1. Verifica se o IP do cliente já está bloqueado
    is_blocked, block_details = await check_ip_blocked(client_ip)
    if is_blocked and block_details:
        rem_sec = block_details.get("remaining_seconds", 0)
        rem_min = max(1, rem_sec // 60)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Seu endereço IP ({client_ip}) está bloqueado. Tempo restante: {rem_min} minuto(s). Motivo: {block_details.get('reason')}"
        )

    # 2. Executa a validação das 5 caixas
    result = await validate_multi_box_credentials(payload.boxes, client_ip)

    # 3. Define Cookie HTTPOnly de Sessão
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=result["session_token"],
        httponly=True,
        samesite="lax",
        secure=False,  # Permite HTTP em rede local da oficina / HTTPS em produção
        max_age=86400  # 24 horas
    )

    return {
        "status": "ok",
        "user": result["username"],
        "folder": result["folder"],
        "token": result["session_token"],
        "redirect": "/",
        "message": "Autenticação realizada com sucesso."
    }


@router.get("/status")
async def get_auth_status(request: Request):
    """
    Retorna o status atual da sessão e do IP do requisitante.
    """
    client_ip = get_client_ip(request)
    is_blocked, block_details = await check_ip_blocked(client_ip)

    # Verifica token via Cookie ou Header Authorization
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "").strip()

    session_data = verify_session_token(token) if token else None

    return {
        "client_ip": client_ip,
        "is_blocked": is_blocked,
        "block_details": block_details,
        "authenticated": session_data is not None,
        "user": session_data.get("username") if session_data else None,
        "folder": session_data.get("folder") if session_data else None
    }


@router.post("/logout")
async def logout(response: Response):
    """Encerra a sessão e expira o cookie de autenticação."""
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return {"status": "ok", "message": "Sessão encerrada com sucesso."}


@router.get("/blocked-ips")
async def list_blocked_ips_endpoint(admin_data: dict = Depends(verify_admin_only)):
    """Lista todos os IPs bloqueados (Restrito ao Administrador)."""
    blocked_list = await get_all_blocked_ips()
    return {"total": len(blocked_list), "blocked_ips": blocked_list}


@router.post("/unblock-ip")
async def unblock_ip_endpoint(
    payload: UnblockIPPayload,
    admin_data: dict = Depends(verify_admin_only)
):
    """Desbloqueia manualmente um IP (Restrito ao Administrador)."""
    success = await unblock_ip_manual(payload.ip)
    if success:
        return {"status": "ok", "message": f"IP {payload.ip} desbloqueado com sucesso."}
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Não foi possível desbloquear o IP {payload.ip}."
    )
