#!/usr/bin/env bash
# Roll back to the previous version.
#   deploy/rollback.sh test [--dry-run]                 restart the previous image tag in the test stack
#   deploy/rollback.sh prod --confirm-owner [--dry-run] stop the new stack and start the legacy V1 bot
# Env: PREV_TAG (test), COMPOSE_FILES (default: deploy/docker-compose.yml + test override),
#      V1_UNIT (default airobotbro-edu), TG_BOT_TOKEN (prod, to remove the webhook), OWNER_TG_ID
set -euo pipefail

TARGET="${1:-}"
shift || true
CONFIRM=0
DRY=0
for arg in "$@"; do
  case "$arg" in
    --confirm-owner) CONFIRM=1 ;;
    --dry-run) DRY=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

run() {
  if [[ $DRY -eq 1 ]]; then echo "dry-run: $*"; else "$@"; fi
}

case "$TARGET" in
  test)
    : "${PREV_TAG:?PREV_TAG is required (previous image tag)}"
    FILES="${COMPOSE_FILES:---env-file .env.test -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml}"
    # shellcheck disable=SC2086
    TAG="$PREV_TAG" run docker compose $FILES up -d --no-build
    echo "rollback ok: test stack on tag ${PREV_TAG}"
    ;;
  prod)
    if [[ $CONFIRM -ne 1 ]]; then
      echo "refused: production rollback needs --confirm-owner (alert criteria: no answer for 5 minutes," >&2
      echo "errors in over 10% of requests in 15 minutes, or wrong charges)" >&2
      exit 3
    fi
    FILES="${COMPOSE_FILES:---env-file .env.prod -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml}"
    UNIT="${V1_UNIT:-airobotbro-edu}"
    # shellcheck disable=SC2086
    run docker compose $FILES down
    if [[ -n "${TG_BOT_TOKEN:-}" && $DRY -eq 0 ]]; then
      # webhook off so the legacy bot can poll; the token stays out of the output
      curl -fsS "https://api.telegram.org/bot${TG_BOT_TOKEN}/deleteWebhook" >/dev/null
    else
      echo "dry-run: would delete the Telegram webhook"
    fi
    run systemctl start "${UNIT}"
    if [[ $DRY -eq 0 ]]; then
      systemctl is-active --quiet "${UNIT}" || { echo "legacy bot ${UNIT} is not active" >&2; exit 4; }
    fi
    echo "rollback ok: legacy V1 (${UNIT}) is running"
    ;;
  *)
    echo "usage: deploy/rollback.sh test|prod [--confirm-owner] [--dry-run]" >&2
    exit 2
    ;;
esac
