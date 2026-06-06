from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from db import get_db

_CHALLENGES: list[tuple[str, str, list[str]]] = [
    ("What is 3 + 4?", "7", ["5", "6", "7", "8", "9"]),
    ("What color is the sky on a clear day?", "Blue", ["Red", "Blue", "Green", "Yellow", "Pink"]),
    ("How many days are in a week?", "7", ["5", "6", "7", "8", "9"]),
    ("What comes after Monday?", "Tuesday", ["Sunday", "Tuesday", "Wednesday", "Friday", "Saturday"]),
    ("What is 10 - 3?", "7", ["4", "5", "6", "7", "8"]),
    ("Which animal says 'meow'?", "Cat", ["Dog", "Cat", "Bird", "Fish", "Cow"]),
    ("How many legs does a spider have?", "8", ["4", "6", "8", "10", "12"]),
    ("What is 2 × 5?", "10", ["6", "8", "10", "12", "14"]),
]


async def captcha_enabled() -> bool:
    doc = await get_db().settings.find_one({"key": "captcha"})
    return bool(doc and doc.get("enabled"))


async def set_captcha(enabled: bool) -> None:
    await get_db().settings.update_one(
        {"key": "captcha"},
        {"$set": {"enabled": enabled}},
        upsert=True,
    )


async def get_pending_captcha(user_id: int) -> dict[str, Any] | None:
    return await get_db().captcha_sessions.find_one({"user_id": user_id})


async def create_captcha_session(user_id: int) -> dict[str, Any]:
    question, answer, pool = random.choice(_CHALLENGES)
    # Build 5 unique options always containing the correct answer
    wrong = [o for o in pool if o != answer]
    options = [answer] + random.sample(wrong, min(4, len(wrong)))
    random.shuffle(options)
    doc = {
        "user_id": user_id,
        "question": question,
        "answer": answer,
        "options": options,
        "created_at": datetime.now(timezone.utc),
    }
    await get_db().captcha_sessions.replace_one({"user_id": user_id}, doc, upsert=True)
    return doc


async def resolve_captcha(user_id: int) -> None:
    await get_db().captcha_sessions.delete_one({"user_id": user_id})


async def has_passed_captcha(user_id: int) -> bool:
    doc = await get_db().users.find_one({"user_id": user_id}, {"captcha_passed": 1})
    return bool(doc and doc.get("captcha_passed"))


async def mark_captcha_passed(user_id: int) -> None:
    await get_db().users.update_one(
        {"user_id": user_id}, {"$set": {"captcha_passed": True}}
    )
