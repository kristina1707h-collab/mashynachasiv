import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from aiogram import Bot
from aiogram.types import BotCommand
from app.config import settings
from app.db import init_db
from app.bot import setup_dispatcher
from app.admin import router as admin_router

bot = Bot(settings.bot_token)
dp = setup_dispatcher()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустити / відкрити курс"),
        BotCommand(command="menu", description="Головне меню"),
        BotCommand(command="status", description="Мій доступ"),
        BotCommand(command="support", description="Підтримка"),
    ])
    yield
    await bot.session.close()

app = FastAPI(title="GOTIt School — Машина часів", lifespan=lifespan)
app.include_router(admin_router)

@app.get("/health")
async def health():
    return {"ok": True, "service": "gotit-time-machine-bot"}

async def polling():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    if settings.polling:
        asyncio.run(polling())
    else:
        import uvicorn
        uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
