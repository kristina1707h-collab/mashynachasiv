from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import String, Integer, DateTime, Boolean, Text, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from app.config import settings

if settings.database_url.startswith("sqlite+aiosqlite:///./"):
    Path("./data").mkdir(exist_ok=True)

engine = create_async_engine(settings.database_url, future=True)
Session = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    package: Mapped[str | None] = mapped_column(String(30), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_code: Mapped[str] = mapped_column(String(64), unique=True)
    curator_telegram_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="lead")
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(255), unique=True)
    telegram_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    package: Mapped[str] = mapped_column(String(30))
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Homework(Base):
    __tablename__ = "homework"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(Integer)
    lesson: Mapped[str | None] = mapped_column(String(50), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))
    telegram_message_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_student(telegram_id: int, session: AsyncSession):
    res = await session.execute(select(Student).where(Student.telegram_id == telegram_id))
    return res.scalar_one_or_none()
