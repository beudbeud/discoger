from types import SimpleNamespace

from discoger import utils
from discoger.client import Discoger
from discoger.database import UserDatabases


class Bot:
    def __init__(self, fail_markdown=False):
        self.fail_markdown = fail_markdown
        self.sent = []

    def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        if self.fail_markdown and parse_mode:
            raise Exception("Bad Request: can't parse entities")
        self.sent.append((chat_id, text, parse_mode))


def test_lock_same_for_int_and_str(tmp_path):
    dbs = UserDatabases(tmp_path)
    assert dbs.lock(123) is dbs.lock("123")


def test_send_msg_falls_back_to_plain_text():
    bot = Bot(fail_markdown=True)
    assert utils.send_msg(bot, 1, "Some_Artist") is True
    assert bot.sent == [(1, "Some_Artist", None)]


def test_send_msg_failure_is_not_a_block():
    class Broken:
        def send_message(self, **kwargs):
            raise Exception("network down")

    assert utils.send_msg(Broken(), 1, "x") is None


def make_client(tmp_path, allow_registration):
    client = Discoger.__new__(Discoger)  # skip __init__: it needs config and network
    client.bot = Bot()
    client.dbs = UserDatabases(tmp_path)
    client.allow_registration = allow_registration
    return client


def test_closed_registration_blocks_only_new_chats(tmp_path):
    client = make_client(tmp_path, allow_registration=False)
    db = client.dbs.open(1)
    db["release_list"] = []
    db.save()
    calls = []
    handler = client._guard(lambda message: calls.append(message.chat.id))

    handler(SimpleNamespace(chat=SimpleNamespace(id=1)))
    handler(SimpleNamespace(chat=SimpleNamespace(id=2)))

    assert calls == [1]
    assert client.bot.sent[0][0] == 2
    assert not client.dbs.exists(2)


def test_open_registration_lets_new_chats_in(tmp_path):
    client = make_client(tmp_path, allow_registration=True)
    calls = []
    client._guard(lambda message: calls.append(message.chat.id))(SimpleNamespace(chat=SimpleNamespace(id=2)))
    assert calls == [2]
