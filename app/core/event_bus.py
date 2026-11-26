import asyncio
import time
from collections import defaultdict
from typing import Any, Callable
import httpx
from app.config import settings
from app.models.enums import EventType
from app.utils.identifiers import create_event_identifier
from app.utils.logger import logger


class EventBus:
    """Manages real-time event distribution to WebSockets and HTTP webhooks."""

    def __init__(self):
        self.subscriber_callbacks: dict[str, list[Callable]] = defaultdict(list)

    def add_subscriber(self, session_name: str, event_name: str, callback: Callable) -> Callable:
        lookup_key = f"{session_name}:{event_name}"
        self.subscriber_callbacks[lookup_key].append(callback)

        def remove_subscriber():
            if callback in self.subscriber_callbacks.get(lookup_key, []):
                self.subscriber_callbacks[lookup_key].remove(callback)

        return remove_subscriber

    async def broadcast_event(self, session_name: str, event_type: EventType, event_payload: Any) -> None:
        event_envelope = {
            "event_id": create_event_identifier(),
            "timestamp": int(time.time() * 1000),
            "session_name": session_name,
            "event_type": event_type.value,
            "payload": event_payload,
        }

        candidate_keys = [
            f"{session_name}:{event_type.value}",
            f"{session_name}:*",
            f"*:{event_type.value}",
            "*:*",
        ]

        for key in candidate_keys:
            for callback in self.subscriber_callbacks.get(key, []):
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event_envelope)
                    else:
                        callback(event_envelope)
                except Exception as callback_error:
                    logger.error("Error executing event callback", error=str(callback_error))

        if settings.webhook_target_url:
            asyncio.create_task(self.send_webhook_request(event_envelope))

    async def send_webhook_request(self, event_envelope: dict[str, Any]) -> None:
        target_url = settings.webhook_target_url
        if not target_url:
            return

        headers = {"Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as http_client:
                response = await http_client.post(target_url, json=event_envelope, headers=headers)
                if response.status_code >= 400:
                    logger.warning("Webhook returned error status", status_code=response.status_code)
        except Exception as network_error:
            logger.error("Failed to deliver webhook notification", error=str(network_error), target_url=target_url)


event_bus = EventBus()
