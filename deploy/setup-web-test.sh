#!/usr/bin/env bash
# Тестовая копия веб-версии «Мой Доктор» на боевом VPS.
#
# Что делает: ставит ветку web-app в ОТДЕЛЬНУЮ папку (/opt/my_doctor_web) со своим
# окружением Python, ПУСТОЙ базой и отдельным сервисом, и открывает её по HTTPS через Caddy
# на адресе вида <ip-с-дефисами>.sslip.io (домен покупать не нужно).
# Бот (/opt/my_doctor_bot, сервис mydoctor), его база и его окружение НЕ затрагиваются.
#
# Запуск на сервере, от root:
#   cd /opt/my_doctor_bot && git fetch origin web-app && git show origin/web-app:deploy/setup-web-test.sh > /root/setup-web-test.sh
#   less /root/setup-web-test.sh          # посмотреть, что будет выполнено
#   bash /root/setup-web-test.sh          # установить / обновить
#   bash /root/setup-web-test.sh remove   # полностью убрать тестовую копию
set -euo pipefail

BOT_DIR=/opt/my_doctor_bot
WEB_DIR=/opt/my_doctor_web
BRANCH=web-app
SERVICE=mydoctor-web-test
SVC_USER=mydoctorweb
PORT=8001
PUBLIC_IP="${PUBLIC_IP:-72.56.124.160}"
HOST="${PUBLIC_IP//./-}.sslip.io"
CADDYFILE=/etc/caddy/Caddyfile
MARK_BEGIN="# >>> mydoctor-web-test"
MARK_END="# <<< mydoctor-web-test"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die()  { printf '\n\033[31mОШИБКА: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "запускайте от root"
[ -d "$BOT_DIR/.git" ] || die "не найден репозиторий бота в $BOT_DIR"

# ── Удаление ────────────────────────────────────────────────────────────────
if [ "${1:-}" = "remove" ]; then
  say "Останавливаю и удаляю тестовую копию (бот не трогаю)"
  systemctl disable --now "$SERVICE" 2>/dev/null || true
  rm -f "/etc/systemd/system/$SERVICE.service"
  systemctl daemon-reload
  if [ -f "$CADDYFILE" ] && grep -qF "$MARK_BEGIN" "$CADDYFILE"; then
    sed -i "/$MARK_BEGIN/,/$MARK_END/d" "$CADDYFILE"
    systemctl reload caddy 2>/dev/null || true
  fi
  git -C "$BOT_DIR" worktree remove --force "$WEB_DIR" 2>/dev/null || rm -rf "$WEB_DIR"
  git -C "$BOT_DIR" worktree prune
  id "$SVC_USER" >/dev/null 2>&1 && userdel "$SVC_USER" 2>/dev/null || true
  echo "Готово. Тестовая копия удалена. Бот работает как раньше."
  exit 0
fi

# ── Проверки ────────────────────────────────────────────────────────────────
say "Проверяю сервер"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "нужен Python 3.10 или новее (сейчас: $(python3 --version 2>&1))"
python3 -c 'import ensurepip, venv' 2>/dev/null \
  || die "не хватает модуля venv. Установите: apt install -y python3-venv   и запустите скрипт снова"
avail_mb=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
echo "Свободной памяти: ${avail_mb} МБ"
[ "$avail_mb" -ge 250 ] || echo "ВНИМАНИЕ: памяти мало — установка зависимостей может быть медленной или оборваться."

for port in 80 443; do
  owner=$(ss -ltnpH "sport = :$port" 2>/dev/null | awk '{print $NF}' | head -1 || true)
  if [ -n "$owner" ] && ! printf '%s' "$owner" | grep -q caddy; then
    die "порт $port уже занят ($owner). Освободите его или настройте этот сайт в вашем веб-сервере вручную."
  fi
done

# ── Код ─────────────────────────────────────────────────────────────────────
say "Получаю ветку $BRANCH (рабочая копия бота не меняется)"
git -C "$BOT_DIR" fetch origin "$BRANCH"
if [ -d "$WEB_DIR" ]; then
  git -C "$WEB_DIR" checkout --detach --force "origin/$BRANCH"
else
  git -C "$BOT_DIR" worktree add --detach "$WEB_DIR" "origin/$BRANCH"
fi

# ── Python-окружение (своё, окружение бота не используется и не меняется) ───
say "Ставлю зависимости в отдельное окружение"
[ -x "$WEB_DIR/venv/bin/python" ] || python3 -m venv "$WEB_DIR/venv"
"$WEB_DIR/venv/bin/python" -m pip install -q --upgrade pip
"$WEB_DIR/venv/bin/python" -m pip install -q -r "$WEB_DIR/requirements.txt"

# ── Настройки (создаются один раз, повторный запуск их не перезаписывает) ───
say "Готовлю настройки"
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$SVC_USER"
mkdir -p "$WEB_DIR/data"
chown "$SVC_USER":"$SVC_USER" "$WEB_DIR/data"

if [ ! -f "$WEB_DIR/.env" ]; then
  groq_line=$(grep -E '^GROQ_API_KEY=' "$BOT_DIR/.env" || true)
  [ -n "$groq_line" ] || die "в $BOT_DIR/.env нет GROQ_API_KEY — без него консультация не заработает"
  {
    echo "$groq_line"
    echo "API_JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
    echo "DATABASE_PATH=$WEB_DIR/data/web_test.db"
    # Коды входа пишутся в журнал сервера (письма не настроены) — только для закрытого теста.
    echo "WEB_DEV_PRINT_CODES=true"
    echo "TRUST_PROXY_HEADERS=true"
    # Ключ Groq общий с ботом — ограничиваем расход тестовой копии.
    echo "WEB_DAILY_MESSAGE_LIMIT=40"
  } > "$WEB_DIR/.env"
fi
chown root:"$SVC_USER" "$WEB_DIR/.env"
chmod 640 "$WEB_DIR/.env"

# ── Сервис ──────────────────────────────────────────────────────────────────
say "Настраиваю сервис $SERVICE"
cat > "/etc/systemd/system/$SERVICE.service" <<UNIT
[Unit]
Description=Мой Доктор — тестовая веб-версия
After=network.target

[Service]
Type=simple
User=$SVC_USER
Group=$SVC_USER
WorkingDirectory=$WEB_DIR
EnvironmentFile=$WEB_DIR/.env
ExecStart=$WEB_DIR/venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port $PORT
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$WEB_DIR/data

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"

for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 \
  || die "сервис не поднялся. Смотрите: journalctl -u $SERVICE -n 50 --no-pager"

# ── HTTPS (Caddy) ───────────────────────────────────────────────────────────
say "Настраиваю HTTPS на $HOST"
if ! command -v caddy >/dev/null 2>&1; then
  echo "Caddy не найден — ставлю из официального репозитория (Debian/Ubuntu)"
  command -v apt-get >/dev/null 2>&1 || die "автоустановка Caddy поддерживается только на Debian/Ubuntu; поставьте Caddy вручную и запустите скрипт снова"
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y -qq caddy
fi
mkdir -p "$(dirname "$CADDYFILE")"
touch "$CADDYFILE"
if ! grep -qF "$MARK_BEGIN" "$CADDYFILE"; then
  cat >> "$CADDYFILE" <<CADDY

$MARK_BEGIN
$HOST {
	encode gzip
	reverse_proxy 127.0.0.1:$PORT
}
$MARK_END
CADDY
fi
caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null
systemctl enable caddy >/dev/null 2>&1 || true
systemctl reload caddy 2>/dev/null || systemctl restart caddy

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  echo "ufw: порты 80 и 443 открыты"
fi

say "Жду сертификат (до 90 секунд)"
ok=0
for _ in $(seq 1 45); do
  if curl -fsS "https://$HOST/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done

echo
if [ "$ok" -eq 1 ]; then
  echo "ГОТОВО. Адрес для друга:  https://$HOST"
else
  echo "Сервис работает локально, но https://$HOST пока не отвечает."
  echo "Частые причины: порты 80/443 закрыты в панели хостера (файрвол провайдера) или сертификат ещё выпускается."
  echo "Логи Caddy: journalctl -u caddy -n 50 --no-pager"
fi
echo
echo "Коды входа появляются в журнале (друг вводит почту -> вы пересылаете ему код):"
echo "  journalctl -u $SERVICE -f | grep --line-buffered 'sign-in code'"
echo "Убрать тестовую копию полностью:  bash $0 remove"
