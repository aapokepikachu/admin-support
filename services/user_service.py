from __future__ import annotations

from datetime import datetime
from typing import Any

from aiogram.types import User as TgUser

from db import get_db


async def upsert_user(tg_user: TgUser) -> None:
    db = get_db()
    await db.users.update_one(
        {"user_id": tg_user.id},
        {
            "$set": {
                "username": tg_user.username,
                "first_name": tg_user.first_name,
                "last_name": tg_user.last_name,
                "last_seen": datetime.utcnow(),
                "is_deleted": False,
            },
            "$setOnInsert": {
                "user_id": tg_user.id,
                "joined_at": datetime.utcnow(),
                "status": "active",
            },
        },
        upsert=True,
    )


async def get_user(user_id: int) -> dict[str, Any] | None:
    return await get_db().users.find_one({"user_id": user_id})


async def mark_deleted(user_id: int) -> None:
    await get_db().users.update_one(
        {"user_id": user_id},
        {"$set": {"is_deleted": True, "status": "deleted"}},
    )


async def all_users() -> list[dict[str, Any]]:
    return await get_db().users.find({}, {"_id": 0}).to_list(None)


async def all_active_user_ids() -> list[int]:
    docs = await get_db().users.find(
        {"is_deleted": {"$ne": True}}, {"user_id": 1}
    ).to_list(None)
    return [d["user_id"] for d in docs]
