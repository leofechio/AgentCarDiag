"""
websockets.py — Router de Endpoints WebSocket (Hardware, Gateway ESP32, Clientes Web e Telemetria)
AgentCarDiag Server
"""

import json
import logging
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


# ─── Handlers Auxiliares ──────────────────────────────────────────────────────

async def _handle_hardware_ws(websocket: WebSocket, node_id: str) -> None:
    """
    Handler compartilhado para conexões WebSocket de nós de hardware.
    Persiste quadros CAN e rajadas ADC na sessão ativa e retransmite para os navegadores.
    """
    await manager.connect_hardware(websocket, node_id)

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                payload = json.loads(raw)
                msg_type = payload.get("type")

                # Handshake informativo
                if msg_type == "handshake":
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

            except json.JSONDecodeError:
                pass

            # Retransmite aos clientes web conectados
            await manager.relay_hardware_message(websocket, raw)

    except WebSocketDisconnect:
        logger.info(f"[HW] Node {node_id} desconectado normalmente")
    except Exception as e:
        logger.error(f"[HW] Erro inesperado do node {node_id}: {e}")
    finally:
        await db.flush_pending()
        await manager.disconnect_hardware(websocket)


# ─── Endpoints WebSocket ──────────────────────────────────────────────────────

@router.websocket("/ws/hardware")
async def hardware_endpoint(
    websocket: WebSocket,
    node_id: str = Query(default=None, description="Hardware node identifier"),
):
    """WebSocket para nós de hardware ESP32-S3 (estilo query-param legado)."""
    resolved_id = node_id or f"node-{uuid.uuid4().hex[:6]}"
    await _handle_hardware_ws(websocket, resolved_id)


@router.websocket("/ws/node/{node_id}")
async def node_endpoint(websocket: WebSocket, node_id: str):
    """WebSocket para nós de hardware por path parameter (novo padrão)."""
    await _handle_hardware_ws(websocket, node_id)


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
                    target = payload.get("target_node")
                    count = await manager.route_command_to_hardware(raw, target)
                    await websocket.send_text(
                        json.dumps({
                            "type": "cmd_ack",
                            "cmd": cmd,
                            "nodes_reached": count,
                        })
                    )
                elif cmd in ("set_protocol", "set_module_pin", "set_obd_pin", "obd_send", "start_live_stream", "stop_live_stream"):
                    await gateway_manager.route_to_esp32(payload)
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
    fw: str = Query(None)
):
    """Gateway de hardware ESP32-S3 com autenticação por token e roteamento multi-serial."""
    if not token or not secrets.compare_digest(token, WS_TOKEN):
        logger.warning("[Gateway] Acesso negado. Token inválido.")
        await websocket.close(code=1008)
        return

    resolved_serial = serial.strip().lower() if serial else None
    await gateway_manager.connect_esp32(websocket, device_type=type, serial=resolved_serial, fw_version=fw)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)

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
                            with open("/home/leonardof/AgentCarDiag/server/esp32_debug.log", "a") as f:
                                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {payload.get('message', '')}\n")
                        except Exception:
                            pass

                # Encaminhar mensagens ao gateway para os navegadores
                await gateway_manager.handle_esp32_message(payload, type, serial=resolved_serial)

            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        logger.info("[Gateway] ESP32 desconectado normalmente")
    except Exception as e:
        logger.error(f"[Gateway] Erro no ESP32: {e}")
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
                    await gateway_manager.route_to_esp32(payload)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        logger.info("[Gateway] Cliente de telemetria desconectado normalmente")
    except Exception as e:
        logger.error(f"[Gateway] Erro no cliente de telemetria: {e}")
    finally:
        await gateway_manager.disconnect_web_client(websocket)
