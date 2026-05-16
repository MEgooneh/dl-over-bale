# DL Over Bale

Move files through Bale with:

- `sender`: downloads the file and uploads parts to a Bale channel
- `receiver`: reads the same Bale channel, rebuilds the file, and serves the final download link

## Setup

You need:

- one Bale channel
- two Bale bots
  - one sender bot
  - one receiver bot

For both bots:

1. Create them with `@botfather`.
2. Enable `اضافه شدن به گروه`.
3. Add both bots to the same channel.
4. Make both bots channel admins.

Then:

1. Copy `.env.example` to `.env` on both hosts.
2. Set the same values on both hosts:
   - `CHANNEL_CHAT_ID`
   - `ARCHIVE_PASSWORD`
   - `DOWNLOAD_LINK_SECRET`
   - `URL_RESPONSE_PASSWORD`
   - `DOWNLOAD_BASIC_AUTH_USER`
   - `DOWNLOAD_BASIC_AUTH_PASSWORD`
3. On the sender host, set:
   - `SENDER_BOT_TOKEN`
   - `ALLOWED_USERNAMES` or `ALLOWED_USER_IDS`
4. On the receiver host, set:
   - `RECEIVER_BOT_TOKEN`
   - `PUBLIC_DOWNLOAD_BASE_URL`

The tested sender defaults are:

- `TRANSFER_CHUNK_SIZE=12582912`
- `UPLOAD_RETRIES=8`

## Deploy

On the receiver host:

```bash
docker compose --env-file .env -f docker-compose.receiver.yml up -d --build
```

On the sender host:

```bash
docker compose --env-file .env -f docker-compose.sender.yml up -d --build
```

## Use

Send a URL to the sender bot in a private chat.
