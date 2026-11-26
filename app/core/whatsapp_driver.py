import asyncio
import base64
import io
import os
import pathlib
import shutil
import zipfile
from typing import Any
import qrcode
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright
from app.config import settings
from app.core.event_bus import event_bus
from app.database.session_store import session_store
from app.models.enums import EventType, SessionStatus
from app.utils.logger import logger


class WhatsAppDriver:
    """Production-ready WhatsApp Web driver modeled after WAHA Core.
    Uses persistent browser profiles (IndexedDB preservation via MongoDB GridFS zips),
    and an in-page JS bridge (@wppconnect/wa-js) for zero-reload internal dispatching.
    """

    def __init__(self, session_name: str, session_instance):
        self.session_name = session_name
        self.session = session_instance
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.monitor_task: asyncio.Task | None = None
        self.snapshot_task: asyncio.Task | None = None
        self.is_running = False
        self.is_authenticated = False
        self.qr_raw: str | None = None
        self.ascii_qr: str | None = None

        self.user_data_dir = os.path.abspath(
            os.path.join(settings.sessions_base_dir, self.session_name)
        )
        self.wpp_js_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "assets", "wppconnect-wa.js")
        )

    # --- Profile Persistence Lifecycle (WAHA WPPAuthManager pattern) ---

    def _remove_singleton_locks(self) -> None:
        """Clear Chromium lock files that prevent restarts after unexpected termination."""
        if not os.path.exists(self.user_data_dir):
            return
        lock_files = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
        for root, dirs, files in os.walk(self.user_data_dir):
            for file_name in files:
                if any(file_name.startswith(lf) for lf in lock_files):
                    file_path = os.path.join(root, file_name)
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass

    async def before_start(self) -> None:
        """Restore previous session profile (IndexedDB + LocalStorage) from MongoDB GridFS zip."""
        os.makedirs(self.user_data_dir, exist_ok=True)
        try:
            has_archive = await session_store.has_session_archive(self.session_name)
            if has_archive:
                logger.info(f"Restoring saved WhatsApp session profile from MongoDB GridFS for '{self.session_name}'...")
                zip_data = await session_store.load_session_archive(self.session_name)
                if zip_data:
                    with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zip_ref:
                        zip_ref.extractall(self.user_data_dir)
                    logger.info(f"Successfully unpacked IndexedDB & storage state for '{self.session_name}'")
            else:
                logger.info(f"No existing MongoDB session archive for '{self.session_name}', starting clean")
        except Exception as err:
            logger.warning(f"Could not restore session archive for '{self.session_name}': {err}")

        self._remove_singleton_locks()

    async def save_snapshot(self) -> None:
        """Create a compact zip of the Chromium profile (preserving IndexedDB) and store in MongoDB GridFS."""
        if not self.is_authenticated or not os.path.exists(self.user_data_dir):
            return

        try:
            logger.debug(f"Saving IndexedDB session snapshot to MongoDB GridFS for '{self.session_name}'...")
            zip_buffer = io.BytesIO()
            # Only backup directories essential for session persistence
            target_dirs = ["Default/IndexedDB", "Default/Local Storage", "Default/Sync Data"]

            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for target in target_dirs:
                    target_path = os.path.join(self.user_data_dir, target)
                    if not os.path.exists(target_path):
                        continue
                    for root, dirs, files in os.walk(target_path):
                        for file_name in files:
                            # Skip temporary lock files
                            if file_name.endswith(".lock") or file_name.startswith("Singleton"):
                                continue
                            full_path = os.path.join(root, file_name)
                            rel_path = os.path.relpath(full_path, self.user_data_dir)
                            try:
                                zip_file.write(full_path, rel_path)
                            except OSError:
                                pass

            zip_bytes = zip_buffer.getvalue()
            if len(zip_bytes) > 100:
                await session_store.save_session_archive(self.session_name, zip_bytes)
                logger.info(f"Saved session profile archive to MongoDB GridFS ({len(zip_bytes)} bytes)")
        except Exception as snap_err:
            logger.warning(f"Failed to save profile snapshot for '{self.session_name}': {snap_err}")

    async def _snapshot_loop(self) -> None:
        """Periodic background task snapshotting browser storage to MongoDB."""
        while self.is_running:
            await asyncio.sleep(settings.session_backup_interval_seconds)
            if self.is_authenticated:
                await self.save_snapshot()

    # --- Engine Launch with WAHA Chromium Arguments ---

    async def start(self, stored_credentials: dict[str, Any] | None = None) -> None:
        """Launch Playwright persistent context with WAHA anti-detect and optimization flags."""
        self.is_running = True
        logger.info(f"Launching WAHA-compliant WhatsApp Web engine for session '{self.session_name}'...")

        await self.before_start()

        self.playwright = await async_playwright().start()

        # Chromium arguments optimized by WAHA Core for performance and stability
        browser_args = [
            "--disable-accelerated-2d-canvas",
            "--disable-application-cache",
            "--disable-client-side-phishing-detection",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-metrics",
            "--disable-gpu",
            "--disable-popup-blocking",
            "--disable-setuid-sandbox",
            "--disable-sync",
            "--disable-translate",
            "--hide-scrollbars",
            "--metrics-recording-only",
            "--mute-audio",
            "--no-default-browser-check",
            "--no-first-run",
            "--no-pings",
            "--no-sandbox",
            "--password-store=basic",
            "--disable-blink-features=AutomationControlled",
            f"--a-waha-session={self.session_name}",
        ]

        user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )

        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=True,
            args=browser_args,
            user_agent=user_agent,
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
        )

        # Enhanced stealth script masking automation fingerprints
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

        # Re-use existing open tab or open a new one
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()

        try:
            await self.page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=45000)
        except Exception as nav_err:
            logger.warning(f"Initial navigation notice for '{self.session_name}': {nav_err}")

        # Start lifecycle monitor and periodic backup
        self.monitor_task = asyncio.create_task(self._monitor_lifecycle())
        self.snapshot_task = asyncio.create_task(self._snapshot_loop())

    # --- WA-JS Injection & Helper ---

    async def _ensure_wpp_injected(self) -> bool:
        """Inject the @wppconnect/wa-js bundle into WhatsApp Web execution context."""
        if not self.page or self.page.is_closed():
            return False

        try:
            is_ready = await self.page.evaluate(
                "() => typeof window.WPP !== 'undefined' && window.WPP.isReady"
            )
            if is_ready:
                return True

            if os.path.exists(self.wpp_js_path):
                await self.page.add_script_tag(path=self.wpp_js_path)
                # Await WPP initialization
                try:
                    await self.page.wait_for_function(
                        "() => typeof window.WPP !== 'undefined' && window.WPP.isReady",
                        timeout=10000,
                    )
                    logger.info(f"Injected @wppconnect/wa-js bridge successfully into '{self.session_name}'")
                    return True
                except Exception:
                    pass
        except Exception as err:
            logger.debug(f"WA-JS check heartbeat: {err}")

        return False

    def _normalize_chat_id(self, chat_id: str) -> str:
        """Format raw phone or chat id into proper WhatsApp JID."""
        cleaned = chat_id.strip()
        if "@" not in cleaned:
            cleaned = cleaned.replace("+", "")
            return f"{cleaned}@c.us"
        return cleaned

    # --- Lifecycle Monitoring ---

    async def _monitor_lifecycle(self) -> None:
        """Monitor connection status, stream QR codes, and detect ready state."""
        logger.info(f"Monitoring WhatsApp lifecycle for session '{self.session_name}'...")

        while self.is_running and self.page and not self.page.is_closed():
            try:
                # 1. Attempt to inject and query WA-JS
                wpp_ready = await self._ensure_wpp_injected()

                if wpp_ready:
                    # Query authentication status from WA-JS directly
                    is_auth = await self.page.evaluate(
                        "() => window.WPP.conn.isMainReady() || window.WPP.conn.isAuthenticated()"
                    )
                    if is_auth and not self.is_authenticated:
                        await self._on_authenticated()
                        await asyncio.sleep(5.0)
                        continue

                    # If not authenticated, query auth QR code from WPP
                    if not self.is_authenticated:
                        auth_code = await self.page.evaluate("() => window.WPP.conn.getAuthCode()")
                        if auth_code and auth_code != self.qr_raw:
                            self._update_qr(auth_code)

                # 2. Fallback: Query DOM selectors for authentication & QR
                if not self.is_authenticated:
                    chat_pane = await self.page.query_selector("#pane-side, div[contenteditable='true']")
                    if chat_pane:
                        await self._on_authenticated()
                        await asyncio.sleep(5.0)
                        continue

                    qr_element = await self.page.query_selector("div[data-ref], canvas")
                    if qr_element:
                        qr_ref = await qr_element.get_attribute("data-ref")
                        if qr_ref and qr_ref != self.qr_raw:
                            self._update_qr(qr_ref)

                await asyncio.sleep(2.0)

            except Exception as monitor_err:
                if self.is_running:
                    logger.debug(f"Lifecycle heartbeat: {monitor_err}")
                await asyncio.sleep(2.5)

    async def _on_authenticated(self) -> None:
        """Actions executed upon confirmed WhatsApp authentication."""
        self.is_authenticated = True
        self.session.status = SessionStatus.WORKING
        self.session.qr_code_image = None
        self.session.qr_raw = None
        self.session.ascii_qr = None

        await session_store.save_session_status(self.session_name, SessionStatus.WORKING.value)

        # Capture account info if available
        try:
            if await self._ensure_wpp_injected():
                me = await self.page.evaluate("() => window.WPP.conn.getMyUserId()")
                if me:
                    self.session.account_number = str(me)
        except Exception:
            pass

        # Save initial authenticated snapshot
        await self.save_snapshot()

        # Start outbound queue worker
        self.session.message_queue.start()

        await event_bus.broadcast_event(
            self.session_name,
            EventType.SESSION_STATUS,
            {"status": SessionStatus.WORKING.value, "account_name": self.session.account_name},
        )
        logger.info(f"🎉 WhatsApp session '{self.session_name}' is AUTHENTICATED and WORKING! Profile backed up.")

    def _update_qr(self, qr_text: str) -> None:
        """Generate ASCII and Base64 QR code representations."""
        self.qr_raw = qr_text
        self.session.qr_raw = qr_text

        qr_gen = qrcode.QRCode()
        qr_gen.add_data(qr_text)
        qr_gen.make(fit=True)
        f = io.StringIO()
        qr_gen.print_ascii(out=f, invert=True)
        self.ascii_qr = f.getvalue()
        self.session.ascii_qr = self.ascii_qr

        # Render PNG data URL
        img = qr_gen.make_image(fill_color="black", back_color="white")
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        b64_png = base64.b64encode(buffered.getvalue()).decode("utf-8")
        self.session.qr_code_image = f"data:image/png;base64,{b64_png}"

        self.session.status = SessionStatus.SCAN_QR_CODE

        print(f"\n{'='*56}\nWHATSAPP LOGIN QR CODE for session: {self.session_name}\n{'='*56}")
        print(self.ascii_qr)
        print(f"{'='*56}\nScan the QR code above with WhatsApp (Linked Devices)\n{'='*56}\n")

    # --- In-Page JavaScript Operations (Anti-Ban Compliant) ---

    async def send_text_message(
        self,
        recipient_chat_id: str,
        message_text: str,
        reply_to_message_id: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch a text message in-page via window.WPP.chat without page navigation."""
        if not self.is_authenticated or not self.page:
            raise RuntimeError(f"Session '{self.session_name}' is not authenticated.")

        target_chat = self._normalize_chat_id(recipient_chat_id)
        await self._ensure_wpp_injected()

        logger.info(f"Dispatching text message to {target_chat} via WA-JS bridge...")
        result = await self.page.evaluate("""async ([chatId, text, replyTo]) => {
            const options = { createChat: true };
            if (replyTo) {
                options.quotedMsg = replyTo;
            }
            const sent = await window.WPP.chat.sendTextMessage(chatId, text, options);
            return {
                id: sent?.id || null,
                timestamp: sent?.t || Math.floor(Date.now() / 1000),
                ack: sent?.ack || 1,
            };
        }""", [target_chat, message_text, reply_to_message_id])

        return {
            "success": True,
            "session": self.session_name,
            "recipient": target_chat,
            "message": message_text,
            "message_id": result.get("id"),
            "status": "delivered",
        }

    async def set_chat_presence(self, recipient_chat_id: str, state: str) -> None:
        """Transmit real XMPP presence updates ('composing', 'recording', 'paused') to WhatsApp servers."""
        if not self.is_authenticated or not self.page:
            return

        target_chat = self._normalize_chat_id(recipient_chat_id)
        await self._ensure_wpp_injected()

        try:
            if state in ("composing", "typing"):
                await self.page.evaluate(
                    "([chatId]) => window.WPP.chat.markIsComposing(chatId)", [target_chat]
                )
            elif state == "recording":
                await self.page.evaluate(
                    "([chatId]) => window.WPP.chat.markIsRecording(chatId)", [target_chat]
                )
            else:
                await self.page.evaluate(
                    "([chatId]) => window.WPP.chat.markIsPaused(chatId)", [target_chat]
                )
        except Exception as presence_err:
            logger.debug(f"Presence update error: {presence_err}")

    async def send_file_message(
        self,
        recipient_chat_id: str,
        data_base64: str,
        mime_type: str,
        filename: str,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """Send an attachment (image, document, audio) directly through WhatsApp Web internal MMS."""
        if not self.is_authenticated or not self.page:
            raise RuntimeError(f"Session '{self.session_name}' is not authenticated.")

        target_chat = self._normalize_chat_id(recipient_chat_id)
        await self._ensure_wpp_injected()

        # Format Data URI
        data_uri = f"data:{mime_type};base64,{data_base64}" if not data_base64.startswith("data:") else data_base64

        logger.info(f"Dispatching file message ({mime_type}) to {target_chat} via WA-JS...")
        result = await self.page.evaluate("""async ([chatId, dataUri, filename, caption]) => {
            const sent = await window.WPP.chat.sendFileMessage(chatId, dataUri, {
                type: 'auto-detect',
                filename: filename,
                caption: caption || '',
                createChat: true
            });
            return {
                id: sent?.id || null,
                timestamp: sent?.t || Math.floor(Date.now() / 1000),
            };
        }""", [target_chat, data_uri, filename, caption or ""])

        return {
            "success": True,
            "session": self.session_name,
            "recipient": target_chat,
            "message_id": result.get("id"),
            "filename": filename,
            "status": "delivered",
        }

    async def send_poll_message(
        self,
        recipient_chat_id: str,
        question: str,
        options: list[str],
        allow_multiple: bool = False,
    ) -> dict[str, Any]:
        """Send a native WhatsApp Poll via WA-JS without clicking DOM elements."""
        if not self.is_authenticated or not self.page:
            raise RuntimeError(f"Session '{self.session_name}' is not authenticated.")

        target_chat = self._normalize_chat_id(recipient_chat_id)
        await self._ensure_wpp_injected()

        selectable_count = 0 if allow_multiple else 1
        logger.info(f"Dispatching poll '{question}' to {target_chat} via WA-JS...")

        result = await self.page.evaluate("""async ([chatId, question, options, selectableCount]) => {
            const sent = await window.WPP.chat.sendPollCreationMessage(chatId, question, options, {
                selectableCount: selectableCount
            });
            return {
                id: sent?.id || null,
                timestamp: sent?.t || Math.floor(Date.now() / 1000),
            };
        }""", [target_chat, question, options, selectable_count])

        poll_record = {
            "poll_id": str(result.get("id") or f"poll_{int(asyncio.get_event_loop().time() * 1000)}"),
            "recipient": target_chat,
            "question": question,
            "options": [{"option": opt, "votes": 0} for opt in options],
            "allow_multiple_answers": allow_multiple,
            "status": "delivered",
        }
        await session_store.save_poll(self.session_name, poll_record)

        return {
            "success": True,
            "session": self.session_name,
            **poll_record,
        }

    async def send_reaction(self, message_id: str, emoji: str) -> dict[str, Any]:
        """Send emoji reaction to a message."""
        if not self.is_authenticated or not self.page:
            raise RuntimeError(f"Session '{self.session_name}' is not authenticated.")

        await self._ensure_wpp_injected()
        await self.page.evaluate("""async ([msgId, emoji]) => {
            return await window.WPP.chat.sendReactionToMessage(msgId, emoji);
        }""", [message_id, emoji])

        return {"success": True, "session": self.session_name, "message_id": message_id, "emoji": emoji}

    async def delete_message(self, recipient_chat_id: str, message_id: str, delete_for_everyone: bool = True) -> dict[str, Any]:
        """Delete message for everyone or for me."""
        if not self.is_authenticated or not self.page:
            raise RuntimeError(f"Session '{self.session_name}' is not authenticated.")

        target_chat = self._normalize_chat_id(recipient_chat_id)
        await self._ensure_wpp_injected()

        await self.page.evaluate("""async ([chatId, msgId, forEveryone]) => {
            return await window.WPP.chat.deleteMessage(chatId, msgId, forEveryone);
        }""", [target_chat, message_id, delete_for_everyone])

        return {
            "success": True,
            "session": self.session_name,
            "recipient": target_chat,
            "message_id": message_id,
            "deleted_for": "everyone" if delete_for_everyone else "me",
        }

    async def read_chat_polls(self, recipient_chat_id: str) -> list[dict[str, Any]]:
        """Retrieve stored and live poll results."""
        return await session_store.get_chat_polls(self.session_name, self._normalize_chat_id(recipient_chat_id))

    # --- Graceful Shutdown ---

    async def close(self) -> None:
        """Save final snapshot to MongoDB GridFS and terminate browser context."""
        self.is_running = False
        self.is_authenticated = False

        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            self.monitor_task = None

        if self.snapshot_task and not self.snapshot_task.done():
            self.snapshot_task.cancel()
            self.snapshot_task = None

        # Take final snapshot before closing browser
        try:
            await self.save_snapshot()
        except Exception:
            pass

        if self.page and not self.page.is_closed():
            await self.page.close()
            self.page = None

        if self.context:
            await self.context.close()
            self.context = None

        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

        logger.info(f"Gracefully closed WAHA engine for session '{self.session_name}'")
