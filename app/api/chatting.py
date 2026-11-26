from fastapi import APIRouter, HTTPException, Query
from app.core.session_manager import session_manager
from app.models.chatting import (
    CastPollVoteRequest,
    DeleteMessageRequest,
    SendMediaMessageRequest,
    SendPollRequest,
    SendPresenceRequest,
    SendReactionRequest,
    SendTextMessageRequest,
)

router = APIRouter(tags=["Chatting"])


def verify_and_get_session(session_name: str):
    try:
        return session_manager.get_ready_session(session_name)
    except (KeyError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/sendText")
async def send_text_message(
    payload: SendTextMessageRequest,
    wait_for_delivery: bool = Query(default=False, description="Wait synchronously until message is dispatched"),
):
    session = verify_and_get_session(payload.session_name)
    try:
        return await session.message_queue.enqueue(
            recipient=payload.recipient_chat_id,
            message_type="text",
            payload={
                "message": payload.message_text,
                "reply_to": payload.reply_to_message_id,
            },
            wait_for_delivery=wait_for_delivery,
        )
    except TimeoutError as timeout_err:
        raise HTTPException(status_code=504, detail=str(timeout_err))


@router.post("/sendImage")
async def send_image_message(
    payload: SendMediaMessageRequest,
    wait_for_delivery: bool = Query(default=False, description="Wait synchronously until message is dispatched"),
):
    session = verify_and_get_session(payload.session_name)
    try:
        return await session.message_queue.enqueue(
            recipient=payload.recipient_chat_id,
            message_type="image",
            payload={
                "caption": payload.caption,
                "attachment": payload.attachment.model_dump(),
                "reply_to": payload.reply_to_message_id,
            },
            wait_for_delivery=wait_for_delivery,
        )
    except TimeoutError as timeout_err:
        raise HTTPException(status_code=504, detail=str(timeout_err))


@router.post("/sendFile")
async def send_file_document(
    payload: SendMediaMessageRequest,
    wait_for_delivery: bool = Query(default=False, description="Wait synchronously until message is dispatched"),
):
    session = verify_and_get_session(payload.session_name)
    try:
        return await session.message_queue.enqueue(
            recipient=payload.recipient_chat_id,
            message_type="file",
            payload={
                "caption": payload.caption,
                "attachment": payload.attachment.model_dump(),
                "reply_to": payload.reply_to_message_id,
            },
            wait_for_delivery=wait_for_delivery,
        )
    except TimeoutError as timeout_err:
        raise HTTPException(status_code=504, detail=str(timeout_err))


@router.put("/reaction")
async def set_message_reaction(payload: SendReactionRequest):
    session = verify_and_get_session(payload.session_name)
    try:
        return await session.driver.send_reaction(payload.message_id, payload.emoji)
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to set reaction: {str(err)}")


@router.post("/presence")
async def set_chat_presence(payload: SendPresenceRequest):
    session = verify_and_get_session(payload.session_name)
    try:
        await session.driver.set_chat_presence(payload.recipient_chat_id, payload.presence_state)
        return {
            "success": True,
            "session": session.session_name,
            "recipient": payload.recipient_chat_id,
            "state": payload.presence_state,
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to set presence: {str(err)}")


# --- Poll Operations ---

@router.post("/sendPoll")
async def send_poll_message(
    payload: SendPollRequest,
    wait_for_delivery: bool = Query(default=False, description="Wait synchronously until poll is dispatched"),
):
    session = verify_and_get_session(payload.session_name)
    try:
        return await session.message_queue.enqueue(
            recipient=payload.recipient_chat_id,
            message_type="poll",
            payload={
                "poll_question": payload.poll_question,
                "options": payload.poll_options,
                "allow_multiple_answers": payload.allow_multiple_answers,
            },
            wait_for_delivery=wait_for_delivery,
        )
    except TimeoutError as timeout_err:
        raise HTTPException(status_code=504, detail=str(timeout_err))


@router.post("/sendPollVote")
async def cast_poll_vote(payload: CastPollVoteRequest):
    session = verify_and_get_session(payload.session_name)
    return {
        "success": True,
        "session": session.session_name,
        "recipient": payload.recipient_chat_id,
        "poll_message_id": payload.poll_message_id,
        "selected_options": payload.selected_options,
    }


# --- Message Deletion (For Me or For Everyone/Both) ---

@router.post("/deleteMessage")
async def delete_message(payload: DeleteMessageRequest):
    session = verify_and_get_session(payload.session_name)
    try:
        return await session.driver.delete_message(
            recipient_chat_id=payload.recipient_chat_id,
            message_id=payload.message_id,
            delete_for_everyone=payload.delete_for_everyone,
        )
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to delete message: {str(err)}")


# --- Queue Management Endpoints ---

@router.get("/queue/{session_name}")
async def get_session_queue_metrics(session_name: str):
    """Inspect queue depth and rate limit statistics for a session."""
    session = verify_and_get_session(session_name)
    return session.message_queue.get_stats()


@router.delete("/queue/{session_name}")
async def clear_session_queue_items(session_name: str):
    """Discard all unhandled jobs currently in the session queue."""
    session = verify_and_get_session(session_name)
    await session.message_queue.clear()
    return {"success": True, "message": f"Queue for session '{session_name}' cleared."}
