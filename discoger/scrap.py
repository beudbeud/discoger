from bs4 import BeautifulSoup
import requests
import re
import logging


class DiscogsScraper:
    def __init__(self, url, d):
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1)"}
        req = requests.get(url, headers=headers)
        soup = BeautifulSoup(req.text, "html.parser")
        self.soup = soup
        self.release_id = re.findall(r"\d+", soup.select("a.release-page")[0]["href"])[
            0
        ]
        self.d = d

    @property
    def media_id(self) -> str:
        return self.release_id

    @property
    def media_condition(self) -> str:
        media_html = self.soup.select("strong:-soup-contains('Media:')")[
            0
        ].find_next_sibling("span")
        media_text = re.split(r"\W+", media_html.text.strip())
        return f"{media_text[0]} ({media_text[1]})"

    @property
    def sleeve_condition(self) -> str:
        if not self.soup.select("strong:-soup-contains('Sleeve:')"):
            return "N/A"
        return self.soup.select("strong:-soup-contains('Sleeve:')")[
            0
        ].next_sibling.strip()

    @property
    def shipping_from(self) -> str:
        return self.soup.select("strong:-soup-contains('Item Ships From:')")[
            0
        ].next_sibling.strip()

    @property
    def suggestion_price(self) -> str:
        _info = self.d.release(self.release_id)
        try:
            value = _info.price_suggestions.mint.value
            currency = _info.price_suggestions.mint.currency
            return "%s %s" % (round(value, 2), currency)
        except Exception:
            return "Unknow"


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
        release_info = dict()
        if self.media_type == "master":
            try:
                master_release_info = self.discogs.master(self.release_id)
                all_info = self.discogs.release(master_release_info.main_release.id)
            except self.d.exceptions.DiscogsAPIError as e:
                logging.error("Error, %s" % e)
        else:
            try:
                all_info = self.discogs.release(self.release_id)
            except self.d.exceptions.DiscogsAPIError as e:
                logging.error("Error, %s" % e)
        release_info["release_id"] = self.release_id
        release_info["artist"] = all_info.artists[0].name
        release_info["title"] = all_info.title
        release_info["url"] = self.url
        release_info["type"] = self.media_type
        release_info["image"] = all_info.images[0]["uri"]
        release_info["last_sell"] = dict()
        return release_info
