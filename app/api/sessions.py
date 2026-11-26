from fastapi import APIRouter, HTTPException
from app.core.session_manager import session_manager
from app.models.sessions import CreateSessionRequest, SessionData

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.get("", response_model=list[SessionData])
async def list_all_sessions():
    return [session.get_summary() for session in session_manager.active_sessions.values()]


@router.get("/{session_name}", response_model=SessionData)
async def get_session_details(session_name: str):
    try:
        session = session_manager.get_session(session_name)
        return session.get_summary()
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("", response_model=SessionData)
async def create_new_session(payload: CreateSessionRequest):
    try:
        return await session_manager.create_session(
            payload.session_name,
            start_immediately=payload.start_immediately,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/{session_name}/start", response_model=SessionData)
async def start_session_connection(session_name: str):
    try:
        session = session_manager.get_session(session_name)
        await session.start_connection()
        return session.get_summary()
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/{session_name}/stop", response_model=SessionData)
async def stop_session_connection(session_name: str):
    try:
        session = session_manager.get_session(session_name)
        await session.stop_connection()
        return session.get_summary()
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.get("/{session_name}/auth/qr")
async def get_session_qr_code(session_name: str):
    try:
        session = session_manager.get_session(session_name)
        return {
            "session_name": session.session_name,
            "status": session.status.value,
            "qr_image": session.qr_code_image,
            "qr_raw": getattr(session, "qr_raw", None),
            "ascii_qr": getattr(session, "ascii_qr", None),
            "message": "Scan this QR code with WhatsApp on your phone" if session.qr_code_image else "QR code is not yet generated or session is already authenticated",
        }
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.delete("/{session_name}")
async def delete_session(session_name: str):
    try:
        await session_manager.remove_session(session_name)
        return {"success": True, "message": f"Session '{session_name}' deleted."}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error))
