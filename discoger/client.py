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
            logging.error("No config file, please create a config file following the example")
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

        self._db_locks = {}
        self._db_locks_mutex = threading.Lock()

        self._check_thread = None
        self._check_thread_lock = threading.Lock()

        self._register_handlers()
        self._run()

    # -------------------------------------------------------------------------
    # DB helpers
    # -------------------------------------------------------------------------

    def get_db_lock(self, chat_id):
        with self._db_locks_mutex:
            if chat_id not in self._db_locks:
                self._db_locks[chat_id] = threading.Lock()
            return self._db_locks[chat_id]

    def _open_db(self, chat_id) -> YamlDB:
        return YamlDB(filename="%s/%s.yaml" % (self.database_dir, chat_id))

    # -------------------------------------------------------------------------
    # Telegram handlers
    # -------------------------------------------------------------------------

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
            self.bot, chat_id, help_text,
            reply_markup=markup,
            disable_web_page_preview=True,
        )

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
            utils.send_msg(self.bot, chat_id, "Okay i'm checking your following list")
            self._check_user(chat_id)
        else:
            utils.send_msg(self.bot, chat_id, "Your following list is empty, send me a url first")

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
                utils.send_msg(self.bot, chat_id, "%s is added in following list" % release_id)
            else:
                utils.send_msg(self.bot, chat_id, "%s is already in following list" % release_id)

    def _handle_list(self, message):
        chat_id = message.chat.id
        with self.get_db_lock(chat_id):
            db = self._open_db(chat_id)
            if not db.get("release_list"):
                utils.send_msg(self.bot, chat_id, "Your following list is empty, send me a url first")
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
            utils.send_msg(self.bot, chat_id, chunk, disable_web_page_preview=True)

    def _handle_delete(self, message):
        answer = self.bot.reply_to(message, "Which item do you want to delete from your list?")
        self.bot.register_next_step_handler(answer, self._process_delete_step)

    def _process_delete_step(self, message):
        chat_id = message.chat.id
        try:
            idx = int(message.text)
        except ValueError:
            utils.send_msg(self.bot, chat_id, "Please send a valid number.")
            return
        with self.get_db_lock(chat_id):
            db = self._open_db(chat_id)
            if idx < 0 or idx >= len(db["release_list"]):
                utils.send_msg(self.bot, chat_id, "Index %s is out of range." % idx)
                return
            db["release_list"].pop(idx)
            db.save()
        utils.send_msg(self.bot, chat_id, "%s is deleted from following list" % idx)

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
            utils.send_msg(self.bot, chat_id, "Your wantlist is synchronized")
            with self.get_db_lock(chat_id):
                db = self._open_db(chat_id)
                if not db.get("wantlist_user"):
                    db["wantlist_user"] = username
                    db.save()
        except discogs_client.exceptions.DiscogsAPIError as e:
            utils.send_msg(self.bot, chat_id, "Error, %s" % e)

    # -------------------------------------------------------------------------
    # Scheduler / check logic
    # -------------------------------------------------------------------------

    def _process_releases(self, chat_id, release_list):
        """Check all releases sequentially, notify on new listings.

        Returns (updates: dict {release_id: data}, bot_blocked: bool).
        bot_blocked is True if a send attempt revealed the user blocked the bot;
        in that case the caller should delete the user's DB.
        """
        http = cloudscraper.create_scraper()
        updates = {}
        bot_blocked = False

        for item in release_list:
            if bot_blocked:
                break
            type_sell = item.get("type") or "release"
            try:
                data_last_sell = scrap.check_sales(
                    http, self.discogs_url, self.disable_unofficial,
                    item["release_id"], type_sell,
                )
            except Exception as e:
                logging.error("Error checking release %s: %s" % (item["release_id"], e))
                continue

            if data_last_sell:
                if not item["last_sell"] or int(data_last_sell["id"]) > int(item["last_sell"]["id"]):
                    logging.info("New item for %s - %s" % (item["artist"], item["title"]))
                    suggestion = scrap.get_suggestion_price(self.d, item["release_id"])
                    text = (
                        "**New release for:**\n"
                        "%s - %s\n"
                        "Price: %s\n"
                        "Recommended price: %s\n"
                        "Media: %s\n"
                        "Sleeve: %s\n"
                        "Shipping from: %s\n"
                        "%s"
                    ) % (
                        item["artist"],
                        item["title"],
                        data_last_sell["price"],
                        suggestion,
                        data_last_sell["media_condition"],
                        data_last_sell["sleeve_condition"],
                        data_last_sell["shipping_from"],
                        data_last_sell["url"],
                    )
                    sent = utils.send_msg(self.bot, chat_id, text, photo=item.get("image") or None,
                                          disable_web_page_preview=not item.get("image"))
                    if not sent:
                        bot_blocked = True
                        break
                    updates[item["release_id"]] = data_last_sell
                else:
                    logging.info("Not new item for %s - %s" % (item["artist"], item["title"]))
            else:
                logging.info("Nothing available for %s - %s" % (item["artist"], item["title"]))

            time.sleep(1)

        return updates, bot_blocked

    def _check_user(self, chat_id):
        logging.info("Check user list %s" % chat_id)

        with self.get_db_lock(chat_id):
            db = self._open_db(chat_id)
            release_list = list(db.get("release_list") or [])
            stored_chat_id = db.get("chat_id") or chat_id

        if not release_list:
            return

        image_updates = {}
        for item in release_list:
            if not item.get("image"):
                image = scrap.fetch_image(self.d, item["release_id"])
                if image:
                    item["image"] = image
                    image_updates[item["release_id"]] = image
                    logging.info("Fetched missing image for release %s" % item["release_id"])

        if image_updates:
            with self.get_db_lock(chat_id):
                db = self._open_db(chat_id)
                for i, item in enumerate(db["release_list"]):
                    if item["release_id"] in image_updates:
                        db["release_list"][i]["image"] = image_updates[item["release_id"]]
                db.save()

        updates, bot_blocked = self._process_releases(stored_chat_id, release_list)

        if bot_blocked:
            with self.get_db_lock(chat_id):
                db_path = Path("%s/%s.yaml" % (self.database_dir, chat_id))
                db_path.unlink(missing_ok=True)
            logging.info("User %s blocked the bot, removed from database" % chat_id)
        elif updates:
            with self.get_db_lock(chat_id):
                db = self._open_db(chat_id)
                for i, item in enumerate(db["release_list"]):
                    if item["release_id"] in updates:
                        db["release_list"][i]["last_sell"] = updates[item["release_id"]]
                db.save()

    def _check_discogs(self):
        logging.info("Check all lists")
        for x in self.database_dir.iterdir():
            match = re.search(r"\d+", str(x))
            if match:
                self._check_user(match.group())

    def _start_check(self):
        with self._check_thread_lock:
            if self._check_thread and self._check_thread.is_alive():
                logging.warning("Previous check still running, skipping this interval")
                return
            self._check_thread = threading.Thread(target=self._check_discogs, daemon=True)
            self._check_thread.start()

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
        schedule.every(int(self.config["DEFAULT"]["schedule_time"])).minutes.do(self._start_check)
        polling_thread = threading.Thread(target=self._bot_polling, daemon=True)
        polling_thread.start()
        while True:
            schedule.run_pending()
            time.sleep(1)


def main():
    Discoger()


if __name__ == "__main__":
    main()
