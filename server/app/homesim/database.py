import aiosqlite
import os
import re
from datetime import datetime

# Banco SQLite isolado no volume de dados persistentes (/app/data/homesim.db)
DB_PATH = os.environ.get("HOMESIM_DB_PATH", "/app/data/homesim.db")

async def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                api_key TEXT,
                carrier_name TEXT,
                signal_strength_dbm INTEGER,
                signal_level INTEGER,
                battery_level INTEGER,
                is_charging INTEGER,
                battery_temp REAL,
                wifi_ssid TEXT,
                wifi_ip TEXT,
                app_version TEXT,
                last_seen TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS telemetry_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                battery_level INTEGER,
                is_charging INTEGER,
                battery_temp REAL,
                signal_level INTEGER,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sms_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                body TEXT NOT NULL,
                otp_code TEXT,
                received_at TEXT,
                is_read INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS call_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                number TEXT NOT NULL,
                caller_name TEXT,
                call_type TEXT NOT NULL,
                duration_seconds INTEGER DEFAULT 0,
                received_at TEXT NOT NULL,
                is_read INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                plan_tier TEXT DEFAULT 'trial',
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pairing_tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                used_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Migração idempotente: adiciona user_id em devices se não existir
        cursor = await db.execute("PRAGMA table_info(devices)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "user_id" not in columns:
            try:
                await db.execute("ALTER TABLE devices ADD COLUMN user_id INTEGER DEFAULT 1")
            except Exception:
                pass
        await db.commit()

def extract_otp_code(text: str) -> str:
    """Extrai códigos de verificação 2FA (4 a 8 dígitos/letras comumente usados por bancos, gov.br, whatsapp, etc.)"""
    # 1. Padrão hifenizado estilo WhatsApp / Google (ex: "772-910" ou "G-123456")
    m = re.search(r'\b(?:G-)?(\d{3})[- ](\d{3})\b', text)
    if m:
        return f"{m.group(1)}{m.group(2)}"

    # 2. Busca número de 4 a 8 dígitos após termos indicativos
    m = re.search(r'(?:c[oó]digo|token|senha|chave|code|pin|valida[çc][aã]o|verification)[^\d]{1,30}(\d{4,8})\b', text, re.IGNORECASE)
    if m:
        return m.group(1)

    # 3. Padrão alfanumérico que contenha pelo menos um número (ex: "AB12CD", "48F9A")
    m = re.search(r'(?:c[oó]digo|token|senha|chave|code|pin)[^\w]{1,10}([A-Z0-9]*\d[A-Z0-9]*)\b', text, re.IGNORECASE)
    if m and len(m.group(1)) >= 4:
        return m.group(1).upper()

    # 4. Padrão de 4 a 8 dígitos isolados no texto
    m = re.search(r'\b(\d{4,8})\b', text)
    if m:
        return m.group(1)
        
    return ""

async def get_db_connection():
    return await aiosqlite.connect(DB_PATH)
