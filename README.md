# Discoger

Telegram bot for checking if there are new sell in one specific list on Discogs

## How to use it

### Installation

Installation is in three steps, the first is getting credentials from Discogs and Telegram. 
You need to create a [Token](https://www.discogs.com/fr/settings/developers).

For Telegram you need contact []@BotFather](https://t.me/botfather) and follow a few simple steps for get your authorization token.

### Configuration

After that you need create config.ini file

```
[DEFAULT]
schedule_time = 30

[discogs]
secret = dbPVkGbCVVffggfgkdfgmlkknzezsbhmscskncno
 
[telegram]
token = 1766763279:AAFwufBsdfdsfgdfsgfgsfsgdfgsdf
```

### Docker

```
docker container run -v ./:/root/.config/discoger beudbeud/discoger
```
