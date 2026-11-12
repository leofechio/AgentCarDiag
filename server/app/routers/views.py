"""
views.py — Router de Interface Web e Páginas HTML
AgentCarDiag Server
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import STATIC_DIR
from app.dependencies import verify_credentials, verify_admin_only

logger = logging.getLogger("cardiag.views")

router = APIRouter(include_in_schema=False)


@router.get("/login", response_class=HTMLResponse)
async def serve_login():
    """Serve a interface minimalista de camuflagem do Multi-Box Honeypot Defense."""
    login_path = STATIC_DIR / "login.html"
    if not login_path.exists():
        raise HTTPException(status_code=404, detail="login.html não encontrado.")
    return HTMLResponse(content=login_path.read_text(encoding="utf-8"))


@router.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """Serve o dashboard principal. Se não autenticado no navegador, redireciona para /login."""
    try:
        await verify_credentials(request, None)
    except HTTPException:
        return RedirectResponse(url="/login")

    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html não encontrado.")
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@router.get("/admin", response_class=HTMLResponse)
async def serve_admin_panel(admin_data: dict = Depends(verify_admin_only)):
    """Serve o Painel Master da Fábrica / Linha de Produção (Apenas Admin)."""
    admin_path = STATIC_DIR / "admin.html"
    if not admin_path.exists():
        index_path = STATIC_DIR / "index.html"
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content=admin_path.read_text(encoding="utf-8"))


@router.get("/favicon.ico")
async def serve_favicon():
    """Retorna um favicon automotivo SVG limpo para evitar erros 404 nos navegadores."""
    svg_icon = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="8" fill="#0d1117"/>'
        '<circle cx="16" cy="16" r="11" fill="none" stroke="#00d4ff" stroke-width="2.5"/>'
        '<circle cx="16" cy="16" r="3" fill="#00d4ff"/>'
        '<path d="M16 5 v6 M16 21 v6 M5 16 h6 M21 16 h6" stroke="#00d4ff" stroke-width="2" stroke-linecap="round"/>'
        '</svg>'
    )
    from fastapi import Response
    return Response(content=svg_icon, media_type="image/svg+xml")
