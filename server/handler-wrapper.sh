#!/bin/bash
# Обёртка для handler.py — подгружает переменные окружения из /etc/environment
# и запускает основной обработчик

set -e

# Загружаем переменные из /etc/environment
if [ -f /etc/environment ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # Пропускаем пустые строки и комментарии
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        export "$line" 2>/dev/null || true
    done < /etc/environment
fi

# Запускаем основной обработчик
exec /app/handler.py
