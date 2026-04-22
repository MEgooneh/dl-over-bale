#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx


LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dl-over-bale-text-receiver")

BOT_TOKEN = os.environ["BOT_TOKEN"]
SOURCE_CHAT_ID = str(os.environ.get("SOURCE_CHAT_ID", "")).strip()
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "30"))
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "20"))
START_OFFSET = int(os.environ.get("START_OFFSET", "0"))
BALE_API = f"https://tapi.bale.ai/bot{BOT_TOKEN}"


def api_get(client: httpx.Client, method: str, *, params: dict[str, Any]) -> dict[str, Any]:
    response = client.get(f"{BALE_API}/{method}", params=params, timeout=POLL_TIMEOUT + 5)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok", False):
        description = payload.get("description") or payload.get("error") or "unknown Bale API error"
        raise RuntimeError(f"Bale API {method} failed: {description}")
    return payload


def api_post(client: httpx.Client, method: str, **kwargs: Any) -> dict[str, Any]:
    response = client.post(f"{BALE_API}/{method}", timeout=REQUEST_TIMEOUT, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok", False):
        description = payload.get("description") or payload.get("error") or "unknown Bale API error"
        raise RuntimeError(f"Bale API {method} failed: {description}")
    return payload


def main() -> None:
    if not SOURCE_CHAT_ID:
        raise RuntimeError("SOURCE_CHAT_ID is required.")
    offset = START_OFFSET
    with httpx.Client() as client:
        me = api_post(client, "getMe").get("result", {})
        log.info("Receiver bot ready: %s", me.get("username") or me.get("id") or "?")
        log.info("Listening for channel/chat messages in %s starting at offset %s", SOURCE_CHAT_ID, offset)
        while True:
            try:
                updates = api_get(
                    client,
                    "getUpdates",
                    params={"timeout": POLL_TIMEOUT, "offset": offset, "allowed_updates": '["message"]'},
                ).get("result", [])
                if not updates:
                    continue
                for update in updates:
                    offset = int(update["update_id"]) + 1
                    message = update.get("message") or {}
                    chat = message.get("chat") or {}
                    if str(chat.get("id") or "") != SOURCE_CHAT_ID:
                        log.info("Ignored non-target update: %s", json.dumps(update, ensure_ascii=False))
                        continue
                    log.info("Received channel/chat update: %s", json.dumps(update, ensure_ascii=False))
            except httpx.TimeoutException:
                continue
            except Exception:
                log.exception("Receiver polling error")
                time.sleep(2)


if __name__ == "__main__":
    main()
