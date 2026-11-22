import re
import os

def patch_backend():
    path = "/home/leonardof/AgentCarDiag/server/app/websocket_manager.py"
    with open(path, "r") as f:
        code = f.read()

    new_manager = """import asyncio
import time
from typing import Optional
from fastapi import WebSocket
import json
import logging

logger = logging.getLogger("api")

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

    async def connect_hardware(self, websocket: WebSocket, hw_id: str):
        await websocket.accept()
        self.hardware_connections[websocket] = {
            "id": hw_id,
            "connected_at": time.time(),
            "messages_sent": 0
        }
        self.total_hardware_connected += 1

    async def disconnect_hardware(self, websocket: WebSocket):
        if websocket in self.hardware_connections:
            del self.hardware_connections[websocket]

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
        sent_count = 0
        dead = []
        for ws, meta in list(self.hardware_connections.items()):
            if target_node and meta.get("id") != target_node:
                continue
            try:
                await ws.send_text(json.dumps(payload, separators=(",", ":")))
                sent_count += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect_hardware(ws)
        return sent_count

manager = ConnectionManager()

class HardwareGatewayManager:
    def __init__(self):
        self.web_clients: list[WebSocket] = []
        self.nodes = {
            "Scanner_CAN": {"ws": None, "ping_ms": 0, "last_seen": 0},
            "Osciloscopio": {"ws": None, "ping_ms": 0, "last_seen": 0}
        }
        self.pending_requests = {}
        
        # Start ping loop
        asyncio.create_task(self.ping_loop())

    async def ping_loop(self):
        while True:
            await asyncio.sleep(2)
            now = time.time()
            for dev_type, node in list(self.nodes.items()):
                if node["ws"] is not None:
                    # Timeout check (5 seconds)
                    if now - node["last_seen"] > 5:
                        logger.warning(f"[Ping] {dev_type} timeout. Disconnecting.")
                        await self.disconnect_esp32(node["ws"], dev_type)
                        continue
                    
                    # Send ping
                    try:
                        await node["ws"].send_text(json.dumps({"cmd": "ping", "time": now}))
                    except Exception:
                        await self.disconnect_esp32(node["ws"], dev_type)

    async def connect_esp32(self, websocket: WebSocket, device_type: str = 'Desconhecido'):
        await websocket.accept()
        if device_type not in self.nodes:
            self.nodes[device_type] = {"ws": None, "ping_ms": 0, "last_seen": time.time()}
        
        self.nodes[device_type]["ws"] = websocket
        self.nodes[device_type]["last_seen"] = time.time()
        logger.info(f"[Gateway] Hardware connected: {device_type}")
        await self.broadcast_hardware_status()

    async def disconnect_esp32(self, websocket: WebSocket, device_type: str = None):
        for dtype, node in self.nodes.items():
            if node["ws"] == websocket or dtype == device_type:
                node["ws"] = None
                node["ping_ms"] = 0
                logger.info(f"[Gateway] Hardware disconnected: {dtype}")
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
            nodes_status[k] = {
                "connected": v["ws"] is not None,
                "ping_ms": v["ping_ms"]
            }
        return {
            "type": "hardware_status",
            "nodes": nodes_status
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

    async def route_to_esp32(self, message: dict):
        # Broadcast to all connected nodes for now, or route by type later
        dead = []
        for dtype, node in self.nodes.items():
            if node["ws"]:
                try:
                    await node["ws"].send_text(json.dumps(message))
                except Exception:
                    dead.append((node["ws"], dtype))
        for ws, dtype in dead:
            await self.disconnect_esp32(ws, dtype)

    async def handle_esp32_message(self, payload: dict, device_type: str):
        msg_type = payload.get("type")
        
        # Handle Pong
        if msg_type == "pong":
            if device_type in self.nodes:
                self.nodes[device_type]["last_seen"] = time.time()
                t_sent = payload.get("time", time.time())
                ping = (time.time() - t_sent) * 1000.0
                
                # Moving average
                old_ping = self.nodes[device_type]["ping_ms"]
                self.nodes[device_type]["ping_ms"] = (old_ping * 0.7) + (ping * 0.3) if old_ping > 0 else ping
                
                # Broadcast updated status every pong to update frontend ping
                await self.broadcast_hardware_status()
            return
            
        await self.broadcast_to_web(payload)

gateway_manager = HardwareGatewayManager()
"""
    with open(path, "w") as f:
        f.write(new_manager)
    print("Websocket manager patched")

def patch_main():
    path = "/home/leonardof/AgentCarDiag/server/app/main.py"
    with open(path, "r") as f:
        code = f.read()
    
    # Update esp32_endpoint to pass device_type to handle_esp32_message
    if "await gateway_manager.handle_esp32_message(payload)" in code:
        code = code.replace("await gateway_manager.handle_esp32_message(payload)", "await gateway_manager.handle_esp32_message(payload, type)")
        with open(path, "w") as f:
            f.write(code)
        print("Main patched")

def patch_frontend_html():
    path = "/home/leonardof/AgentCarDiag/server/app/static/index.html"
    with open(path, "r") as f:
        html = f.read()

    old_section = re.search(r'<div class="sys-dashboard".*?Gateway Hardware & Conectividade BLE.*?</div>\s*</div>\s*</div>\s*</div>', html, re.DOTALL)
    
    # We will replace the entire "sys-dashboard" section that holds the old BLE UI.
    # It's better to use regex carefully.
    
    # Looking for the container holding "Gateway Hardware & Conectividade BLE"
    pattern = re.compile(r'<div class="card-container">\s*<h3 class="section-title">.*?Gateway Hardware & Conectividade BLE.*?</div>\s*</div>\s*</div>', re.DOTALL)
    
    new_cards = """<div class="card-container" style="display: flex; gap: 16px; margin-bottom: 24px;">
            
            <!-- Card Scanner -->
            <div class="dashboard-card" style="flex: 1; padding: 20px; border-left: 4px solid var(--accent-blue);">
              <h3 style="color: var(--text-main); font-size: 15px; margin-bottom: 16px; display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 18px;">🔌</span> Gateway Scanner CAN
              </h3>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <p class="badge-status offline" id="status-scanner" style="margin: 0;">● Offline</p>
                <div style="text-align: right;">
                  <span style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">LATÊNCIA (PING)</span>
                  <span id="ping-scanner" style="font-size: 20px; font-weight: bold; color: var(--text-main); font-family: monospace;">--</span>
                  <span style="font-size: 12px; color: var(--text-muted);">ms</span>
                </div>
              </div>
            </div>

            <!-- Card Osciloscopio -->
            <div class="dashboard-card" style="flex: 1; padding: 20px; border-left: 4px solid var(--accent-amber);">
              <h3 style="color: var(--text-main); font-size: 15px; margin-bottom: 16px; display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 18px;">📡</span> Osciloscópio de Borda
              </h3>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <p class="badge-status offline" id="status-osc" style="margin: 0;">● Offline</p>
                <div style="text-align: right;">
                  <span style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">LATÊNCIA (PING)</span>
                  <span id="ping-osc" style="font-size: 20px; font-weight: bold; color: var(--text-main); font-family: monospace;">--</span>
                  <span style="font-size: 12px; color: var(--text-muted);">ms</span>
                </div>
              </div>
            </div>

          </div>"""

    if pattern.search(html):
        html = pattern.sub(new_cards, html)
        with open(path, "w") as f:
            f.write(html)
        print("Frontend HTML patched")

def patch_frontend_js():
    path = "/home/leonardof/AgentCarDiag/server/app/static/app.js"
    with open(path, "r") as f:
        code = f.read()
    
    # Replace the old hardware_status logic
    old_logic = re.compile(r'case \'hardware_status\':.*?break;', re.DOTALL)
    new_logic = """case 'hardware_status':
      const updateCard = (id, data) => {
        const badge = document.getElementById(`status-${id}`);
        const ping = document.getElementById(`ping-${id}`);
        if (!badge || !ping) return;
        
        if (data && data.connected) {
          badge.className = 'badge-status online';
          badge.textContent = '● Online (Ativo)';
          ping.textContent = Math.round(data.ping_ms);
        } else {
          badge.className = 'badge-status offline';
          badge.textContent = '● Offline';
          ping.textContent = '--';
        }
      };
      
      if (msg.nodes) {
        updateCard('scanner', msg.nodes['Scanner_CAN']);
        updateCard('osc', msg.nodes['Osciloscopio']);
      }
      break;"""
    
    if old_logic.search(code):
        code = old_logic.sub(new_logic, code)
        with open(path, "w") as f:
            f.write(code)
        print("Frontend JS patched")

def patch_ino_scanner():
    path = "/home/leonardof/AgentCarDiag/firmware/AgentCar_Scanner/AgentCar_Scanner.ino"
    with open(path, "r") as f:
        code = f.read()
    
    # Inject ping handler
    if '"pong"' not in code:
        old = """                if (!err && doc.containsKey("cmd") && doc["cmd"] == "query_pid") {"""
        new = """                if (!err && doc.containsKey("cmd")) {
                    if (doc["cmd"] == "ping") {
                        JsonDocument pongDoc;
                        pongDoc["type"] = "pong";
                        pongDoc["time"] = doc["time"];
                        String pOut;
                        serializeJson(pongDoc, pOut);
                        webSocket.sendTXT(pOut);
                    }
                    else if (doc["cmd"] == "query_pid") {"""
        code = code.replace(old, new)
        code = code.replace("                    }\n                }\n            }", "                    }\n                }\n            }")
        with open(path, "w") as f:
            f.write(code)
        print("Scanner INO patched")

def patch_ino_osc():
    path = "/home/leonardof/AgentCarDiag/firmware/AgentCar_Oscilloscope/AgentCar_Oscilloscope.ino"
    with open(path, "r") as f:
        code = f.read()
    
    # Inject ping handler
    if '"pong"' not in code:
        old = """    } else if (type == WStype_CONNECTED) {
        Serial.println("[WS] Conectado ao Servidor AgentCarDiag!");
    }
}"""
        new = """    } else if (type == WStype_CONNECTED) {
        Serial.println("[WS] Conectado ao Servidor AgentCarDiag!");
    } else if (type == WStype_TEXT) {
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, payload);
        if (!err && doc.containsKey("cmd") && doc["cmd"] == "ping") {
            JsonDocument pongDoc;
            pongDoc["type"] = "pong";
            pongDoc["time"] = doc["time"];
            String pOut;
            serializeJson(pongDoc, pOut);
            webSocket.sendTXT(pOut);
        }
    }
}"""
        code = code.replace(old, new)
        with open(path, "w") as f:
            f.write(code)
        print("Osc INO patched")

if __name__ == "__main__":
    patch_backend()
    patch_main()
    patch_frontend_html()
    patch_frontend_js()
    patch_ino_scanner()
    patch_ino_osc()
