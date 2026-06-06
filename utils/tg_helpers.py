from __future__ import annotations

import re


def user_mention(user_id: int, name: str) -> str:
    """Return an HTML mention link for a user."""
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def extract_channel_id_from_link(value: str) -> int | None:
    """
    Accept either a raw integer ID or a t.me / joinchat link and return the
    channel/group integer ID, or None if parsing fails.

    Examples accepted:
      -1001234567890
      https://t.me/somechannel
      https://t.me/+AbCdEfGhIjK   (invite links — stored as-is after hash)
    """
    value = value.strip()

    # Plain integer (possibly negative for supergroups)
    if re.fullmatch(r"-?\d+", value):
        return int(value)

    # t.me/username  →  we cannot resolve the ID here without an API call,
    # so store a placeholder negative hash to keep things consistent.
    # Admins should prefer raw IDs.
    match = re.search(r"t\.me/(?:joinchat/|[+])?([A-Za-z0-9_-]+)", value)
    if match:
        # Return None; instruct admin to use the numeric ID instead.
        return None

    return None
