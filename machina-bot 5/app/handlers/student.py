"""Вигляд для тих, хто оплатив: меню, уроки, тести, домашки, дзвінки, підтримка."""
import uuid
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, PollAnswer
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from .. import texts as T
from ..common import (IsStudent, access_state, gate, main_menu, relay_to_staff, safe_send, send_item,
                      send_sticker_for, url_kb)
from ..config import settings
from ..course import (BLOCKS, CALLS_TOTAL, QUIZZES, access_end, block_lessons, block_of_lesson, block_open_at,
                      block_theme, block_title, has_support, lesson_title, open_blocks, package_title)
from ..db import Event, Poll, QuizResult, Student, utcnow
from ..services import esc, fmt_date, fmt_dm, get_items, log_event, manager_ids, staff_name, admin_ids

router = Router()
router.message.filter(IsStudent())
router.callback_query.filter(IsStudent())
router.poll_answer.filter(IsStudent())


class HW(StatesGroup):
    send = State()


class Msg(StatesGroup):
    text = State()  # data: kind = support | call | feedback


def _who(label_staff: str, st: Student) -> str:
    return "Валерії" if st.package == "valeria" else (label_staff or "куратору")


async def _targets(session, st: Student, kind: str) -> list[int]:
    if kind in ("hw", "call"):
        return [st.curator_tg_id] if st.curator_tg_id else await admin_ids(session)
    return await manager_ids(session)


# ───────── /start і ▶ Старт ─────────
@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def start_cmd(message: Message, student: Student, state: FSMContext):
    await state.clear()
    await show_start(message, student)


@router.message(F.text == T.BTN_START)
async def btn_start(message: Message, student: Student, state: FSMContext):
    await state.clear()
    await show_start(message, student)


async def show_start(message: Message, st: Student):
    if not await gate(message, st):
        return
    sched = "\n".join(f"• {block_title(b)} — {fmt_dm(block_open_at(st.paid_at, b))}" for b in range(1, BLOCKS + 1))
    sched += f"\n• 🎁 Бонусний тиждень — {fmt_dm(st.paid_at + timedelta(days=35))}"
    await message.answer(T.tx("start_info", start=fmt_date(st.paid_at), schedule=sched,
                              end=fmt_date(access_end(st.paid_at, st.extra_days))),
                         reply_markup=main_menu(st.package))


# ───────── Мої уроки ─────────
def lessons_text(st: Student) -> str:
    k = len(open_blocks(st.paid_at, utcnow()))
    return T.tx("lessons_title") + f"\n\n{'▰' * k}{'▱' * (BLOCKS - k)}  відкрито {k} з {BLOCKS}"


def blocks_kb(st: Student) -> InlineKeyboardMarkup:
    now = utcnow()
    ob = open_blocks(st.paid_at, now)
    kb = InlineKeyboardBuilder()
    for b in range(1, BLOCKS + 1):
        if b in ob:
            kb.button(text=f"📖 {block_title(b)}", callback_data=f"blk:{b}")
        else:
            kb.button(text=f"🔒 {block_title(b)} · з {fmt_dm(block_open_at(st.paid_at, b))}", callback_data=f"lock:{b}")
    kb.adjust(1)
    return kb.as_markup()


@router.message(F.text == T.BTN_LESSONS)
async def btn_lessons(message: Message, student: Student, state: FSMContext):
    await state.clear()
    if not await gate(message, student):
        return
    await message.answer(lessons_text(student), reply_markup=blocks_kb(student))


@router.callback_query(F.data == "list")
async def cb_list(cb: CallbackQuery, student: Student):
    if access_state(student) != "ok":
        return await cb.answer("Доступ закрито", show_alert=True)
    await cb.message.edit_text(lessons_text(student), reply_markup=blocks_kb(student))
    await cb.answer()


@router.callback_query(F.data.startswith("lock:"))
async def cb_lock(cb: CallbackQuery, student: Student):
    b = int(cb.data.split(":")[1])
    await cb.answer(T.tx("block_locked", date=fmt_dm(block_open_at(student.paid_at, b))), show_alert=True)


async def _block_ok(cb: CallbackQuery, st: Student, b: int) -> bool:
    if access_state(st) != "ok":
        await cb.answer("Доступ закрито", show_alert=True)
        return False
    if b not in open_blocks(st.paid_at, utcnow()):
        await cb.answer(T.tx("block_locked", date=fmt_dm(block_open_at(st.paid_at, b))), show_alert=True)
        return False
    return True


@router.callback_query(F.data.startswith("blk:"))
async def cb_block(cb: CallbackQuery, student: Student, session):
    b = int(cb.data.split(":")[1])
    if not await _block_ok(cb, student, b):
        return
    done = set((await session.execute(select(Event.data).where(
        Event.student_id == student.id, Event.type == "answers"))).scalars())
    kb = InlineKeyboardBuilder()
    for n in block_lessons(b):
        kb.button(text=f"{'✅' if str(n) in done else '▶'} {lesson_title(n)}", callback_data=f"les:{n}")
    kb.button(text=f"📝 Тест · {block_title(b)}", callback_data=f"quiz:{b}")
    kb.button(text="⬅ До блоків", callback_data="list")
    kb.adjust(1)
    theme = block_theme(b)
    await cb.message.edit_text(T.tx("block_page", title=esc(block_title(b)), theme=(esc(theme) + "\n\n") if theme else "\n"),
                               reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("les:"))
async def cb_lesson(cb: CallbackQuery, student: Student, session, bot: Bot):
    n = int(cb.data.split(":")[1])
    if not await _block_ok(cb, student, block_of_lesson(n)):
        return
    await cb.answer()
    chat = cb.message.chat.id
    items = await get_items(session, n, ("lesson", "video", "audio", "exercises"))
    if not items:
        await bot.send_message(chat, T.tx("lesson_empty"))
        return
    await bot.send_message(chat, T.tx("lesson_header", title=esc(lesson_title(n))), protect_content=True)
    for it in items:
        try:
            await send_item(bot, chat, it, student)
        except Exception:
            await bot.send_message(chat, "Один файл не вдалось надіслати 🙈 Напиши в «💬 Підтримка» — виправимо.")
    await log_event(session, student.id, "lesson", str(n))
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Я зробив(-ла) — покажи розбір", callback_data=f"ans:{n}")
    await bot.send_message(chat, T.tx("lesson_done_prompt"), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("ans:"))
async def cb_answers(cb: CallbackQuery, student: Student, session, bot: Bot):
    n = int(cb.data.split(":")[1])
    if not await _block_ok(cb, student, block_of_lesson(n)):
        return
    await cb.answer()
    items = await get_items(session, n, ("answers",))
    if not items:
        await bot.send_message(cb.message.chat.id, T.tx("answers_empty"))
        return
    for it in items:
        await send_item(bot, cb.message.chat.id, it, student)
    await log_event(session, student.id, "answers", str(n))


# ───────── Таблиця часів ─────────
@router.message(F.text == T.BTN_TABLE)
async def btn_table(message: Message, student: Student, session, bot: Bot, state: FSMContext):
    await state.clear()
    if not await gate(message, student):
        return
    items = await get_items(session, 0, ("table",))
    if not items:
        await message.answer(T.tx("table_empty"))
        return
    await message.answer(T.tx("table_intro"), protect_content=True)
    for it in items:
        await send_item(bot, message.chat.id, it, student)


# ───────── Тести (нативні Telegram-квізи) ─────────
async def send_question(bot: Bot, session, st: Student, b: int, idx: int, attempt: str) -> None:
    q = QUIZZES[str(b)][idx]
    m = await bot.send_poll(st.tg_id, question=q["q"][:300], options=[o[:100] for o in q["options"]], type="quiz",
                            correct_option_id=q["correct"], is_anonymous=False,
                            explanation=(q.get("explanation") or None) and q["explanation"][:200],
                            protect_content=True)
    session.add(Poll(poll_id=m.poll.id, student_id=st.id, block=b, idx=idx, correct=q["correct"], attempt=attempt))
    await session.flush()


@router.callback_query(F.data.startswith("quiz:"))
async def cb_quiz(cb: CallbackQuery, student: Student, session, bot: Bot):
    b = int(cb.data.split(":")[1])
    if not await _block_ok(cb, student, b):
        return
    qs = QUIZZES.get(str(b)) or []
    if not qs:
        return await cb.answer(T.tx("quiz_none"), show_alert=True)
    await cb.answer()
    await bot.send_message(cb.message.chat.id, T.tx("quiz_start", title=esc(block_title(b)), n=len(qs)))
    await send_question(bot, session, student, b, 0, uuid.uuid4().hex[:12])


@router.poll_answer()
async def on_poll_answer(pa: PollAnswer, student: Student, session, bot: Bot):
    poll = await session.get(Poll, pa.poll_id)
    if not poll or poll.student_id != student.id or poll.is_right is not None:
        return
    poll.is_right = bool(pa.option_ids) and pa.option_ids[0] == poll.correct
    await session.flush()
    qs = QUIZZES.get(str(poll.block)) or []
    if poll.idx + 1 < len(qs):
        await send_question(bot, session, student, poll.block, poll.idx + 1, poll.attempt)
        return
    rows = (await session.execute(select(Poll).where(Poll.attempt == poll.attempt))).scalars().all()
    score, total = sum(1 for r in rows if r.is_right), len(qs)
    session.add(QuizResult(student_id=student.id, block=poll.block, score=score, total=total))
    await log_event(session, student.id, "quiz", f"{poll.block}:{score}/{total}")
    ratio = score / total if total else 0
    key = "quiz_done_high" if ratio >= 0.8 else "quiz_done_mid" if ratio >= 0.5 else "quiz_done_low"
    if key == "quiz_done_high":
        await send_sticker_for(bot, session, student.tg_id, "quiz_high")
    await bot.send_message(student.tg_id, T.tx(key, score=score, total=total))


# ───────── Домашки ─────────
@router.message(F.text == T.BTN_HW)
async def btn_hw(message: Message, student: Student, state: FSMContext):
    await state.clear()
    if not await gate(message, student):
        return
    if not has_support(student.package):
        await message.answer(T.tx("hw_no_support"))
        return
    kb = InlineKeyboardBuilder()
    for b in open_blocks(student.paid_at, utcnow()):
        for n in block_lessons(b):
            kb.button(text=lesson_title(n), callback_data=f"hwl:{n}")
    kb.adjust(2)
    await message.answer(T.tx("hw_pick"), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("hwl:"))
async def cb_hw_lesson(cb: CallbackQuery, student: Student, state: FSMContext):
    n = int(cb.data.split(":")[1])
    if not await _block_ok(cb, student, block_of_lesson(n)):
        return
    await state.set_state(HW.send)
    await state.update_data(lesson=n)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Це все", callback_data="hwdone")
    await cb.message.answer(T.tx("hw_send", n=n), reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data == "hwdone")
async def cb_hw_done(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer(T.tx("hw_done"))
    await cb.answer()


@router.message(HW.send)
async def hw_message(message: Message, student: Student, session, bot: Bot, state: FSMContext):
    n = (await state.get_data()).get("lesson", 0)
    who = "Валерії" if student.package == "valeria" else "куратору"
    ok = await relay_to_staff(bot, session, student, message, "hw", str(n), f"📩 <b>Домашка · урок {n}</b>",
                              await _targets(session, student, "hw"))
    if ok:
        await log_event(session, student.id, "hw", str(n))
        await send_sticker_for(bot, session, message.chat.id, "hw_got")
        await message.answer(T.tx("hw_got", who=who))
    else:
        await message.answer(T.tx("hw_no_curator"))


# ───────── Дзвінок ─────────
@router.message(F.text == T.BTN_CALL)
async def btn_call(message: Message, student: Student, state: FSMContext):
    await state.clear()
    if not await gate(message, student):
        return
    if not has_support(student.package):
        await message.answer(T.tx("hw_no_support"))
        return
    kb = InlineKeyboardBuilder()
    if settings.CALL_BOOKING_URL:
        kb.row(InlineKeyboardButton(text="📅 Обрати час", url=settings.CALL_BOOKING_URL))
    kb.button(text="✍ Написати побажання щодо часу", callback_data="callwish")
    kb.adjust(1)
    await message.answer(T.tx("call_info", used=student.calls_used, total=CALLS_TOTAL), reply_markup=kb.as_markup())


@router.callback_query(F.data == "callwish")
async def cb_call_wish(cb: CallbackQuery, student: Student, state: FSMContext):
    if access_state(student) != "ok":
        return await cb.answer("Доступ закрито", show_alert=True)
    await state.set_state(Msg.text)
    await state.update_data(kind="call")
    await cb.message.answer(T.tx("call_wish", who=_who("куратору", student)))
    await cb.answer()


# ───────── Підтримка / відгук ─────────
@router.message(F.text == T.BTN_SUPPORT)
async def btn_support(message: Message, student: Student, state: FSMContext):
    await state.set_state(Msg.text)
    await state.update_data(kind="support")
    await message.answer(T.tx("support_ask"))


@router.callback_query(F.data == "fb")
async def cb_feedback(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Msg.text)
    await state.update_data(kind="feedback")
    await cb.message.answer(T.tx("feedback_ask"))
    await cb.answer()


@router.message(Msg.text)
async def msg_to_staff(message: Message, student: Student, session, bot: Bot, state: FSMContext):
    kind = (await state.get_data()).get("kind", "support")
    await state.clear()
    title = {"support": "💬 <b>Підтримка</b>", "call": "📞 <b>Запит на дзвінок</b>", "feedback": "⭐ <b>Відгук</b>"}[kind]
    ok = await relay_to_staff(bot, session, student, message, kind, "", title, await _targets(session, student, kind))
    await message.answer(T.tx({"support": "support_sent", "call": "call_sent", "feedback": "feedback_thanks"}[kind],
                              who=_who("куратору", student)))
    if not ok:
        await message.answer(T.tx("hw_no_curator"))


# ───────── Ще більше ─────────
@router.message(F.text == T.BTN_MORE)
@router.callback_query(F.data == "more")
async def more(event, student: Student, state: FSMContext):
    await state.clear()
    msg = event.message if isinstance(event, CallbackQuery) else event
    kb = url_kb(("🔁 Продовжити доступ", settings.EXTEND_URL), ("📓 Робочий зошит для друку", settings.WORKBOOK_URL),
                ("📘 Уроки граматики зі знижкою", settings.GRAMMAR_URL))
    await msg.answer(T.tx("more") if kb else T.tx("more_empty"), reply_markup=kb)
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data == "call")
async def cb_call_open(cb: CallbackQuery, student: Student, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    if settings.CALL_BOOKING_URL:
        kb.row(InlineKeyboardButton(text="📅 Обрати час", url=settings.CALL_BOOKING_URL))
    kb.button(text="✍ Написати побажання щодо часу", callback_data="callwish")
    kb.adjust(1)
    await cb.message.answer(T.tx("call_info", used=student.calls_used, total=CALLS_TOTAL), reply_markup=kb.as_markup())
    await cb.answer()


@router.message(Command("menu"))
async def cmd_menu(message: Message, student: Student, state: FSMContext):
    await state.clear()
    await message.answer("Ось меню 👇", reply_markup=main_menu(student.package))


# ───────── будь-що інше ─────────
@router.message()
async def fallback(message: Message, student: Student):
    await message.answer("Got it? 😉 Скористайся кнопками меню внизу 👇", reply_markup=main_menu(student.package))
