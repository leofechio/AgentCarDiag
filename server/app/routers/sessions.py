"""
AgentCarDiag — Sessions REST Router
Endpoints for vehicle diagnostic session management.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app import database as db

logger = logging.getLogger("cardiag.sessions")

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])


# ─── Request / Response models ────────────────────────────────────────────────

class SessionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, examples=["VW Golf 2.0 TDI - 1234ABC"])
    vehicle_profile: Optional[str] = Field(default="renault_trafic_m9r", examples=["renault_trafic_m9r"])
    notes: Optional[str] = Field(default="", max_length=2000, examples=["Reclama de falha ao acelerar em frio"])


class SessionUpdate(BaseModel):
    name: Optional[str] = None
    vehicle_profile: Optional[str] = None
    notes: Optional[str] = None
    scanner_data: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    name: str
    vehicle_profile: Optional[str] = "renault_trafic_m9r"
    notes: str
    scanner_data: Optional[str] = "{}"
    created_at: str
    updated_at: str
    is_active: int

    model_config = {"from_attributes": True}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", summary="List all sessions", response_model=list[SessionResponse])
async def list_sessions():
    """Return all diagnostic sessions ordered by most recent first."""
    return await db.list_sessions()


@router.post("", summary="Create new session", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(body: SessionCreate):
    """
    Create a new vehicle diagnostic session.
    The new session is automatically set as **active** — all incoming hardware
    telemetry will be associated with it.
    """
    session = await db.create_session(
        name=body.name, 
        notes=body.notes or "", 
        vehicle_profile=body.vehicle_profile or "renault_trafic_m9r"
    )
    return session


@router.patch("/{session_id}", summary="Update session fields", response_model=SessionResponse)
@router.put("/{session_id}", summary="Update session fields", response_model=SessionResponse)
async def update_session(session_id: str, body: SessionUpdate):
    """Update vehicle_profile, notes, or scanner_data for a specific session."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = await db.update_session(session_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return updated


@router.get("/{session_id}", summary="Get session detail")
async def get_session_detail(session_id: str, limit: int = 500):
    """
    Return session metadata + last `limit` CAN frames + last 50 OSC captures.
    """
    detail = await db.get_session_detail(session_id, limit=limit)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return detail


@router.put("/{session_id}/activate", summary="Activate session", response_model=SessionResponse)
async def activate_session(session_id: str):
    """
    Set the given session as active.
    All subsequent hardware telemetry will be stored under this session.
    Deactivates any previously active session.
    """
    # Flush any pending CAN batch before switching sessions
    await db.flush_pending()

    session = await db.activate_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    logger.info(f"Session activated: {session_id} — {session['name']!r}")
    return session


@router.delete("/{session_id}", summary="Delete session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str):
    """
    Permanently delete a session and all its associated CAN logs and OSC captures.
    """
    deleted = await db.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
