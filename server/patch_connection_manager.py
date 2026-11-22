import re

path = "/home/leonardof/AgentCarDiag/server/app/websocket_manager.py"
with open(path, "r") as f:
    code = f.read()

get_status_method = """    def get_status(self) -> dict:
        return {
            "hardware_nodes": [],
            "web_clients": len(self.client_connections),
            "messages_relayed": self.messages_relayed,
            "total_hardware_ever": self.total_hardware_connected,
            "total_clients_ever": self.total_clients_connected,
        }

manager = ConnectionManager()"""

code = code.replace("manager = ConnectionManager()", get_status_method)

with open(path, "w") as f:
    f.write(code)
print("Added get_status back")
