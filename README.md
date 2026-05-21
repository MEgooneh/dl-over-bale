# DL Over Bale

Move files through Bale with:

- `sender`: downloads direct files or [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)-supported URLs, then uploads parts to a Bale channel
- `receiver`: reads the same Bale channel, rebuilds the file, and serves the final download link

For each URL, `sender` first tries a direct file download. If the URL is not a directly downloadable file, it falls back to `yt-dlp`.

## Setup

You need:

- one Bale channel
- two Bale bots
  - one sender bot
  - one receiver bot

Host layout:

- Run `sender` outside Iran; this is required for accessing international download sources.
- Run `receiver` inside Iran so users get the final download link from an Iran-based server.

For both bots:

1. Create them with `@botfather`.
2. Enable `اضافه شدن به گروه`.
3. Add both bots to the same channel.
4. Make both bots channel admins.

Then create a `.env` file. For the smallest working setup, fill only:

```env
SENDER_BOT_TOKEN=
RECEIVER_BOT_TOKEN=
CHANNEL_CHAT_ID=
URL_RESPONSE_PASSWORD=
ALLOWED_USERNAMES=
ALLOWED_USER_IDS=
PUBLIC_DOWNLOAD_BASE_URL=http://localhost:8080
```

Set either `ALLOWED_USERNAMES` or `ALLOWED_USER_IDS` for the sender bot. The optional settings below add protection for production or shared deployments.

## Environment Variables

Required on both hosts:

- `CHANNEL_CHAT_ID`: Bale channel id used for file parts and control messages.
- `URL_RESPONSE_PASSWORD`: shared secret used to encrypt bot control messages and part captions. Keep this set and identical on sender and receiver.

Required on the sender host:

- `SENDER_BOT_TOKEN`: token of the sender bot that users message directly.
- `ALLOWED_USERNAMES`: comma-separated Bale usernames allowed to use the sender bot.
- `ALLOWED_USER_IDS`: comma-separated Bale user ids allowed to use the sender bot.
- `PUBLIC_DOWNLOAD_BASE_URL`: optional fallback used to expand path-only receiver completion messages.

Required on the receiver host:

- `RECEIVER_BOT_TOKEN`: token of the receiver bot that reads the Bale channel.
- `PUBLIC_DOWNLOAD_BASE_URL`: public base URL of the receiver download endpoint.

Optional protections:

- `ARCHIVE_PASSWORD`: encrypts the split `7z` chunks uploaded to Bale. Leave it empty for simpler setup; set a strong shared password if channel storage or admins should not see file contents. When set, it must be at least 24 characters and include uppercase, lowercase, digit, and symbol characters.
- `DOWNLOAD_LINK_SECRET`: signs generated download URLs and adds expiry. Leave it empty for plain stable URLs; set it to make copied links expire after `DOWNLOAD_LINK_TTL_SECONDS`.
- `DOWNLOAD_BASIC_AUTH_USER` and `DOWNLOAD_BASIC_AUTH_PASSWORD`: add HTTP basic auth in front of downloads. Leave both empty for one-click downloads; set both if links may be forwarded or exposed.

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

For cookie setup details, see yt-dlp's ["How do I pass cookies to yt-dlp?"](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp) documentation.

Optional runtime tuning:

- `DOWNLOAD_FILE_TTL_MINUTES`: how long generated downloads stay on disk.
- `DOWNLOAD_CLEAN_INTERVAL_SECONDS`: how often the download cleanup job runs.
- `PUBLIC_DOWNLOAD_RETENTION_SECONDS`: how long public download files are kept.
- `PUBLIC_DOWNLOAD_CLEAN_INTERVAL_SECONDS`: how often public file cleanup runs.
- `DOWNLOAD_LINK_TTL_SECONDS`: lifetime of a generated signed download link when `DOWNLOAD_LINK_SECRET` is set.
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
