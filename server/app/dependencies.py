"""
dependencies.py — Injeção de Dependências e Autenticação Compartilhada
AgentCarDiag Server
"""

import secrets
import logging
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import ADMIN_USER, ADMIN_PASSWORD
from app.database import get_db
from app.security.honeypot_auth import SESSION_COOKIE_NAME, verify_session_token

logger = logging.getLogger("cardiag.auth")
security = HTTPBasic(auto_error=False)


async def verify_credentials(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security)
) -> dict:
    """
    Verifica as credenciais do usuário.
    1. Sessão Segura Honeypot Stealth (via Cookie HTTPOnly ou Bearer Token).
    2. Super Admin (Fábrica / Linha de Produção via Basic Auth).
    3. Oficinas Clientes cadastradas no banco de dados SQLite.
    """
    # 1. Verifica Cookie ou Header de Sessão Stealth
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "").strip()

    if token:
        session_data = verify_session_token(token)
        if session_data:
            uname = session_data["username"]
            folder = session_data.get("folder", f"pasta_{uname}")
            is_adm = (uname == ADMIN_USER or uname == "admin")
            return {
                "username": uname,
                "is_admin": is_adm,
                "workshop_id": folder,
                "name": uname.capitalize(),
                "folder": folder
            }

    # 2. Basic Auth (Fallback para dispositivos de bancada e nós ESP32)
    if credentials:
        # Master Admin
        if secrets.compare_digest(credentials.username, ADMIN_USER) and secrets.compare_digest(credentials.password, ADMIN_PASSWORD):
            return {
                "username": ADMIN_USER,
                "is_admin": True,
                "workshop_id": "oficina-matriz",
                "name": "Administrador Geral"
            }

        # Oficinas Clientes
        async with get_db() as db_conn:
            async with db_conn.execute(
                "SELECT id, name, username, password_hash, status FROM workshops WHERE username = ? OR id = ?",
                (credentials.username.strip(), credentials.username.strip().lower())
            ) as cur:
                row = await cur.fetchone()
                if row:
                    w_id, w_name, w_user, w_pass, w_status = row
                    if w_status == "BLOCKED":
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Conta de oficina suspensa ou bloqueada. Contate o suporte da fábrica."
                        )
                    if secrets.compare_digest(credentials.password, w_pass or "123456"):
                        return {
                            "username": w_user or w_id,
                            "is_admin": False,
                            "workshop_id": w_id,
                            "name": w_name
                        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Acesso não autorizado. Efetue login.",
        headers={"WWW-Authenticate": "Basic"},
    )


def verify_admin_only(auth_data: dict = Depends(verify_credentials)) -> dict:
    """Exige privilégios de administrador da fábrica."""
    if not auth_data.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado. Esta área é restrita aos administradores e engenheiros da fábrica."
        )
    return auth_data
