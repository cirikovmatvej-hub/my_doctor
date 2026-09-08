#!/bin/bash
# Использование: bash deploy.sh ВАШ_IP
# Например:      bash deploy.sh 185.100.200.10
# Пользователь для SSH/rsync по умолчанию — root (как и было), но можно
# переопределить: DEPLOY_USER=deploy bash deploy.sh 185.100.200.10

SERVER_IP=${1:?"Укажи IP сервера: bash deploy.sh 185.100.200.10"}
SERVER_DIR="/opt/my_doctor_bot"
DEPLOY_USER="${DEPLOY_USER:-root}"

# Директория, где лежит сам deploy.sh — а не путь конкретной машины
# разработчика (раньше был захардкожен /Users/matvey/my_doctor_bot/, что
# рассинхронизировалось с любым другим клоном репозитория).
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "📦 Отправляю файлы на сервер $SERVER_IP..."
rsync -avz --progress \
  --exclude='.env' \
  --exclude='*.db' \
  --exclude='__pycache__' \
  --exclude='.git' \
  --exclude='venv' \
  "$LOCAL_DIR"/ "$DEPLOY_USER@$SERVER_IP:$SERVER_DIR/"

echo "🔄 Перезапускаю бота..."
ssh "$DEPLOY_USER@$SERVER_IP" "systemctl restart mydoctor && systemctl status mydoctor --no-pager"

echo "✅ Готово!"
