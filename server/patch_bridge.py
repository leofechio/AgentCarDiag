import re

path = "/home/leonardof/AgentCarDiag/server/app/websocket_manager.py"
with open(path, "r") as f:
    code = f.read()

old_code = """        # Broadcast updated status every pong to update frontend ping
                await self.broadcast_hardware_status()
            return
            
        await self.broadcast_to_web(payload)"""

new_code = """        # Broadcast updated status every pong to update frontend ping
                await self.broadcast_hardware_status()
            return
            
        await self.broadcast_to_web(payload)
        
        # Bridge to the old manager so app.js can receive adc_burst, can_frame, etc.
        await manager.broadcast_to_clients(payload)"""

code = code.replace(old_code, new_code)
with open(path, "w") as f:
    f.write(code)

print("Bridged!")
