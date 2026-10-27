# Deployment guide for the owner

This guide never contains secrets, server addresses or domains. Real values live only in
`.env.test` and `.env.prod` on the server (`chmod 600`, owner `googlagent`, never in Git).

## What runs

| Service | What it does |
|---|---|
| `db` | PostgreSQL 16, data in a Docker volume |
| `redis` | Redis 7 with a password, internal network only |
| `bot-api` | FastAPI app: `/health`, Telegram webhook, Mini App session API |
| `miniapp` | Next.js Mini App opened from Telegram (served on `/`; the API lives under `/api`) |

Nginx and certbot run on the host (`deploy/nginx.conf` is the site template).

## Quick path on a fresh Ubuntu server (as root)

```
apt-get update && apt-get install -y git
git clone https://github.com/Aleksa9999/Agent.git && cd Agent
bash deploy/bootstrap-server.sh check      # memory, disk, system: stops if the server is too small
bash deploy/bootstrap-server.sh install    # Docker, Nginx, certbot, firewall (22, 80, 443)
bash deploy/bootstrap-server.sh env        # random passwords; asks for the bot token and ids (hidden)
bash deploy/bootstrap-server.sh up         # builds and starts the stack, waits for /health
bash deploy/bootstrap-server.sh nginx app.example.com [you@example.com]   # needs the DNS record first; email is optional
bash deploy/bootstrap-server.sh webhook    # registers the Telegram webhook and menus
```

The DNS record (type A) for the domain must point to this server before the `nginx` step.
The manual version of the same steps follows.

## First start of the test stack, manual version (about 15 minutes)

1. Copy `.env.example` to `.env.test` and fill it, including `TG_WEBHOOK_SECRET`, `GROUP_CHAT_ID`, `OWNER_TG_ID` and `WEBAPP_URL` (the public https address of this server). For the agent set `QWEN_API_KEY` (the Model Studio key, International region), `QWEN_MODEL` and `QWEN_FAST_MODEL` (exact model ids from the Model Studio console; without them the agent answers that it is unavailable). Add two lines for the stack itself:
   `POSTGRES_PASSWORD=` and `REDIS_PASSWORD=` (long random values; enter them on the server, do not paste them into chats).
2. `chmod 600 .env.test`.
3. `make stack-up` (it passes `--env-file .env.test` to Docker Compose).
4. `curl http://127.0.0.1:8000/health` must answer `{"status":"ok", ...}` and show both `db` and `redis` as `ok`.
5. Copy `deploy/nginx.conf` to Nginx, replace `APP_DOMAIN`, run certbot, reload Nginx.
6. Register the webhook and menus once: `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml exec bot-api python -m app.bot.setup`.
7. In the test group make the bot an administrator with the rights to manage topics, pin and delete messages. Turn off privacy mode in BotFather.

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

`make check` runs the linter, all tests, the skill validator and the Mini App checks (types, tests, build). CI runs the same checks plus a secret scan of the whole Git history.
