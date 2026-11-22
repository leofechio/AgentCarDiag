# OBSOLETO: script histórico pontual (token migrado para server/.env e app/config.py)
import os
import re

def secure_main():
    file_path = "/home/leonardof/AgentCarDiag/server/app/main.py"
    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()

    # Add Query to fastapi import if not there
    if "from fastapi import" in code and "Query" not in code:
        code = code.replace("from fastapi import", "from fastapi import Query,")
    
    # Update esp32 endpoint
    old_def = "async def esp32_endpoint(websocket: WebSocket):"
    new_def = """async def esp32_endpoint(websocket: WebSocket, token: str = Query(None)):
    if token != os.getenv("WS_TOKEN", ""):
        logger.warning(f"[Gateway] Acesso negado. Token Invalido: {token}")
        await websocket.close(code=1008)
        return"""
    
    if old_def in code:
        code = code.replace(old_def, new_def)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
        print("Backend Secured.")
    else:
        print("Backend already secured or signature not found.")

def secure_ino(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()
    
    old_url = 'const char* WS_URL    = "/ws/esp32";'
    new_url = 'const char* WS_URL    = "/ws/esp32?token=<SET_WS_TOKEN>";'
    
    if old_url in code:
        code = code.replace(old_url, new_url)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"Secured {file_path}")

if __name__ == "__main__":
    secure_main()
    secure_ino("/home/leonardof/AgentCarDiag/firmware/AgentCar_Scanner/AgentCar_Scanner.ino")
    secure_ino("/home/leonardof/AgentCarDiag/firmware/AgentCar_Oscilloscope/AgentCar_Oscilloscope.ino")
