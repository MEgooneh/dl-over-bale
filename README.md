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
2. Fill the variables below.

## Environment Variables

Both hosts:

- `CHANNEL_CHAT_ID`: Bale channel id used for file parts and control messages.
- `ARCHIVE_PASSWORD`: password used for the split `7z` archives.
- `DOWNLOAD_LINK_SECRET`: secret used to sign the final download URLs.
- `URL_RESPONSE_PASSWORD`: secret used inside transport payload encryption.
- `DOWNLOAD_BASIC_AUTH_USER`: username that protects the receiver download endpoint.
- `DOWNLOAD_BASIC_AUTH_PASSWORD`: password that protects the receiver download endpoint.

Sender host:

- `SENDER_BOT_TOKEN`: token of the sender bot that users message directly.
- `ALLOWED_USERNAMES`: comma-separated Bale usernames allowed to use the sender bot.
- `ALLOWED_USER_IDS`: comma-separated Bale user ids allowed to use the sender bot.

Receiver host:

- `RECEIVER_BOT_TOKEN`: token of the receiver bot that reads the Bale channel.
- `PUBLIC_DOWNLOAD_BASE_URL`: public base URL of the receiver download endpoint.

Optional network and proxy settings:

- `DOWNLOAD_NGINX_PORT`: local port exposed by the receiver download proxy.
- `DOWNLOAD_RATE_LIMIT_RPS`: request-per-second rate limit for downloads.
- `DOWNLOAD_RATE_LIMIT_BURST`: burst size for the download rate limiter.
- `DOWNLOAD_RATE_LIMIT_CONNECTIONS`: max simultaneous download connections per client.
- `TRUSTED_PROXY_CIDRS`: trusted proxy CIDRs for real client IP handling.
- `APT_MIRROR`: alternate Debian mirror for hosts that cannot use the default one.
- `LOG_LEVEL`: log level, for example `INFO` or `DEBUG`.
- `YTDLP_PROXY`: proxy used by sender downloads.
- `YTDLP_COOKIE_FILE`: cookie file path passed to `yt-dlp`.
- `YTDLP_COOKIE_TEXT`: raw cookie file content passed inline.
- `YTDLP_COOKIE_TEXT_B64`: base64-encoded cookie file content.
- `YTDLP_COOKIES_FROM_BROWSER`: browser cookie import setting for `yt-dlp`.
- `YTDLP_EXTRA_OPTS_JSON`: extra `yt-dlp` options as JSON.

Optional runtime tuning:

- `DOWNLOAD_FILE_TTL_MINUTES`: how long generated downloads stay on disk.
- `DOWNLOAD_CLEAN_INTERVAL_SECONDS`: how often the download cleanup job runs.
- `PUBLIC_DOWNLOAD_RETENTION_SECONDS`: how long public download files are kept.
- `PUBLIC_DOWNLOAD_CLEAN_INTERVAL_SECONDS`: how often public file cleanup runs.
- `DOWNLOAD_LINK_TTL_SECONDS`: lifetime of a generated download link.
- `DEFAULT_REQUEST_DOWNLOAD_LIMIT_BYTES`: default max source file size per request.
- `TRANSFER_CHUNK_SIZE`: sender chunk size before each Bale upload.
- `UPLOAD_RETRIES`: sender upload retry count for each chunk.
- `MISSING_PART_RETRIES`: receiver retry count when parts are missing.
- `WORKER_COUNT`: number of worker threads per service.
- `MAX_QUEUE_SIZE`: max queued requests per service.
- `COMPLETION_WATCHDOG_INTERVAL_SECONDS`: sender completion retry loop interval.
- `UPLOAD_CONFIRMATION_RETRY_SECONDS`: sender wait time before resending completion.
- `UPLOAD_CONFIRMATION_MAX_RETRIES`: max sender completion resends.
- `CHUNK_MESSAGE_RETENTION_SECONDS`: how long sender chunk message records are kept.
- `CHUNK_MESSAGE_CLEAN_INTERVAL_SECONDS`: how often sender chunk message cleanup runs.
- `STATS_ADMIN_USERNAMES`: usernames allowed to use sender stats commands.
- `STATS_ADMIN_USER_IDS`: user ids allowed to use sender stats commands.

Helper-script only:

- `BOT_TOKEN`: bot token used by the low-level helper scripts.
- `TARGET_CHAT_ID`: target chat for `dl-over-bale-text-sender`.
- `SOURCE_CHAT_ID`: source chat filter for `dl-over-bale-text-receiver`.
- `MESSAGE_TEXT`: custom text for the helper sender script.

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
