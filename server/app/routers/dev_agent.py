"""
dev_agent.py — Agente de Desenvolvimento ao Vivo
Chat com Gemini que tem acesso direto ao ESP32 Scanner via ferramentas.
"""
import os
import json
import asyncio
import logging
import urllib.request
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Dev Agent"])

SYSTEM = (
    "Voce e o AgentCarDiag Dev Bot - especialista em firmware ESP32 e diagnostico CAN/OBD-II. "
    "Voce tem acesso DIRETO ao ESP32 Scanner conectado a um carro real atraves das ferramentas. "
    "CAPACIDADES: verificar hardware, enviar PIDs OBD-II, ler respostas reais, iniciar live stream, sugerir codigo. "
    "REGRAS: "
    "1. SEMPRE use get_hardware_status antes de enviar comandos. "
    "2. Use as ferramentas para dados reais - jamais invente valores do carro. "
    "3. Responda em portugues do Brasil, linguagem tecnica mas acessivel. "
    "4. Quando sugerir codigo, use blocos markdown cpp formatados."
)

TOOLS = {
    "functionDeclarations": [
        {
            "name": "get_hardware_status",
            "description": "Verifica se ESP32 Scanner esta conectado e retorna ping em ms.",
            "parameters": {"type": "OBJECT", "properties": {}}
        },
        {
            "name": "send_obd_query",
            "description": (
                "Envia um PID OBD-II ao carro via ESP32 e retorna resposta HEX bruta. "
                "Exemplos: 010C=RPM, 010D=Velocidade, 0105=TempRefrigeracao, "
                "010F=TempAr, 0111=PosicaoAcelerador, 03=lerDTCs, 04=limparDTCs."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "PID OBD-II em HEX, ex: 010C"
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "start_live_stream",
            "description": "Inicia leitura continua de multiplos PIDs ao mesmo tempo.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "pids": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "Lista de PIDs, ex: ['010C','010D','0105']"
                    }
                },
                "required": ["pids"]
            }
        },
        {
            "name": "stop_live_stream",
            "description": "Para o monitoramento continuo de PIDs.",
            "parameters": {"type": "OBJECT", "properties": {}}
        },
        {
            "name": "set_protocol",
            "description": "Altera o protocolo de comunicacao veicular do hardware: 'can' (CAN Bus pinos 6/14) ou 'kline' (Linha K / KWP2000 pino 7 ou selecionado no MUX).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "proto": {
                        "type": "STRING",
                        "description": "Protocolo: 'can' ou 'kline'"
                    }
                },
                "required": ["proto"]
            }
        },
        {
            "name": "set_obd_module",
            "description": "Aciona o multiplexador de hardware para chavear a Linha K para outros modulos veiculares (ECU pino 7, ABS pino 1, Airbag pino 3, Cambio pino 11, BCM pinos 8/9).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "pin": {
                        "type": "INTEGER",
                        "description": "Pino OBD2 desejado: 7 (ECU/Motor), 1 (ABS), 3 (Airbag), 11 (Cambio), 8/9 (BCM), 12/13 (Auxiliar)"
                    },
                    "module": {
                        "type": "STRING",
                        "description": "Nome do modulo: 'ECU', 'ABS', 'AIRBAG', 'CAMBIO', 'BCM'"
                    }
                },
                "required": ["pin"]
            }
        }
    ]
}


async def execute_tool(name: str, args: dict, gw) -> dict:
    """Executa a ferramenta solicitada pela IA."""
    if name == "get_hardware_status":
        result = {
            dt: {"connected": n["ws"] is not None, "ping_ms": round(n.get("ping_ms", 0), 1)}
            for dt, n in gw.nodes.items()
        }
        return {
            "hardware": result,
            "any_connected": any(n["ws"] is not None for n in gw.nodes.values())
        }

    if name == "send_obd_query":
        q = args.get("query", "")
        sc = gw.nodes.get("Scanner_CAN")
        if not sc or not sc["ws"]:
            return {"error": "ESP32 Scanner nao esta conectado. Verifique se esta ligado e na mesma rede."}
        try:
            await sc["ws"].send_text(json.dumps({"cmd": "obd_send", "query": q}))
            await asyncio.sleep(1.5)
            last = gw.last_response.get(q)
            if last:
                return {"query": q, "raw": last, "status": "received"}
            return {
                "query": q, "raw": None, "status": "timeout",
                "note": "Sem resposta em 1.5s. Carro desligado ou PID nao suportado neste veiculo."
            }
        except Exception as e:
            return {"error": str(e)}

    if name == "start_live_stream":
        pids = args.get("pids", [])
        sc = gw.nodes.get("Scanner_CAN")
        if not sc or not sc["ws"]:
            return {"error": "ESP32 Scanner nao esta conectado."}
        await sc["ws"].send_text(json.dumps({"cmd": "start_live_stream", "pids": pids}))
        return {"status": "started", "pids": pids}

    if name == "stop_live_stream":
        sc = gw.nodes.get("Scanner_CAN")
        if sc and sc["ws"]:
            await sc["ws"].send_text(json.dumps({"cmd": "stop_live_stream"}))
        return {"status": "stopped"}

    if name == "set_protocol":
        proto = args.get("proto", "can").lower()
        sc = gw.nodes.get("Scanner_CAN")
        if not sc or not sc["ws"]:
            return {"error": "ESP32 Scanner nao esta conectado."}
        try:
            await sc["ws"].send_text(json.dumps({"cmd": "set_protocol", "proto": proto}))
            sc["proto"] = proto
            return {"status": "protocol_updated", "proto": proto}
        except Exception as e:
            return {"error": str(e)}

    if name == "set_obd_module":
        pin = int(args.get("pin", 7))
        module = args.get("module", "ECU").upper()
        sc = gw.nodes.get("Scanner_CAN")
        if not sc or not sc["ws"]:
            return {"error": "ESP32 Scanner nao esta conectado."}
        try:
            await sc["ws"].send_text(json.dumps({"cmd": "set_module_pin", "pin": pin, "module": module}))
            sc["pin"] = pin
            sc["module"] = module
            return {"status": "module_pin_switched", "pin": pin, "module": module}
        except Exception as e:
            return {"error": str(e)}

    return {"error": f"Ferramenta desconhecida: {name}"}


async def _call_gemini(history: list, api_key: str) -> dict:
    """Chama a API do Gemini de forma assíncrona."""
    ep = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={api_key}"
    )
    body = {
        "contents": history,
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "tools": [TOOLS],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 8192}
    }
    req = urllib.request.Request(
        ep,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(
        None,
        lambda: urllib.request.urlopen(req, timeout=30).read().decode()
    )
    return json.loads(raw)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    chat_id: Optional[str] = None      # None = nova conversa
    history: Optional[List[ChatMessage]] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_dev_agent_router(gw_ref):
    """Cria o router injetando a referência ao gateway_manager."""

    # ── Histórico ───────────────────────────────────────────────────────────────

    @router.get("/dev_agent/chats")
    async def list_chats():
        """Lista todas as conversas salvas, mais recentes primeiro."""
        async with get_db() as db:
            async with db.execute(
                "SELECT id, title, created_at, updated_at FROM agent_chats ORDER BY updated_at DESC"
            ) as cur:
                rows = await cur.fetchall()
        return [{"id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]} for r in rows]

    @router.get("/dev_agent/chats/{chat_id}")
    async def get_chat(chat_id: str):
        """Retorna uma conversa com todas as mensagens."""
        async with get_db() as db:
            async with db.execute(
                "SELECT id, title, created_at, updated_at FROM agent_chats WHERE id=?", (chat_id,)
            ) as cur:
                chat = await cur.fetchone()
            if not chat:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Conversa não encontrada")
            async with db.execute(
                "SELECT role, content, created_at FROM agent_messages WHERE chat_id=? ORDER BY created_at ASC",
                (chat_id,)
            ) as cur:
                msgs = await cur.fetchall()
        return {
            "id": chat[0], "title": chat[1], "created_at": chat[2], "updated_at": chat[3],
            "messages": [{"role": r[0], "content": r[1], "created_at": r[2]} for r in msgs]
        }

    @router.delete("/dev_agent/chats/{chat_id}")
    async def delete_chat(chat_id: str):
        """Apaga uma conversa e todas as mensagens (CASCADE)."""
        async with get_db() as db:
            await db.execute("DELETE FROM agent_chats WHERE id=?", (chat_id,))
            await db.commit()
        return {"deleted": chat_id}

    # ── Chat com persistência ───────────────────────────────────────────────────

    @router.post("/dev_agent/chat")
    async def dev_agent_chat(req: ChatRequest):
        """Chat ao vivo com IA via SSE. Salva automaticamente no banco."""
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            return {"error": "GEMINI_API_KEY nao configurada no servidor."}

        # Determina se é conversa nova ou continuação
        chat_id = req.chat_id
        is_new_chat = not chat_id

        # Monta histórico Gemini
        history = [
            {"role": "user" if m.role == "user" else "model", "parts": [{"text": m.content}]}
            for m in (req.history or [])
        ]
        history.append({"role": "user", "parts": [{"text": req.message}]})

        async def generate():
            nonlocal chat_id

            # Cria registro no banco se conversa nova
            if is_new_chat:
                chat_id = str(uuid.uuid4())
                # Título = primeiros 60 chars da mensagem do usuário
                title = req.message[:60] + ("..." if len(req.message) > 60 else "")
                now = _now()
                async with get_db() as db:
                    await db.execute(
                        "INSERT INTO agent_chats (id, title, created_at, updated_at) VALUES (?,?,?,?)",
                        (chat_id, title, now, now)
                    )
                    await db.execute(
                        "INSERT INTO agent_messages (chat_id, role, content, created_at) VALUES (?,?,?,?)",
                        (chat_id, "user", req.message, now)
                    )
                    await db.commit()
                # Envia o chat_id para o frontend saber qual ID usar nas próximas msgs
                yield f"data: {json.dumps({'type': 'chat_id', 'chat_id': chat_id})}\n\n"
            else:
                # Salva a mensagem do usuário na conversa existente
                now = _now()
                async with get_db() as db:
                    await db.execute(
                        "INSERT INTO agent_messages (chat_id, role, content, created_at) VALUES (?,?,?,?)",
                        (chat_id, "user", req.message, now)
                    )
                    await db.execute(
                        "UPDATE agent_chats SET updated_at=? WHERE id=?", (now, chat_id)
                    )
                    await db.commit()

            # Loop Gemini com function calling
            lh = history.copy()
            ai_response = ""

            for _ in range(6):
                try:
                    data = await _call_gemini(lh, api_key)
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
                    return

                cand = data.get("candidates", [{}])[0]
                cont = cand.get("content", {})
                parts = cont.get("parts", [])
                if not parts:
                    return

                fn = next((p.get("functionCall") for p in parts if "functionCall" in p), None)

                if fn:
                    fn_name = fn.get("name")
                    fn_args = fn.get("args", {})
                    yield f"data: {json.dumps({'type': 'tool_call', 'tool': fn_name, 'args': fn_args})}\n\n"
                    res = await execute_tool(fn_name, fn_args, gw_ref)
                    yield f"data: {json.dumps({'type': 'tool_result', 'tool': fn_name, 'result': res})}\n\n"
                    lh.append(cont)
                    lh.append({
                        "role": "user",
                        "parts": [{"functionResponse": {"name": fn_name, "response": res}}]
                    })
                    continue

                text = next((p.get("text", "") for p in parts if "text" in p), "")
                if text:
                    ai_response = text
                    yield f"data: {json.dumps({'type': 'message', 'content': text})}\n\n"

                # Salva resposta da IA no banco
                if ai_response and chat_id:
                    now = _now()
                    async with get_db() as db:
                        await db.execute(
                            "INSERT INTO agent_messages (chat_id, role, content, created_at) VALUES (?,?,?,?)",
                            (chat_id, "assistant", ai_response, now)
                        )
                        await db.execute(
                            "UPDATE agent_chats SET updated_at=? WHERE id=?", (now, chat_id)
                        )
                        await db.commit()

                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'error', 'content': 'Maximo de turnos atingido.'})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    return router
