"""
ota.py — Router para Upload e Gerenciamento de Firmware Over-The-Air (OTA)
AgentCarDiag Server
"""

import json
import logging
from fastapi import APIRouter, Depends, File, UploadFile, Form

from app.config import STATIC_DIR
from app.dependencies import verify_credentials
from app.websocket_manager import gateway_manager

logger = logging.getLogger("cardiag.ota")

router = APIRouter(prefix="/api", tags=["OTA"])


@router.post("/upload_firmware")
async def upload_firmware(
    file: UploadFile = File(...),
    device_type: str = Form(...),
    auth_data: dict = Depends(verify_credentials)
):
    """
    Recebe novo binário de firmware compilado e notifica o ESP32-S3 via WebSocket para iniciar o processo OTA.
    """
    filepath = STATIC_DIR / "firmware.bin"

    content = await file.read()
    with open(filepath, "wb") as out_file:
        out_file.write(content)

    ota_url = "http://diag.anality.me/static/firmware.bin"
    cmd_payload = {"cmd": "start_ota", "url": ota_url}

    # Rotear apenas para o dispositivo selecionado
    node = gateway_manager.nodes.get(device_type)
    if node and node.get("ws"):
        try:
            await node["ws"].send_text(json.dumps(cmd_payload))
            logger.info(f"[OTA] Notificação de atualização enviada para {device_type}")
            return {"status": "success", "msg": f"Firmware gravado! {device_type} notificado para atualizar!"}
        except Exception as e:
            logger.error(f"[OTA] Falha ao enviar comando para {device_type}: {e}")
            return {"status": "error", "msg": f"Erro ao notificar {device_type}."}
    else:
        return {"status": "error", "msg": f"Firmware salvo, mas {device_type} está offline."}
