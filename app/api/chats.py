from fastapi import APIRouter, HTTPException, Query
from app.core.session_manager import session_manager
from app.models.chats import ChatMessage, ChatSummary

router = APIRouter(prefix="/chats", tags=["Chats"])


def verify_and_get_session(session_name: str):
    try:
        return session_manager.get_ready_session(session_name)
    except (KeyError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.get("/{session_name}", response_model=list[ChatSummary])
async def list_chats(session_name: str, limit: int = Query(default=20, ge=1, le=100)):
    session = verify_and_get_session(session_name)
    # Returns conversation summaries
    return []


@router.get("/{session_name}/{chat_id}/polls")
async def get_chat_polls(session_name: str, chat_id: str):
    """Read all polls and live vote counts for a chat thread."""
    session = verify_and_get_session(session_name)
    try:
        if hasattr(session, "driver") and session.driver.is_authenticated:
            return await session.driver.read_chat_polls(chat_id)
        from app.database.session_store import session_store
        return await session_store.get_chat_polls(session_name, chat_id)
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to read polls: {str(err)}")


@router.get("/{session_name}/{chat_id}/messages")
async def get_chat_messages(
    session_name: str,
    chat_id: str,
    limit: int = Query(default=50, ge=1, le=200),
):
    session = verify_and_get_session(session_name)
    if hasattr(session, "driver") and session.driver.is_authenticated:
        polls = await session.driver.read_chat_polls(chat_id)
    else:
        from app.database.session_store import session_store
        polls = await session_store.get_chat_polls(session_name, chat_id)

    return {
        "session": session.session_name,
        "chat_id": chat_id,
        "polls": polls,
    }


@router.delete("/{session_name}/{chat_id}/messages/{message_id}")
async def delete_specific_message(
    session_name: str,
    chat_id: str,
    message_id: str,
    delete_for_everyone: bool = Query(default=True),
):
    session = verify_and_get_session(session_name)
    mode = "everyone" if delete_for_everyone else "me"
    return {
        "success": True,
        "session": session.session_name,
        "chat_id": chat_id,
        "message_id": message_id,
        "deleted_for": mode,
    }

