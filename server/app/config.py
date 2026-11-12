"""
config.py — Centralização de Configurações, Constantes e Variáveis de Ambiente
AgentCarDiag Server
"""

import os
from pathlib import Path

# Diretórios Base
SERVER_DIR = Path(__file__).parent.parent
APP_DIR = Path(__file__).parent
DATA_DIR = SERVER_DIR / "data"
STATIC_DIR = APP_DIR / "static"
DATABASES_DIR = APP_DIR / "databases"


def _load_env_file(env_path: Path) -> None:
    """Carrega variáveis de .env local sem sobrescrever variáveis já definidas no ambiente."""
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)


_load_env_file(SERVER_DIR / ".env")

# Garantir existência dos diretórios
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
DATABASES_DIR.mkdir(parents=True, exist_ok=True)

# Banco de Dados
DB_PATH = os.getenv("CARDIAG_DB_PATH", str(DATA_DIR / "cardiag.db"))

# Autenticação Master
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD deve ser definido via variável de ambiente ou server/.env")

# Chave e Integrações IA
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Gateway Hardware ESP32
WS_TOKEN = os.getenv("WS_TOKEN", "")
if not WS_TOKEN:
    raise RuntimeError("WS_TOKEN deve ser definido via variável de ambiente ou server/.env")

# Base de DTCs, Formas de Onda (Osciloscópio) e Manuais de Oficina (Repair Manuals)
DTC_DATABASE_PATH = DATABASES_DIR / "dtc_database.json"
REFERENCE_WAVEFORMS_PATH = DATABASES_DIR / "reference_waveforms.json"
WORKSHOP_MANUALS_PATH = DATABASES_DIR / "workshop_repair_manuals.json"
OEM_KNOWLEDGE_PATH = APP_DIR / "data" / "oem_knowledge.json"

# Versão do Sistema
SYSTEM_VERSION = "2.1.0"
SERVICE_NAME = "cardiag-server"

# Multi-Box Honeypot Defense
USERS_CONFIG_PATH = Path(os.getenv("USERS_CONFIG_PATH", str(DATA_DIR / "usuarios.json")))
BLOCKED_IPS_JSON_PATH = Path(os.getenv("BLOCKED_IPS_JSON_PATH", str(DATA_DIR / "blocked_ips.json")))
USER_FOLDERS_ROOT = Path(os.getenv("USER_FOLDERS_ROOT", str(DATA_DIR / "user_folders")))
USER_FOLDERS_ROOT.mkdir(parents=True, exist_ok=True)

HONEYPOT_LOCKOUT_SECONDS = int(os.getenv("HONEYPOT_LOCKOUT_SECONDS", "900"))  # 15 min ban por brute-force
HONEYPOT_BAN_SECONDS = int(os.getenv("HONEYPOT_BAN_SECONDS", "86400"))        # 24h ban por honeypot direto
MAX_AUTH_ATTEMPTS = int(os.getenv("MAX_AUTH_ATTEMPTS", "3"))
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY deve ser definido via variável de ambiente ou server/.env")
