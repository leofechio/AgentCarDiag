"""
websockets.py — Router de Endpoints WebSocket (Hardware, Gateway ESP32, Clientes Web e Telemetria)
AgentCarDiag Server
"""

import asyncio
import json
import logging
import re
import secrets
import uuid
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.config import WS_TOKEN
from app.websocket_manager import manager, gateway_manager
from app import database as db
from app.fleet_engine import fleet_engine

logger = logging.getLogger("cardiag.websockets")

router = APIRouter(tags=["WebSockets"])

# Prazo curto obrigatório para conclusão do handshake de autenticação inicial via mensagem WS
AUTH_HANDSHAKE_TIMEOUT = 2.5

_PROXY_FORWARD_HEADERS = (
    "x-forwarded-for",
    "x-real-ip",
    "forwarded",
    "cf-connecting-ip",
    "true-client-ip",
    "x-client-ip",
)


class SensitiveTokenLogFilter(logging.Filter):
    """Garante que nenhum token apareça em logs de aplicação, exceções ou access logs."""
    _URL_TOKEN_RE = re.compile(r"([?&]token=)[^&\s\"']+", re.IGNORECASE)
    _JSON_TOKEN_RE = re.compile(r'("token"\s*:\s*")[^"]+(")', re.IGNORECASE)
    _BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-~+/]+=*", re.IGNORECASE)

    @classmethod
    def sanitize(cls, text: str) -> str:
        if not isinstance(text, str):
            return text
        text = cls._URL_TOKEN_RE.sub(r"\1[REDACTED]", text)
        text = cls._JSON_TOKEN_RE.sub(r"\1[REDACTED]\2", text)
        text = cls._BEARER_RE.sub(r"\1[REDACTED]", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.sanitize(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    self.sanitize(a) if isinstance(a, str) else a
                    for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: (self.sanitize(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
        return True


def install_token_log_redaction() -> None:
    flt = SensitiveTokenLogFilter()
    for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "cardiag.websockets", "cardiag.db", "api"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, SensitiveTokenLogFilter) for f in lg.filters):
            lg.addFilter(flt)


install_token_log_redaction()


def _extract_header_token(websocket: WebSocket) -> str | None:
    hdrs = getattr(websocket, "headers", None) or {}
    hdr_tok = hdrs.get("x-device-token")
    if hdr_tok:
        return hdr_tok.strip()
    auth_hdr = hdrs.get("authorization", "")
    if auth_hdr.lower().startswith("bearer "):
        return auth_hdr[7:].strip()
    return None


# ─── Handlers Auxiliares ──────────────────────────────────────────────────────

async def _handle_hardware_ws(websocket: WebSocket, node_id: str, token: str = None, auth_timeout: float = None) -> None:
    """
    Handler compartilhado para conexões WebSocket de nós de hardware.
    Suporta autenticação por mensagem inicial de handshake (sem token na URL),
    cabeçalhos ou modo de transição controlado, e restringe virtual_car_node ao loopback sem proxy.
    """
    is_virtual_simulator = (node_id == "virtual_car_node")
    presented_token = _extract_header_token(websocket) or token
    already_accepted = False

    if is_virtual_simulator and presented_token is None:
        # Permitir estritamente se for conexão comprovadamente local direta (sem proxy intermediário)
        client_host = getattr(websocket.client, "host", "") if websocket.client else ""
        hdrs = getattr(websocket, "headers", None) or {}
        has_proxy_hdr = any(h in hdrs for h in _PROXY_FORWARD_HEADERS)
        if client_host not in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost", "testclient") or has_proxy_hdr:
            logger.warning(
                f"[HW] Bloqueada tentativa de conexão não-autenticada de virtual_car_node "
                f"(host={client_host!r}, proxy_headers={has_proxy_hdr})"
            )
            await websocket.close(code=1008)
            return
    else:
        if presented_token is None:
            # Autenticação obrigatória via mensagem inicial de handshake dentro do prazo curto
            try:
                await websocket.accept()
                already_accepted = True
            except Exception:
                return

            timeout_val = min(max(auth_timeout or AUTH_HANDSHAKE_TIMEOUT, 0.1), 10.0)
            try:
                first_raw = await asyncio.wait_for(websocket.receive_text(), timeout=timeout_val)
            except asyncio.TimeoutError:
                logger.warning(f"[HW] Timeout de autenticação inicial ({timeout_val}s) para node={node_id!r}.")
                await websocket.close(code=1008)
                return
            except Exception:
                return

            try:
                first_payload = json.loads(first_raw)
            except Exception:
                logger.warning(f"[HW] Frame inicial inválido antes da autenticação para node={node_id!r}.")
                await websocket.close(code=1008)
                return

            if not isinstance(first_payload, dict) or first_payload.get("type") not in ("auth", "handshake", "hw_info"):
                logger.warning(
                    f"[HW] Dados rejeitados antes da conclusão da autenticação de node={node_id!r}."
                )
                await websocket.close(code=1008)
                return

            presented_token = str(first_payload.pop("token", "") or "").strip() or None
            if first_payload.get("serial") or first_payload.get("node_id"):
                node_id = str(first_payload.get("serial") or first_payload.get("node_id")).strip()

        is_auth, auth_mode = await db.verify_device_authentication(node_id, presented_token)
        if not is_auth:
            logger.warning(f"[HW] Acesso negado para node={node_id!r}. Razão: {auth_mode}")
            await websocket.close(code=1008)
            return

    await manager.connect_hardware(websocket, node_id, already_accepted=already_accepted)
    if already_accepted:
        try:
            await websocket.send_text(json.dumps({"type": "auth_ack", "status": "authenticated", "node_id": node_id}))
        except Exception:
            pass

    try:
        while True:
            raw = await websocket.receive_text()

            # Verifica revogação imediata antes de aceitar qualquer dado
            if await db.is_serial_revoked_async(node_id):
                logger.warning(f"[HW] Mensagem bloqueada: credencial revogada em sessão ativa de node={node_id!r}.")
                await manager.evict_hardware_node(node_id)
                try:
                    await websocket.close(code=1008)
                except Exception:
                    pass
                break

            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    payload.pop("token", None)
                    msg_type = payload.get("type")

                    # Handshake informativo
                    if msg_type in ("handshake", "auth"):
                        logger.info(
                            f"[HW] Handshake de {node_id!r}: "
                            f"hw={payload.get('hw')} fw={payload.get('fw')}"
                        )
                        continue

                    # Persistência na sessão ativa
                    session_id = await db.get_active_session_id()
                    if session_id:
                        if msg_type == "can_frame":
                            await db.persist_can_frame(session_id, payload)
                        elif msg_type == "adc_burst":
                            await db.persist_osc_capture(session_id, payload)
                            await db.update_session_timestamp(session_id)

                    raw = json.dumps(payload, separators=(",", ":"))

            except json.JSONDecodeError:
                pass

            # Retransmite aos clientes web conectados
            await manager.relay_hardware_message(websocket, raw)

    except WebSocketDisconnect:
        logger.info(f"[HW] Node {node_id} desconectado normalmente")
    except Exception as e:
        logger.error(f"[HW] Erro inesperado do node {node_id}: {SensitiveTokenLogFilter.sanitize(str(e))}")
    finally:
        await db.flush_pending()
        await manager.disconnect_hardware(websocket)


# ─── Endpoints WebSocket ──────────────────────────────────────────────────────

@router.websocket("/ws/hardware")
async def hardware_endpoint(
    websocket: WebSocket,
    node_id: str = Query(default=None, description="Hardware node identifier"),
    token: str = Query(default=None, description="Auth token (modo transição)"),
    auth_timeout: float = Query(default=None, description="Timeout opcional de handshake"),
):
    """WebSocket para nós de hardware ESP32-S3."""
    resolved_id = node_id or f"node-{uuid.uuid4().hex[:6]}"
    await _handle_hardware_ws(websocket, resolved_id, token=token, auth_timeout=auth_timeout)


@router.websocket("/ws/node/{node_id}")
async def node_endpoint(
    websocket: WebSocket,
    node_id: str,
    token: str = Query(default=None, description="Auth token (modo transição)"),
    auth_timeout: float = Query(default=None, description="Timeout opcional de handshake"),
):
    """WebSocket para nós de hardware por path parameter."""
    await _handle_hardware_ws(websocket, node_id, token=token, auth_timeout=auth_timeout)


@router.websocket("/ws/client")
async def client_endpoint(
    websocket: WebSocket,
    client_id: str = Query(default=None, description="Identificador opcional do cliente"),
):
    """WebSocket para clientes de interface web / mobile."""
    resolved_id = client_id or f"client-{uuid.uuid4().hex[:6]}"
    await manager.connect_client(websocket, resolved_id)

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                payload = json.loads(raw)
                cmd = payload.get("cmd", "")

                if cmd == "ping":
                    await websocket.send_text(
                        json.dumps({"type": "pong", "client_id": resolved_id})
                    )
                elif cmd in ("can_start", "can_stop", "osc_capture", "osc_stop"):
                    target = payload.get("target_node") or payload.get("target_serial") or payload.get("serial")
                    count = await manager.route_command_to_hardware(raw, target)
                    await websocket.send_text(
                        json.dumps({
                            "type": "cmd_ack",
                            "cmd": cmd,
                            "nodes_reached": count,
                        })
                    )
                elif cmd in ("set_protocol", "set_module_pin", "set_obd_pin", "obd_send", "start_live_stream", "stop_live_stream"):
                    target_serial = payload.get("target_serial") or payload.get("serial") or payload.get("target_node")
                    await gateway_manager.route_to_esp32(payload, target_serial=target_serial)
                    await websocket.send_text(
                        json.dumps({
                            "type": "cmd_ack",
                            "cmd": cmd,
                            "status": "routed"
                        })
                    )
                else:
                    logger.debug(f"[CLI] Comando desconhecido de {resolved_id}: {cmd!r}")

            except json.JSONDecodeError:
                logger.warning(f"[CLI] Não-JSON do cliente {resolved_id}: {raw[:80]}")

    except WebSocketDisconnect:
        logger.info(f"[CLI] Cliente {resolved_id} desconectado normalmente")
    except Exception as e:
        logger.error(f"[CLI] Erro inesperado do cliente {resolved_id}: {e}")
    finally:
        await manager.disconnect_client(websocket)


@router.websocket("/ws/esp32")
async def esp32_endpoint(
    websocket: WebSocket,
    token: str = Query(None),
    type: str = Query("Desconhecido"),
    serial: str = Query(None),
    fw: str = Query(None),
    auth_timeout: float = Query(None),
):
    """
    Gateway de hardware ESP32-S3 com:
    - Autenticação por mensagem inicial de handshake (sem exposição de token na URL)
    - Credencial individual vinculada ao serial + proteção anti-takeover
    - Revogação imediata com desconexão ativa e bloqueio de mensagens subsequentes
    """
    presented_token = _extract_header_token(websocket) or token
    already_accepted = False
    initial_hw_info_payload = None

    if presented_token is None:
        # Aceita transporte em quarentena e aguarda mensagem inicial de autenticação dentro do prazo curto
        try:
            await websocket.accept()
            already_accepted = True
        except Exception:
            return

        timeout_val = min(max(auth_timeout or AUTH_HANDSHAKE_TIMEOUT, 0.1), 10.0)
        try:
            first_raw = await asyncio.wait_for(websocket.receive_text(), timeout=timeout_val)
        except asyncio.TimeoutError:
            logger.warning(f"[Gateway] Timeout de autenticação inicial ({timeout_val}s) no endpoint /ws/esp32.")
            await websocket.close(code=1008)
            return
        except Exception:
            return

        try:
            auth_doc = json.loads(first_raw)
        except Exception:
            logger.warning("[Gateway] Frame inicial não-JSON rejeitado antes da autenticação.")
            await websocket.close(code=1008)
            return

        if not isinstance(auth_doc, dict) or auth_doc.get("type") not in ("auth", "handshake", "hw_info"):
            logger.warning(
                f"[Gateway] Dados do dispositivo ({auth_doc.get('type') if isinstance(auth_doc, dict) else 'raw'}) "
                "rejeitados antes da autenticação!"
            )
            await websocket.close(code=1008)
            return

        presented_token = str(auth_doc.pop("token", "") or "").strip() or None
        if not presented_token:
            logger.warning("[Gateway] Handshake inicial sem credencial rejeitado.")
            await websocket.close(code=1008)
            return

        if auth_doc.get("serial"):
            serial = str(auth_doc["serial"])
        if auth_doc.get("device_type") or auth_doc.get("hw"):
            type = str(auth_doc.get("device_type") or auth_doc.get("hw"))
        if auth_doc.get("fw_version") or auth_doc.get("fw"):
            fw = str(auth_doc.get("fw_version") or auth_doc.get("fw"))
        if auth_doc.get("type") == "hw_info":
            initial_hw_info_payload = auth_doc

    resolved_serial = serial.strip().lower() if serial else None
    if not resolved_serial:
        if "scan" in type.lower():
            resolved_serial = "s2001"
        elif "osc" in type.lower():
            resolved_serial = "o2001"
        elif "aguia" in type.lower() or "4g" in type.lower():
            resolved_serial = "a2001"
        else:
            resolved_serial = f"dev-{type.lower()}"

    is_auth, auth_mode = await db.verify_device_authentication(resolved_serial, presented_token)
    if not is_auth:
        logger.warning(f"[Gateway] Acesso negado para serial={resolved_serial}. Razão: {auth_mode}")
        await websocket.close(code=1008)
        return

    connected = await gateway_manager.connect_esp32(
        websocket,
        device_type=type,
        serial=resolved_serial,
        fw_version=fw,
        auth_mode=auth_mode,
        already_accepted=already_accepted,
    )
    if not connected:
        logger.warning(f"[Gateway] Takeover bloqueado para serial={resolved_serial}.")
        await websocket.close(code=1008)
        return

    if already_accepted:
        try:
            await websocket.send_text(
                json.dumps({
                    "type": "auth_ack",
                    "status": "authenticated",
                    "serial": resolved_serial,
                    "auth_mode": auth_mode,
                })
            )
            if initial_hw_info_payload:
                await gateway_manager.handle_esp32_message(initial_hw_info_payload, type, serial=resolved_serial)
        except Exception:
            pass

    try:
        while True:
            raw = await websocket.receive_text()

            # Verifica imediatamente se a credencial foi revogada durante a sessão ativa
            if await db.is_serial_revoked_async(resolved_serial):
                logger.warning(
                    f"[Gateway] Mensagem rejeitada: credencial de serial={resolved_serial} foi revogada com sessão ativa."
                )
                await gateway_manager.evict_revoked_device(resolved_serial)
                try:
                    await websocket.close(code=1008)
                except Exception:
                    pass
                break

            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    # Remove qualquer campo token por segurança antes de logs ou retransmissão
                    payload.pop("token", None)
                    if payload.get("type") == "auth":
                        await websocket.send_text(
                            json.dumps({"type": "auth_ack", "status": "authenticated", "serial": resolved_serial})
                        )
                        continue

                # Persistência em sessão ativa
                session_id = await db.get_active_session_id()
                if session_id:
                    msg_type = payload.get("type")
                    if msg_type == "live_data":
                        pid = payload.get("pid")
                        raw_int = payload.get("raw_int", 0)

                        metric_name = pid
                        metric_value = raw_int

                        # Conversões OBD Padrão
                        if pid == "010C":
                            metric_name = "RPM"
                            metric_value = raw_int / 4.0
                        elif pid == "010D":
                            metric_name = "Speed"
                        elif pid == "0105":
                            metric_name = "ECT"
                            metric_value = raw_int - 40
                        elif pid == "010F":
                            metric_name = "IAT"
                            metric_value = raw_int - 40
                        elif pid == "0110":
                            metric_name = "MAF"
                            metric_value = raw_int / 100.0

                        if metric_name == "RPM":
                            payload["engine_rpm"] = metric_value
                        if metric_name == "Speed":
                            payload["vehicle_speed"] = metric_value

                        await db.persist_obd_metric(session_id, metric_name, metric_value)

                    elif msg_type == "ai_response":
                        pid_req = payload.get("pid_req", "unknown")
                        val = payload.get("parsed_value", 0)
                        raw_resp = payload.get("raw", "")
                        await db.persist_obd_metric(session_id, f"PID_{pid_req}", val, raw_resp)
                    elif msg_type == "ble_pair_status":
                        gateway_manager.ble_status = payload
                    elif msg_type in ("aguiacar_telemetry", "obd_disconnect_alert"):
                        await fleet_engine.process_telemetry(payload)
                    elif msg_type == "log":
                        try:
                            from pathlib import Path as _Path
                            msg_clean = SensitiveTokenLogFilter.sanitize(str(payload.get("message", "")))
                            log_path = _Path(__file__).resolve().parents[2] / "esp32_debug.log"
                            with open(log_path, "a", encoding="utf-8") as f:
                                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg_clean}\n")
                        except Exception:
                            pass

                # Encaminhar mensagens ao gateway para os navegadores
                await gateway_manager.handle_esp32_message(payload, type, serial=resolved_serial)

            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        logger.info("[Gateway] ESP32 desconectado normalmente")
    except Exception as e:
        logger.error(f"[Gateway] Erro no ESP32: {SensitiveTokenLogFilter.sanitize(str(e))}")
    finally:
        await gateway_manager.disconnect_esp32(websocket, type, serial=resolved_serial)


@router.websocket("/ws/telemetry")
async def telemetry_endpoint(websocket: WebSocket):
    """WebSocket de telemetria e comandos do navegador para o hardware."""
    await gateway_manager.connect_web_client(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
                cmd = payload.get("command") or payload.get("cmd")
                if cmd in (
                    "scan_ble", "pair_ble", "unpair_ble", "terminal", "obd_send",
                    "start_live_stream", "stop_live_stream", "set_live_pids",
                    "query_dtc", "clear_dtc", "status", "abort_all",
                    "set_protocol", "set_module_pin", "set_obd_pin"
                ):
                    target_serial = payload.get("target_serial") or payload.get("serial") or payload.get("target_node")
                    await gateway_manager.route_to_esp32(payload, target_serial=target_serial)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        logger.info("[Gateway] Cliente de telemetria desconectado normalmente")
    except Exception as e:
        logger.error(f"[Gateway] Erro no cliente de telemetria: {e}")
    finally:
        await gateway_manager.disconnect_web_client(websocket)
