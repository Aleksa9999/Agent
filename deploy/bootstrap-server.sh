#!/usr/bin/env bash
# Prepares a fresh Ubuntu server for the test stack. Run as root from the repository root.
#   bash deploy/bootstrap-server.sh check            resources and system check (changes nothing)
#   bash deploy/bootstrap-server.sh install          Docker, Nginx, certbot, firewall (22, 80, 443 only)
#   bash deploy/bootstrap-server.sh env              create .env.test (random passwords, asks for the rest)
#   bash deploy/bootstrap-server.sh up               build and start the test stack, wait for /health
#   bash deploy/bootstrap-server.sh nginx DOMAIN EMAIL   site config and a TLS certificate
#   bash deploy/bootstrap-server.sh webhook          register the Telegram webhook and menus
# Secrets are typed with hidden input and written only to .env.test (mode 600). Nothing prints them.
set -euo pipefail

MIN_RAM_KB="${MIN_RAM_KB:-3500000}"      # about 3.5 GB
MIN_DISK_KB="${MIN_DISK_KB:-20000000}"   # about 20 GB free
MEMINFO="${BOOTSTRAP_MEMINFO:-/proc/meminfo}"
OS_RELEASE="${BOOTSTRAP_OS_RELEASE:-/etc/os-release}"
ENV_OUT="${ENV_OUT:-.env.test}"
COMPOSE=(docker compose --env-file "${ENV_OUT}" -f deploy/docker-compose.yml -f deploy/docker-compose.test.yml)

say() { printf '%s\n' "$*"; }
fail() { printf 'STOP: %s\n' "$*" >&2; exit 1; }

disk_free_kb() {
  if [[ -n "${BOOTSTRAP_DISK_KB:-}" ]]; then echo "${BOOTSTRAP_DISK_KB}"; else df --output=avail -k / | tail -1 | tr -d ' '; fi
}

check() {
  local ram_kb disk_kb cpus os_id version problems=0
  ram_kb="$(awk '/^MemTotal:/ {print $2}' "${MEMINFO}")"
  disk_kb="$(disk_free_kb)"
  cpus="$(nproc 2>/dev/null || echo 1)"
  # shellcheck disable=SC1090
  os_id="$(. "${OS_RELEASE}"; echo "${ID:-unknown}")"
  # shellcheck disable=SC1090
  version="$(. "${OS_RELEASE}"; echo "${VERSION_ID:-unknown}")"
  say "system : ${os_id} ${version}"
  say "memory : $((ram_kb / 1024)) MB   (needs at least $((MIN_RAM_KB / 1024)) MB)"
  say "disk   : $((disk_kb / 1024 / 1024)) GB free   (needs at least $((MIN_DISK_KB / 1024 / 1024)) GB)"
  say "cpu    : ${cpus} core(s)"
  if command -v docker >/dev/null 2>&1; then say "docker : $(docker --version)"; else say "docker : not installed"; fi
  if [[ "${os_id}" != "ubuntu" ]] || [[ "${version}" != "22.04" && "${version}" != "24.04" ]]; then
    say "PROBLEM: Ubuntu 22.04 or 24.04 is expected"; problems=1
  fi
  if (( ram_kb < MIN_RAM_KB )); then say "PROBLEM: not enough memory for the stack and its builds"; problems=1; fi
  if (( disk_kb < MIN_DISK_KB )); then say "PROBLEM: not enough free disk space"; problems=1; fi
  if (( problems == 0 )); then say "RESULT : suitable"; else say "RESULT : not suitable"; return 1; fi
}

install_all() {
  check || fail "the server does not meet the minimum, nothing was installed"
  [[ "$(id -u)" -eq 0 ]] || fail "run as root"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl git ufw nginx certbot python3-certbot-nginx openssl
  if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    local codename arch
    # shellcheck disable=SC1091
    codename="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
    arch="$(dpkg --print-architecture)"
    echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  # SSH is allowed before the firewall is switched on, so the session is never cut off
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
  docker --version
  docker compose version
  say "install ok"
}

random_hex() { openssl rand -hex 24; }

get_var() { [[ -f "${ENV_OUT}" ]] && grep -E "^$1=" "${ENV_OUT}" | head -1 | cut -d= -f2- || true; }

make_env() {
  umask 077
  local tmp
  tmp="$(mktemp)"
  cp .env.example "${tmp}"
  set_var() { # name value  (replaces the line, or appends it)
    if grep -qE "^$1=" "${tmp}"; then
      local escaped
      escaped="$(printf '%s' "$2" | sed -e 's/[\/&|]/\\&/g')"
      sed -i "s|^$1=.*|$1=${escaped}|" "${tmp}"
    else
      printf '%s=%s\n' "$1" "$2" >> "${tmp}"
    fi
  }
  ask() { # name prompt secret(1/0) required(1/0)
    local current value
    current="$(get_var "$1")"
    if [[ -n "${current}" ]]; then set_var "$1" "${current}"; return; fi
    value=""
    if [[ "$3" == "1" ]]; then read -rs -p "$2: " value || true; echo; else read -r -p "$2: " value || true; fi
    if [[ -z "${value}" && "$4" == "1" ]]; then rm -f "${tmp}"; fail "$1 is required"; fi
    [[ -n "${value}" ]] && set_var "$1" "${value}"
    return 0
  }
  for secret in POSTGRES_PASSWORD REDIS_PASSWORD TG_WEBHOOK_SECRET; do
    current="$(get_var "${secret}")"
    set_var "${secret}" "${current:-$(random_hex)}"
  done
  set_var APP_ENV test
  ask TG_TEST_BOT_TOKEN "Test bot token (hidden)" 1 1
  ask OWNER_TG_ID "Your Telegram id" 0 1
  ask GROUP_CHAT_ID "Test group id (starts with -100)" 0 1
  ask WEBAPP_URL "Public https address of this server, e.g. https://app.example.com" 0 1
  ask QWEN_API_KEY "Model Studio key (hidden, Enter to skip for now)" 1 0
  ask QWEN_MODEL "Model id from the console (Enter to skip for now)" 0 0
  ask QWEN_FAST_MODEL "Cheap model id for summaries (Enter to skip)" 0 0
  mv "${tmp}" "${ENV_OUT}"
  chmod 600 "${ENV_OUT}"
  say "${ENV_OUT} written (mode 600). Values are not shown."
}

up() {
  [[ -f "${ENV_OUT}" ]] || fail "${ENV_OUT} is missing: run the env step first"
  "${COMPOSE[@]}" up -d --build
  say "waiting for /health ..."
  for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
      curl -sS http://127.0.0.1:8000/health; echo
      return 0
    fi
    sleep 3
  done
  "${COMPOSE[@]}" ps
  fail "/health did not answer in 3 minutes (look at: docker compose logs bot-api)"
}

nginx_site() {
  local domain="${1:-}" email="${2:-}"
  [[ -n "${domain}" && -n "${email}" ]] || fail "usage: nginx DOMAIN EMAIL"
  [[ "${domain}" =~ ^[a-zA-Z0-9.-]+$ ]] || fail "the domain looks wrong"
  cat > /etc/nginx/sites-available/googlagent <<CONF
server {
    listen 80;
    server_name ${domain};
    client_max_body_size 25m;
    location ~ ^/(api|telegram|health) {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
CONF
  ln -sf /etc/nginx/sites-available/googlagent /etc/nginx/sites-enabled/googlagent
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl reload nginx
  certbot --nginx -d "${domain}" -m "${email}" --agree-tos --no-eff-email -n --redirect
  say "https is on for ${domain}"
}

webhook() {
  "${COMPOSE[@]}" exec bot-api python -m app.bot.setup
}

case "${1:-}" in
  check) check ;;
  install) install_all ;;
  env) make_env ;;
  up) up ;;
  nginx) shift; nginx_site "$@" ;;
  webhook) webhook ;;
  *) sed -n '2,11p' "$0"; exit 2 ;;
esac
