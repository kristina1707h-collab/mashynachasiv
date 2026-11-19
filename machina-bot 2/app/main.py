import asyncio
import hmac
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from . import texts as T
from .common import DbMiddleware, safe_send
from .config import KYIV, settings
from .course import package_by_amount, PACKAGES
from .db import SessionLocal, Setting, Staff, Student, init_db
from .handlers import admin, guest, student
from .scheduler import tick, weekly_report
from .services import deep_link, issue_student, manager_ids, seats_limit, seats_taken, esc

log = logging.getLogger("machina")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(DbMiddleware())
    dp.include_router(admin)          # команди персоналу + реплаї куратора
    dp.include_router(student)        # оплачені
    dp.include_router(guest)          # неоплачені
    return dp


async def bootstrap() -> None:
    await init_db()
    async with SessionLocal() as s:
        for tid in settings.ADMIN_IDS:
            if not await s.get(Staff, tid):
                s.add(Staff(tg_id=tid, name="Адмін", role="manager", is_admin=True))
        await s.commit()
        rows = (await s.execute(select(Setting).where(Setting.key.like("text:%")))).scalars().all()
        T.set_overrides({r.key[5:]: r.value for r in rows})


async def payment_webhook(request: web.Request) -> web.Response:
    """POST /webhook/payment  (заголовок X-Webhook-Secret). Тіло JSON:
    {"order_id": "...", "package": "self|curator|valeria" (або "amount": 1890), "name": "...", "instagram": "@...", "source": "..."}
    Створює код і сповіщає менеджерку — ВОНА надсилає посилання людині після перевірки оплати."""
    secret = request.headers.get("X-Webhook-Secret", "")
    if not settings.PAYMENT_WEBHOOK_SECRET or not hmac.compare_digest(secret, settings.PAYMENT_WEBHOOK_SECRET):
        return web.json_response({"error": "forbidden"}, status=403)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    pkg = data.get("package")
    if pkg not in PACKAGES and data.get("amount"):
        pkg = package_by_amount(int(float(data["amount"])))
    if pkg not in PACKAGES:
        return web.json_response({"error": "unknown package"}, status=400)
    order_id = str(data.get("order_id") or "") or None
    bot: Bot = request.app["bot"]
    async with SessionLocal() as s:
        if order_id:
            ex = (await s.execute(select(Student).where(Student.order_id == order_id))).scalar_one_or_none()
            if ex:
                return web.json_response({"code": ex.code, "link": deep_link(ex.code), "duplicate": True})
        st = await issue_student(s, pkg, name=str(data.get("name") or ""), instagram=str(data.get("instagram") or ""),
                                 amount=int(float(data["amount"])) if data.get("amount") else None,
                                 source=str(data.get("source") or "pay"), order_id=order_id)
        await s.commit()
        link = deep_link(st.code)
        for m in await manager_ids(s):
            await safe_send(bot, m, f"💰 Нова оплата · {PACKAGES[pkg]['title']} · {st.amount} грн · {esc(st.display)}\n"
                                    f"Перевір надходження й надішли в Direct:\n<code>You DID it! 🎉 Оплату отримали. Ось твій квиток у «Машину часів» → {link}</code>")
        if pkg == "valeria" and await seats_taken(s) >= await seats_limit(s):
            for m in await manager_ids(s):
                await safe_send(bot, m, "⚠️ Місця «З Валерією» закінчились — вимкни посилання Pay!")
    return web.json_response({"code": st.code, "link": link})


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задано")
    bot = Bot(settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bootstrap()
    if not settings.BOT_USERNAME:
        settings.BOT_USERNAME = (await bot.get_me()).username
    dp = build_dispatcher()

    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/health", lambda r: web.Response(text="ok"))
    app.router.add_post("/webhook/payment", payment_webhook)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=settings.TG_SECRET).register(app, path="/webhook/telegram")
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.PORT).start()

    sched = AsyncIOScheduler(timezone=KYIV)
    sched.add_job(tick, "interval", minutes=5, args=[bot], max_instances=1, coalesce=True)
    sched.add_job(weekly_report, "cron", day_of_week="mon", hour=10, args=[bot])
    sched.start()

    types = dp.resolve_used_update_types()
    if settings.USE_POLLING:
        log.info("Polling mode")
        await bot.delete_webhook()
        await dp.start_polling(bot, allowed_updates=types)
    else:
        url = f"{settings.BASE_URL}/webhook/telegram"
        await bot.set_webhook(url, secret_token=settings.TG_SECRET, allowed_updates=types)
        log.info("Webhook set: %s", url)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
