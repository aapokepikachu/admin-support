from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from db import get_db


# ── Template CRUD ─────────────────────────────────────────────────────────────

async def create_template(
    title: str,
    prompt_msg: str,
    invalid_msg: str,
    done_msg: str,
) -> dict[str, Any]:
    slug = secrets.token_urlsafe(8)
    doc = {
        "title": title,
        "slug": slug,
        "prompt_msg": prompt_msg,
        "invalid_msg": invalid_msg,
        "done_msg": done_msg,
        "created_at": datetime.now(timezone.utc),
    }
    result = await get_db().report_templates.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def get_template(template_id: str) -> dict[str, Any] | None:
    try:
        return await get_db().report_templates.find_one({"_id": ObjectId(template_id)})
    except Exception:
        return None


async def get_template_by_slug(slug: str) -> dict[str, Any] | None:
    return await get_db().report_templates.find_one({"slug": slug})


async def list_templates(page: int = 0, page_size: int = 5) -> list[dict[str, Any]]:
    return (
        await get_db()
        .report_templates.find({})
        .skip(page * page_size)
        .limit(page_size)
        .to_list(None)
    )


async def count_templates() -> int:
    return await get_db().report_templates.count_documents({})


async def update_template(template_id: str, fields: dict[str, Any]) -> bool:
    try:
        result = await get_db().report_templates.update_one(
            {"_id": ObjectId(template_id)}, {"$set": fields}
        )
        return result.modified_count > 0
    except Exception:
        return False


async def delete_template(template_id: str) -> bool:
    try:
        result = await get_db().report_templates.delete_one(
            {"_id": ObjectId(template_id)}
        )
        return result.deleted_count > 0
    except Exception:
        return False


# ── Report state ──────────────────────────────────────────────────────────────

async def get_report_state(user_id: int, template_id: str) -> dict[str, Any] | None:
    try:
        return await get_db().report_states.find_one(
            {"user_id": user_id, "template_id": ObjectId(template_id)}
        )
    except Exception:
        return None


async def create_report_state(user_id: int, template_id: str) -> None:
    from bson import ObjectId as OId
    await get_db().report_states.update_one(
        {"user_id": user_id, "template_id": OId(template_id)},
        {
            "$set": {
                "status": "pending",
                "submitted_at": datetime.now(timezone.utc),
                "admin_msg_id": None,
            }
        },
        upsert=True,
    )


async def resolve_report_state(user_id: int, template_id: str, status: str) -> None:
    from bson import ObjectId as OId
    await get_db().report_states.update_one(
        {"user_id": user_id, "template_id": OId(template_id)},
        {"$set": {"status": status, "resolved_at": datetime.now(timezone.utc)}},
    )


async def save_report_admin_msg(
    user_id: int, template_id: str, admin_msg_id: int
) -> None:
    from bson import ObjectId as OId
    await get_db().report_states.update_one(
        {"user_id": user_id, "template_id": OId(template_id)},
        {"$set": {"admin_msg_id": admin_msg_id}},
    )


async def get_report_by_admin_msg(admin_msg_id: int) -> dict[str, Any] | None:
    return await get_db().report_states.find_one({"admin_msg_id": admin_msg_id})
