import re
import logging
import discogs_client
from bs4 import BeautifulSoup


def fetch_image(d, release_id):
    try:
        info = d.release(release_id)
        return info.images[0]["uri"] if info.images else None
    except Exception as e:
        logging.warning("Could not fetch image for release %s: %s" % (release_id, e))
        return None


def get_suggestion_price(d, release_id):
    try:
        _info = d.release(release_id)
        value = _info.price_suggestions.mint.value
        currency = _info.price_suggestions.mint.currency
        return "%s %s" % (round(value, 2), currency)
    except Exception as e:
        logging.warning("Could not fetch suggestion price for release %s: %s" % (release_id, e))
        return "Unknown"


def check_sales(http, discogs_url, disable_unofficial, release_id, type_sell):
    if type_sell == "master":
        url = f"{discogs_url}/sell/list?sort=listed%2Cdesc&limit=25&master_id={release_id}&format=Vinyl"
    else:
        url = f"{discogs_url}/sell/release/{release_id}?sort=listed%2Cdesc&limit=25"
    try:
        response = http.get(url, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logging.warning("Network error for release %s: %s" % (release_id, e))
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    table = soup.find_all("table", {"class": "mpitems"})
    if not table:
        logging.debug("No listings found for release %s" % release_id)
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


class DiscogerInfo:
    def __init__(self, url, d, release_id):
        self.url = url
        self.discogs = d

        if len(re.findall(r"\/master\/\d+", self.url)) == 1:
            self.media_type = "master"
        else:
            self.media_type = "release"

        self.release_id = release_id

    @property
    def release_info(self) -> dict:
        try:
            if self.media_type == "master":
                master = self.discogs.master(self.release_id)
                all_info = self.discogs.release(master.main_release.id)
            else:
                all_info = self.discogs.release(self.release_id)
        except discogs_client.exceptions.DiscogsAPIError as e:
            logging.error("Error fetching release %s: %s" % (self.release_id, e))
            raise

        return {
            "release_id": self.release_id,
            "artist": all_info.artists[0].name,
            "title": all_info.title,
            "url": self.url,
            "type": self.media_type,
            "image": all_info.images[0]["uri"] if all_info.images else None,
            "last_sell": dict(),
        }
