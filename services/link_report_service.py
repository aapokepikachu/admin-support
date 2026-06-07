from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId

from db import get_db

# ── Settings ──────────────────────────────────────────────────────────────────

DEFAULT_REPORT_LIMIT = 2


async def get_report_limit() -> int:
    doc = await get_db().settings.find_one({"key": "report_limit"})
    return int(doc["value"]) if doc else DEFAULT_REPORT_LIMIT


async def set_report_limit(n: int) -> None:
    await get_db().settings.update_one(
        {"key": "report_limit"},
        {"$set": {"value": n}},
        upsert=True,
    )


# ── Per-user submission tracking ──────────────────────────────────────────────

async def count_user_reports(user_id: int) -> int:
    """Count active (non-resolved) reports by this user."""
    return await get_db().link_reports.count_documents(
        {"user_id": user_id, "status": "pending"}
    )


async def has_reported_link(user_id: int, link: str) -> bool:
    """True if user already has a pending report for this exact link."""
    return bool(await get_db().link_reports.find_one(
        {"user_id": user_id, "link": link, "status": "pending"}
    ))


async def create_link_report(user_id: int, link: str, admin_msg_id: int | None = None) -> str:
    """Insert a new link report, return its string ID."""
    result = await get_db().link_reports.insert_one({
        "user_id": user_id,
        "link": link,
        "status": "pending",
        "admin_msg_id": admin_msg_id,
        "created_at": datetime.utcnow(),
    })
    return str(result.inserted_id)


async def set_link_report_admin_msg(report_id: str, admin_msg_id: int) -> None:
    await get_db().link_reports.update_one(
        {"_id": ObjectId(report_id)},
        {"$set": {"admin_msg_id": admin_msg_id}},
    )


async def resolve_link_report(report_id: str) -> str | None:
    """Resolve and DELETE the report (free storage). Return the link."""
    doc = await get_db().link_reports.find_one_and_delete({"_id": ObjectId(report_id)})
    return doc["link"] if doc else None


async def get_link_report(report_id: str) -> dict[str, Any] | None:
    try:
        return await get_db().link_reports.find_one({"_id": ObjectId(report_id)})
    except Exception:
        return None


async def get_link_report_by_admin_msg(admin_msg_id: int) -> dict[str, Any] | None:
    return await get_db().link_reports.find_one({"admin_msg_id": admin_msg_id})


async def get_user_reports(user_id: int) -> list[dict[str, Any]]:
    """Return all pending reports for a user."""
    return await get_db().link_reports.find(
        {"user_id": user_id, "status": "pending"},
        {"_id": 1, "link": 1, "created_at": 1},
    ).to_list(None)


async def get_all_pending_reports() -> list[dict[str, Any]]:
    return await get_db().link_reports.find(
        {"status": "pending"},
        {"_id": 1, "user_id": 1, "link": 1, "created_at": 1},
    ).to_list(None)
