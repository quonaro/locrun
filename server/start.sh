#!/bin/bash
set -e

# Очищаем и записываем все переменные окружения, которые есть у Docker
# Исключаем служебные переменные, чтобы не было конфликтов
printenv > /etc/environment

# ВАЖНО: Даем права на чтение, иначе юзер tun не сможет их подтянуть
chmod 644 /etc/environment

# 1. Валидация окружения
if [ -z "$BASE_DOMAIN" ]; then
    echo "❌ FATAL: BASE_DOMAIN environment variable is required."
    exit 1
fi

# 2. Подготовка SSH-ключей хоста
# Если ключи не смонтированы через Volume, генерируем их при старте
if [ ! -f "/etc/ssh/ssh_host_rsa_key" ]; then
    echo "🔑 Generating SSH host keys..."
    ssh-keygen -A
fi

# 3. Запуск Caddy в фоне
echo "🚀 Starting Caddy (API on localhost:2019)..."
caddy start --config /etc/caddy/Caddyfile --adapter caddyfile

# 4. Запуск SSH-сервера
# Запускаем в фоне, чтобы скрипт мог идти дальше
echo "🔌 Starting SSHD on port ${SSH_PORT:-22}..."
/usr/sbin/sshd

echo "----------------------------------------------------"
echo "✅ LocRun Gateway is UP and Running!"
echo "📍 Base Domain: $BASE_DOMAIN"
echo "----------------------------------------------------"

# 5. Удержание контейнера (Keep-alive)
# Вместо запуска handler.py здесь, мы просто заставляем скрипт ждать.
# Это не ест ресурсы и не дает Docker завершить работу контейнера.
exec tail -f /dev/null