# setup_windows.ps1 — Configuracao e Inicializacao Autonoma do AgentCarDiag no Windows
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  AgentCarDiag — Preparacao Autonoma para Notebook de Campo" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan

if (-not (Test-Path "$ProjectRoot\.venv\Scripts\python.exe")) {
    Write-Host "[1/3] Criando ambiente virtual Python (.venv)..." -ForegroundColor Yellow
    python -m venv "$ProjectRoot\.venv"
}

Write-Host "[2/3] Verificando e instalando dependencias Python..." -ForegroundColor Yellow
& "$ProjectRoot\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$ProjectRoot\.venv\Scripts\python.exe" -m pip install -r "$ProjectRoot\server\requirements.txt"

$env:PYTHONPATH = "$ProjectRoot\server"
Write-Host "[3/3] Executando validacao rapida da suite de testes..." -ForegroundColor Yellow
& "$ProjectRoot\.venv\Scripts\pytest.exe" "$ProjectRoot\server\tests\test_modular_api.py" -v

Write-Host "`n[PRONTO] Iniciando servidor AgentCarDiag na porta 8000 (0.0.0.0:8000)..." -ForegroundColor Green
& "$ProjectRoot\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
