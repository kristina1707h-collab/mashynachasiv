import hashlib
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")


def _ids(name: str) -> list[int]:
    raw = os.environ.get(name, "")
    return [int(x) for x in raw.replace(" ", "").split(",") if x.lstrip("-").isdigit()]


def _db_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgresql+asyncpg://"):
        p = urlsplit(url)
        q = [(k, v) for k, v in parse_qsl(p.query) if k not in ("sslmode", "ssl")]
        url = urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))
    return url


def _kyiv_to_utc_naive(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso).replace(tzinfo=KYIV)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class Settings:
    def __init__(self) -> None:
        e = os.environ.get
        self.BOT_TOKEN = e("BOT_TOKEN", "")
        self.BOT_USERNAME = e("BOT_USERNAME", "")
        self.DATABASE_URL = _db_url(e("DATABASE_URL", "sqlite+aiosqlite:///./machina.db"))
        self.ADMIN_IDS = _ids("ADMIN_IDS")
        self.BASE_URL = (e("WEBHOOK_BASE_URL") or e("RENDER_EXTERNAL_URL") or "").rstrip("/")
        self.USE_POLLING = e("USE_POLLING") == "1" or not self.BASE_URL
        self.PORT = int(e("PORT", "10000"))
        self.TG_SECRET = hashlib.sha256((self.BOT_TOKEN + ":machina").encode()).hexdigest()[:48]
        self.PAYMENT_WEBHOOK_SECRET = e("PAYMENT_WEBHOOK_SECRET", "")
        self.DIRECT_URL = e("DIRECT_URL", "")
        self.CALL_BOOKING_URL = e("CALL_BOOKING_URL", "")
        self.FEEDBACK_URL = e("FEEDBACK_URL", "")
        self.EXTEND_URL = e("EXTEND_URL", "")
        self.WORKBOOK_URL = e("WORKBOOK_URL", "")
        self.GRAMMAR_URL = e("GRAMMAR_URL", "")
        self.PRICE_CHANGE_AT_UTC = _kyiv_to_utc_naive(e("PRICE_CHANGE_AT", "2026-12-02T00:00"))
        self.VALERIA_SEATS_LIMIT = int(e("VALERIA_SEATS_LIMIT", "5"))
        self.QUIET_HOURS = e("QUIET_HOURS", "1") == "1"
        self.WATERMARK = e("WATERMARK_CAPTIONS", "1") == "1"
        self.ANSWERS_NEXT_DAY = e("ANSWERS_NEXT_DAY", "1") == "1"  # 1 = розбір приходить наступного дня, 0 = одразу


settings = Settings()
