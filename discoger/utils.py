import logging


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


def send_msg(bot, chat_id, text, photo=None, parse_mode="markdown", disable_web_page_preview=False, **kwargs):
    """Send a Telegram message or photo. Returns False if the user blocked the bot, True otherwise."""
    try:
        if photo:
            bot.send_photo(chat_id=chat_id, photo=photo, parse_mode=parse_mode, caption=text, **kwargs)
        else:
            bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                **kwargs,
            )
        return True
    except Exception as inst:
        if "bot was blocked by the user" in str(inst):
            logging.info("Bot blocked by user %s, muting notifications" % chat_id)
            return False
        logging.warning("user: %s, %s" % (chat_id, inst))
        return True
