from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from app.config import settings
from app.core.event_bus import event_bus

from app.utils.logger import logger
ws_router = APIRouter()


@ws_router.websocket("/ws")
async def handle_websocket_connection(
    websocket: WebSocket,
    session_name: str = Query(default="*"),
    event_names: str = Query(default="*"),
):
    provided_key = websocket.query_params.get("x-api-key")
    if provided_key != settings.api_key:
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info("Client connected to WebSocket", session=session_name, events=event_names)

    selected_events = [event.strip() for event in event_names.split(",")]

    async def forward_event_to_client(event_data: dict):
        try:
            await websocket.send_json(event_data)
        except Exception:
            pass

    unsubscribe_functions = []
    if "*" in selected_events:
        remove_listener = event_bus.add_subscriber(session_name, "*", forward_event_to_client)
        unsubscribe_functions.append(remove_listener)
    else:
        for event_name in selected_events:
            remove_listener = event_bus.add_subscriber(session_name, event_name, forward_event_to_client)
            unsubscribe_functions.append(remove_listener)

    try:
        while True:
            client_message = await websocket.receive_text()
            if client_message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.info("Client disconnected from WebSocket", session=session_name)
    finally:
        for cancel_subscription in unsubscribe_functions:
            cancel_subscription()
