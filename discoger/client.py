#!/usr/bin/env python3

import configparser
import discogs_client
import logging
import threading
import schedule
import time
import re
import cloudscraper

from yamldb.YamlDB import YamlDB
from pathlib import Path
from time import sleep
from telebot import types, util, telebot
from discoger import scrap, utils


class Discoger:
    def __init__(self):
        self.home = str(Path.home())
        self.config_file = Path(self.home + "/.config/discoger/config.ini")
        self.database_dir = Path(self.home + "/.config/discoger/databases")
        self.discogs_url = "https://www.discogs.com"

        if self.config_file.exists():
            self.config = configparser.ConfigParser()
            self.config.read(self.config_file)
        else:
            logging.error("No config file, please create a config file follwing example")
            raise SystemExit()

        if not self.database_dir.exists():
            self.database_dir.mkdir(parents=True, exist_ok=True)

        self.token = self.config["telegram"]["token"]
        self.secret = self.config["discogs"]["secret"]
        self.disable_unofficial = self.config["DEFAULT"].getboolean(
            "disable_unofficial", fallback=True
        )
        self.bot = telebot.TeleBot(self.token)
        self.log_level = self.config["DEFAULT"].get("log_level", fallback="INFO")

        handler = logging.StreamHandler()
        handler.setFormatter(utils.CustomFormatter())
        logger = logging.getLogger()
        logger.addHandler(handler)
        logger.setLevel(self.log_level)

        self.commands = {
            "/start": "Get used to the bot",
            "/help": "Gives you information about the available commands",
            "/list": "Show all items in your following list",
            "/delete": "Delete item from the following list",
            "/wantlist": "Synchronize Discogs wantlist to following list",
            "https://www.discogs.com/release|master/.*": "Add release or master release in following list (ex: https://www.discogs.com/release/26741825)",
        }

        try:
            self.d = discogs_client.Client("DiscogsAlert/0.1", user_token=self.secret)
            self.me = self.d.identity()
        except discogs_client.exceptions.HTTPError as e:
            logging.error("Error: Unable to authenticate.")
            raise SystemExit(e)

        # Un lock par chat_id pour protéger les accès concurrents à YamlDB.
        # _db_locks_mutex protège le dict lui-même lors de la création de nouveaux locks.
        self._db_locks = {}
        self._db_locks_mutex = threading.Lock()

        self.http = cloudscraper.create_scraper()

        self._register_handlers()
        self._run()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def get_db_lock(self, chat_id):
        """Retourne le lock associé à un chat_id, en le créant si besoin."""
        with self._db_locks_mutex:
            if chat_id not in self._db_locks:
                self._db_locks[chat_id] = threading.Lock()
            return self._db_locks[chat_id]

    def _open_db(self, chat_id) -> YamlDB:
        return YamlDB(filename="%s/%s.yaml" % (self.database_dir, chat_id))

    def _send_help_keyboard(self, chat_id):
        markup = types.ReplyKeyboardMarkup()
        markup.row(
            types.KeyboardButton("/help"),
            types.KeyboardButton("/check"),
            types.KeyboardButton("/wantlist"),
        )
        markup.row(
            types.KeyboardButton("/list"),
            types.KeyboardButton("/delete"),
        )
        help_text = "What do you want?\n"
        for key, description in self.commands.items():
            help_text += "%s %s\n" % (key, description)
        utils.send_msg(
            self, chat_id, help_text,
            reply_markup=markup,
            disable_web_page_preview=True,
        )

    # -------------------------------------------------------------------------
    # Handlers
    # -------------------------------------------------------------------------

    def _handle_start(self, message):
        chat_id = message.chat.id
        with self.get_db_lock(chat_id):
            db = self._open_db(chat_id)
            if not db.get("release_list"):
                db["release_list"] = list()
                db["chat_id"] = chat_id
                db.save()
        self.bot.reply_to(message, "Hi there, I am Discoger bot")
        self._send_help_keyboard(chat_id)

    def _handle_check(self, message):
        chat_id = message.chat.id
        with self.get_db_lock(chat_id):
            db = self._open_db(chat_id)
            has_list = bool(db.get("release_list"))
        if has_list:
            utils.send_msg(self, chat_id, "Okay i'm checking your following list")
            self._check_discogs(chat_id)
        else:
            utils.send_msg(self, chat_id, "Your following list is empty, send me a url first")

    def _handle_add_release(self, message):
        chat_id = message.chat.id
        url = message.text
        release_id = re.findall(r"\d+", url)[0]
        with self.get_db_lock(chat_id):
            db = self._open_db(chat_id)
            if not db.search("release_list[?release_id=='%s']" % release_id):
                release = scrap.DiscogerInfo(url, self.d, release_id)
                db["release_list"].append(release.release_info)
                db.save()
                utils.send_msg(self, chat_id, "%s is added in following list" % release_id)
            else:
                utils.send_msg(self, chat_id, "%s is already in following list" % release_id)

    def _handle_list(self, message):
        chat_id = message.chat.id
        with self.get_db_lock(chat_id):
            db = self._open_db(chat_id)
            if not db.get("release_list"):
                utils.send_msg(self, chat_id, "Your following list is empty, send me a url first")
                return
            lines = []
            for idx, item in enumerate(db["release_list"]):
                sell_type = item.get("type", "release")
                lines.append("%s: %s - %s %s/%s/%s" % (
                    idx,
                    item["artist"],
                    item["title"],
                    self.discogs_url,
                    sell_type,
                    item["release_id"],
                ))
        for chunk in util.split_string("\n".join(lines), 3000):
            utils.send_msg(self, chat_id, chunk, disable_web_page_preview=True)

    def _handle_delete(self, message):
        answer = self.bot.reply_to(message, "Which item do you want to delete from your list?")
        self.bot.register_next_step_handler(answer, self._process_delete_step)

    def _process_delete_step(self, message):
        chat_id = message.chat.id
        id_item = message.text
        with self.get_db_lock(chat_id):
            db = self._open_db(chat_id)
            db["release_list"].pop(int(id_item))
            db.save()
        utils.send_msg(self, chat_id, "%s is deleted from following list" % id_item)

    def _handle_wantlist(self, message):
        chat_id = message.chat.id
        with self.get_db_lock(chat_id):
            db = self._open_db(chat_id)
            wantlist_user = db.get("wantlist_user")
        if wantlist_user:
            message.text = wantlist_user
            self._process_wantlist(message)
        else:
            answer = self.bot.reply_to(message, "Give your Discogs username to sync your wantlist:")
            self.bot.register_next_step_handler(answer, self._process_wantlist)

    def _process_wantlist(self, message):
        chat_id = message.chat.id
        username = message.text
        try:
            user_info = self.d.user(username)
            for i in user_info.wantlist:
                release_info = self.d.release(i.id)
                with self.get_db_lock(chat_id):
                    db = self._open_db(chat_id)
                    if not db.search("release_list[?release_id=='%s']" % i.id):
                        release = scrap.DiscogerInfo(release_info.url, self.d, str(i.id))
                        db["release_list"].append(release.release_info)
                        db.save()
                        logging.info("Item %s added in following list" % i.id)
                    else:
                        logging.info("Item %s already in your following list" % i.id)
            utils.send_msg(self, chat_id, "Your wantlist is synchronized")
            with self.get_db_lock(chat_id):
                db = self._open_db(chat_id)
                if not db.get("wantlist_user"):
                    db["wantlist_user"] = username
                    db.save()
        except discogs_client.exceptions.DiscogsAPIError as e:
            utils.send_msg(self, chat_id, "Error, %s" % e)

    # -------------------------------------------------------------------------
    # Scheduler
    # -------------------------------------------------------------------------

    def _check_discogs(self, chat_id=None):
        if chat_id:
            logging.info("Check user list %s" % chat_id)
            with self.get_db_lock(chat_id):
                db = self._open_db(chat_id)
                utils.scrap_data(self, chat_id, db)
        else:
            logging.info("Check all lists")
            for x in self.database_dir.iterdir():
                chat_id = re.findall(r"\d+", str(x))[0]
                logging.info("Check user list %s" % chat_id)
                with self.get_db_lock(chat_id):
                    db = self._open_db(chat_id)
                    utils.scrap_data(self, chat_id, db)

    # -------------------------------------------------------------------------
    # Wiring
    # -------------------------------------------------------------------------

    def _register_handlers(self):
        self.bot.register_message_handler(
            self._handle_start,
            commands=["help", "start"],
            pass_bot=False,
        )
        self.bot.register_message_handler(
            self._handle_check,
            commands=["check"],
            pass_bot=False,
        )
        self.bot.register_message_handler(
            self._handle_list,
            commands=["list"],
            pass_bot=False,
        )
        self.bot.register_message_handler(
            self._handle_delete,
            commands=["delete"],
            pass_bot=False,
        )
        self.bot.register_message_handler(
            self._handle_wantlist,
            commands=["wantlist"],
            pass_bot=False,
        )
        self.bot.register_message_handler(
            self._handle_add_release,
            regexp="^https://www.discogs.com/.*(release|master)/.*",
            pass_bot=False,
        )

    def _bot_polling(self):
        while True:
            try:
                logging.info("Starting bot polling now. New bot instance started!")
                self.bot.polling(none_stop=True, interval=3, timeout=30)
            except Exception as ex:
                logging.error("Bot polling failed, restarting in 30sec. Error:\n%s" % ex)
                self.bot.stop_polling()
                sleep(30)
            else:
                self.bot.stop_polling()
                logging.info("Bot polling loop finished.")
                break

    def _run(self):
        schedule.every(int(self.config["DEFAULT"]["schedule_time"])).minutes.do(
            lambda: threading.Thread(target=self._check_discogs).start()
        )
        polling_thread = threading.Thread(target=self._bot_polling, daemon=True)
        polling_thread.start()
        while True:
            schedule.run_pending()
            time.sleep(1)


def main():
    Discoger()


if __name__ == "__main__":
    main()
