"""Команди менеджерки / Валерії / кураторів. Повний список — /admin."""
import csv
import io
import re
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message, ReactionTypeEmoji
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, select

from .. import texts as T
from ..common import IsAdmin, IsStaff, RelayReply, access_state, apply_commands, main_menu, safe_send
from ..config import settings
from ..course import PACKAGES, access_end, day_number, has_support, open_blocks, package_title, status_of
from ..db import ContentItem, Relay, Staff, Student, utcnow
from ..services import (build_stats, deep_link, esc, find_students, fmt_date, get_setting, issue_student,
                        seats_limit, seats_taken, set_setting, staff_name, student_card, admin_ids)
from .guest import bind_and_welcome

router = Router()
PKGS = "|".join(PACKAGES)


class Issue(StatesGroup):
    info = State()


class Upload(StatesGroup):
    files = State()


class Broadcast(StatesGroup):
    confirm = State()


class SetText(StatesGroup):
    value = State()


class SetSticker(StatesGroup):
    wait = State()


HELP = (
    "⚙️ <b>Додатково</b> (усе основне — кнопками в /admin)\n\n"
    "<b>Доступи</b>\n/issue [self|curator|valeria] [Імʼя @instagram] — видати код після оплати\n"
    "/students [пакет] — список · /student &lt;id|імʼя|@нік&gt; — картка · /stats — цифри\n"
    "/set &lt;id&gt; &lt;поле&gt; &lt;значення&gt; — name, instagram, amount, country, tz, source, upsell, notes, curator, package, calls, paid_at\n"
    "/extend &lt;id&gt; &lt;днів&gt; · /block &lt;id&gt; · /unblock &lt;id&gt; · /calldone &lt;id&gt; · /export — CSV таблиця студентів\n"
    "/seats [число] — місця «З Валерією»\n\n"
    "<b>Контент</b>\n/upload — потім кидай файли <i>MCh_Урок01_….pdf</i> (імʼя → урок і тип автоматично)\n"
    "/upload &lt;блок&gt; &lt;урок&gt; &lt;lesson|video|audio|exercises|answers|table&gt; — вручну · /done — вийти\n"
    "/content [урок] — список · /delcontent &lt;id&gt;\n\n"
    "<b>Стиль і стікери</b>\n/texts — усі тексти · /settext &lt;ключ&gt; · /resettext &lt;ключ&gt; · /setsticker &lt;подія&gt;\n\n"
    "<b>Команда</b>\n/staff · /addstaff &lt;tg_id&gt; &lt;manager|curator|valeria&gt; &lt;імʼя&gt; [admin] · /rmstaff &lt;tg_id&gt;\n\n"
    "<b>Тестування</b>\n/setup — перевірка готовності · /testas &lt;self|curator|valeria&gt; — стати оплаченим студентом · /guest — повернутись у вигляд «не оплатив»\n"
    "/shift &lt;id&gt; &lt;днів&gt; — «перемотати» час, щоб побачити нові блоки й автоповідомлення\n"
    "/broadcast [all|self|curator|valeria] текст — розсилка студентам"
)


def panel_kb():
    kb = InlineKeyboardBuilder()
    for t, d in [("🆕 Видати доступ", "adm:issue"), ("👥 Студенти", "adm:students"),
                 ("📥 Додати матеріали", "adm:upload"), ("📊 Статистика", "adm:stats"),
                 ("✅ Готовність до старту", "adm:setup"), ("🧪 Перевірка бота", "adm:test"),
                 ("⚙️ Додатково", "adm:help")]:
        kb.button(text=t, callback_data=d)
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


@router.message(Command("admin", "help"), IsStaff())
async def admin_help(message: Message, staff: Staff):
    if staff.is_admin:
        await message.answer("🛠 <b>Панель «Машини часів»</b>\nОбирай дію 👇", reply_markup=panel_kb())
    else:
        await message.answer("Ти куратор 💜 Домашки приходять сюди. Щоб відповісти студенту — просто зроби <b>реплай</b> "
                             "на його повідомлення (текст, голосове чи файл).")


async def _students_kb(session):
    rows = (await session.execute(select(Student).where(Student.is_test == False)  # noqa: E712
                                  .order_by(Student.id.desc()).limit(40))).scalars().all()
    now = utcnow()
    kb = InlineKeyboardBuilder()
    for r in rows:
        stt = "⏳ не активовано" if not r.tg_id else status_of(r.paid_at, now, r.extra_days, r.blocked)
        kb.button(text=f"{PACKAGES[r.package]['emoji']} {r.display} · {stt}"[:60], callback_data=f"stu:{r.id}")
    kb.adjust(1)
    return rows, kb.as_markup()


def _card_kb(st: Student):
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ +30 днів доступу", callback_data=f"sa:ext:{st.id}")
    kb.button(text="✅ Розблокувати" if st.blocked else "🚫 Заблокувати", callback_data=f"sa:blk:{st.id}")
    if has_support(st.package):
        kb.button(text="📞 Дзвінок проведено (+1)", callback_data=f"sa:call:{st.id}")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data.startswith("stu:"), IsAdmin())
async def cb_student(cb: CallbackQuery, session):
    st = await session.get(Student, int(cb.data.split(":")[1]))
    await cb.answer()
    if st:
        await cb.message.answer(await student_card(session, st), reply_markup=_card_kb(st))


@router.callback_query(F.data.startswith("sa:"), IsAdmin())
async def cb_student_action(cb: CallbackQuery, session):
    _, act, sid = cb.data.split(":")
    st = await session.get(Student, int(sid))
    if not st:
        return await cb.answer("Не знайшла", show_alert=True)
    if act == "ext":
        st.extra_days += 30
    elif act == "blk":
        st.blocked = not st.blocked
    elif act == "call":
        st.calls_used += 1
    await cb.answer("Готово ✅")
    await cb.message.edit_text(await student_card(session, st), reply_markup=_card_kb(st))


async def _coverage(session) -> str:
    rows = (await session.execute(select(ContentItem))).scalars().all()
    have = {}
    for r in rows:
        have.setdefault(r.lesson, set()).add(r.kind)
    mark = lambda ok: "✅" if ok else "▫️"  # noqa: E731
    lines = ["📥 <b>Контент</b> (📄 PDF · 🎬 відео · 🎧 аудіо · 🎯 місії Марка · ✏️ вправи · 🔑 розбір · 🧾 шпаргалка)"]
    for n in range(1, 11):
        h = have.get(n, set())
        lines.append(f"Урок {n}: {mark('lesson' in h)}📄 {mark('video' in h)}🎬 {mark('audio' in h)}🎧 "
                     f"{mark('missions' in h)}🎯 {mark('exercises' in h)}✏️ {mark('answers' in h)}🔑 {mark('cheatsheet' in h)}🧾")
    lines.append(f"Таблиця часів: {mark('table' in have.get(0, set()))}")
    lines.append("\nДодати: /upload auto · список: /content")
    return "\n".join(lines)


async def _readiness(session) -> str:
    ok = lambda c: "✅" if c else "⚠️"  # noqa: E731
    rows = (await session.execute(select(ContentItem))).scalars().all()
    have = {}
    for r in rows:
        have.setdefault(r.lesson, set()).add(r.kind)
    staff = (await session.execute(select(Staff))).scalars().all()
    from ..course import QUIZZES
    from ..db import Setting
    stickers = (await session.execute(select(Setting).where(Setting.key.like("sticker:%")))).scalars().all()
    b1 = all("lesson" in have.get(n, set()) for n in (1, 2))
    lines = ["✅ <b>Готовність до старту</b>", "",
             f"{ok(settings.DIRECT_URL)} Кнопка «Як отримати доступ» (DIRECT_URL)",
             f"{ok(any(s.role == 'valeria' for s in staff))} Валерія додана як <code>valeria</code> (/addstaff) — для пакета «З Валерією»",
             f"{ok(any(s.role == 'curator' for s in staff))} Є хоча б один куратор (/addstaff) — для пакета «З куратором»",
             f"{ok(b1)} Блок 1: PDF уроків 1–2 завантажені (до 12.11 — перед стартом!)",
             f"{ok(sum(1 for n in range(1, 11) if 'lesson' in have.get(n, set())) == 10)} Усі 10 уроків мають PDF "
             f"({sum(1 for n in range(1, 11) if 'lesson' in have.get(n, set()))}/10)",
             f"{ok(sum(1 for n in range(1, 11) if 'cheatsheet' in have.get(n, set())) == 10)} Шпаргалки після уроків "
             f"({sum(1 for n in range(1, 11) if 'cheatsheet' in have.get(n, set()))}/10)",
             f"{ok(sum(1 for n in range(1, 11) if 'answers' in have.get(n, set())) == 10)} Розбори уроків — приходять наступного дня "
             f"({sum(1 for n in range(1, 11) if 'answers' in have.get(n, set()))}/10)",
             f"{ok('table' in have.get(0, set()))} Шаблон таблиці часів",
             f"{ok(len(QUIZZES) >= 5)} Тести блоків у data/quizzes.json ({len(QUIZZES)}/5)",
             f"{ok(settings.CALL_BOOKING_URL)} Календар дзвінків (CALL_BOOKING_URL; без нього — запит текстом)",
             f"{ok(settings.EXTEND_URL and settings.WORKBOOK_URL)} Посилання «Ще більше» (EXTEND_URL, WORKBOOK_URL, GRAMMAR_URL)",
             f"{ok(settings.FEEDBACK_URL)} Форма відгуку (FEEDBACK_URL; без неї відгук збирається в боті)",
             f"{ok(settings.PAYMENT_WEBHOOK_SECRET)} Вебхук оплати (PAYMENT_WEBHOOK_SECRET)",
             f"{ok(stickers)} Стікери: налаштовано {len(stickers)} з 6 (/setsticker)",
             "", "Далі: протестуй обидва вигляди (👀 / 🧪 у /admin), зроби тестову покупку кожного пакета."]
    return "\n".join(lines)


@router.message(Command("setup"), IsAdmin())
async def cmd_setup(message: Message, session):
    await message.answer(await _readiness(session))


@router.callback_query(F.data.startswith("adm:"), IsAdmin())
async def cb_panel(cb: CallbackQuery, session, bot: Bot, state: FSMContext):
    act = cb.data[4:]
    await cb.answer()
    m = cb.message
    if act == "issue":
        kb = InlineKeyboardBuilder()
        for k in PACKAGES:
            kb.button(text=package_title(k), callback_data=f"iss:{k}")
        kb.adjust(1)
        await m.answer("Який пакет оплатили?", reply_markup=kb.as_markup())
    elif act == "students":
        rows, kb = await _students_kb(session)
        await m.answer("👥 <b>Студенти</b> — натисни, щоб відкрити картку 👇" if rows else "Поки нікого. Видай перший доступ 🆕",
                       reply_markup=kb if rows else None)
    elif act == "upload":
        await _start_wizard(m, session, state)
    elif act == "stats":
        await m.answer(await build_stats(session))
    elif act == "content":
        await m.answer(await _coverage(session))
    elif act == "setup":
        await m.answer(await _readiness(session))
    elif act == "help":
        await m.answer(HELP)
    elif act == "test":
        kb = InlineKeyboardBuilder()
        kb.button(text="👀 Як неоплачений", callback_data="tst:guest")
        for k in PACKAGES:
            kb.button(text=f"{package_title(k)} (оплачений)", callback_data=f"tst:{k}")
        kb.button(text="⏩ Перемотати +7 днів (наступний блок)", callback_data="tst:shift")
        kb.adjust(1)
        await m.answer("🧪 <b>Перевірка бота</b>\nОбери, у якій ролі хочеш побачити бота:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("tst:"), IsAdmin())
async def cb_testas(cb: CallbackQuery, session, bot: Bot):
    await cb.answer()
    what = cb.data.split(":")[1]
    if what == "guest":
        await _guest_mode(cb.from_user.id, session)
        from aiogram.types import ReplyKeyboardRemove
        return await cb.message.answer("Тепер ти для бота — людина, що не оплатила. Напиши /start 👇",
                                       reply_markup=ReplyKeyboardRemove())
    if what == "shift":
        st = (await session.execute(select(Student).where(Student.tg_id == cb.from_user.id, Student.is_test == True))  # noqa: E712
              ).scalars().first()
        if not st:
            return await cb.message.answer("Спочатку стань оплаченим студентом (кнопка вище) 🙂")
        st.paid_at -= timedelta(days=7)
        return await cb.message.answer(f"⏩ Тепер у тебе день {day_number(st.paid_at, utcnow())}. "
                                       "Нове автоповідомлення прийде за ≤5 хв, блоки вже відкриті в «📚 Мої уроки».")
    await _testas(bot, session, cb.message.chat.id, cb.from_user, what)


# ───────── видача доступів ─────────
def _parse_info(text: str) -> tuple[str, str]:
    ig = re.search(r"@[\w.]+", text)
    insta = ig.group(0) if ig else ""
    name = re.sub(r"@[\w.]+", "", text).strip(" ,-—")
    return name, insta


async def _do_issue(message: Message, session, bot: Bot, pkg: str, info: str) -> None:
    name, insta = _parse_info(info)
    st = await issue_student(session, pkg, name=name, instagram=insta, source="manual")
    await session.commit()
    link = deep_link(st.code)
    cur = esc(await staff_name(session, st.curator_tg_id)) if has_support(pkg) else "—"
    await message.answer(
        f"✅ Код видано · #{st.id} · {package_title(pkg)} · {st.amount} грн\n👩‍🏫 куратор: {cur}\n"
        f"Код: <code>{st.code}</code>\n\n<b>Скопіюй і надішли в Direct:</b>\n"
        f"<code>You DID it! 🎉 Оплату отримали. Ось твій квиток у «Машину часів» → {link}</code>")
    if pkg == "valeria":
        lim, taken = await seats_limit(session), await seats_taken(session)
        if taken >= lim:
            for a in await admin_ids(session):
                await safe_send(bot, a, f"⚠️ Місця «З Валерією»: {taken}/{lim}. Вимкни посилання Pay на цей пакет!")


@router.message(Command("issue"), IsAdmin())
async def cmd_issue(message: Message, command: CommandObject, session, bot: Bot, state: FSMContext):
    await state.clear()
    args = (command.args or "").split(maxsplit=1)
    if args and args[0] in PACKAGES:
        return await _do_issue(message, session, bot, args[0], args[1] if len(args) > 1 else "")
    kb = InlineKeyboardBuilder()
    for k in PACKAGES:
        kb.button(text=package_title(k), callback_data=f"iss:{k}")
    kb.adjust(1)
    await message.answer("Який пакет оплатили?", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("iss:"), IsAdmin())
async def cb_issue(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Issue.info)
    await state.update_data(pkg=cb.data.split(":")[1])
    await cb.message.answer("Напиши імʼя та @instagram одним повідомленням (або «-», щоб пропустити):")
    await cb.answer()


@router.message(Issue.info, IsAdmin())
async def issue_info(message: Message, session, bot: Bot, state: FSMContext):
    pkg = (await state.get_data())["pkg"]
    await state.clear()
    await _do_issue(message, session, bot, pkg, "" if (message.text or "").strip() == "-" else (message.text or ""))


# ───────── тестування ─────────
async def _guest_mode(uid: int, session) -> None:
    from sqlalchemy import update
    await session.execute(update(Student).where(Student.tg_id == uid, Student.is_test == True)  # noqa: E712
                          .values(tg_id=None))


async def _testas(bot: Bot, session, chat_id: int, user, pkg: str) -> None:
    from sqlalchemy import update
    from ..services import mark_sent
    st = await issue_student(session, pkg, name=user.first_name or "Тест", is_test=True, source="test")
    st.curator_tg_id = user.id if has_support(pkg) else None  # домашки й запити прийдуть тобі
    await session.execute(update(Student).where(Student.tg_id == user.id).values(tg_id=None))
    st.tg_id, st.tg_username = user.id, user.username or ""
    st.first_name, st.activated_at, st.last_active_at = user.first_name or "", utcnow(), utcnow()
    await mark_sent(session, st.id, "block_open:1")
    await session.commit()
    await bot.send_message(chat_id, f"🧪 Тестовий студент #{st.id} ({package_title(pkg)}). Нижче — те, що побачить оплачена людина.\n"
                                    f"/shift {st.id} 7 — відкрити наступний блок · /guest — вигляд «не оплатив».")
    await bind_and_welcome(bot, session, chat_id, user, st)


@router.message(Command("testas"), IsAdmin())
async def cmd_testas(message: Message, command: CommandObject, session, bot: Bot, state: FSMContext):
    await state.clear()
    pkg = (command.args or "").strip()
    if pkg not in PACKAGES:
        return await message.answer("Використання: /testas self | curator | valeria")
    await _testas(bot, session, message.chat.id, message.from_user, pkg)


@router.message(Command("guest"), IsStaff())
async def cmd_guest(message: Message, session, state: FSMContext):
    await state.clear()
    await _guest_mode(message.from_user.id, session)
    from aiogram.types import ReplyKeyboardRemove
    await message.answer("Ок, тепер ти для бота — людина, що не оплатила. Напиши /start 👇", reply_markup=ReplyKeyboardRemove())


@router.message(Command("shift"), IsAdmin())
async def cmd_shift(message: Message, command: CommandObject, session):
    try:
        sid, days = (command.args or "").split()
        st = await session.get(Student, int(sid))
        st.paid_at -= timedelta(days=int(days))
    except Exception:
        return await message.answer("Використання: /shift <id> <днів> (мінус днів від дати оплати)")
    await message.answer(f"⏩ #{st.id}: день {day_number(st.paid_at, utcnow())}. Автоповідомлення прийдуть за ≤5 хв.")


# ───────── студенти ─────────
@router.message(Command("students"), IsAdmin())
async def cmd_students(message: Message, command: CommandObject, session):
    rows, kb = await _students_kb(session)
    await message.answer("👥 <b>Студенти</b> — натисни, щоб відкрити картку 👇" if rows else "Поки нікого.", reply_markup=kb if rows else None)


@router.message(Command("student"), IsAdmin())
async def cmd_student(message: Message, command: CommandObject, session):
    rows = await find_students(session, command.args or "")
    if not rows:
        return await message.answer("Не знайшла 🤔")
    for r in rows[:5]:
        await message.answer(await student_card(session, r))


@router.message(Command("stats"), IsAdmin())
async def cmd_stats(message: Message, session):
    await message.answer(await build_stats(session))


@router.message(Command("seats"), IsAdmin())
async def cmd_seats(message: Message, command: CommandObject, session):
    if command.args and command.args.strip().isdigit():
        await set_setting(session, "valeria_seats", command.args.strip())
    await message.answer(f"⭐ «З Валерією»: зайнято {await seats_taken(session)} з {await seats_limit(session)}")


@router.message(Command("set"), IsAdmin())
async def cmd_set(message: Message, command: CommandObject, session):
    try:
        sid, field, value = (command.args or "").split(maxsplit=2)
        st = await session.get(Student, int(sid))
        if field in ("amount", "calls", "curator"):
            attr = {"calls": "calls_used", "curator": "curator_tg_id", "amount": "amount"}[field]
            setattr(st, attr, int(value))
        elif field == "paid_at":
            st.paid_at = datetime.fromisoformat(value)
        elif field == "package":
            assert value in PACKAGES
            st.package = value
        elif field in ("name", "instagram", "country", "tz", "source", "upsell", "notes"):
            setattr(st, field, value)
        else:
            raise ValueError
    except Exception:
        return await message.answer("Використання: /set <id> <поле> <значення>. Поля — див. /admin")
    await message.answer("✅\n" + await student_card(session, st))


@router.message(Command("extend"), IsAdmin())
async def cmd_extend(message: Message, command: CommandObject, session):
    try:
        sid, days = (command.args or "").split()
        st = await session.get(Student, int(sid))
        st.extra_days += int(days)
    except Exception:
        return await message.answer("Використання: /extend <id> <днів>")
    await message.answer(f"✅ Доступ #{st.id} тепер до {fmt_date(access_end(st.paid_at, st.extra_days))}")


@router.message(Command("block", "unblock", "calldone"), IsAdmin())
async def cmd_flags(message: Message, command: CommandObject, session):
    try:
        st = await session.get(Student, int((command.args or "").strip()))
        if command.command == "block":
            st.blocked = True
        elif command.command == "unblock":
            st.blocked = False
        else:
            st.calls_used += 1
    except Exception:
        return await message.answer(f"Використання: /{command.command} <id>")
    await message.answer("✅\n" + await student_card(session, st))


@router.message(Command("export"), IsAdmin())
async def cmd_export(message: Message, session):
    rows = (await session.execute(select(Student).where(Student.is_test == False).order_by(Student.id))).scalars().all()  # noqa: E712
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "Імʼя", "Instagram", "Telegram", "Пакет", "Сума", "Дата оплати", "Країна", "Часовий пояс",
                "Куратор", "Джерело", "Статус", "Допродажі", "Дзвінків", "Код", "Активовано"])
    now = utcnow()
    for r in rows:
        w.writerow([r.id, r.name, r.instagram, f"@{r.tg_username}" if r.tg_username else r.tg_id or "", r.package, r.amount,
                    fmt_date(r.paid_at), r.country, r.tz, await staff_name(session, r.curator_tg_id), r.source,
                    status_of(r.paid_at, now, r.extra_days, r.blocked), r.upsell, r.calls_used, r.code, "так" if r.tg_id else "ні"])
    await message.answer_document(BufferedInputFile(buf.getvalue().encode("utf-8-sig"), filename="machina_students.csv"))


# ───────── команда ─────────
@router.message(Command("staff"), IsAdmin())
async def cmd_staff(message: Message, session):
    rows = (await session.execute(select(Staff))).scalars().all()
    await message.answer("\n".join(f"{s.tg_id} · {esc(s.name)} · {s.role}{' · admin' if s.is_admin else ''}" for s in rows) or "Порожньо")


@router.message(Command("addstaff"), IsAdmin())
async def cmd_addstaff(message: Message, command: CommandObject, session, bot: Bot):
    parts = (command.args or "").split()
    try:
        tg, role = int(parts[0]), parts[1]
        assert role in ("manager", "curator", "valeria")
        is_admin = parts[-1] == "admin"
        name = " ".join(parts[2:-1] if is_admin else parts[2:])
    except Exception:
        return await message.answer("Використання: /addstaff <tg_id> <manager|curator|valeria> <імʼя> [admin]")
    row = await session.get(Staff, tg)
    if row:
        row.role, row.name, row.is_admin = role, name, is_admin
    else:
        session.add(Staff(tg_id=tg, role=role, name=name, is_admin=is_admin))
    await session.commit()
    await apply_commands(bot)
    await message.answer("✅ Додано. Людина має написати боту /start, щоб бот міг їй писати.")


@router.message(Command("rmstaff"), IsAdmin())
async def cmd_rmstaff(message: Message, command: CommandObject, session):
    try:
        await session.execute(delete(Staff).where(Staff.tg_id == int(command.args.strip())))
    except Exception:
        return await message.answer("Використання: /rmstaff <tg_id>")
    await message.answer("✅ Видалено")


# ───────── контент ─────────
def _extract(m: Message):
    if m.video:
        return "video", m.video.file_id, m.video.file_name or ""
    if m.document:
        return "document", m.document.file_id, m.document.file_name or ""
    if m.audio:
        return "audio", m.audio.file_id, m.audio.file_name or m.audio.title or ""
    if m.voice:
        return "voice", m.voice.file_id, ""
    if m.photo:
        return "photo", m.photo[-1].file_id, ""
    return None


def _auto(ftype: str, text: str):
    low = text.lower()
    if "таблиц" in low or "table" in low or "tablic" in low:
        return 0, 0, "table"
    m = re.search(r"(?:урок|urok|lesson|l)[\s_\-]*0*(\d{1,2})", low)
    if not m:
        return None
    n = int(m.group(1))
    if ftype == "video":
        kind = "video"
    elif ftype in ("audio", "voice"):
        kind = "audio"
    elif any(w in low for w in ("шпарг", "shparg", "cheat")):
        kind = "cheatsheet"
    elif any(w in low for w in ("місі", "місій", "missi", "mission")):
        kind = "missions"
    elif any(w in low for w in ("розбір", "razbir", "answer", "key")):
        kind = "answers"
    elif any(w in low for w in ("вправ", "exerc", "practice")):
        kind = "exercises"
    else:
        kind = "lesson"
    return (n + 1) // 2, n, kind


# ───────── майстер «Додати матеріали» (поетапно, одним повідомленням) ─────────
SLOTS = [("lesson", "📄 PDF уроку"), ("video", "🎬 Відео"), ("audio", "🎧 Аудіо"), ("missions", "🎯 Місії від Марка"),
         ("exercises", "✏️ Вправи"), ("answers", "🔑 Розбір"), ("cheatsheet", "🧾 Шпаргалка")]
SLOT_LABEL = dict(SLOTS)


async def _counts(session) -> dict:
    c: dict = {}
    for r in (await session.execute(select(ContentItem))).scalars():
        c[(r.lesson, r.kind)] = c.get((r.lesson, r.kind), 0) + 1
    return c


def _bar(done: int, total: int, n: int = 10) -> str:
    k = round(n * done / total) if total else 0
    return "▰" * k + "▱" * (n - k)


async def _view_pick(session):
    c = await _counts(session)
    total = 10 * len(SLOTS)
    done = sum(1 for n in range(1, 11) for k, _ in SLOTS if c.get((n, k)))
    kb = InlineKeyboardBuilder()
    for n in range(1, 11):
        have = sum(1 for k, _ in SLOTS if c.get((n, k)))
        kb.button(text=f"{'✅' if have == len(SLOTS) else '📘'} Урок {n} · {have}/{len(SLOTS)}", callback_data=f"w:l:{n}")
    kb.button(text=f"{'✅' if c.get((0, 'table')) else '🗂'} Таблиця часів", callback_data="w:t")
    kb.button(text="✅ Готово", callback_data="w:done")
    kb.adjust(2, 2, 2, 2, 2, 1, 1)
    text = (f"📥 <b>Матеріали курсу</b>\n{_bar(done, total)}  {done} з {total}\n\n"
            "Обери урок 👇\n<i>Або просто кидай файли з назвою на кшталт «Урок 3 …» — я сама розкладу.</i>")
    return text, kb.as_markup()


async def _view_lesson(session, n: int):
    c = await _counts(session)
    kb = InlineKeyboardBuilder()
    lines = [f"📘 <b>Урок {n}</b> — що вже є", ""]
    for k, label in SLOTS:
        cnt = c.get((n, k), 0)
        lines.append(f"{'✅' if cnt else '▫️'} {label}" + (f" · {cnt}" if cnt > 1 else ""))
        kb.button(text=f"{'🔄' if cnt else '➕'} {label}", callback_data=f"w:s:{n}:{k}")
    lines += ["", "Тисни на пункт і надсилай файл. Або кидай файли одразу — я підберу місце сама."]
    kb.button(text="⬅ До уроків", callback_data="w:pick")
    if n < 10:
        kb.button(text=f"Урок {n + 1} ➡", callback_data=f"w:l:{n + 1}")
    kb.adjust(1, 1, 1, 1, 1, 1, 1, 2)
    return "\n".join(lines), kb.as_markup()


def _view_slot(n: int, kind: str, have: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово — назад до уроку" if n else "✅ Готово", callback_data=f"w:l:{n}" if n else "w:pick")
    where = "🗂 Таблиця часів" if kind == "table" else f"Урок {n} · {SLOT_LABEL[kind]}"
    note = f"\n<i>Зараз завантажено: {have}. Новий файл замінить старий; кілька підряд — додадуться.</i>" if have else \
        "\n<i>Можна надіслати кілька файлів підряд.</i>"
    return f"📤 <b>{where}</b>\nНадішли файл сюди 👇{note}", kb.as_markup()


async def _render(bot: Bot, session, state: FSMContext, view: str, n: int = 0, kind: str = "") -> None:
    d = await state.get_data()
    if view == "pick":
        text, kb = await _view_pick(session)
    elif view == "lesson":
        text, kb = await _view_lesson(session, n)
    else:
        c = await _counts(session)
        text, kb = _view_slot(n, kind, c.get((n, kind), 0))
    try:
        await bot.edit_message_text(text, chat_id=d["cid"], message_id=d["mid"], reply_markup=kb)
    except Exception:
        pass  # «message is not modified» тощо


async def _start_wizard(target: Message, session, state: FSMContext) -> None:
    text, kb = await _view_pick(session)
    m = await target.answer(text, reply_markup=kb)
    await state.set_state(Upload.files)
    await state.update_data(mid=m.message_id, cid=m.chat.id, lesson=None, slot=None, replace=False)


@router.message(Command("upload"), IsAdmin())
async def cmd_upload(message: Message, session, state: FSMContext):
    await _start_wizard(message, session, state)


@router.message(Command("done"), IsStaff())
async def cmd_done(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Готово 👌")


def _guess_kind(ftype: str, text: str, have: dict, lesson: int) -> str:
    low = text.lower()
    if ftype == "video":
        return "video"
    if ftype in ("audio", "voice"):
        return "audio"
    if any(w in low for w in ("шпарг", "shparg", "cheat")):
        return "cheatsheet"
    if any(w in low for w in ("місі", "місій", "missi", "mission")):
        return "missions"
    if any(w in low for w in ("розбір", "razbir", "answer", "key")):
        return "answers"
    if any(w in low for w in ("вправ", "exerc", "practice")):
        return "exercises"
    for k in ("lesson", "exercises", "answers"):  # перший порожній документний слот
        if not have.get((lesson, k)):
            return k
    return "lesson"


@router.message(Upload.files, IsAdmin())
async def upload_file(message: Message, session, bot: Bot, state: FSMContext):
    ex = _extract(message)
    if not ex:
        return await message.answer("Це не файл 🤔 Надішли PDF, відео чи аудіо (краще <i>як файл</i>) або тисни «Готово» вище.")
    ftype, fid, fname = ex
    d = await state.get_data()
    caption = message.caption or ""
    lesson, slot = d.get("lesson"), d.get("slot")
    c = await _counts(session)
    if slot:                                   # обрано конкретний слот
        kind = slot
    elif lesson:                               # обрано урок — підбираю слот
        kind = _guess_kind(ftype, f"{fname} {caption}", c, lesson)
    else:                                      # нічого не обрано — шукаю за назвою
        res = _auto(ftype, f"{fname} {caption}")
        if not res:
            return await message.answer("Не зрозуміла, до якого уроку це 🤔 Обери урок кнопкою в повідомленні вище 👆")
        _, lesson, kind = res
    if kind == "table":
        lesson = 0
    if d.get("replace") and slot:
        await session.execute(delete(ContentItem).where(ContentItem.lesson == lesson, ContentItem.kind == kind))
        await state.update_data(replace=False)
    title = caption or re.sub(r"\.[A-Za-z0-9]{2,4}$", "", fname).replace("_", " ").replace("MCh ", "").strip()
    session.add(ContentItem(block=(lesson + 1) // 2 if lesson else 0, lesson=lesson, kind=kind,
                            title=(title or SLOT_LABEL.get(kind, "Таблиця часів"))[:300], file_id=fid, file_type=ftype))
    await session.flush()
    try:
        await message.react([ReactionTypeEmoji(emoji="👍")])
    except Exception:
        await message.answer(f"✓ Збережено: урок {lesson} · {kind}")
    if slot:
        await _render(bot, session, state, "slot", lesson, kind)
    elif lesson:
        await _render(bot, session, state, "lesson", lesson)
    else:
        await _render(bot, session, state, "pick")


@router.message(Upload.files, IsAdmin(), F.text)
async def upload_text(message: Message):
    await message.answer("Тут чекаю файли 📎 Обери урок кнопками вище 👆 Вийти — «Готово».")


@router.callback_query(F.data.startswith("w:"), IsAdmin())
async def cb_wizard(cb: CallbackQuery, session, bot: Bot, state: FSMContext):
    parts = cb.data.split(":")
    await cb.answer()
    await state.set_state(Upload.files)
    await state.update_data(mid=cb.message.message_id, cid=cb.message.chat.id)
    act = parts[1]
    if act == "pick":
        await state.update_data(lesson=None, slot=None, replace=False)
        await _render(bot, session, state, "pick")
    elif act == "l":
        n = int(parts[2])
        await state.update_data(lesson=n, slot=None, replace=False)
        await _render(bot, session, state, "lesson", n)
    elif act == "s":
        n, kind = int(parts[2]), parts[3]
        await state.update_data(lesson=n, slot=kind, replace=True)
        await _render(bot, session, state, "slot", n, kind)
    elif act == "t":
        await state.update_data(lesson=0, slot="table", replace=True)
        await _render(bot, session, state, "slot", 0, "table")
    elif act == "done":
        await state.clear()
        await cb.message.edit_text(await _coverage(session) + "\n\nГотово 👌 Повернутись: /admin")


@router.message(Command("content"), IsAdmin())
async def cmd_content(message: Message, command: CommandObject, session):
    q = select(ContentItem).order_by(ContentItem.lesson, ContentItem.id)
    if command.args and command.args.strip().isdigit():
        q = q.where(ContentItem.lesson == int(command.args.strip()))
    rows = (await session.execute(q)).scalars().all()
    await message.answer("\n".join(f"#{r.id} · урок {r.lesson} · {r.kind} · {esc(r.title)}" for r in rows)[:4000] or "Контенту ще нема.")


@router.message(Command("delcontent"), IsAdmin())
async def cmd_delcontent(message: Message, command: CommandObject, session):
    try:
        await session.execute(delete(ContentItem).where(ContentItem.id == int(command.args.strip())))
    except Exception:
        return await message.answer("Використання: /delcontent <id>")
    await message.answer("✅ Видалено")


# ───────── тексти й стікери ─────────
@router.message(Command("texts"), IsAdmin())
async def cmd_texts(message: Message):
    keys = "\n".join(f"<code>{k}</code>" for k in T.DEFAULTS)
    await message.answer(f"Ключі текстів (змінити: /settext ключ):\n{keys}"[:4000])


@router.message(Command("settext"), IsAdmin())
async def cmd_settext(message: Message, command: CommandObject, state: FSMContext):
    key = (command.args or "").strip()
    if key not in T.DEFAULTS:
        return await message.answer("Невідомий ключ. Список — /texts")
    await state.set_state(SetText.value)
    await state.update_data(key=key)
    await message.answer(f"Поточний текст:\n\n<code>{esc(T._overrides.get(key) or T.DEFAULTS[key])}</code>\n\n"
                         "Надішли новий (HTML і {плейсхолдери} можна, лише не видаляй їх). /cancel — скасувати.")


@router.message(SetText.value, IsAdmin(), F.text)
async def settext_value(message: Message, session, state: FSMContext):
    if message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer(T.tx("cancelled"))
    key = (await state.get_data())["key"]
    await state.clear()
    T.put_override(key, message.html_text)
    await set_setting(session, f"text:{key}", message.html_text)
    await message.answer("✅ Збережено. Дивись у боті.")


@router.message(Command("resettext"), IsAdmin())
async def cmd_resettext(message: Message, command: CommandObject, session):
    key = (command.args or "").strip()
    T.put_override(key, None)
    from ..db import Setting
    await session.execute(delete(Setting).where(Setting.key == f"text:{key}"))
    await message.answer("✅ Повернула стандартний текст.")


@router.message(Command("setsticker"), IsAdmin())
async def cmd_setsticker(message: Message, command: CommandObject, state: FSMContext):
    ev = (command.args or "").strip()
    if ev not in T.STICKER_EVENTS:
        return await message.answer("Події:\n" + "\n".join(f"<code>{k}</code> — {v}" for k, v in T.STICKER_EVENTS.items())
                                    + "\n\nПриклад: /setsticker welcome, потім надішли стікер.")
    await state.set_state(SetSticker.wait)
    await state.update_data(ev=ev)
    await message.answer("Надішли стікер 👇 (/cancel — скасувати)")


@router.message(SetSticker.wait, IsAdmin())
async def setsticker_value(message: Message, session, state: FSMContext):
    if not message.sticker:
        await state.clear()
        return await message.answer(T.tx("cancelled"))
    ev = (await state.get_data())["ev"]
    await state.clear()
    await set_setting(session, f"sticker:{ev}", message.sticker.file_id)
    await message.answer(f"✅ Стікер для «{T.STICKER_EVENTS[ev]}» збережено.")


# ───────── розсилка ─────────
@router.message(Command("broadcast"), IsAdmin())
async def cmd_broadcast(message: Message, command: CommandObject, session, state: FSMContext):
    parts = (command.args or "").split(maxsplit=1)
    if not parts:
        return await message.answer("Використання: /broadcast [all|self|curator|valeria] текст")
    target, text = ("all", command.args) if parts[0] not in (*PACKAGES, "all") else (parts[0], parts[1] if len(parts) > 1 else "")
    q = select(Student).where(Student.tg_id.is_not(None), Student.blocked == False, Student.is_test == False)  # noqa: E712
    if target != "all":
        q = q.where(Student.package == target)
    ids = [s.tg_id for s in (await session.execute(q)).scalars() if access_state(s) == "ok"]
    await state.set_state(Broadcast.confirm)
    await state.update_data(ids=ids, text=text)
    kb = InlineKeyboardBuilder()
    kb.button(text=f"✅ Надіслати ({len(ids)})", callback_data="bc:yes")
    kb.button(text="✖ Скасувати", callback_data="bc:no")
    await message.answer(f"Отримувачів: {len(ids)}\n\n{text}", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("bc:"), IsAdmin())
async def cb_broadcast(cb: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    if cb.data == "bc:no" or not data.get("ids"):
        await cb.message.answer(T.tx("cancelled"))
        return await cb.answer()
    import asyncio
    ok = 0
    for tid in data["ids"]:
        ok += await safe_send(bot, tid, data["text"], protect_content=True)
        await asyncio.sleep(0.05)
    await cb.message.answer(f"✅ Надіслано: {ok}/{len(data['ids'])}")
    await cb.answer()


# ───────── відповідь персоналу студенту (реплай) ─────────
@router.message(RelayReply())
async def staff_reply(message: Message, relay: Relay, session, bot: Bot):
    st = await session.get(Student, relay.student_id)
    if not st or not st.tg_id:
        return await message.answer("Студент ще не активував бот 🤔")
    label = {"hw": "💬 Відповідь на домашку", "support": "💬 Підтримка", "call": "📞 Щодо дзвінка",
             "feedback": "💜 Дякуємо за відгук"}.get(relay.kind, "💬")
    await bot.send_message(st.tg_id, f"<b>{label}</b>")
    await bot.copy_message(st.tg_id, message.chat.id, message.message_id)
    try:
        await message.react([ReactionTypeEmoji(emoji="👍")])
    except Exception:
        await message.answer("✓ Надіслано")
