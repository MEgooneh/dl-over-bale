#!/usr/bin/env python3
from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx
import hashlib
import queue


LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dl-over-bale-receiver")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ARCHIVE_PASSWORD = os.environ["ARCHIVE_PASSWORD"]

CHANNEL_CHAT_ID = str(os.environ.get("CHANNEL_CHAT_ID", "")).strip()
WORK_ROOT = Path(os.environ.get("WORK_ROOT", "/var/tmp/dl_over_bale_receiver")).resolve()
STATE_PATH = WORK_ROOT / "state.json"
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "30"))
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "120"))
DOWNLOAD_TIMEOUT = float(os.environ.get("DOWNLOAD_TIMEOUT", "1800"))
IDLE_SLEEP = float(os.environ.get("IDLE_SLEEP", "2"))
PUBLIC_DOWNLOAD_RETENTION_SECONDS = max(60, int(os.environ.get("PUBLIC_DOWNLOAD_RETENTION_SECONDS", "3600")))
PUBLIC_DOWNLOAD_CLEAN_INTERVAL_SECONDS = max(60, int(os.environ.get("PUBLIC_DOWNLOAD_CLEAN_INTERVAL_SECONDS", "300")))

PUBLIC_DOWNLOAD_ROOT = Path(os.environ.get("PUBLIC_DOWNLOAD_ROOT", "/srv/downloads")).resolve()
PUBLIC_DOWNLOAD_BASE_URL = os.environ.get("PUBLIC_DOWNLOAD_BASE_URL", "http://localhost:8080").rstrip("/")
DOWNLOAD_LINK_SECRET = os.environ.get("DOWNLOAD_LINK_SECRET", "").strip()
DOWNLOAD_LINK_TTL_SECONDS = max(60, int(os.environ.get("DOWNLOAD_LINK_TTL_SECONDS", "10800")))
URL_RESPONSE_PASSWORD = os.environ.get("URL_RESPONSE_PASSWORD", "").strip()
WORKER_COUNT = max(1, int(os.environ.get("WORKER_COUNT", "8")))
MAX_QUEUE_SIZE = max(1, int(os.environ.get("MAX_QUEUE_SIZE", "1000")))

BALE_API = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
PART_CAPTION_RE = re.compile(r"^~([A-Za-z0-9_-]+)$")
CONTROL_DONE_PREFIX = "BALE_DONE "
CONTROL_FAIL_PREFIX = "BALE_FAIL "
CONTROL_UPLOAD_DONE_PREFIX = "BALE_UPLOAD_DONE "
CONTROL_RETRY_PREFIX = "BALE_RETRY "

state_lock = threading.Lock()
job_queue: queue.Queue[str] = queue.Queue(maxsize=MAX_QUEUE_SIZE)
workers_started = False
MISSING_PART_RETRIES = max(1, int(os.environ.get("MISSING_PART_RETRIES", "5")))
download_cleanup_started = False


def ensure_prerequisites() -> None:
    if shutil.which("7z") is None:
        raise RuntimeError("7z is required in the container. Install p7zip-full.")
    if not CHANNEL_CHAT_ID:
        raise RuntimeError("CHANNEL_CHAT_ID is required.")
    if not DOWNLOAD_LINK_SECRET:
        raise RuntimeError("DOWNLOAD_LINK_SECRET is required for protected disk download links.")
    if not URL_RESPONSE_PASSWORD:
        raise RuntimeError("URL_RESPONSE_PASSWORD is required.")
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    PUBLIC_DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"offset": None, "jobs": {}, "completed_jobs": {}, "failed_jobs": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    temp_path = STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(STATE_PATH)


def api_get(client: httpx.Client, method: str, *, params: dict[str, Any]) -> dict[str, Any]:
    response = client.get(f"{BALE_API}/{method}", params=params, timeout=POLL_TIMEOUT + 5)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok", False):
        description = payload.get("description") or payload.get("error") or "unknown Bale API error"
        raise RuntimeError(f"Bale API {method} failed: {description}")
    return payload


def api_post(
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


def send_channel_control(client: httpx.Client, prefix: str, payload: dict[str, Any]) -> None:
    text = prefix + encrypt_transport_payload(payload)
    api_post(client, "sendMessage", json={"chat_id": CHANNEL_CHAT_ID, "text": text})


def parse_control_message(text: str) -> tuple[str, dict[str, Any]] | None:
    stripped = text.strip()
    for prefix, kind in ((CONTROL_UPLOAD_DONE_PREFIX, "upload_done"),):
        if not stripped.startswith(prefix):
            continue
        payload = decrypt_transport_payload(stripped[len(prefix):].strip())
        if payload is not None:
            return kind, payload
    return None


def extract_part_info(message: dict[str, Any]) -> dict[str, Any] | None:
    caption = str(message.get("caption") or "").strip()
    match = PART_CAPTION_RE.match(caption)
    if not match:
        return None
    payload = decrypt_transport_payload(match.group(1))
    if not isinstance(payload, dict):
        return None
    request_id = str(payload.get("r") or "").strip()
    volume_name = str(payload.get("v") or "").strip()
    try:
        part_index = int(payload.get("p") or 0)
        total_parts = int(payload.get("t") or 0)
    except (TypeError, ValueError):
        return None
    mode = str(payload.get("m") or "legacy").strip() or "legacy"
    if not request_id or part_index <= 0 or not volume_name:
        return None
    return {
        "request_id": request_id,
        "part": part_index,
        "total": total_parts,
        "volume": volume_name,
        "mode": mode,
    }


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


def same_channel(message: dict[str, Any]) -> bool:
    return chat_matches_config(message.get("chat") or {}, CHANNEL_CHAT_ID)


def get_file_url(file_result: dict[str, Any]) -> str:
    file_path = file_result.get("file_path") or file_result.get("url") or file_result.get("download_url") or ""
    if not file_path:
        raise RuntimeError(f"getFile did not return a file_path-like value: {file_result}")
    if str(file_path).startswith(("http://", "https://")):
        return str(file_path)
    return f"https://tapi.bale.ai/file/bot{BOT_TOKEN}/{str(file_path).lstrip('/')}"


def download_document(client: httpx.Client, document: dict[str, Any], destination: Path) -> None:
    file_id = document.get("file_id")
    if not file_id:
        raise RuntimeError("Incoming document is missing file_id")
    file_result = api_post(client, "getFile", data={"file_id": file_id}).get("result", {})
    file_url = get_file_url(file_result)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_destination = destination.with_name(f".{destination.name}.partial")
    try:
        with client.stream("GET", file_url, timeout=DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            with temp_destination.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        temp_destination.replace(destination)
    except Exception:
        temp_destination.unlink(missing_ok=True)
        raise


def storage_relative_path(object_key: str, fallback_file_name: str) -> Path:
    raw_path = str(object_key or "").strip().strip("/")
    candidate = PurePosixPath(raw_path) if raw_path else PurePosixPath(Path(fallback_file_name).name)
    parts = [part for part in candidate.parts if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise RuntimeError(f"Invalid disk storage path: {object_key or fallback_file_name}")
    return Path(*parts)


def storage_final_path(object_key: str, fallback_file_name: str) -> tuple[Path, Path]:
    relative_path = storage_relative_path(object_key, fallback_file_name)
    final_path = (PUBLIC_DOWNLOAD_ROOT / relative_path).resolve()
    if not final_path.is_relative_to(PUBLIC_DOWNLOAD_ROOT):
        raise RuntimeError(f"Resolved storage path escaped PUBLIC_DOWNLOAD_ROOT: {relative_path}")
    return relative_path, final_path


def build_secure_link_token(uri: str, expires: int) -> str:
    payload = f"{expires}{uri} {DOWNLOAD_LINK_SECRET}".encode("utf-8")
    digest = hashlib.md5(payload).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def public_disk_url(relative_path: Path) -> str:
    uri = f"/files/{quote(relative_path.as_posix(), safe='/')}"
    expires = int(time.time()) + DOWNLOAD_LINK_TTL_SECONDS
    token = build_secure_link_token(uri, expires)
    return f"{PUBLIC_DOWNLOAD_BASE_URL}{uri}?md5={token}&expires={expires}"


def xor_keystream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        remaining = len(data) - len(output)
        output.extend(block[:remaining])
        counter += 1
    return bytes(left ^ right for left, right in zip(data, output))


def encrypt_response_value(value: str) -> str:
    salt = os.urandom(16)
    nonce = os.urandom(16)
    key_material = hashlib.pbkdf2_hmac("sha256", URL_RESPONSE_PASSWORD.encode("utf-8"), salt, 200_000, dklen=64)
    enc_key = key_material[:32]
    mac_key = key_material[32:]
    plaintext = value.encode("utf-8")
    ciphertext = xor_keystream(plaintext, enc_key, nonce)
    mac = hmac.new(mac_key, b"dl-over-bale-url-v1" + salt + nonce + ciphertext, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(salt + nonce + mac + ciphertext).decode("ascii").rstrip("=")
    return f"enc-v1.{token}"


def encrypt_transport_payload(payload: dict[str, Any]) -> str:
    salt = os.urandom(12)
    nonce = os.urandom(12)
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


def cleanup_public_downloads() -> None:
    cutoff = time.time() - PUBLIC_DOWNLOAD_RETENTION_SECONDS
    for path in PUBLIC_DOWNLOAD_ROOT.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime <= cutoff:
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
    for path in sorted(PUBLIC_DOWNLOAD_ROOT.rglob("*"), reverse=True):
        if not path.is_dir():
            continue
        try:
            path.rmdir()
        except OSError:
            continue


def public_download_cleanup_worker() -> None:
    while True:
        try:
            cleanup_public_downloads()
        except Exception:
            log.exception("Public download cleanup failed")
        time.sleep(PUBLIC_DOWNLOAD_CLEAN_INTERVAL_SECONDS)


def first_archive_part(job: dict[str, Any], job_dir: Path) -> Path:
    parts = job.get("parts") or {}
    if "1" in parts:
        return job_dir / "parts" / parts["1"]
    candidates = sorted((job_dir / "parts").glob("*"), key=lambda path: path.name)
    if not candidates:
        raise RuntimeError("No downloaded archive parts found")
    return candidates[0]


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if chunk:
                digest.update(chunk)
    return digest.hexdigest().lower()


def extract_archive(job_dir: Path, job: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    extract_dir = job_dir / "extracted"
    shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)

    archive_part = first_archive_part(job, job_dir)
    cmd = [
        "7z",
        "x",
        "-y",
        f"-p{ARCHIVE_PASSWORD}",
        str(archive_part),
        f"-o{extract_dir}",
    ]
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"7z extract failed: {completed.stderr.strip() or completed.stdout.strip()}")

    metadata_path = extract_dir / "metadata.json"
    payload_dir = extract_dir / "payload"
    if not metadata_path.is_file():
        raise RuntimeError("Archive did not contain metadata.json")
    if not payload_dir.is_dir():
        raise RuntimeError("Archive did not contain payload/")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise RuntimeError("metadata.json did not contain an object")
    payload_file_name = str(metadata.get("payload_file_name") or "").strip()
    if not payload_file_name:
        raise RuntimeError("metadata.json missing payload_file_name")
    payload_path = payload_dir / payload_file_name
    if not payload_path.is_file():
        raise RuntimeError(f"Payload file missing: {payload_file_name}")
    expected_sha256 = str(metadata.get("payload_sha256") or "").strip().lower()
    if expected_sha256:
        digest = sha256sum(payload_path)
        if digest != expected_sha256:
            raise RuntimeError("Extracted payload checksum does not match metadata")
    return metadata, payload_path


def extract_chunk_archive(archive_path: Path, extract_dir: Path) -> tuple[dict[str, Any], Path]:
    shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "7z",
        "x",
        "-y",
        f"-p{ARCHIVE_PASSWORD}",
        str(archive_path),
        f"-o{extract_dir}",
    ]
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"7z extract failed: {completed.stderr.strip() or completed.stdout.strip()}")

    metadata_path = extract_dir / "metadata.json"
    payload_dir = extract_dir / "payload"
    if not metadata_path.is_file():
        raise RuntimeError("Chunk archive did not contain metadata.json")
    if not payload_dir.is_dir():
        raise RuntimeError("Chunk archive did not contain payload/")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise RuntimeError("Chunk metadata did not contain an object")
    chunk_file_name = str(metadata.get("chunk_file_name") or "").strip()
    if not chunk_file_name:
        raise RuntimeError("Chunk metadata missing chunk_file_name")
    payload_path = payload_dir / chunk_file_name
    if not payload_path.is_file():
        raise RuntimeError(f"Chunk payload missing: {chunk_file_name}")
    expected_sha256 = str(metadata.get("chunk_sha256") or "").strip().lower()
    if expected_sha256:
        digest = sha256sum(payload_path)
        if digest != expected_sha256:
            raise RuntimeError("Chunk checksum does not match metadata")
    return metadata, payload_path


def assemble_chunked_payload(job_dir: Path, job: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    request_id = str(job.get("request_id") or "").strip()
    payload_file_name = str(job.get("payload_file_name") or "").strip()
    object_key = str(job.get("object_key") or "").strip()
    if not payload_file_name:
        raise RuntimeError("Chunked job metadata missing payload_file_name")
    if not object_key:
        raise RuntimeError("Chunked job metadata missing object_key")

    assemble_dir = job_dir / "assembled"
    shutil.rmtree(assemble_dir, ignore_errors=True)
    assemble_dir.mkdir(parents=True, exist_ok=True)
    assembled_path = assemble_dir / payload_file_name
    extract_root = job_dir / "chunk_extract"
    shutil.rmtree(extract_root, ignore_errors=True)
    extract_root.mkdir(parents=True, exist_ok=True)

    parts = job.get("parts") or {}
    total = int(job.get("total") or 0)
    overall_digest = hashlib.sha256()
    current_offset = 0

    with assembled_path.open("wb") as destination:
        for index in range(1, total + 1):
            volume_name = str(parts.get(str(index)) or "").strip()
            if not volume_name:
                raise RuntimeError(f"Missing chunk archive entry for {index}")
            archive_path = job_dir / "parts" / volume_name
            chunk_metadata, payload_path = extract_chunk_archive(archive_path, extract_root / f"{index:06d}")
            if str(chunk_metadata.get("protocol") or "") != "dl-over-bale-v3-chunk":
                raise RuntimeError(f"Unexpected chunk protocol for {volume_name}")
            if request_id and str(chunk_metadata.get("request_id") or "").strip() != request_id:
                raise RuntimeError(f"Chunk request_id mismatch for {volume_name}")
            if int(chunk_metadata.get("chunk_index") or 0) != index:
                raise RuntimeError(f"Chunk index mismatch for {volume_name}")
            if int(chunk_metadata.get("chunk_offset") or 0) != current_offset:
                raise RuntimeError(f"Chunk offset mismatch for {volume_name}")
            with payload_path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    if not chunk:
                        continue
                    destination.write(chunk)
                    overall_digest.update(chunk)
                    current_offset += len(chunk)
            shutil.rmtree(extract_root / f"{index:06d}", ignore_errors=True)

    expected_size = int(job.get("payload_size") or 0)
    if expected_size and assembled_path.stat().st_size != expected_size:
        raise RuntimeError("Assembled payload size does not match upload metadata")
    expected_sha256 = str(job.get("payload_sha256") or "").strip().lower()
    if expected_sha256 and overall_digest.hexdigest().lower() != expected_sha256:
        raise RuntimeError("Assembled payload checksum does not match upload metadata")

    metadata = {
        "protocol": "dl-over-bale-v3-chunk",
        "request_id": request_id,
        "payload_file_name": payload_file_name,
        "payload_size": assembled_path.stat().st_size,
        "payload_sha256": overall_digest.hexdigest(),
        "object_key": object_key,
    }
    return metadata, assembled_path


def write_chunked_payload_to_disk(job_dir: Path, job: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    request_id = str(job.get("request_id") or "").strip()
    payload_file_name = str(job.get("payload_file_name") or "").strip()
    object_key = str(job.get("object_key") or "").strip()
    if not payload_file_name:
        raise RuntimeError("Chunked job metadata missing payload_file_name")

    extract_root = job_dir / "chunk_extract"
    shutil.rmtree(extract_root, ignore_errors=True)
    extract_root.mkdir(parents=True, exist_ok=True)

    relative_path, final_path = storage_final_path(object_key, payload_file_name)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = final_path.parent / f".{final_path.name}.partial"
    temp_path.unlink(missing_ok=True)

    parts = job.get("parts") or {}
    total = int(job.get("total") or 0)
    expected_size = int(job.get("payload_size") or 0)
    expected_sha256 = str(job.get("payload_sha256") or "").strip().lower()
    overall_digest = hashlib.sha256()
    current_offset = 0

    try:
        with temp_path.open("wb") as destination:
            for index in range(1, total + 1):
                volume_name = str(parts.get(str(index)) or "").strip()
                if not volume_name:
                    raise RuntimeError(f"Missing chunk archive entry for {index}")
                archive_path = job_dir / "parts" / volume_name
                chunk_dir = extract_root / f"{index:06d}"
                chunk_metadata, payload_path = extract_chunk_archive(archive_path, chunk_dir)
                if str(chunk_metadata.get("protocol") or "") != "dl-over-bale-v3-chunk":
                    raise RuntimeError(f"Unexpected chunk protocol for {volume_name}")
                if request_id and str(chunk_metadata.get("request_id") or "").strip() != request_id:
                    raise RuntimeError(f"Chunk request_id mismatch for {volume_name}")
                if int(chunk_metadata.get("chunk_index") or 0) != index:
                    raise RuntimeError(f"Chunk index mismatch for {volume_name}")
                if int(chunk_metadata.get("chunk_offset") or 0) != current_offset:
                    raise RuntimeError(f"Chunk offset mismatch for {volume_name}")

                local_digest = hashlib.sha256()
                written = 0
                with payload_path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        if not chunk:
                            continue
                        destination.write(chunk)
                        overall_digest.update(chunk)
                        local_digest.update(chunk)
                        written += len(chunk)
                        current_offset += len(chunk)
                expected_chunk_size = int(chunk_metadata.get("chunk_size") or 0)
                if expected_chunk_size and written != expected_chunk_size:
                    raise RuntimeError(f"Chunk size mismatch for {volume_name}")
                expected_chunk_sha = str(chunk_metadata.get("chunk_sha256") or "").strip().lower()
                if expected_chunk_sha and local_digest.hexdigest().lower() != expected_chunk_sha:
                    raise RuntimeError(f"Chunk checksum mismatch for {volume_name}")
                shutil.rmtree(chunk_dir, ignore_errors=True)
                archive_path.unlink(missing_ok=True)

        if expected_size and temp_path.stat().st_size != expected_size:
            raise RuntimeError("Assembled payload size does not match upload metadata")
        final_sha256 = overall_digest.hexdigest().lower()
        if expected_sha256 and final_sha256 != expected_sha256:
            raise RuntimeError("Assembled payload checksum does not match upload metadata")

        final_path.unlink(missing_ok=True)
        temp_path.replace(final_path)
        metadata = {
            "protocol": "dl-over-bale-v3-chunk",
            "request_id": request_id,
            "payload_file_name": payload_file_name,
            "payload_size": final_path.stat().st_size,
            "payload_sha256": final_sha256,
            "object_key": object_key,
            "storage_relative_path": relative_path.as_posix(),
        }
        return metadata, final_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)


def write_payload_to_disk(metadata: dict[str, Any], payload_path: Path) -> tuple[dict[str, Any], Path]:
    payload_file_name = str(metadata.get("payload_file_name") or payload_path.name).strip() or payload_path.name
    relative_path, final_path = storage_final_path(str(metadata.get("object_key") or ""), payload_file_name)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = final_path.parent / f".{final_path.name}.partial"
    temp_path.unlink(missing_ok=True)
    try:
        shutil.copyfile(payload_path, temp_path)
        final_path.unlink(missing_ok=True)
        temp_path.replace(final_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    metadata["storage_relative_path"] = relative_path.as_posix()
    return metadata, final_path


def process_completed_job(request_id: str, state: dict[str, Any]) -> None:
    job_dir = WORK_ROOT / "jobs" / request_id
    with state_lock:
        job = (state.get("jobs") or {}).get(request_id)
        if not job or job.get("status") != "processing":
            return

    try:
        if str(job.get("mode") or "legacy") == "chunked":
            metadata, final_path = write_chunked_payload_to_disk(job_dir, job)
        else:
            metadata, payload_path = extract_archive(job_dir, job)
            metadata, final_path = write_payload_to_disk(metadata, payload_path)
        relative_path = storage_relative_path(
            str(metadata.get("storage_relative_path") or metadata.get("object_key") or ""),
            str(metadata.get("payload_file_name") or final_path.name),
        )
        location = public_disk_url(relative_path)
        with httpx.Client() as client:
            backend = "disk"
            send_channel_control(
                client,
                CONTROL_DONE_PREFIX,
                {"request_id": request_id, "backend": backend, "url": location},
            )
        with state_lock:
            state.setdefault("completed_jobs", {})[request_id] = {
                "completed_at": int(time.time()),
                "location": location,
                "backend": backend,
                "metadata": metadata,
            }
            state.get("jobs", {}).pop(request_id, None)
            save_state(state)
        shutil.rmtree(job_dir, ignore_errors=True)
        log.info("Completed request %s -> %s", request_id, location)
    except Exception as exc:
        error_text = str(exc).strip() or exc.__class__.__name__
        log.exception("Failed processing request %s", request_id)
        with httpx.Client() as client:
            send_channel_control(client, CONTROL_FAIL_PREFIX, {"request_id": request_id, "error": error_text})
        with state_lock:
            state.setdefault("failed_jobs", {})[request_id] = {
                "failed_at": int(time.time()),
                "error": error_text,
            }
            if request_id in state.get("jobs", {}):
                state["jobs"][request_id]["status"] = "failed"
            save_state(state)


def all_parts_present(job: dict[str, Any], job_dir: Path) -> bool:
    total = int(job.get("total") or 0)
    parts = job.get("parts") or {}
    if total <= 0 or len(parts) < total:
        return False
    for index in range(1, total + 1):
        volume_name = parts.get(str(index))
        if not volume_name:
            return False
        if not (job_dir / "parts" / volume_name).is_file():
            return False
    return True


def missing_part_indexes(job: dict[str, Any], job_dir: Path) -> list[int]:
    total = int(job.get("total") or 0)
    if total <= 0:
        return []
    parts = job.get("parts") or {}
    missing: list[int] = []
    for index in range(1, total + 1):
        volume_name = parts.get(str(index))
        if not volume_name:
            missing.append(index)
            continue
        if not (job_dir / "parts" / volume_name).is_file():
            missing.append(index)
    return missing


def maybe_queue_processing(request_id: str, state: dict[str, Any], job_dir: Path) -> bool:
    with state_lock:
        job = (state.get("jobs") or {}).get(request_id)
        if not job:
            return False
        if not job.get("upload_complete"):
            return False
        if not all_parts_present(job, job_dir):
            return False
        if job.get("status") != "pending":
            return job.get("status") == "processing"
        job["status"] = "processing"
        job["updated_at"] = int(time.time())
        save_state(state)
    try:
        job_queue.put_nowait(request_id)
        return True
    except queue.Full:
        with state_lock:
            job = (state.get("jobs") or {}).get(request_id)
            if job:
                job["status"] = "failed"
                job["updated_at"] = int(time.time())
            state.setdefault("failed_jobs", {})[request_id] = {
                "failed_at": int(time.time()),
                "error": "receiver queue is full",
            }
            save_state(state)
        return False


def request_missing_parts(client: httpx.Client, request_id: str, state: dict[str, Any]) -> None:
    job_dir = WORK_ROOT / "jobs" / request_id
    with state_lock:
        job = (state.get("jobs") or {}).get(request_id)
        if not job or job.get("status") in {"failed", "processing"}:
            return
        if not job.get("upload_complete"):
            return
        missing = missing_part_indexes(job, job_dir)
        if not missing:
            return
        attempts = int(job.get("recovery_attempts") or 0)
        if attempts >= MISSING_PART_RETRIES:
            error_text = f"missing archive parts after {attempts} recovery attempts: {missing}"
            job["status"] = "failed"
            job["updated_at"] = int(time.time())
            state.setdefault("failed_jobs", {})[request_id] = {
                "failed_at": int(time.time()),
                "error": error_text,
            }
            save_state(state)
            should_fail = True
        else:
            job["recovery_attempts"] = attempts + 1
            job["updated_at"] = int(time.time())
            save_state(state)
            should_fail = False
    if should_fail:
        send_channel_control(client, CONTROL_FAIL_PREFIX, {"request_id": request_id, "error": error_text})
        return
    log.warning("Requesting recovery for %s missing parts %s", request_id, missing)
    send_channel_control(
        client,
        CONTROL_RETRY_PREFIX,
        {"request_id": request_id, "missing": missing, "attempt": attempts + 1},
    )


def handle_control_message(client: httpx.Client, message: dict[str, Any], state: dict[str, Any]) -> None:
    if not same_channel(message):
        return
    parsed = parse_control_message(str(message.get("text") or ""))
    if not parsed:
        return
    kind, payload = parsed
    if kind != "upload_done":
        return

    request_id = str(payload.get("request_id") or "").strip()
    total_parts = int(payload.get("total") or 0)
    if not request_id or total_parts <= 0:
        return

    mode = str(payload.get("mode") or "legacy").strip() or "legacy"
    with state_lock:
        if request_id in state.get("completed_jobs", {}) or request_id in state.get("failed_jobs", {}):
            return
        job = state.setdefault("jobs", {}).setdefault(
            request_id,
            {"parts": {}, "total": total_parts, "status": "pending", "mode": mode, "request_id": request_id},
        )
        if job.get("status") == "failed":
            return
        job["total"] = max(int(job.get("total") or 0), total_parts)
        job["mode"] = mode
        job["request_id"] = request_id
        if mode == "chunked":
            job["payload_file_name"] = str(payload.get("payload_file_name") or job.get("payload_file_name") or "").strip()
            job["payload_size"] = int(payload.get("payload_size") or job.get("payload_size") or 0)
            job["payload_sha256"] = str(payload.get("payload_sha256") or job.get("payload_sha256") or "").strip()
            job["object_key"] = str(payload.get("object_key") or job.get("object_key") or "").strip()
        job["upload_complete"] = True
        job["updated_at"] = int(time.time())
        save_state(state)

    job_dir = WORK_ROOT / "jobs" / request_id
    if maybe_queue_processing(request_id, state, job_dir):
        return
    request_missing_parts(client, request_id, state)


def handle_document_message(client: httpx.Client, message: dict[str, Any], state: dict[str, Any]) -> None:
    if not same_channel(message):
        return
    document = message.get("document")
    if not isinstance(document, dict):
        return
    part = extract_part_info(message)
    if not part:
        return

    request_id = str(part["request_id"])
    part_index = int(part["part"])
    total_parts = int(part["total"])
    mode = str(part["mode"])
    volume_name = str(part["volume"])

    with state_lock:
        if request_id in state.get("completed_jobs", {}) or request_id in state.get("failed_jobs", {}):
            return
        job = state.setdefault("jobs", {}).setdefault(
            request_id,
            {"parts": {}, "total": total_parts, "status": "pending", "mode": mode, "request_id": request_id},
        )
        if job.get("status") == "failed":
            return
        if total_parts > 0:
            job["total"] = max(int(job.get("total") or 0), total_parts)
        job["mode"] = mode
        job["request_id"] = request_id
        job["updated_at"] = int(time.time())
        save_state(state)

    job_dir = WORK_ROOT / "jobs" / request_id
    parts_dir = job_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    destination = parts_dir / volume_name
    if not destination.exists():
        log.info("Downloading %s part %d/%d", request_id, part_index, total_parts)
        try:
            download_document(client, document, destination)
        except Exception:
            log.exception("Failed downloading %s part %d/%d; waiting for recovery", request_id, part_index, total_parts)
            return

    with state_lock:
        job = state.setdefault("jobs", {}).setdefault(
            request_id,
            {"parts": {}, "total": total_parts, "status": "pending", "mode": mode, "request_id": request_id},
        )
        job["parts"][str(part_index)] = volume_name
        job["mode"] = mode
        job["updated_at"] = int(time.time())
        save_state(state)
    maybe_queue_processing(request_id, state, job_dir)


def job_worker(state: dict[str, Any]) -> None:
    while True:
        request_id = job_queue.get()
        try:
            process_completed_job(request_id, state)
        finally:
            job_queue.task_done()


def start_workers(state: dict[str, Any]) -> None:
    global workers_started
    if workers_started:
        return
    workers_started = True
    for index in range(WORKER_COUNT):
        thread = threading.Thread(target=job_worker, args=(state,), name=f"receiver-worker-{index + 1}", daemon=True)
        thread.start()


def start_public_download_cleanup_worker() -> None:
    global download_cleanup_started
    if download_cleanup_started:
        return
    download_cleanup_started = True
    thread = threading.Thread(
        target=public_download_cleanup_worker,
        name="receiver-public-download-cleanup",
        daemon=True,
    )
    thread.start()


def requeue_processing_jobs(state: dict[str, Any]) -> None:
    with state_lock:
        jobs = dict(state.get("jobs") or {})
    for request_id, job in jobs.items():
        if job.get("status") == "processing":
            try:
                job_queue.put_nowait(request_id)
            except queue.Full:
                break


def poll_forever() -> None:
    ensure_prerequisites()
    state = load_state()
    start_workers(state)
    start_public_download_cleanup_worker()
    requeue_processing_jobs(state)

    with httpx.Client() as client:
        me = api_post(client, "getMe").get("result", {})
        log.info("Receiver bot ready: %s", me.get("username") or me.get("id") or "?")
        log.info("Listening to Bale channel %s", CHANNEL_CHAT_ID)

        while True:
            try:
                with state_lock:
                    offset = state.get("offset")
                params: dict[str, Any] = {"timeout": POLL_TIMEOUT, "allowed_updates": '["message"]'}
                if offset is not None:
                    params["offset"] = offset
                updates = api_get(client, "getUpdates", params=params).get("result", [])
                if not updates:
                    time.sleep(IDLE_SLEEP)
                    continue
                for update in updates:
                    with state_lock:
                        state["offset"] = int(update["update_id"]) + 1
                        save_state(state)
                    message = update.get("message")
                    if isinstance(message, dict):
                        handle_control_message(client, message, state)
                        handle_document_message(client, message, state)
            except httpx.TimeoutException:
                continue
            except Exception:
                log.exception("Receiver polling error")
                time.sleep(5)


if __name__ == "__main__":
    poll_forever()
