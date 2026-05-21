#!/bin/sh
set -eu

AUTH_CONFIG_PATH="${BASIC_AUTH_CONFIG_PATH:-/etc/nginx/download-basic-auth.conf}"
SIGNED_LINK_CONFIG_PATH="${SIGNED_LINK_CONFIG_PATH:-/etc/nginx/download-signed-link.conf}"
DOWNLOAD_BASIC_AUTH_USER="${DOWNLOAD_BASIC_AUTH_USER:-}"
DOWNLOAD_BASIC_AUTH_PASSWORD="${DOWNLOAD_BASIC_AUTH_PASSWORD:-}"
DOWNLOAD_LINK_SECRET="${DOWNLOAD_LINK_SECRET:-}"

if [ -n "$DOWNLOAD_BASIC_AUTH_USER" ] || [ -n "$DOWNLOAD_BASIC_AUTH_PASSWORD" ]; then
  if [ -z "$DOWNLOAD_BASIC_AUTH_USER" ] || [ -z "$DOWNLOAD_BASIC_AUTH_PASSWORD" ]; then
    printf '%s\n' 'Set both DOWNLOAD_BASIC_AUTH_USER and DOWNLOAD_BASIC_AUTH_PASSWORD, or leave both empty.' >&2
    exit 1
  fi
  htpasswd -Bbc /etc/nginx/.htpasswd "$DOWNLOAD_BASIC_AUTH_USER" "$DOWNLOAD_BASIC_AUTH_PASSWORD"
  {
    printf '%s\n' 'auth_basic "Protected downloads";'
    printf '%s\n' 'auth_basic_user_file /etc/nginx/.htpasswd;'
  } >"$AUTH_CONFIG_PATH"
else
  printf '%s\n' '# basic auth disabled' >"$AUTH_CONFIG_PATH"
fi

if [ -n "$DOWNLOAD_LINK_SECRET" ]; then
  case "$DOWNLOAD_LINK_SECRET" in
    *\"*|*\\*)
      printf '%s\n' 'DOWNLOAD_LINK_SECRET cannot contain double quotes or backslashes.' >&2
      exit 1
      ;;
  esac
  {
    printf '%s\n' 'secure_link $arg_md5,$arg_expires;'
    printf '%s%s%s\n' 'secure_link_md5 "$secure_link_expires$uri ' "$DOWNLOAD_LINK_SECRET" '";'
    printf '%s\n' 'if ($secure_link = "") {'
    printf '%s\n' '    return 403;'
    printf '%s\n' '}'
    printf '%s\n' 'if ($secure_link = "0") {'
    printf '%s\n' '    return 410;'
    printf '%s\n' '}'
  } >"$SIGNED_LINK_CONFIG_PATH"
else
  printf '%s\n' '# signed links disabled' >"$SIGNED_LINK_CONFIG_PATH"
fi
