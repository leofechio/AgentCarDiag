import httpx
import logging

logger = logging.getLogger("homesim.telegram")

async def send_telegram_sms_alert(bot_token: str, chat_id: str, sender: str, body: str, otp_code: str, device_name: str):
    if not bot_token or not chat_id:
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    otp_badge = f"\n\n🔑 <b>CÓDIGO 2FA IDENTIFICADO:</b> <code>{otp_code}</code>" if otp_code else ""
    
    text = (
        f"📱 <b>Novo SMS Recebido - HomeSIM</b>\n"
        f"🏠 <b>Aparelho:</b> {device_name}\n"
        f"👤 <b>Remetente:</b> <code>{sender}</code>\n"
        f"💬 <b>Mensagem:</b>\n<i>{body}</i>"
        f"{otp_badge}"
    )
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            })
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Erro ao enviar alerta Telegram: {e}")
        return False

async def send_telegram_device_alert(bot_token: str, chat_id: str, device_name: str, message: str):
    if not bot_token or not chat_id:
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    text = f"⚠️ <b>Alerta HomeSIM ({device_name}):</b>\n{message}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            })
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Erro ao enviar alerta de dispositivo Telegram: {e}")
        return False
