"""Чиста логіка курсу (без залежностей): графік блоків, доступ, ціни, статуси."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

BLOCKS = 5
BLOCK_DAYS = 7
BONUS_DAY = 35
REMIND_DAY = 80
END_DAY = 90
CALL_PROMPT_DAY = 6  # на якій добі блоку бот пропонує дзвінок (кінець тижня)
CALLS_TOTAL = 5

PACKAGES = {
    "self": {"title": "Самостійний", "emoji": "🚀", "support": False, "launch": 1890, "regular": 2490},
    "curator": {"title": "З куратором", "emoji": "🤝", "support": True, "launch": 7490, "regular": 9990},
    "valeria": {"title": "З Валерією", "emoji": "⭐", "support": True, "launch": 16990, "regular": 19990},
}

_DATA = Path(__file__).resolve().parent.parent / "data"


def _load(name: str, default):
    try:
        return json.loads((_DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return default


COURSE = _load("course.json", {"blocks": {}})
QUIZZES = _load("quizzes.json", {})


def package_title(pkg: str) -> str:
    p = PACKAGES.get(pkg)
    return f"{p['emoji']} {p['title']}" if p else pkg


def has_support(pkg: str) -> bool:
    return bool(PACKAGES.get(pkg, {}).get("support"))


def block_lessons(b: int) -> list[int]:
    return [2 * b - 1, 2 * b]


def block_of_lesson(n: int) -> int:
    return (n + 1) // 2


def block_title(b: int) -> str:
    return COURSE.get("blocks", {}).get(str(b), {}).get("title") or f"Блок {b}"


def block_theme(b: int) -> str:
    return COURSE.get("blocks", {}).get(str(b), {}).get("theme") or ""


def lesson_title(n: int) -> str:
    return COURSE.get("blocks", {}).get(str(block_of_lesson(n)), {}).get("lessons", {}).get(str(n)) or f"Урок {n}"


def block_open_at(paid_at: datetime, b: int) -> datetime:
    return paid_at + timedelta(days=BLOCK_DAYS * (b - 1))


def open_blocks(paid_at: datetime, now: datetime) -> list[int]:
    return [b for b in range(1, BLOCKS + 1) if now >= block_open_at(paid_at, b)]


def access_end(paid_at: datetime, extra_days: int = 0) -> datetime:
    return paid_at + timedelta(days=END_DAY + extra_days)


def is_expired(paid_at: datetime, now: datetime, extra_days: int = 0) -> bool:
    return now >= access_end(paid_at, extra_days)


def day_number(paid_at: datetime, now: datetime) -> int:
    return max(0, (now - paid_at).days)


def due_events(paid_at: datetime, now: datetime, extra_days: int, support: bool) -> list[str]:
    """Ключі подій, які вже мали статись до моменту now (відправлені фільтруються поза цією функцією)."""
    keys: list[str] = []
    for b in range(2, BLOCKS + 1):
        if now >= block_open_at(paid_at, b):
            keys.append(f"block_open:{b}")
    if support:
        for b in range(1, BLOCKS + 1):
            if now >= block_open_at(paid_at, b) + timedelta(days=CALL_PROMPT_DAY):
                keys.append(f"call:{b}")
    if now >= paid_at + timedelta(days=BONUS_DAY):
        keys.append("bonus")
    if now >= paid_at + timedelta(days=REMIND_DAY + extra_days):
        keys.append(f"remind_end:{extra_days}")
    if now >= access_end(paid_at, extra_days):
        keys.append(f"expired:{extra_days}")
    return keys


def price_for(pkg: str, now: datetime, change_at: datetime) -> int:
    p = PACKAGES[pkg]
    return p["launch"] if now < change_at else p["regular"]


def package_by_amount(amount: int) -> str | None:
    for k, p in PACKAGES.items():
        if amount in (p["launch"], p["regular"]):
            return k
    return None


def status_of(paid_at: datetime, now: datetime, extra_days: int, blocked: bool) -> str:
    if blocked:
        return "заблоковано"
    if is_expired(paid_at, now, extra_days):
        return "завершив"
    if extra_days and now >= paid_at + timedelta(days=END_DAY):
        return "продовжив"
    if now >= paid_at + timedelta(days=BONUS_DAY):
        return "бонус-тиждень"
    return "навчається"
