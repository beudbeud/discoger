import threading
from pathlib import Path

from yamldb.YamlDB import YamlDB


class UserDatabases:
    """Per-chat YAML databases, one file per chat_id, with per-chat locks."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._locks = {}
        self._mutex = threading.Lock()

    def lock(self, chat_id):
        with self._mutex:
            if chat_id not in self._locks:
                self._locks[chat_id] = threading.Lock()
            return self._locks[chat_id]

    def open(self, chat_id) -> YamlDB:
        return YamlDB(filename=str(self.directory / ("%s.yaml" % chat_id)))

    def delete(self, chat_id):
        with self.lock(chat_id):
            (self.directory / ("%s.yaml" % chat_id)).unlink(missing_ok=True)

    def chat_ids(self):
        return [p.stem for p in self.directory.glob("*.yaml")]
