#!/usr/bin/env python3

import configparser
import discogs_client
import logging
import threading
import schedule
import time
import re

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
            logging.error(
                "No config file, please create a config file follwing example"
            )
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

        self.commands = {  # command description used in the "help" command
            "/start": "Get used to the bot",
            "/help": "Gives you information about the available commands",
            "/list": "Show all items in your following list",
            "/delete": "Delete item from the following list",
            "/wantlist": "Synchronize Discogs wantlist to following list",
            "https://www.discogs.com/release|master/.*": "Add release or master release in following list (ex: https://www.discogs.com/release/26741825)",
        }
        self.options = {  # command description used in the "help" command
            "/start": "Get used to the bot"
        }

        try:
            self.d = discogs_client.Client("DiscogsAlert/0.1", user_token=self.secret)
            self.me = self.d.identity()
        except discogs_client.exceptions.HTTPError as e:
            logging.error("Error: Unable to authenticate.")
            raise SystemExit(e)

        @self.bot.message_handler(commands=["help", "start"])
        def send_welcome(message):
            chat_id = message.chat.id
            msg = "Hi there, I am Discoger bot"
            db = YamlDB(filename="%s/%s.yaml" % (self.database_dir, chat_id))
            if not db.get("release_list"):
                db["release_list"] = list()
                db["chat_id"] = chat_id
                db.save()
            self.bot.reply_to(message, msg)
            process_hi_step(chat_id)

        def process_hi_step(chat_id):
            markup = types.ReplyKeyboardMarkup()
            itembtna = types.KeyboardButton("/help")
            itembtnb = types.KeyboardButton("/check")
            itembtnc = types.KeyboardButton("/list")
            itembtnd = types.KeyboardButton("/delete")
            itembtne = types.KeyboardButton("/wantlist")
            markup.row(itembtna, itembtnb, itembtne)
            markup.row(itembtnc, itembtnd)
            help_text = "What do you want?\n"
            for key in self.commands:
                help_text += key + " "
                help_text += self.commands[key] + "\n"
            self.bot.send_message(
                chat_id, help_text, reply_markup=markup, disable_web_page_preview=True
            )

        @self.bot.message_handler(commands=["check"])
        def get_check(message):
            chat_id = message.chat.id
            db = YamlDB(filename="%s/%s.yaml" % (self.database_dir, chat_id))
            if db.get("release_list"):
                self.bot.send_message(chat_id, "Okay i'm checkng your following list")
                check_discogs(chat_id)
            else:
                self.bot.send_message(
                    chat_id,
                    "Your discoger following list is empty, send me a url first",
                )

        @self.bot.message_handler(
            regexp="^https://www.discogs.com/.*(release|master)/.*"
        )
        def handle_message(message):
            chat_id = message.chat.id
            url = message.text
            release_id = re.findall(r"\d+", url)[0]
            db = YamlDB(filename="%s/%s.yaml" % (self.database_dir, chat_id))
            if not db.search("release_list[?release_id=='%s']" % (release_id)):
                release = scrap.DiscogerInfo(url, self.d, release_id)
                db["release_list"].append(release.release_info)
                db.save()
                self.bot.send_message(
                    chat_id, "%s is added in following list" % (release_id)
                )
            else:
                self.bot.send_message(
                    chat_id, "%s is already in following list" % (release_id)
                )

        @self.bot.message_handler(commands=["list"])
        def get_list(message):
            chat_id = message.chat.id
            db = YamlDB(filename="%s/%s.yaml" % (self.database_dir, chat_id))
            if not db.get("release_list"):
                self.bot.send_message(
                    chat_id,
                    "Your discoger following list is empty, send me a url first",
                )
            else:
                id_list = 0
                all_text = ""
                for i in db["release_list"]:
                    sell_type = i.get("type")
                    if sell_type is None:
                        sell_type = "release"
                    text = "%s: %s - %s %s/%s/%s" % (
                        id_list,
                        i["artist"],
                        i["title"],
                        self.discogs_url,
                        sell_type,
                        i["release_id"],
                    )
                    all_text = all_text + "\n" + text
                    id_list = id_list + 1
                splitted_text = util.split_string(all_text, 3000)
                for text in splitted_text:
                    self.bot.send_message(chat_id, text, disable_web_page_preview=True)

        @self.bot.message_handler(commands=["delete"])
        def delete_release(message):
            msg = "Which item do you want delete in your list?"
            answer = self.bot.reply_to(message, msg)
            self.bot.register_next_step_handler(answer, process_delete_step)

        def process_delete_step(message):
            chat_id = message.chat.id
            id_item = message.text
            db = YamlDB(filename="%s/%s.yaml" % (self.database_dir, chat_id))
            db["release_list"].pop(int(id_item))
            db.save()
            self.bot.send_message(
                chat_id, "%s is deleted in following list" % (id_item)
            )

        @self.bot.message_handler(commands=["wantlist"])
        def wantlist(message):
            chat_id = message.chat.id
            db = YamlDB(filename="%s/%s.yaml" % (self.database_dir, chat_id))
            if db.get("wantlist_user"):
                message.text = db.get("wantlist_user")
                message.chat.id = chat_id
                process_wantlist(message)
            else:
                msg = "Give your discogs username for checking your wantlist?"
                answer = self.bot.reply_to(message, msg)
                self.bot.register_next_step_handler(answer, process_wantlist)

        def process_wantlist(message):
            chat_id = message.chat.id
            username = message.text
            db = YamlDB(filename="%s/%s.yaml" % (self.database_dir, chat_id))
            try:
                user_info = self.d.user(username)
                for i in user_info.wantlist:
                    release_info = self.d.release(i.id)
                    if not db.search("release_list[?release_id=='%s']" % (i.id)):
                        release = scrap.DiscogerInfo(
                            release_info.url, self.d, str(i.id)
                        )
                        db["release_list"].append(release.release_info)
                        db.save()
                        logging.info("Item %s added in following list" % (i.id))
                    else:
                        logging.info("Item %s already in your following list" % (i.id))
                self.bot.send_message(chat_id, "Your wantlist is synchronized")
                if not db.get("wantlist_user"):
                    db["wantlist_user"] = username
            except discogs_client.exceptions.DiscogsAPIError as e:
                self.bot.send_message(chat_id, "Error, %s" % e)

        def check_discogs(chat_id=None):
            if chat_id:
                logging.info("Check user list %s" % (chat_id))
                db = YamlDB(filename="%s/%s.yaml" % (self.database_dir, chat_id))
                utils.scrap_data(self, chat_id, db)
            else:
                logging.info("Check all list")
                for x in self.database_dir.iterdir():
                    chat_id = re.findall(r"\d+", str(x))[0]
                    logging.info("Check user list %s" % (chat_id))
                    db = YamlDB(filename="%s/%s.yaml" % (self.database_dir, chat_id))
                    utils.scrap_data(self, chat_id, db)

        def bot_polling():
            while True:
                try:
                    logging.info("Starting bot polling now. New bot instance started!")
                    self.bot.polling(none_stop=True, interval=3, timeout=30)
                except Exception as ex:
                    logging.error(
                        "Bot polling failed, restarting in {}sec. Error:\n{}".format(
                            30, ex
                        )
                    )
                    self.bot.stop_polling()
                    sleep(30)
                else:
                    self.bot.stop_polling()
                    logging.info("Bot polling loop finished.")
                    break

        def run_threaded(job_func):
            job_thread = threading.Thread(target=job_func)
            job_thread.start()

        schedule.every(int(self.config["DEFAULT"]["schedule_time"])).minutes.do(
            run_threaded, check_discogs
        )
        polling_thread = threading.Thread(target=bot_polling)
        polling_thread.daemon = True
        polling_thread.start()
        while 1:
            schedule.run_pending()
            time.sleep(1)


def main():
    Discoger()


if __name__ == "__main__":
    main()
