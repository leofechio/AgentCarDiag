"""
honeypot_auth.py — Sistema Proprietário de Autenticação Multi-Box Honeypot Defense
AgentCarDiag Full-Stack Security Engine

Arquitetura de Defesa:
1. Multi-Box Honeypot: 5 caixas de entrada anônimas. Caixas 1 e 3 são armadilhas estritas.
2. Banimento Imediato de IP: Preenchimento de qualquer honeypot resulta em HTTP 403 e ban imediato.
3. Brute-Force Lockout: 3 falhas consecutivas nos campos válidos resultam em ban temporário (15 min).
4. Detecção Real de IP: Suporte a CF-Connecting-IP, X-Forwarded-For, X-Real-IP e socket direto.
5. Persistência Dupla: Registro em SQLite (tabela blocked_ips) e sincronização em arquivo JSON.
6. Suporte Multi-Usuário Dinâmico: Baseado no arquivo configurável usuarios.json com isolamento de diretórios.
"""

import hmac
import hashlib
import ipaddress
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from fastapi import Request, HTTPException, status
import aiosqlite

from app.config import (
    DB_PATH,
    USERS_CONFIG_PATH,
    BLOCKED_IPS_JSON_PATH,
    USER_FOLDERS_ROOT,
    HONEYPOT_LOCKOUT_SECONDS,
    HONEYPOT_BAN_SECONDS,
    MAX_AUTH_ATTEMPTS,
    SECRET_KEY,
    TRUSTED_PROXY_CIDRS,
)

logger = logging.getLogger("cardiag.security.honeypot")

# ─── Configuração Padrão Inicial de Usuários ──────────────────────────────────
# Credenciais reais devem residir apenas em server/data/usuarios.json (ignorado pelo Git)
DEFAULT_USERS_CONFIG: Dict[str, Any] = {}


# ─── Extração do IP Real do Cliente ───────────────────────────────────────────
def get_client_ip(request: Request) -> str:
    """
    Extrai o endereço IP real do cliente inspecionando cabeçalhos de proxy reverso
    e balanceadores de carga com prioridade de segurança.
    1. CF-Connecting-IP (Cloudflare)
    2. X-Forwarded-For (primeiro IP da cadeia de proxies)
    3. X-Real-IP
    4. Socket direto do cliente
    """
    peer = request.client.host if request.client and request.client.host else "127.0.0.1"
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        # Test clients and unusual ASGI transports may use a non-IP peer name.
        return peer

    # Forwarding headers are user-controlled unless the immediate peer is trusted.
    if not any(peer_ip in network for network in TRUSTED_PROXY_CIDRS):
        return str(peer_ip)

    def parse_ip(value: str):
        try:
            return ipaddress.ip_address(value.strip())
        except ValueError:
            return None

    cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if cf_ip and "," not in cf_ip:
        parsed = parse_ip(cf_ip)
        if parsed:
            return str(parsed)

    # Walk XFF from the trusted socket inward, skipping trusted proxy hops.
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        chain = [parse_ip(value) for value in xff.split(",")]
        if chain and all(chain):
            for address in reversed(chain):
                if not any(address in network for network in TRUSTED_PROXY_CIDRS):
                    return str(address)
            return str(chain[0])

    real_ip = parse_ip(request.headers.get("X-Real-IP", ""))
    if real_ip:
        return str(real_ip)
    return str(peer_ip)


# ─── Gerenciamento de Usuários (usuarios.json) ─────────────────────────────────
def load_users_config() -> Dict[str, Any]:
    """
    Carrega o arquivo usuarios.json. Se não existir, inicializa com o template padrão.
    """
    try:
        if not USERS_CONFIG_PATH.exists():
            USERS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(USERS_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_USERS_CONFIG, f, indent=2, ensure_ascii=False)
            logger.info(f"Arquivo usuarios.json criado em: {USERS_CONFIG_PATH}")
            return DEFAULT_USERS_CONFIG

        with open(USERS_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return DEFAULT_USERS_CONFIG
    except Exception as e:
        logger.error(f"Erro ao carregar usuarios.json: {e}")
        return DEFAULT_USERS_CONFIG


def get_user_folder(folder_name: str) -> Path:
    """Retorna o caminho seguro e isolado para o diretório de arquivos do usuário."""
    # Sanitiza o nome para prevenir Path Traversal
    safe_name = "".join(c for c in folder_name if c.isalnum() or c in ("-", "_")).strip()
    if not safe_name:
        safe_name = "default_user_folder"
    user_dir = USER_FOLDERS_ROOT / safe_name
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


# ─── Persistência Dupla de Bloqueios (SQLite + JSON) ───────────────────────────
async def sync_blocked_ips_to_json(conn: aiosqlite.Connection) -> None:
    """Exporta os bloqueios ativos do banco SQLite para o arquivo JSON sincronizado."""
    try:
        now = int(time.time())
        async with conn.execute(
            "SELECT ip, blocked_at, reason, expires_at, attempts, last_attempt_at FROM blocked_ips"
        ) as cur:
            rows = await cur.fetchall()

        data = {}
        for row in rows:
            ip, blocked_at, reason, expires_at, attempts, last_attempt_at = row
            data[ip] = {
                "ip": ip,
                "blocked_at": blocked_at,
                "reason": reason,
                "expires_at": expires_at,
                "is_active": expires_at > now,
                "attempts": attempts,
                "last_attempt_at": last_attempt_at
            }

        BLOCKED_IPS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(BLOCKED_IPS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Erro ao sincronizar blocked_ips.json: {e}")


async def check_ip_blocked(ip: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Verifica se o IP está com bloqueio ativo.
    Retorna (is_blocked, detalhes_do_bloqueio).
    Se o bloqueio tiver expirado, limpa o bloqueio do IP.
    """
    now = int(time.time())
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT ip, blocked_at, reason, expires_at, attempts, last_attempt_at FROM blocked_ips WHERE ip = ?",
                (ip,)
            ) as cur:
                row = await cur.fetchone()

            if not row:
                return False, None

            ip_val, blocked_at, reason, expires_at, attempts, last_attempt = row
            if expires_at > 0:
                if expires_at > now:
                    remaining = expires_at - now
                    return True, {
                        "ip": ip_val,
                        "blocked_at": blocked_at,
                        "reason": reason,
                        "expires_at": expires_at,
                        "remaining_seconds": remaining,
                        "attempts": attempts
                    }
                else:
                    # Ban expirou: zera o bloqueio e contador
                    await db.execute(
                        "UPDATE blocked_ips SET expires_at = 0, attempts = 0, reason = 'EXPIRED' WHERE ip = ?",
                        (ip,)
                    )
                    await db.commit()
                    await sync_blocked_ips_to_json(db)
                    return False, None
            else:
                # Não está banido. Zera attempts apenas se a janela de 15 minutos expirou
                if attempts > 0 and (now - last_attempt > HONEYPOT_LOCKOUT_SECONDS):
                    await db.execute(
                        "UPDATE blocked_ips SET attempts = 0 WHERE ip = ?",
                        (ip,)
                    )
                    await db.commit()
                    await sync_blocked_ips_to_json(db)
                return False, None
    except Exception as e:
        logger.error(f"Erro ao verificar IP bloqueado ({ip}): {e}")
        return False, None


async def block_client_ip(ip: str, reason: str, duration_seconds: int) -> Dict[str, Any]:
    """
    Bloqueia imediatamente o IP pelo período especificado.
    Salva no SQLite e sincroniza no arquivo JSON.
    """
    now = int(time.time())
    expires_at = now + duration_seconds
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO blocked_ips (ip, blocked_at, reason, expires_at, attempts, last_attempt_at)
                VALUES (?, ?, ?, ?, 3, ?)
                ON CONFLICT(ip) DO UPDATE SET
                    blocked_at = excluded.blocked_at,
                    reason = excluded.reason,
                    expires_at = excluded.expires_at,
                    attempts = excluded.attempts,
                    last_attempt_at = excluded.last_attempt_at
                """,
                (ip, now_iso, reason, expires_at, now)
            )
            await db.commit()
            await sync_blocked_ips_to_json(db)

        logger.warning(f"🚨 [DEFENSE ALERT] IP {ip} BLOQUEADO! Motivo: {reason}. Duração: {duration_seconds}s (Expira em: {expires_at})")
        return {
            "ip": ip,
            "blocked_at": now_iso,
            "reason": reason,
            "expires_at": expires_at,
            "duration_seconds": duration_seconds
        }
    except Exception as e:
        logger.error(f"Erro ao bloquear IP no banco ({ip}): {e}")
        return {"ip": ip, "reason": reason, "expires_at": expires_at}


async def register_failed_attempt(ip: str) -> Tuple[int, bool]:
    """
    Registra tentativa de login com credenciais incorretas (sem acionamento de honeypot).
    Implementa Brute-Force Lockout com janela de tempo:
    - Retorna (total_tentativas, foi_bloqueado).
    - Na 3ª falha consecutiva, aplica quarentena de 15 minutos (900s).
    """
    now = int(time.time())
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT attempts, last_attempt_at, expires_at FROM blocked_ips WHERE ip = ?",
                (ip,)
            ) as cur:
                row = await cur.fetchone()

            if row:
                prev_attempts, last_attempt, expires_at = row
                # Janela de tempo de 15 min: se a última tentativa for muito antiga, reinicia contagem
                if now - last_attempt > HONEYPOT_LOCKOUT_SECONDS:
                    current_attempts = 1
                else:
                    current_attempts = prev_attempts + 1
            else:
                current_attempts = 1

            if current_attempts >= MAX_AUTH_ATTEMPTS:
                # Dispara lockout temporário de 15 minutos
                ban_duration = HONEYPOT_LOCKOUT_SECONDS
                expires_at = now + ban_duration
                reason = f"BRUTE_FORCE_LOCKOUT: {MAX_AUTH_ATTEMPTS} falhas consecutivas de autenticação."
                await db.execute(
                    """
                    INSERT INTO blocked_ips (ip, blocked_at, reason, expires_at, attempts, last_attempt_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ip) DO UPDATE SET
                        blocked_at = excluded.blocked_at,
                        reason = excluded.reason,
                        expires_at = excluded.expires_at,
                        attempts = excluded.attempts,
                        last_attempt_at = excluded.last_attempt_at
                    """,
                    (ip, now_iso, reason, expires_at, current_attempts, now)
                )
                await db.commit()
                await sync_blocked_ips_to_json(db)
                logger.warning(f"⛔ [BRUTE FORCE] IP {ip} excedeu {MAX_AUTH_ATTEMPTS} tentativas. Ban de {ban_duration}s aplicado.")
                return current_attempts, True
            else:
                # Apenas incrementa contador
                await db.execute(
                    """
                    INSERT INTO blocked_ips (ip, blocked_at, reason, expires_at, attempts, last_attempt_at)
                    VALUES (?, ?, 'LOGIN_FAILED', 0, ?, ?)
                    ON CONFLICT(ip) DO UPDATE SET
                        attempts = excluded.attempts,
                        last_attempt_at = excluded.last_attempt_at
                    """,
                    (ip, now_iso, current_attempts, now)
                )
                await db.commit()
                await sync_blocked_ips_to_json(db)
                return current_attempts, False
    except Exception as e:
        logger.error(f"Erro ao registrar falha para IP {ip}: {e}")
        return 1, False


async def reset_failed_attempts(ip: str) -> None:
    """Zera o contador de falhas e desbloqueia caso o login seja realizado com sucesso."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE blocked_ips SET attempts = 0, expires_at = 0, reason = 'AUTHENTICATED' WHERE ip = ?",
                (ip,)
            )
            await db.commit()
            await sync_blocked_ips_to_json(db)
    except Exception as e:
        logger.error(f"Erro ao resetar tentativas para IP {ip}: {e}")


async def unblock_ip_manual(ip: str) -> bool:
    """Desbloqueia manualmente um IP."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM blocked_ips WHERE ip = ?", (ip,))
            await db.commit()
            await sync_blocked_ips_to_json(db)
        logger.info(f"IP {ip} desbloqueado manualmente com sucesso.")
        return True
    except Exception as e:
        logger.error(f"Erro ao desbloquear IP {ip}: {e}")
        return False


async def get_all_blocked_ips() -> List[Dict[str, Any]]:
    """Retorna lista de todos os registros de IPs bloqueados ou com falhas."""
    try:
        now = int(time.time())
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT ip, blocked_at, reason, expires_at, attempts, last_attempt_at FROM blocked_ips ORDER BY last_attempt_at DESC"
            ) as cur:
                rows = await cur.fetchall()

        results = []
        for row in rows:
            ip, blocked_at, reason, expires_at, attempts, last_attempt_at = row
            results.append({
                "ip": ip,
                "blocked_at": blocked_at,
                "reason": reason,
                "expires_at": expires_at,
                "is_active": expires_at > now,
                "remaining_seconds": max(0, expires_at - now),
                "attempts": attempts,
                "last_attempt_at": last_attempt_at
            })
        return results
    except Exception as e:
        logger.error(f"Erro ao listar blocked_ips: {e}")
        return []


# ─── Sessão Segura e Assinatura Criptográfica de Tokens ─────────────────────────
SESSION_COOKIE_NAME = "cardiag_stealth_session"

def create_session_token(username: str, folder: str) -> str:
    """Gera um token de sessão com assinatura HMAC-SHA256 à prova de adulteração."""
    timestamp = int(time.time())
    payload = f"{username}:{folder}:{timestamp}"
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return f"{payload}:{signature}"


def verify_session_token(token: str) -> Optional[Dict[str, Any]]:
    """Valida a integridade e expiração do token de sessão."""
    try:
        parts = token.split(":")
        if len(parts) != 4:
            return None
        username, folder, timestamp_str, signature = parts
        timestamp = int(timestamp_str)

        # Sessão de 24 horas
        if time.time() - timestamp > 86400:
            return None

        payload = f"{username}:{folder}:{timestamp_str}"
        expected_sig = hmac.new(
            SECRET_KEY.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        if secrets.compare_digest(signature, expected_sig):
            return {
                "username": username,
                "folder": folder,
                "created_at": timestamp
            }
        return None
    except Exception:
        return None


# ─── Agente Porteiro: Validação por Matriz Dinâmica de Assinaturas ────────────
async def validate_multi_box_credentials(boxes: List[str], client_ip: str) -> Dict[str, Any]:
    """
    Agente Porteiro — Matriz Dinâmica Multidimensional (5 Linhas por Coluna):
    
    1. Regra da Quantidade Estrita:
       - Deve ter exatamente 3 caixas preenchidas com pelo menos 1 caractere.
       - Se vier apenas 1, 2, 4 ou 5 caixas -> Bloqueio imediato do IP (HTTP 403 Forbidden).

    2. Regra da Assinatura de Posição (Linhas Válidas na Matriz):
       - Identifica o padrão de 3 linhas ativas digitadas (ex: Linhas 1, 3 e 4).
       - Verifica se existe pelo menos um usuário cadastrado na matriz com essa exata combinação.
       - Se NENHUM usuário utilizar essa combinação de 3 linhas -> Bloqueio imediato do IP (HTTP 403 Forbidden).

    3. Regra de Conteúdo vs Tolerância de Digitação:
       - Para os usuários que possuem essa exata assinatura de linhas:
         - Confere o conteúdo digitado nas 3 posições usando secrets.compare_digest.
         - Se coincidir com algum usuário -> Acesso concedido! Zera falhas anteriores.
         - Se as posições estiverem corretas, mas o conteúdo digitado estiver incoerente:
           -> Trata como humano que errou digitação: permite até 3 tentativas.
           -> Na 3ª falha consecutiva: Bloqueio do IP por 15 minutos (Quarentena / HTTP 403 Forbidden).
    """
    if len(boxes) != 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Estrutura de dados inválida."
        )

    # Identifica as posições ativas (linhas preenchidas com pelo menos 1 caractere)
    active_indices = tuple(i for i, val in enumerate(boxes) if val is not None and str(val).strip() != "")

    # 1. Regra da Quantidade Estrita: Exatamente 3 caixas devem conter dados
    if len(active_indices) != 3:
        reason = f"QUANTITY_VIOLATION_TRAP: Foram preenchidas {len(active_indices)} caixas. O sistema exige exatamente 3 caixas."
        await block_client_ip(client_ip, reason, HONEYPOT_BAN_SECONDS)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso Negado. Sistema de defesa acionado."
        )

    # 2. Carrega usuários dinâmicos (Colunas da Matriz)
    users = load_users_config()

    # Filtra as colunas (usuários) cuja assinatura de linhas ativas coincide com o trio digitado
    matching_pattern_users = {}
    for uname, udata in users.items():
        expected_boxes = udata.get("boxes", [])
        if len(expected_boxes) != 5:
            continue
        user_active = tuple(i for i, val in enumerate(expected_boxes) if val is not None and str(val).strip() != "")
        if user_active == active_indices:
            matching_pattern_users[uname] = udata

    # Se NENHUM usuário no sistema utiliza essa combinação de 3 linhas -> Ban imediato
    if not matching_pattern_users:
        readable_lines = [i + 1 for i in active_indices]
        reason = f"INVALID_PATTERN_TRAP: Combinação de linhas {readable_lines} não corresponde a nenhum usuário cadastrado."
        await block_client_ip(client_ip, reason, HONEYPOT_BAN_SECONDS)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso Negado. Sistema de defesa acionado."
        )

    # 3. Regra de Conteúdo: Linhas corretas, agora valida o texto digitado
    authenticated_user = None
    user_info = None

    for uname, udata in matching_pattern_users.items():
        expected_boxes = udata["boxes"]
        match_all = True
        for i in active_indices:
            exp = str(expected_boxes[i])
            act = str(boxes[i])
            if not secrets.compare_digest(act.encode("utf-8"), exp.encode("utf-8")):
                match_all = False
                break

        if match_all:
            authenticated_user = uname
            user_info = udata
            break

    # Sucesso Total
    if authenticated_user and user_info:
        await reset_failed_attempts(client_ip)
        folder_name = user_info.get("folder", f"pasta_{authenticated_user}")
        user_folder = get_user_folder(folder_name)
        session_token = create_session_token(authenticated_user, folder_name)

        logger.info(f"✅ [PORTEIRO] Acesso autorizado para '{authenticated_user}' [IP: {client_ip}]. Pasta: {folder_name}")
        return {
            "status": "success",
            "username": authenticated_user,
            "folder": folder_name,
            "folder_path": str(user_folder),
            "session_token": session_token,
            "message": "Autenticação autorizada."
        }

    # Falha de digitação nas linhas corretas (Tolerância humana de até 3 tentativas)
    attempts, is_blocked = await register_failed_attempt(client_ip)
    if is_blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso bloqueado por 15 minutos devido a 3 tentativas incorretas consecutivas."
        )

    remaining = max(0, MAX_AUTH_ATTEMPTS - attempts)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Credenciais incorretas. Tentativas restantes antes do bloqueio: {remaining}."
    )
