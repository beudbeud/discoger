# Discoger

Discoger Bot is a Telegram bot that allows you to be notified when a new sale for a vinyl in your Discogs wantlist is available.

## Features

- Follow Discogs releases or masters and get a Telegram message when a new listing appears (price, condition, shipping origin, suggested price)
- Synchronize your Discogs wantlist (`/wantlist`)
- Scheduled checks (every `schedule_time` minutes) with Cloudflare-resilient scraping (curl_cffi with browser impersonation, automatic retries)
- Optional admin alert on Telegram when checks fail (e.g. Cloudflare blocking)

## Usage

1. Search for the Telegram bot "Discoger" or click [this link](https://t.me/Discogers_bot) to open a conversation with the bot.

## How to use it

### Installation

Installation is in three steps, the first is getting credentials from Discogs and Telegram.
You need to create a [Token](https://www.discogs.com/fr/settings/developers).

For Telegram you need contact [@BotFather](https://t.me/botfather) and follow a few simple steps for get your authorization token.

### Configuration

After that you need create config.ini file

```
[DEFAULT]
schedule_time = 30
disable_unofficial = True
log_level = INFO

[discogs]
secret = dbPVkGbCVVffggfgkdfgmlkknzezsbhmscskncno

[telegram]
token = 1766763279:AAFwufBsdfdsfgdfsgfgsfsgdfgsdf
admin_chat_id =
```

- `schedule_time`: minutes between two check cycles
- `disable_unofficial`: skip "Unofficial" listings
- `admin_chat_id` (optional): your Telegram chat id; if set, you receive a summary message when a check cycle has failures (e.g. `⚠️ Discoger: 5/20 checks en échec ce cycle (dont 5 Cloudflare 403)`). Leave empty to disable.

### Docker

```
docker container run -v ./:/root/.config/discoger beudbeud/discoger
```

### Upgrade

If you use the old version of discoger you need to update your database.

Example of database for the version 1.1

```
chat_id: 249125421
release_list:
- release_id: '288931'
  artist: Aloud
  title: Track Lifting
  url: https://www.discogs.com/fr/master/288931-Julian-Jay-Savarin-Waiters-On-The-Dance
  type: master
  last_sell: {}
- release_id: '26741825'
  artist: Metallica
  title: 72 Seasons
  url: https://www.discogs.com/fr/release/26741825-Metallica-72-Seasons
  type: release
  last_sell: {}
```
