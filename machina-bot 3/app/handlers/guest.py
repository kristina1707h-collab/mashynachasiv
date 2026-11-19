"""Вигляд для тих, хто НЕ оплатив: лише привітання, кнопка в Direct і ввід коду."""
import re

from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select, update

from .. import texts as T
from ..common import CODE_RE, IsGuest, guest_kb, main_menu, safe_send, send_sticker_for
from ..config import settings
from ..course import access_end, block_open_at, has_support, package_title, PACKAGES
from ..db import Student, utcnow
from ..services import esc, fmt_date, log_event, manager_ids, mark_sent, staff_name

router = Router()
router.message.filter(IsGuest())
router.callback_query.filter(IsGuest())


async def welcome_text(session, st: Student, name: str) -> str:
    who = esc(await staff_name(session, st.curator_tg_id)) if st.curator_tg_id else "куратор"
    line = T.tx("support_line", who="Валерія" if st.package == "valeria" else who) if has_support(st.package) else T.tx("self_line")
    return T.tx("welcome", name=esc(name), package=package_title(st.package), start=fmt_date(st.paid_at),
                end=fmt_date(access_end(st.paid_at, st.extra_days)), support_line=line)


async def try_activate(message: Message, session, bot: Bot, raw: str) -> None:
    code = re.sub(r"[^A-Z0-9]", "", raw.upper())
    st = (await session.execute(select(Student).where(Student.code == code))).scalar_one_or_none()
    if not st:
        await message.answer(T.tx("no_code"))
        return
    uid = message.from_user.id
    if st.blocked:
        await message.answer(T.tx("blocked"))
        return
    if st.tg_id and st.tg_id != uid:
        await message.answer(T.tx("code_used"))
        return
    others = (await session.execute(select(Student).where(Student.tg_id == uid, Student.id != st.id))).scalars().all()
    if others and not (st.is_test or any(o.is_test for o in others)):
        await message.answer(T.tx("already_has"))
        return
    if others:  # тестові акаунти: перепривʼязка
        await session.execute(update(Student).where(Student.tg_id == uid, Student.id != st.id).values(tg_id=None))
    now = utcnow()
    st.tg_id = uid
    st.tg_username = message.from_user.username or ""
    st.first_name = message.from_user.first_name or ""
    st.activated_at = st.activated_at or now
    st.last_active_at = now
    await mark_sent(session, st.id, "block_open:1")
    await log_event(session, st.id, "activated")
    await session.commit()
    await bind_and_welcome(bot, session, message.chat.id, message.from_user, st)


async def bind_and_welcome(bot: Bot, session, chat_id: int, user, st: Student) -> None:
    name = st.name or user.first_name or "друже"
    await send_sticker_for(bot, session, chat_id, "welcome")
    await bot.send_message(chat_id, await welcome_text(session, st, name), reply_markup=main_menu(st.package))
    if st.is_test:
        return
    info = (f"🟢 Активовано доступ: <b>{esc(st.display)}</b> · {package_title(st.package)} · #{st.id}"
            + (f" · @{st.tg_username}" if st.tg_username else ""))
    targets = set(await manager_ids(session))
    if st.curator_tg_id:
        targets.add(st.curator_tg_id)
    for t in targets:
        await safe_send(bot, t, info)


@router.message(CommandStart(deep_link=True))
async def start_code(message: Message, command: CommandObject, session, bot: Bot, state: FSMContext):
    await state.clear()
    await try_activate(message, session, bot, command.args or "")


@router.message(F.text)
async def guest_text(message: Message, session, bot: Bot, state: FSMContext):
    await state.clear()
    txt = (message.text or "").strip().upper().replace(" ", "")
    if CODE_RE.match(txt):
        await try_activate(message, session, bot, txt)
        return
    key = "guest" if (message.text or "").startswith("/start") else "guest_locked"
    await message.answer(T.tx(key), reply_markup=guest_kb())


@router.message()
async def guest_any(message: Message):
    await message.answer(T.tx("guest_locked"), reply_markup=guest_kb())
