import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import settings
from db import init_db, close_db
from middlewares.rate_limit import RateLimitMiddleware
from middlewares.captcha import CaptchaMiddleware
from handlers import user, admin, report, captcha, group_guard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def health(request: web.Request) -> web.Response:
    """
    Health-check endpoint — required for Render free web service to stay alive.
    Register this URL with UptimeRobot (every 5 min) to prevent the 15-min sleep.
    """
    return web.json_response({"status": "ok"})


async def on_startup(bot: Bot) -> None:
    await init_db()
    await bot.set_webhook(
        url=settings.WEBHOOK_URL,
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "my_chat_member"],
    )
    logger.info("Webhook set: %s", settings.WEBHOOK_URL)


async def on_shutdown(bot: Bot) -> None:
    await bot.delete_webhook()
    await close_db()
    logger.info("Webhook removed, DB closed.")


def build_app() -> web.Application:
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Startup / shutdown hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Middlewares
    dp.message.middleware(RateLimitMiddleware())
    dp.message.middleware(CaptchaMiddleware())

    # Routers (order matters — group_guard first, then captcha, then domain handlers)
    dp.include_router(group_guard.router)
    dp.include_router(captcha.router)
    dp.include_router(user.router)
    dp.include_router(admin.router)
    dp.include_router(report.router)

    app = web.Application()

    # Health-check route (must be registered before webhook handler)
    app.router.add_get("/health", health)

    # Telegram webhook route
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=settings.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    return app


if __name__ == "__main__":
    web.run_app(build_app(), port=settings.PORT)
