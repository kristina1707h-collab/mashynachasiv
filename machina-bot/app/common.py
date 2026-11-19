"""Спільні штуки: middleware, фільтри, надсилання захищеного контенту, релей до персоналу."""
from __future__ import annotations

import asyncio
import logging
import re

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Filter
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup, ReplyParameters)
from sqlalchemy import select

from . import texts as T
from .config import settings
from .course import has_support, is_expired
from .db import ContentItem, Relay, SessionLocal, Staff, Student, utcnow
from .services import esc, get_setting, staff_name

log = logging.getLogger("machina")
CODE_RE = re.compile(r"^[A-Z0-9]{8,12}$")


# ───────── middleware / фільтри ─────────
class DbMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        async with SessionLocal() as session:
            data["session"] = session
            data["staff"] = None
            data["student"] = None
            user = data.get("event_from_user")
            if user:
                data["staff"] = await session.get(Staff, user.id)
                st = (await session.execute(select(Student).where(Student.tg_id == user.id)
                                            .order_by(Student.id.desc()))).scalars().first()
                if st:
                    st.last_active_at = utcnow()
                    st.bot_blocked = False
                    if user.username is not None and st.tg_username != user.username:
                        st.tg_username = user.username
                data["student"] = st
            result = await handler(event, data)
            await session.commit()
            return result


class IsStaff(Filter):
    async def __call__(self, event, staff=None) -> bool:
        return staff is not None


class IsAdmin(Filter):
    async def __call__(self, event, staff=None) -> bool:
        return staff is not None and staff.is_admin


class IsGuest(Filter):
    async def __call__(self, event, student=None) -> bool:
        return student is None


class IsStudent(Filter):
    async def __call__(self, event, student=None) -> bool:
        return student is not None


class RelayReply(Filter):
    """Реплай персоналу на повідомлення, яке бот переслав від студента."""
    async def __call__(self, message: Message, session, staff=None):
        if staff is None or not message.reply_to_message:
            return False
        if message.text and message.text.startswith("/"):
            return False
        r = await session.get(Relay, (message.chat.id, message.reply_to_message.message_id))
        return {"relay": r} if r else False


# ───────── клавіатури ─────────
def main_menu(package: str) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=T.BTN_START), KeyboardButton(text=T.BTN_LESSONS)], [KeyboardButton(text=T.BTN_TABLE)]]
    if has_support(package):
        rows.append([KeyboardButton(text=T.BTN_HW), KeyboardButton(text=T.BTN_CALL)])
    rows.append([KeyboardButton(text=T.BTN_SUPPORT), KeyboardButton(text=T.BTN_MORE)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def url_kb(*pairs: tuple[str, str]) -> InlineKeyboardMarkup | None:
    rows = [[InlineKeyboardButton(text=t, url=u)] for t, u in pairs if u]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def guest_kb() -> InlineKeyboardMarkup | None:
    return url_kb(("💜 Як отримати доступ", settings.DIRECT_URL))


# ───────── доступ ─────────
def access_state(st: Student) -> str:
    """ok | blocked | expired"""
    if st.blocked:
        return "blocked"
    if is_expired(st.paid_at, utcnow(), st.extra_days):
        return "expired"
    return "ok"


async def gate(message: Message, st: Student) -> bool:
    s = access_state(st)
    if s == "ok":
        return True
    await message.answer(T.tx("blocked" if s == "blocked" else "expired"))
    return False


# ───────── надсилання ─────────
async def send_sticker_for(bot: Bot, session, chat_id: int, event: str) -> None:
    fid = await get_setting(session, f"sticker:{event}")
    if fid:
        try:
            await bot.send_sticker(chat_id, fid, protect_content=True)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass


def nick_of(st: Student) -> str:
    return f"@{st.tg_username}" if st.tg_username else f"id{st.tg_id}"


async def send_item(bot: Bot, chat_id: int, it: ContentItem, st: Student | None = None) -> None:
    """Усе, що бачить студент, іде з protect_content=True: Telegram забороняє пересилання й збереження.
    У підпис додається «водяний знак» з ніком студента."""
    cap = it.title or ""
    if settings.WATERMARK and st is not None:
        cap = (cap + "\n" if cap else "") + f"🔒 {nick_of(st)}"
    kw = {"caption": cap or None, "protect_content": True}
    ft = it.file_type
    if ft == "video":
        await bot.send_video(chat_id, it.file_id, supports_streaming=True, **kw)
    elif ft == "audio":
        await bot.send_audio(chat_id, it.file_id, **kw)
    elif ft == "voice":
        await bot.send_voice(chat_id, it.file_id, **kw)
    elif ft == "photo":
        await bot.send_photo(chat_id, it.file_id, **kw)
    else:
        await bot.send_document(chat_id, it.file_id, **kw)
    await asyncio.sleep(0.3)


async def safe_send(bot: Bot, chat_id: int, text: str, **kw) -> bool:
    try:
        await bot.send_message(chat_id, text, **kw)
        return True
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        log.warning("send to %s failed: %s", chat_id, e)
        return False


async def relay_to_staff(bot: Bot, session, st: Student, message: Message, kind: str, ref: str,
                         title: str, targets: list[int]) -> int:
    header = (f"{title}\n👤 {esc(st.display)} · #{st.id} · {st.package}"
              + (f"\n🔗 @{st.tg_username}" if st.tg_username else ""))
    ok = 0
    for t in dict.fromkeys(targets):
        try:
            h = await bot.send_message(t, header)
            c = await bot.copy_message(t, message.chat.id, message.message_id,
                                       reply_parameters=ReplyParameters(message_id=h.message_id))
            for mid in (h.message_id, c.message_id):
                session.add(Relay(chat_id=t, message_id=mid, student_id=st.id, kind=kind, ref=ref))
            ok += 1
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            log.warning("relay to %s failed: %s", t, e)
    await session.flush()
    return ok
