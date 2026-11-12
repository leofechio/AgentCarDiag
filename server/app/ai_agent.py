import os
import json
import logging
import urllib.request
import urllib.error
import asyncio

# Tenta ler o .env diretamente se não estiver no os.environ
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"\'')

from app.agent_tools import read_obd_live_data

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"

SYSTEM_INSTRUCTION = (
    "Você é o Agente Diagnosta Automotivo Sênior do AgentCarDiag. "
    "Sua função é cruzar dados digitais e anomalias físicas para encontrar o defeito. "
    "Você pode requisitar a leitura de PIDs específicos no veículo em tempo real se a causa for incerta. "
    "Regras: "
    "1. Se a defasagem de dentes (tooth_offset) for > 0, é problema de sincronismo mecânico. "
    "2. Se você suspeitar de mistura rica/pobre, PEÇA PARA LER OS PIDS de Fuel Trim (ex: 0114) ou Sonda Lambda. "
    "3. Só dê a resposta final quando tiver certeza. A resposta final DEVE ser em JSON com as chaves: "
    "'veredicto_principal' (string), 'certeza_pct' (int), 'passos_oficina' (lista de strings). NUNCA DEVOLVA TEXTO PURO NA RESPOSTA FINAL."
)

TOOL_DECLARATION = {
    "functionDeclarations": [
        {
            "name": "read_obd_live_data",
            "description": "Requisita o valor atual de um PID OBD-II específico no carro em tempo real. Use isso para investigar sensores.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "pid": {
                        "type": "STRING",
                        "description": "O código hexadecimal do PID OBD-II (ex: '010C' para RPM, '0114' para Fuel Trim)."
                    }
                },
                "required": ["pid"]
            }
        }
    ]
}

async def _make_async_request(url, data_bytes):
    """Executa a chamada web de forma assíncrona para não travar o FastAPI."""
    loop = asyncio.get_running_loop()
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    def _do_req():
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            return resp.read().decode("utf-8")
            
    return await loop.run_in_executor(None, _do_req)

async def query_gemini_diagnostician(oem_data: dict, inconsistencies: list, live_summary: dict) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY).strip()
    if not api_key:
        return {
            "veredicto_principal": "Chave GEMINI_API_KEY não configurada no servidor (.env).",
            "certeza_pct": 0,
            "passos_oficina": ["Configure a GEMINI_API_KEY no arquivo .env para ativar a IA em nuvem."]
        }

    url = f"{GEMINI_ENDPOINT}?key={api_key}"
    
    # Inicia a conversa com os dados iniciais
    prompt_payload = {
        "montadora": oem_data.get("name", "Genérico"),
        "inconsistencias_detectadas": inconsistencies,
        "telemetria": live_summary
    }
    
    history = [
        {
            "role": "user",
            "parts": [{"text": f"Contexto do veículo e anomalias:\n{json.dumps(prompt_payload, ensure_ascii=False)}"}]
        }
    ]
    
    max_turns = 5
    turn = 0
    
    while turn < max_turns:
        turn += 1
        
        body = {
            "contents": history,
            "systemInstruction": {
                "parts": [{"text": SYSTEM_INSTRUCTION}]
            },
            "tools": [TOOL_DECLARATION],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.8
            }
        }

        try:
            data_bytes = json.dumps(body).encode("utf-8")
            raw_response = await _make_async_request(url, data_bytes)
            data = json.loads(raw_response)
            
            candidate = data.get("candidates", [{}])[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            
            if not parts:
                break
                
            # Verifica se o Gemini decidiu chamar uma função
            function_call = None
            for part in parts:
                if "functionCall" in part:
                    function_call = part["functionCall"]
                    break
                    
            if function_call:
                # 1. Guarda a chamada no histórico
                history.append(content)
                
                # 2. Executa a função (chamada real pro carro via WebSocket!)
                name = function_call.get("name")
                args = function_call.get("args", {})
                logger.info(f"[IA LOOP] Model requested {name} with args {args}")
                
                func_result = {}
                if name == "read_obd_live_data" and "pid" in args:
                    func_result = await read_obd_live_data(args["pid"])
                
                # 3. Devolve a resposta ao Gemini
                history.append({
                    "role": "function",
                    "parts": [{
                        "functionResponse": {
                            "name": name,
                            "response": func_result
                        }
                    }]
                })
                # Continua o loop para a IA analisar o novo dado
                continue
            
            # Se não houve chamada de função, o Gemini nos deu texto.
            # Tenta fazer o parse do JSON esperado
            raw_text = parts[0].get("text", "")
            
            # Remove marcadores Markdown caso a IA retorne ```json ... ```
            clean_text = raw_text.replace("```json\n", "").replace("```", "").strip()
            
            try:
                final_json = json.loads(clean_text)
                return final_json
            except json.JSONDecodeError:
                return {
                    "veredicto_principal": "A IA não retornou um JSON válido.",
                    "certeza_pct": 50,
                    "passos_oficina": ["Tente novamente.", f"Saída bruta: {clean_text}"]
                }

        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            logger.error(f"Erro HTTP Gemini API ({e.code}): {err_msg}")
            return {
                "veredicto_principal": f"Erro na API do Gemini ({e.code}).",
                "certeza_pct": 0,
                "passos_oficina": [f"Detalhe: {err_msg[:120]}"]
            }
        except Exception as e:
            logger.exception("Falha na requisição Gemini")
            return {
                "veredicto_principal": f"Falha na requisição da IA: {str(e)}",
                "certeza_pct": 0,
                "passos_oficina": ["Verifique a conexão com a internet e logs do container."]
            }
            
    return {
        "veredicto_principal": "A IA excedeu o número máximo de turnos de investigação.",
        "certeza_pct": 0,
        "passos_oficina": ["O problema é complexo demais para resolução automática."]
    }
