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
from telebot import types, util

import logging
logging.basicConfig(format='%(asctime)s %(levelname)s - %(message)s', level=logging.INFO)

home = str(Path.home())
config_file = Path(home + "/.config/discoger/config.ini")
database_dir = Path(home + "/.config/discoger/databases")
discogs_url = 'https://www.discogs.com'

if config_file.exists():
    config = configparser.ConfigParser()
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
        bot.send_message(chat_id, "Your discoger following list is empty, send me item url first")


@bot.message_handler(regexp="^https://www.discogs.com/.*(release|master)/.*")
def handle_message(message):
    release_info = dict()
    chat_id = message.chat.id
    release_id = re.findall(r'\d+', message.text)[0]
    db = YamlDB(filename="%s/.config/discoger/databases/%s.yaml" % (home, chat_id))
    if not db.search("release_list[?release_id=='%s']" % (release_id)):
        relase_all_info = d.release(release_id)
        db = YamlDB(filename="%s/.config/discoger/databases/%s.yaml" % (home, chat_id))
        release_info["release_id"] = release_id
        release_info["artist"] = relase_all_info.artists[0].name
        release_info["title"] = relase_all_info.title
        release_info["url"] = message.text
        if len(re.findall(r'\/master\/\d+', message.text)) == 1:
            release_info["type"] = "master"
        else:
            release_info["type"] = "release"
        release_info["last_sell"] = dict()
        db["release_list"].append(release_info)
        db.save()
        bot.send_message(chat_id, "%s is added in following list" % (release_id))
    else:
        bot.send_message(chat_id, "%s is already in following list" % (release_id))


@bot.message_handler(commands=['list'])
def get_list(message):
    chat_id = message.chat.id
    db = YamlDB(filename="%s/.config/discoger/databases/%s.yaml" % (home, chat_id))
    id_list = 0
    all_text = ""
    for i in db["release_list"]:
        sell_type = i.get("type")
        if sell_type is None:
            sell_type = "release"
        text = "%s: %s - %s %s/%s/%s" % (id_list, i["artist"], i["title"], discogs_url, sell_type, i["release_id"])
        all_text = all_text + "\n" + text
        id_list = id_list + 1
    splitted_text = util.split_string(all_text, 3000)
    for text in splitted_text:
        bot.send_message(chat_id, text, disable_web_page_preview=True)


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
    bot.send_message(chat_id, "% is deleted in following list" % (id_item))


def get_info(release_id, type_sell):
    data_last_sell = dict()
    if type_sell == 'master':
        url = f"{discogs_url}/sell/mplistrss?output=rss&master_id={release_id}&ev=mb&format=Vinyl"
    else:
        url = f"{discogs_url}/sell/mplistrss?output=rss&release_id={release_id}"
    feed = feedparser.parse(url)
    try:
        entry = feed.entries[-1]
        data_last_sell["id"] = re.findall(r'\d+', entry["link"])[0]
        data_last_sell["date"] = entry["updated"]
        data_last_sell["url"] = entry["link"]
        data_last_sell["price"] = re.findall(r'... \d?\d?\d\d.\d\d', entry["summary_detail"]["value"])[0]
        return data_last_sell
    except Exception as e:
        logging.debug("%s: for %s item" % (e, release_id))
        return None


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
    for i in range(len(db["release_list"])):
        item = db.search("release_list[%s]" % (str(i)))
        sell_type = item.get("type")
        if sell_type is None:
            sell_type = "release"
        data_last_sell = get_info(item["release_id"], sell_type)
        if data_last_sell:
            if not item["last_sell"] or (item["last_sell"]["id"] != data_last_sell["id"] and item["last_sell"]["date"] < data_last_sell["date"]):
                logging.info("New item for %s - %s" % (item["artist"], item["title"]))
                text = "New release for:\n%s - %s\ndate: %s\nprice: %s\n%s" % (item["artist"], item["title"], data_last_sell["date"], data_last_sell["price"], data_last_sell["url"])
                bot.send_message(chat_id, text, disable_web_page_preview=False)
                db["release_list"][i]["last_sell"] = data_last_sell
            else:
                logging.info("Not new item for %s - %s" % (db["release_list"][i]["artist"], db["release_list"][i]["title"]))
        else:
            logging.info("Nothing available for %s - %s" % (db["release_list"][i]["artist"], db["release_list"][i]["title"]))
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
