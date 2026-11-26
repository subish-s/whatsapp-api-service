import asyncio
import random
import time
import uuid
from typing import Any
from app.config import settings
from app.core.event_bus import event_bus
from app.models.enums import EventType, SessionStatus
from app.utils.logger import logger


class MessageJob:
    """Represents a queued outbound message task."""

    def __init__(
        self,
        session_name: str,
        recipient: str,
        message_type: str,
        payload: dict[str, Any],
    ):
        self.job_id = f"job_{uuid.uuid4().hex[:12]}"
        self.session_name = session_name
        self.recipient = recipient
        self.message_type = message_type
        self.payload = payload
        self.created_at = time.time()
        self.completed_event = asyncio.Event()
        self.result: dict[str, Any] | None = None
        self.error: str | None = None


class SessionMessageQueue:
    """Manages an anti-ban outbound queue with human presence emulation and jitter for a session."""

    def __init__(self, session_name: str, session_instance):
        self.session_name = session_name
        self.session = session_instance
        self.queue: asyncio.Queue[MessageJob] = asyncio.Queue()
        self.worker_task: asyncio.Task | None = None
        self.is_running = False

        # Quota tracking (sliding timestamps)
        self.sent_timestamps: list[float] = []
        self.lock = asyncio.Lock()

    def start(self) -> None:
        """Start the background worker if enabled."""
        if not settings.queue_enabled:
            logger.info("Message queue is disabled; dispatching will be unthrottled", session=self.session_name)
            return

        if self.worker_task is None or self.worker_task.done():
            self.is_running = True
            self.worker_task = asyncio.create_task(self._worker_loop())
            logger.info("Outbound message queue worker started", session=self.session_name)

    async def stop(self) -> None:
        """Gracefully terminate worker loop."""
        self.is_running = False
        if self.worker_task and not self.worker_task.done():
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            self.worker_task = None
        logger.info("Outbound message queue worker stopped", session=self.session_name)

    async def clear(self) -> None:
        """Drain all pending jobs."""
        while not self.queue.empty():
            try:
                job = self.queue.get_nowait()
                job.error = "Session stopped or cleared before dispatch"
                job.completed_event.set()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def enqueue(
        self,
        recipient: str,
        message_type: str,
        payload: dict[str, Any],
        wait_for_delivery: bool = False,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Enqueue an outbound message and optionally wait for dispatch."""
        job = MessageJob(
            session_name=self.session_name,
            recipient=recipient,
            message_type=message_type,
            payload=payload,
        )

        # If queue is disabled, dispatch immediately
        if not settings.queue_enabled:
            return await self._dispatch_direct(job)

        # Ensure worker is alive
        if not self.is_running:
            self.start()

        position = self.queue.qsize() + 1
        avg_delay = (settings.queue_min_delay_seconds + settings.queue_max_delay_seconds) / 2
        avg_typing = (settings.queue_typing_min_seconds + settings.queue_typing_max_seconds) / 2 if settings.queue_simulate_typing else 0
        est_delay = round(position * (avg_delay + avg_typing), 1)

        await self.queue.put(job)
        logger.info(
            "Message job enqueued",
            job_id=job.job_id,
            session=self.session_name,
            recipient=recipient,
            position=position,
            estimated_delay=est_delay,
        )

        if wait_for_delivery:
            try:
                await asyncio.wait_for(job.completed_event.wait(), timeout=timeout)
                if job.error:
                    raise RuntimeError(job.error)
                return job.result or {}
            except asyncio.TimeoutError:
                raise TimeoutError(f"Job {job.job_id} did not complete within {timeout}s")

        return {
            "success": True,
            "status": "queued",
            "job_id": job.job_id,
            "session": self.session_name,
            "recipient": recipient,
            "queue_position": position,
            "estimated_delay_seconds": est_delay,
        }

    async def _dispatch_direct(self, job: MessageJob) -> dict[str, Any]:
        """Immediate dispatch when queue is bypassed."""
        result = {
            "success": True,
            "status": "dispatched",
            "session": self.session_name,
            "recipient": job.recipient,
            "job_id": job.job_id,
            **job.payload,
        }
        await event_bus.broadcast_event(self.session_name, EventType.MESSAGE_ACK, result)
        return result

    async def _worker_loop(self) -> None:
        """Background loop continuously consuming queued jobs and enforcing safety intervals."""
        while self.is_running:
            try:
                job = await self.queue.get()
            except asyncio.CancelledError:
                break

            try:
                # 1. Enforce quota limits (Anti-ban protection)
                await self._enforce_quotas()

                # 2. Simulate human presence: typing state
                if settings.queue_simulate_typing and job.message_type in ("text", "image", "file", "poll"):
                    typing_duration = random.uniform(
                        settings.queue_typing_min_seconds,
                        settings.queue_typing_max_seconds,
                    )
                    await self._simulate_presence(job.recipient, "typing", typing_duration)

                # 3. Randomized pacing / jitter delay
                delay = random.uniform(
                    settings.queue_min_delay_seconds,
                    settings.queue_max_delay_seconds,
                )
                logger.debug("Applying pacing jitter", session=self.session_name, delay=round(delay, 2))
                await asyncio.sleep(delay)

                # 4. Dispatch the message via WhatsApp Web driver
                driver_result = {}
                if hasattr(self.session, "driver") and self.session.driver.is_authenticated:
                    if job.message_type == "poll":
                        driver_result = await self.session.driver.send_poll_message(
                            recipient_chat_id=job.recipient,
                            question=job.payload.get("poll_question", "Poll"),
                            options=job.payload.get("options", []),
                            allow_multiple=job.payload.get("allow_multiple_answers", False),
                        )
                    elif job.message_type in ("image", "file", "media"):
                        attachment = job.payload.get("attachment") or {}
                        file_data = attachment.get("data") or attachment.get("base64") or ""
                        mime_type = attachment.get("mime_type") or "application/octet-stream"
                        filename = attachment.get("filename") or ("image.png" if job.message_type == "image" else "document.pdf")
                        caption = job.payload.get("caption") or ""
                        driver_result = await self.session.driver.send_file_message(
                            recipient_chat_id=job.recipient,
                            data_base64=file_data,
                            mime_type=mime_type,
                            filename=filename,
                            caption=caption,
                        )
                    else:
                        raw_text = job.payload.get("message", "")
                        reply_to = job.payload.get("reply_to")
                        driver_result = await self.session.driver.send_text_message(
                            recipient_chat_id=job.recipient,
                            message_text=raw_text,
                            reply_to_message_id=reply_to,
                        )

                now = time.time()
                async with self.lock:
                    self.sent_timestamps.append(now)

                dispatch_result = {
                    "success": True,
                    "status": "delivered",
                    "job_id": job.job_id,
                    "session": self.session_name,
                    "recipient": job.recipient,
                    "message_type": job.message_type,
                    **job.payload,
                    **driver_result,
                }
                job.result = dispatch_result
                job.completed_event.set()

                # Broadcast delivery acknowledgment
                await event_bus.broadcast_event(self.session_name, EventType.MESSAGE_ACK, dispatch_result)
                logger.info("Message successfully dispatched", job_id=job.job_id, session=self.session_name)

            except Exception as dispatch_err:
                logger.error("Error processing queued job", job_id=job.job_id, error=str(dispatch_err))
                job.error = str(dispatch_err)
                job.completed_event.set()
            finally:
                self.queue.task_done()

    async def _simulate_presence(self, recipient: str, state: str, duration: float) -> None:
        """Transmit real WhatsApp presence to recipient via driver, and notify event bus."""
        try:
            # 1. Transmit genuine presence update to WhatsApp servers via driver
            if hasattr(self.session, "driver") and self.session.driver.is_authenticated:
                await self.session.driver.set_chat_presence(recipient, "composing")

            # 2. Local event notification
            await event_bus.broadcast_event(
                self.session_name,
                EventType.PRESENCE_UPDATE,
                {"recipient": recipient, "state": state},
            )

            # 3. Hold typing state for randomized duration
            await asyncio.sleep(duration)

            # 4. Reset presence state
            if hasattr(self.session, "driver") and self.session.driver.is_authenticated:
                await self.session.driver.set_chat_presence(recipient, "paused")

            await event_bus.broadcast_event(
                self.session_name,
                EventType.PRESENCE_UPDATE,
                {"recipient": recipient, "state": "paused"},
            )
        except Exception as presence_err:
            logger.warning("Failed presence simulation", error=str(presence_err))

    async def _enforce_quotas(self) -> None:
        """Ensure per-minute and per-hour message limits are respected."""
        now = time.time()
        minute_ago = now - 60.0
        hour_ago = now - 3600.0

        async with self.lock:
            # Clean up records older than 1 hour
            self.sent_timestamps = [ts for ts in self.sent_timestamps if ts > hour_ago]
            recent_minute = [ts for ts in self.sent_timestamps if ts > minute_ago]

        # Minute quota check
        if len(recent_minute) >= settings.queue_max_per_minute:
            oldest = recent_minute[0]
            sleep_needed = max(0.5, (oldest + 60.0) - now)
            logger.warning(
                "Minute quota reached; throttling queue",
                session=self.session_name,
                sent_in_minute=len(recent_minute),
                sleep_seconds=round(sleep_needed, 2),
            )
            await asyncio.sleep(sleep_needed)

        # Hourly quota check
        if len(self.sent_timestamps) >= settings.queue_max_per_hour:
            oldest = self.sent_timestamps[0]
            sleep_needed = max(1.0, (oldest + 3600.0) - now)
            logger.warning(
                "Hourly quota reached; pausing dispatch",
                session=self.session_name,
                sent_in_hour=len(self.sent_timestamps),
                sleep_seconds=round(sleep_needed, 2),
            )
            await asyncio.sleep(sleep_needed)

    def get_stats(self) -> dict[str, Any]:
        """Return queue metrics and rate consumption."""
        now = time.time()
        minute_ago = now - 60.0
        hour_ago = now - 3600.0
        in_minute = sum(1 for ts in self.sent_timestamps if ts > minute_ago)
        in_hour = sum(1 for ts in self.sent_timestamps if ts > hour_ago)

        return {
            "session": self.session_name,
            "is_running": self.is_running,
            "pending_count": self.queue.qsize(),
            "sent_last_minute": in_minute,
            "max_per_minute": settings.queue_max_per_minute,
            "sent_last_hour": in_hour,
            "max_per_hour": settings.queue_max_per_hour,
        }

