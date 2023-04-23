#!/usr/bin/env python3

import configparser
import discogs_client
from yamldb.YamlDB import YamlDB
import feedparser
import re
from pathlib import Path

import threading
import schedule
import time
from time import sleep

import telebot
from telebot import types

import logging
logging.basicConfig(format='%(asctime)s %(levelname)s - %(message)s', level=logging.INFO)

home = str(Path.home())
config_file = Path(home + "/.config/discoger/config.ini")
database_dir = Path(home + "/.config/discoger/databases")


def read_ini(file_path):
    config = configparser.ConfigParser()
    config.read(file_path)
    for section in config.sections():
        for key in config[section]:
            print((key, config[section][key]))
    return config


if config_file.exists():
    config = read_ini(config_file)
    config.read(config_file)
else:
    logging.error("No config file, please create a config file follwing example")
    raise SystemExit()

if not database_dir.exists():
    database_dir.mkdir(parents=True, exist_ok=True)

token = config["telegram"]["token"]
secret = secret = config["discogs"]["secret"]
bot = telebot.TeleBot(token)

try:
    d = discogs_client.Client('DiscogsAlert/0.1', user_token=secret)
    me = d.identity()
except discogs_client.exceptions.HTTPError as e:
    logging.error('Error: Unable to authenticate.')
    raise SystemExit(e)


@bot.message_handler(commands=['help', 'start'])
def send_welcome(message):
    chat_id = message.chat.id
    msg = "Hi there, I am Discoger bot"
    bot.reply_to(message, msg)
    process_hi_step(chat_id)


def process_hi_step(chat_id):
    markup = types.ReplyKeyboardMarkup()
    itembtna = types.KeyboardButton('/help')
    itembtnb = types.KeyboardButton('/check')
    itembtnc = types.KeyboardButton('/list')
    itembtnd = types.KeyboardButton('/delete')
    markup.row(itembtna, itembtnb)
    markup.row(itembtnc, itembtnd)
    msg = "What do you want?"
    bot.send_message(chat_id, msg, reply_markup=markup)


@bot.message_handler(commands=['check'])
def get_check(message):
    chat_id = message.chat.id
    db = YamlDB(filename="%s/.config/discoger/databases/%s.yaml" % (home, chat_id))
    if db.get("release_list"):
        bot.send_message(chat_id, "Okay i check your discogs list")
        check_discogs(chat_id)
    else:
        db["release_list"] = list()
        db.save()
        bot.send_message(chat_id, "Your discoger want list is empty, send me item url first")


@bot.message_handler(regexp="^https://www.discogs.com/fr/release/.*")
def handle_message(message):
    release_info = dict()
    chat_id = message.chat.id
    release_id = re.findall(r'\d+', message.text)[0]
    relase_all_info = d.release(release_id)
    bot.send_message(chat_id, release_id)
    db = YamlDB(filename="%s/.config/discoger/databases/%s.yaml" % (home, chat_id))
    release_info["release_id"] = release_id
    release_info["artist"] = relase_all_info.artists[0].name
    release_info["title"] = relase_all_info.title
    release_info["last_sell"] = dict()
    db["release_list"].append(release_info)
    db.save()


@bot.message_handler(commands=['list'])
def get_list(message):
    chat_id = message.chat.id
    db = YamlDB(filename="%s/.config/discoger/databases/%s.yaml" % (home, chat_id))
    id_list = 0
    for i in db["release_list"]:
        bot.send_message(chat_id, "%s: %s - %s" % (id_list, i["artist"], i["title"]))
        id_list = id_list + 1


@bot.message_handler(commands=['delete'])
def delete_release(message):
    msg = "Which item do you want delete in your list?"
    answer = bot.reply_to(message, msg)
    bot.register_next_step_handler(answer, process_delete_step)


def process_delete_step(message):
    chat_id = message.chat.id
    id_item = message.text
    db = YamlDB(filename="%s/.config/discoger/databases/%s.yaml" % (home, chat_id))
    db["release_list"].pop(int(id_item))
    db.save()


def get_info(release_id):
    data_last_sell = dict()
    url = f"https://www.discogs.com/fr/sell/mplistrss?output=rss&release_id={release_id}"
    feed = feedparser.parse(url)
    entry = feed.entries[-1]
    data_last_sell["id"] = re.findall(r'\d+', entry["link"])[0]
    data_last_sell["date"] = entry["updated"]
    data_last_sell["url"] = entry["link"]
    data_last_sell["price"] = re.findall(r'... \d?\d?\d\d.\d\d', entry["summary_detail"]["value"])[0]
    return data_last_sell


def check_discogs(chat_id=None):
    if chat_id:
        logging.info("Check user list %s" % (chat_id))
        scrap_data(chat_id)
    else:
        logging.info("Check all list")
        for x in database_dir.iterdir():
            chat_id = re.findall(r'\d+', str(x))[0]
            logging.info("Check user list %s" % (chat_id))
            scrap_data(chat_id)


def scrap_data(chat_id):
    db = YamlDB(filename="%s/.config/discoger/databases/%s.yaml" % (home, chat_id))
    chat_id = db.get("chat_id")
    for i in db["release_list"]:
        data_last_sell = get_info(i["release_id"])
        if not i["last_sell"] or (i["last_sell"]["id"] != data_last_sell["id"] and i["last_sell"]["date"] < data_last_sell["date"]):
            logging.info("New item for %s - %s" % (i["artist"], i["title"]))
            text = "New release for :\n%s\ndate: %s\nprice: %s\n%s" % (i["title"], data_last_sell["date"], data_last_sell["price"], data_last_sell["url"])
            bot.send_message(chat_id, text)
            i["last_sell"] = data_last_sell
        else:
            logging.info("Not new item for %s - %s" % (i["artist"], i["title"]))
    db.save()


def bot_polling():
    while True:
        try:
            logging.info("Starting bot polling now. New bot instance started!")
            bot.polling(none_stop=True, interval=3, timeout=30)
        except Exception as ex:
            logging.error("Bot polling failed, restarting in {}sec. Error:\n{}".format(30, ex))
            bot.stop_polling()
            sleep(30)
        else:
            bot.stop_polling()
            logging.info("Bot polling loop finished.")
            break


def run_threaded(job_func):
    job_thread = threading.Thread(target=job_func)
    job_thread.start()


def main():
    schedule.every(int(config["DEFAULT"]["schedule_time"])).minutes.do(run_threaded, check_discogs)
    polling_thread = threading.Thread(target=bot_polling)
    polling_thread.daemon = True
    polling_thread.start()
    while 1:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
