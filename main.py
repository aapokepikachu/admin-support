import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import settings
from db import init_db
from middlewares.rate_limit import RateLimitMiddleware
from middlewares.captcha import CaptchaMiddleware
from handlers import user, admin, report, captcha, group_guard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    await init_db()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Middlewares (order matters)
    dp.message.middleware(RateLimitMiddleware())
    dp.message.middleware(CaptchaMiddleware())

    # Routers
    dp.include_router(group_guard.router)
    dp.include_router(captcha.router)
    dp.include_router(user.router)
    dp.include_router(admin.router)
    dp.include_router(report.router)

    logger.info("Bot starting (long polling)…")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
