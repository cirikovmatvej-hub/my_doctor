#!/bin/bash
# Использование: bash deploy.sh ВАШ_IP
# Например:      bash deploy.sh 185.100.200.10

SERVER_IP=${1:?"Укажи IP сервера: bash deploy.sh 185.100.200.10"}
SERVER_DIR="/opt/my_doctor_bot"

echo "📦 Отправляю файлы на сервер $SERVER_IP..."
rsync -avz --progress \
  --exclude='.env' \
  --exclude='*.db' \
  --exclude='__pycache__' \
  --exclude='.git' \
  --exclude='venv' \
  /Users/matvey/my_doctor_bot/ root@$SERVER_IP:$SERVER_DIR/

echo "🔄 Перезапускаю бота..."
ssh root@$SERVER_IP "systemctl restart mydoctor && systemctl status mydoctor --no-pager"

echo "✅ Готово!"
