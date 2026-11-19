from datetime import datetime, timedelta, timezone
import secrets

BLOCK_DAYS = {
    1: 0,
    2: 7,
    3: 14,
    4: 21,
    5: 28,
    6: 35,
}

def new_code() -> str:
    return secrets.token_urlsafe(18)

def is_active(student, now=None):
    now = now or datetime.now(timezone.utc)
    return bool(student.active and student.access_until and student.access_until > now)

def current_day(student, now=None) -> int:
    now = now or datetime.now(timezone.utc)
    if not student.paid_at:
        return -1
    paid = student.paid_at
    if paid.tzinfo is None:
        paid = paid.replace(tzinfo=timezone.utc)
    return max(0, (now.date() - paid.date()).days)

def unlocked_block(student, block_number: int, now=None) -> bool:
    if not is_active(student, now):
        return False
    return current_day(student, now) >= BLOCK_DAYS.get(block_number, 9999)

def access_until(paid_at):
    if paid_at.tzinfo is None:
        paid_at = paid_at.replace(tzinfo=timezone.utc)
    return paid_at + timedelta(days=90)

def package_label(package):
    return {
        "self": "🚀 Самостійний",
        "curator": "🤝 З куратором",
        "valeria": "⭐ З Валерією",
    }.get(package, package)
