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
log = logging.getLogger("dl-over-bale-text-sender")

BOT_TOKEN = os.environ["BOT_TOKEN"]
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID", "").strip()
MESSAGE_TEXT = os.environ.get("MESSAGE_TEXT", f"dl-over-bale sender test {int(time.time())}")
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "30"))
BALE_API = f"https://tapi.bale.ai/bot{BOT_TOKEN}"


def api_call(client: httpx.Client, method: str, **kwargs: Any) -> dict[str, Any]:
    response = client.post(f"{BALE_API}/{method}", timeout=REQUEST_TIMEOUT, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok", False):
        description = payload.get("description") or payload.get("error") or "unknown Bale API error"
        raise RuntimeError(f"Bale API {method} failed: {description}")
    return payload


def main() -> None:
    if not TARGET_CHAT_ID:
        raise RuntimeError("TARGET_CHAT_ID is required.")
    with httpx.Client() as client:
        me = api_call(client, "getMe").get("result", {})
        log.info("Sender bot ready: %s", me.get("username") or me.get("id") or "?")
        result = api_call(
            client,
            "sendMessage",
            json={"chat_id": TARGET_CHAT_ID, "text": MESSAGE_TEXT},
        ).get("result", {})
        log.info("Sent message: %s", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
