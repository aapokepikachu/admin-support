from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import settings
from db import get_db


async def check_rate_limit(user_id: int) -> tuple[bool, int]:
    """
    Returns (allowed, retry_after_seconds).
    allowed=True  → message may proceed.
    allowed=False → user is throttled; retry_after > 0.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    doc = await db.rate_limit.find_one({"user_id": user_id})

    if doc is None:
        await db.rate_limit.insert_one(
            {
                "user_id": user_id,
                "count": 1,
                "window_start": now,
                "throttled_until": None,
            }
        )
        return True, 0

    # Still in cooldown?
    if doc.get("throttled_until") and doc["throttled_until"] > now:
        remaining = int((doc["throttled_until"] - now).total_seconds())
        return False, remaining

    elapsed = (now - doc["window_start"]).total_seconds()

    if elapsed > settings.RATE_LIMIT_WINDOW:
        # New window — reset counter
        await db.rate_limit.update_one(
            {"user_id": user_id},
            {"$set": {"count": 1, "window_start": now, "throttled_until": None}},
        )
        return True, 0

    count: int = doc["count"] + 1
    if count > settings.RATE_LIMIT_MESSAGES:
        throttled_until = now + timedelta(seconds=settings.RATE_LIMIT_COOLDOWN)
        await db.rate_limit.update_one(
            {"user_id": user_id},
            {"$set": {"count": count, "throttled_until": throttled_until}},
        )
        return False, settings.RATE_LIMIT_COOLDOWN

    await db.rate_limit.update_one({"user_id": user_id}, {"$set": {"count": count}})
    return True, 0
