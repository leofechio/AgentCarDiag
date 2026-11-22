#!/usr/bin/env python3
"""
AgentCarDiag — Comprehensive Verification Suite
Tests Dual Bus CAN/K-Line switching, OBD Pin Multiplexing, WebSockets, and Dev Agent tools.
"""
import asyncio
import json
import sys
import time
import urllib.request
import websockets

import os

PORT = os.getenv("CARDIAG_PORT", "8001")
BASE_HTTP = f"http://127.0.0.1:{PORT}"
WS_ESP32 = f"ws://127.0.0.1:{PORT}/ws/esp32?token=AgentCarV2_Secreto_123&type=Scanner_CAN"
WS_TELEMETRY = f"ws://127.0.0.1:{PORT}/ws/telemetry"

PASSED = 0
FAILED = 0

def log_test(name: str, success: bool, detail: str = ""):
    global PASSED, FAILED
    if success:
        PASSED += 1
        print(f"  \033[92m✔ [PASS]\033[0m {name} {detail}")
    else:
        FAILED += 1
        print(f"  \033[91m✘ [FAIL]\033[0m {name} {detail}")

async def wait_for_message(ws, expected_type=None, expected_key=None, timeout=3.0):
    """Lê mensagens do WebSocket até encontrar o tipo ou chave esperada, ignorando status repetidos."""
    start = time.time()
    while time.time() - start < timeout:
        remaining = max(0.1, timeout - (time.time() - start))
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        data = json.loads(raw)
        if expected_type and data.get("type") == expected_type:
            return data
        if expected_key and expected_key in data:
            return data
    raise TimeoutError(f"Tempo esgotado aguardando {expected_type or expected_key}")

async def wait_for_esp32_cmd(ws, expected_cmd=None, timeout=3.0):
    """Lê mensagens que chegam no ESP32 ignorando pings de fundo."""
    start = time.time()
    while time.time() - start < timeout:
        remaining = max(0.1, timeout - (time.time() - start))
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        data = json.loads(raw)
        cmd = data.get("cmd") or data.get("command")
        if cmd == "ping":
            # Responde pong com metadados para manter o gateway atualizado
            pong = {
                "type": "pong",
                "time": data.get("time", int(time.time() * 1000)),
                "proto": "can",
                "pin": 7,
                "module": "ECU"
            }
            await ws.send(json.dumps(pong))
            continue
        if expected_cmd and cmd == expected_cmd:
            return data
        if not expected_cmd:
            return data
    raise TimeoutError(f"Tempo esgotado aguardando comando '{expected_cmd}' no ESP32")

async def test_all():
    print("\n\033[1m====================================================\033[0m")
    print("\033[1m       AgentCarDiag — Test & Verification Suite     \033[0m")
    print("\033[1m====================================================\033[0m\n")

    # 1. HTTP Endpoints Check
    print("\033[94m[1/4] Verificando endpoints REST básicos...\033[0m")
    try:
        req = urllib.request.urlopen(f"{BASE_HTTP}/health", timeout=3)
        data = json.loads(req.read().decode())
        log_test("GET /health", data.get("status") == "ok", f"-> {data}")
    except Exception as e:
        log_test("GET /health", False, str(e))

    try:
        req = urllib.request.urlopen(f"{BASE_HTTP}/status", timeout=3)
        data = json.loads(req.read().decode())
        log_test("GET /status", "web_clients" in data, f"-> web_clients={data.get('web_clients')}")
    except Exception as e:
        log_test("GET /status", False, str(e))

    try:
        req = urllib.request.urlopen(f"{BASE_HTTP}/api/dev_agent/chats", timeout=3)
        chats = json.loads(req.read().decode())
        log_test("GET /api/dev_agent/chats", isinstance(chats, list), f"-> {len(chats)} conversas registradas")
    except Exception as e:
        log_test("GET /api/dev_agent/chats", False, str(e))

    # 2. WebSocket Handshake & Mock ESP32 Connection
    print("\n\033[94m[2/4] Conectando ESP32 Scanner Mock e Cliente Telemetria...\033[0m")
    async with websockets.connect(WS_ESP32) as ws_esp32, websockets.connect(WS_TELEMETRY) as ws_client:
        log_test("Conexão WebSocket ESP32 Scanner", True)
        log_test("Conexão WebSocket Cliente Telemetria", True)

        # Recebe status no cliente
        init_status = await wait_for_message(ws_client, expected_type="hardware_status", timeout=4)
        scanner_node = init_status.get("nodes", {}).get("Scanner_CAN", {})
        log_test("ESP32 reconhecido como online no gateway", scanner_node.get("connected") is True, f"-> {scanner_node}")

        # 3. Protocol Switching & Multiplexing
        print("\n\033[94m[3/4] Testando Comutação de Protocolo e Multiplexador de Pinos OBD2...\033[0m")

        # Test 3a: Trocar protocolo para Linha K
        client_cmd_kline = {"cmd": "set_protocol", "proto": "kline"}
        await ws_client.send(json.dumps(client_cmd_kline))

        esp32_rx = await wait_for_esp32_cmd(ws_esp32, expected_cmd="set_protocol")
        log_test("ESP32 recebeu comando 'set_protocol'", esp32_rx.get("proto") == "kline", f"-> {esp32_rx}")

        # ESP32 Mock responde com proto_ack
        await ws_esp32.send(json.dumps({"type": "proto_ack", "proto": "kline", "pin": 7}))

        # Cliente Telemetria deve receber o proto_ack
        client_rx = await wait_for_message(ws_client, expected_type="proto_ack")
        log_test("Cliente recebeu broadcast 'proto_ack'", client_rx.get("proto") == "kline", f"-> {client_rx}")

        # Test 3b: Chavear Multiplexador para Pino 1 (ABS)
        client_cmd_mux = {"cmd": "set_module_pin", "pin": 1, "module": "ABS"}
        await ws_client.send(json.dumps(client_cmd_mux))

        esp32_mux_rx = await wait_for_esp32_cmd(ws_esp32, expected_cmd="set_module_pin")
        log_test("ESP32 recebeu chaveamento para Pino 1 (ABS)", esp32_mux_rx.get("pin") == 1 and esp32_mux_rx.get("module") == "ABS", f"-> {esp32_mux_rx}")

        await ws_esp32.send(json.dumps({"type": "pin_ack", "pin": 1, "module": "ABS"}))
        client_mux_rx = await wait_for_message(ws_client, expected_type="pin_ack")
        log_test("Cliente recebeu broadcast 'pin_ack' (Pino 1 ABS)", client_mux_rx.get("pin") == 1 and client_mux_rx.get("module") == "ABS")

        # Test 3c: Chavear Multiplexador para Pino 3 (Airbag)
        await ws_client.send(json.dumps({"cmd": "set_module_pin", "pin": 3, "module": "AIRBAG"}))
        esp32_airbag_rx = await wait_for_esp32_cmd(ws_esp32, expected_cmd="set_module_pin")
        log_test("ESP32 recebeu chaveamento para Pino 3 (Airbag)", esp32_airbag_rx.get("pin") == 3)
        await ws_esp32.send(json.dumps({"type": "pin_ack", "pin": 3, "module": "AIRBAG"}))
        client_airbag_rx = await wait_for_message(ws_client, expected_type="pin_ack")
        log_test("Cliente recebeu broadcast 'pin_ack' (Pino 3 Airbag)", client_airbag_rx.get("pin") == 3)

        # Test 3d: Envio de query OBD2 e resposta em K-Line
        client_obd_req = {"cmd": "obd_send", "query": "010C"}
        await ws_client.send(json.dumps(client_obd_req))

        esp32_obd_rx = await wait_for_esp32_cmd(ws_esp32, expected_cmd="obd_send")
        log_test("ESP32 recebeu query OBD2 '010C'", esp32_obd_rx.get("query") == "010C", f"-> {esp32_obd_rx}")

        # Mock ESP32 envia resposta decodificada KWP2000
        kline_resp = {
            "query": "010C",
            "raw": "41 0C 1A F8",
            "proto": "kline",
            "pin": 3,
            "module": "AIRBAG"
        }
        await ws_esp32.send(json.dumps(kline_resp))

        client_obd_rx = await wait_for_message(ws_client, expected_key="raw")
        log_test("Cliente recebeu resposta RAW OBD2 via Linha K", client_obd_rx.get("raw") == "41 0C 1A F8" and client_obd_rx.get("proto") == "kline", f"-> {client_obd_rx}")

        # Test 3e: Chavear de volta para CAN Bus
        await ws_client.send(json.dumps({"cmd": "set_protocol", "proto": "can"}))
        esp32_can_rx = await wait_for_esp32_cmd(ws_esp32, expected_cmd="set_protocol")
        log_test("ESP32 recebeu comando de retorno para CAN Bus", esp32_can_rx.get("proto") == "can")
        await ws_esp32.send(json.dumps({"type": "proto_ack", "proto": "can", "pin": 7}))
        client_can_ack = await wait_for_message(ws_client, expected_type="proto_ack")
        log_test("Cliente recebeu confirmação de volta para CAN Bus", client_can_ack.get("proto") == "can")

    # 4. Dev Agent Tools Unit & Integration Test
    print("\n\033[94m[4/4] Testando Ferramentas do Agente Dev IA...\033[0m")
    from app.routers.dev_agent import execute_tool, TOOLS

    # Verifica se as novas ferramentas estão declaradas no esquema do Gemini
    tool_names = [fn["name"] for fn in TOOLS["functionDeclarations"]]
    log_test("Ferramenta 'set_protocol' declarada no Gemini", "set_protocol" in tool_names)
    log_test("Ferramenta 'set_obd_module' declarada no Gemini", "set_obd_module" in tool_names)

    # Cria Mock Gateway com o Scanner conectado
    class MockWS:
        def __init__(self):
            self.sent_messages = []
        async def send_text(self, text):
            self.sent_messages.append(json.loads(text))

    class MockGateway:
        def __init__(self):
            self.mock_ws = MockWS()
            self.nodes = {
                "Scanner_CAN": {"ws": self.mock_ws, "ping_ms": 12.5, "proto": "can", "pin": 7, "module": "ECU"},
                "Osciloscopio": {"ws": None, "ping_ms": 0}
            }
            self.last_response = {}

    gw = MockGateway()

    # Test 4a: get_hardware_status
    hw_res = await execute_tool("get_hardware_status", {}, gw)
    log_test("Dev Agent: get_hardware_status", hw_res.get("hardware", {}).get("Scanner_CAN", {}).get("connected") is True, f"-> {hw_res}")

    # Test 4b: set_protocol
    proto_res = await execute_tool("set_protocol", {"proto": "kline"}, gw)
    log_test("Dev Agent: set_protocol ('kline')", proto_res.get("proto") == "kline" and gw.nodes["Scanner_CAN"]["proto"] == "kline", f"-> {proto_res}")

    # Test 4c: set_obd_module
    mod_res = await execute_tool("set_obd_module", {"pin": 1, "module": "ABS"}, gw)
    log_test("Dev Agent: set_obd_module (Pino 1 ABS)", mod_res.get("pin") == 1 and gw.nodes["Scanner_CAN"]["pin"] == 1, f"-> {mod_res}")

    # Test 4d: send_obd_query
    gw.last_response["010C"] = "41 0C 1A F8"
    query_res = await execute_tool("send_obd_query", {"query": "010C"}, gw)
    log_test("Dev Agent: send_obd_query ('010C')", query_res.get("raw") == "41 0C 1A F8", f"-> {query_res}")

    print("\n\033[1m----------------------------------------------------\033[0m")
    print(f"\033[1mResultado dos Testes: {PASSED} Passaram, {FAILED} Falharam\033[0m")
    print("\033[1m----------------------------------------------------\033[0m\n")
    if FAILED > 0:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_all())
