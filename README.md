# DL Over Bale

`dl-over-bale` moves downloaded files through Bale using two Python services:

- `sender`: runs on a host with normal internet access, downloads the source URL, chunks it, and uploads the parts to Bale.
- `receiver`: runs on a host that can serve downloads locally, rebuilds the file, stores it, and exposes a short-lived download URL.

The repository is now Docker-first:

- Python `3.13`
- `uv` for dependency management and locking
- `ruff` for linting and formatting
- `yt-dlp` nightly for the sender service

## Architecture

- `docker-compose.sender.yml`: sender-only deployment
- `docker-compose.receiver.yml`: receiver-only deployment
- `docker-compose.yml`: combined local stack for one-machine testing
- `src/dl_over_bale/`: packaged application code
- `deploy/nginx/`: protected download proxy image
- `deploy/downloads/`: download cleanup image

## Quick Start

1. Copy the environment file:

```bash
cp .env.example .env
```

2. Fill the required values in `.env`:

- `BOT_TOKEN`
- `CHANNEL_CHAT_ID`
- `ARCHIVE_PASSWORD`
- `INGEST_TOKEN`
- `URL_RESPONSE_PASSWORD`
- `DOWNLOAD_LINK_SECRET`
- `DOWNLOAD_BASIC_AUTH_USER`
- `DOWNLOAD_BASIC_AUTH_PASSWORD`
- `ALLOWED_USERNAMES` or `ALLOWED_USER_IDS`
- `PUBLIC_DOWNLOAD_BASE_URL`

3. Set the cross-service URLs:

- On the sender host: `RECEIVER_INGEST_BASE_URL=http://RECEIVER_IP:8090`
- On the receiver host: `SENDER_CONTROL_BASE_URL=http://SENDER_IP:8091`

Use the peer address that is actually routable from the other host. If the two hosts already have a private tunnel, prefer that private address over the public IP.

## Deploy With Docker

Receiver host:

```bash
docker compose --env-file .env -f docker-compose.receiver.yml up -d --build
```

Sender host:

```bash
docker compose --env-file .env -f docker-compose.sender.yml up -d --build
```

Local one-machine test:

```bash
docker compose --env-file .env up -d --build
```

The runtime images are self-contained. Deployment only needs Docker, the compose file, and environment variables.

## Bale Setup

1. Create a Bale channel.
2. Create a bot with `@botfather`.
3. Enable `اضافه شدن به گروه` for the bot.
4. Add the bot to the channel.
5. Promote the bot to channel admin.
6. Copy the bot token and the channel id into `.env`.

## `yt-dlp` Nightly

The sender image installs `yt-dlp` from the official nightly builds channel. The current lockfile resolves the latest nightly available when it was generated.

Optional sender-side environment variables:

- `YTDLP_PROXY`
- `YTDLP_COOKIE_FILE`
- `YTDLP_COOKIE_TEXT`
- `YTDLP_COOKIE_TEXT_B64`
- `YTDLP_COOKIES_FROM_BROWSER`
- `YTDLP_EXTRA_OPTS_JSON`
- `TRANSFER_CHUNK_SIZE`
- `UPLOAD_RETRIES`
- `UPLOAD_COMPLETE_SETTLE_SECONDS`

Example:

```bash
YTDLP_EXTRA_OPTS_JSON={"extractor_args":{"generic":{"impersonate":["chrome"]}}}
```

For Bale upload stability, the current defaults use:

- `TRANSFER_CHUNK_SIZE=12582912` (`12 MiB`)
- `UPLOAD_RETRIES=8`
- `UPLOAD_COMPLETE_SETTLE_SECONDS=30`

If Bale starts returning repeated `500` or `504` errors on `sendDocument`, lower `TRANSFER_CHUNK_SIZE` further before changing anything else.

## Development

Install the local environment:

```bash
uv sync --extra sender
```

Run the linters:

```bash
uv run ruff check .
uv run ruff format --check .
```

Run the helper scripts:

```bash
uv run dl-over-bale-text-sender
uv run dl-over-bale-text-receiver
```

Direct script execution still works from a checkout:

```bash
python sender.py
python receiver.py
```

## Updating Dependencies

- Refresh the lockfile: `uv lock --upgrade`
- Refresh `yt-dlp` nightly explicitly: `uv lock --upgrade-package yt-dlp`
- Rebuild images after updating dependencies: `docker compose build --no-cache`

## Security Notes

- Restrict bot access with `ALLOWED_USERNAMES` or `ALLOWED_USER_IDS`.
- Use strong values for `ARCHIVE_PASSWORD`, `INGEST_TOKEN`, `URL_RESPONSE_PASSWORD`, and `DOWNLOAD_LINK_SECRET`.
- Keep the sender control port and receiver ingest port reachable only by the corresponding peer host.
- Protect the receiver download proxy with strong basic auth credentials.

## Helper Scripts

- `dl-over-bale-text-sender`: sends a raw test message to a chat
- `dl-over-bale-text-receiver`: listens to raw Bale updates for debugging

These helpers are for low-level integration checks only. Normal deployments use the sender and receiver services.
