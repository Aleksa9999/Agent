# Deployment guide for the owner

This guide never contains secrets, server addresses or domains. Real values live only in
`.env.test` and `.env.prod` on the server (`chmod 600`, owner `googlagent`, never in Git).

## What runs

| Service | What it does |
|---|---|
| `db` | PostgreSQL 16, data in a Docker volume |
| `redis` | Redis 7 with a password, internal network only |
| `bot-api` | FastAPI app: `/health` now; Telegram webhook and Mini App API in later slices |

Nginx and certbot run on the host (`deploy/nginx.conf` is the site template).

## First start of the test stack (about 15 minutes)

1. Copy `.env.example` to `.env.test` and fill it. Add two lines for the stack itself:
   `POSTGRES_PASSWORD=` and `REDIS_PASSWORD=` (long random values; enter them on the server, do not paste them into chats).
2. `chmod 600 .env.test`.
3. `make stack-up`.
4. `curl http://127.0.0.1:8000/health` must answer `{"status":"ok", ...}` and show both `db` and `redis` as `ok`.
5. Copy `deploy/nginx.conf` to Nginx, replace `APP_DOMAIN`, run certbot, reload Nginx.
6. Register the webhook and menus once: `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml exec bot-api python -m app.bot.setup`.
7. In the test group make the bot an administrator with the rights to manage topics, pin and delete messages. Turn off privacy mode in BotFather.

Also set `TG_WEBHOOK_SECRET` (a long random value), `GROUP_CHAT_ID`, `OWNER_TG_ID` and `WEBAPP_URL` (the public https address of this server).

Use the test bot token (`TG_TEST_BOT_TOKEN`) and the test group. The production token is touched only after the owner approves with `/deploy_approve`.

## Before every change to the live system

1. `BACKUP_LABEL=prod deploy/backup.sh` (needs `DATABASE_URL`; keeps the newest 7 dumps, verifies each one).
2. Check the rollback: `deploy/rollback.sh test --dry-run` (needs `PREV_TAG`), and `deploy/rollback.sh prod --confirm-owner --dry-run`.

## Rollback

- Test stack: `PREV_TAG=<previous image tag> deploy/rollback.sh test`.
- Production: `deploy/rollback.sh prod --confirm-owner`. It stops the new stack, removes the Telegram webhook and starts the legacy V1 service (`airobotbro-edu`, polling). It refuses to run without `--confirm-owner`.
- When to roll back: the bot is silent for more than 5 minutes, more than 10% of requests fail within 15 minutes, or users are charged wrongly.
- Database rollback: restore the last dump taken before the change with `pg_restore`.

## Without Docker (development machine)

`make native-up` starts a real PostgreSQL 16 and Redis 7 on local ports and the app on port 8000; `make native-down` stops them.

## Checks

`make check` runs the linter, all tests and the skill validator. CI runs the same checks plus a secret scan of the whole Git history.
