import logging
import time

from curl_cffi import requests as curl_requests

from discoger import scrap


def new_session():
    # curl_cffi firefox impersonation: chrome profile gets intermittent 403s
    # on /sell/list (masters), firefox passes first try on both endpoints.
    return curl_requests.Session(impersonate="firefox")


NEW_SELL_TEXT = (
    "**New release for:**\n"
    "%s - %s\n"
    "Price: %s\n"
    "Recommended price: %s\n"
    "Media: %s\n"
    "Sleeve: %s\n"
    "Shipping from: %s\n"
    "%s"
)


class Checker:
    """Runs the sale checks over the user databases.

    notify(chat_id, text, **kwargs) must return False when the user blocked
    the bot (same contract as utils.send_msg).
    """

    def __init__(self, d, dbs, notify, disable_unofficial=True, admin_chat_id=None,
                 discogs_url="https://www.discogs.com", pause=0.2):
        self.d = d
        self.dbs = dbs
        self.notify = notify
        self.disable_unofficial = disable_unofficial
        self.admin_chat_id = admin_chat_id
        self.discogs_url = discogs_url
        # ponytail: rate pacing between checks (0.2s ≈ 30s cycle for 40 releases),
        # raise back toward 1s if Cloudflare 403s come back; set to 0 in tests
        self.pause = pause
        # ponytail: long-lived session, renewed only after Cloudflare failures.
        self.http = new_session()

    def process_releases(self, chat_id, release_list):
        """Check all releases sequentially, notify on new listings.

        Returns (updates: dict {release_id: data}, bot_blocked: bool, stats: dict).
        bot_blocked is True if a send attempt revealed the user blocked the bot;
        in that case the caller should delete the user's DB.
        """
        updates = {}
        bot_blocked = False
        stats = {"checked": 0, "errors": 0, "cf_errors": 0}
        consecutive_cf = 0

        for item in release_list:
            if bot_blocked:
                break
            type_sell = item.get("type") or "release"
            stats["checked"] += 1
            try:
                data_last_sell = scrap.check_sales(
                    self.http, self.discogs_url, self.disable_unofficial,
                    item["release_id"], type_sell,
                )
            except Exception as e:
                logging.error("Error checking release %s: %s" % (item["release_id"], e))
                stats["errors"] += 1
                if isinstance(e, scrap.ScrapeError) and e.cloudflare:
                    stats["cf_errors"] += 1
                    consecutive_cf += 1
                    if consecutive_cf >= 5:
                        logging.error("%s consecutive Cloudflare blocks, aborting cycle for user %s" % (consecutive_cf, chat_id))
                        break
                time.sleep(self.pause)
                continue

            consecutive_cf = 0

            if data_last_sell:
                if not item["last_sell"] or int(data_last_sell["id"]) > int(item["last_sell"]["id"]):
                    logging.info("New item for %s - %s" % (item["artist"], item["title"]))
                    suggestion = scrap.get_suggestion_price(self.d, item["release_id"])
                    text = NEW_SELL_TEXT % (
                        item["artist"],
                        item["title"],
                        data_last_sell["price"],
                        suggestion,
                        data_last_sell["media_condition"],
                        data_last_sell["sleeve_condition"],
                        data_last_sell["shipping_from"],
                        data_last_sell["url"],
                    )
                    sent = self.notify(chat_id, text, photo=item.get("image") or None,
                                       disable_web_page_preview=not item.get("image"))
                    if not sent:
                        bot_blocked = True
                        break
                    updates[item["release_id"]] = data_last_sell
                else:
                    logging.info("Not new item for %s - %s" % (item["artist"], item["title"]))
            else:
                logging.info("Nothing available for %s - %s" % (item["artist"], item["title"]))

            time.sleep(self.pause)

        return updates, bot_blocked, stats

    def check_user(self, chat_id):
        logging.info("Check user list %s" % chat_id)

        with self.dbs.lock(chat_id):
            db = self.dbs.open(chat_id)
            release_list = list(db.get("release_list") or [])
            stored_chat_id = db.get("chat_id") or chat_id

        if not release_list:
            return {"checked": 0, "errors": 0, "cf_errors": 0}

        image_updates = {}
        for item in release_list:
            if not item.get("image"):
                image = scrap.fetch_image(self.d, item["release_id"])
                if image:
                    item["image"] = image
                    image_updates[item["release_id"]] = image
                    logging.info("Fetched missing image for release %s" % item["release_id"])

        if image_updates:
            with self.dbs.lock(chat_id):
                db = self.dbs.open(chat_id)
                for i, item in enumerate(db["release_list"]):
                    if item["release_id"] in image_updates:
                        db["release_list"][i]["image"] = image_updates[item["release_id"]]
                db.save()

        updates, bot_blocked, stats = self.process_releases(stored_chat_id, release_list)

        if bot_blocked:
            self.dbs.delete(chat_id)
            logging.info("User %s blocked the bot, removed from database" % chat_id)
        elif updates:
            with self.dbs.lock(chat_id):
                db = self.dbs.open(chat_id)
                for i, item in enumerate(db["release_list"]):
                    if item["release_id"] in updates:
                        db["release_list"][i]["last_sell"] = updates[item["release_id"]]
                db.save()

        return stats

    def check_cycle(self):
        logging.info("Check all lists")
        total = {"checked": 0, "errors": 0, "cf_errors": 0}
        for chat_id in self.dbs.chat_ids():
            stats = self.check_user(chat_id)
            for key in total:
                total[key] += stats[key]
        logging.info(
            "Check cycle done: %s/%s checks failed (%s Cloudflare)"
            % (total["errors"], total["checked"], total["cf_errors"])
        )
        if total["cf_errors"]:
            logging.warning("Renewing HTTP session after Cloudflare failures")
            self.http = new_session()
        if total["errors"] and self.admin_chat_id:
            self.notify(
                self.admin_chat_id,
                "⚠️ Discoger: %s/%s checks en échec ce cycle (dont %s Cloudflare 403)"
                % (total["errors"], total["checked"], total["cf_errors"]),
            )
