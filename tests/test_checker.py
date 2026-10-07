import time

import pytest

from discoger import scrap
from discoger.checker import Checker
from discoger.database import UserDatabases


class Notifier:
    def __init__(self, blocked=False):
        self.sent = []
        self.blocked = blocked

    def __call__(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))
        return not self.blocked


def make_item(release_id="42", last_sell=None):
    return {
        "release_id": release_id,
        "artist": "Pink Floyd",
        "title": "Animals",
        "url": "https://www.discogs.com/release/%s" % release_id,
        "type": "release",
        "image": "https://img.discogs.com/x.jpg",
        "last_sell": last_sell or {},
    }


def make_checker(tmp_path, notify, **kwargs):
    dbs = UserDatabases(tmp_path)
    return Checker(d=None, dbs=dbs, notify=notify, pause=0, **kwargs), dbs


def seed(dbs, chat_id, items):
    db = dbs.open(chat_id)
    db["chat_id"] = int(chat_id)
    db["release_list"] = items
    db.save()


SELL = {
    "id": "99",
    "price": "EUR 10.00",
    "url": "https://www.discogs.com/sell/item/99",
    "media_condition": "VG+",
    "sleeve_condition": "NM",
    "shipping_from": "France",
}


def test_new_sell_notifies_and_saves(tmp_path, monkeypatch):
    notify = Notifier()
    checker, dbs = make_checker(tmp_path, notify)
    seed(dbs, "111", [make_item()])
    monkeypatch.setattr(scrap, "check_sales", lambda *a, **k: dict(SELL))
    monkeypatch.setattr(scrap, "get_suggestion_price", lambda d, rid: "12 EUR")

    stats = checker.check_user("111")

    assert stats == {"checked": 1, "errors": 0, "cf_errors": 0}
    assert len(notify.sent) == 1
    assert "EUR 10.00" in notify.sent[0][1]
    assert dbs.open("111")["release_list"][0]["last_sell"]["id"] == "99"


def test_known_sell_no_notification(tmp_path, monkeypatch):
    notify = Notifier()
    checker, dbs = make_checker(tmp_path, notify)
    seed(dbs, "111", [make_item(last_sell={"id": "100"})])
    monkeypatch.setattr(scrap, "check_sales", lambda *a, **k: dict(SELL))

    stats = checker.check_user("111")

    assert stats == {"checked": 1, "errors": 0, "cf_errors": 0}
    assert notify.sent == []
    assert dbs.open("111")["release_list"][0]["last_sell"]["id"] == "100"


def test_block_pauses_all_checks(tmp_path, monkeypatch):
    notify = Notifier()
    checker, dbs = make_checker(tmp_path, notify)
    seed(dbs, "111", [make_item(str(i)) for i in range(50)])
    seed(dbs, "222", [make_item("x")])

    def blocked(*a, **k):
        time.sleep(0.005)
        raise scrap.ScrapeError("403", cloudflare=True)

    monkeypatch.setattr(scrap, "check_sales", blocked)

    stats = checker.check_user("111")

    # first block cancels pending checks (an in-flight one may still land)
    # and rotates the profile
    assert 1 <= stats["cf_errors"] <= 2
    assert checker.blocked()
    assert checker._session_epoch == 1
    assert notify.sent == []
    # every later check is skipped until the cooldown ends
    assert checker.check_user("222")["checked"] == 0
    checker.blocked_until = 0
    assert checker.check_user("222")["checked"] == 1


def test_rate_limit_keeps_profile(tmp_path, monkeypatch):
    checker, dbs = make_checker(tmp_path, Notifier())
    seed(dbs, "111", [make_item()])

    def limited(*a, **k):
        raise scrap.ScrapeError("429", cloudflare=True, rate_limited=True)

    monkeypatch.setattr(scrap, "check_sales", limited)
    checker.check_user("111")
    assert checker.blocked()
    assert checker._session_epoch == 0


def test_blocked_user_db_removed(tmp_path, monkeypatch):
    notify = Notifier(blocked=True)
    checker, dbs = make_checker(tmp_path, notify)
    seed(dbs, "111", [make_item()])
    monkeypatch.setattr(scrap, "check_sales", lambda *a, **k: dict(SELL))
    monkeypatch.setattr(scrap, "get_suggestion_price", lambda d, rid: "12 EUR")

    checker.check_user("111")

    assert not (tmp_path / "111.yaml").exists()


def test_cycle_sends_admin_alert_on_errors(tmp_path, monkeypatch):
    notify = Notifier()
    checker, dbs = make_checker(tmp_path, notify, admin_chat_id="999")
    seed(dbs, "111", [make_item()])

    def broken(*a, **k):
        raise scrap.ScrapeError("boom")

    monkeypatch.setattr(scrap, "check_sales", broken)

    checker.check_cycle()

    assert len(notify.sent) == 1
    chat_id, text = notify.sent[0]
    assert chat_id == "999"
    assert "1/1" in text


def test_cycle_quiet_when_all_green(tmp_path, monkeypatch):
    notify = Notifier()
    checker, dbs = make_checker(tmp_path, notify, admin_chat_id="999")
    seed(dbs, "111", [make_item(last_sell={"id": "100"})])
    monkeypatch.setattr(scrap, "check_sales", lambda *a, **k: dict(SELL))

    checker.check_cycle()

    assert notify.sent == []


def test_renew_sessions_rotates_profile(tmp_path, monkeypatch):
    used = []
    monkeypatch.setattr("discoger.checker.new_session", lambda p: used.append(p) or p)
    checker, _ = make_checker(tmp_path, Notifier())
    for _ in range(4):
        checker._get_session()
        checker.renew_sessions()
    assert used == ["chrome", "safari", "chrome", "safari"]


def test_due_chat_ids_spreads_users(tmp_path):
    checker, dbs = make_checker(tmp_path, Notifier())
    for chat_id in ["100", "101", "-102"]:
        seed(dbs, chat_id, [make_item()])
    due = [checker.due_chat_ids(45, minute=m) for m in range(45)]
    # each user exactly once per interval, never all at the same minute
    assert sorted(c for d in due for c in d) == ["-102", "100", "101"]
    assert max(len(d) for d in due) == 1


def test_nothing_for_sale_skips_scrape(tmp_path, monkeypatch):
    checker, dbs = make_checker(tmp_path, Notifier())
    seed(dbs, "111", [make_item()])
    monkeypatch.setattr(scrap, "has_listings", lambda d, rid: False)

    def scraped(*a, **k):
        raise AssertionError("should not scrape")

    monkeypatch.setattr(scrap, "check_sales", scraped)
    assert checker.check_user("111") == {"checked": 1, "errors": 0, "cf_errors": 0}
