"""
AgentCarDiag — Database Layer
Async SQLite via aiosqlite. Schema: sessions, can_logs, osc_captures.
DB path is configured via the DB_PATH env var (default: ./data/cardiag.db).
"""

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
    source      TEXT DEFAULT 'RAW'
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

        # Atualiza credenciais padrão para as oficinas se estiverem nulas
        await db.execute("UPDATE workshops SET username = id WHERE username IS NULL OR username = ''")
        await db.execute("UPDATE workshops SET password_hash = '123456' WHERE password_hash IS NULL OR password_hash = ''")

        # Seed inicial de 10 Oficinas Piloto se a tabela estiver vazia
        async with db.execute("SELECT COUNT(*) FROM workshops") as cur:
            row = await cur.fetchone()
            count = row[0] if row else 0

        if count == 0:
            now_str = _now()
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

        await db.commit()
    logger.info(f"Database initialized at {DB_PATH}")


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

# In-memory batch buffer to reduce write frequency
_can_batch: list[tuple] = []
_BATCH_SIZE = 20


async def persist_can_frame(session_id: str, frame: dict) -> None:
    """Buffer a CAN frame and flush to DB every _BATCH_SIZE frames."""
    global _can_batch

    can_id   = frame.get("id", "0x000")
    dlc      = frame.get("dlc", 0)
    data     = frame.get("data", [])
    ts       = frame.get("ts") or _now()
    source   = CAN_ID_SOURCE.get(can_id, CAN_ID_SOURCE.get(can_id.lower(), "RAW"))
    data_hex = " ".join(f"{b:02X}" for b in data) if isinstance(data, list) else str(data)

    _can_batch.append((session_id, ts, can_id, dlc, data_hex, source))

    if len(_can_batch) >= _BATCH_SIZE:
        await _flush_can_batch()


async def _flush_can_batch() -> None:
    """Write accumulated CAN frames to the database."""
    global _can_batch
    if not _can_batch:
        return
    batch = _can_batch
    _can_batch = []
    try:
        async with get_db() as db:
            await db.executemany(
                "INSERT INTO can_logs (session_id, timestamp, can_id, dlc, data_hex, source) VALUES (?,?,?,?,?,?)",
                batch,
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to flush CAN batch: {e}")


async def flush_pending() -> None:
    """Flush any remaining buffered data (called on shutdown or session switch)."""
    await _flush_can_batch()


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
