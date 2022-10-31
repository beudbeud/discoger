#!/usr/bin/env python3

import configparser
import discogs_client
import yaml
import requests
from bs4 import BeautifulSoup
import re
import datetime
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

url = "https://www.discogs.com/fr/settings/developers"
database = dict()

config = configparser.ConfigParser()
config_file = Path(home + "/.config/discoger/config.ini")
database_dir = Path(home + "/.config/discoger/databases")

if config_file.exists():
    config.read(config_file)
else:
    print("No config file")
    exit()

if not database_dir.exists():
    database_dir.mkdir(parents=True, exist_ok=True)


schedule_logger = logging.getLogger('schedule')
logger = telebot.logger

token = config["telegram"]["token"]
bot = telebot.TeleBot(token)

if config["discogs"]["secret"]:
    secret = config["discogs"]["secret"]
else:
    print(f'Please browse to the following URL {url}')

    secret = input('Verification code : ')
    config["discogs"]["secret"] = secret
    with open(config_file, 'w') as configfile:
        config.write(configfile)

try:
    client = discogs_client.Client('DiscogsAlert/0.1', user_token=secret)
    me = client.identity()
except discogs_client.exceptions.HTTPError as e:
    logging.error('Error: Unable to authenticate.')
    raise SystemExit(e)


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


@bot.message_handler(commands=['help', 'start'])
def send_welcome(message):
    chat_id = message.chat.id
    if Path("%s/.config/discoger/databases/%s.yaml" % (home, chat_id)).exists():
        msg = "Hi there, I am Discoger bot"
        bot.reply_to(message, msg)
        process_hi_step(chat_id)
    else:
        msg = "Hi new user, I am Discorger bot. Give me the ID of the list you want i will need follow ?"
        answer = bot.reply_to(message, msg)
        bot.register_next_step_handler(answer, process_save_step)


def process_hi_step(chat_id):
    markup = types.ReplyKeyboardMarkup()
    itembtna = types.KeyboardButton('/help')
    itembtnb = types.KeyboardButton('/check')
    markup.row(itembtna, itembtnb)
    msg = "What do you want?"
    bot.send_message(chat_id, msg, reply_markup=markup)


def process_save_step(message):
    data_to_save = dict()
    chat_id = message.chat.id
    id_list = message.text
    try:
        client.list(id_list)
        msg = "All is okay. Now you can enjoy Discogers"
        data_file = Path("%s/.config/discoger/databases/%s.yaml" % (home, chat_id))
        data_to_save["chat_id"] = chat_id
        data_to_save["id_list"] = id_list
        data_to_save["release_list"] = list()
        with open(data_file, 'w') as file:
            yaml.dump(data_to_save, file)
            file.close()
        msg = "Thanks, i added your list in my database"
        bot.reply_to(message, msg)
        process_hi_step(chat_id)
    except:
        msg = "There are problem to acces to your list. You need check the ID or if the list in public"
        bot.reply_to(message, msg)


@bot.message_handler(commands=['check'])
def get_check(message):
    chat_id = message.chat.id
    data_file = Path("%s/.config/discoger/databases/%s.yaml" % (home, chat_id))
    bot.send_message(chat_id, "Okay i check your discogs list")
    check_discogs(data_file)


def market_scrape(release_id, title, last_one):
    url = f"https://www.discogs.com/fr/sell/mplistrss?output=rss&release_id={release_id}"
    try:
        response = requests.get(url)
    except requests.exceptions.RequestException as e:
        raise SystemExit(e)

    soup = BeautifulSoup(response.content, features="xml")

    # grab all the summaries and links from discogs marketplace,
    # put 'em in a list
    messy_list = list()
    summaries = soup.findAll('summary')
    links = soup.findAll('link')
    date = soup.findAll('updated')

    new_one = False
    for i in range(len(summaries)):
        messy_list.append(str(summaries[i].text) + str(links[i+1]) + str(date[i+1].text))

    for i in range(len(messy_list)):
        this_dict = dict()
        match = re.findall(r'\d{4}-\d{2}-\d{2}[\w]\d{2}:\d{2}:\d{2}', messy_list[i])[0]
        updated = datetime.datetime.strptime(match.replace("T", " "), '%Y-%m-%d %H:%M:%S')
        sell_id = re.findall('"([^"]*)"', messy_list[i])[0].rsplit('/', 1)[-1]
        if not sell_id:
            break
        if check_exist(release_id, sell_id):
            this_dict = get_data(release_id)
        else:
            if updated > last_one:
                this_dict['date'] = updated
                this_dict['title'] = title
                this_dict['id'] = release_id
                this_dict['id_sell'] = sell_id
                this_dict['price'] = re.findall(r'... \d?\d?\d\d.\d\d', messy_list[i])[0]
                this_dict['url'] = re.findall('"([^"]*)"', messy_list[i])[0]
                last_one = updated
                new_one = True
        if new_one:
            logging.info("There are new sale\n")
            send_msg(title=title, data=this_dict)
        return this_dict


def send_msg(title, data):
    url = data.get("url")
    date = data.get("date")
    price = data.get("price")
    text = "New release for :\n%s\ndate: %s\nprice: %s\n%s" % (title, date.strftime('%d %B %Y - %H:%M'), price, url)
    chat_id = user_data["chat_id"]
    bot.send_message(chat_id, text)


def get_data(release_id):
    data = dict()
    for i in user_data["release_list"]:
        if release_id == i.get("id"):
            data = i
            return data


def check_exist(release_id, id_sell):
    for i in user_data["release_list"]:
        if release_id == i.get("id"):
            if id_sell == i.get("id_sell"):
                return True
    return False


def check_date(id):
    for i in user_data["release_list"]:
        if id == i.get("id"):
            last_one = i.get("date")
            return last_one
    last_one = datetime.datetime.strptime("1986-09-17 05:51:41", '%Y-%m-%d %H:%M:%S')
    return last_one


def check_discogs(data_file=None):
    if data_file:
        logging.info("Check user list")
        scrap_data(data_file)
    else:
        logging.info("Check all list")
        for x in database_dir.iterdir():
            scrap_data(x)


def scrap_data(data_file):
    data_to_save = dict()
    with open(data_file) as file:
        global user_data
        user_data = yaml.full_load(file)
    data_to_save["release_list"] = list()
    id_list = user_data["id_list"]
    list_notif = client.list(id_list)
    logging.info("Check if there are new a new sale for:")
    for item in list_notif.items:
        last_one = (check_date(item.id))
        logging.info(str(item.id) + ": " + item.display_title)
        data_from_item = market_scrape(item.id, item.display_title, last_one)
        if data_from_item:
            data_to_save["release_list"].append(data_from_item)
    while {} in data_to_save["release_list"]:
        data_to_save["release_list"].remove({})
    data_to_save["id_list"] = id_list
    data_to_save["chat_id"] = user_data["chat_id"]
    with open(data_file, 'w') as file:
        yaml.dump(data_to_save, file)
        file.close()


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
