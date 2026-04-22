# DL Over Bale

Move files through Bale. The sender downloads and uploads chunks. The receiver rebuilds files and serves short-lived protected links.

## Deploy It Like This

- Run `sender` outside Iran.
- Give `sender` normal access to the global internet.
- Run `receiver` inside Iran.
- Put both bots in the same Bale target/update channel flow.

Use these files:

- `docker-compose.sender.yml`: sender host outside Iran
- `docker-compose.receiver.yml`: receiver host inside Iran
- `docker-compose.yml`: all-in-one local test stack

## Quick Start

1. Copy `.env.example` to `.env`.
2. Fill these values:
   - `SENDER_BOT_TOKEN`
   - `RECEIVER_BOT_TOKEN`
   - `ARCHIVE_PASSWORD`
   - `CHANNEL_TARGET_CHAT_ID`
   - `CHANNEL_UPDATES_CHAT_ID`
   - `ALLOWED_USERNAMES` or `ALLOWED_USER_IDS`
   - `PUBLIC_DOWNLOAD_BASE_URL`
   - `DOWNLOAD_LINK_SECRET`
   - `URL_RESPONSE_PASSWORD`
   - `DOWNLOAD_BASIC_AUTH_USER`
   - `DOWNLOAD_BASIC_AUTH_PASSWORD`
3. On the outside-Iran server:

```bash
docker compose -f docker-compose.sender.yml up -d --build
```

4. On the Iran server:

```bash
docker compose -f docker-compose.receiver.yml up -d --build
```

5. Ask the sender bot for a file or URL.

## Before You Start

- Make sure the sender host can reach the public internet.
- Make sure the receiver host can serve `PUBLIC_DOWNLOAD_BASE_URL`.
- Use strong secrets. Do not reuse simple passwords.
- Set `ALLOWED_USERNAMES` or `ALLOWED_USER_IDS`. Without that, anyone who can message the sender bot could use it.

## Local Test

Use the all-in-one stack only for local testing:

```bash
docker compose up -d --build
```

## Generic `yt-dlp` Configuration

The sender passes URLs directly to `yt-dlp`.

- `YTDLP_PROXY`
- `YTDLP_COOKIE_FILE`
- `YTDLP_COOKIE_TEXT`
- `YTDLP_COOKIE_TEXT_B64`
- `YTDLP_COOKIES_FROM_BROWSER`
- `YTDLP_EXTRA_OPTS_JSON`

Example:

```bash
YTDLP_EXTRA_OPTS_JSON={"extractor_args":{"generic":{"impersonate":["chrome"]}}}
```

`YTDLP_EXTRA_OPTS_JSON` is optional. It lets advanced users add raw `yt-dlp` options without editing the app.

## Helper Files

- `python text_sender.py` sends a test message with `BOT_TOKEN` and `TARGET_CHAT_ID`
- `python text_receiver.py` prints matching updates with `BOT_TOKEN` and `SOURCE_CHAT_ID`
