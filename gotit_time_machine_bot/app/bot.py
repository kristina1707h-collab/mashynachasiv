from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.enums import ChatMemberStatus
from sqlalchemy import select

from app.config import settings
from app.db import Session, Student, Homework
from app.access import is_active, current_day, unlocked_block, package_label
from app.keyboards import start_kb, lesson_kb
from app.content import CONTENT

router = Router()

async def touch(student):
    student.last_activity_at = datetime.now(timezone.utc)

async def get_student_by_code(code: str):
    async with Session() as s:
        r = await s.execute(select(Student).where(Student.access_code == code))
        return r.scalar_one_or_none()

def welcome_text(student):
    return (
        "🎟 <b>Ласкаво просимо в «Машину часів»!</b>\\n\\n"
        "Тут англійські часи складаються в одну систему — без хаосу й зубріння.\\n\\n"
        f"Твій пакет: <b>{package_label(student.package)}</b>\\n"
        f"Доступ до: <b>{student.access_until.strftime('%d.%m.%Y') if student.access_until else '—'}</b>\\n\\n"
        "Обирай, куди рухатися 👇"
    )

@router.message(CommandStart())
async def start(message: Message, bot: Bot):
    args = message.text.split(maxsplit=1)
    code = args[1] if len(args) > 1 else None

    async with Session() as s:
        student = None
        if code:
            r = await s.execute(select(Student).where(Student.access_code == code))
            student = r.scalar_one_or_none()
            if student and not student.telegram_id:
                student.telegram_id = message.from_user.id
                student.telegram_username = message.from_user.username
                student.active = True
                student.status = "навчається"
        if not student:
            r = await s.execute(select(Student).where(Student.telegram_id == message.from_user.id))
            student = r.scalar_one_or_none()

        if not student or not is_active(student):
            await message.answer(
                "Привіт! 👋\\n\\n"
                "«Машина часів» відкривається після оплати.\\n"
                "Якщо ти вже оплатив(-ла), напиши менеджерці, щоб отримати персональне посилання.",
            )
            return
        await touch(student)
        await s.commit()
        await message.answer(welcome_text(student), reply_markup=start_kb(), parse_mode="HTML")

@router.message(Command("menu"))
async def menu(message: Message):
    async with Session() as s:
        r = await s.execute(select(Student).where(Student.telegram_id == message.from_user.id))
        student = r.scalar_one_or_none()
        if not student or not is_active(student):
            await message.answer("🔒 Доступ не активний. Напиши менеджерці.")
            return
        await touch(student)
        await s.commit()
        await message.answer(welcome_text(student), reply_markup=start_kb(), parse_mode="HTML")

@router.callback_query(F.data == "start_info")
async def start_info(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer(
        "🧭 <b>Як проходити курс</b>\\n\\n"
        "1. Відкривай поточний блок.\\n"
        "2. Дивись пояснення та проходь вправи.\\n"
        "3. Після уроків заповнюй свою таблицю часів.\\n"
        "4. Наприкінці блоку — тест.\\n\\n"
        "No pressure. Просто повертайся до англійської регулярно 💜",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "lessons")
async def lessons(cb: CallbackQuery):
    await cb.answer()
    async with Session() as s:
        r = await s.execute(select(Student).where(Student.telegram_id == cb.from_user.id))
        student = r.scalar_one_or_none()
        if not student or not is_active(student):
            await cb.message.answer("🔒 Доступ не активний.")
            return
        unlocked = [i for i in range(1, 6) if unlocked_block(student, i)]
        if current_day(student) >= 35:
            unlocked.append(6)
        await cb.message.answer(
            f"📚 <b>Мої уроки</b>\\nДень курсу: {current_day(student)}",
            reply_markup=lesson_kb(unlocked),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("block:"))
async def block(cb: CallbackQuery, bot: Bot):
    await cb.answer()
    n = int(cb.data.split(":")[1])
    async with Session() as s:
        r = await s.execute(select(Student).where(Student.telegram_id == cb.from_user.id))
        student = r.scalar_one_or_none()
        if not student or not unlocked_block(student, n):
            await cb.message.answer("🔒 Цей блок ще не відкрився.")
            return
        block = CONTENT.get(f"block_{n}")
        await cb.message.answer(block["title"])
        for item in block.get("items", []):
            kind = item["type"]
            caption = item.get("caption", "")
            if kind == "text":
                await cb.message.answer(caption, protect_content=True)
            elif kind == "pdf":
                await cb.message.answer_document(item["file_id"], caption=caption, protect_content=True)
            elif kind == "video":
                await cb.message.answer_video(item["file_id"], caption=caption, protect_content=True)
            elif kind == "audio":
                await cb.message.answer_audio(item["file_id"], caption=caption, protect_content=True)
        await cb.message.answer("Готово 💜 Повернутися до уроків →", reply_markup=lesson_kb(list(range(1, min(6, n+1)+1))))

@router.callback_query(F.data == "table")
async def table(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer(
        "🗂 <b>Таблиця часів</b>\\n\\n"
        "Після кожного уроку заповнюй свою таблицю: назва часу → формула → коли використовуємо → приклад.\\n\\n"
        "Завантаж шаблон у content/blocks.json або заміни цю кнопку на реальний PDF.",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "homework")
async def homework(cb: CallbackQuery):
    await cb.answer()
    async with Session() as s:
        r = await s.execute(select(Student).where(Student.telegram_id == cb.from_user.id))
        student = r.scalar_one_or_none()
        if not student or student.package == "self":
            await cb.message.answer("У твоєму пакеті немає перевірки домашок 💜")
            return
        await cb.message.answer("📩 Надішли наступним повідомленням файл, фото, текст або голосове. Я передам його закріпленому куратору.")

@router.message(F.content_type.in_({"text", "photo", "document", "voice"}))
async def receive_homework(message: Message, bot: Bot):
    if message.text and message.text.startswith("/"):
        return
    async with Session() as s:
        r = await s.execute(select(Student).where(Student.telegram_id == message.from_user.id))
        student = r.scalar_one_or_none()
        if not student or not is_active(student) or student.package == "self":
            return
        if message.photo:
            kind = "photo"
        elif message.document:
            kind = "document"
        elif message.voice:
            kind = "voice"
        else:
            kind = "text"
        hw = Homework(
            student_id=student.id,
            lesson="current",
            kind=kind,
            telegram_message_id=message.message_id,
            created_at=datetime.now(timezone.utc),
        )
        s.add(hw)
        await s.commit()

        target = student.curator_telegram_id
        if not target and student.package == "valeria":
            target = next(iter(settings.admins), None)

        if target:
            await bot.forward_message(chat_id=target, from_chat_id=message.chat.id, message_id=message.message_id)
            await bot.send_message(target, f"📩 Homework від {student.name or message.from_user.full_name} | package={student.package}")
            await message.answer("Прийнято 💜 Я передав(-ла) домашку куратору.")
        else:
            await message.answer("Домашку збережено, але куратор ще не закріплений. Напиши менеджерці.")

@router.callback_query(F.data == "call")
async def call(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("📞 Запис на дзвінок буде доступний наприкінці кожного блоку. Підключіть календар куратора в цьому місці.")

@router.callback_query(F.data == "support")
async def support(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("💬 Якщо питання про оплату, доступ або техніку — напиши менеджерці GOTIt School.")

@router.callback_query(F.data == "more")
async def more(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("⭐ Тут можна додати робочий зошит, продовження доступу та інші продукти GOTIt School.")

@router.message(Command("status"))
async def status(message: Message):
    async with Session() as s:
        r = await s.execute(select(Student).where(Student.telegram_id == message.from_user.id))
        student = r.scalar_one_or_none()
        if not student:
            await message.answer("Студента не знайдено.")
            return
        await message.answer(
            f"Пакет: {package_label(student.package)}\\n"
            f"День: {current_day(student)}\\n"
            f"Активний: {'так' if is_active(student) else 'ні'}\\n"
            f"До: {student.access_until.strftime('%d.%m.%Y') if student.access_until else '—'}"
        )

def setup_dispatcher():
    dp = Dispatcher()
    dp.include_router(router)
    return dp
