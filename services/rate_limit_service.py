from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import settings
from db import get_db


def _now() -> datetime:
    """Naive UTC datetime — consistent with what MongoDB returns."""
    return datetime.utcnow()


def _as_naive(dt: datetime) -> datetime:
    """Strip timezone info from a datetime so comparisons with MongoDB docs work."""
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


async def check_rate_limit(user_id: int) -> tuple[bool, int]:
    """
    Returns (allowed, retry_after_seconds).
    allowed=True  → message may proceed.
    allowed=False → user is throttled; retry_after > 0.
    """
    db = get_db()
    now = _now()
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
    throttled_until = doc.get("throttled_until")
    if throttled_until:
        throttled_until = _as_naive(throttled_until)
        if throttled_until > now:
            remaining = int((throttled_until - now).total_seconds())
            return False, remaining

    window_start = _as_naive(doc["window_start"])
    elapsed = (now - window_start).total_seconds()

    if elapsed > settings.RATE_LIMIT_WINDOW:
        # New window — reset counter
        await db.rate_limit.update_one(
            {"user_id": user_id},
            {"$set": {"count": 1, "window_start": now, "throttled_until": None}},
        )
        return True, 0

    count: int = doc["count"] + 1
    if count > settings.RATE_LIMIT_MESSAGES:
        throttled_until_new = now + timedelta(seconds=settings.RATE_LIMIT_COOLDOWN)
        await db.rate_limit.update_one(
            {"user_id": user_id},
            {"$set": {"count": count, "throttled_until": throttled_until_new}},
        )
        return False, settings.RATE_LIMIT_COOLDOWN

    await db.rate_limit.update_one({"user_id": user_id}, {"$set": {"count": count}})
    return True, 0
