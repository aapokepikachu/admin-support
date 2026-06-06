from __future__ import annotations

import re


def parse_channel_id(value: str) -> int | None:
    """
    Accept a raw integer ID (e.g. -1001234567890) and return it as int.
    Returns None for t.me links — admins must use the numeric ID directly.
    """
    value = value.strip()
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return None
