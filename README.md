# DL Over Bale

`DL Over Bale` transfers files through Bale by splitting uploads on the sender side and rebuilding them on the receiver side. It supports direct file URLs and generic `yt-dlp` downloads without hardcoded site rules.

## What It Includes

- `sender.py`: polls private messages, validates access, downloads content, chunks it, and uploads chunks to Bale
- `receiver.py`: watches the configured Bale channel, rebuilds files, stores them on disk, and publishes protected download links
- `docker-compose.yml`: local stack for sender, receiver, MinIO, and the protected download proxy

## Prerequisites

- Docker and Docker Compose
- Two Bale bots: one for the sender, one for the receiver
- A Bale chat/channel the bots can access
- Strong secrets for `ARCHIVE_PASSWORD`, `DOWNLOAD_LINK_SECRET`, and `URL_RESPONSE_PASSWORD`

## Setup

1. Fill `.env` from `.env.example`.
2. Set these required values at minimum:
   - `SENDER_BOT_TOKEN`
   - `RECEIVER_BOT_TOKEN`
   - `ARCHIVE_PASSWORD`
   - `CHANNEL_TARGET_CHAT_ID`
   - `CHANNEL_UPDATES_CHAT_ID`
   - `ALLOWED_USERNAMES` or `ALLOWED_USER_IDS`
   - `MINIO_ROOT_USER`
   - `MINIO_ROOT_PASSWORD`
   - `PUBLIC_DOWNLOAD_BASE_URL`
   - `DOWNLOAD_LINK_SECRET`
   - `URL_RESPONSE_PASSWORD`
   - `DOWNLOAD_BASIC_AUTH_USER`
   - `DOWNLOAD_BASIC_AUTH_PASSWORD`
3. Start the stack:

```bash
docker compose up -d --build
```

The sender bot accepts requests from allowed users, uploads chunked payloads to Bale, and the receiver reconstructs them into protected download links served from `/files/...`.

## Generic `yt-dlp` Configuration

The sender passes supported URLs straight to `yt-dlp`. Optional knobs:

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

`YTDLP_EXTRA_OPTS_JSON` is merged into the base options object, so advanced users can supply extractor-specific settings without changing application code.

## Local Helpers

- `python text_sender.py` sends a test message with `BOT_TOKEN` and `TARGET_CHAT_ID`
- `python text_receiver.py` prints matching updates with `BOT_TOKEN` and `SOURCE_CHAT_ID`

## Notes

- The sender requires at least one allowed username or user ID.
- The receiver requires a reachable public `PUBLIC_DOWNLOAD_BASE_URL`.
- The public repo intentionally does not include deployment-specific CI/CD wiring.
