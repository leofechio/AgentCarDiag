"""
homesim_proxy.py — Proxy Reverso HTTP & WebSocket para HomeSIM
Roteia requisições de /homesim no AgentCarDiag (porta 8000) diretamente para o HomeSIM (porta 8090)
"""

import logging
from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
import httpx
import websockets

logger = logging.getLogger("cardiag.homesim_proxy")
router = APIRouter(tags=["HomeSIM Proxy"])

HOMESIM_UPSTREAM_HTTP = "http://127.0.0.1:8090"
HOMESIM_UPSTREAM_WS = "ws://127.0.0.1:8090"


@router.api_route("/homesim{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"], include_in_schema=False)
async def proxy_homesim_http(request: Request, path: str = ""):
    """Proxy HTTP assíncrono para o HomeSIM."""
    target_url = f"{HOMESIM_UPSTREAM_HTTP}/homesim{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
            upstream_resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body if body else None,
            )

            # Filtra headers hop-by-hop
            resp_headers = dict(upstream_resp.headers)
            for hop in ["content-encoding", "transfer-encoding", "connection", "keep-alive"]:
                resp_headers.pop(hop, None)

            return Response(
                content=upstream_resp.content,
                status_code=upstream_resp.status_code,
                headers=resp_headers,
                media_type=upstream_resp.headers.get("content-type")
            )
    except httpx.ConnectError:
        return Response(
            content="<b>HomeSIM Server indisponível ou iniciando na porta 8090.</b>",
            status_code=503,
            media_type="text/html"
        )
    except Exception as e:
        logger.error(f"Erro no proxy do HomeSIM: {e}")
        return Response(
            content=f"Erro interno no proxy HomeSIM: {str(e)}",
            status_code=502,
            media_type="text/plain"
        )


@router.websocket("/homesim/ws/live")
async def proxy_homesim_ws(client_ws: WebSocket):
    """Proxy bidirecional para o WebSocket do HomeSIM."""
    await client_ws.accept()
    upstream_url = f"{HOMESIM_UPSTREAM_WS}/homesim/ws/live"

    try:
        async with websockets.connect(upstream_url) as server_ws:
            import asyncio

            async def client_to_server():
                try:
                    while True:
                        msg = await client_ws.receive_text()
                        await server_ws.send(msg)
                except (WebSocketDisconnect, Exception):
                    pass

            async def server_to_client():
                try:
                    async for msg in server_ws:
                        await client_ws.send_text(msg)
                except Exception:
                    pass

            await asyncio.gather(client_to_server(), server_to_client(), return_exceptions=True)

    except Exception as e:
        logger.warning(f"Erro na ponte WebSocket do HomeSIM: {e}")
    finally:
        try:
            await client_ws.close()
        except Exception:
            pass
