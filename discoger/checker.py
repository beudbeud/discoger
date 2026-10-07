import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from curl_cffi import requests as curl_requests

from discoger import scrap


# ponytail: Cloudflare flips which curl_cffi profile it challenges (chrome 403
# on /sell/list, then firefox 403 everywhere, then safari from the server IP
# in 2026-10). A Cloudflare 403 block moves to the next profile.
PROFILES = ["chrome", "safari"]


def new_session(profile):
    return curl_requests.Session(impersonate=profile)


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
                 discogs_url="https://www.discogs.com", pause=2.5, workers=1, cooldown=3600):
        self.d = d
        self.dbs = dbs
        self.notify = notify
        self.disable_unofficial = disable_unofficial
        self.admin_chat_id = admin_chat_id
        self.discogs_url = discogs_url
        # ponytail: per-worker pacing before each request. Discogs allows 25
        # unauthenticated requests/min (moving 60s window); 2.5s + request
        # time stays under it. 1s got 429s after ~10 requests. 0 in tests
        self.pause = pause
        # ponytail: pool threads live for the bot's lifetime, so the per-thread
        # sessions below stay long-lived too (renewed only after CF failures)
        self.pool = ThreadPoolExecutor(max_workers=workers)
        # ponytail: one block (403 after retries, or 429) pauses every check for
        # `cooldown` seconds: hammering a blocked IP only extends the block
        self.cooldown = cooldown
        self.blocked_until = 0
        self._local = threading.local()
        self._session_epoch = 0

    def _get_session(self):
        """One long-lived session per pool thread, recreated when the epoch bumps."""
        if getattr(self._local, "epoch", -1) != self._session_epoch:
            self._local.http = new_session(PROFILES[self._session_epoch % len(PROFILES)])
            self._local.epoch = self._session_epoch
        return self._local.http

    def renew_sessions(self):
        self._session_epoch += 1

    def process_releases(self, chat_id, release_list):
        """Check all releases sequentially, notify on new listings.

        Returns (updates: dict {release_id: data}, bot_blocked: bool, stats: dict).
        bot_blocked is True if a send attempt revealed the user blocked the bot;
        in that case the caller should delete the user's DB.
        """
        updates = {}
        bot_blocked = False
        stats = {"checked": 0, "errors": 0, "cf_errors": 0}

        def check_one(item):
            time.sleep(self.pause)
            return scrap.check_sales(
                self._get_session(), self.discogs_url, self.disable_unofficial,
                item["release_id"], item.get("type") or "release",
            )

        # ponytail: scraping runs in the pool, notifications and DB decisions
        # stay in this thread (as_completed loop is sequential)
        futures = {self.pool.submit(check_one, item): item for item in release_list}
        for future in as_completed(futures):
            if future.cancelled():
                continue
            item = futures[future]
            stats["checked"] += 1
            try:
                data_last_sell = future.result()
            except Exception as e:
                logging.error("Error checking release %s: %s" % (item["release_id"], e))
                stats["errors"] += 1
                if isinstance(e, scrap.ScrapeError) and e.cloudflare:
                    stats["cf_errors"] += 1
                    if not self.blocked():
                        self.block(rate_limited=e.rate_limited)
                    for f in futures:
                        f.cancel()
                continue

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
                        for f in futures:
                            f.cancel()
                        continue
                    updates[item["release_id"]] = data_last_sell
                else:
                    logging.info("Not new item for %s - %s" % (item["artist"], item["title"]))
            else:
                logging.info("Nothing available for %s - %s" % (item["artist"], item["title"]))

        return updates, bot_blocked, stats

    def blocked(self):
        return time.time() < self.blocked_until

    def block(self, rate_limited):
        self.blocked_until = time.time() + self.cooldown
        # a 429 is about pace, not fingerprint: keep the profile that passed
        if not rate_limited:
            self.renew_sessions()
        logging.error(
            "%s, pausing all checks for %s min (profile: %s)"
            % ("Rate limited (429)" if rate_limited else "Cloudflare block (403)",
               self.cooldown // 60, PROFILES[self._session_epoch % len(PROFILES)])
        )

    def check_user(self, chat_id):
        if self.blocked():
            logging.info("Checks paused after a block, skipping user %s" % chat_id)
            return {"checked": 0, "errors": 0, "cf_errors": 0}
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

    def due_chat_ids(self, interval, minute=None):
        """Users whose turn it is this minute: each user gets a fixed offset in
        the interval (chat_id modulo interval) so checks are spread out instead
        of hitting Discogs for everyone at once."""
        if minute is None:
            minute = int(time.time() // 60)
        return [c for c in self.dbs.chat_ids() if (int(c) + minute) % interval == 0]

    def check_cycle(self, chat_ids=None):
        if chat_ids is None:
            chat_ids = self.dbs.chat_ids()
        logging.info("Check lists for %s user(s)" % len(chat_ids))
        total = {"checked": 0, "errors": 0, "cf_errors": 0}
        for chat_id in chat_ids:
            if self.blocked():
                break
            stats = self.check_user(chat_id)
            for key in total:
                total[key] += stats[key]
        logging.info(
            "Check cycle done: %s/%s checks failed (%s Cloudflare)"
            % (total["errors"], total["checked"], total["cf_errors"])
        )
        if total["errors"] and self.admin_chat_id:
            self.notify(
                self.admin_chat_id,
                "⚠️ Discoger: %s/%s checks en échec ce cycle (dont %s Cloudflare 403 / 429)"
                % (total["errors"], total["checked"], total["cf_errors"]),
            )
