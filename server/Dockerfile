FROM caddy:2.8-alpine AS caddy-builder

# Установка необходимых пакетов
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-requests \
    openssh-client \
    openssh-server \
    iproute2 \
    curl \
    shadow \
    openssl \
    bash \
    && rm -rf /var/cache/apk/*

WORKDIR /app

# Копируем конфиги и скрипт
COPY handler.py .
COPY sshd_config /etc/ssh/sshd_config
COPY Caddyfile /etc/caddy/Caddyfile

# Настройка пользователя 'tun' БЕЗ пароля
RUN adduser -D -s /bin/bash tun && \
    passwd -d tun && \
    mkdir -p /home/tun/.ssh && \
    chown -R tun:tun /home/tun && \
    ssh-keygen -A

# Подготовка директорий
RUN mkdir -p /var/log/caddy /run/sshd && \
    chmod 0755 /run/sshd

# Скрипт запуска
RUN printf '#!/bin/sh\n\
echo "🚀 Starting LocRun Server (No Password Mode)..."\n\
echo "📡 Domain: *.$BASE_DOMAIN"\n\
echo "🔑 SSH User: tun"\n\
echo "🔓 Authentication: NONE (Empty Password Allowed)"\n\
echo "----------------------------------------"\n\
\n\
# Запуск SSH\n\
/usr/sbin/sshd\n\
\n\
# Запуск Caddy (логи в файл, чтобы не спамить в stdout)\n\
caddy start --config /etc/caddy/Caddyfile > /var/log/caddy/caddy.log 2>&1\n\
\n\
echo "⚡ Services are running. Ready for tunnels."\n\
exec python3 /app/handler.py\n\
' > /app/start.sh && chmod +x /app/start.sh

EXPOSE 80 443 2019 22

CMD ["/app/start.sh"]