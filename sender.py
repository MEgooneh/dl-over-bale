#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import queue
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
import yt_dlp


LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dl-over-bale-sender")


def first_configured_id(raw: str) -> str:
    for item in raw.split(","):
        value = item.strip()
        if value:
            return value
    return ""


BOT_TOKEN = os.environ["BOT_TOKEN"]
ARCHIVE_PASSWORD = os.environ["ARCHIVE_PASSWORD"]

CHANNEL_TARGET_CHAT_ID = str(os.environ.get("CHANNEL_TARGET_CHAT_ID", "")).strip()
CHANNEL_UPDATES_CHAT_ID = str(os.environ.get("CHANNEL_UPDATES_CHAT_ID", "")).strip()
DB_PATH = Path(os.environ.get("DB_PATH", "/app/data/sender.sqlite3")).resolve()
WORK_ROOT = Path(os.environ.get("WORK_ROOT", "/var/tmp/dl_over_bale_sender")).resolve()
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "120"))
UPLOAD_TIMEOUT = float(os.environ.get("UPLOAD_TIMEOUT", "1800"))
UPLOAD_RETRIES = max(1, int(os.environ.get("UPLOAD_RETRIES", "4")))
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "30"))
ARCHIVE_VOLUME_SIZE = os.environ.get("ARCHIVE_VOLUME_SIZE", "20m")
DEFAULT_REQUEST_DOWNLOAD_LIMIT_BYTES = int(
    os.environ.get(
        "DEFAULT_REQUEST_DOWNLOAD_LIMIT_BYTES",
        os.environ.get("MAX_DIRECT_DOWNLOAD_SIZE", str(1 * 1024 * 1024 * 1024)),
    )
)
TRANSFER_CHUNK_SIZE = max(1, int(os.environ.get("TRANSFER_CHUNK_SIZE", str(18 * 1024 * 1024))))
WORKER_COUNT = max(1, int(os.environ.get("WORKER_COUNT", "8")))
MAX_QUEUE_SIZE = max(1, int(os.environ.get("MAX_QUEUE_SIZE", "1000")))
COMPLETION_WATCHDOG_INTERVAL_SECONDS = max(10, int(os.environ.get("COMPLETION_WATCHDOG_INTERVAL_SECONDS", "30")))
UPLOAD_CONFIRMATION_RETRY_SECONDS = max(30, int(os.environ.get("UPLOAD_CONFIRMATION_RETRY_SECONDS", "120")))
UPLOAD_CONFIRMATION_MAX_RETRIES = max(1, int(os.environ.get("UPLOAD_CONFIRMATION_MAX_RETRIES", "15")))
CHUNK_MESSAGE_RETENTION_SECONDS = max(3600, int(os.environ.get("CHUNK_MESSAGE_RETENTION_SECONDS", "86400")))
CHUNK_MESSAGE_CLEAN_INTERVAL_SECONDS = max(60, int(os.environ.get("CHUNK_MESSAGE_CLEAN_INTERVAL_SECONDS", "3600")))
ALLOWED_USERNAMES = {
    username.strip().lstrip("@").lower()
    for username in os.environ.get("ALLOWED_USERNAMES", "").split(",")
    if username.strip()
}
ALLOWED_USER_IDS = {
    user_id.strip()
    for user_id in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if user_id.strip()
}
STATS_ADMIN_USERNAMES = {
    username.strip().lstrip("@").lower()
    for username in os.environ.get("STATS_ADMIN_USERNAMES", "").split(",")
    if username.strip()
}
STATS_ADMIN_USER_IDS = {
    user_id.strip()
    for user_id in os.environ.get("STATS_ADMIN_USER_IDS", "").split(",")
    if user_id.strip()
}
ADMIN_CHAT_ID = (
    first_configured_id(os.environ.get("STATS_ADMIN_USER_IDS", ""))
)
USER_AGENT = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)
COOKIE_FILE = os.environ.get("YTDLP_COOKIE_FILE", "").strip()
COOKIE_TEXT = os.environ.get("YTDLP_COOKIE_TEXT", "").strip()
COOKIE_TEXT_B64 = os.environ.get("YTDLP_COOKIE_TEXT_B64", "").strip()
COOKIES_FROM_BROWSER = os.environ.get("YTDLP_COOKIES_FROM_BROWSER", "").strip()
YTDLP_PROXY = os.environ.get("YTDLP_PROXY", "").strip()
YTDLP_EXTRA_OPTS_JSON = os.environ.get("YTDLP_EXTRA_OPTS_JSON", "").strip()
DEFAULT_YTDLP_COOKIE_FILE = Path("/run/secrets/ytdlp.cookies.txt")
INLINE_COOKIE_PATH = Path("/tmp/dl-over-bale-ytdlp-cookies.txt")
DOWNLOAD_LINK_TTL_SECONDS = max(60, int(os.environ.get("DOWNLOAD_LINK_TTL_SECONDS", "10800")))
URL_RESPONSE_PASSWORD = os.environ.get("URL_RESPONSE_PASSWORD", "").strip()
YTDLP_FORMAT_CANDIDATES = (
    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
    "bestvideo+bestaudio/best",
    "bestvideo*+bestaudio/best",
    "best",
)

BALE_API = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ".,!?;:)]}'\""
CONTROL_DONE_PREFIX = "BALE_DONE "
CONTROL_FAIL_PREFIX = "BALE_FAIL "
CONTROL_UPLOAD_DONE_PREFIX = "BALE_UPLOAD_DONE "
CONTROL_RETRY_PREFIX = "BALE_RETRY "
PART_CAPTION_PREFIX = "~"
STEP_DOWNLOAD_TEXT = "Step [1/2]..."
STEP_UPLOAD_TEXT = "Step [2/2]..."
STEP_TRANSFER_TEXT = "Step [2/2]..."
DEFAULT_VIDEO_HEIGHT = 480
QUALITY_SELECTION_RE = re.compile(r"(?<!\d)(360|480|720|1080|1440|2160)\s*p?\b", re.IGNORECASE)
QUALITY_OVERRIDE_LOOKBACK_SECONDS = max(60, int(os.environ.get("QUALITY_OVERRIDE_LOOKBACK_SECONDS", "900")))

DIRECT_PAGE_CONTENT_TYPES = {"application/xhtml+xml", "text/html"}
DIRECT_PAGE_EXTENSIONS = {
    ".asp",
    ".aspx",
    ".cfm",
    ".cgi",
    ".htm",
    ".html",
    ".jsp",
    ".php",
    ".shtml",
    ".xhtml",
}
MEDIA_EXTENSIONS = {
    ".3gp",
    ".aac",
    ".aiff",
    ".alac",
    ".avi",
    ".flac",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}
request_queue: queue.Queue[str] = queue.Queue(maxsize=MAX_QUEUE_SIZE)
workers_started = False
recovery_lock = threading.Lock()
recovering_requests: set[str] = set()
completion_watchdog_started = False
chunk_message_cleanup_started = False


@dataclass
class ChunkManifest:
    request_id: str
    source_url: str
    download_url: str
    file_name: str
    file_size: int
    sha256: str
    object_key: str
    total_chunks: int
    chunks: list[dict[str, Any]]
    cache_path: str = ""


@dataclass
class VideoProbe:
    title: str
    final_url: str
    estimated_size_bytes: int
    selected_height: int
    is_video: bool


def ensure_prerequisites() -> None:
    if shutil.which("7z") is None:
        raise RuntimeError("7z is required in the container. Install p7zip-full.")
    validate_password_strength(ARCHIVE_PASSWORD)
    if not CHANNEL_TARGET_CHAT_ID:
        raise RuntimeError("CHANNEL_TARGET_CHAT_ID is required.")
    if not CHANNEL_UPDATES_CHAT_ID:
        raise RuntimeError("CHANNEL_UPDATES_CHAT_ID is required.")
    if not (ALLOWED_USERNAMES or ALLOWED_USER_IDS):
        raise RuntimeError("Configure ALLOWED_USERNAMES or ALLOWED_USER_IDS for sender access control.")
    if not URL_RESPONSE_PASSWORD:
        raise RuntimeError("URL_RESPONSE_PASSWORD is required.")
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def validate_password_strength(password: str) -> None:
    checks = [
        (len(password) >= 24, "at least 24 characters"),
        (re.search(r"[A-Z]", password) is not None, "an uppercase letter"),
        (re.search(r"[a-z]", password) is not None, "a lowercase letter"),
        (re.search(r"\d", password) is not None, "a digit"),
        (re.search(r"[^A-Za-z0-9]", password) is not None, "a symbol"),
    ]
    missing = [label for ok, label in checks if not ok]
    if missing:
        raise RuntimeError(f"ARCHIVE_PASSWORD is too weak; missing {', '.join(missing)}.")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                user_message_id INTEGER NOT NULL,
                progress_message_id INTEGER,
                prompt_message_id INTEGER,
                source_url TEXT NOT NULL,
                status TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                user_id TEXT NOT NULL DEFAULT '',
                request_kind TEXT NOT NULL DEFAULT '',
                requested_video_height INTEGER NOT NULL DEFAULT 0,
                final_url TEXT NOT NULL DEFAULT '',
                error_text TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS request_events (
                request_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                input_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                error_text TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                finished_at INTEGER,
                latency_ms INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uploaded_chunk_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                part_index INTEGER NOT NULL DEFAULT 0,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                sent_at INTEGER NOT NULL,
                deleted_at INTEGER,
                delete_attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                UNIQUE(chat_id, message_id)
            )
            """
        )
        existing_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(requests)").fetchall()
        }
        if "username" not in existing_columns:
            conn.execute("ALTER TABLE requests ADD COLUMN username TEXT NOT NULL DEFAULT ''")
        if "user_id" not in existing_columns:
            conn.execute("ALTER TABLE requests ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
        if "prompt_message_id" not in existing_columns:
            conn.execute("ALTER TABLE requests ADD COLUMN prompt_message_id INTEGER")
        if "request_kind" not in existing_columns:
            conn.execute("ALTER TABLE requests ADD COLUMN request_kind TEXT NOT NULL DEFAULT ''")
        if "requested_video_height" not in existing_columns:
            conn.execute("ALTER TABLE requests ADD COLUMN requested_video_height INTEGER NOT NULL DEFAULT 0")
        if "completion_notified_at" not in existing_columns:
            conn.execute("ALTER TABLE requests ADD COLUMN completion_notified_at INTEGER")
        if "completion_retry_count" not in existing_columns:
            conn.execute("ALTER TABLE requests ADD COLUMN completion_retry_count INTEGER NOT NULL DEFAULT 0")
        uploaded_chunk_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(uploaded_chunk_messages)").fetchall()
        }
        if "size_bytes" not in uploaded_chunk_columns:
            conn.execute("ALTER TABLE uploaded_chunk_messages ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def db_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, timeout=30)


def set_meta(key: str, value: str) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO meta (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()


def get_meta(key: str) -> str | None:
    with db_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row[0])


def create_request_record(
    request_id: str,
    chat_id: int | str,
    user_message_id: int,
    progress_message_id: int | None,
    prompt_message_id: int | None,
    source_url: str,
    username: str,
    user_id: str,
    request_kind: str = "",
    requested_video_height: int = 0,
) -> None:
    now = int(time.time())
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO requests (
                request_id, chat_id, user_message_id, progress_message_id, prompt_message_id,
                source_url, status, username, user_id, request_kind, requested_video_height,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                str(chat_id),
                int(user_message_id),
                int(progress_message_id) if progress_message_id is not None else None,
                int(prompt_message_id) if prompt_message_id is not None else None,
                source_url,
                "queued",
                username,
                user_id,
                request_kind,
                int(requested_video_height),
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO request_events (
                request_id, user_id, username, input_url, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                user_id,
                username,
                source_url,
                "queued",
                now,
            ),
        )
        conn.commit()


def record_uploaded_chunk_message(
    request_id: str,
    chat_id: int | str,
    message_id: int,
    *,
    part_index: int,
    size_bytes: int,
) -> None:
    now = int(time.time())
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO uploaded_chunk_messages (
                request_id, chat_id, message_id, part_index, size_bytes, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                request_id = excluded.request_id,
                part_index = excluded.part_index,
                size_bytes = excluded.size_bytes
            """,
            (request_id, str(chat_id), int(message_id), int(part_index), int(size_bytes), now),
        )
        conn.commit()


def update_request_event(
    request_id: str,
    *,
    status: str | None = None,
    size_bytes: int | None = None,
    error_text: str | None = None,
    finished: bool = False,
) -> None:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT created_at, status, size_bytes, error_text
            FROM request_events
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if row is None:
            return
        created_at = int(row[0])
        current_status = str(row[1] or "")
        current_size = int(row[2] or 0)
        current_error = str(row[3] or "")
        finished_at = int(time.time()) if finished else None
        latency_ms = (finished_at - created_at) * 1000 if finished_at is not None else None
        conn.execute(
            """
            UPDATE request_events
            SET status = ?,
                size_bytes = ?,
                error_text = ?,
                finished_at = COALESCE(?, finished_at),
                latency_ms = COALESCE(?, latency_ms)
            WHERE request_id = ?
            """,
            (
                status if status is not None else current_status,
                int(size_bytes) if size_bytes is not None else current_size,
                error_text if error_text is not None else current_error,
                finished_at,
                latency_ms,
                request_id,
            ),
        )
        conn.commit()


def list_recent_request_events(limit: int = 20) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT request_id, username, user_id, input_url, status, size_bytes,
                   error_text, created_at, finished_at, latency_ms
            FROM request_events
            ORDER BY COALESCE(finished_at, created_at) DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [
        {
            "request_id": str(row[0]),
            "username": str(row[1] or ""),
            "user_id": str(row[2] or ""),
            "input_url": str(row[3] or ""),
            "status": str(row[4] or ""),
            "size_bytes": int(row[5] or 0),
            "error_text": str(row[6] or ""),
            "created_at": int(row[7] or 0),
            "finished_at": int(row[8] or 0) if row[8] is not None else None,
            "latency_ms": int(row[9] or 0) if row[9] is not None else None,
        }
        for row in rows
    ]


def format_size_brief(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "-"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


def format_latency_brief(latency_ms: int | None) -> str:
    if not latency_ms or latency_ms <= 0:
        return "-"
    return f"{latency_ms / 1000:.1f}s"


def format_stats_message(limit: int = 20) -> str:
    rows = list_recent_request_events(limit)
    if not rows:
        return "No events."
    lines = ["Recent events:"]
    remaining = 3600 - len(lines[0]) - 2
    for row in rows:
        ts = int(row["finished_at"] or row["created_at"] or 0)
        ts_text = time.strftime("%m-%d %H:%M:%S", time.localtime(ts)) if ts > 0 else "-"
        user = row["username"] or row["user_id"] or "-"
        status = row["status"] or "-"
        size_text = format_size_brief(int(row["size_bytes"] or 0))
        latency_text = format_latency_brief(row["latency_ms"])
        request_brief = str(row["request_id"] or "")[-8:] or "-"
        url = str(row["input_url"] or "")
        error = str(row["error_text"] or "")
        line = f"{ts_text} | {status} | {user} | {size_text} | {latency_text} | {request_brief}"
        if url:
            compact_url = re.sub(r"\s+", " ", url.strip())
            if len(compact_url) > 160:
                compact_url = compact_url[:157] + "..."
            line += f"\nurl: {compact_url}"
        if error:
            compact_error = re.sub(r"\s+", " ", error.strip())
            if len(compact_error) > 160:
                compact_error = compact_error[:157] + "..."
            line += f"\nerr: {compact_error}"
        chunk = ("\n\n" if len(lines) > 1 else "\n\n") + line
        if len(chunk) > remaining:
            lines.append("...")
            break
        lines.append(line)
        remaining -= len(chunk)
    return "\n\n".join(lines)


def mark_completion_waiting(request_id: str) -> None:
    now = int(time.time())
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE requests
            SET completion_notified_at = ?,
                completion_retry_count = 0,
                updated_at = ?
            WHERE request_id = ?
            """,
            (now, now, request_id),
        )
        conn.commit()


def mark_completion_retry(request_id: str) -> int:
    now = int(time.time())
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(completion_retry_count, 0)
            FROM requests
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if row is None:
            return 0
        retry_count = int(row[0] or 0) + 1
        conn.execute(
            """
            UPDATE requests
            SET completion_notified_at = ?,
                completion_retry_count = ?,
                updated_at = ?
            WHERE request_id = ?
            """,
            (now, retry_count, now, request_id),
        )
        conn.commit()
        return retry_count


def list_uploaded_request_retries(*, force: bool = False) -> list[tuple[str, int]]:
    with db_conn() as conn:
        if force:
            rows = conn.execute(
                """
                SELECT request_id, COALESCE(completion_retry_count, 0)
                FROM requests
                WHERE status = 'uploaded'
                ORDER BY created_at ASC
                """
            ).fetchall()
        else:
            cutoff = int(time.time()) - UPLOAD_CONFIRMATION_RETRY_SECONDS
            rows = conn.execute(
                """
                SELECT request_id, COALESCE(completion_retry_count, 0)
                FROM requests
                WHERE status = 'uploaded'
                  AND COALESCE(completion_notified_at, updated_at, created_at) <= ?
                ORDER BY created_at ASC
                """,
                (cutoff,),
            ).fetchall()
    return [(str(row[0]), int(row[1] or 0)) for row in rows]


def fail_uploaded_request(request_id: str, error_text: str) -> None:
    update_request_status(request_id, status="failed", error_text=error_text)
    update_request_event(request_id, status="failed", error_text=error_text, finished=True)
    with httpx.Client() as client:
        update_progress(client, request_id, format_user_error(RuntimeError(error_text)))
    cleanup_request_workdir(request_id)


def resend_upload_completion(request_id: str) -> None:
    record = get_request_record(request_id)
    if record is None or record["status"] != "uploaded":
        return
    manifest = load_chunk_manifest(request_id)
    with httpx.Client() as client:
        notify_upload_complete(client, manifest)


def retry_uploaded_requests(*, force: bool = False) -> None:
    for request_id, retry_count in list_uploaded_request_retries(force=force):
        if retry_count >= UPLOAD_CONFIRMATION_MAX_RETRIES:
            fail_uploaded_request(request_id, "receiver confirmation timed out")
            continue
        try:
            resend_upload_completion(request_id)
            mark_completion_retry(request_id)
            log.info("Re-sent upload completion for %s (%d/%d)", request_id, retry_count + 1, UPLOAD_CONFIRMATION_MAX_RETRIES)
        except Exception:
            log.exception("Failed to re-send upload completion for %s", request_id)


def completion_watchdog() -> None:
    while True:
        try:
            retry_uploaded_requests(force=False)
        except Exception:
            log.exception("Completion watchdog failed")
        time.sleep(COMPLETION_WATCHDOG_INTERVAL_SECONDS)


def list_expired_chunk_messages(limit: int = 100) -> list[dict[str, Any]]:
    cutoff = int(time.time()) - CHUNK_MESSAGE_RETENTION_SECONDS
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, request_id, chat_id, message_id, part_index, size_bytes, sent_at, delete_attempts, last_error
            FROM uploaded_chunk_messages
            WHERE deleted_at IS NULL
              AND sent_at <= ?
            ORDER BY sent_at ASC
            LIMIT ?
            """,
            (cutoff, int(limit)),
        ).fetchall()
    return [
        {
            "id": int(row[0]),
            "request_id": str(row[1]),
            "chat_id": str(row[2]),
            "message_id": int(row[3]),
            "part_index": int(row[4] or 0),
            "size_bytes": int(row[5] or 0),
            "sent_at": int(row[6] or 0),
            "delete_attempts": int(row[7] or 0),
            "last_error": str(row[8] or ""),
        }
        for row in rows
    ]


def mark_chunk_message_deleted(row_id: int) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE uploaded_chunk_messages
            SET deleted_at = ?, last_error = ''
            WHERE id = ?
            """,
            (int(time.time()), int(row_id)),
        )
        conn.commit()


def mark_chunk_message_delete_failure(row_id: int, error_text: str) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE uploaded_chunk_messages
            SET delete_attempts = delete_attempts + 1,
                last_error = ?
            WHERE id = ?
            """,
            (error_text[:500], int(row_id)),
        )
        conn.commit()


def delete_message(client: httpx.Client, chat_id: int | str, message_id: int) -> bool:
    result = api_call(client, "deleteMessage", json={"chat_id": str(chat_id), "message_id": int(message_id)}).get("result")
    return True if result is None else bool(result)


def chunk_message_delete_is_terminal(exc: Exception) -> bool:
    text = str(exc).strip().lower()
    return ("not found" in text) or ("message not found" in text) or ("invalid message" in text)


def format_cleanup_summary(cleaned_rows: list[dict[str, Any]]) -> str:
    chunk_count = len(cleaned_rows)
    request_count = len({str(row["request_id"]) for row in cleaned_rows})
    total_size = sum(int(row.get("size_bytes") or 0) for row in cleaned_rows)
    return (
        f"Chunk cleanup done.\n"
        f"{request_count} requests | {chunk_count} chunks | {human_size(total_size)}"
    )


def notify_chunk_cleanup(client: httpx.Client, cleaned_rows: list[dict[str, Any]]) -> None:
    if not cleaned_rows or not ADMIN_CHAT_ID:
        return
    send_message(client, ADMIN_CHAT_ID, format_cleanup_summary(cleaned_rows))


def cleanup_expired_chunk_messages(*, force: bool = False) -> None:
    while True:
        rows = list_expired_chunk_messages(limit=200 if force else 100)
        if not rows:
            return
        cleaned_rows: list[dict[str, Any]] = []
        with httpx.Client() as client:
            for row in rows:
                try:
                    delete_message(client, row["chat_id"], row["message_id"])
                    mark_chunk_message_deleted(row["id"])
                    cleaned_rows.append(row)
                except Exception as exc:
                    if chunk_message_delete_is_terminal(exc):
                        mark_chunk_message_deleted(row["id"])
                        cleaned_rows.append(row)
                        continue
                    mark_chunk_message_delete_failure(row["id"], str(exc).strip() or "delete failed")
                    log.warning(
                        "Failed deleting chunk message %s for request %s part %s: %s",
                        row["message_id"],
                        row["request_id"],
                        row["part_index"],
                        exc,
                    )
            if cleaned_rows:
                try:
                    notify_chunk_cleanup(client, cleaned_rows)
                except Exception:
                    log.exception("Failed sending chunk cleanup summary")
        if not force:
            return


def chunk_message_cleanup_worker() -> None:
    while True:
        try:
            cleanup_expired_chunk_messages(force=False)
        except Exception:
            log.exception("Chunk message cleanup failed")
        time.sleep(CHUNK_MESSAGE_CLEAN_INTERVAL_SECONDS)


def update_request_status(
    request_id: str,
    *,
    status: str,
    final_url: str | None = None,
    error_text: str | None = None,
) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT request_id, chat_id, progress_message_id, status, final_url, error_text
            FROM requests
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        chat_id = str(row[1])
        progress_message_id = row[2]
        stored_final_url = str(row[4] or "")
        stored_error = str(row[5] or "")
        conn.execute(
            """
            UPDATE requests
            SET status = ?,
                final_url = ?,
                error_text = ?,
                updated_at = ?
            WHERE request_id = ?
            """,
            (
                status,
                final_url if final_url is not None else stored_final_url,
                error_text if error_text is not None else stored_error,
                int(time.time()),
                request_id,
            ),
        )
        conn.commit()
    return {
        "request_id": request_id,
        "chat_id": chat_id,
        "progress_message_id": progress_message_id,
    }


def get_request_record(request_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT request_id, chat_id, user_message_id, progress_message_id, prompt_message_id,
                   source_url, status, username, user_id, request_kind, requested_video_height,
                   final_url, error_text
            FROM requests
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "request_id": str(row[0]),
        "chat_id": str(row[1]),
        "user_message_id": int(row[2]),
        "progress_message_id": int(row[3]) if row[3] is not None else None,
        "prompt_message_id": int(row[4]) if row[4] is not None else None,
        "source_url": str(row[5]),
        "status": str(row[6]),
        "username": str(row[7] or ""),
        "user_id": str(row[8] or ""),
        "request_kind": str(row[9] or ""),
        "requested_video_height": int(row[10] or 0),
        "final_url": str(row[11] or ""),
        "error_text": str(row[12] or ""),
    }


def set_request_progress_message_id(request_id: str, message_id: int | None) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE requests
            SET progress_message_id = ?, updated_at = ?
            WHERE request_id = ?
            """,
            (int(message_id) if message_id is not None else None, int(time.time()), request_id),
        )
        conn.commit()


def set_request_prompt_message_id(request_id: str, message_id: int | None) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE requests
            SET prompt_message_id = ?, updated_at = ?
            WHERE request_id = ?
            """,
            (int(message_id) if message_id is not None else None, int(time.time()), request_id),
        )
        conn.commit()


def set_request_video_quality(request_id: str, requested_video_height: int) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE requests
            SET requested_video_height = ?, updated_at = ?
            WHERE request_id = ?
            """,
            (int(requested_video_height), int(time.time()), request_id),
        )
        conn.commit()


def find_latest_adjustable_video_request(chat_id: int | str, user_id: str) -> dict[str, Any] | None:
    cutoff = int(time.time()) - QUALITY_OVERRIDE_LOOKBACK_SECONDS
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT request_id
            FROM requests
            WHERE chat_id = ?
              AND user_id = ?
              AND status = 'queued'
              AND request_kind = 'video'
              AND prompt_message_id IS NOT NULL
              AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(chat_id), str(user_id), cutoff),
        ).fetchone()
    if row is None:
        return None
    return get_request_record(str(row[0]))


def list_requeueable_request_ids() -> list[str]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT request_id
            FROM requests
            WHERE status IN ('queued', 'processing')
            ORDER BY created_at ASC
            """
        ).fetchall()
    return [str(row[0]) for row in rows]


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")[:120] or "item"


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def chunk_manifest_path(request_id: str) -> Path:
    return WORK_ROOT / request_id / "stage" / "manifest.json"


def save_chunk_manifest(manifest: ChunkManifest) -> None:
    path = chunk_manifest_path(manifest.request_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "request_id": manifest.request_id,
        "source_url": manifest.source_url,
        "download_url": manifest.download_url,
        "file_name": manifest.file_name,
        "file_size": manifest.file_size,
        "sha256": manifest.sha256,
        "object_key": manifest.object_key,
        "total_chunks": manifest.total_chunks,
        "chunks": manifest.chunks,
        "cache_path": manifest.cache_path,
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_chunk_manifest(request_id: str) -> ChunkManifest:
    payload = json.loads(chunk_manifest_path(request_id).read_text(encoding="utf-8"))
    return ChunkManifest(
        request_id=str(payload["request_id"]),
        source_url=str(payload["source_url"]),
        download_url=str(payload["download_url"]),
        file_name=str(payload["file_name"]),
        file_size=int(payload["file_size"]),
        sha256=str(payload["sha256"]),
        object_key=str(payload["object_key"]),
        total_chunks=int(payload["total_chunks"]),
        chunks=list(payload["chunks"]),
        cache_path=str(payload.get("cache_path") or ""),
    )


def extract_message_url(text: str) -> str | None:
    match = URL_RE.search(text)
    if match:
        return match.group(0).rstrip(TRAILING_URL_PUNCTUATION)
    return None


def normalize_sender_source_url(url: str) -> str:
    return url.strip()


def normalized_suffix(name: str) -> str:
    suffix = Path(name).suffix.lower().strip()
    if re.fullmatch(r"\.[a-z0-9]{1,9}", suffix):
        return suffix
    return ".bin"


def obfuscated_payload_name(request_id: str, name_hint: str) -> str:
    token = hashlib.sha1(f"payload:{request_id}".encode("utf-8")).hexdigest()[:20]
    return f"asset-{token}{normalized_suffix(name_hint)}"


def infer_filename_from_headers(url: str, headers: httpx.Headers) -> str:
    content_disposition = headers.get("content-disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)\"?", content_disposition, re.IGNORECASE)
    if match:
        candidate = unquote(match.group(1) or match.group(2) or "").strip()
        if candidate:
            return Path(candidate).name
    candidate = Path(unquote(urlparse(url).path)).name.strip()
    return candidate or f"download-{secrets.token_hex(6)}.bin"


def is_direct_downloadable(url: str, headers: httpx.Headers) -> bool:
    content_type = (headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in DIRECT_PAGE_EXTENSIONS:
        return False
    if content_type in DIRECT_PAGE_CONTENT_TYPES:
        return False
    if headers.get("content-disposition"):
        return True
    if suffix and not content_type.startswith("text/"):
        return True
    return not content_type.startswith("text/")


def parse_browser_spec(spec: str) -> tuple[str, ...]:
    browser_part, profile_part, container = spec, None, None
    if "::" in spec:
        browser_part, container = spec.split("::", 1)
    if ":" in browser_part:
        browser_part, profile_part = browser_part.split(":", 1)

    if "+" in browser_part:
        browser, keyring = browser_part.split("+", 1)
    else:
        browser, keyring = browser_part, None

    values = [browser]
    if profile_part is not None or keyring is not None or container is not None:
        values.append(profile_part)
    if keyring is not None or container is not None:
        values.append(keyring)
    if container is not None:
        values.append(container or None)
    return tuple(values)


def ensure_inline_cookie_file() -> str | None:
    cookie_file = COOKIE_FILE
    if not cookie_file and DEFAULT_YTDLP_COOKIE_FILE.is_file():
        cookie_file = str(DEFAULT_YTDLP_COOKIE_FILE)
    if cookie_file:
        if not Path(cookie_file).is_file():
            raise FileNotFoundError(f"Configured YTDLP_COOKIE_FILE does not exist: {cookie_file}")
        return cookie_file

    if not (COOKIE_TEXT_B64 or COOKIE_TEXT):
        return None

    cookie_text = COOKIE_TEXT
    if COOKIE_TEXT_B64:
        try:
            cookie_text = base64.b64decode(COOKIE_TEXT_B64).decode("utf-8")
        except Exception as exc:
            raise ValueError("Configured YTDLP_COOKIE_TEXT_B64 is not valid base64") from exc
    INLINE_COOKIE_PATH.write_text(cookie_text, encoding="utf-8")
    return str(INLINE_COOKIE_PATH)


def deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_ytdlp_extra_opts(opts: dict[str, Any]) -> dict[str, Any]:
    if not YTDLP_EXTRA_OPTS_JSON:
        return opts
    try:
        payload = json.loads(YTDLP_EXTRA_OPTS_JSON)
    except json.JSONDecodeError as exc:
        raise ValueError("YTDLP_EXTRA_OPTS_JSON must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("YTDLP_EXTRA_OPTS_JSON must decode to a JSON object.")
    return deep_merge_dict(opts, payload)


def pick_downloaded_media_file(output_dir: Path) -> Path:
    candidates = [
        path
        for path in output_dir.rglob("*")
        if path.is_file() and not path.name.startswith(".part")
    ]
    if not candidates:
        raise RuntimeError("yt-dlp did not produce a file.")
    media_candidates = [path for path in candidates if path.suffix.lower() in MEDIA_EXTENSIONS]
    pool = media_candidates or candidates
    return max(pool, key=lambda path: (path.stat().st_size, path.stat().st_mtime_ns))


def human_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 B"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(num_bytes)
    unit = units[0]
    for candidate in units[1:]:
        if value < 1024.0:
            break
        value /= 1024.0
        unit = candidate
    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"


def request_download_limit_bytes(username: str) -> int:
    return DEFAULT_REQUEST_DOWNLOAD_LIMIT_BYTES


def ensure_request_size_within_limit(size_bytes: int, limit_bytes: int) -> None:
    if size_bytes > limit_bytes:
        raise RuntimeError(
            f"Request is too large for this account: {human_size(size_bytes)} exceeds {human_size(limit_bytes)}."
        )


def ytdlp_size_hint(info: dict[str, Any]) -> int:
    for key in ("filesize", "filesize_approx"):
        value = info.get(key)
        if isinstance(value, (int, float)) and int(value) > 0:
            return int(value)

    requested_downloads = info.get("requested_downloads")
    if not isinstance(requested_downloads, list):
        return 0

    total = 0
    found = False
    for entry in requested_downloads:
        if not isinstance(entry, dict):
            continue
        for key in ("filesize", "filesize_approx"):
            value = entry.get(key)
            if isinstance(value, (int, float)) and int(value) > 0:
                total += int(value)
                found = True
                break
    return total if found else 0


def ytdlp_duration_seconds(info: dict[str, Any]) -> float:
    value = info.get("duration")
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return 0.0


def ytdlp_entry_size_hint(entry: dict[str, Any], *, duration_seconds: float = 0.0) -> int:
    for key in ("filesize", "filesize_approx"):
        value = entry.get(key)
        if isinstance(value, (int, float)) and int(value) > 0:
            return int(value)
    if duration_seconds > 0:
        bitrate = entry.get("tbr")
        if isinstance(bitrate, (int, float)) and float(bitrate) > 0:
            return int((float(bitrate) * 1000.0 / 8.0) * duration_seconds)
    return 0


def ytdlp_is_video_info(info: dict[str, Any]) -> bool:
    if int(info.get("height") or 0) > 0:
        return True
    vcodec = str(info.get("vcodec") or "").strip().lower()
    if vcodec and vcodec != "none":
        return True
    for collection_key in ("requested_downloads", "requested_formats", "formats"):
        collection = info.get(collection_key)
        if not isinstance(collection, list):
            continue
        for entry in collection:
            if not isinstance(entry, dict):
                continue
            if int(entry.get("height") or 0) > 0:
                return True
            entry_vcodec = str(entry.get("vcodec") or "").strip().lower()
            if entry_vcodec and entry_vcodec != "none":
                return True
    return False


def ytdlp_size_hint_for_quality(info: dict[str, Any], *, selected_height: int = 0) -> int:
    hint = ytdlp_size_hint(info)
    if hint > 0:
        return hint

    duration_seconds = ytdlp_duration_seconds(info)
    requested_parts = info.get("requested_downloads") or info.get("requested_formats")
    if isinstance(requested_parts, list):
        total = 0
        found = False
        for entry in requested_parts:
            if not isinstance(entry, dict):
                continue
            part_size = ytdlp_entry_size_hint(entry, duration_seconds=duration_seconds)
            if part_size > 0:
                total += part_size
                found = True
        if found:
            return total

    formats = info.get("formats")
    if not isinstance(formats, list):
        return 0

    video_candidates: list[tuple[int, int]] = []
    audio_candidates: list[int] = []
    for entry in formats:
        if not isinstance(entry, dict):
            continue
        entry_height = int(entry.get("height") or 0)
        entry_size = ytdlp_entry_size_hint(entry, duration_seconds=duration_seconds)
        if entry_size <= 0:
            continue
        vcodec = str(entry.get("vcodec") or "").strip().lower()
        acodec = str(entry.get("acodec") or "").strip().lower()
        has_video = (entry_height > 0) or (vcodec and vcodec != "none")
        has_audio = bool(acodec and acodec != "none")
        if has_video:
            if selected_height > 0 and entry_height > 0 and entry_height > selected_height:
                continue
            video_candidates.append((entry_height, entry_size))
        if has_audio and not has_video:
            audio_candidates.append(entry_size)

    if video_candidates:
        video_candidates.sort(key=lambda item: (item[0], item[1]))
        best_video_size = video_candidates[-1][1]
        best_audio_size = max(audio_candidates) if audio_candidates else 0
        return best_video_size + best_audio_size

    return max(audio_candidates) if audio_candidates else 0


def build_ytdlp_formats(max_video_height: int | None = None) -> tuple[str, ...]:
    if max_video_height is None or max_video_height <= 0:
        return YTDLP_FORMAT_CANDIDATES
    max_height = int(max_video_height)
    return (
        (
            f"bestvideo*[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo*[height<={max_height}]+bestaudio"
            f"/best[height<={max_height}][ext=mp4]"
            f"/best[height<={max_height}]"
            "/bestaudio/best"
        ),
        (
            f"bestvideo[height<={max_height}][ext=mp4]+bestaudio"
            f"/bestvideo[height<={max_height}]+bestaudio"
            f"/best[height<={max_height}]"
            "/bestaudio/best"
        ),
    )


def build_ytdlp_opts(
    output_dir: Path,
    *,
    format_selector: str | None = None,
    max_video_height: int | None = None,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "format": format_selector or build_ytdlp_formats(max_video_height=max_video_height)[0],
        "merge_output_format": "mp4",
        "outtmpl": str(output_dir / "%(title).80s-%(id)s.%(ext)s"),
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 10,
        "js_runtimes": {"node": {}},
        "restrictfilenames": True,
        "quiet": True,
        "no_warnings": True,
    }
    if YTDLP_PROXY:
        opts["proxy"] = YTDLP_PROXY

    cookie_file = ensure_inline_cookie_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file
    elif COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = parse_browser_spec(COOKIES_FROM_BROWSER)

    return merge_ytdlp_extra_opts(opts)


def ytdlp_final_url(info: dict[str, Any], fallback: str) -> str:
    for key in ("webpage_url", "original_url", "url"):
        value = str(info.get(key) or "").strip()
        if value:
            return value
    return fallback


def ytdlp_is_unavailable_format_error(exc: Exception) -> bool:
    return "requested format is not available" in str(exc).strip().lower()


def parse_requested_video_height(text: str) -> int | None:
    match = QUALITY_SELECTION_RE.search(text)
    if not match:
        return None
    return int(match.group(1))


def maybe_video_page_url(url: str) -> bool:
    suffix = Path(urlparse(url).path).suffix.lower()
    return not suffix or suffix in DIRECT_PAGE_EXTENSIONS


def format_video_prompt(probe: VideoProbe) -> str:
    lines: list[str] = []
    if probe.title:
        lines.append(probe.title[:160])
    quality_label = f"{probe.selected_height}p"
    if probe.selected_height == DEFAULT_VIDEO_HEIGHT:
        lines.append(f"Quality: {quality_label} (default)")
    else:
        lines.append(f"Quality: {quality_label}")
    if probe.estimated_size_bytes > 0:
        lines.append(f"Estimated size: ~{human_size(probe.estimated_size_bytes)}")
    lines.append("Reply with 720p or 1080p before start if you need higher.")
    return "\n".join(lines)


def probe_video_metadata(
    source_url: str,
    *,
    selected_height: int = DEFAULT_VIDEO_HEIGHT,
) -> VideoProbe:
    probe_dir = WORK_ROOT / ".probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None

    for format_selector in build_ytdlp_formats(max_video_height=selected_height):
        opts = build_ytdlp_opts(probe_dir, format_selector=format_selector, max_video_height=selected_height)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(source_url, download=False)
            if not isinstance(info, dict):
                raise RuntimeError("yt-dlp did not return a media entry.")
            final_url = ytdlp_final_url(info, source_url)
            return VideoProbe(
                title=str(info.get("title") or "").strip(),
                final_url=final_url,
                estimated_size_bytes=ytdlp_size_hint_for_quality(info, selected_height=selected_height),
                selected_height=selected_height,
                is_video=ytdlp_is_video_info(info),
            )
        except Exception as exc:
            last_error = exc
            if not ytdlp_is_unavailable_format_error(exc):
                raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("yt-dlp did not return video metadata.")


def download_with_ytdlp(
    source_url: str,
    output_dir: Path,
    *,
    max_download_size: int,
    requested_video_height: int = 0,
) -> tuple[Path, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None

    format_candidates = build_ytdlp_formats(max_video_height=requested_video_height)
    for index, format_selector in enumerate(format_candidates):
        opts = build_ytdlp_opts(
            output_dir,
            format_selector=format_selector,
            max_video_height=requested_video_height,
        )
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(source_url, download=False)
            if not isinstance(info, dict):
                raise RuntimeError("yt-dlp did not return a media entry.")
            expected_size = ytdlp_size_hint_for_quality(info, selected_height=requested_video_height)
            if expected_size > 0:
                ensure_request_size_within_limit(expected_size, max_download_size)
            final_url = ytdlp_final_url(info, source_url)

            shutil.rmtree(output_dir, ignore_errors=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(source_url, download=True)
            media_path = pick_downloaded_media_file(output_dir)
            ensure_request_size_within_limit(media_path.stat().st_size, max_download_size)
            return media_path, final_url
        except Exception as exc:
            last_error = exc
            if index == len(format_candidates) - 1 or not ytdlp_is_unavailable_format_error(exc):
                raise
            log.warning(
                "yt-dlp format selector %s was unavailable for %s; retrying with the next fallback",
                format_selector,
                source_url,
            )
            shutil.rmtree(output_dir, ignore_errors=True)
            output_dir.mkdir(parents=True, exist_ok=True)

    if last_error is not None:
        raise last_error
    raise RuntimeError("yt-dlp did not produce a file.")


def api_call(
    client: httpx.Client,
    method: str,
    *,
    timeout: float = REQUEST_TIMEOUT,
    **kwargs: Any,
) -> dict[str, Any]:
    response = client.post(f"{BALE_API}/{method}", timeout=timeout, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok", False):
        description = payload.get("description") or payload.get("error") or "unknown Bale API error"
        raise RuntimeError(f"Bale API {method} failed: {description}")
    return payload


def send_message(
    client: httpx.Client,
    chat_id: int | str,
    text: str,
    *,
    reply_to_message_id: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    return api_call(client, "sendMessage", json=payload).get("result", {})


def send_control_message(client: httpx.Client, chat_id: int | str, prefix: str, payload: dict[str, Any]) -> dict[str, Any]:
    return send_message(client, chat_id, prefix + encrypt_transport_payload(payload))


def edit_message_text(client: httpx.Client, chat_id: int | str, message_id: int, text: str) -> dict[str, Any]:
    return api_call(
        client,
        "editMessageText",
        json={"chat_id": chat_id, "message_id": message_id, "text": text},
    ).get("result", {})


def send_document(client: httpx.Client, chat_id: int | str, file_path: Path, caption: str) -> dict[str, Any]:
    file_name = f"asset{normalized_suffix(file_path.name)}"
    size_mb = file_path.stat().st_size / (1024 * 1024)
    last_error: Exception | None = None
    for attempt in range(1, UPLOAD_RETRIES + 1):
        try:
            with file_path.open("rb") as handle:
                log.info("Uploading %s (%.1fMB), attempt %d/%d", file_name, size_mb, attempt, UPLOAD_RETRIES)
                return api_call(
                    client,
                    "sendDocument",
                    data={"chat_id": str(chat_id), "caption": caption},
                    files={"document": (file_name, handle)},
                    timeout=UPLOAD_TIMEOUT,
                ).get("result", {})
        except Exception as exc:
            last_error = exc
            if attempt >= UPLOAD_RETRIES:
                break
            delay = min(90.0, 5.0 * (2 ** (attempt - 1)))
            log.warning("Upload failed for %s: %s; retrying in %.1fs", file_name, exc, delay)
            time.sleep(delay)
    raise RuntimeError(f"Failed to upload {file_name}: {last_error}") from last_error


def build_archive(stage_dir: Path, archive_name: str) -> Path:
    cmd = [
        "7z",
        "a",
        "-t7z",
        archive_name,
        "payload",
        "metadata.json",
        "-mx=0",
        "-mhe=on",
        f"-p{ARCHIVE_PASSWORD}",
    ]
    completed = subprocess.run(cmd, cwd=stage_dir, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"7z failed: {completed.stderr.strip() or completed.stdout.strip()}")
    archive_path = stage_dir / archive_name
    if not archive_path.is_file():
        raise RuntimeError(f"7z did not produce {archive_name}")
    return archive_path


def object_key_for_request(request_id: str, file_name: str) -> str:
    date_prefix = time.strftime("%Y/%m/%d")
    token = hashlib.sha1(f"object:{request_id}".encode("utf-8")).hexdigest()[:24]
    return f"downloads/{date_prefix}/{token}{normalized_suffix(file_name)}"


def chunk_archive_name(request_id: str, chunk_index: int) -> str:
    token = hashlib.sha1(f"{request_id}:{chunk_index}".encode("utf-8")).hexdigest()[:16]
    return f"{token}.bin"


def xor_keystream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        remaining = len(data) - len(output)
        output.extend(block[:remaining])
        counter += 1
    return bytes(left ^ right for left, right in zip(data, output))


def encrypt_user_url(value: str) -> str:
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    key_material = hashlib.pbkdf2_hmac("sha256", URL_RESPONSE_PASSWORD.encode("utf-8"), salt, 200_000, dklen=64)
    enc_key = key_material[:32]
    mac_key = key_material[32:]
    plaintext = value.encode("utf-8")
    ciphertext = xor_keystream(plaintext, enc_key, nonce)
    mac = hmac.new(mac_key, b"dl-over-bale-url-v1" + salt + nonce + ciphertext, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(salt + nonce + mac + ciphertext).decode("ascii").rstrip("=")
    return f"enc-v1.{token}"


def encrypt_transport_payload(payload: dict[str, Any]) -> str:
    salt = secrets.token_bytes(12)
    nonce = secrets.token_bytes(12)
    key_material = hashlib.pbkdf2_hmac("sha256", ARCHIVE_PASSWORD.encode("utf-8"), salt, 120_000, dklen=64)
    enc_key = key_material[:32]
    mac_key = key_material[32:]
    plaintext = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ciphertext = xor_keystream(plaintext, enc_key, nonce)
    mac = hmac.new(mac_key, b"dl-over-bale-meta-v1" + salt + nonce + ciphertext, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(salt + nonce + mac + ciphertext).decode("ascii").rstrip("=")


def decrypt_transport_payload(token: str) -> dict[str, Any] | None:
    try:
        raw = token.encode("ascii")
        raw += b"=" * (-len(raw) % 4)
        blob = base64.urlsafe_b64decode(raw)
    except Exception:
        return None
    if len(blob) < 56:
        return None
    salt = blob[:12]
    nonce = blob[12:24]
    mac = blob[24:56]
    ciphertext = blob[56:]
    key_material = hashlib.pbkdf2_hmac("sha256", ARCHIVE_PASSWORD.encode("utf-8"), salt, 120_000, dklen=64)
    enc_key = key_material[:32]
    mac_key = key_material[32:]
    expected_mac = hmac.new(mac_key, b"dl-over-bale-meta-v1" + salt + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        return None
    try:
        plaintext = xor_keystream(ciphertext, enc_key, nonce).decode("utf-8")
        payload = json.loads(plaintext)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def build_part_caption(request_id: str, part_index: int, part_total: int, volume_name: str, *, mode: str) -> str:
    payload = {"r": request_id, "p": part_index, "t": part_total, "v": volume_name, "m": mode}
    return PART_CAPTION_PREFIX + encrypt_transport_payload(payload)


def create_chunk_archive(stage_dir: Path, manifest: ChunkManifest, entry: dict[str, Any], raw_chunk_path: Path) -> Path:
    chunk_index = int(entry["index"])
    chunk_stage_dir = stage_dir / f"chunk-{chunk_index:06d}"
    payload_root = chunk_stage_dir / "payload"
    shutil.rmtree(chunk_stage_dir, ignore_errors=True)
    payload_root.mkdir(parents=True, exist_ok=True)
    payload_path = payload_root / "chunk.bin"
    shutil.move(str(raw_chunk_path), payload_path)
    metadata = {
        "protocol": "dl-over-bale-v3-chunk",
        "request_id": manifest.request_id,
        "payload_file_name": manifest.file_name,
        "payload_size": manifest.file_size,
        "payload_sha256": manifest.sha256,
        "object_key": manifest.object_key,
        "chunk_index": chunk_index,
        "chunk_total": manifest.total_chunks,
        "chunk_offset": int(entry["offset"]),
        "chunk_size": int(entry["size"]),
        "chunk_sha256": str(entry["sha256"]),
        "chunk_file_name": payload_path.name,
        "created_at": int(time.time()),
    }
    (chunk_stage_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    built_archive = build_archive(chunk_stage_dir, chunk_archive_name(manifest.request_id, chunk_index))
    final_archive = stage_dir / built_archive.name
    built_archive.replace(final_archive)
    shutil.rmtree(chunk_stage_dir, ignore_errors=True)
    return final_archive


def upload_local_file_to_channel(
    upload_client: httpx.Client,
    request_id: str,
    source_url: str,
    download_url: str,
    payload_path: Path,
    temp_dir: Path,
    stage_dir: Path,
) -> ChunkManifest:
    file_name = obfuscated_payload_name(request_id, payload_path.name)
    file_size = payload_path.stat().st_size
    manifest = ChunkManifest(
        request_id=request_id,
        source_url=source_url,
        download_url=download_url,
        file_name=file_name,
        file_size=file_size,
        sha256="",
        object_key=object_key_for_request(request_id, file_name),
        total_chunks=math.ceil(file_size / TRANSFER_CHUNK_SIZE) if file_size else 0,
        chunks=[],
        cache_path=str(payload_path),
    )
    save_chunk_manifest(manifest)
    raw_chunk_path = temp_dir / f"{request_id}.chunk.bin"
    raw_handle = raw_chunk_path.open("wb")
    chunk_digest = hashlib.sha256()
    chunk_size = 0
    chunk_index = 1
    chunk_offset = 0
    overall_digest = hashlib.sha256()
    upload_started = False

    def finalize_current_chunk() -> None:
        nonlocal raw_handle, chunk_digest, chunk_size, chunk_index, chunk_offset, upload_started
        raw_handle.close()
        if chunk_size <= 0:
            raw_chunk_path.unlink(missing_ok=True)
            return
        entry = {
            "index": chunk_index,
            "offset": chunk_offset,
            "size": chunk_size,
            "sha256": chunk_digest.hexdigest(),
        }
        manifest.chunks.append(entry)
        save_chunk_manifest(manifest)
        archive_path = create_chunk_archive(stage_dir, manifest, entry, raw_chunk_path)
        archive_size = archive_path.stat().st_size
        try:
            if not upload_started:
                update_progress(upload_client, request_id, STEP_UPLOAD_TEXT)
                upload_started = True
            message = send_document(
                upload_client,
                CHANNEL_TARGET_CHAT_ID,
                archive_path,
                build_part_caption(request_id, chunk_index, manifest.total_chunks, archive_path.name, mode="chunked"),
            )
            message_id = int(message.get("message_id") or 0)
            if message_id > 0:
                record_uploaded_chunk_message(
                    request_id,
                    CHANNEL_TARGET_CHAT_ID,
                    message_id,
                    part_index=chunk_index,
                    size_bytes=archive_size,
                )
        finally:
            archive_path.unlink(missing_ok=True)
        chunk_index += 1
        chunk_offset += chunk_size
        chunk_size = 0
        chunk_digest = hashlib.sha256()

    with payload_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            if not chunk:
                continue
            overall_digest.update(chunk)
            chunk_digest.update(chunk)
            raw_handle.write(chunk)
            chunk_size += len(chunk)
            if chunk_size >= TRANSFER_CHUNK_SIZE:
                finalize_current_chunk()
                raw_handle = raw_chunk_path.open("wb")

    if chunk_size > 0:
        finalize_current_chunk()
    else:
        raw_handle.close()
        raw_chunk_path.unlink(missing_ok=True)

    manifest.sha256 = overall_digest.hexdigest()
    manifest.total_chunks = len(manifest.chunks)
    save_chunk_manifest(manifest)
    return manifest


def stream_download_to_channel(
    upload_client: httpx.Client,
    request_id: str,
    source_url: str,
    download_dir: Path,
    stage_dir: Path,
    *,
    max_download_size: int,
) -> ChunkManifest:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=headers) as download_client:
        head_response: httpx.Response | None = None
        try:
            head_response = download_client.head(source_url)
            head_response.raise_for_status()
        except Exception:
            head_response = None

        if head_response is not None and not is_direct_downloadable(str(head_response.url), head_response.headers):
            raise ValueError("URL does not look like a direct downloadable file.")

        with download_client.stream("GET", source_url) as response:
            response.raise_for_status()
            download_url = str(response.url)
            if not is_direct_downloadable(download_url, response.headers):
                raise ValueError("URL resolved to a web page instead of a direct file.")

            content_length = int(response.headers.get("content-length") or 0)
            if content_length:
                ensure_request_size_within_limit(content_length, max_download_size)

            file_name = obfuscated_payload_name(
                request_id,
                infer_filename_from_headers(download_url, response.headers),
            )
            manifest = ChunkManifest(
                request_id=request_id,
                source_url=source_url,
                download_url=download_url,
                file_name=file_name,
                file_size=0,
                sha256="",
                object_key=object_key_for_request(request_id, file_name),
                total_chunks=math.ceil(content_length / TRANSFER_CHUNK_SIZE) if content_length else 0,
                chunks=[],
            )
            save_chunk_manifest(manifest)
            update_request_status(request_id, status="processing")

            raw_chunk_path = download_dir / f"{request_id}.chunk.bin"
            raw_handle = raw_chunk_path.open("wb")
            chunk_digest = hashlib.sha256()
            chunk_size = 0
            chunk_index = 1
            chunk_offset = 0
            total_bytes = 0
            overall_digest = hashlib.sha256()
            upload_started = False

            def finalize_current_chunk() -> None:
                nonlocal raw_handle, chunk_digest, chunk_size, chunk_index, chunk_offset, upload_started
                raw_handle.close()
                if chunk_size <= 0:
                    raw_chunk_path.unlink(missing_ok=True)
                    return
                entry = {
                    "index": chunk_index,
                    "offset": chunk_offset,
                    "size": chunk_size,
                    "sha256": chunk_digest.hexdigest(),
                }
                manifest.chunks.append(entry)
                save_chunk_manifest(manifest)
                archive_path = create_chunk_archive(stage_dir, manifest, entry, raw_chunk_path)
                archive_size = archive_path.stat().st_size
                try:
                    if not upload_started:
                        update_progress(upload_client, request_id, STEP_UPLOAD_TEXT)
                        upload_started = True
                    message = send_document(
                        upload_client,
                        CHANNEL_TARGET_CHAT_ID,
                        archive_path,
                        build_part_caption(request_id, chunk_index, manifest.total_chunks, archive_path.name, mode="chunked"),
                    )
                    message_id = int(message.get("message_id") or 0)
                    if message_id > 0:
                        record_uploaded_chunk_message(
                            request_id,
                            CHANNEL_TARGET_CHAT_ID,
                            message_id,
                            part_index=chunk_index,
                            size_bytes=archive_size,
                        )
                finally:
                    archive_path.unlink(missing_ok=True)
                chunk_index += 1
                chunk_offset += chunk_size
                chunk_size = 0
                chunk_digest = hashlib.sha256()

            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total_bytes += len(chunk)
                ensure_request_size_within_limit(total_bytes, max_download_size)
                overall_digest.update(chunk)
                chunk_digest.update(chunk)
                raw_handle.write(chunk)
                chunk_size += len(chunk)
                if chunk_size >= TRANSFER_CHUNK_SIZE:
                    finalize_current_chunk()
                    raw_handle = raw_chunk_path.open("wb")

            if chunk_size > 0:
                finalize_current_chunk()
            else:
                raw_handle.close()
                raw_chunk_path.unlink(missing_ok=True)

            manifest.file_size = total_bytes
            manifest.sha256 = overall_digest.hexdigest()
            manifest.total_chunks = len(manifest.chunks)
            save_chunk_manifest(manifest)
            return manifest


def cleanup_request_workdir(request_id: str) -> None:
    shutil.rmtree(WORK_ROOT / request_id, ignore_errors=True)


def notify_upload_complete(client: httpx.Client, manifest: ChunkManifest) -> None:
    send_control_message(
        client,
        CHANNEL_TARGET_CHAT_ID,
        CONTROL_UPLOAD_DONE_PREFIX,
        {
            "request_id": manifest.request_id,
            "total": manifest.total_chunks,
            "mode": "chunked",
            "payload_file_name": manifest.file_name,
            "payload_size": manifest.file_size,
            "payload_sha256": manifest.sha256,
            "object_key": manifest.object_key,
        },
    )


def redownload_chunk(manifest: ChunkManifest, entry: dict[str, Any], destination: Path) -> None:
    start = int(entry["offset"])
    size = int(entry["size"])
    end = start + size - 1
    cache_path = Path(manifest.cache_path).resolve() if manifest.cache_path else None
    if cache_path and cache_path.is_file():
        digest = hashlib.sha256()
        total_bytes = 0
        with cache_path.open("rb") as source, destination.open("wb") as handle:
            source.seek(start)
            remaining = size
            while remaining > 0:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                handle.write(chunk)
                total_bytes += len(chunk)
                remaining -= len(chunk)
        if total_bytes != size:
            destination.unlink(missing_ok=True)
            raise RuntimeError(f"Recovered chunk size mismatch for chunk {entry['index']}: expected {size}, got {total_bytes}")
        if digest.hexdigest().lower() != str(entry["sha256"]).lower():
            destination.unlink(missing_ok=True)
            raise RuntimeError(f"Recovered chunk checksum mismatch for chunk {entry['index']}")
        return

    headers = {"User-Agent": USER_AGENT, "Range": f"bytes={start}-{end}"}
    candidates = [str(manifest.source_url or "").strip(), str(manifest.download_url or "").strip()]
    seen: set[str] = set()
    last_error: Exception | None = None
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        total_bytes = 0
        digest = hashlib.sha256()
        destination.unlink(missing_ok=True)
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=headers) as client:
                with client.stream("GET", candidate) as response:
                    response.raise_for_status()
                    if response.status_code == 200 and (start != 0 or manifest.total_chunks > 1):
                        raise RuntimeError("Remote server ignored byte-range request for chunk recovery")
                    with destination.open("wb") as handle:
                        for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            digest.update(chunk)
                            handle.write(chunk)
                            total_bytes += len(chunk)
            if total_bytes != size:
                raise RuntimeError(f"Recovered chunk size mismatch for chunk {entry['index']}: expected {size}, got {total_bytes}")
            if digest.hexdigest().lower() != str(entry["sha256"]).lower():
                raise RuntimeError(f"Recovered chunk checksum mismatch for chunk {entry['index']}")
            return
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"No valid recovery URL is available for chunk {entry['index']}")


def recreate_chunk_archive(stage_dir: Path, manifest: ChunkManifest, entry: dict[str, Any]) -> Path:
    raw_chunk_path = stage_dir / f"{manifest.request_id}.recover-{int(entry['index']):06d}.bin"
    raw_chunk_path.unlink(missing_ok=True)
    redownload_chunk(manifest, entry, raw_chunk_path)
    return create_chunk_archive(stage_dir, manifest, entry, raw_chunk_path)


def resend_missing_parts(request_id: str, missing_parts: list[int]) -> None:
    try:
        record = get_request_record(request_id)
        if record is None:
            log.info("Ignoring recovery request for unknown request %s", request_id)
            return
        if record["status"] in {"completed", "failed"}:
            return
        manifest = load_chunk_manifest(request_id)
        if manifest.total_chunks <= 0:
            raise RuntimeError("Request manifest is missing chunk metadata")

        invalid = sorted({index for index in missing_parts if index < 1 or index > manifest.total_chunks})
        if invalid:
            raise RuntimeError(f"Recovery requested invalid part indexes: {invalid}")
        unique_missing = sorted({index for index in missing_parts if 1 <= index <= manifest.total_chunks})
        if not unique_missing:
            log.info("Ignoring empty recovery request for %s", request_id)
            return

        stage_dir = WORK_ROOT / request_id / "stage"
        stage_dir.mkdir(parents=True, exist_ok=True)
        with httpx.Client() as client:
            log.info("Recovering %s missing parts %s", request_id, unique_missing)
            for index in unique_missing:
                entry = manifest.chunks[index - 1]
                archive_path = recreate_chunk_archive(stage_dir, manifest, entry)
                archive_size = archive_path.stat().st_size
                try:
                    message = send_document(
                        client,
                        CHANNEL_TARGET_CHAT_ID,
                        archive_path,
                        build_part_caption(request_id, index, manifest.total_chunks, archive_path.name, mode="chunked"),
                    )
                    message_id = int(message.get("message_id") or 0)
                    if message_id > 0:
                        record_uploaded_chunk_message(
                            request_id,
                            CHANNEL_TARGET_CHAT_ID,
                            message_id,
                            part_index=index,
                            size_bytes=archive_size,
                        )
                finally:
                    archive_path.unlink(missing_ok=True)
            notify_upload_complete(client, manifest)
    except Exception:
        log.exception("Failed to recover missing parts for %s", request_id)
    finally:
        with recovery_lock:
            recovering_requests.discard(request_id)


def schedule_missing_part_recovery(request_id: str, missing_parts: list[int]) -> None:
    with recovery_lock:
        if request_id in recovering_requests:
            log.info("Recovery already in progress for %s", request_id)
            return
        recovering_requests.add(request_id)
    thread = threading.Thread(
        target=resend_missing_parts,
        args=(request_id, missing_parts),
        name=f"sender-recover-{request_id}",
        daemon=True,
    )
    thread.start()


def update_progress(client: httpx.Client, request_id: str, text: str) -> None:
    record = get_request_record(request_id)
    if not record:
        return
    progress_message_id = record.get("progress_message_id")
    if progress_message_id is None:
        result = send_message(
            client,
            record["chat_id"],
            text,
            reply_to_message_id=int(record["user_message_id"] or 0) or None,
        )
        message_id = int(result.get("message_id") or 0) or None
        if message_id is not None:
            set_request_progress_message_id(request_id, message_id)
        return
    try:
        edit_message_text(client, record["chat_id"], int(progress_message_id), text)
    except Exception:
        log.exception("Failed to edit progress message for %s", request_id)
        result = send_message(
            client,
            record["chat_id"],
            text,
            reply_to_message_id=int(record["user_message_id"] or 0) or None,
        )
        message_id = int(result.get("message_id") or 0) or None
        if message_id is not None:
            set_request_progress_message_id(request_id, message_id)


def delete_request_prompt(client: httpx.Client, request_id: str) -> None:
    record = get_request_record(request_id)
    if not record:
        return
    prompt_message_id = record.get("prompt_message_id")
    if prompt_message_id is None:
        return
    try:
        delete_message(client, record["chat_id"], int(prompt_message_id))
    except Exception:
        log.exception("Failed to delete prompt message for %s", request_id)
    finally:
        set_request_prompt_message_id(request_id, None)


def format_user_error(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return "Failed."
    return f"Failed: {text}"


def format_completion_message(final_location: str, backend: str) -> str:
    if not final_location:
        return "Done."
    return final_location


def send_completion_message(client: httpx.Client, request_id: str, final_location: str, backend: str) -> None:
    record = get_request_record(request_id)
    if not record:
        return
    send_message(client, record["chat_id"], format_completion_message(final_location, backend))


def can_retry_with_ytdlp(exc: Exception) -> bool:
    if not isinstance(exc, ValueError):
        return False
    text = str(exc).strip().lower()
    return text in {
        "url does not look like a direct downloadable file.",
        "url resolved to a web page instead of a direct file.",
    }


def sender_is_allowed(message: dict[str, Any]) -> bool:
    sender = message.get("from") or {}
    username = str(sender.get("username") or "").strip().lstrip("@").lower()
    user_id = str(sender.get("id") or "").strip()
    return (username in ALLOWED_USERNAMES) or (user_id in ALLOWED_USER_IDS)


def sender_is_stats_admin(message: dict[str, Any]) -> bool:
    sender = message.get("from") or {}
    username = str(sender.get("username") or "").strip().lstrip("@").lower()
    user_id = str(sender.get("id") or "").strip()
    return username in STATS_ADMIN_USERNAMES or user_id in STATS_ADMIN_USER_IDS


def process_request(request_id: str) -> None:
    record = get_request_record(request_id)
    if not record:
        return
    update_request_status(request_id, status="processing")
    work_dir = WORK_ROOT / request_id
    download_dir = work_dir / "download"
    stage_dir = work_dir / "stage"
    ytdlp_dir = work_dir / "ytdlp"
    download_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    ytdlp_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client() as client:
        upload_completed = False
        try:
            max_download_size = request_download_limit_bytes(str(record.get("username") or ""))
            delete_request_prompt(client, request_id)
            update_progress(client, request_id, STEP_DOWNLOAD_TEXT)
            request_kind = str(record.get("request_kind") or "").strip().lower()
            requested_video_height = int(record.get("requested_video_height") or 0)
            if request_kind == "video":
                media_path, final_url = download_with_ytdlp(
                    record["source_url"],
                    ytdlp_dir,
                    max_download_size=max_download_size,
                    requested_video_height=requested_video_height or DEFAULT_VIDEO_HEIGHT,
                )
                manifest = upload_local_file_to_channel(
                    client,
                    request_id,
                    record["source_url"],
                    final_url,
                    media_path,
                    download_dir,
                    stage_dir,
                )
            else:
                try:
                    manifest = stream_download_to_channel(
                        client,
                        request_id,
                        record["source_url"],
                        download_dir,
                        stage_dir,
                        max_download_size=max_download_size,
                    )
                except Exception as exc:
                    if not can_retry_with_ytdlp(exc):
                        raise
                    media_path, final_url = download_with_ytdlp(
                        record["source_url"],
                        ytdlp_dir,
                        max_download_size=max_download_size,
                    )
                    manifest = upload_local_file_to_channel(
                        client,
                        request_id,
                        record["source_url"],
                        final_url,
                        media_path,
                        download_dir,
                        stage_dir,
                    )
            update_request_status(request_id, status="uploaded")
            update_request_event(request_id, status="uploaded", size_bytes=manifest.file_size)
            notify_upload_complete(client, manifest)
            mark_completion_waiting(request_id)
            update_progress(client, request_id, STEP_TRANSFER_TEXT)
            upload_completed = True
        except Exception as exc:
            log.exception("Request %s failed before receiver completion", request_id)
            update_request_status(request_id, status="failed", error_text=str(exc).strip())
            update_request_event(request_id, status="failed", error_text=str(exc).strip(), finished=True)
            update_progress(client, request_id, format_user_error(exc))
        finally:
            if not upload_completed:
                cleanup_request_workdir(request_id)


def request_worker() -> None:
    while True:
        request_id = request_queue.get()
        try:
            process_request(request_id)
        finally:
            request_queue.task_done()


def start_workers() -> None:
    global workers_started
    if workers_started:
        return
    workers_started = True
    for index in range(WORKER_COUNT):
        thread = threading.Thread(target=request_worker, name=f"sender-worker-{index + 1}", daemon=True)
        thread.start()


def start_completion_watchdog() -> None:
    global completion_watchdog_started
    if completion_watchdog_started:
        return
    completion_watchdog_started = True
    thread = threading.Thread(target=completion_watchdog, name="sender-completion-watchdog", daemon=True)
    thread.start()


def start_chunk_message_cleanup_worker() -> None:
    global chunk_message_cleanup_started
    if chunk_message_cleanup_started:
        return
    chunk_message_cleanup_started = True
    thread = threading.Thread(
        target=chunk_message_cleanup_worker,
        name="sender-chunk-message-cleanup",
        daemon=True,
    )
    thread.start()


def enqueue_request(request_id: str) -> None:
    request_queue.put_nowait(request_id)


def parse_control_message(text: str) -> tuple[str, dict[str, Any]] | None:
    stripped = text.strip()
    for prefix, kind in (
        (CONTROL_DONE_PREFIX, "done"),
        (CONTROL_FAIL_PREFIX, "fail"),
        (CONTROL_RETRY_PREFIX, "retry"),
    ):
        if not stripped.startswith(prefix):
            continue
        payload = decrypt_transport_payload(stripped[len(prefix):].strip())
        if payload is not None:
            return kind, payload
    return None


def chat_matches_config(chat: dict[str, Any], configured_chat: str) -> bool:
    configured = str(configured_chat or "").strip()
    if not configured:
        return False
    chat_id = str(chat.get("id") or "").strip()
    if chat_id and chat_id == configured:
        return True
    configured_username = configured.lstrip("@").lower()
    chat_username = str(chat.get("username") or "").strip().lstrip("@").lower()
    return bool(configured_username and chat_username and configured_username == chat_username)


def handle_channel_message(client: httpx.Client, message: dict[str, Any]) -> None:
    text = str(message.get("text") or "").strip()
    parsed = parse_control_message(text)
    if not parsed:
        return
    kind, payload = parsed
    request_id = str(payload.get("request_id") or "").strip()
    if not request_id:
        return
    record = get_request_record(request_id)
    if record is None:
        log.info("Ignoring channel control for unknown request %s", request_id)
        return
    if kind == "retry":
        missing_raw = payload.get("missing")
        if not isinstance(missing_raw, list):
            return
        try:
            missing_parts = sorted({int(value) for value in missing_raw})
        except (TypeError, ValueError):
            return
        if missing_parts:
            schedule_missing_part_recovery(request_id, missing_parts)
        return
    if kind == "done":
        final_location = str(payload.get("sealed_location") or payload.get("path") or payload.get("url") or "").strip()
        backend = str(payload.get("backend") or "").strip()
        if final_location:
            update_request_status(request_id, status="completed", final_url=final_location)
        else:
            update_request_status(request_id, status="completed")
        update_request_event(request_id, status="completed", finished=True)
        update_progress(client, request_id, format_completion_message(final_location, backend))
        cleanup_request_workdir(request_id)
        return
    error_text = str(payload.get("error") or "receiver failed").strip()
    update_request_status(request_id, status="failed", error_text=error_text)
    update_request_event(request_id, status="failed", error_text=error_text, finished=True)
    update_progress(client, request_id, format_user_error(RuntimeError(error_text)))
    cleanup_request_workdir(request_id)


def handle_private_message(client: httpx.Client, message: dict[str, Any]) -> None:
    text = str(message.get("text") or "").strip()
    chat_id = message["chat"]["id"]
    message_id = int(message.get("message_id") or 0)
    username = str((message.get("from") or {}).get("username") or "").strip().lstrip("@").lower()
    user_id = str((message.get("from") or {}).get("id") or "").strip()
    if not sender_is_allowed(message):
        return
    if text == "/health":
        send_message(client, chat_id, "ok", reply_to_message_id=message_id)
        return
    if text == "/stats":
        if sender_is_stats_admin(message):
            send_message(client, chat_id, format_stats_message(), reply_to_message_id=message_id)
        return
    if text.startswith("/"):
        return
    url = extract_message_url(text)
    quality_text = text.replace(url, " ") if url else text
    requested_video_height = parse_requested_video_height(quality_text)
    if not url and requested_video_height is not None:
        record = find_latest_adjustable_video_request(chat_id, user_id)
        if record is None:
            return
        selected_height = max(DEFAULT_VIDEO_HEIGHT, requested_video_height)
        set_request_video_quality(record["request_id"], selected_height)
        prompt_message_id = record.get("prompt_message_id")
        if prompt_message_id is None:
            return
        try:
            probe = probe_video_metadata(
                record["source_url"],
                selected_height=selected_height,
            )
            edit_message_text(client, record["chat_id"], int(prompt_message_id), format_video_prompt(probe))
        except Exception:
            log.exception("Failed to refresh video prompt for %s", record["request_id"])
        return
    if not url:
        return
    normalized_url = normalize_sender_source_url(url)
    request_id = f"req-{int(time.time())}-{secrets.token_hex(4)}"
    request_kind = ""
    prompt_message_id: int | None = None
    selected_video_height = 0
    if maybe_video_page_url(normalized_url):
        try:
            selected_video_height = max(DEFAULT_VIDEO_HEIGHT, requested_video_height or DEFAULT_VIDEO_HEIGHT)
            probe = probe_video_metadata(
                normalized_url,
                selected_height=selected_video_height,
            )
            if probe.is_video:
                request_kind = "video"
                prompt = send_message(
                    client,
                    chat_id,
                    format_video_prompt(probe),
                    reply_to_message_id=message_id,
                )
                prompt_message_id = int(prompt.get("message_id") or 0) or None
            else:
                selected_video_height = 0
        except Exception as exc:
            send_message(client, chat_id, format_user_error(exc), reply_to_message_id=message_id)
            return
    create_request_record(
        request_id=request_id,
        chat_id=chat_id,
        user_message_id=message_id,
        progress_message_id=None,
        prompt_message_id=prompt_message_id,
        source_url=normalized_url,
        username=username,
        user_id=user_id,
        request_kind=request_kind,
        requested_video_height=selected_video_height,
    )
    try:
        enqueue_request(request_id)
    except queue.Full:
        delete_request_prompt(client, request_id)
        update_request_status(request_id, status="failed", error_text="queue is full")
        update_request_event(request_id, status="failed", error_text="queue is full", finished=True)
        update_progress(client, request_id, "Failed: bot queue is full. Try again later.")


def current_offset() -> int | None:
    raw = get_meta("offset")
    if raw is None or not raw.strip():
        return None
    return int(raw)


def save_offset(offset: int) -> None:
    set_meta("offset", str(offset))


def poll_forever() -> None:
    ensure_prerequisites()
    init_db()
    start_workers()
    start_completion_watchdog()
    start_chunk_message_cleanup_worker()
    for request_id in list_requeueable_request_ids():
        try:
            enqueue_request(request_id)
        except queue.Full:
            break
    retry_uploaded_requests(force=True)
    cleanup_expired_chunk_messages(force=True)

    with httpx.Client() as client:
        me = api_call(client, "getMe").get("result", {})
        log.info("Sender bot ready: %s", me.get("username") or me.get("id") or "?")
        offset = current_offset()

        while True:
            try:
                params: dict[str, Any] = {"timeout": POLL_TIMEOUT, "allowed_updates": '["message"]'}
                if offset is not None:
                    params["offset"] = offset
                response = client.get(f"{BALE_API}/getUpdates", params=params, timeout=POLL_TIMEOUT + 5)
                response.raise_for_status()
                updates = response.json().get("result", [])
                for update in updates:
                    offset = int(update["update_id"]) + 1
                    save_offset(offset)
                    message = update.get("message")
                    if not isinstance(message, dict):
                        continue
                    chat = message.get("chat") or {}
                    chat_type = str(chat.get("type") or "")
                    if chat_type == "private":
                        handle_private_message(client, message)
                    elif chat_matches_config(chat, CHANNEL_UPDATES_CHAT_ID):
                        handle_channel_message(client, message)
            except httpx.TimeoutException:
                continue
            except Exception:
                log.exception("Sender polling error")
                time.sleep(5)


if __name__ == "__main__":
    poll_forever()
