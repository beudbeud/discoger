from bs4 import BeautifulSoup
import re
import logging
import discogs_client


class DiscogsScraper:
    def __init__(self, url, d, http):
        response = http.get(url, timeout=10)
        response.raise_for_status()
        self.soup = BeautifulSoup(response.text, "html.parser")
        self.d = d

        release_page = self.soup.select("a.release-page")
        if not release_page:
            logging.warning("Scraping structure changed: a.release-page not found at %s" % url)
            raise ValueError("Cannot find release-page link at %s" % url)
        self.release_id = re.findall(r"\d+", release_page[0]["href"])[0]

    @property
    def media_id(self) -> str:
        return self.release_id

    @property
    def media_condition(self) -> str:
        nodes = self.soup.select("strong:-soup-contains('Media:')")
        if not nodes:
            logging.warning("Scraping structure changed: Media field not found")
            return "N/A"
        media_html = nodes[0].find_next_sibling("span")
        if not media_html:
            logging.warning("Scraping structure changed: Media sibling span not found")
            return "N/A"
        media_text = re.split(r"\W+", media_html.text.strip())
        if len(media_text) < 2:
            logging.warning("Scraping structure changed: unexpected Media text format: %r" % media_html.text)
            return media_text[0] if media_text else "N/A"
        return f"{media_text[0]} ({media_text[1]})"

    @property
    def sleeve_condition(self) -> str:
        nodes = self.soup.select("strong:-soup-contains('Sleeve:')")
        if not nodes:
            return "N/A"
        sibling = nodes[0].next_sibling
        if sibling is None:
            logging.warning("Scraping structure changed: Sleeve sibling not found")
            return "N/A"
        return sibling.strip()

    @property
    def shipping_from(self) -> str:
        nodes = self.soup.select("strong:-soup-contains('Item Ships From:')")
        if not nodes:
            logging.warning("Scraping structure changed: 'Item Ships From' field not found")
            return "N/A"
        sibling = nodes[0].next_sibling
        if sibling is None:
            logging.warning("Scraping structure changed: 'Item Ships From' sibling not found")
            return "N/A"
        return sibling.strip()

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
