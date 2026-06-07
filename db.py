import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config import settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def init_db() -> None:
    global _client, _db
    _client = AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
    _db = _client[settings.DB_NAME]
    await _ensure_indexes()
    logger.info("MongoDB connected: %s", settings.DB_NAME)


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None


async def _ensure_indexes() -> None:
    db = get_db()
    await db.users.create_index("user_id", unique=True)
    await db.users.create_index("username")
    await db.bans.create_index("user_id", unique=True)
    await db.message_map.create_index("admin_msg_id")
    await db.message_map.create_index("user_id")
    await db.report_templates.create_index("slug", unique=True)
    await db.report_states.create_index([("user_id", 1), ("template_id", 1)])
    await db.allowed_channels.create_index("channel_id", unique=True)
    await db.rate_limit.create_index("user_id", unique=True)
    await db.captcha_sessions.create_index("user_id", unique=True)
    await db.settings.create_index("key", unique=True)
    await db.burst_track.create_index("user_id", unique=True)
    await db.link_reports.create_index("user_id")
    await db.link_reports.create_index("admin_msg_id")


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _db
