import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup


class CustomFormatter(logging.Formatter):
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


def get_suggestion_price(d, release_id):
    try:
        _info = d.release(release_id)
        value = _info.price_suggestions.mint.value
        currency = _info.price_suggestions.mint.currency
        return "%s %s" % (round(value, 2), currency)
    except Exception as e:
        logging.warning("Could not fetch suggestion price for release %s: %s" % (release_id, e))
        return "Unknown"


def send_msg(bot, chat_id, text, photo=None, parse_mode="markdown", disable_web_page_preview=False, **kwargs):
    if photo:
        try:
            bot.send_photo(chat_id=chat_id, photo=photo, parse_mode=parse_mode, caption=text, **kwargs)
        except Exception as inst:
            logging.warning("user: %s, %s" % (chat_id, inst))
    else:
        try:
            bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                **kwargs,
            )
        except Exception as inst:
            logging.warning("user: %s, %s" % (chat_id, inst))


def check_sales(http, discogs_url, disable_unofficial, release_id, type_sell):
    if type_sell == "master":
        url = f"{discogs_url}/sell/list?sort=listed%2Cdesc&limit=25&master_id={release_id}&format=Vinyl"
    else:
        url = f"{discogs_url}/sell/release/{release_id}?sort=listed%2Cdesc&limit=25"
    try:
        response = http.get(url, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logging.debug("Network error for release %s: %s" % (release_id, e))
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    table = soup.find_all("table", {"class": "mpitems"})
    if not table:
        logging.warning(
            "Scraping structure changed: table.mpitems not found for release %s (%s)" % (release_id, url)
        )
        return None

    rows = table[0].find_all("tr")
    for row in rows[1:]:
        item = row.find("a", {"class": "item_description_title"})
        price = row.find("span", {"class": "price"})

        if not item or not price:
            continue
        if "data-currency" not in price.attrs or "data-pricevalue" not in price.attrs:
            logging.warning(
                "Scraping structure changed: span.price missing data attributes for release %s" % release_id
            )
            continue
        if disable_unofficial and "Unofficial" in item.get_text():
            continue

        media_condition = "N/A"
        condition_p = row.find("p", {"class": "item_condition"})
        if condition_p:
            for span in condition_p.find_all("span"):
                classes = span.get("class", [])
                if (
                    "mplabel" not in classes
                    and "item_sleeve_condition" not in classes
                    and "has-tooltip" not in classes
                ):
                    text = "".join(t for t in span.strings if t.parent == span).strip()
                    if text:
                        media_condition = text
                        break

        sleeve_condition = "N/A"
        sleeve_span = row.find("span", {"class": "item_sleeve_condition"})
        if sleeve_span:
            sleeve_condition = sleeve_span.get_text(strip=True)

        shipping_from = "N/A"
        seller_info = row.find("td", {"class": "seller_info"})
        if seller_info:
            for li in seller_info.find_all("li"):
                if "Ships From:" in li.get_text():
                    shipping_from = li.get_text(strip=True).replace("Ships From:", "").strip()
                    break

        return {
            "id": re.search(r"\d+", item["href"]).group(),
            "price": "{} {}".format(price["data-currency"], price["data-pricevalue"]),
            "url": "https://www.discogs.com{}".format(item["href"]),
            "media_condition": media_condition,
            "sleeve_condition": sleeve_condition,
            "shipping_from": shipping_from,
        }

    logging.debug("No eligible listings for release %s" % release_id)
    return None


def scrap_data(d, http, discogs_url, disable_unofficial, bot, chat_id, release_list):
    """
    Checks all releases in parallel.
    Returns dict {release_id: data_last_sell} for items with new listings.
    Sends Telegram notifications for new items.
    """

    def check_one(item):
        type_sell = item.get("type") or "release"
        return check_sales(http, discogs_url, disable_unofficial, item["release_id"], type_sell)

    updates = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_to_item = {pool.submit(check_one, item): item for item in release_list}
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                data_last_sell = future.result()
            except Exception as e:
                logging.error("Error checking release %s: %s" % (item["release_id"], e))
                continue

            if data_last_sell:
                if not item["last_sell"] or int(data_last_sell["id"]) > int(item["last_sell"]["id"]):
                    logging.info("New item for %s - %s" % (item["artist"], item["title"]))
                    suggestion = get_suggestion_price(d, item["release_id"])
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
                    if "image" in item:
                        send_msg(bot, chat_id, text, photo=item["image"])
                    else:
                        send_msg(bot, chat_id, text, disable_web_page_preview=True)
                    updates[item["release_id"]] = data_last_sell
                else:
                    logging.info("Not new item for %s - %s" % (item["artist"], item["title"]))
            else:
                logging.info("Nothing available for %s - %s" % (item["artist"], item["title"]))

    return updates
