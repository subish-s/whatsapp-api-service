from datetime import datetime, timezone
from typing import Any
from app.database.connection import get_database


class SessionStore:
    """Stores session configuration, statuses, and auth data directly in MongoDB."""

    @staticmethod
    def get_collection():
        return get_database().sessions

    async def save_session_configuration(self, session_name: str, configuration_data: dict[str, Any]) -> None:
        current_time = datetime.now(timezone.utc)
        collection = self.get_collection()
        await collection.update_one(
            {"session_name": session_name},
            {
                "$set": {
                    "configuration": configuration_data,
                    "updated_at": current_time,
                },
                "$setOnInsert": {
                    "session_name": session_name,
                    "created_at": current_time,
                },
            },
            upsert=True,
        )

    async def save_session_status(self, session_name: str, current_status: str) -> None:
        current_time = datetime.now(timezone.utc)
        collection = self.get_collection()
        await collection.update_one(
            {"session_name": session_name},
            {
                "$set": {
                    "status": current_status,
                    "updated_at": current_time,
                }
            },
            upsert=True,
        )

    async def save_authentication_credentials(self, session_name: str, credentials_data: dict[str, Any]) -> None:
        current_time = datetime.now(timezone.utc)
        collection = self.get_collection()
        await collection.update_one(
            {"session_name": session_name},
            {
                "$set": {
                    "auth_credentials": credentials_data,
                    "updated_at": current_time,
                }
            },
            upsert=True,
        )

    async def get_authentication_credentials(self, session_name: str) -> dict[str, Any] | None:
        collection = self.get_collection()
        document = await collection.find_one({"session_name": session_name})
        if document:
            return document.get("auth_credentials")
        return None

    async def get_session_by_name(self, session_name: str) -> dict[str, Any] | None:
        collection = self.get_collection()
        return await collection.find_one({"session_name": session_name}, {"auth_credentials": 0})

    async def get_all_sessions(self) -> list[dict[str, Any]]:
        collection = self.get_collection()
        cursor = collection.find({}, {"auth_credentials": 0})
        return await cursor.to_list(length=500)

    async def delete_session_record(self, session_name: str) -> None:
        collection = self.get_collection()
        await collection.delete_one({"session_name": session_name})

    async def save_poll(self, session_name: str, poll_data: dict[str, Any]) -> None:
        """Persist a sent poll record into MongoDB."""
        polls_collection = get_database().polls
        poll_data["session_name"] = session_name
        poll_data["created_at"] = datetime.now(timezone.utc)
        await polls_collection.insert_one(poll_data)

    async def get_chat_polls(self, session_name: str, recipient_chat_id: str) -> list[dict[str, Any]]:
        """Retrieve stored polls for a specific chat from MongoDB."""
        polls_collection = get_database().polls
        cursor = polls_collection.find(
            {"session_name": session_name, "recipient": recipient_chat_id},
            {"_id": 0},
        ).sort("created_at", -1)
        return await cursor.to_list(length=100)

    # --- WAHA-Style GridFS Session Profile (.zip) Persistence ---

    @staticmethod
    def get_auth_bucket():
        from motor.motor_asyncio import AsyncIOMotorGridFSBucket
        return AsyncIOMotorGridFSBucket(get_database(), bucket_name="session_auth")

    async def has_session_archive(self, session_name: str) -> bool:
        """Check if an archived session profile exists in MongoDB GridFS."""
        bucket = self.get_auth_bucket()
        filename = f"{session_name}.zip"
        cursor = bucket.find({"filename": filename})
        files = await cursor.to_list(length=1)
        return len(files) > 0

    async def save_session_archive(self, session_name: str, zip_bytes: bytes) -> None:
        """Save a zipped browser profile (IndexedDB + LocalStorage) to MongoDB GridFS."""
        bucket = self.get_auth_bucket()
        filename = f"{session_name}.zip"
        await bucket.upload_from_stream(
            filename,
            zip_bytes,
            metadata={"session_name": session_name, "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        # Keep only the latest archive, delete older revisions
        cursor = bucket.find({"filename": filename})
        files = await cursor.to_list(length=100)
        if len(files) > 1:
            files.sort(key=lambda f: f.get("uploadDate", datetime.min))
            for old_file in files[:-1]:
                await bucket.delete(old_file["_id"])

    async def load_session_archive(self, session_name: str) -> bytes | None:
        """Retrieve the latest zipped browser profile from MongoDB GridFS."""
        bucket = self.get_auth_bucket()
        filename = f"{session_name}.zip"
        cursor = bucket.find({"filename": filename}).sort("uploadDate", -1)
        files = await cursor.to_list(length=1)
        if not files:
            return None
        stream = await bucket.open_download_stream(files[0]["_id"])
        return await stream.read()

    async def delete_session_archive(self, session_name: str) -> None:
        """Delete all archived session profile snapshots for this session."""
        bucket = self.get_auth_bucket()
        filename = f"{session_name}.zip"
        cursor = bucket.find({"filename": filename})
        files = await cursor.to_list(length=100)
        for f in files:
            await bucket.delete(f["_id"])


session_store = SessionStore()
