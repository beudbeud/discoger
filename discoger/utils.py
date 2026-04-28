import re
import logging
from discoger import scrap
from bs4 import BeautifulSoup


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


def send_msg(
    self,
    chat_id,
    text,
    photo=None,
    parse_mode="markdown",
    disable_web_page_preview=False,
):
    if photo:
        try:
            self.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                parse_mode=parse_mode,
                caption=text,
            )
        except Exception as inst:
            logging.warning("user: %s, %s" % (chat_id, inst))
    else:
        try:
            self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        except Exception as inst:
            logging.warning("user: %s, %s" % (chat_id, inst))


def check_sales(self, release_id, type_sell):
    if type_sell == "master":
        url = f"{self.discogs_url}/sell/list?sort=listed%2Cdesc&limit=25&master_id={release_id}&format=Vinyl"
    else:
        url = f"{self.discogs_url}/sell/release/{release_id}?sort=listed%2Cdesc&limit=25"
    try:
        response = self.http.get(url, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logging.debug("Network error for release %s: %s" % (release_id, e))
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    table = soup.find_all("table", {"class": "mpitems"})
    if not table:
        logging.warning("Scraping structure changed: table.mpitems not found for release %s (%s)" % (release_id, url))
        return None

    rows = table[0].find_all("tr")
    if len(rows) < 2:
        logging.debug("No listings in table for release %s" % release_id)
        return None

    last_item = rows[1]
    item = last_item.find("a", {"class": "item_description_title"})
    price = last_item.find("span", {"class": "price"})

    if not item:
        logging.warning("Scraping structure changed: a.item_description_title not found for release %s (%s)" % (release_id, url))
        return None
    if not price:
        logging.warning("Scraping structure changed: span.price not found for release %s (%s)" % (release_id, url))
        return None
    if "data-currency" not in price.attrs or "data-pricevalue" not in price.attrs:
        logging.warning("Scraping structure changed: span.price missing data attributes for release %s (%s)" % (release_id, url))
        return None

    if self.disable_unofficial and "Unofficial" in item.get_text():
        return None

    return {
        "id": re.search(r'\d+', item["href"]).group(),
        "price": "{} {}".format(price["data-currency"], price["data-pricevalue"]),
        "url": "https://www.discogs.com{}".format(item["href"]),
    }


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
            ):
                parse = scrap.DiscogsScraper(data_last_sell["url"], self.d, self.http)
                logging.info("New item for %s - %s" % (item["artist"], item["title"]))
                text = """
**New release for:**
%s - %s
Price: %s
Recommanded price: %s
Media: %s
Sleeve: %s
Shipping from: %s
%s
                """ % (
                    item["artist"],
                    item["title"],
                    data_last_sell["price"],
                    parse.suggestion_price,
                    parse.media_condition,
                    parse.sleeve_condition,
                    parse.shipping_from,
                    data_last_sell["url"],
                )
                if "image" in item:
                    send_msg(
                        self,
                        chat_id,
                        text,
                        photo=item["image"],
                        parse_mode="markdown",
                    )
                else:
                    send_msg(
                        self,
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
