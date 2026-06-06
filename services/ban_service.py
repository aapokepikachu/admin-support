from __future__ import annotations

from datetime import datetime
from typing import Any

from db import get_db


async def ban_user(user_id: int, banned_by: int) -> None:
    db = get_db()
    await db.bans.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "banned_by": banned_by,
                "banned_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )
    await db.users.update_one({"user_id": user_id}, {"$set": {"status": "banned"}})


async def unban_user(user_id: int) -> bool:
    db = get_db()
    result = await db.bans.delete_one({"user_id": user_id})
    if result.deleted_count:
        await db.users.update_one(
            {"user_id": user_id}, {"$set": {"status": "active"}}
        )
        return True
    return False


async def is_banned(user_id: int) -> bool:
    return bool(await get_db().bans.find_one({"user_id": user_id}))


async def ban_list() -> list[dict[str, Any]]:
    return await get_db().bans.find({}, {"_id": 0}).to_list(None)
