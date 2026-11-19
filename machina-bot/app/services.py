from __future__ import annotations

import html
import secrets
from collections import Counter
from datetime import timedelta, timezone

from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from .config import KYIV, settings
from .course import (PACKAGES, block_open_at, day_number, has_support, open_blocks,
                     package_title, price_for, status_of, access_end, CALLS_TOTAL)
from .db import ContentItem, Event, Setting, SentLog, Staff, Student, utcnow

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
esc = html.escape


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(10))


def deep_link(code: str) -> str:
    return f"https://t.me/{settings.BOT_USERNAME}?start={code}"


def fmt_date(dt) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone(KYIV).strftime("%d.%m.%Y")


def fmt_dm(dt) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone(KYIV).strftime("%d.%m")


async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    row = await session.get(Setting, key)
    return row.value if row else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))


async def seats_limit(session: AsyncSession) -> int:
    return int(await get_setting(session, "valeria_seats", str(settings.VALERIA_SEATS_LIMIT)))


async def seats_taken(session: AsyncSession) -> int:
    q = select(func.count()).select_from(Student).where(
        Student.package == "valeria", Student.is_test == False, Student.blocked == False)  # noqa: E712
    return (await session.execute(q)).scalar_one()


async def pick_curator(session: AsyncSession, package: str) -> int | None:
    if package == "valeria":
        r = (await session.execute(select(Staff).where(Staff.role == "valeria").order_by(Staff.tg_id))).scalars().first()
        return r.tg_id if r else None
    if package == "curator":
        curators = (await session.execute(select(Staff).where(Staff.role == "curator"))).scalars().all()
        if not curators:
            return None
        loads = []
        for c in curators:
            n = (await session.execute(select(func.count()).select_from(Student).where(
                Student.curator_tg_id == c.tg_id, Student.is_test == False))).scalar_one()  # noqa: E712
            loads.append((n, c.tg_id))
        return min(loads)[1]
    return None


async def issue_student(session: AsyncSession, package: str, name: str = "", instagram: str = "",
                        amount: int | None = None, source: str = "", order_id: str | None = None,
                        is_test: bool = False, country: str = "") -> Student:
    now = utcnow()
    if amount is None:
        amount = price_for(package, now, settings.PRICE_CHANGE_AT_UTC)
    code = new_code()
    while (await session.execute(select(Student.id).where(Student.code == code))).first():
        code = new_code()
    st = Student(code=code, package=package, name=name, instagram=instagram, amount=amount,
                 paid_at=now, curator_tg_id=await pick_curator(session, package), source=source,
                 order_id=order_id, is_test=is_test, country=country)
    session.add(st)
    await session.flush()
    return st


async def staff_name(session: AsyncSession, tg_id: int | None) -> str:
    if not tg_id:
        return "—"
    s = await session.get(Staff, tg_id)
    return s.name or str(tg_id) if s else str(tg_id)


async def manager_ids(session: AsyncSession) -> list[int]:
    ids = [s.tg_id for s in (await session.execute(select(Staff).where(Staff.role == "manager"))).scalars()]
    return ids or settings.ADMIN_IDS


async def admin_ids(session: AsyncSession) -> list[int]:
    ids = [s.tg_id for s in (await session.execute(select(Staff).where(Staff.is_admin == True))).scalars()]  # noqa: E712
    return ids or settings.ADMIN_IDS


async def sent_keys(session: AsyncSession, sid: int) -> set[str]:
    return set((await session.execute(select(SentLog.key).where(SentLog.student_id == sid))).scalars())


async def mark_sent(session: AsyncSession, sid: int, key: str) -> None:
    if key not in await sent_keys(session, sid):
        session.add(SentLog(student_id=sid, key=key))
        await session.flush()


async def log_event(session: AsyncSession, sid: int, type_: str, data: str = "") -> None:
    session.add(Event(student_id=sid, type=type_, data=data))


KIND_ORDER = {"lesson": 0, "video": 1, "audio": 2, "exercises": 3, "answers": 4, "table": 5}


async def get_items(session: AsyncSession, lesson: int, kinds: tuple[str, ...]) -> list[ContentItem]:
    rows = (await session.execute(select(ContentItem).where(
        ContentItem.lesson == lesson, ContentItem.kind.in_(kinds)))).scalars().all()
    return sorted(rows, key=lambda r: (KIND_ORDER.get(r.kind, 9), r.id))


async def find_students(session: AsyncSession, q: str) -> list[Student]:
    q = q.strip().lstrip("@")
    if q.isdigit():
        n = int(q)
        r = (await session.execute(select(Student).where(or_(Student.id == n, Student.tg_id == n)))).scalars().all()
        if r:
            return list(r)
    like = f"%{q}%"
    r = (await session.execute(select(Student).where(or_(
        Student.name.ilike(like), Student.tg_username.ilike(like), Student.instagram.ilike(like),
        Student.code == q.upper())).limit(20))).scalars().all()
    return list(r)


async def student_card(session: AsyncSession, st: Student) -> str:
    now = utcnow()
    ob = open_blocks(st.paid_at, now)
    tg = (f"@{st.tg_username} · {st.tg_id}" if st.tg_username else str(st.tg_id)) if st.tg_id else f"не активовано · код <code>{st.code}</code>"
    return (
        f"👤 <b>{esc(st.display)}</b> · #{st.id}{' · 🧪 тест' if st.is_test else ''}\n"
        f"📦 {package_title(st.package)} · {st.amount} грн · оплата {fmt_date(st.paid_at)}\n"
        f"✈ {tg}\n"
        f"📷 {esc(st.instagram) or '—'} · 🌍 {esc(st.country) or '—'} {esc(st.tz)} · джерело: {esc(st.source) or '—'}\n"
        f"🎓 {status_of(st.paid_at, now, st.extra_days, st.blocked)} · день {day_number(st.paid_at, now)} · "
        f"відкрито блоків {len(ob)}/5 · доступ до {fmt_date(access_end(st.paid_at, st.extra_days))}\n"
        f"👩‍🏫 куратор: {esc(await staff_name(session, st.curator_tg_id))} · 📞 дзвінки {st.calls_used}/{CALLS_TOTAL}\n"
        f"🛒 допродажі: {esc(st.upsell) or '—'}" + (f"\n📝 {esc(st.notes)}" if st.notes else "")
    )


async def build_stats(session: AsyncSession) -> str:
    now = utcnow()
    rows = (await session.execute(select(Student).where(Student.is_test == False))).scalars().all()  # noqa: E712
    week = [r for r in rows if r.paid_at >= now - timedelta(days=7)]
    by_pkg = Counter(r.package for r in rows)
    by_pkg_w = Counter(r.package for r in week)
    status = Counter(status_of(r.paid_at, now, r.extra_days, r.blocked) for r in rows)
    pending = sum(1 for r in rows if not r.tg_id)
    lim, taken = await seats_limit(session), await seats_taken(session)
    load = Counter(r.curator_tg_id for r in rows if r.curator_tg_id)
    lines = ["📊 <b>Статистика «Машини часів»</b>", f"Усього оплат: {len(rows)} · за 7 днів: {len(week)}",
             f"Виручка: {sum(r.amount for r in rows)} грн (за 7 днів: {sum(r.amount for r in week)} грн)", ""]
    for k in PACKAGES:
        lines.append(f"{package_title(k)}: {by_pkg[k]} (за тиждень +{by_pkg_w[k]})")
    lines += ["", f"⭐ Вільних місць «З Валерією»: {max(0, lim - taken)} з {lim}",
              f"Не активували код: {pending}",
              "Статуси: " + (", ".join(f"{k} — {v}" for k, v in status.items()) or "—")]
    if load:
        lines.append("")
        lines.append("Навантаження кураторів:")
        for tid, n in load.most_common():
            lines.append(f"• {esc(await staff_name(session, tid))}: {n}")
    return "\n".join(lines)
