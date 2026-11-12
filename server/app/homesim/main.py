import os
import json
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .database import init_db, get_db_connection, extract_otp_code
from .telegram_notifier import send_telegram_sms_alert, send_telegram_device_alert
from .crypto import decrypt_payload
from .auth import hash_password, verify_password, create_session_token, verify_session_token

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="HomeSIM Server", version="1.0.0", lifespan=lifespan)
router = APIRouter()

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                dead_connections.append(connection)
        for dead in dead_connections:
            self.disconnect(dead)

ws_manager = ConnectionManager()

# Pydantic Models
class TelemetryPayload(BaseModel):
    device_id: str
    device_name: str
    carrier_name: Optional[str] = "Desconhecida"
    signal_strength_dbm: Optional[int] = -999
    signal_level: Optional[int] = 0  # 0 to 4
    battery_level: int
    is_charging: bool
    battery_temp: Optional[float] = 25.0
    wifi_ssid: Optional[str] = "Desconectado"
    wifi_ip: Optional[str] = "127.0.0.1"
    app_version: Optional[str] = "1.0.0"

class SmsPayload(BaseModel):
    device_id: str
    sender: Optional[str] = "Desconhecido"
    body: Optional[str] = ""
    timestamp: Optional[str] = None
    encrypted: Optional[bool] = False
    encrypted_payload: Optional[str] = None

class CallPayload(BaseModel):
    device_id: str
    number: Optional[str] = "Número Privado"
    caller_name: Optional[str] = ""
    call_type: Optional[str] = "missed"  # missed, incoming, rejected, outgoing
    duration_seconds: Optional[int] = 0
    timestamp: Optional[str] = None
    encrypted: Optional[bool] = False
    encrypted_payload: Optional[str] = None

class RegisterPayload(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = ""

class LoginPayload(BaseModel):
    email: str
    password: str

class PairConfirmPayload(BaseModel):
    token: str
    device_id: str
    device_name: str

class SettingsPayload(BaseModel):
    telegram_bot_token: Optional[str] = ""
    telegram_chat_id: Optional[str] = ""
    e2ee_secret_key: Optional[str] = ""
    offline_alert_minutes: Optional[int] = 30
    battery_low_alert: Optional[int] = 20

# Endpoints de Autenticação e Multi-Tenancy
@router.post("/api/auth/register")
async def auth_register(payload: RegisterPayload):
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="E-mail inválido")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="A senha deve ter pelo menos 6 caracteres")

    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT id FROM users WHERE email = ?", (email,))
        if await cursor.fetchone():
            raise HTTPException(status_code=400, detail="Este e-mail já está cadastrado")

        pwd_hash = hash_password(payload.password)
        now = datetime.now(timezone.utc).isoformat()
        cursor = await db.execute("""
            INSERT INTO users (email, password_hash, full_name, plan_tier, created_at)
            VALUES (?, ?, ?, 'trial', ?)
        """, (email, pwd_hash, payload.full_name or "", now))
        await db.commit()
        user_id = cursor.lastrowid
        token = create_session_token(user_id, email)
        return {
            "status": "ok",
            "token": token,
            "user": {"id": user_id, "email": email, "full_name": payload.full_name, "plan_tier": "trial"}
        }
    finally:
        await db.close()

@router.post("/api/auth/login")
async def auth_login(payload: LoginPayload):
    email = payload.email.strip().lower()
    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT id, email, password_hash, full_name, plan_tier FROM users WHERE email = ?", (email,))
        row = await cursor.fetchone()
        if not row or not verify_password(payload.password, row[2]):
            raise HTTPException(status_code=401, detail="E-mail ou senha incorretos")

        user_id = row[0]
        token = create_session_token(user_id, email)
        return {
            "status": "ok",
            "token": token,
            "user": {"id": user_id, "email": row[1], "full_name": row[3], "plan_tier": row[4]}
        }
    finally:
        await db.close()

@router.get("/api/auth/me")
async def auth_me(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Não autenticado")
    token = authorization.split(" ")[1]
    payload = verify_session_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token expirado ou inválido")

    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT id, email, full_name, plan_tier, created_at FROM users WHERE id = ?", (payload["uid"],))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        return {
            "id": row[0],
            "email": row[1],
            "full_name": row[2],
            "plan_tier": row[3],
            "created_at": row[4]
        }
    finally:
        await db.close()

# Pareamento Seguro por QR Code
@router.post("/api/devices/pair-token")
async def generate_pair_token(authorization: Optional[str] = Header(None)):
    user_id = 1 # Fallback padrão se não autenticado
    if authorization and authorization.startswith("Bearer "):
        p = verify_session_token(authorization.split(" ")[1])
        if p:
            user_id = p["uid"]

    import secrets
    import time
    pair_token = "hs_pair_" + secrets.token_hex(12)
    expires_at = int(time.time()) + 900 # Válido por 15 minutos

    db = await get_db_connection()
    try:
        await db.execute("""
            INSERT INTO pairing_tokens (token, user_id, expires_at)
            VALUES (?, ?, ?)
        """, (pair_token, user_id, expires_at))
        await db.commit()
        return {
            "token": pair_token,
            "expires_in_seconds": 900
        }
    finally:
        await db.close()

@router.post("/api/devices/pair-confirm")
async def confirm_pairing(payload: PairConfirmPayload):
    import time
    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT user_id, expires_at, used_at FROM pairing_tokens WHERE token = ?", (payload.token,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Código de pareamento inválido")
        if row[1] < time.time():
            raise HTTPException(status_code=400, detail="Código de pareamento expirado. Gere um novo no painel.")
        
        user_id = row[0]
        now = datetime.now(timezone.utc).isoformat()
        
        # Marca token como usado
        await db.execute("UPDATE pairing_tokens SET used_at = ? WHERE token = ?", (now, payload.token))
        
        # Garante que o dispositivo fica vinculado ao usuário
        await db.execute("""
            UPDATE devices SET user_id = ? WHERE id = ?
        """, (user_id, payload.device_id))
        
        await db.commit()
        return {
            "status": "ok",
            "message": "Aparelho pareado com sucesso!",
            "user_id": user_id,
            "device_id": payload.device_id
        }
    finally:
        await db.close()

# Endpoints
@router.post("/api/telemetry")
async def receive_telemetry(payload: TelemetryPayload):
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db_connection()
    try:
        # Atualiza ou insere dispositivo
        await db.execute("""
            INSERT INTO devices (
                id, name, carrier_name, signal_strength_dbm, signal_level, 
                battery_level, is_charging, battery_temp, wifi_ssid, wifi_ip, 
                app_version, last_seen, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                carrier_name=excluded.carrier_name,
                signal_strength_dbm=excluded.signal_strength_dbm,
                signal_level=excluded.signal_level,
                battery_level=excluded.battery_level,
                is_charging=excluded.is_charging,
                battery_temp=excluded.battery_temp,
                wifi_ssid=excluded.wifi_ssid,
                wifi_ip=excluded.wifi_ip,
                app_version=excluded.app_version,
                last_seen=excluded.last_seen
        """, (
            payload.device_id, payload.device_name, payload.carrier_name,
            payload.signal_strength_dbm, payload.signal_level, payload.battery_level,
            1 if payload.is_charging else 0, payload.battery_temp,
            payload.wifi_ssid, payload.wifi_ip, payload.app_version, now, now
        ))
        
        # Histórico de telemetria
        await db.execute("""
            INSERT INTO telemetry_history (device_id, battery_level, is_charging, battery_temp, signal_level, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            payload.device_id, payload.battery_level, 1 if payload.is_charging else 0,
            payload.battery_temp, payload.signal_level, now
        ))
        await db.commit()
    finally:
        await db.close()

    # Transmite para o dashboard via WebSocket
    event_data = {
        "event": "telemetry_update",
        "data": {
            **payload.model_dump(),
            "last_seen": now
        }
    }
    await ws_manager.broadcast(event_data)
    return {"status": "ok", "timestamp": now}

@router.post("/api/sms")
async def receive_sms(payload: SmsPayload):
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db_connection()
    device_name = "HomeSIM Device"
    
    sender = payload.sender or "Desconhecido"
    body = payload.body or ""

    try:
        # Recupera configurações
        cursor = await db.execute("SELECT key, value FROM settings WHERE key IN ('telegram_bot_token', 'telegram_chat_id', 'e2ee_secret_key')")
        settings_rows = await cursor.fetchall()
        settings_dict = {r[0]: r[1] for r in settings_rows}

        cursor = await db.execute("SELECT name FROM devices WHERE id = ?", (payload.device_id,))
        row = await cursor.fetchone()
        if row:
            device_name = row[0]

        # Se veio cifrado via E2EE
        if payload.encrypted and payload.encrypted_payload:
            secret = settings_dict.get("e2ee_secret_key", "")
            if not secret:
                # Fallback carregado via variável de ambiente (server/.env)
                secret = os.environ.get("HOMESIM_E2EE_FALLBACK_SECRET", "")
            try:
                decrypted = decrypt_payload(payload.encrypted_payload, secret)
                sender = decrypted.get("sender", sender)
                body = decrypted.get("body", body)
            except Exception as e:
                return JSONResponse({"status": "error", "message": f"Falha na decriptação E2EE: {str(e)}"}, status_code=400)

        otp_code = extract_otp_code(body)
            
        cursor = await db.execute("""
            INSERT INTO sms_messages (device_id, sender, body, otp_code, received_at, is_read)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (payload.device_id, sender, body, otp_code, now))
        sms_id = cursor.lastrowid
        
        await db.commit()
    finally:
        await db.close()

    # Dispara alerta Telegram em background
    tg_token = settings_dict.get("telegram_bot_token")
    tg_chat = settings_dict.get("telegram_chat_id")
    if tg_token and tg_chat:
        asyncio.create_task(send_telegram_sms_alert(
            bot_token=tg_token,
            chat_id=tg_chat,
            sender=sender,
            body=body,
            otp_code=otp_code,
            device_name=device_name
        ))

    # Transmite para os navegadores conectados
    sms_event = {
        "event": "new_sms",
        "data": {
            "id": sms_id,
            "device_id": payload.device_id,
            "device_name": device_name,
            "sender": sender,
            "body": body,
            "otp_code": otp_code,
            "received_at": now
        }
    }
    await ws_manager.broadcast(sms_event)
    return {"status": "ok", "sms_id": sms_id, "otp_code": otp_code}

@router.post("/api/calls")
async def receive_call(payload: CallPayload):
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db_connection()
    device_name = "HomeSIM Device"
    number = payload.number or "Privado"
    caller_name = payload.caller_name or ""
    call_type = payload.call_type or "missed"
    duration = payload.duration_seconds or 0
    received_at = payload.timestamp or now

    try:
        cursor = await db.execute("SELECT key, value FROM settings WHERE key IN ('telegram_bot_token', 'telegram_chat_id', 'e2ee_secret_key')")
        settings_rows = await cursor.fetchall()
        settings_dict = {r[0]: r[1] for r in settings_rows}

        cursor = await db.execute("SELECT name FROM devices WHERE id = ?", (payload.device_id,))
        row = await cursor.fetchone()
        if row:
            device_name = row[0]

        if payload.encrypted and payload.encrypted_payload:
            secret = settings_dict.get("e2ee_secret_key", "") or "homesim_default_secret"
            try:
                decrypted = decrypt_payload(payload.encrypted_payload, secret)
                number = decrypted.get("number", number)
                caller_name = decrypted.get("caller_name", caller_name)
                call_type = decrypted.get("call_type", call_type)
                duration = decrypted.get("duration_seconds", duration)
                received_at = decrypted.get("timestamp", received_at)
            except Exception as e:
                return JSONResponse({"status": "error", "message": f"Erro E2EE na chamada: {str(e)}"}, status_code=400)

        cursor = await db.execute("""
            INSERT INTO call_logs (device_id, number, caller_name, call_type, duration_seconds, received_at, is_read)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        """, (payload.device_id, number, caller_name, call_type, duration, received_at))
        call_id = cursor.lastrowid
        await db.commit()
    finally:
        await db.close()

    call_event = {
        "event": "new_call",
        "data": {
            "id": call_id,
            "device_id": payload.device_id,
            "device_name": device_name,
            "number": number,
            "caller_name": caller_name,
            "call_type": call_type,
            "duration_seconds": duration,
            "received_at": received_at
        }
    }
    await ws_manager.broadcast(call_event)
    return {"status": "ok", "call_id": call_id}

@router.get("/api/calls")
async def list_calls(limit: int = 50):
    db = await get_db_connection()
    try:
        cursor = await db.execute("""
            SELECT c.id, c.device_id, d.name as device_name, c.number, c.caller_name, c.call_type, c.duration_seconds, c.received_at, c.is_read
            FROM call_logs c
            LEFT JOIN devices d ON c.device_id = d.id
            ORDER BY c.id DESC LIMIT ?
        """, (limit,))
        columns = [col[0] for col in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        await db.close()

@router.get("/api/devices")
async def list_devices():
    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT * FROM devices ORDER BY last_seen DESC")
        columns = [col[0] for col in cursor.description]
        rows = await cursor.fetchall()
        devices = [dict(zip(columns, row)) for row in rows]
        return devices
    finally:
        await db.close()

@router.get("/api/devices/{device_id}/history")
async def get_device_history(device_id: str, limit: int = 50):
    db = await get_db_connection()
    try:
        cursor = await db.execute("""
            SELECT battery_level, is_charging, battery_temp, signal_level, created_at 
            FROM telemetry_history 
            WHERE device_id = ? 
            ORDER BY id DESC LIMIT ?
        """, (device_id, limit))
        rows = await cursor.fetchall()
        return [
            {
                "battery_level": r[0],
                "is_charging": bool(r[1]),
                "battery_temp": r[2],
                "signal_level": r[3],
                "created_at": r[4]
            }
            for r in reversed(rows)
        ]
    finally:
        await db.close()

@router.get("/api/sms")
async def list_sms(limit: int = 100):
    db = await get_db_connection()
    try:
        cursor = await db.execute("""
            SELECT s.id, s.device_id, d.name as device_name, s.sender, s.body, s.otp_code, s.received_at, s.is_read
            FROM sms_messages s
            LEFT JOIN devices d ON s.device_id = d.id
            ORDER BY s.id DESC LIMIT ?
        """, (limit,))
        columns = [col[0] for col in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        await db.close()

@router.get("/api/settings")
async def get_settings():
    db = await get_db_connection()
    try:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        await db.close()

@router.post("/api/settings")
async def update_settings(settings: SettingsPayload):
    db = await get_db_connection()
    try:
        items = [
            ("telegram_bot_token", settings.telegram_bot_token or ""),
            ("telegram_chat_id", settings.telegram_chat_id or ""),
            ("e2ee_secret_key", settings.e2ee_secret_key or ""),
            ("offline_alert_minutes", str(settings.offline_alert_minutes or 30)),
            ("battery_low_alert", str(settings.battery_low_alert or 20))
        ]
        for key, val in items:
            await db.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """, (key, val))
        await db.commit()
        return {"status": "ok"}
    finally:
        await db.close()

@router.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Mantém vivo e recebe mensagens de ping
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

# Servir arquivos estáticos do Dashboard Web
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
@app.get("")
async def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse({"status": "HomeSIM Server Rodando"})

app.include_router(router)

# Exporta explicitamente como sub-aplicação ASGI
homesim_app = app
