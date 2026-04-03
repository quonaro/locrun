#!/bin/bash
set -e

# 1. Валидация
if [ -z "$BASE_DOMAIN" ]; then
    echo "❌ ERROR: BASE_DOMAIN is not set in environment!"
    exit 1
fi

# 2. Генерация ключей хоста, если их нет (сохраняются в volume)
if [ ! -f "/etc/ssh/keys/ssh_host_rsa_key" ]; then
    echo "🔑 Generating new SSH host keys..."
    ssh-keygen -A
    mv /etc/ssh/ssh_host_* /etc/ssh/keys/
fi
# Симлинки, чтобы sshd их нашел
ln -sf /etc/ssh/keys/ssh_host_* /etc/ssh/

# 3. FIX: Проброс переменных окружения в SSH
# Без этого handler.py внутри SSH-сессии не увидит BASE_DOMAIN
printenv | grep -E "BASE_DOMAIN|PORT|DEBUG" > /etc/environment

echo "🚀 Starting Caddy..."
caddy start --config /etc/caddy/Caddyfile

echo "🔌 Starting SSHD..."
/usr/sbin/sshd
