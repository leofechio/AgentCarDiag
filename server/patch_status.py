import re

path = "/home/leonardof/AgentCarDiag/server/app/main.py"
with open(path, "r") as f:
    code = f.read()

old_status = """    # Adicionar o ESP32 atual à lista de nós HW
    if gateway_manager.esp32_connection:
        status_data["hardware_nodes"].append({"id": "ESP32-Gateway", "connected_at": "now", "messages_sent": 0})"""

new_status = """    # Adicionar o ESP32 atual à lista de nós HW
    for dtype, node in gateway_manager.nodes.items():
        if node["ws"]:
            status_data["hardware_nodes"].append({"id": dtype, "connected_at": node["last_seen"], "messages_sent": 0})"""

code = code.replace(old_status, new_status)
with open(path, "w") as f:
    f.write(code)
print("Status route patched")
