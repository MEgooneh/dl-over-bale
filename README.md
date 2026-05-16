# DL Over Bale

Move files through Bale with two services:

- `sender`: runs on a host with normal internet access
- `receiver`: runs on a host that serves the final download link

Both services use:

- one Bale bot
- one bot token
- one Bale channel

## Bale Setup

1. Create a channel in Bale.
2. Create a bot with `@botfather`.
3. Enable `اضافه شدن به گروه` for that bot.
4. Add the bot to the channel.
5. Make the bot a channel admin.
6. Copy the bot token and the channel id.

## Setup

1. Copy `.env.example` to `.env` on both hosts.
2. Fill these values:
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
3. On the sender host, set:
   - `RECEIVER_INGEST_BASE_URL=http://RECEIVER_IP:8090`
4. On the receiver host, set:
   - `SENDER_CONTROL_BASE_URL=http://SENDER_IP:8091`
5. If the host cannot reach the default Debian package servers during `docker build`, set:
   - `APT_MIRROR=...`

The current tested defaults can stay as they are:

- `TRANSFER_CHUNK_SIZE=12582912`
- `UPLOAD_RETRIES=8`
- `UPLOAD_COMPLETE_SETTLE_SECONDS=30`

## Deploy

On the receiver host:

```bash
docker compose --env-file .env -f docker-compose.receiver.yml up -d --build
```

On the sender host:

```bash
docker compose --env-file .env -f docker-compose.sender.yml up -d --build
```

## Network

- sender must reach receiver `:8090`
- receiver must reach sender `:8091`
- users must reach receiver download proxy `:8080`

Use a private or otherwise reachable peer address for `RECEIVER_INGEST_BASE_URL` and `SENDER_CONTROL_BASE_URL`.

## Use

Send a URL to the bot in a private chat.
