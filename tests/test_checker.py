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


def test_cloudflare_aborts_after_five(tmp_path, monkeypatch):
    notify = Notifier()
    checker, dbs = make_checker(tmp_path, notify)
    seed(dbs, "111", [make_item(str(i)) for i in range(50)])

    def blocked(*a, **k):
        time.sleep(0.005)
        raise scrap.ScrapeError("403", cloudflare=True)

    monkeypatch.setattr(scrap, "check_sales", blocked)

    stats = checker.check_user("111")

    # parallel abort: pending checks are cancelled once 5 CF blocks are seen,
    # in-flight ones may still land, so the exact count is nondeterministic
    assert stats["cf_errors"] >= 5
    assert stats["checked"] < 50
    assert notify.sent == []


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
