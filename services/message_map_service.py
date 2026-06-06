from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db import get_db


async def save_mapping(
    user_id: int,
    user_msg_id: int,
    admin_msg_id: int,
) -> None:
    """Map the forwarded admin-group message ID back to the originating user."""
    await get_db().message_map.insert_one(
        {
            "user_id": user_id,
            "user_msg_id": user_msg_id,
            "admin_msg_id": admin_msg_id,
            "created_at": datetime.now(timezone.utc),
        }
    )


async def get_mapping_by_admin_msg(admin_msg_id: int) -> dict[str, Any] | None:
    """Return the mapping whose admin_msg_id matches (direct or reply target)."""
    return await get_db().message_map.find_one({"admin_msg_id": admin_msg_id})
