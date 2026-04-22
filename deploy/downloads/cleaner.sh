#!/bin/sh
set -eu

DOWNLOAD_ROOT="${DOWNLOAD_ROOT:-/srv/downloads}"
TTL_MINUTES="${DOWNLOAD_FILE_TTL_MINUTES:-180}"
SCAN_INTERVAL="${DOWNLOAD_CLEAN_INTERVAL_SECONDS:-300}"

mkdir -p "$DOWNLOAD_ROOT"

while true; do
  find "$DOWNLOAD_ROOT" -xdev -type f -mmin "+${TTL_MINUTES}" -delete || true
  find "$DOWNLOAD_ROOT" -xdev -mindepth 1 -depth -type d -empty -delete || true
  sleep "$SCAN_INTERVAL"
done
