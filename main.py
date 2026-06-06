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
    """Handles GET and HEAD on / and /health. UptimeRobot pings HEAD /."""
    return web.Response(text="ok", status=200)


async def setup_webhook(request: web.Request) -> web.Response:
    """
    Manual webhook reset endpoint — call this if the bot stops responding.
    GET https://your-app.onrender.com/setup
    """
    bot: Bot = request.app["bot"]
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(
            url=settings.WEBHOOK_URL,
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query", "my_chat_member"],
        )
        info = await bot.get_webhook_info()
        return web.json_response({
            "status": "ok",
            "webhook_url": info.url,
            "pending": info.pending_update_count,
            "last_error": info.last_error_message,
        })
    except Exception as exc:
        logger.error("Webhook reset failed: %s", exc)
        return web.json_response({"status": "error", "detail": str(exc)}, status=500)


async def on_startup(bot: Bot, app: web.Application) -> None:
    await init_db()

    # Always delete first to clear any stale webhook state from Telegram
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Old webhook deleted.")

    await bot.set_webhook(
        url=settings.WEBHOOK_URL,
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "my_chat_member"],
    )

    info = await bot.get_webhook_info()
    logger.info("Webhook set: url=%r pending=%d last_error=%r",
                info.url, info.pending_update_count, info.last_error_message)

    # Store bot on app for the /setup endpoint
    app["bot"] = bot


async def on_shutdown(bot: Bot) -> None:
    await bot.delete_webhook()
    await close_db()
    logger.info("Shutdown complete.")


def build_app() -> web.Application:
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Pass app to startup so we can store bot reference
    app = web.Application()

    async def _startup(bot: Bot = bot) -> None:
        await on_startup(bot, app)

    dp.startup.register(_startup)
    dp.shutdown.register(on_shutdown)

    dp.message.middleware(RateLimitMiddleware())
    dp.message.middleware(CaptchaMiddleware())

    dp.include_router(group_guard.router)
    dp.include_router(captcha.router)
    dp.include_router(user.router)
    dp.include_router(admin.router)
    dp.include_router(report.router)

    # Health routes — GET also auto-serves HEAD in aiohttp
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    # Manual webhook reset (useful if bot stops responding)
    app.router.add_get("/setup", setup_webhook)

    # Telegram webhook
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=settings.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    return app


if __name__ == "__main__":
    web.run_app(build_app(), port=settings.PORT)
