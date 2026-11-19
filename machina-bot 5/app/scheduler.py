"""Автоповідомлення за графіком. Ідемпотентно: кожна подія пишеться в sent_log, тож після
перезапуску/«засинання» бот просто дожене пропущене й не задублює."""
import logging
from datetime import timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from . import texts as T
from .common import access_state, safe_send, send_sticker_for, url_kb
from .config import KYIV, settings
from .course import block_theme, block_title, due_events, has_support
from .db import SessionLocal, Student, utcnow
from .services import (admin_ids, build_stats, get_setting, mark_sent, seats_limit, seats_taken,
                       sent_keys, set_setting, staff_name, esc)

log = logging.getLogger("machina.scheduler")


def _quiet(now) -> bool:
    h = now.replace(tzinfo=timezone.utc).astimezone(KYIV).hour
    return settings.QUIET_HOURS and not (9 <= h < 21)


async def _send_event(bot: Bot, session, st: Student, key: str) -> None:
    kind, _, arg = key.partition(":")
    chat = st.tg_id
    kb = InlineKeyboardBuilder()
    if kind == "block_open":
        b = int(arg)
        theme = block_theme(b) or block_title(b)
        await send_sticker_for(bot, session, chat, "block_open")
        kb.button(text="📚 Відкрити блок", callback_data=f"blk:{b}")
        await bot.send_message(chat, T.tx("auto_block", theme=esc(theme)), reply_markup=kb.as_markup())
    elif kind == "call":
        who = "Валерією" if st.package == "valeria" else "куратором"
        kb.button(text="📞 Обрати час", callback_data="call")
        await bot.send_message(chat, T.tx("auto_call", who=who), reply_markup=kb.as_markup())
    elif kind == "bonus":
        await send_sticker_for(bot, session, chat, "bonus")
        if settings.FEEDBACK_URL:
            m = url_kb(("💜 Залишити відгук", settings.FEEDBACK_URL))
        else:
            kb.button(text="💜 Залишити відгук", callback_data="fb")
            m = kb.as_markup()
        await bot.send_message(chat, T.tx("auto_bonus"), reply_markup=m)
    elif kind in ("remind_end", "expired"):
        if kind == "expired":
            await send_sticker_for(bot, session, chat, "expired")
        kb.button(text="⭐ Ще більше", callback_data="more")
        await bot.send_message(chat, T.tx("auto_remind_end" if kind == "remind_end" else "auto_expired"),
                               reply_markup=kb.as_markup())


async def tick(bot: Bot) -> None:
    now = utcnow()
    async with SessionLocal() as session:
        students = (await session.execute(select(Student).where(
            Student.tg_id.is_not(None), Student.blocked == False, Student.bot_blocked == False))).scalars().all()  # noqa: E712
        for st in students:
            try:
                if _quiet(now) and not st.is_test:
                    continue
                done = await sent_keys(session, st.id)
                due = [k for k in due_events(st.paid_at, now, st.extra_days, has_support(st.package)) if k not in done]
                # старі блоки/дзвінки не спамимо: лише найновіший
                for fam in ("block_open", "call"):
                    fk = sorted((k for k in due if k.startswith(fam + ":")), key=lambda k: int(k.split(":")[1]))
                    for old in fk[:-1]:
                        await mark_sent(session, st.id, old)
                        due.remove(old)
                for k in due:
                    if access_state(st) == "expired" and not k.startswith("expired"):
                        await mark_sent(session, st.id, k)
                        continue
                    await _send_event(bot, session, st, k)
                    await mark_sent(session, st.id, k)
                # 3 дні без активності (раз на «серію» неактивності)
                if (access_state(st) == "ok" and st.last_active_at and now - st.last_active_at >= timedelta(days=3)):
                    ik = f"inactive:{st.last_active_at.date().isoformat()}"
                    if ik not in done:
                        await bot.send_message(st.tg_id, T.tx("auto_inactive"))
                        await mark_sent(session, st.id, ik)
                await session.commit()
            except TelegramForbiddenError:
                st.bot_blocked = True
                await session.commit()
            except Exception:
                log.exception("tick failed for student %s", st.id)
                await session.rollback()
        await _price_reminders(bot, session, now)
        await session.commit()


async def _price_reminders(bot: Bot, session, now) -> None:
    change = settings.PRICE_CHANGE_AT_UTC
    for stage, at, text in (("d1", change - timedelta(days=1), "⏰ Завтра о 00:00 змінюються ціни. Підготуй нові посилання Pay!"),
                            ("now", change, "💸 Ціни змінились: 2 490 / 9 990 / 19 990. Перевір, що посилання Pay оновлені!")):
        key = f"pricechange:{stage}"
        if now >= at and not await get_setting(session, key):
            for a in await admin_ids(session):
                await safe_send(bot, a, text)
            await set_setting(session, key, "1")


async def weekly_report(bot: Bot) -> None:
    async with SessionLocal() as session:
        text = await build_stats(session)
        for a in await admin_ids(session):
            await safe_send(bot, a, text)
