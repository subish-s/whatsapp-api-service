from datetime import datetime, timezone
import gridfs
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from app.database.connection import get_database


class MediaStore:
    """Stores all images, documents, and audio directly in MongoDB GridFS.
    No filesystem storage and no external S3 buckets required."""

    @staticmethod
    def get_bucket() -> AsyncIOMotorGridFSBucket:
        return AsyncIOMotorGridFSBucket(get_database(), bucket_name="whatsapp_media")

    async def save_file(
        self,
        session_name: str,
        message_identifier: str,
        file_bytes: bytes,
        mime_type: str,
        file_name: str,
    ) -> str:
        bucket = self.get_bucket()
        file_id = await bucket.upload_from_stream(
            file_name,
            file_bytes,
            metadata={
                "session_name": session_name,
                "message_identifier": message_identifier,
                "mime_type": mime_type,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return str(file_id)

    async def fetch_file(self, file_id_string: str) -> tuple[bytes, str, str] | None:
        bucket = self.get_bucket()
        try:
            stream = await bucket.open_download_stream(ObjectId(file_id_string))
            file_bytes = await stream.read()
            metadata = stream.metadata or {}
            mime_type = metadata.get("mime_type", "application/octet-stream")
            return file_bytes, mime_type, stream.filename
        except gridfs.NoFile:
            return None

    async def delete_file(self, file_id_string: str) -> None:
        bucket = self.get_bucket()
        await bucket.delete(ObjectId(file_id_string))


media_store = MediaStore()
