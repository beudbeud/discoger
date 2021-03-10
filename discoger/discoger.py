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

config = configparser.ConfigParser()
config_file = Path(home + "/.config/discoger/config.ini")
data_file = Path(home + "/.config/discoger/database.yaml")

if config_file.exists():
    config.read(config_file)
else:
    print("No config file")
    exit()

schedule_logger = logging.getLogger('schedule')
logger = telebot.logger

token = config["telegram"]["token"]
bot = telebot.TeleBot(token)
chat_id = config["telegram"]["chat_id"]

data_to_save = list()

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
    markup = types.ReplyKeyboardMarkup()
    itembtnd = types.KeyboardButton('/check')
    itembtnc = types.KeyboardButton('/help')
    markup.row(itembtnd, itembtnc)
    bot.reply_to(message, """\
Hi there, I am Discoger bot.
What do you want?
""", reply_markup=markup)


@bot.message_handler(commands=['check'])
def get_check(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "Okay i check your discogs list")
    check_discogs()


def market_scrape(release_id, title, last_one):
    url = f"https://www.discogs.com/sell/release/{release_id}?output=rss"
    first_last_one = last_one
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
        match = re.findall(r'\d{4}-\d{2}-\d{2}[\w]\d{2}:\d{2}:\d{2}', messy_list[i])[0]
        updated = datetime.datetime.strptime(match.replace("T", " "), '%Y-%m-%d %H:%M:%S')
        if updated >= last_one:
            this_dict = dict()
            this_dict['date'] = updated
            this_dict['title'] = title
            this_dict['id'] = release_id
            this_dict['price'] = re.findall(r'... \d?\d?\d\d.\d\d', messy_list[i])[0]
            this_dict['url'] = re.findall('"([^"]*)"', messy_list[i])[0]
            last_one = updated
            new_one = True
        else:
            new_one = False
    if first_last_one != last_one:
        logging.info("There are new sale\n")
        send_msg(title=title, data=this_dict)
    elif not new_one:
        this_dict = {}
    return this_dict


def send_msg(title, data):
    url = data.get("url")
    date = data.get("date")
    price = data.get("price")
    text = "New release for :\n%s\ndate: %s\nprice: %s\n%s" % (title, date.strftime('%d %B %Y'), price, url)
    bot.send_message(chat_id, text)


def check_exist(id, database):
    for i in database:
        if id == i.get("id"):
            last_one = i.get("date")
            return last_one
    last_one = datetime.datetime.strptime("1986-09-17 05:51:41", '%Y-%m-%d %H:%M:%S')
    return last_one


def check_discogs():
    if data_file.exists():
        with open(data_file) as file:
            database = yaml.full_load(file)
    else:
        database = list()
    id_list = config["discogs"]["id_list"]
    list_notif = client.list(id_list)
    logging.info("Check if there are new a new sale for:")
    for item in list_notif.items:
        last_one = (check_exist(item.id, database))
        logging.info(str(item.id) + ": " + item.display_title)
        data_to_save.append(market_scrape(item.id, item.display_title, last_one))
    while {} in data_to_save:
        data_to_save.remove({})
    with open(data_file, 'w') as file:
        yaml.dump(data_to_save, file)


def run_threaded(job_func):
    job_thread = threading.Thread(target=job_func)
    job_thread.start()


def main():
    schedule.every(30).minutes.do(run_threaded, check_discogs)
    polling_thread = threading.Thread(target=bot_polling)
    polling_thread.daemon = True
    polling_thread.start()

    while 1:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
