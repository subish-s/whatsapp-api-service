from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import settings
from app.utils.logger import logger

database_client: AsyncIOMotorClient | None = None
active_database: AsyncIOMotorDatabase | None = None


async def connect_to_database() -> None:
    global database_client, active_database

    database_client = AsyncIOMotorClient(
        settings.mongodb_connection_string,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        retryWrites=True,
    )
    active_database = database_client[settings.mongodb_database_name]

    await database_client.admin.command("ping")
    logger.info("Connected to MongoDB successfully", database=settings.mongodb_database_name)

    await active_database.sessions.create_index("session_name", unique=True)


async def close_database_connection() -> None:
    global database_client
    if database_client:
        database_client.close()
        logger.info("Closed MongoDB connection")


def get_database() -> AsyncIOMotorDatabase:
    if active_database is None:
        raise RuntimeError("Database connection has not been initialized.")
    return active_database
