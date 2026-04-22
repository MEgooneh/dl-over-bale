#!/bin/sh
set -eu

OUTPUT_PATH="${REAL_IP_CONFIG_PATH:-/etc/nginx/real-ip.conf}"
TRUSTED_PROXY_CIDRS="${TRUSTED_PROXY_CIDRS:-}"

if [ -z "$TRUSTED_PROXY_CIDRS" ]; then
  printf '%s\n' '# no trusted proxy CIDRs configured' >"$OUTPUT_PATH"
  exit 0
fi

{
  printf '%s\n' 'real_ip_header X-Forwarded-For;'
  printf '%s\n' 'real_ip_recursive on;'
  printf '%s\n' "$TRUSTED_PROXY_CIDRS" | tr ', ' '\n\n' | sed '/^$/d' | while IFS= read -r cidr; do
    printf 'set_real_ip_from %s;\n' "$cidr"
  done
} >"$OUTPUT_PATH"
