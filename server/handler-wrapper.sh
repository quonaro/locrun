#!/bin/bash
# Обёртка для handler.py — подгружает переменные окружения из /etc/environment
# и запускает основной обработчик

set -e

# Логируем запуск
exec 2>&1
set -x

echo "=== Handler wrapper starting at $(date) ===" >&2
echo "Args: $*" >&2

# Загружаем переменные из /etc/environment
if [ -f /etc/environment ]; then
    echo "Loading environment from /etc/environment..." >&2
    while IFS= read -r line || [ -n "$line" ]; do
        # Пропускаем пустые строки и комментарии
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        export "$line" 2>/dev/null || true
    done < /etc/environment
    echo "BASE_DOMAIN=${BASE_DOMAIN:-NOT_SET}" >&2
else
    echo "WARNING: /etc/environment not found!" >&2
fi

echo "=== Starting handler.py ===" >&2

# Запускаем основной обработчик с небуферизованным выводом
exec python3 -u /app/handler.py
