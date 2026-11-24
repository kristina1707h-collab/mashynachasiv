from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Staff(Base):
    __tablename__ = "staff"
    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), default="")
    role: Mapped[str] = mapped_column(String(20), default="curator")  # manager | curator | valeria
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    tg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    tg_username: Mapped[str] = mapped_column(String(64), default="")
    first_name: Mapped[str] = mapped_column(String(100), default="")
    name: Mapped[str] = mapped_column(String(100), default="")
    instagram: Mapped[str] = mapped_column(String(100), default="")
    package: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer, default=0)
    paid_at: Mapped[datetime] = mapped_column(DateTime)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    extra_days: Mapped[int] = mapped_column(Integer, default=0)
    curator_tg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    calls_used: Mapped[int] = mapped_column(Integer, default=0)
    country: Mapped[str] = mapped_column(String(60), default="")
    tz: Mapped[str] = mapped_column(String(60), default="")
    source: Mapped[str] = mapped_column(String(60), default="")
    upsell: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    bot_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def display(self) -> str:
        return self.name or self.first_name or (f"@{self.tg_username}" if self.tg_username else f"#{self.id}")


class ContentItem(Base):
    __tablename__ = "content"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block: Mapped[int] = mapped_column(Integer, default=0)
    lesson: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(20))  # lesson|video|audio|missions|exercises|answers|cheatsheet|table
    title: Mapped[str] = mapped_column(String(300), default="")
    file_id: Mapped[str] = mapped_column(String(300))
    file_type: Mapped[str] = mapped_column(String(20))  # document|video|audio|voice|photo
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SentLog(Base):
    __tablename__ = "sent_log"
    __table_args__ = (UniqueConstraint("student_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    key: Mapped[str] = mapped_column(String(60))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Relay(Base):
    """Зв'язок «повідомлення у чаті персоналу → студент», щоб відповідь-реплаєм доходила назад."""
    __tablename__ = "relay"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    student_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # hw|support|call|feedback
    ref: Mapped[str] = mapped_column(String(40), default="")


class Poll(Base):
    __tablename__ = "polls"
    poll_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    student_id: Mapped[int] = mapped_column(Integer)
    block: Mapped[int] = mapped_column(Integer)
    idx: Mapped[int] = mapped_column(Integer)
    correct: Mapped[int] = mapped_column(Integer)
    attempt: Mapped[str] = mapped_column(String(20))
    is_right: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)


class QuizResult(Base):
    __tablename__ = "quiz_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    block: Mapped[int] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Event(Base):
    """Журнал дій студента — для «Статусу» й підтримки."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(30))
    data: Mapped[str] = mapped_column(String(100), default="")
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
