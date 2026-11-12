"""
main.py — Ponto de Entrada da Aplicação AgentCarDiag
Arquitetura Modularizada (FastAPI + WebSockets + SQLite + AI)
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR, SYSTEM_VERSION
from app import database as db
from app.websocket_manager import gateway_manager
from app.homesim.database import init_db as init_homesim_db
from app.homesim.main import homesim_app

# Routers Modulares
from app.routers.views import router as views_router
from app.routers.system import router as system_router
from app.routers.websockets import router as websockets_router
from app.routers.sessions import router as sessions_router
from app.routers.dev_agent import create_dev_agent_router
from app.routers.fleet import router as fleet_router
from app.routers.devices import router as devices_router
from app.routers.reports import router as reports_router
from app.routers.antigravity_bridge import router as remote_bridge_router
from app.routers.ota import router as ota_router
from app.routers.diagnosis import router as diagnosis_router
from app.routers.flasher import router as flasher_router
from app.routers.xpro_diag import router as xpro_diag_router
from app.routers.auth import router as auth_router

# ─── Configuração de Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cardiag.main")


# ─── Ciclo de Vida da Aplicação (Lifespan) ────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializa banco de dados SQLite na inicialização
    await db.init_db()
    # Inicializa banco de dados SQLite isolado do HomeSIM (/app/data/homesim.db)
    await init_homesim_db()

    logger.info("╔══════════════════════════════════════════════╗")
    logger.info("║      AgentCarDiag Server — Starting up       ║")
    logger.info(f"║      Versão: {SYSTEM_VERSION:<31} ║")
    logger.info("╠══════════════════════════════════════════════╣")
    logger.info("║  /ws/node/{id}     → Hardware nodes (new)    ║")
    logger.info("║  /ws/esp32         → ESP32 Multi-Device GW   ║")
    logger.info("║  /ws/client        → Browser dashboard       ║")
    logger.info("║  /ws/telemetry     → Telemetry Stream        ║")
    logger.info("║  /api/sessions     → Session management      ║")
    logger.info("║  /api/reports      → Diagnostic Reports      ║")
    logger.info("║  /                 → Web UI                  ║")
    logger.info("║  /status           → System status (JSON)    ║")
    logger.info("╚══════════════════════════════════════════════╝")

    yield

    # Limpa buffer pendente de CAN frames antes de encerrar
    await db.flush_pending()
    logger.info("AgentCarDiag Server — Shutdown completo")


# ─── Inicialização do FastAPI ─────────────────────────────────────────────────

app = FastAPI(
    title="AgentCarDiag",
    description="Servidor de diagnóstico automotivo em tempo real para ESP32-S3 CAN Sniffer, ÁguiaCar e Osciloscópio",
    version=SYSTEM_VERSION,
    lifespan=lifespan,
)

# ─── Registro dos Routers Modulares ───────────────────────────────────────────

# 1. Páginas e Visualizações HTML
app.include_router(views_router)

# 2. Status, Health Check e Metadados do Sistema
app.include_router(system_router)

# 3. Barramento e Streams WebSockets
app.include_router(websockets_router)

# 4. Sessões de Diagnóstico
app.include_router(sessions_router)

# 5. Agente Dev / Chat com Hardware
app.include_router(create_dev_agent_router(gateway_manager))

# 6. ÁguiaCar — Gestão Telemática de Frota
app.include_router(fleet_router)

# 7. Multi-Tenant, Oficinas e Linha de Produção
app.include_router(devices_router)

# 8. Laudos Periciais e Orçamentos com QR Code
app.include_router(reports_router)

# 9. Ponte de Acesso Remoto Celular (diag.anality.me/chat)
app.include_router(remote_bridge_router)

# 10. Atualização Over-The-Air (OTA)
app.include_router(ota_router)

# 11. Validação Cruzada Diagnóstica (CAN + Osciloscópio + IA)
app.include_router(diagnosis_router)

# 12. Reprogramação de Centrais (ECU Flasher UDS 0x34/0x36/0x37 & Seed/Key 0x27)
app.include_router(flasher_router)

# 13. Diagnóstico X-PRO5 / Launch Engine & AuSCrypto
app.include_router(xpro_diag_router)

# 14. Autenticação Multi-Box Honeypot Defense
app.include_router(auth_router)

# ─── Arquivos Estáticos ───────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ─── Sub-Aplicação ASGI: HomeSIM Sentinel ─────────────────────────────────────
# Rota pública protegida: https://diag.anality.me/homesim
app.mount("/homesim", homesim_app)
