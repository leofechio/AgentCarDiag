import logging
from app.websocket_manager import gateway_manager

logger = logging.getLogger("cardiag.tools")

async def read_obd_live_data(pid: str) -> dict:
    """
    Requisita ativamente um valor do veículo através do ESP32/Vlinker.
    Espera a resposta real chegar antes de retornar à IA.
    """
    logger.info(f"[Agent Tools] IA requisitou leitura ao vivo do PID: {pid}")
    
    try:
        # A IA deve passar algo como "0114" (Mode 01, PID 14 - O2 sensor)
        response = await gateway_manager.request_pid_from_esp32(pid, timeout=5.0)
        
        # O ESP32 envia: {"type": "ai_response", "pid_req": "0114", "parsed_value": 45, "raw": "..."}
        if response and "parsed_value" in response:
            return {
                "status": "success",
                "pid": pid,
                "value": response["parsed_value"],
                "raw_hex": response.get("raw", "")
            }
        else:
            return {"status": "error", "message": "Resposta inválida ou vazia do hardware."}
            
    except Exception as e:
        logger.error(f"[Agent Tools] Falha ao ler PID {pid}: {e}")
        return {"status": "error", "message": f"Hardware inalcançável ou timeout: {str(e)}"}
