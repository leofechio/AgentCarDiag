import re

def update_inos():
    scanner = "/home/leonardof/AgentCarDiag/firmware/AgentCar_Scanner/AgentCar_Scanner.ino"
    osc = "/home/leonardof/AgentCarDiag/firmware/AgentCar_Oscilloscope/AgentCar_Oscilloscope.ino"
    
    with open(scanner, 'r') as f:
        code = f.read()
    code = code.replace('"/ws/esp32?token=AgentCarV2_Secreto_123"', '"/ws/esp32?token=AgentCarV2_Secreto_123&type=Scanner_CAN"')
    with open(scanner, 'w') as f:
        f.write(code)

    with open(osc, 'r') as f:
        code = f.read()
    code = code.replace('"/ws/esp32?token=AgentCarV2_Secreto_123"', '"/ws/esp32?token=AgentCarV2_Secreto_123&type=Osciloscopio"')
    with open(osc, 'w') as f:
        f.write(code)
    print("INOs updated")

def update_backend():
    manager = "/home/leonardof/AgentCarDiag/server/app/websocket_manager.py"
    with open(manager, 'r') as f:
        code = f.read()
    
    if "self.device_type" not in code:
        code = code.replace("self.is_connected = False", "self.is_connected = False\n        self.device_type = 'Desconhecido'")
        code = code.replace("async def connect_esp32(self, websocket: WebSocket):", "async def connect_esp32(self, websocket: WebSocket, device_type: str = 'Desconhecido'):")
        code = code.replace("self.esp32_connection = websocket", "self.esp32_connection = websocket\n        self.device_type = device_type")
        code = code.replace('"connected": self.is_connected', '"connected": self.is_connected,\n            "device_type": self.device_type')
        with open(manager, 'w') as f:
            f.write(code)
        print("Manager updated")

    main = "/home/leonardof/AgentCarDiag/server/app/main.py"
    with open(main, 'r') as f:
        code = f.read()
    
    if "device_type=type" not in code:
        old_def = "async def esp32_endpoint(websocket: WebSocket, token: str = Query(None)):\n    if token !="
        new_def = "async def esp32_endpoint(websocket: WebSocket, token: str = Query(None), type: str = Query('Desconhecido')):\n    if token !="
        code = code.replace(old_def, new_def)
        
        old_conn = "await gateway_manager.connect_esp32(websocket)"
        new_conn = "await gateway_manager.connect_esp32(websocket, device_type=type)"
        code = code.replace(old_conn, new_conn)
        
        with open(main, 'w') as f:
            f.write(code)
        print("Main updated")

def update_frontend():
    appjs = "/home/leonardof/AgentCarDiag/server/app/static/app.js"
    with open(appjs, 'r') as f:
        code = f.read()
    
    if "msg.device_type" not in code:
        old_online = "badge.textContent = '● Online (Pronto)';"
        new_online = "const devType = msg.device_type || 'Desconhecido';\n      badge.textContent = `● Online (${devType})`;"
        code = code.replace(old_online, new_online)
        with open(appjs, 'w') as f:
            f.write(code)
        print("App.js updated")

if __name__ == "__main__":
    update_inos()
    update_backend()
    update_frontend()

