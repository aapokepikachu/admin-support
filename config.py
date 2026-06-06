import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    BOT_TOKEN: str = field(default_factory=lambda: _require("BOT_TOKEN"))
    ADMIN_GROUP_ID: int = field(
        default_factory=lambda: int(_require("ADMIN_GROUP_ID"))
    )
    MONGO_URI: str = field(default_factory=lambda: _require("MONGO_URI"))
    DB_NAME: str = field(default_factory=lambda: os.getenv("DB_NAME", "supportbot"))

    # Rate limiting
    RATE_LIMIT_MESSAGES: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_MESSAGES", "5"))
    )
    RATE_LIMIT_WINDOW: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_WINDOW", "60"))
    )
    RATE_LIMIT_COOLDOWN: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_COOLDOWN", "300"))
    )


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


settings = Settings()
