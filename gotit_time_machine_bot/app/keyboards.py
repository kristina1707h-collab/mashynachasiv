from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def start_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Старт", callback_data="start_info")],
        [InlineKeyboardButton(text="📚 Мої уроки", callback_data="lessons")],
        [InlineKeyboardButton(text="🗂 Таблиця часів", callback_data="table")],
        [InlineKeyboardButton(text="📩 Надіслати домашку", callback_data="homework")],
        [InlineKeyboardButton(text="📞 Мій дзвінок", callback_data="call")],
        [InlineKeyboardButton(text="💬 Підтримка", callback_data="support")],
        [InlineKeyboardButton(text="⭐ Ще більше", callback_data="more")],
    ])

def lesson_kb(unlocked: list[int]):
    rows = []
    for n in unlocked:
        rows.append([InlineKeyboardButton(text=f"Блок {n}", callback_data=f"block:{n}")])
    if not rows:
        rows = [[InlineKeyboardButton(text="🔒 Поки що закрито", callback_data="locked")]]
    rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def access_help_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💜 Як отримати доступ", url="https://www.instagram.com/")],
    ])
