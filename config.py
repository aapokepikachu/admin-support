import hashlib
import os
from dataclasses import dataclass, field


def _require(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


@dataclass(frozen=True)
class Settings:
    BOT_TOKEN: str = field(default_factory=lambda: _require("BOT_TOKEN"))
    ADMIN_GROUP_ID: int = field(
        default_factory=lambda: int(_require("ADMIN_GROUP_ID"))
    )
    MONGO_URI: str = field(default_factory=lambda: _require("MONGO_URI"))
    WEBHOOK_HOST: str = field(default_factory=lambda: _require("WEBHOOK_HOST").rstrip("/"))
    DB_NAME: str = field(default_factory=lambda: os.getenv("DB_NAME", "supportbot"))
    PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))

    RATE_LIMIT_MESSAGES: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_MESSAGES", "5"))
    )
    RATE_LIMIT_WINDOW: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_WINDOW", "60"))
    )
    RATE_LIMIT_COOLDOWN: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_COOLDOWN", "300"))
    )

    @property
    def WEBHOOK_PATH(self) -> str:
        # Hash the token so the path contains no special characters (no colons)
        # and is still secret and unique per bot
        token_hash = hashlib.sha256(self.BOT_TOKEN.encode()).hexdigest()[:32]
        return f"/webhook/{token_hash}"

    @property
    def WEBHOOK_URL(self) -> str:
        return f"{self.WEBHOOK_HOST}{self.WEBHOOK_PATH}"


settings = Settings()
