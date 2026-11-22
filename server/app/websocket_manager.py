import asyncio
import time
from typing import Optional
from fastapi import WebSocket
import json
import logging

logger = logging.getLogger("api")

SCANNER_COMMANDS = {
    "obd_send", "query_dtc", "clear_dtc", "set_protocol",
    "set_module_pin", "set_obd_pin", "start_live_stream",
    "stop_live_stream", "set_live_pids", "scan_ble", "pair_ble", "unpair_ble"
}
OSCILLOSCOPE_COMMANDS = {
    "osc_capture", "osc_stop"
}

# Basic ConnectionManager for Web clients
class ConnectionManager:
    def __init__(self):
        self.client_connections: list[WebSocket] = []
        self.hardware_connections: dict[WebSocket, dict] = {}
        self.messages_relayed = 0
        self.total_hardware_connected = 0
        self.total_clients_connected = 0

    async def connect_client(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.client_connections.append(websocket)
        self.total_clients_connected += 1

    async def disconnect_client(self, websocket: WebSocket):
        if websocket in self.client_connections:
            self.client_connections.remove(websocket)

    async def connect_hardware(self, websocket: WebSocket, hw_id: str, already_accepted: bool = False):
        clean_id = str(hw_id).strip()
        # Encerra e remove qualquer conexão anterior com o mesmo hw_id (Item B)
        old_sockets = [
            ws for ws, meta in list(self.hardware_connections.items())
            if meta.get("id") == clean_id and ws != websocket
        ]
        for old_ws in old_sockets:
            logger.info(f"[HW] Encerrando conexão duplicada anterior para hw_id={clean_id}")
            if old_ws in self.hardware_connections:
                del self.hardware_connections[old_ws]
            try:
                await old_ws.close(code=1000)
            except Exception:
                pass

        if not already_accepted:
            try:
                await websocket.accept()
            except Exception:
                pass
        self.hardware_connections[websocket] = {
            "id": clean_id,
            "connected_at": time.time(),
            "messages_sent": 0
        }
        self.total_hardware_connected += 1

    async def disconnect_hardware(self, websocket: WebSocket):
        if websocket in self.hardware_connections:
            del self.hardware_connections[websocket]

    async def evict_hardware_node(self, hw_id: str) -> int:
        """Encerra imediatamente conexões ativas de um nó revogado sem afetar os demais."""
        clean_id = str(hw_id).strip().lower()
        target_sockets = [
            ws for ws, meta in list(self.hardware_connections.items())
            if str(meta.get("id", "")).strip().lower() == clean_id
        ]
        evicted = 0
        for ws in target_sockets:
            self.hardware_connections.pop(ws, None)
            try:
                await ws.close(code=1008)
            except Exception:
                pass
            evicted += 1
        return evicted

    async def broadcast_to_clients(self, message: dict):
        self.messages_relayed += 1
        dead = []
        payload = json.dumps(message, separators=(",", ":"))
        for client in self.client_connections:
            try:
                await client.send_text(payload)
            except Exception:
                dead.append(client)
        for client in dead:
            await self.disconnect_client(client)

    async def route_command_to_hardware(self, raw_data: str, target_node: Optional[str] = None) -> int:
        try:
            payload = json.loads(raw_data)
        except Exception:
            return 0

        cmd = payload.get("cmd") or payload.get("command") or ""
        target = payload.get("target_node") or payload.get("target_serial") or payload.get("serial") or target_node
        is_broadcast = not target or str(target).strip().lower() in ("all", "*", "")
        clean_target = str(target).strip().lower() if not is_broadcast else None

        reached_devices = set()
        dead = []

        for ws, meta in list(self.hardware_connections.items()):
            node_id = str(meta.get("id", "")).strip().lower()
            if not is_broadcast and node_id != clean_target:
                continue
            # Filtragem por tipo de dispositivo em broadcast (Item A)
            if is_broadcast:
                if cmd in OSCILLOSCOPE_COMMANDS and "osc" not in node_id:
                    continue
                if cmd in SCANNER_COMMANDS and "osc" in node_id:
                    continue
            try:
                await ws.send_text(json.dumps(payload, separators=(",", ":")))
                reached_devices.add(meta.get("id"))
                meta["messages_sent"] = meta.get("messages_sent", 0) + 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect_hardware(ws)

        # Também distribui para dispositivos registrados no gateway_manager (/ws/esp32)
        dead_gw = []
        for s, dev in list(gateway_manager.devices.items()):
            ws = dev.get("ws")
            clean_s = s.strip().lower()
            if not ws or ws in self.hardware_connections or clean_s in reached_devices:
                continue
            if not is_broadcast and clean_s != clean_target:
                continue
            # Filtragem por tipo de dispositivo em broadcast (Item A)
            dev_type = dev.get("type", "").lower()
            if is_broadcast:
                if cmd in OSCILLOSCOPE_COMMANDS and "osc" not in dev_type:
                    continue
                if cmd in SCANNER_COMMANDS and "osc" in dev_type:
                    continue
            try:
                await ws.send_text(json.dumps(payload, separators=(",", ":")))
                reached_devices.add(s)
            except Exception:
                dead_gw.append((ws, dev.get("type"), s))
        for ws, dtype, s in dead_gw:
            await gateway_manager.disconnect_esp32(ws, dtype, serial=s)

        # Retorna contagem de dispositivos lógicos únicos alcançados com sucesso (Item D)
        return len(reached_devices)

    async def relay_hardware_message(self, websocket: WebSocket, raw: str):
        self.messages_relayed += 1
        dead = []
        for client in self.client_connections:
            try:
                await client.send_text(raw)
            except Exception:
                dead.append(client)
        for client in dead:
            await self.disconnect_client(client)

    def get_status(self) -> dict:
        return {
            "hardware_nodes": [meta.get("id") for meta in self.hardware_connections.values()],
            "web_clients": len(self.client_connections),
            "messages_relayed": self.messages_relayed,
            "total_hardware_ever": self.total_hardware_connected,
            "total_clients_ever": self.total_clients_connected,
        }

manager = ConnectionManager()

class HardwareGatewayManager:
    def __init__(self):
        self.web_clients: list[WebSocket] = []
        # Fallback legacy dictionary for single-type lookups
        self.nodes = {
            "Scanner_CAN": {"ws": None, "ping_ms": 0, "last_seen": 0, "proto": "can", "pin": 7, "module": "ECU"},
            "Osciloscopio": {"ws": None, "ping_ms": 0, "last_seen": 0}
        }
        # Registro dinâmico de todos os aparelhos conectados por Serial (ex: 's2001', 'a2001', 'o2001')
        self.devices: dict[str, dict] = {}
        self.pending_requests = {}
        self.last_response = {}  # Captura última resposta por query (para o Dev Agent)
        self._ping_task = None
        self._revocation_watch_task = None

    def ensure_ping_loop(self):
        try:
            loop = asyncio.get_running_loop()
            if self._ping_task is None or self._ping_task.done():
                self._ping_task = loop.create_task(self.ping_loop())
            if self._revocation_watch_task is None or self._revocation_watch_task.done():
                self._revocation_watch_task = loop.create_task(self.revocation_watch_loop())
        except RuntimeError:
            pass

    async def revocation_watch_loop(self):
        """Monitora revogações (inclusive entre processos via SQLite) e encerra conexões ativas imediatamente."""
        from app import database as db
        while True:
            await asyncio.sleep(0.15)
            if not self.devices and not manager.hardware_connections:
                continue
            try:
                revoked_set = await db.get_all_revoked_serials_async()
                if not revoked_set:
                    continue
                for s in list(self.devices.keys()):
                    if s.strip().lower() in revoked_set:
                        await self.evict_revoked_device(s)
                for ws, meta in list(manager.hardware_connections.items()):
                    hw_id = str(meta.get("id", "")).strip().lower()
                    if hw_id in revoked_set:
                        await manager.evict_hardware_node(hw_id)
            except Exception:
                pass

    async def evict_revoked_device(self, serial: str) -> int:
        """
        Identifica e encerra imediatamente o socket ativo correspondente ao serial revogado,
        impedindo mensagens posteriores e preservando todos os demais dispositivos conectados.
        """
        clean_serial = serial.strip().lower()
        evicted = 0
        dev = self.devices.pop(clean_serial, None)
        ws = dev.get("ws") if dev else None

        if ws is not None:
            # Limpa referência nos nós legados apenas se apontar para este socket revogado
            for dtype, node in self.nodes.items():
                if node.get("ws") == ws:
                    node["ws"] = None
                    node["ping_ms"] = 0
            try:
                await ws.close(code=1008)
            except Exception:
                pass
            evicted += 1
            logger.warning(f"[Gateway] Conexão ativa encerrada imediatamente por revogação: serial={clean_serial}")

        evicted += await manager.evict_hardware_node(clean_serial)
        if evicted > 0:
            await self.broadcast_hardware_status()
        return evicted

    async def ping_loop(self):
        while True:
            await asyncio.sleep(2)
            now = time.time()
            
            # 1. Pings para os dispositivos registrados por serial
            for serial, dev in list(self.devices.items()):
                ws = dev.get("ws")
                if ws is not None:
                    if now - dev.get("last_seen", 0) > 6:
                        logger.warning(f"[Ping] Serial {serial} ({dev.get('type')}) timeout. Desconectando.")
                        await self.disconnect_esp32(ws, dev.get("type"), serial=serial)
                        continue
                    try:
                        await ws.send_text(json.dumps({"cmd": "ping", "time": int(now * 1000)}))
                    except Exception:
                        await self.disconnect_esp32(ws, dev.get("type"), serial=serial)
                else:
                    # Dispositivos baseados em telemetria HTTP/4G (ex: AguiaCar)
                    if now - dev.get("last_seen", 0) > 45:
                        logger.info(f"[Gateway] AguiaCar/4G Serial {serial} sem telemetria recente. Marcando offline.")
                        del self.devices[serial]
                        await self.broadcast_hardware_status()

            # 2. Pings legados para nós sem serial explícito
            for dev_type, node in list(self.nodes.items()):
                if node["ws"] is not None and not any(d.get("ws") == node["ws"] for d in self.devices.values()):
                    if now - node["last_seen"] > 6:
                        logger.warning(f"[Ping] {dev_type} timeout. Disconnecting.")
                        await self.disconnect_esp32(node["ws"], dev_type)
                        continue
                    try:
                        await node["ws"].send_text(json.dumps({"cmd": "ping", "time": int(now * 1000)}))
                    except Exception:
                        await self.disconnect_esp32(node["ws"], dev_type)

    async def connect_esp32(
        self,
        websocket: WebSocket,
        device_type: str = 'Desconhecido',
        serial: str = None,
        fw_version: str = None,
        auth_mode: str = "legacy",
        already_accepted: bool = False,
    ) -> bool:
        # Se não enviou serial na query, define um fallback automático
        if not serial:
            if "scan" in device_type.lower():
                serial = "s2001"
            elif "osc" in device_type.lower():
                serial = "o2001"
            elif "aguia" in device_type.lower() or "4g" in device_type.lower():
                serial = "a2001"
            else:
                serial = f"dev-{device_type.lower()}"

        clean_serial = serial.strip().lower()
        ws_client = getattr(websocket, "client", None)
        new_host = getattr(ws_client, "host", "") if ws_client else ""

        # Proteção contra Takeover e Usurpação de Identidade (Parte B)
        if clean_serial in self.devices:
            old_dev = self.devices[clean_serial]
            old_ws = old_dev.get("ws")
            old_auth = old_dev.get("auth_mode", "legacy")
            old_host = old_dev.get("client_host", "")

            if old_ws and old_ws != websocket:
                # 1. Dispositivo protegido por credencial individual nunca pode ser assumido por token legado
                if old_auth == "individual" and auth_mode in ("legacy", "legacy_migrating"):
                    logger.warning(
                        f"[Gateway] Bloqueado takeover de serial={clean_serial}: dispositivo protegido por credencial "
                        "individual não pode ser desconectado por token global legado."
                    )
                    return False

                # 2. Em modo legado de transição, impede que um host diferente usurpe uma sessão ativa saudável
                if auth_mode in ("legacy", "legacy_migrating") and old_host and new_host and old_host != new_host:
                    if (time.time() - old_dev.get("last_seen", 0)) < 6.0:
                        logger.warning(
                            f"[Gateway] Bloqueado takeover legado entre hosts diferentes para serial={clean_serial} "
                            f"(ativo={old_host}, tentativa={new_host})."
                        )
                        return False

                logger.info(f"[Gateway] Encerrando sessão anterior para serial={clean_serial} (auth_mode={auth_mode})")
                # Desvincula imediatamente referência antiga para evitar conflito com desconexão tardia
                old_dev["ws"] = None
                try:
                    await old_ws.close(code=1000)
                except Exception:
                    pass

        if not already_accepted:
            try:
                await websocket.accept()
            except Exception:
                pass

        self.ensure_ping_loop()
        now = time.time()

        # Registra no mapa por serial
        self.devices[clean_serial] = {
            "ws": websocket,
            "type": device_type,
            "serial": clean_serial,
            "auth_mode": auth_mode,
            "client_host": new_host,
            "fw_version": fw_version or "v2.5.2",
            "ping_ms": 0,
            "last_seen": now,
            "proto": "can",
            "pin": 7,
            "module": "ECU"
        }

        # Atualiza ponte legada para retrocompatibilidade
        if device_type in self.nodes:
            self.nodes[device_type]["ws"] = websocket
            self.nodes[device_type]["last_seen"] = now
            self.nodes[device_type]["serial"] = clean_serial
            self.nodes[device_type]["fw_version"] = fw_version or "v2.5.2"
        elif "scan" in device_type.lower():
            self.nodes["Scanner_CAN"]["ws"] = websocket
            self.nodes["Scanner_CAN"]["last_seen"] = now
            self.nodes["Scanner_CAN"]["serial"] = clean_serial
            self.nodes["Scanner_CAN"]["fw_version"] = fw_version or "v2.5.2"
        elif "osc" in device_type.lower():
            self.nodes["Osciloscopio"]["ws"] = websocket
            self.nodes["Osciloscopio"]["last_seen"] = now
            self.nodes["Osciloscopio"]["serial"] = clean_serial
            self.nodes["Osciloscopio"]["fw_version"] = fw_version or "v2.5.2"

        logger.info(f"[Gateway] Hardware conectado: Serial={clean_serial} | Tipo={device_type} | FW={fw_version or 'v2.5.2'}")
        await self.broadcast_hardware_status()
        return True

    async def register_heartbeat(self, serial: str, device_type: str = "fleet_tracker", fw_version: str = None):
        """Permite que dispositivos que enviam telemetria por HTTP (ex: AguiaCar 4G) fiquem Online no painel."""
        self.ensure_ping_loop()
        now = time.time()
        clean_serial = serial.strip().lower()

        if clean_serial not in self.devices:
            self.devices[clean_serial] = {
                "ws": None,
                "type": device_type,
                "serial": clean_serial,
                "fw_version": fw_version or "v2.5.2",
                "ping_ms": 15,
                "last_seen": now,
                "proto": "can_4g",
                "pin": 6,
                "module": "TELEMATICS"
            }
        else:
            self.devices[clean_serial]["last_seen"] = now
            self.devices[clean_serial]["type"] = device_type
            if fw_version:
                self.devices[clean_serial]["fw_version"] = fw_version

        await self.broadcast_hardware_status()

    async def request_pid_from_esp32(self, pid: str, timeout: float = 5.0, target_serial: str = None) -> dict:
        """Requisita ativamente um PID ao ESP32 e aguarda a resposta."""
        ws_target = None
        if target_serial and target_serial.lower() in self.devices:
            ws_target = self.devices[target_serial.lower()]["ws"]
        else:
            # Procura o primeiro scanner conectado
            for d in self.devices.values():
                if "scan" in d["type"].lower() and d["ws"]:
                    ws_target = d["ws"]
                    break
            if not ws_target and self.nodes.get("Scanner_CAN", {}).get("ws"):
                ws_target = self.nodes["Scanner_CAN"]["ws"]

        if not ws_target:
            raise RuntimeError("Nenhum ESP32 Scanner conectado ao gateway.")

        clean_pid = pid.strip().upper()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_requests[clean_pid] = future

        try:
            await ws_target.send_text(json.dumps({"cmd": "obd_send", "query": clean_pid}))
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            if clean_pid in self.last_response:
                return {"parsed_value": 0, "raw": self.last_response[clean_pid]}
            raise TimeoutError(f"Timeout aguardando resposta do PID {clean_pid}")
        finally:
            if self.pending_requests.get(clean_pid) is future:
                self.pending_requests.pop(clean_pid, None)

    async def disconnect_esp32(self, websocket: WebSocket, device_type: str = None, serial: str = None):
        # Desconecta do mapa de seriais (Item B - apenas se o websocket for o atualmente registrado)
        removed_any = False
        if serial and serial.lower() in self.devices:
            if self.devices[serial.lower()].get("ws") == websocket:
                del self.devices[serial.lower()]
                removed_any = True
                logger.info(f"[Gateway] Hardware desconectado por Serial: {serial}")
        else:
            to_remove = [s for s, d in self.devices.items() if d.get("ws") == websocket]
            for s in to_remove:
                del self.devices[s]
                removed_any = True
                logger.info(f"[Gateway] Hardware desconectado por Serial: {s}")

        # Limpa nós legados apenas se o websocket for o correspondente
        for dtype, node in self.nodes.items():
            if node.get("ws") == websocket:
                node["ws"] = None
                node["ping_ms"] = 0
                removed_any = True
                logger.info(f"[Gateway] Hardware disconnected (legado): {dtype}")

        # Falha e cancela imediatamente requisições pendentes associadas se o dispositivo desconectou (Item E)
        if removed_any:
            for q_key, fut in list(self.pending_requests.items()):
                if not fut.done():
                    fut.set_exception(ConnectionError(f"ESP32 desconectado durante a requisição de PID={q_key}"))
            self.pending_requests.clear()

        await self.broadcast_hardware_status()

    async def connect_web_client(self, websocket: WebSocket):
        await websocket.accept()
        self.web_clients.append(websocket)
        await self.send_hardware_status(websocket)

    async def disconnect_web_client(self, websocket: WebSocket):
        if websocket in self.web_clients:
            self.web_clients.remove(websocket)

    def get_status_payload(self):
        nodes_status = {}
        for k, v in self.nodes.items():
            node_data = {
                "connected": v["ws"] is not None,
                "ping_ms": v["ping_ms"]
            }
            if "proto" in v:
                node_data["proto"] = v.get("proto", "can")
                node_data["pin"] = v.get("pin", 7)
                node_data["module"] = v.get("module", "ECU")
            if "serial" in v:
                node_data["serial"] = v.get("serial")
            if "fw_version" in v:
                node_data["fw_version"] = v.get("fw_version")
            nodes_status[k] = node_data

        # Adiciona detalhes de todos os dispositivos seriais conectados
        active_devices = {}
        now = time.time()
        for s, d in self.devices.items():
            is_connected = (d.get("ws") is not None) or ((now - d.get("last_seen", 0)) < 45)
            active_devices[s] = {
                "connected": is_connected,
                "type": d.get("type"),
                "fw_version": d.get("fw_version", "v2.5.2"),
                "ping_ms": d.get("ping_ms", 0),
                "proto": d.get("proto", "can"),
                "pin": d.get("pin", 7),
                "module": d.get("module", "ECU")
            }

        return {
            "type": "hardware_status",
            "nodes": nodes_status,
            "devices": active_devices
        }

    async def broadcast_hardware_status(self):
        await self.broadcast_to_web(self.get_status_payload())

    async def send_hardware_status(self, websocket: WebSocket):
        try:
            await websocket.send_text(json.dumps(self.get_status_payload()))
        except Exception:
            pass

    async def broadcast_to_web(self, message: dict):
        dead = []
        payload = json.dumps(message)
        for client in self.web_clients:
            try:
                await client.send_text(payload)
            except Exception:
                dead.append(client)
        for c in dead:
            await self.disconnect_web_client(c)

    async def route_to_esp32(self, message: dict, target_serial: str = None) -> int:
        cmd = message.get("cmd") or message.get("command") or ""
        target = target_serial or message.get("target_serial") or message.get("serial") or message.get("target_node")
        is_broadcast = not target or str(target).strip().lower() in ("all", "*", "")
        clean_target = str(target).strip().lower() if not is_broadcast else None

        reached_devices = set()

        if not is_broadcast:
            # Comando direcionado: envia ESTRITAMENTE para o serial alvo (Item A)
            if clean_target in self.devices:
                dev = self.devices[clean_target]
                ws = dev.get("ws")
                if ws:
                    try:
                        await ws.send_text(json.dumps(message))
                        reached_devices.add(clean_target)
                    except Exception:
                        await self.disconnect_esp32(ws, dev.get("type"), serial=clean_target)
                else:
                    logger.warning(f"[Gateway] Dispositivo {clean_target} não possui websocket ativo.")
            else:
                logger.warning(f"[Gateway] Alvo {clean_target} não encontrado. Comando direcionado NÃO sofrerá fallback para broadcast.")
            return len(reached_devices)

        # Broadcast: filtra comandos por aptidão de tipo de hardware (Item A)
        dead = []
        for s, dev in list(self.devices.items()):
            ws = dev.get("ws")
            if not ws:
                continue
            dev_type = dev.get("type", "").lower()
            if cmd in OSCILLOSCOPE_COMMANDS and "osc" not in dev_type:
                continue
            if cmd in SCANNER_COMMANDS and "osc" in dev_type:
                continue
            try:
                await ws.send_text(json.dumps(message))
                reached_devices.add(s)
            except Exception:
                dead.append((ws, dev.get("type"), s))
        for ws, dtype, s in dead:
            await self.disconnect_esp32(ws, dtype, serial=s)

        return len(reached_devices)

    async def handle_esp32_message(self, payload: dict, device_type: str, serial: str = None):
        msg_type = payload.get("type")
        now = time.time()
        
        # Localiza o registro do aparelho por serial ou legado
        clean_serial = serial.lower() if serial else None
        dev_entry = self.devices.get(clean_serial) if clean_serial else None

        # Handle Pong
        if msg_type == "pong":
            t_sent = payload.get("time", int(now * 1000))
            ping = max(0, (now * 1000.0) - t_sent)

            if dev_entry:
                dev_entry["last_seen"] = now
                if "proto" in payload: dev_entry["proto"] = payload["proto"]
                if "pin" in payload: dev_entry["pin"] = payload["pin"]
                if "module" in payload: dev_entry["module"] = payload["module"]
                if "fw_version" in payload: dev_entry["fw_version"] = payload["fw_version"]
                old_p = dev_entry.get("ping_ms", 0)
                dev_entry["ping_ms"] = (old_p * 0.7) + (ping * 0.3) if old_p > 0 else ping

            if device_type in self.nodes:
                self.nodes[device_type]["last_seen"] = now
                if "proto" in payload: self.nodes[device_type]["proto"] = payload["proto"]
                if "pin" in payload: self.nodes[device_type]["pin"] = payload["pin"]
                if "module" in payload: self.nodes[device_type]["module"] = payload["module"]
                if "fw_version" in payload: self.nodes[device_type]["fw_version"] = payload["fw_version"]
                old_ping = self.nodes[device_type]["ping_ms"]
                self.nodes[device_type]["ping_ms"] = (old_ping * 0.7) + (ping * 0.3) if old_ping > 0 else ping
                
            await self.broadcast_hardware_status()
            return

        if msg_type == "hw_info":
            fw_val = payload.get("fw_version", "v2.5.2")
            if dev_entry:
                dev_entry["fw_version"] = fw_val
            if device_type in self.nodes:
                self.nodes[device_type]["fw_version"] = fw_val
            await self.broadcast_hardware_status()
            return

        if msg_type == "proto_ack":
            proto_val = payload.get("proto", "can")
            pin_val = payload.get("pin", 7)
            if dev_entry:
                dev_entry["proto"] = proto_val
                dev_entry["pin"] = pin_val
            if device_type in self.nodes:
                self.nodes[device_type]["proto"] = proto_val
                self.nodes[device_type]["pin"] = pin_val
            await self.broadcast_hardware_status()

        if msg_type == "pin_ack":
            pin_val = payload.get("pin", 7)
            mod_val = payload.get("module", "ECU")
            if dev_entry:
                dev_entry["pin"] = pin_val
                dev_entry["module"] = mod_val
            if device_type in self.nodes:
                self.nodes[device_type]["pin"] = pin_val
                self.nodes[device_type]["module"] = mod_val
            await self.broadcast_hardware_status()
            
        await self.broadcast_to_web(payload)
        
        # Captura respostas OBD para o Dev Agent ler via last_response
        if "query" in payload and "raw" in payload:
            self.last_response[payload["query"]] = payload["raw"]

        # Resolve requisições pendentes da IA ou Dev Agent
        q_key = payload.get("query") or payload.get("pid_req") or payload.get("pid")
        if q_key and q_key.upper() in self.pending_requests:
            fut = self.pending_requests[q_key.upper()]
            if not fut.done():
                fut.set_result(payload)
            
            # Se for resposta do VIN (Modo 0902), decodifica automaticamente
            if payload["query"] == "0902":
                try:
                    from app.vin_decoder import vin_service
                    # Extrai os caracteres ASCII dos bytes hexadecimais
                    parts = payload["raw"].split()
                    # Pula cabeçalhos UDS/OBD (ex: 49 02 01 ou 03 49 02)
                    ascii_chars = []
                    for p in parts:
                        try:
                            val = int(p, 16)
                            if 32 <= val <= 126: # caractere ASCII imprimível
                                ascii_chars.append(chr(val))
                        except ValueError:
                            pass
                    extracted_text = "".join(ascii_chars)
                    # Procura sequência de 17 caracteres alfanuméricos (VIN)
                    import re
                    match = re.search(r'[A-HJ-NPR-Z0-9]{17}', extracted_text)
                    if match:
                        vin = match.group(0)
                        vehicle_data = vin_service.decode(vin)
                        vin_broadcast = {
                            "type": "vehicle_auto_detected",
                            "vin": vin,
                            "vehicle": vehicle_data
                        }
                        await self.broadcast_to_web(vin_broadcast)
                except Exception as ex:
                    logger.error(f"[VIN] Error auto-decoding VIN: {ex}")
        
        # Bridge to the old manager so app.js can receive adc_burst, can_frame, etc.
        await manager.broadcast_to_clients(payload)

gateway_manager = HardwareGatewayManager()

try:
    from app import database as _db_mod
    _db_mod.register_revocation_callback(gateway_manager.evict_revoked_device)
except Exception:
    pass

