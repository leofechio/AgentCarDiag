@echo off
title AgentCarDiag — Servidor Autonomo de Diagnostico Veicular (Windows)
cd /d "%~dp0"

echo ==============================================================
echo   AgentCarDiag — Inicializacao Autonoma para Testes em Veiculo
echo ==============================================================

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Criando ambiente virtual Python local ^(.venv^)...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERRO] Python nao encontrado no PATH. Instale Python 3.11+ e marque "Add Python to PATH".
        pause
        exit /b 1
    )
    echo [2/3] Instalando dependencias em .venv...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r server\requirements.txt
)

set PYTHONPATH=%~dp0server
set PORT=8000

echo [3/3] Iniciando Servidor AgentCarDiag em http://127.0.0.1:8000 ...
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
