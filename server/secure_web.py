# OBSOLETO: script histórico pontual (autenticação migrada para app/dependencies.py)
import os
import re

def add_basic_auth():
    file_path = "/home/leonardof/AgentCarDiag/server/app/main.py"
    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()

    # Add imports if missing
    if "HTTPBasic" not in code:
        imports = """from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, "admin")
    correct_password = secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", ""))
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acesso Negado",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
"""
        code = code.replace("from fastapi.staticfiles import StaticFiles", "from fastapi.staticfiles import StaticFiles\n" + imports)
    
    # Secure the dashboard
    old_route = """@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard():"""
    new_route = """@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard(username: str = Depends(verify_credentials)):"""
    
    if old_route in code:
        code = code.replace(old_route, new_route)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
        print("Web Frontend Secured with Basic Auth.")
    else:
        print("Frontend route not found or already secured.")

if __name__ == "__main__":
    add_basic_auth()
