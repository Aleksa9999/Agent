#!/usr/bin/env bash
# Test stack WITHOUT Docker: real PostgreSQL 16 and Redis 7 on local ports, then the app.
# For development machines without a Docker daemon. On the server use `make stack-up`.
#   deploy/native-stack.sh up | down | health
set -euo pipefail

RUN_DIR="${STACK_DIR:-/tmp/googlagent-native}"
PG_PORT="${PG_PORT:-55432}"
REDIS_PORT="${REDIS_PORT:-56379}"
APP_PORT="${APP_PORT:-8000}"
PG_BIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)"
PG_USER="googlagent"
PG_DB="googlagent"
RUNAS=()
[[ "$(id -u)" -eq 0 ]] && RUNAS=(runuser -u postgres --)

case "${1:-}" in
  up)
    mkdir -p "$RUN_DIR"
    chown postgres "$RUN_DIR" 2>/dev/null || true
    if [[ ! -d "$RUN_DIR/pg" ]]; then
      "${RUNAS[@]}" "$PG_BIN/initdb" -D "$RUN_DIR/pg" -A trust -E UTF8 --locale=C.UTF-8 >/dev/null
    fi
    "${RUNAS[@]}" "$PG_BIN/pg_ctl" -D "$RUN_DIR/pg" -o "-p $PG_PORT -k $RUN_DIR" \
      -l "$RUN_DIR/pg.log" -w start >/dev/null
    "${RUNAS[@]}" "$PG_BIN/psql" -h "$RUN_DIR" -p "$PG_PORT" -d postgres -tc \
      "SELECT 1 FROM pg_roles WHERE rolname='$PG_USER'" | grep -q 1 \
      || "${RUNAS[@]}" "$PG_BIN/psql" -h "$RUN_DIR" -p "$PG_PORT" -d postgres \
           -c "CREATE ROLE $PG_USER LOGIN SUPERUSER" >/dev/null
    "${RUNAS[@]}" "$PG_BIN/psql" -h "$RUN_DIR" -p "$PG_PORT" -d postgres -tc \
      "SELECT 1 FROM pg_database WHERE datname='$PG_DB'" | grep -q 1 \
      || "${RUNAS[@]}" "$PG_BIN/createdb" -h "$RUN_DIR" -p "$PG_PORT" -O "$PG_USER" "$PG_DB"
    redis-server --port "$REDIS_PORT" --daemonize yes --dir "$RUN_DIR" \
      --pidfile "$RUN_DIR/redis.pid" --logfile "$RUN_DIR/redis.log" >/dev/null
    export DATABASE_URL="postgresql://$PG_USER@localhost:$PG_PORT/$PG_DB"
    export PGHOST="$RUN_DIR"  # unix-socket directory for psql and pg_dump
    export REDIS_URL="redis://localhost:$REDIS_PORT/0"
    python3 -m alembic upgrade head
    nohup python3 -m uvicorn app.main:app_factory --factory --host 127.0.0.1 \
      --port "$APP_PORT" > "$RUN_DIR/app.log" 2>&1 &
    echo $! > "$RUN_DIR/app.pid"
    for _ in $(seq 1 30); do
      curl -fsS "http://127.0.0.1:$APP_PORT/health" >/dev/null 2>&1 && break
      sleep 0.5
    done
    curl -sS "http://127.0.0.1:$APP_PORT/health"; echo
    ;;
  health)
    curl -sS -w '\nHTTP %{http_code}\n' "http://127.0.0.1:$APP_PORT/health"
    ;;
  down)
    [[ -f "$RUN_DIR/app.pid" ]] && kill "$(cat "$RUN_DIR/app.pid")" 2>/dev/null || true
    [[ -f "$RUN_DIR/redis.pid" ]] && kill "$(cat "$RUN_DIR/redis.pid")" 2>/dev/null || true
    "${RUNAS[@]}" "$PG_BIN/pg_ctl" -D "$RUN_DIR/pg" -m fast stop >/dev/null 2>&1 || true
    echo "stopped"
    ;;
  *)
    echo "usage: deploy/native-stack.sh up|down|health" >&2
    exit 2
    ;;
esac
