from __future__ import annotations

from typing import Any

from db import get_db


async def add_channel(channel_id: int, title: str | None = None) -> None:
    await get_db().allowed_channels.update_one(
        {"channel_id": channel_id},
        {"$set": {"channel_id": channel_id, "title": title or str(channel_id)}},
        upsert=True,
    )


async def remove_channel(channel_id: int) -> bool:
    result = await get_db().allowed_channels.delete_one({"channel_id": channel_id})
    return result.deleted_count > 0


async def list_channels() -> list[dict[str, Any]]:
    return await get_db().allowed_channels.find({}, {"_id": 0}).to_list(None)


async def is_allowed_channel(channel_id: int) -> bool:
    return bool(await get_db().allowed_channels.find_one({"channel_id": channel_id}))
