import feedparser
import re
import logging
from discoger import scrap


class CustomFormatter(logging.Formatter):
    """Logging Formatter to add colors"""

    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    fmt_nok = "%(asctime)s %(levelname)s (%(filename)s:%(lineno)d) - %(message)s"
    fmt_ok = "%(asctime)s %(levelname)s - %(message)s"

    FORMATS = {
        logging.INFO: OKGREEN + fmt_ok + ENDC,
        logging.WARNING: WARNING + fmt_nok + ENDC,
        logging.ERROR: FAIL + fmt_nok + ENDC,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def check_sales(self, release_id, type_sell):
    self.discogs_url = "https://www.discogs.com"
    data_last_sell = dict()
    if type_sell == "master":
        url = f"{self.discogs_url}/sell/mplistrss?output=rss&master_id={release_id}&ev=mb&format=Vinyl"
    else:
        url = f"{self.discogs_url}/sell/mplistrss?output=rss&release_id={release_id}"
    feed = feedparser.parse(url)
    try:
        entry = feed.entries[-1]
        data_last_sell["id"] = re.findall(r"\d+", entry["link"])[0]
        data_last_sell["date"] = entry["updated"]
        data_last_sell["url"] = entry["link"]
        data_last_sell["price"] = re.findall(
            r"... \d?\d?\d\d.\d\d", entry["summary_detail"]["value"]
        )[0]
        if (
            self.disable_unofficial
            and len(re.findall("Unofficial", entry["title"])) > 0
        ):
            return None
        else:
            return data_last_sell
    except Exception as e:
        logging.debug("%s: for %s item" % (e, release_id))
        return None


def scrap_data(self, chat_id, db):
    chat_id = db.get("chat_id")
    for i in range(len(db["release_list"])):
        item = db.search("release_list[%s]" % (str(i)))
        type_sell = item.get("type")
        if type_sell is None:
            type_sell = "release"
        data_last_sell = check_sales(self, item["release_id"], type_sell)
        if data_last_sell:
            if not item["last_sell"] or (
                item["last_sell"]["id"] != data_last_sell["id"]
                and item["last_sell"]["date"] < data_last_sell["date"]
            ):
                parse = scrap.DiscogsScraper(data_last_sell["url"], self.d)
                logging.info("New item for %s - %s" % (item["artist"], item["title"]))
                text = """
**New release for:**
%s - %s
Date: %s
Price: %s
Recommanded price: %s
Media: %s
Sleeve: %s
Shipping from: %s
%s
                """ % (
                    item["artist"],
                    item["title"],
                    data_last_sell["date"],
                    data_last_sell["price"],
                    parse.suggestion_price,
                    parse.media_condition,
                    parse.sleeve_condition,
                    parse.shipping_from,
                    data_last_sell["url"],
                )
                if "image" in item:
                    self.bot.send_photo(
                        chat_id,
                        photo=item["image"],
                        parse_mode="markdown",
                        caption=text,
                    )
                else:
                    self.bot.send_message(
                        chat_id,
                        text,
                        parse_mode="markdown",
                        disable_web_page_preview=True,
                    )
                db["release_list"][i]["last_sell"] = data_last_sell
            else:
                logging.info(
                    "Not new item for %s - %s"
                    % (
                        db["release_list"][i]["artist"],
                        db["release_list"][i]["title"],
                    )
                )
        else:
            logging.info(
                "Nothing available for %s - %s"
                % (
                    db["release_list"][i]["artist"],
                    db["release_list"][i]["title"],
                )
            )
    db.save()
