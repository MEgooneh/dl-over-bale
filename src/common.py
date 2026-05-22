"""Shared Bale API, wire protocol, and crypto helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from collections.abc import Iterable
from typing import Any

import httpx

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"

CONTROL_DONE_PREFIX = "BALE_DONE "
CONTROL_FAIL_PREFIX = "BALE_FAIL "
CONTROL_UPLOAD_DONE_PREFIX = "BALE_UPLOAD_DONE "
CONTROL_RETRY_PREFIX = "BALE_RETRY "
PART_CAPTION_PREFIX = "~"
PART_CAPTION_RE = re.compile(r"^~([A-Za-z0-9_-]+)$")

URL_CIPHER_CONTEXT = b"dl-over-bale-url-v1"
TRANSPORT_CIPHER_CONTEXT = b"dl-over-bale-meta-v1"


def configure_logging(logger_name: str) -> logging.Logger:
    logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
    return logging.getLogger(logger_name)


def bale_api_url(bot_token: str) -> str:
    return f"https://tapi.bale.ai/bot{bot_token}"


def first_configured_id(raw: str) -> str:
    for item in raw.split(","):
        value = item.strip()
        if value:
            return value
    return ""


def sanitize_error_text(value: object, *sensitive_values: str) -> str:
    text = str(value).strip()
    for sensitive_value in sensitive_values:
        if sensitive_value:
            text = text.replace(sensitive_value, "<bot-token>")
    return text


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


def api_get(
    client: httpx.Client,
    api_base_url: str,
    method: str,
    *,
    params: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    response = client.get(f"{api_base_url}/{method}", params=params, timeout=timeout)
    response.raise_for_status()
    return checked_api_payload(method, response.json())


def api_post(
    client: httpx.Client,
    api_base_url: str,
    method: str,
    *,
    timeout: float,
    **kwargs: Any,
) -> dict[str, Any]:
    response = client.post(f"{api_base_url}/{method}", timeout=timeout, **kwargs)
    response.raise_for_status()
    return checked_api_payload(method, response.json())


def checked_api_payload(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("ok", False):
        description = payload.get("description") or payload.get("error") or "unknown Bale API error"
        raise RuntimeError(f"Bale API {method} failed: {description}")
    return payload


def send_channel_control(
    client: httpx.Client,
    api_base_url: str,
    channel_chat_id: str,
    prefix: str,
    payload: dict[str, Any],
    password: str,
    *,
    timeout: float,
) -> None:
    text = prefix + encrypt_transport_payload(payload, password)
    api_post(client, api_base_url, "sendMessage", json={"chat_id": channel_chat_id, "text": text}, timeout=timeout)


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


def get_file_url(file_result: dict[str, Any], bot_token: str) -> str:
    file_path = file_result.get("file_path") or file_result.get("url") or file_result.get("download_url") or ""
    if not file_path:
        raise RuntimeError(f"getFile did not return a file_path-like value: {file_result}")
    if str(file_path).startswith(("http://", "https://")):
        return str(file_path)
    return f"https://tapi.bale.ai/file/bot{bot_token}/{str(file_path).lstrip('/')}"


def xor_keystream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < len(data):
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        remaining = len(data) - len(output)
        output.extend(block[:remaining])
        counter += 1
    return bytes(left ^ right for left, right in zip(data, output))


def encrypt_response_value(value: str, password: str) -> str:
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    key_material = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000, dklen=64)
    enc_key = key_material[:32]
    mac_key = key_material[32:]
    plaintext = value.encode("utf-8")
    ciphertext = xor_keystream(plaintext, enc_key, nonce)
    mac = hmac.new(mac_key, URL_CIPHER_CONTEXT + salt + nonce + ciphertext, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(salt + nonce + mac + ciphertext).decode("ascii").rstrip("=")
    return f"enc-v1.{token}"


def encrypt_transport_payload(payload: dict[str, Any], password: str) -> str:
    salt = secrets.token_bytes(12)
    nonce = secrets.token_bytes(12)
    key_material = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000, dklen=64)
    enc_key = key_material[:32]
    mac_key = key_material[32:]
    plaintext = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ciphertext = xor_keystream(plaintext, enc_key, nonce)
    mac = hmac.new(mac_key, TRANSPORT_CIPHER_CONTEXT + salt + nonce + ciphertext, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(salt + nonce + mac + ciphertext).decode("ascii").rstrip("=")


def decrypt_transport_payload(
    token: str,
    primary_password: str,
    fallback_password: str = "",
) -> dict[str, Any] | None:
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
    keys = [primary_password]
    if fallback_password and fallback_password != primary_password:
        keys.append(fallback_password)

    for key in keys:
        key_material = hashlib.pbkdf2_hmac("sha256", key.encode("utf-8"), salt, 120_000, dklen=64)
        enc_key = key_material[:32]
        mac_key = key_material[32:]
        expected_mac = hmac.new(
            mac_key,
            TRANSPORT_CIPHER_CONTEXT + salt + nonce + ciphertext,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(mac, expected_mac):
            continue
        try:
            plaintext = xor_keystream(ciphertext, enc_key, nonce).decode("utf-8")
            payload = json.loads(plaintext)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def parse_control_message(
    text: str,
    prefixes: Iterable[tuple[str, str]],
    primary_password: str,
    fallback_password: str = "",
) -> tuple[str, dict[str, Any]] | None:
    stripped = text.strip()
    for prefix, kind in prefixes:
        if not stripped.startswith(prefix):
            continue
        payload = decrypt_transport_payload(stripped[len(prefix) :].strip(), primary_password, fallback_password)
        if payload is not None:
            return kind, payload
    return None


def build_part_caption(
    request_id: str,
    part_index: int,
    part_total: int,
    volume_name: str,
    *,
    mode: str,
    password: str,
) -> str:
    payload = {"r": request_id, "p": part_index, "t": part_total, "v": volume_name, "m": mode}
    return PART_CAPTION_PREFIX + encrypt_transport_payload(payload, password)


def extract_part_info(
    message: dict[str, Any],
    primary_password: str,
    fallback_password: str = "",
) -> dict[str, Any] | None:
    caption = str(message.get("caption") or "").strip()
    match = PART_CAPTION_RE.match(caption)
    if not match:
        return None
    payload = decrypt_transport_payload(match.group(1), primary_password, fallback_password)
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
