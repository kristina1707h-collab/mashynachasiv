import sys, os, re, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import datetime, timedelta
from app.course import *

P = datetime(2026, 11, 13, 12, 0)


def test_blocks_open_by_week():
    assert open_blocks(P, P) == [1]
    assert open_blocks(P, P + timedelta(days=7)) == [1, 2]
    assert open_blocks(P, P + timedelta(days=28)) == [1, 2, 3, 4, 5]


def test_due_events_schedule():
    assert due_events(P, P, 0, True) == []
    d7 = due_events(P, P + timedelta(days=7), 0, False)
    assert "block_open:2" in d7 and not any(k.startswith("call") for k in d7)
    assert "call:1" in due_events(P, P + timedelta(days=6), 0, True)
    assert "bonus" in due_events(P, P + timedelta(days=35), 0, False)
    assert "remind_end:0" in due_events(P, P + timedelta(days=80), 0, False)
    assert "expired:0" in due_events(P, P + timedelta(days=90), 0, False)


def test_extension_moves_end():
    assert not is_expired(P, P + timedelta(days=91), 30)
    assert is_expired(P, P + timedelta(days=121), 30)
    assert "remind_end:30" in due_events(P, P + timedelta(days=110), 30, False)


def test_prices_and_packages():
    change = datetime(2026, 12, 1, 22, 0)
    assert price_for("self", datetime(2026, 11, 20), change) == 1890
    assert price_for("valeria", datetime(2026, 12, 3), change) == 19990
    assert package_by_amount(7490) == "curator" and package_by_amount(9990) == "curator"
    assert has_support("curator") and not has_support("self")


def test_status():
    assert status_of(P, P, 0, False) == "навчається"
    assert status_of(P, P + timedelta(days=36), 0, False) == "бонус-тиждень"
    assert status_of(P, P + timedelta(days=95), 0, False) == "завершив"
    assert status_of(P, P + timedelta(days=95), 30, False) == "продовжив"


def test_lesson_code():
    assert [lesson_code(n) for n in (1, 2, 3, 4, 9, 10)] == ["1.1", "1.2", "2.1", "2.2", "5.1", "5.2"]


def test_answers_next_day():
    # 12:00 за Києвом (зима, UTC+2) = 10:00 UTC → розбір завтра о 10:00 за Києвом = 08:00 UTC
    done = datetime(2026, 11, 24, 10, 0)
    assert answers_due_at(done) == datetime(2026, 11, 25, 8, 0)
    # пізній вечір: 23:30 за Києвом → теж «наступного дня» о 10:00
    assert answers_due_at(datetime(2026, 11, 24, 21, 30)) == datetime(2026, 11, 25, 8, 0)
    # тестовий акаунт — за кілька хвилин
    assert answers_due_at(done, is_test=True) == done + timedelta(minutes=TEST_ANSWERS_MINUTES)


def test_text_keys_exist():
    os.environ.setdefault("BOT_TOKEN", "x")
    from app.texts import DEFAULTS
    used = set()
    for f in glob.glob(os.path.join(os.path.dirname(__file__), "..", "app", "**", "*.py"), recursive=True):
        used |= set(re.findall(r'tx\(\s*"([a-z_]+)"', open(f).read()))
    used |= {"welcome"}
    assert used <= set(DEFAULTS), used - set(DEFAULTS)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
