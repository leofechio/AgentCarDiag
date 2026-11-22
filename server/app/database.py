"""
AgentCarDiag — Database Layer
Async SQLite via aiosqlite. Schema: sessions, can_logs, osc_captures.
DB path is configured via the DB_PATH env var (default: ./data/cardiag.db).
"""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

import aiosqlite

logger = logging.getLogger("cardiag.db")

from app.config import DB_PATH

# ─── Schema ───────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    vehicle_profile TEXT DEFAULT 'renault_trafic_m9r',
    notes           TEXT DEFAULT '',
    scanner_data    TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS can_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    timestamp   TEXT NOT NULL,
    can_id      TEXT NOT NULL,
    dlc         INTEGER NOT NULL,
    data_hex    TEXT NOT NULL,
    source      TEXT DEFAULT 'RAW',
    frame_uid   TEXT
);

CREATE TABLE IF NOT EXISTS osc_captures (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    timestamp    TEXT NOT NULL,
    samples_json TEXT NOT NULL,
    sample_rate  INTEGER NOT NULL DEFAULT 10000,
    vmin         REAL,
    vmax         REAL,
    vmean        REAL
);

CREATE TABLE IF NOT EXISTS obd_metrics (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    timestamp    TEXT NOT NULL,
    metric_name  TEXT NOT NULL,
    metric_value REAL NOT NULL,
    raw_response TEXT
);

CREATE INDEX IF NOT EXISTS idx_can_session    ON can_logs(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_osc_session    ON osc_captures(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_obd_session    ON obd_metrics(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_session_active ON sessions(is_active);

CREATE TABLE IF NOT EXISTS agent_chats (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL REFERENCES agent_chats(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_msg_chat ON agent_messages(chat_id, created_at);

-- ─── AguiaCar Fleet & Telematics ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fleet_vehicles (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    plate       TEXT NOT NULL,
    model       TEXT NOT NULL,
    vin         TEXT DEFAULT '',
    company     TEXT NOT NULL DEFAULT 'Enterprise / Hertz',
    status      TEXT NOT NULL DEFAULT 'OPERACIONAL',
    last_seen   TEXT,
    last_lat    REAL,
    last_lon    REAL,
    driving_score INTEGER DEFAULT 100,
    geofence_status TEXT DEFAULT 'INSIDE' -- 'INSIDE', 'OUTSIDE'
);

CREATE TABLE IF NOT EXISTS fleet_configs (
    vehicle_id               TEXT PRIMARY KEY REFERENCES fleet_vehicles(id) ON DELETE CASCADE,
    gps_interval_sec         INTEGER NOT NULL DEFAULT 5,
    gps_standby_interval_sec INTEGER NOT NULL DEFAULT 60,
    dtc_scan_interval_min    INTEGER NOT NULL DEFAULT 30,
    alert_email              TEXT NOT NULL DEFAULT 'reileonardofechio@gmail.com',
    max_engine_temp          REAL NOT NULL DEFAULT 105.0,
    max_rpm                  REAL NOT NULL DEFAULT 5500.0,
    max_speed                REAL NOT NULL DEFAULT 130.0,
    notify_disconnect        INTEGER NOT NULL DEFAULT 1,
    geofence_enabled         INTEGER NOT NULL DEFAULT 1,
    geofence_lat             REAL DEFAULT 42.580346,
    geofence_lon             REAL DEFAULT -5.584364,
    geofence_radius_km       REAL DEFAULT 15.0
);

CREATE TABLE IF NOT EXISTS fleet_telemetry (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id     TEXT NOT NULL REFERENCES fleet_vehicles(id) ON DELETE CASCADE,
    timestamp      TEXT NOT NULL,
    lat            REAL,
    lon            REAL,
    speed_gps      REAL,
    speed_obd      REAL,
    rpm            REAL,
    engine_temp    REAL,
    fuel_pct       REAL,
    engine_load    REAL,
    throttle_pct   REAL,
    battery_v      REAL,
    dtcs           TEXT,
    alert_level    TEXT DEFAULT 'NORMAL',
    accel_g        REAL DEFAULT 0.0,
    driving_event  TEXT DEFAULT '' -- 'HARSH_ACCEL', 'HARSH_BRAKE', 'CRASH', 'NORMAL'
);

CREATE TABLE IF NOT EXISTS fleet_alerts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id     TEXT NOT NULL REFERENCES fleet_vehicles(id) ON DELETE CASCADE,
    timestamp      TEXT NOT NULL,
    severity       TEXT NOT NULL, -- 'INFO', 'PREVENTIVA', 'CRITICO_PARADA'
    title          TEXT NOT NULL,
    message        TEXT NOT NULL,
    dtc            TEXT,
    ai_report      TEXT,
    status         TEXT NOT NULL DEFAULT 'OPEN' -- 'OPEN', 'RESOLVED'
);

CREATE INDEX IF NOT EXISTS idx_fleet_tel_veh ON fleet_telemetry(vehicle_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_fleet_alert_veh ON fleet_alerts(vehicle_id, status);

-- ─── Multi-Tenant & Hardware Production Line ─────────────────────────────────

CREATE TABLE IF NOT EXISTS workshops (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    owner_name     TEXT DEFAULT '',
    contact_email  TEXT DEFAULT '',
    contact_phone  TEXT DEFAULT '',
    username       TEXT UNIQUE,
    password_hash  TEXT DEFAULT '',
    created_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'ACTIVE' -- 'ACTIVE', 'TRIAL', 'BLOCKED'
);

CREATE TABLE IF NOT EXISTS hardware_devices (
    serial_number  TEXT PRIMARY KEY,
    device_type    TEXT NOT NULL, -- 'SCANNER_CAN', 'AGUIACAR_4G', 'OSCILOSCOPIO'
    model_name     TEXT NOT NULL,
    batch_code     TEXT NOT NULL DEFAULT 'LOTE-2026-01',
    workshop_id    TEXT REFERENCES workshops(id) ON DELETE SET NULL,
    status         TEXT NOT NULL DEFAULT 'IN_STOCK', -- 'IN_STOCK', 'ACTIVE', 'MAINTENANCE', 'BLOCKED'
    created_at     TEXT NOT NULL,
    activated_at   TEXT,
    last_seen      TEXT
);

CREATE TABLE IF NOT EXISTS inspection_reports (
    id             TEXT PRIMARY KEY,
    workshop_id    TEXT REFERENCES workshops(id) ON DELETE CASCADE,
    client_name    TEXT DEFAULT 'Cliente Final',
    vehicle_vin    TEXT DEFAULT '',
    vehicle_model  TEXT DEFAULT '',
    plate          TEXT DEFAULT '',
    odometer_km    TEXT DEFAULT '',
    dtcs_json      TEXT DEFAULT '[]',
    live_data_json TEXT DEFAULT '{}',
    ai_verdict     TEXT DEFAULT '',
    notes          TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hw_workshop ON hardware_devices(workshop_id);
CREATE INDEX IF NOT EXISTS idx_hw_status   ON hardware_devices(status);
CREATE INDEX IF NOT EXISTS idx_report_ws   ON inspection_reports(workshop_id);

-- ─── Honeypot Auth & Brute-Force Defense ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS blocked_ips (
    ip              TEXT PRIMARY KEY,
    blocked_at      TEXT NOT NULL,
    reason          TEXT NOT NULL,
    expires_at      INTEGER NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_attempt_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_blocked_ips_expires ON blocked_ips(expires_at);

-- ─── Device Credentials (Autenticação Individual de Hardware) ─────────────────
CREATE TABLE IF NOT EXISTS device_credentials (
    serial           TEXT PRIMARY KEY,
    device_type      TEXT NOT NULL,
    token_hash       TEXT NOT NULL,
    auth_level       TEXT NOT NULL DEFAULT 'individual',
    is_revoked       INTEGER NOT NULL DEFAULT 0,
    migration_status TEXT NOT NULL DEFAULT 'CONFIRMED',
    created_at       TEXT NOT NULL,
    last_auth_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_dev_cred_revoked ON device_credentials(is_revoked);

CREATE TABLE IF NOT EXISTS security_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

# ─── Lifecycle ────────────────────────────────────────────────────────────────

async def init_db() -> None:
    """Create the data directory, initialize schema and seed initial multi-tenant workshops."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        # Migração idempotente de colunas adicionadas
        try:
            await db.execute("ALTER TABLE sessions ADD COLUMN vehicle_profile TEXT DEFAULT 'renault_trafic_m9r'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE sessions ADD COLUMN scanner_data TEXT DEFAULT '{}'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE fleet_vehicles ADD COLUMN vin TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE inspection_reports ADD COLUMN readiness_json TEXT DEFAULT '{}'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE inspection_reports ADD COLUMN hv_battery_json TEXT DEFAULT '{}'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE workshops ADD COLUMN username TEXT")
            await db.execute("ALTER TABLE workshops ADD COLUMN password_hash TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE fleet_vehicles ADD COLUMN driving_score INTEGER DEFAULT 100")
            await db.execute("ALTER TABLE fleet_vehicles ADD COLUMN geofence_status TEXT DEFAULT 'INSIDE'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE fleet_configs ADD COLUMN geofence_enabled INTEGER NOT NULL DEFAULT 1")
            await db.execute("ALTER TABLE fleet_configs ADD COLUMN geofence_lat REAL DEFAULT 42.580346")
            await db.execute("ALTER TABLE fleet_configs ADD COLUMN geofence_lon REAL DEFAULT -5.584364")
            await db.execute("ALTER TABLE fleet_configs ADD COLUMN geofence_radius_km REAL DEFAULT 15.0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE fleet_telemetry ADD COLUMN accel_g REAL DEFAULT 0.0")
            await db.execute("ALTER TABLE fleet_telemetry ADD COLUMN driving_event TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE can_logs ADD COLUMN frame_uid TEXT")
        except Exception:
            pass
        try:
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_can_logs_uid ON can_logs(frame_uid) WHERE frame_uid IS NOT NULL")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE device_credentials ADD COLUMN migration_status TEXT NOT NULL DEFAULT 'CONFIRMED'")
        except Exception:
            pass

        now_str = _now()
        await db.execute(
            "INSERT OR IGNORE INTO security_settings (key, value, updated_at) VALUES ('legacy_ws_token_enabled', '1', ?)",
            (now_str,)
        )
        await db.execute(
            "INSERT OR IGNORE INTO security_settings (key, value, updated_at) VALUES ('allow_url_token_fallback', '1', ?)",
            (now_str,)
        )

        # Atualiza credenciais padrão para as oficinas se estiverem nulas
        await db.execute("UPDATE workshops SET username = id WHERE username IS NULL OR username = ''")
        await db.execute("UPDATE workshops SET password_hash = '123456' WHERE password_hash IS NULL OR password_hash = ''")

        # Seed inicial de 10 Oficinas Piloto se a tabela estiver vazia
        async with db.execute("SELECT COUNT(*) FROM workshops") as cur:
            row = await cur.fetchone()
            count = row[0] if row else 0

        if count == 0:
            pilots = [
                ("oficina-matriz", "Matriz AgentCar Tech (Lab & P&D)", "Eng. Leonardo Fechio", "admin@agentcar.me", "+34 600 000 001"),
                ("oficina-piloto-01", "Oficina Piloto 01 — Auto Mecânica Precision", "Carlos Alberto", "carlos@precisionauto.com", "+34 611 111 001"),
                ("oficina-piloto-02", "Oficina Piloto 02 — Garagem Euro Motors", "Marcio Vieira", "marcio@euromotors.es", "+34 611 111 002"),
                ("oficina-piloto-03", "Oficina Piloto 03 — Injeção Eletrônica Total", "Rodrigo Ramos", "rodrigo@injecaototal.com", "+34 611 111 003"),
                ("oficina-piloto-04", "Oficina Piloto 04 — Bosch Car Service Centro", "Fernando Dias", "fernando@boschcentro.es", "+34 611 111 004"),
                ("oficina-piloto-05", "Oficina Piloto 05 — Diesel & Câmbio Automático", "Paulo Souza", "paulo@dieselecambio.com", "+34 611 111 005"),
                ("oficina-piloto-06", "Oficina Piloto 06 — Oficina Modelo Rapida", "Julio Cesar", "julio@oficinamp.com", "+34 611 111 006"),
                ("oficina-piloto-07", "Oficina Piloto 07 — Centro Automotivo Aliança", "Marcelo Lima", "marcelo@aliancaauto.es", "+34 611 111 007"),
                ("oficina-piloto-08", "Oficina Piloto 08 — Frotas & Vans Express", "Roberto Mendes", "roberto@vansexpress.com", "+34 611 111 008"),
                ("oficina-piloto-09", "Oficina Piloto 09 — Locadora & Rent-A-Car Ibérica", "Eduardo Perez", "frotas@ibericarent.es", "+34 611 111 009"),
                ("oficina-piloto-10", "Oficina Piloto 10 — Especializada Franceses & EV", "Antoine Dupont", "antoine@evspecialist.fr", "+34 611 111 010"),
            ]
            for w_id, w_name, w_owner, w_email, w_phone in pilots:
                await db.execute(
                    "INSERT INTO workshops (id, name, owner_name, contact_email, contact_phone, created_at, status) VALUES (?,?,?,?,?,?,?)",
                    (w_id, w_name, w_owner, w_email, w_phone, now_str, 'ACTIVE')
                )

            # Equipamentos de Demonstração e Lote Inicial de Fabricação (s2001, a2001, o2001...)
            initial_devices = [
                # Ativos na Matriz
                ("s2001", "SCANNER_CAN", "AgentCar Scanner Pro (TWAI + K-Line MUX)", "LOTE-2026-01", "oficina-matriz", "ACTIVE", now_str, now_str),
                ("a2001", "AGUIACAR_4G", "AguiaCar Fleet Guardian 4G LTE", "LOTE-2026-01", "oficina-matriz", "ACTIVE", now_str, now_str),
                ("o2001", "OSCILOSCOPIO", "Osciloscópio de Borda Digital Dual", "LOTE-2026-01", "oficina-matriz", "ACTIVE", now_str, now_str),
                # Ativo na Oficina Piloto 01 e 02
                ("s2002", "SCANNER_CAN", "AgentCar Scanner Pro (TWAI + K-Line MUX)", "LOTE-2026-01", "oficina-piloto-01", "ACTIVE", now_str, now_str),
                ("s2003", "SCANNER_CAN", "AgentCar Scanner Pro (TWAI + K-Line MUX)", "LOTE-2026-01", "oficina-piloto-02", "ACTIVE", now_str, now_str),
                # Em Estoque Fabril (Prontos para venda ou ativação pelo mecânico)
                ("s2004", "SCANNER_CAN", "AgentCar Scanner Pro (TWAI + K-Line MUX)", "LOTE-2026-01", None, "IN_STOCK", now_str, None),
                ("s2005", "SCANNER_CAN", "AgentCar Scanner Pro (TWAI + K-Line MUX)", "LOTE-2026-01", None, "IN_STOCK", now_str, None),
                ("s2006", "SCANNER_CAN", "AgentCar Scanner Pro (TWAI + K-Line MUX)", "LOTE-2026-01", None, "IN_STOCK", now_str, None),
                ("a2002", "AGUIACAR_4G", "AguiaCar Fleet Guardian 4G LTE", "LOTE-2026-01", None, "IN_STOCK", now_str, None),
                ("o2002", "OSCILOSCOPIO", "Osciloscópio de Borda Digital Dual", "LOTE-2026-01", None, "IN_STOCK", now_str, None),
            ]
            for s_num, d_type, m_name, b_code, w_id, d_status, c_at, a_at in initial_devices:
                await db.execute(
                    "INSERT INTO hardware_devices (serial_number, device_type, model_name, batch_code, workshop_id, status, created_at, activated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (s_num, d_type, m_name, b_code, w_id, d_status, c_at, a_at)
                )

        # Carrega seriais revogados para cache em memória
        async with db.execute("SELECT serial FROM device_credentials WHERE is_revoked = 1") as cur:
            rev_rows = await cur.fetchall()
            _revoked_serials.clear()
            for r in rev_rows:
                _revoked_serials.add(str(r[0]).strip().lower())

        await db.commit()
    logger.info(f"Database initialized at {DB_PATH}")
    # Recupera automaticamente qualquer lote CAN retido no spool secundário em disco
    try:
        await recover_can_spool()
    except Exception as e:
        logger.warning(f"[DB] Aviso ao recuperar spool CAN na inicialização: {e}")


@asynccontextmanager
async def get_db():
    """Async context manager that yields a configured aiosqlite connection."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA journal_mode=WAL")
        yield db


# ─── Helper ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: aiosqlite.Row) -> dict:
    return dict(zip(row.keys(), row))


# ─── Sessions CRUD ────────────────────────────────────────────────────────────

async def list_sessions() -> list[dict]:
    """Return all sessions ordered by most recent first."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC"
        ) as cur:
            rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def create_session(name: str, notes: str = "", vehicle_profile: str = "renault_trafic_m9r") -> dict:
    """Create a new session, automatically set as active (deactivates others)."""
    import uuid
    session_id = uuid.uuid4().hex
    now = _now()

    async with get_db() as db:
        await db.execute("UPDATE sessions SET is_active = 0")
        await db.execute(
            "INSERT INTO sessions (id, name, vehicle_profile, notes, scanner_data, created_at, updated_at, is_active) VALUES (?,?,?,?,?,?,?,1)",
            (session_id, name, vehicle_profile, notes, "{}", now, now),
        )
        await db.commit()
        async with db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)) as cur:
            row = await cur.fetchone()

    logger.info(f"Session created: {session_id} — {name!r} ({vehicle_profile})")
    return _row_to_dict(row)


async def update_session(session_id: str, updates: dict) -> Optional[dict]:
    """Update fields of a session (e.g. vehicle_profile, notes, scanner_data)."""
    now = _now()
    allowed = {"name", "notes", "vehicle_profile", "scanner_data"}
    fields = []
    values = []
    for k, v in updates.items():
        if k in allowed:
            fields.append(f"{k} = ?")
            values.append(v)
    if not fields:
        return await get_session(session_id)
    fields.append("updated_at = ?")
    values.append(now)
    values.append(session_id)

    async with get_db() as db:
        await db.execute(
            f"UPDATE sessions SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        await db.commit()
    return await get_session(session_id)


async def get_session(session_id: str) -> Optional[dict]:
    """Fetch a single session row."""
    async with get_db() as db:
        async with db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row) if row else None


async def activate_session(session_id: str) -> Optional[dict]:
    """Set one session as active, deactivate all others."""
    async with get_db() as db:
        await db.execute("UPDATE sessions SET is_active = 0")
        await db.execute(
            "UPDATE sessions SET is_active = 1, updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )
        await db.commit()
        async with db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row) if row else None


async def delete_session(session_id: str) -> bool:
    """Delete a session and all its associated data (CASCADE)."""
    async with get_db() as db:
        cur = await db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        await db.commit()
        deleted = cur.rowcount > 0
    if deleted:
        logger.info(f"Session deleted: {session_id}")
    return deleted


async def get_active_session_id() -> Optional[str]:
    """Return the ID of the currently active session, or None."""
    async with get_db() as db:
        async with db.execute(
            "SELECT id FROM sessions WHERE is_active = 1 LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
    return row["id"] if row else None


async def update_session_timestamp(session_id: str) -> None:
    """Touch updated_at on a session."""
    async with get_db() as db:
        await db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )
        await db.commit()


# ─── Session detail (with data) ───────────────────────────────────────────────

async def get_session_detail(session_id: str, limit: int = 500) -> Optional[dict]:
    """Return session + last N CAN frames + last 50 OSC captures (without full samples blob)."""
    await flush_pending()
    session = await get_session(session_id)
    if not session:
        return None

    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM can_logs WHERE session_id=? ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit),
        ) as cur:
            can_rows = [_row_to_dict(r) for r in await cur.fetchall()]

        async with db.execute(
            "SELECT id, session_id, timestamp, sample_rate, vmin, vmax, vmean FROM osc_captures WHERE session_id=? ORDER BY timestamp DESC LIMIT 50",
            (session_id,),
        ) as cur:
            osc_rows = [_row_to_dict(r) for r in await cur.fetchall()]

        async with db.execute(
            "SELECT COUNT(*) as c FROM can_logs WHERE session_id=?", (session_id,)
        ) as cur:
            can_count = (await cur.fetchone())["c"]

        async with db.execute(
            "SELECT COUNT(*) as c FROM osc_captures WHERE session_id=?", (session_id,)
        ) as cur:
            osc_count = (await cur.fetchone())["c"]

    session["can_logs"]    = can_rows
    session["osc_captures"] = osc_rows
    session["can_count"]   = can_count
    session["osc_count"]   = osc_count
    return session


# ─── Telemetry persistence ────────────────────────────────────────────────────

CAN_ID_SOURCE = {
    "0x120": "RPM",
    "0x201": "SPEED",
    "0x310": "TEMP",
}

# In-memory batch buffer + Durable secondary disk spool
_can_batch: list[tuple] = []
_BATCH_SIZE = 20
_MAX_CAN_BUFFER = 5000
_MAX_SPOOL_FRAMES = 50000
_MAX_SPOOL_BYTES = 10 * 1024 * 1024        # 10 MB limite máximo para o arquivo de spool em disco
_MIN_DISK_FREE_BYTES = 20 * 1024 * 1024    # 20 MB espaço livre mínimo na partição
_MAX_FLUSH_RETRIES = 3
_MAX_SPOOL_WRITE_RETRIES = 3

_can_batch_lock: Optional[asyncio.Lock] = None
_can_flush_lock: Optional[asyncio.Lock] = None
_can_spool_path: Optional[Path] = None

_can_dropped_frames_count = 0
_can_buffer_overflow_alert = False
_can_spool_saturation_alert = False
_can_spool_write_errors = 0
_can_spooled_frames_total = 0
_can_recovered_frames_total = 0


def _get_can_lock() -> asyncio.Lock:
    global _can_batch_lock
    if _can_batch_lock is None:
        _can_batch_lock = asyncio.Lock()
    return _can_batch_lock


def _get_flush_lock() -> asyncio.Lock:
    global _can_flush_lock
    if _can_flush_lock is None:
        _can_flush_lock = asyncio.Lock()
    return _can_flush_lock


def _get_spool_path() -> Path:
    if _can_spool_path is not None:
        return Path(_can_spool_path)
    return Path(DB_PATH).parent / "can_spool.jsonl"


def _read_spool_records() -> list[tuple]:
    """Lê todos os registros válidos do arquivo de spool secundário preservando a ordem FIFO."""
    spool_path = _get_spool_path()
    if not spool_path.exists():
        return []
    records: list[tuple] = []
    try:
        with open(spool_path, "r", encoding="utf-8") as f:
            for line in f:
                line_s = line.strip()
                if not line_s:
                    continue
                try:
                    arr = json.loads(line_s)
                    if isinstance(arr, list) and len(arr) >= 6:
                        if len(arr) == 6:
                            arr.append(uuid.uuid4().hex)
                        records.append(tuple(arr[:7]))
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"[DB-Spool] Erro ao ler arquivo de spool CAN ({spool_path}): {e}")
    return records


def _write_spool_records_atomic(records: list[tuple]) -> bool:
    """Reescreve ou remove atomicamente o spool secundário somente após confirmação."""
    global _can_spool_write_errors, _can_spool_saturation_alert
    spool_path = _get_spool_path()
    try:
        if not records:
            if spool_path.exists():
                spool_path.unlink(missing_ok=True)
            return True

        spool_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = spool_path.with_suffix(".jsonl.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(list(rec)) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, spool_path)
        return True
    except Exception as e:
        _can_spool_write_errors += 1
        _can_spool_saturation_alert = True
        logger.critical(f"[DB-Spool] Falha crítica ao atualizar spool atômico ({spool_path}): {e}")
        return False


def _append_to_disk_spool(records: list[tuple]) -> int:
    """
    Persiste registros no armazenamento secundário durável em disco (FIFO) com:
    - Controle de espaço livre na partição (_MIN_DISK_FREE_BYTES)
    - Limite máximo de bytes (_MAX_SPOOL_BYTES) e quantidade de frames (_MAX_SPOOL_FRAMES)
    - Retentativas em caso de falha de I/O (_MAX_SPOOL_WRITE_RETRIES)
    Retorna a quantidade exata de frames gravados com sucesso no disco.
    """
    global _can_spool_saturation_alert, _can_buffer_overflow_alert, _can_spool_write_errors, _can_spooled_frames_total
    if not records:
        return 0

    spool_path = _get_spool_path()
    try:
        spool_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        _can_spool_write_errors += 1
        _can_spool_saturation_alert = True
        _can_buffer_overflow_alert = True
        logger.critical(f"[DB-Spool] Falha ao criar diretório de spool {spool_path.parent}: {e}")
        return 0

    # 1. Verifica espaço livre em disco na partição
    try:
        usage = shutil.disk_usage(spool_path.parent)
        if usage.free < _MIN_DISK_FREE_BYTES:
            _can_spool_saturation_alert = True
            _can_buffer_overflow_alert = True
            logger.critical(
                f"[DB-Spool] ESPAÇO EM DISCO INSUFICIENTE: livre={usage.free} bytes < mínimo={_MIN_DISK_FREE_BYTES} bytes."
            )
            return 0
    except Exception as e:
        logger.warning(f"[DB-Spool] Não foi possível verificar espaço em disco: {e}")

    # 2. Verifica limites de utilização do arquivo de spool (bytes e contagem de frames)
    existing_records = _read_spool_records()
    existing_count = len(existing_records)
    current_bytes = spool_path.stat().st_size if spool_path.exists() else 0

    if existing_count >= _MAX_SPOOL_FRAMES or current_bytes >= _MAX_SPOOL_BYTES:
        _can_spool_saturation_alert = True
        _can_buffer_overflow_alert = True
        logger.critical(
            f"[DB-Spool] SATURAÇÃO DO ARMAZENAMENTO SECUNDÁRIO: spool atingiu limite "
            f"(frames={existing_count}/{_MAX_SPOOL_FRAMES}, bytes={current_bytes}/{_MAX_SPOOL_BYTES})."
        )
        return 0

    allowed_by_count = max(0, _MAX_SPOOL_FRAMES - existing_count)
    lines_to_write: list[str] = []
    projected_bytes = current_bytes
    for rec in records[:allowed_by_count]:
        rec_norm = list(rec[:7]) if len(rec) >= 7 else list(rec) + [uuid.uuid4().hex]
        line_str = json.dumps(rec_norm) + "\n"
        line_bytes = len(line_str.encode("utf-8"))
        if projected_bytes + line_bytes > _MAX_SPOOL_BYTES:
            _can_spool_saturation_alert = True
            _can_buffer_overflow_alert = True
            logger.critical(
                f"[DB-Spool] Limite de bytes do spool atingido ({projected_bytes + line_bytes} > {_MAX_SPOOL_BYTES})."
            )
            break
        lines_to_write.append(line_str)
        projected_bytes += line_bytes

    if not lines_to_write:
        return 0

    # 3. Gravação com retentativas e fsync
    for attempt in range(1, _MAX_SPOOL_WRITE_RETRIES + 1):
        try:
            with open(spool_path, "a", encoding="utf-8") as f:
                f.writelines(lines_to_write)
                f.flush()
                os.fsync(f.fileno())
            written = len(lines_to_write)
            _can_spooled_frames_total += written
            if written < len(records):
                _can_spool_saturation_alert = True
                _can_buffer_overflow_alert = True
            return written
        except Exception as e:
            _can_spool_write_errors += 1
            logger.warning(f"[DB-Spool] Tentativa {attempt}/{_MAX_SPOOL_WRITE_RETRIES} de escrita no spool falhou: {e}")

    _can_spool_saturation_alert = True
    _can_buffer_overflow_alert = True
    logger.critical(
        f"[DB-Spool] FALHA DEFINITIVA DE ESCRITA NO SPOOL EM DISCO após {_MAX_SPOOL_WRITE_RETRIES} tentativas!"
    )
    return 0


def get_can_buffer_status() -> dict:
    """Inspeciona estado em tempo real do buffer RAM e do armazenamento secundário (spool) CAN."""
    spool_path = _get_spool_path()
    spool_exists = spool_path.exists()
    spool_bytes = spool_path.stat().st_size if spool_exists else 0
    spool_frames = len(_read_spool_records()) if spool_exists else 0
    return {
        "buffer_size": len(_can_batch),
        "max_buffer_bound": _MAX_CAN_BUFFER,
        "spool_frames": spool_frames,
        "spool_bytes": spool_bytes,
        "max_spool_frames": _MAX_SPOOL_FRAMES,
        "max_spool_bytes": _MAX_SPOOL_BYTES,
        "spooled_frames_total": _can_spooled_frames_total,
        "recovered_frames_total": _can_recovered_frames_total,
        "spool_write_errors": _can_spool_write_errors,
        "dropped_frames": _can_dropped_frames_count,
        "overflow_alert": _can_buffer_overflow_alert,
        "spool_saturation_alert": _can_spool_saturation_alert,
    }


async def persist_can_frame(session_id: str, frame: dict) -> None:
    """Buffer a CAN frame in RAM (with automatic spill to durable disk spool if full) and flush to DB."""
    global _can_batch, _can_dropped_frames_count, _can_buffer_overflow_alert, _can_spool_saturation_alert

    can_id    = frame.get("id", "0x000")
    dlc       = frame.get("dlc", 0)
    data      = frame.get("data", [])
    ts        = frame.get("ts") or _now()
    frame_uid = frame.get("frame_uid") or uuid.uuid4().hex
    source    = CAN_ID_SOURCE.get(can_id, CAN_ID_SOURCE.get(can_id.lower(), "RAW"))
    data_hex  = " ".join(f"{b:02X}" for b in data) if isinstance(data, list) else str(data)

    should_flush = False
    async with _get_can_lock():
        if len(_can_batch) >= _MAX_CAN_BUFFER:
            # Tenta primeiro descarregar os frames mais antigos para o armazenamento durável em disco (FIFO)
            spill_chunk_size = min(len(_can_batch), max(_BATCH_SIZE, 200))
            to_spill = _can_batch[:spill_chunk_size]
            spilled = _append_to_disk_spool(to_spill)
            if spilled > 0:
                _can_batch = _can_batch[spilled:]
                logger.warning(
                    f"[DB] Buffer RAM atingiu {_MAX_CAN_BUFFER}; {spilled} frames transferidos para o spool durável em disco."
                )

            # Se mesmo após tentativa de spool o buffer RAM continuar no limite físico, contabiliza perda inevitável
            if len(_can_batch) >= _MAX_CAN_BUFFER:
                _can_dropped_frames_count += 1
                _can_buffer_overflow_alert = True
                _can_spool_saturation_alert = True
                _can_batch.pop(0)
                logger.critical(
                    f"[DB] CRITICAL BUFFER & SPOOL OVERFLOW: Buffer RAM ({_MAX_CAN_BUFFER}) e Spool em Disco saturados. "
                    f"Frame mais antigo descartado. Total descartados: {_can_dropped_frames_count}. "
                    "PERDA INEVITÁVEL DE DADOS DE TELEMETRIA!"
                )
        _can_batch.append((session_id, ts, can_id, dlc, data_hex, source, frame_uid))
        should_flush = len(_can_batch) >= _BATCH_SIZE

    if should_flush:
        await _flush_can_batch()


async def _insert_can_records_with_retry(records: list[tuple]) -> bool:
    """Grava lote de registros CAN no SQLite com proteção contra duplicações (INSERT OR IGNORE por frame_uid)."""
    if not records:
        return True
    normalized = [
        (r[0], r[1], r[2], r[3], r[4], r[5], r[6] if len(r) >= 7 else uuid.uuid4().hex)
        for r in records
    ]
    for attempt in range(1, _MAX_FLUSH_RETRIES + 1):
        try:
            async with get_db() as db:
                await db.executemany(
                    "INSERT OR IGNORE INTO can_logs (session_id, timestamp, can_id, dlc, data_hex, source, frame_uid) VALUES (?,?,?,?,?,?,?)",
                    normalized,
                )
                await db.commit()
            return True
        except Exception as e:
            logger.warning(f"Tentativa {attempt}/{_MAX_FLUSH_RETRIES} de gravação do lote CAN falhou: {e}")
            if attempt < _MAX_FLUSH_RETRIES:
                await asyncio.sleep(0.05 * attempt)
    return False


async def recover_can_spool() -> int:
    """
    Recupera e drena os frames do spool secundário em disco para o SQLite em ordem estrita FIFO.
    Elimina os dados temporários do spool SOMENTE após confirmação de commit no banco definitivo.
    """
    global _can_recovered_frames_total
    async with _get_flush_lock():
        spooled = _read_spool_records()
        if not spooled:
            return 0
        ok = await _insert_can_records_with_retry(spooled)
        if ok:
            _write_spool_records_atomic([])
            _can_recovered_frames_total += len(spooled)
            logger.info(f"[DB-Spool] Recuperados {len(spooled)} frames do spool em disco para o SQLite.")
            return len(spooled)
        return 0


async def _flush_can_batch() -> None:
    """
    Sincroniza e persiste frames CAN preservando ordem global FIFO:
    1. Se houver frames no spool em disco, drena o spool primeiro para manter ordem FIFO.
    2. Em seguida, grava o lote atual da memória RAM.
    3. Se o SQLite estiver indisponível após _MAX_FLUSH_RETRIES, transfere o lote para o spool em disco.
    4. Caso o spool em disco também esteja saturado/indisponível, retém em RAM até _MAX_CAN_BUFFER e contabiliza perdas.
    """
    global _can_batch, _can_dropped_frames_count, _can_buffer_overflow_alert, _can_recovered_frames_total

    async with _get_flush_lock():
        async with _get_can_lock():
            batch = _can_batch
            _can_batch = []

        spooled = _read_spool_records()
        if not spooled and not batch:
            return

        # 1. Se existem dados no spool em disco, precisamos drená-los ANTES do batch atual para preservar FIFO estrito
        if spooled:
            spool_ok = await _insert_can_records_with_retry(spooled)
            if spool_ok:
                # Elimina os dados temporários somente após confirmação do commit no SQLite
                _write_spool_records_atomic([])
                _can_recovered_frames_total += len(spooled)
                logger.info(f"[DB-Spool] {len(spooled)} frames do spool persistidos e limpos com sucesso.")
            else:
                # SQLite continua indisponível: preserva o spool e envia o batch atual para o final do spool
                logger.critical(
                    f"[DB] FALHA DEFINITIVA NA PERSISTÊNCIA CAN: {_MAX_FLUSH_RETRIES} tentativas falharam. "
                    f"Spool ativo ({len(spooled)} frames). Tentando fazer spool de mais {len(batch)} frames."
                )
                _can_buffer_overflow_alert = True
                if batch:
                    spilled = _append_to_disk_spool(batch)
                    unspilled = batch[spilled:]
                    if unspilled:
                        async with _get_can_lock():
                            _can_batch = unspilled + _can_batch
                            if len(_can_batch) > _MAX_CAN_BUFFER:
                                dropped = len(_can_batch) - _MAX_CAN_BUFFER
                                _can_dropped_frames_count += dropped
                                _can_batch = _can_batch[-_MAX_CAN_BUFFER:]
                                logger.critical(
                                    f"[DB] CRITICAL OVERFLOW: {dropped} frames descartados por saturação simultânea de RAM e Spool! "
                                    f"Total descartados: {_can_dropped_frames_count}."
                                )
                return

        # 2. Grava o lote atual da RAM no SQLite
        if batch:
            batch_ok = await _insert_can_records_with_retry(batch)
            if not batch_ok:
                logger.critical(
                    f"[DB] FALHA DEFINITIVA NA PERSISTÊNCIA CAN: {_MAX_FLUSH_RETRIES} tentativas falharam. "
                    f"Transferindo {len(batch)} frames para o spool durável em disco!"
                )
                _can_buffer_overflow_alert = True
                spilled = _append_to_disk_spool(batch)
                unspilled = batch[spilled:]
                if unspilled:
                    async with _get_can_lock():
                        _can_batch = unspilled + _can_batch
                        if len(_can_batch) > _MAX_CAN_BUFFER:
                            dropped = len(_can_batch) - _MAX_CAN_BUFFER
                            _can_dropped_frames_count += dropped
                            _can_batch = _can_batch[-_MAX_CAN_BUFFER:]
                            logger.critical(
                                f"[DB] CRITICAL OVERFLOW: {dropped} frames descartados por saturação simultânea de RAM e Spool! "
                                f"Total descartados: {_can_dropped_frames_count}."
                            )


async def flush_pending() -> None:
    """Flush any remaining buffered data (called on shutdown or session switch)."""
    await _flush_can_batch()


# ─── Device Credentials, Controlled Migration & Immediate Revocation ──────────

_revoked_serials: set[str] = set()
_revocation_callbacks: list[Callable[[str], Awaitable[None]]] = []


def register_revocation_callback(callback: Callable[[str], Awaitable[None]]) -> None:
    """Registra callback assíncrono para encerrar conexões ativas imediatamente na revogação."""
    if callback not in _revocation_callbacks:
        _revocation_callbacks.append(callback)


def is_serial_revoked(serial: str) -> bool:
    """Verificação O(1) em tempo real se um serial teve sua credencial revogada."""
    if not serial:
        return False
    return serial.strip().lower() in _revoked_serials


async def is_serial_revoked_async(serial: str) -> bool:
    """Verifica revogação consultando o SQLite (fonte de verdade entre processos) e o cache em memória."""
    if not serial:
        return False
    clean_serial = serial.strip().lower()
    try:
        async with get_db() as db:
            async with db.execute(
                "SELECT is_revoked FROM device_credentials WHERE serial = ?",
                (clean_serial,)
            ) as cur:
                row = await cur.fetchone()
                if row is not None:
                    if int(row[0]) == 1:
                        _revoked_serials.add(clean_serial)
                        return True
                    else:
                        _revoked_serials.discard(clean_serial)
                        return False
    except Exception:
        pass
    return clean_serial in _revoked_serials


async def get_all_revoked_serials_async() -> set[str]:
    """Sincroniza e retorna todos os seriais com credencial revogada no banco."""
    try:
        async with get_db() as db:
            async with db.execute("SELECT serial, is_revoked FROM device_credentials") as cur:
                rows = await cur.fetchall()
                for r in rows:
                    s_clean = str(r[0]).strip().lower()
                    if int(r[1]) == 1:
                        _revoked_serials.add(s_clean)
                    else:
                        _revoked_serials.discard(s_clean)
    except Exception:
        pass
    return set(_revoked_serials)


def hash_device_token(token: str) -> str:
    """Calcula hash SHA-256 seguro da credencial do dispositivo."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


async def register_device_credential(
    serial: str,
    device_type: str,
    token: str,
    auth_level: str = "individual",
    migration_status: str = "CONFIRMED",
) -> None:
    """Registra credencial individual de um dispositivo (armazenada apenas como hash SHA-256)."""
    clean_serial = serial.strip().lower()
    t_hash = hash_device_token(token)
    now = _now()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO device_credentials (serial, device_type, token_hash, auth_level, is_revoked, migration_status, created_at, last_auth_at)
               VALUES (?, ?, ?, ?, 0, ?, ?, ?)
               ON CONFLICT(serial) DO UPDATE SET
                   device_type = excluded.device_type,
                   token_hash = excluded.token_hash,
                   auth_level = excluded.auth_level,
                   is_revoked = 0,
                   migration_status = excluded.migration_status,
                   last_auth_at = excluded.last_auth_at""",
            (clean_serial, device_type, t_hash, auth_level, migration_status, now, now)
        )
        await db.commit()
    _revoked_serials.discard(clean_serial)
    logger.info(
        f"[Auth] Credencial individual registrada para serial={clean_serial} "
        f"(tipo={device_type}, status={migration_status})"
    )


async def provision_device_credential(
    serial: str,
    device_type: str,
    token: Optional[str] = None,
    require_confirmation: bool = True,
) -> dict:
    """
    Provisiona uma credencial exclusiva para um dispositivo durante a migração controlada.
    Se require_confirmation=True, inicia em 'PENDING_CONFIRMATION' até o dispositivo autenticar
    com sua credencial individual pela primeira vez, confirmando a migração.
    """
    clean_serial = serial.strip().lower()
    raw_token = token.strip() if token else f"acd_{clean_serial}_{secrets.token_urlsafe(24)}"
    mig_status = "PENDING_CONFIRMATION" if require_confirmation else "CONFIRMED"
    await register_device_credential(
        serial=clean_serial,
        device_type=device_type,
        token=raw_token,
        auth_level="individual",
        migration_status=mig_status,
    )
    return {
        "serial": clean_serial,
        "device_type": device_type,
        "token": raw_token,
        "migration_status": mig_status,
    }


async def revoke_device_credential(serial: str) -> bool:
    """
    Revoga imediatamente a credencial de um dispositivo:
    1. Marca no conjunto em memória _revoked_serials (efeito instantâneo em mensagens em trânsito).
    2. Persiste is_revoked = 1 no SQLite.
    3. Aciona todos os callbacks registrados no gateway para fechar o socket ativo imediatamente.
    """
    clean_serial = serial.strip().lower()
    _revoked_serials.add(clean_serial)
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE device_credentials SET is_revoked = 1 WHERE serial = ?",
            (clean_serial,)
        )
        await db.commit()
        revoked = cur.rowcount > 0

    if revoked:
        logger.warning(f"[Auth] Credencial individual REVOGADA para serial={clean_serial}. Encerrando conexões ativas...")
    else:
        logger.warning(f"[Auth] Serial {clean_serial} adicionado à lista de bloqueio imediato.")

    # Notifica imediatamente o gerenciador de WebSockets para desconectar o socket ativo do serial
    for cb in list(_revocation_callbacks):
        try:
            await cb(clean_serial)
        except Exception as e:
            logger.error(f"[Auth] Erro ao executar callback de revogação para {clean_serial}: {e}")

    return revoked


async def get_device_credential(serial: str) -> Optional[dict]:
    """Consulta registro de credencial por serial."""
    clean_serial = serial.strip().lower()
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM device_credentials WHERE serial = ?",
            (clean_serial,)
        ) as cur:
            row = await cur.fetchone()
            return _row_to_dict(row) if row else None


async def is_legacy_auth_enabled() -> bool:
    """Verifica se o modo de transição com WS_TOKEN global ainda está habilitado."""
    async with get_db() as db:
        async with db.execute(
            "SELECT value FROM security_settings WHERE key = 'legacy_ws_token_enabled'"
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return True
            return str(row[0]) == "1"


async def set_legacy_auth_enabled(enabled: bool, force: bool = False) -> tuple[bool, str]:
    """
    Ativa ou desativa o suporte ao token global legado (WS_TOKEN).
    Para desativar (enabled=False) sem force=True, exige que exista pelo menos um dispositivo
    provisionado e que TODOS os dispositivos provisionados estejam com migration_status='CONFIRMED'
    (nenhum pendente de confirmação).
    """
    if not enabled and not force:
        async with get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM device_credentials WHERE is_revoked = 0"
            ) as cur:
                total_prov = (await cur.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(*) FROM device_credentials WHERE is_revoked = 0 AND migration_status != 'CONFIRMED'"
            ) as cur:
                pending_prov = (await cur.fetchone())[0]

        if total_prov == 0:
            return False, "no_provisioned_devices"
        if pending_prov > 0:
            return False, f"pending_migrations:{pending_prov}"

    val = "1" if enabled else "0"
    now = _now()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO security_settings (key, value, updated_at) VALUES ('legacy_ws_token_enabled', ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (val, now)
        )
        await db.commit()
    logger.info(f"[Auth] Modo legado WS_TOKEN alterado para enabled={enabled} (force={force})")
    return True, "updated"


async def get_migration_status_summary() -> dict:
    """Retorna panorama completo do provisionamento individual e status do modo legado."""
    legacy_enabled = await is_legacy_auth_enabled()
    async with get_db() as db:
        async with db.execute(
            "SELECT serial, device_type, auth_level, is_revoked, migration_status, created_at, last_auth_at FROM device_credentials ORDER BY serial"
        ) as cur:
            rows = await cur.fetchall()
            creds = [_row_to_dict(r) for r in rows]

    confirmed = [c for c in creds if not c["is_revoked"] and c.get("migration_status") == "CONFIRMED"]
    pending = [c for c in creds if not c["is_revoked"] and c.get("migration_status") != "CONFIRMED"]
    revoked = [c for c in creds if c["is_revoked"]]
    return {
        "legacy_ws_token_enabled": legacy_enabled,
        "total_credentials": len(creds),
        "confirmed_count": len(confirmed),
        "pending_confirmation_count": len(pending),
        "revoked_count": len(revoked),
        "ready_to_disable_legacy": len(confirmed) > 0 and len(pending) == 0,
        "devices": creds,
    }


async def verify_device_authentication(serial: str, presented_token: Optional[str]) -> tuple[bool, str]:
    """
    Valida autenticação do dispositivo:
    1. Rejeita imediatamente se o serial estiver revogado (_revoked_serials ou banco).
    2. Se possuir credencial individual registrada:
       - Valida hash SHA-256 em tempo constante (secrets.compare_digest).
       - Se válido e estava em 'PENDING_CONFIRMATION', promove automaticamente para 'CONFIRMED'.
       - Se inválido e estiver em 'PENDING_CONFIRMATION' com modo legado ativo, permite transição controlada;
         caso já esteja 'CONFIRMED', bloqueia estritamente qualquer outro token (inclusive o legado).
    3. Para dispositivos ainda sem credencial individual, só aceita WS_TOKEN se legacy_ws_token_enabled=True.
    """
    from app.config import WS_TOKEN
    clean_serial = serial.strip().lower() if serial else ""
    if not presented_token:
        return False, "missing_token"

    # 1. Verifica se existe credencial individual registrada para este serial
    cred = await get_device_credential(clean_serial)
    if cred:
        if cred.get("is_revoked", 0) == 1:
            _revoked_serials.add(clean_serial)
            logger.warning(f"[Auth] Acesso negado para serial={clean_serial}: credencial revogada.")
            return False, "revoked"
        else:
            _revoked_serials.discard(clean_serial)

        presented_hash = hash_device_token(presented_token)
        if secrets.compare_digest(presented_hash, cred.get("token_hash", "")):
            now = _now()
            async with get_db() as db:
                await db.execute(
                    "UPDATE device_credentials SET last_auth_at = ?, migration_status = 'CONFIRMED' WHERE serial = ?",
                    (now, clean_serial)
                )
                await db.commit()
            return True, "individual"

        # Se o dispositivo foi recém-provisionado (PENDING_CONFIRMATION) e ainda usa o token legado antes do reflash:
        if cred.get("migration_status") == "PENDING_CONFIRMATION" and await is_legacy_auth_enabled():
            if secrets.compare_digest(presented_token, WS_TOKEN):
                logger.warning(
                    f"[Auth] Serial={clean_serial} conectou com token legado (migração pendente de confirmação)."
                )
                return True, "legacy_migrating"

        logger.warning(f"[Auth] Acesso negado para serial={clean_serial}: token individual incorreto.")
        return False, "individual_token_mismatch"

    # 2. Verifica se o token apresentado pertence a OUTRO dispositivo (impede uso cruzado de credenciais)
    presented_hash = hash_device_token(presented_token)
    async with get_db() as db:
        async with db.execute(
            "SELECT serial FROM device_credentials WHERE token_hash = ?",
            (presented_hash,)
        ) as cur:
            other_row = await cur.fetchone()
            if other_row and str(other_row[0]).strip().lower() != clean_serial:
                logger.warning(
                    f"[Auth] Bloqueada tentativa de usar credencial individual de {other_row[0]} no serial={clean_serial}!"
                )
                return False, "cross_device_credential_abuse"

    # 3. Modo de transição com token global legado (somente se habilitado)
    if not await is_legacy_auth_enabled():
        logger.warning(f"[Auth] Acesso negado para serial={clean_serial}: modo legado WS_TOKEN está desativado.")
        return False, "legacy_disabled"

    if secrets.compare_digest(presented_token, WS_TOKEN):
        return True, "legacy"

    return False, "invalid_token"


async def persist_osc_capture(session_id: str, burst: dict) -> None:
    """Persist an ADC burst capture."""
    samples = burst.get("samples", [])
    if not samples:
        return

    ts          = burst.get("ts") or _now()
    sample_rate = burst.get("sample_rate", 10000)
    vmin        = round(min(samples), 4)
    vmax        = round(max(samples), 4)
    vmean       = round(sum(samples) / len(samples), 4)
    samples_json = json.dumps(samples)

    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO osc_captures (session_id, timestamp, samples_json, sample_rate, vmin, vmax, vmean) VALUES (?,?,?,?,?,?,?)",
                (session_id, ts, samples_json, sample_rate, vmin, vmax, vmean),
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to persist OSC capture: {e}")


async def persist_obd_metric(session_id: str, metric_name: str, metric_value: float, raw_response: str = "") -> None:
    """Persist an OBD metric received from ESP32."""
    ts = _now()
    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO obd_metrics (session_id, timestamp, metric_name, metric_value, raw_response) VALUES (?,?,?,?,?)",
                (session_id, ts, metric_name, metric_value, raw_response),
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to persist OBD metric: {e}")


async def save_inspection_report(report: dict) -> dict:
    """Salva um laudo pericial gerado no banco de dados."""
    r_id = report.get("id") or f"rep-{uuid.uuid4().hex[:8]}"
    now_str = _now()
    async with get_db() as db:
        await db.execute(
            """INSERT INTO inspection_reports 
               (id, workshop_id, client_name, vehicle_vin, vehicle_model, plate, odometer_km, dtcs_json, live_data_json, readiness_json, hv_battery_json, ai_verdict, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r_id,
                report.get("workshop_id", "oficina-matriz"),
                report.get("client_name", "Cliente Final"),
                report.get("vehicle_vin", ""),
                report.get("vehicle_model", ""),
                report.get("plate", ""),
                report.get("odometer_km", ""),
                json.dumps(report.get("dtcs", [])),
                json.dumps(report.get("live_data", {})),
                json.dumps(report.get("readiness_data") or {}),
                json.dumps(report.get("hv_battery_data") or {}),
                report.get("ai_verdict", ""),
                report.get("notes", ""),
                now_str
            )
        )
        await db.commit()
    report["id"] = r_id
    report["created_at"] = now_str
    return report

async def get_inspection_report(report_id: str) -> dict | None:
    """Busca um laudo pericial completo pelo ID."""
    async with get_db() as db:
        async with db.execute(
            """SELECT r.id, r.workshop_id, r.client_name, r.vehicle_vin, r.vehicle_model, r.plate, r.odometer_km, 
                      r.dtcs_json, r.live_data_json, r.readiness_json, r.hv_battery_json, r.ai_verdict, r.notes, r.created_at,
                      w.name as workshop_name, w.owner_name, w.contact_phone, w.contact_email
               FROM inspection_reports r
               LEFT JOIN workshops w ON r.workshop_id = w.id
               WHERE r.id = ?""",
            (report_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "workshop_id": row[1],
                "client_name": row[2],
                "vehicle_vin": row[3],
                "vehicle_model": row[4],
                "plate": row[5],
                "odometer_km": row[6],
                "dtcs": json.loads(row[7] or "[]"),
                "live_data": json.loads(row[8] or "{}"),
                "readiness_data": json.loads(row[9] or "{}"),
                "hv_battery_data": json.loads(row[10] or "{}"),
                "ai_verdict": row[11],
                "notes": row[12],
                "created_at": row[13],
                "workshop": {
                    "name": row[14] or "Centro Técnico Especializado",
                    "owner": row[15] or "",
                    "phone": row[16] or "",
                    "email": row[17] or ""
                }
            }
