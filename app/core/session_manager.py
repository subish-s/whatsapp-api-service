from asyncio import Lock
from app.config import settings
from app.core.event_bus import event_bus
from app.core.message_queue import SessionMessageQueue
from app.core.whatsapp_driver import WhatsAppDriver
from app.database.session_store import session_store
from app.models.enums import EventType, SessionStatus
from app.models.sessions import SessionData
from app.utils.logger import logger


class WhatsAppSession:
    """Represents a WhatsApp connection."""

    def __init__(self, session_name: str):
        self.session_name = session_name
        self.status = SessionStatus.STOPPED
        self.account_number: str | None = None
        self.account_name: str | None = None
        self.qr_code_image: str | None = None
        self.qr_raw: str | None = None
        self.ascii_qr: str | None = None
        self.message_queue = SessionMessageQueue(session_name, self)
        self.driver = WhatsAppDriver(session_name, self)

    def get_summary(self) -> SessionData:
        return SessionData(
            session_name=self.session_name,
            status=self.status,
            account_number=self.account_number,
            account_name=self.account_name,
        )

    async def start_connection(self) -> None:
        self.status = SessionStatus.STARTING
        await session_store.save_session_status(self.session_name, self.status.value)
        await event_bus.broadcast_event(self.session_name, EventType.SESSION_STATUS, {"status": self.status.value})

        stored_credentials = await session_store.get_authentication_credentials(self.session_name)

        # Boot native Playwright WhatsApp driver with saved cookies / storage state
        await self.driver.start(stored_credentials=stored_credentials)
        logger.info(f"Driver started for session '{self.session_name}', awaiting authentication or chat ready")

    async def stop_connection(self) -> None:
        await self.message_queue.stop()
        await self.driver.close()
        self.status = SessionStatus.STOPPED
        await session_store.save_session_status(self.session_name, self.status.value)
        await event_bus.broadcast_event(self.session_name, EventType.SESSION_STATUS, {"status": self.status.value})
        logger.info(f"Session '{self.session_name}' stopped")

    async def logout_and_clear(self) -> None:
        import shutil
        await self.message_queue.clear()
        await self.stop_connection()
        await session_store.delete_session_record(self.session_name)
        await session_store.delete_session_archive(self.session_name)
        shutil.rmtree(self.driver.user_data_dir, ignore_errors=True)
        logger.info(f"Session '{self.session_name}' logged out and cleared from MongoDB GridFS and disk")


class SessionManager:
    """Central registry controlling all active sessions."""

    def __init__(self):
        self.active_sessions: dict[str, WhatsAppSession] = {}
        self.operation_lock = Lock()

    async def bootstrap_sessions(self) -> None:
        session_names = [
            name.strip()
            for name in settings.auto_start_session_names.split(",")
            if name.strip()
        ]
        for name in session_names:
            try:
                await self.create_session(name, start_immediately=True)
            except Exception as creation_error:
                logger.error("Failed to auto-start session", session=name, error=str(creation_error))

    async def stop_all_sessions(self) -> None:
        for session_instance in list(self.active_sessions.values()):
            try:
                await session_instance.stop_connection()
            except Exception:
                pass

    def get_session(self, session_name: str) -> WhatsAppSession:
        session_instance = self.active_sessions.get(session_name)
        if not session_instance:
            raise KeyError(f"Session '{session_name}' was not found.")
        return session_instance

    def get_ready_session(self, session_name: str) -> WhatsAppSession:
        session_instance = self.get_session(session_name)
        if session_instance.status != SessionStatus.WORKING:
            raise RuntimeError(f"Session '{session_name}' is not ready (Status: {session_instance.status.value}).")
        return session_instance

    async def create_session(self, session_name: str, start_immediately: bool = True) -> SessionData:
        async with self.operation_lock:
            if session_name in self.active_sessions:
                raise ValueError(f"Session '{session_name}' already exists.")
            new_session = WhatsAppSession(session_name)
            self.active_sessions[session_name] = new_session

        await session_store.save_session_status(session_name, new_session.status.value)

        if start_immediately:
            await new_session.start_connection()

        return new_session.get_summary()

    async def remove_session(self, session_name: str) -> None:
        async with self.operation_lock:
            session_instance = self.active_sessions.pop(session_name, None)

        if session_instance:
            await session_instance.logout_and_clear()


session_manager = SessionManager()
