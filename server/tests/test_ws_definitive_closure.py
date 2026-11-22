"""
test_ws_definitive_closure.py — Suite Automatizada dos 15 Requisitos Finais de Segurança e Integridade WebSocket
AgentCarDiag Server
"""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.config import WS_TOKEN
from app import database as db
from app.routers.websockets import SensitiveTokenLogFilter


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def setup_clean_db(tmp_path, monkeypatch):
    """Isola banco SQLite e arquivo de spool em tmp_path para cada teste."""
    test_db = tmp_path / "test_closure.db"
    test_spool = tmp_path / "test_can_spool.jsonl"
    monkeypatch.setattr(db, "DB_PATH", str(test_db))
    monkeypatch.setattr(db, "_can_spool_path", test_spool)
    monkeypatch.setattr(db, "_can_batch", [])
    monkeypatch.setattr(db, "_can_batch_lock", None)
    monkeypatch.setattr(db, "_can_flush_lock", None)
    monkeypatch.setattr(db, "_can_dropped_frames_count", 0)
    monkeypatch.setattr(db, "_can_buffer_overflow_alert", False)
    monkeypatch.setattr(db, "_can_spool_saturation_alert", False)
    monkeypatch.setattr(db, "_can_spool_write_errors", 0)
    monkeypatch.setattr(db, "_can_spooled_frames_total", 0)
    monkeypatch.setattr(db, "_can_recovered_frames_total", 0)
    monkeypatch.setattr(db, "_MAX_CAN_BUFFER", 5000)
    monkeypatch.setattr(db, "_MAX_SPOOL_FRAMES", 50000)
    monkeypatch.setattr(db, "_MAX_SPOOL_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(db, "_MIN_DISK_FREE_BYTES", 1024)
    _run(db.init_db())
    yield


def test_01_individual_credentials_and_serial_binding():
    """1. Credenciais individuais, associação ao serial e migração controlada do modo legado."""
    async def _scenario():
        prov = await db.provision_device_credential("s_mig_1", "Scanner_CAN", require_confirmation=True)
        assert prov["migration_status"] == "PENDING_CONFIRMATION"
        token_1 = prov["token"]

        # Não deve permitir desativar modo legado enquanto houver dispositivo pendente de confirmação
        ok, reason = await db.set_legacy_auth_enabled(False, force=False)
        assert not ok
        assert "pending_migrations" in reason

        # Autenticar com o token individual promove automaticamente para CONFIRMED
        is_auth, mode = await db.verify_device_authentication("s_mig_1", token_1)
        assert is_auth is True
        assert mode == "individual"

        cred = await db.get_device_credential("s_mig_1")
        assert cred["migration_status"] == "CONFIRMED"

        # Depois de todos confirmados, permite desativar definitivamente o WS_TOKEN global
        ok2, reason2 = await db.set_legacy_auth_enabled(False, force=False)
        assert ok2 is True
        assert reason2 == "updated"

        # Com modo legado desativado, WS_TOKEN global é rejeitado
        is_leg, leg_mode = await db.verify_device_authentication("s_unprovisioned", WS_TOKEN)
        assert is_leg is False
        assert leg_mode == "legacy_disabled"

        # Dispositivo individual continua autenticando normalmente
        is_auth2, mode2 = await db.verify_device_authentication("s_mig_1", token_1)
        assert is_auth2 is True
        assert mode2 == "individual"

        await db.set_legacy_auth_enabled(True)

    _run(_scenario())


def test_02_takeover_blocked_against_other_esp32_credential():
    """2. Tentativa de takeover com credencial de outro ESP32 é bloqueada; sessão ativa permanece intacta."""
    _run(db.register_device_credential("s_dev_a", "Scanner_CAN", "tok_secret_a_123"))
    _run(db.register_device_credential("s_dev_b", "Scanner_CAN", "tok_secret_b_456"))

    client = TestClient(app)
    with client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s_dev_a") as ws_a:
        ws_a.send_text(json.dumps({"type": "auth", "token": "tok_secret_a_123", "serial": "s_dev_a"}))
        ack = json.loads(ws_a.receive_text())
        assert ack["type"] == "auth_ack"
        assert ack["status"] == "authenticated"

        # Atacante com credencial de s_dev_b tenta assumir s_dev_a
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s_dev_a") as ws_atk:
                ws_atk.send_text(json.dumps({"type": "auth", "token": "tok_secret_b_456", "serial": "s_dev_a"}))
                ws_atk.receive_text()
        assert exc_info.value.code == 1008

        # Atacante tenta usar credencial de s_dev_b num serial não-provisionado s_other_99
        with pytest.raises(WebSocketDisconnect) as exc_info2:
            with client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s_other_99") as ws_atk2:
                ws_atk2.send_text(json.dumps({"type": "auth", "token": "tok_secret_b_456", "serial": "s_other_99"}))
                ws_atk2.receive_text()
        assert exc_info2.value.code == 1008

        # Comprova que ws_a continua ativo e operacional
        ws_a.send_text(json.dumps({"type": "auth"}))
        ack2 = json.loads(ws_a.receive_text())
        assert ack2["status"] == "authenticated"


def test_03_immediate_revocation_during_active_session_and_multiple_connections():
    """3. Revogação durante sessão ativa, inativa e com múltiplas conexões sem afetar os demais."""
    _run(db.register_device_credential("s_rev_active", "Scanner_CAN", "tok_rev_active"))
    _run(db.register_device_credential("s_rev_inactive", "Scanner_CAN", "tok_rev_inactive"))
    _run(db.register_device_credential("s_keep_1", "Scanner_CAN", "tok_keep_1"))
    _run(db.register_device_credential("s_keep_2", "Osciloscopio", "tok_keep_2"))

    assert _run(db.revoke_device_credential("s_rev_inactive")) is True

    client = TestClient(app)
    with client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s_rev_active") as ws_target, \
         client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s_keep_1") as ws_k1, \
         client.websocket_connect("/ws/esp32?type=Osciloscopio&serial=s_keep_2") as ws_k2:

        ws_target.send_text(json.dumps({"type": "auth", "token": "tok_rev_active", "serial": "s_rev_active"}))
        assert json.loads(ws_target.receive_text())["status"] == "authenticated"

        ws_k1.send_text(json.dumps({"type": "auth", "token": "tok_keep_1", "serial": "s_keep_1"}))
        assert json.loads(ws_k1.receive_text())["status"] == "authenticated"

        ws_k2.send_text(json.dumps({"type": "auth", "token": "tok_keep_2", "serial": "s_keep_2"}))
        assert json.loads(ws_k2.receive_text())["status"] == "authenticated"

        # Revoga s_rev_active com sessão ativa
        resp = client.post("/api/workshops/devices/s_rev_active/revoke")
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

        # Mensagem posterior do dispositivo revogado não é aceita e socket está encerrado
        with pytest.raises(Exception):
            ws_target.send_text(json.dumps({"type": "live_data", "pid": "010C", "raw_int": 4000}))
            ws_target.receive_text()

        # Os demais dispositivos permanecem operacionais
        ws_k1.send_text(json.dumps({"type": "auth"}))
        assert json.loads(ws_k1.receive_text())["serial"] == "s_keep_1"

        ws_k2.send_text(json.dumps({"type": "auth"}))
        assert json.loads(ws_k2.receive_text())["serial"] == "s_keep_2"


def test_04_reconnection_rejected_after_revocation():
    """4. Reconexão após revogação é sumariamente bloqueada."""
    _run(db.register_device_credential("s_rev_reconn", "Scanner_CAN", "tok_rev_reconn"))
    _run(db.revoke_device_credential("s_rev_reconn"))

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_reconn:
        with client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s_rev_reconn") as ws_re:
            ws_re.send_text(json.dumps({"type": "auth", "token": "tok_rev_reconn", "serial": "s_rev_reconn"}))
            ws_re.receive_text()
    assert exc_reconn.value.code == 1008


def test_05_mandatory_initial_authentication_before_data():
    """5. Autenticação inicial obrigatória no WebSocket: nenhum dado aceito antes da autenticação."""
    session = _run(db.create_session("Auth Gate Test", "renault_trafic_m9r"))
    sid = session["id"]

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_node:
        with client.websocket_connect("/ws/node/unauth_node") as ws_node:
            ws_node.send_text(json.dumps({"type": "can_frame", "id": "0x120", "dlc": 8, "data": [1, 2, 3, 4]}))
            ws_node.receive_text()
    assert exc_node.value.code == 1008

    with pytest.raises(WebSocketDisconnect) as exc_esp:
        with client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s2001") as ws_esp:
            ws_esp.send_text(json.dumps({"type": "live_data", "pid": "010C", "raw_int": 3000}))
            ws_esp.receive_text()
    assert exc_esp.value.code == 1008

    sess_data = _run(db.get_session_detail(sid))
    assert sess_data["can_count"] == 0


def test_06_no_tokens_in_urls_or_logs():
    """6. Ausência de tokens nas URLs dos firmwares e redação automática de tokens nos logs."""
    repo_root = Path(__file__).resolve().parents[2]
    fw_files = [
        repo_root / "firmware/AgentCar_Scanner/AgentCar_Scanner.ino",
        repo_root / "firmware/AgentCar_Oscilloscope/AgentCar_Oscilloscope.ino",
        repo_root / "firmware/AguiaCar_FleetTracker/AguiaCar_FleetTracker.ino",
        repo_root / "firmware/esp32s3/esp32s3_can_sniffer/esp32s3_can_sniffer.ino",
    ]
    for fw in fw_files:
        content = fw.read_text(encoding="utf-8")
        assert '"/ws/esp32?token="' not in content, f"Token exposto na URL em {fw}"

    secret_val = "SUPER_SECRET_DEVICE_TOKEN_999"
    raw_log = (
        f'GET /ws/esp32?token={secret_val}&serial=s2001 '
        f'payload={{"type":"auth","token":"{secret_val}"}} '
        f'Authorization: Bearer {secret_val}'
    )
    record = logging.LogRecord("cardiag.websockets", logging.INFO, "", 1, raw_log, None, None)
    flt = SensitiveTokenLogFilter()
    flt.filter(record)
    assert secret_val not in record.msg
    assert "[REDACTED]" in record.msg


def test_07_authentication_timeout():
    """7. Timeout curto de autenticação fecha conexões que não enviam credenciais a tempo."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s2001&auth_timeout=0.15") as ws:
            time.sleep(0.25)
            ws.receive_text()
    assert exc_info.value.code == 1008


def test_08_reconnection_after_network_failure():
    """8. Reconexão limpa após falha de rede utilizando credencial individual via handshake."""
    _run(db.register_device_credential("s_net_drop", "Scanner_CAN", "tok_net_drop_777"))
    client = TestClient(app)

    with client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s_net_drop") as ws1:
        ws1.send_text(json.dumps({"type": "auth", "token": "tok_net_drop_777", "serial": "s_net_drop"}))
        assert json.loads(ws1.receive_text())["status"] == "authenticated"

        with client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s_net_drop") as ws2:
            ws2.send_text(json.dumps({"type": "auth", "token": "tok_net_drop_777", "serial": "s_net_drop"}))
            ack2 = json.loads(ws2.receive_text())
            assert ack2["status"] == "authenticated"
            assert ack2["serial"] == "s_net_drop"


def test_09_can_buffer_with_sqlite_unavailable_over_5000_frames(monkeypatch):
    """9. Buffer CAN com SQLite indisponível (> 5.000 frames transferidos para spool em disco sem perda)."""
    async def _scenario():
        sess = await db.create_session("Spool Outage Test", "renault_trafic_m9r")
        sid = sess["id"]
        monkeypatch.setattr(db, "_MAX_FLUSH_RETRIES", 1)
        monkeypatch.setattr(db, "_BATCH_SIZE", 500)

        @asynccontextmanager
        async def broken_db():
            raise RuntimeError("SQLITE_DISK_IO_OUTAGE")
            yield

        total_frames = 5200
        with patch.object(db, "get_db", side_effect=broken_db):
            for i in range(total_frames):
                await db.persist_can_frame(sid, {
                    "id": "0x120",
                    "dlc": 4,
                    "data": [0x01, 0x02, 0x03, 0x04],
                    "ts": f"2026-11-17T15:00:{i:06d}Z",
                    "frame_uid": f"uid_outage_{i:05d}",
                })
            await db.flush_pending()

        st = db.get_can_buffer_status()
        assert st["dropped_frames"] == 0
        assert st["spool_frames"] == total_frames
        assert db._get_spool_path().exists()

    _run(_scenario())


def test_10_spool_recovery_after_server_restart(monkeypatch):
    """10. Recuperação do spool após reinício do servidor e remoção do arquivo temporário pós-commit."""
    async def _scenario():
        sess = await db.create_session("Restart Recovery Test", "renault_trafic_m9r")
        sid = sess["id"]

        records = [
            (sid, f"2026-11-17T15:01:{i:06d}Z", "0x120", 4, "01 02 03 04", "RPM", f"uid_restart_{i:04d}")
            for i in range(150)
        ]
        db._write_spool_records_atomic(records)
        assert db._get_spool_path().exists()

        # Simula reinício do servidor chamando init_db()
        await db.init_db()
        assert not db._get_spool_path().exists()

        detail = await db.get_session_detail(sid)
        assert detail["can_count"] == 150

    _run(_scenario())


def test_11_fifo_order_preserved_after_recovery(monkeypatch):
    """11. Ordem estrita FIFO preservada após recuperação do spool e drenagem combinada."""
    async def _scenario():
        sess = await db.create_session("FIFO Order Test", "renault_trafic_m9r")
        sid = sess["id"]
        monkeypatch.setattr(db, "_MAX_FLUSH_RETRIES", 1)

        @asynccontextmanager
        async def broken_db():
            raise RuntimeError("SQLITE_DOWN")
            yield

        # Ingestão de 60 frames com SQLite fora do ar (vão para o spool em disco)
        with patch.object(db, "get_db", side_effect=broken_db):
            for i in range(60):
                await db.persist_can_frame(sid, {
                    "id": "0x120",
                    "dlc": 2,
                    "data": [0xAA, 0xBB],
                    "ts": f"T_SEQ_{i:04d}",
                    "frame_uid": f"fifo_uid_{i:04d}",
                })
            await db.flush_pending()

        # SQLite volta e mais 25 frames chegam em memória RAM
        for i in range(60, 85):
            await db.persist_can_frame(sid, {
                "id": "0x120",
                "dlc": 2,
                "data": [0xCC, 0xDD],
                "ts": f"T_SEQ_{i:04d}",
                "frame_uid": f"fifo_uid_{i:04d}",
            })
        await db.flush_pending()

        async with db.get_db() as conn:
            async with conn.execute(
                "SELECT frame_uid FROM can_logs WHERE session_id = ? ORDER BY id ASC",
                (sid,)
            ) as cur:
                rows = await cur.fetchall()

        assert len(rows) == 85
        for idx, r in enumerate(rows):
            assert r["frame_uid"] == f"fifo_uid_{idx:04d}"

    _run(_scenario())


def test_12_deduplication_protection():
    """12. Ausência de duplicações (idempotência garantida por frame_uid UNIQUE e INSERT OR IGNORE)."""
    async def _scenario():
        sess = await db.create_session("Deduplication Test", "renault_trafic_m9r")
        sid = sess["id"]

        batch_1 = [
            (sid, f"T_{i:03d}", "0x120", 4, "01 02 03 04", "RPM", f"dup_uid_{i:03d}")
            for i in range(30)
        ]
        await db._insert_can_records_with_retry(batch_1)

        # Reproduz lote com 20 frames repetidos + 10 frames inéditos
        batch_2 = [
            (sid, f"T_{i:03d}", "0x120", 4, "01 02 03 04", "RPM", f"dup_uid_{i:03d}")
            for i in range(10, 40)
        ]
        db._write_spool_records_atomic(batch_2)
        await db.recover_can_spool()

        detail = await db.get_session_detail(sid)
        assert detail["can_count"] == 40

    _run(_scenario())


def test_13_secondary_storage_saturation_and_loss_accounting(monkeypatch):
    """13. Saturação do armazenamento secundário: alerta crítico emitido e perda inevitável contabilizada."""
    async def _scenario():
        sess = await db.create_session("Saturation Test", "renault_trafic_m9r")
        sid = sess["id"]

        monkeypatch.setattr(db, "_MAX_SPOOL_FRAMES", 30)
        monkeypatch.setattr(db, "_MAX_CAN_BUFFER", 30)
        monkeypatch.setattr(db, "_BATCH_SIZE", 10)
        monkeypatch.setattr(db, "_MAX_FLUSH_RETRIES", 1)

        @asynccontextmanager
        async def broken_db():
            raise RuntimeError("SQLITE_UNAVAILABLE")
            yield

        with patch.object(db, "get_db", side_effect=broken_db):
            for i in range(75):
                await db.persist_can_frame(sid, {"id": "0x201", "dlc": 2, "data": [1, 2], "ts": f"T{i:03d}"})
            await db.flush_pending()

        st = db.get_can_buffer_status()
        assert st["spool_saturation_alert"] is True
        assert st["overflow_alert"] is True
        assert st["spool_frames"] == 30
        assert st["buffer_size"] == 30
        assert st["dropped_frames"] == 15

    _run(_scenario())


def test_14_repeated_write_failures_resilience(monkeypatch):
    """14. Falhas repetidas de escrita no SQLite e no spool em disco tratadas com retentativas e alertas."""
    async def _scenario():
        sess = await db.create_session("Write Failure Test", "renault_trafic_m9r")
        sid = sess["id"]

        with patch("builtins.open", side_effect=OSError("DISK_IO_FAILURE")):
            written = db._append_to_disk_spool([(sid, "T999", "0x120", 1, "FF", "RPM", "uid_err_1")])
            assert written == 0

        st = db.get_can_buffer_status()
        assert st["spool_write_errors"] >= 3
        assert st["spool_saturation_alert"] is True

    _run(_scenario())


def test_15_compatibility_with_all_four_firmwares():
    """15. Compatibilidade comprovada com os 4 projetos de firmware existentes."""
    client = TestClient(app)

    # 1. AgentCar_Scanner (s2000)
    with client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s2000") as ws_scan:
        ws_scan.send_text(json.dumps({
            "type": "hw_info",
            "token": WS_TOKEN,
            "serial": "s2000",
            "device_type": "Scanner_CAN",
            "fw_version": "v2.5.2",
            "proto": "can",
            "pin": 7,
            "module": "ECU",
        }))
        ack = json.loads(ws_scan.receive_text())
        assert ack["type"] == "auth_ack"
        assert ack["serial"] == "s2000"

    # 2. AgentCar_Oscilloscope (o2000)
    with client.websocket_connect("/ws/esp32?type=Osciloscopio&serial=o2000") as ws_osc:
        ws_osc.send_text(json.dumps({
            "type": "hw_info",
            "token": WS_TOKEN,
            "serial": "o2000",
            "device_type": "Osciloscopio",
            "fw_version": "v2.5.2",
        }))
        ack = json.loads(ws_osc.receive_text())
        assert ack["type"] == "auth_ack"
        assert ack["serial"] == "o2000"

    # 3. esp32s3_can_sniffer (s2001)
    with client.websocket_connect("/ws/esp32?type=Scanner_CAN&serial=s2001") as ws_snif:
        ws_snif.send_text(json.dumps({
            "type": "auth",
            "token": WS_TOKEN,
            "serial": "s2001",
            "device_type": "Scanner_CAN",
            "fw_version": "v2.5.2",
        }))
        ack = json.loads(ws_snif.receive_text())
        assert ack["type"] == "auth_ack"
        assert ack["serial"] == "s2001"

    # 4. AguiaCar_FleetTracker (a2000)
    resp = client.post(
        "/api/fleet/telemetry_ingest",
        headers={"X-Device-Token": WS_TOKEN, "X-Device-Serial": "a2000"},
        json={
            "type": "aguiacar_telemetry",
            "device_id": "a2000",
            "fw_version": "v2.6.0-wifi-router",
            "gps": {"valid": True, "lat": 42.58, "lon": -5.58, "speed_kmh": 60.0},
            "telemetry": {"connected": True, "rpm": 2100, "speed_obd": 60, "temp_c": 88.0, "battery_v": 14.1},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"
