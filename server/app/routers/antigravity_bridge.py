"""
antigravity_bridge.py — Ponte Remota Mobile para o Antigravity
Permite ao admin acessar pelo celular em diag.anality.me/chat:
- Visualizar o histórico e ações do Antigravity em tempo real
- Enviar mensagens e comandos para o assistente
- Enviar prints/fotos do celular
"""

import os
import re
import json
import uuid
import base64
import logging
from pathlib import Path
from datetime import datetime, timezone
import urllib.request
import urllib.error
import asyncio

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List

logger = logging.getLogger("cardiag.remote_chat")

router = APIRouter(tags=["Antigravity Remote Bridge"])

BRAIN_CONV_DIR = Path("/home/leonardof/.gemini/antigravity/brain/d1217ac4-77d5-4769-aebb-01fd307eb357")
TRANSCRIPT_PATH = BRAIN_CONV_DIR / ".system_generated" / "logs" / "transcript.jsonl"
UPLOAD_DIR = BRAIN_CONV_DIR / ".user_uploaded"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

PREFERRED_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemma-4-26b-a4b-it"
]


@router.get("/api/remote/transcript")
async def get_remote_transcript():
    """Lê o histórico do Antigravity para exibir na interface mobile."""
    if not TRANSCRIPT_PATH.exists():
        return {"messages": []}

    messages = []
    try:
        with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    source = entry.get("source")
                    step_type = entry.get("type")
                    content = entry.get("content", "")
                    created_at = entry.get("created_at", "")

                    # 1. Mensagem do Usuário
                    if step_type == "USER_INPUT" or source == "USER_EXPLICIT":
                        if "<USER_REQUEST>" in content:
                            m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
                            clean_text = m.group(1).strip() if m else content
                        else:
                            clean_text = content.strip()

                        # Detecta se há imagens anexadas
                        image_urls = []
                        if ".user_uploaded" in content:
                            for img_match in re.finditer(r"/\S+/\.user_uploaded/(\S+)", content):
                                fn = img_match.group(1).rstrip("),.;\"'")
                                image_urls.append(f"/api/remote/image/{fn}")

                        messages.append({
                            "role": "user",
                            "content": clean_text,
                            "image": image_urls[0] if image_urls else None,
                            "images": image_urls,
                            "time": created_at
                        })

                    # 2. Resposta do Assistente
                    elif source == "MODEL" and step_type == "PLANNER_RESPONSE" and content:
                        messages.append({
                            "role": "assistant",
                            "content": content,
                            "time": created_at
                        })
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"Erro ao ler transcript: {e}")

    return {"messages": messages[-40:]}


@router.get("/api/remote/image/{filename}")
async def get_uploaded_image(filename: str):
    """Serve imagens enviadas para exibição no chat."""
    from fastapi.responses import FileResponse
    file_path = UPLOAD_DIR / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Imagem não encontrada")


class MobileMessagePayload(BaseModel):
    message: str
    image_url: Optional[str] = None
    image_urls: Optional[List[str]] = []


@router.post("/api/remote/send")
async def send_mobile_message(payload: MobileMessagePayload):
    """
    Recebe mensagem do celular e executa com fallback inteligente de modelos.
    Garante resposta imediata no celular e espelha no log do servidor.
    Suporta múltiplos prints e imagens anexadas de uma só vez.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY não configurada no servidor.")

    history = []
    try:
        if TRANSCRIPT_PATH.exists():
            with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    entry = json.loads(line.strip())
                    st = entry.get("type")
                    src = entry.get("source")
                    ct = entry.get("content", "")
                    if (st == "USER_INPUT" or src == "USER_EXPLICIT") and ct:
                        if "<USER_REQUEST>" in ct:
                            m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", ct, re.DOTALL)
                            clean = m.group(1).strip() if m else ct
                        else:
                            clean = ct.strip()
                        history.append({"role": "user", "parts": [{"text": clean}]})
                    elif src == "MODEL" and st == "PLANNER_RESPONSE" and ct:
                        history.append({"role": "model", "parts": [{"text": ct}]})
    except Exception:
        pass

    history = history[-6:]
    user_parts = []
    if payload.message and payload.message.strip():
        user_parts.append({"text": payload.message.strip()})
    else:
        user_parts.append({"text": "Analise as imagens anexadas e forneça diagnóstico técnico."})

    # Coleta todas as imagens anexadas
    all_images = []
    if payload.image_urls:
        for u in payload.image_urls:
            if u and u not in all_images:
                all_images.append(u)
    if payload.image_url and payload.image_url not in all_images:
        all_images.append(payload.image_url)

    for img_url in all_images:
        if "/api/remote/image/" in img_url:
            fname = img_url.split("/")[-1]
            img_path = UPLOAD_DIR / fname
            if img_path.exists():
                try:
                    mime = "image/png"
                    if fname.lower().endswith((".jpg", ".jpeg")):
                        mime = "image/jpeg"
                    elif fname.lower().endswith(".webp"):
                        mime = "image/webp"
                    b64 = base64.b64encode(img_path.read_bytes()).decode("utf-8")
                    user_parts.append({
                        "inlineData": {
                            "mimeType": mime,
                            "data": b64
                        }
                    })
                except Exception as e:
                    logger.error(f"Erro ao embutir imagem {fname}: {e}")

    history.append({"role": "user", "parts": user_parts})

    system_instruction = (
        "Você é o Antigravity, o assistente IA de engenharia e diagnóstico automotivo do projeto AgentCarDiag. "
        "Você está conversando diretamente com o Leonardo pelo celular no portal remoto seguro diag.anality.me/chat. "
        "Responda sempre em Português do Brasil com clareza técnica e preste suporte a tudo o que ele perguntar ou enviar em prints."
    )

    loop = asyncio.get_running_loop()
    reply = None
    last_err = None

    for model_name in PREFERRED_MODELS:
        body = {
            "contents": history,
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 4096}
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            raw = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=16).read().decode())
            res = json.loads(raw)
            candidates = res.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                if parts and "text" in parts[0]:
                    reply = parts[0]["text"]
            if reply:
                break
        except Exception as e:
            last_err = e
            continue

    if not reply:
        return {"status": "error", "reply": f"Serviço temporariamente ocupado nos modelos Google. Erro: {last_err}"}

    # Registra no transcript para sincronizar
    now_iso = datetime.now(timezone.utc).isoformat()
    imgs_annot = " ".join([f"/home/leonardof/.gemini/antigravity/brain/d1217ac4-77d5-4769-aebb-01fd307eb357/.user_uploaded/{u.split('/')[-1]}" for u in all_images])
    prompt_record = f"<USER_REQUEST>[Celular] {payload.message} {imgs_annot}".strip() + "</USER_REQUEST>"

    try:
        with open(TRANSCRIPT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": now_iso,
                "content": prompt_record
            }) + "\n")
            f.write(json.dumps({
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "created_at": now_iso,
                "content": reply
            }) + "\n")
    except Exception:
        pass

    return {"status": "ok", "reply": reply}


@router.post("/api/remote/upload")
async def upload_mobile_image(file: UploadFile = File(...)):
    """Recebe um print ou foto do celular e salva para uso imediato no chat."""
    ext = Path(file.filename or "print.png").suffix or ".png"
    unique_name = f"mobile_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
    dest = UPLOAD_DIR / unique_name

    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    return {
        "status": "ok",
        "filename": unique_name,
        "url": f"/api/remote/image/{unique_name}"
    }


@router.post("/api/remote/upload-multi")
async def upload_multi_mobile_images(files: List[UploadFile] = File(...)):
    """Recebe múltiplos prints/fotos do celular simultaneamente em lote."""
    results = []
    for file in files:
        ext = Path(file.filename or "print.png").suffix or ".png"
        unique_name = f"mobile_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
        dest = UPLOAD_DIR / unique_name
        content = await file.read()
        with open(dest, "wb") as f:
            f.write(content)
        results.append({
            "original_name": file.filename or unique_name,
            "filename": unique_name,
            "url": f"/api/remote/image/{unique_name}"
        })
    return {"status": "ok", "files": results}

