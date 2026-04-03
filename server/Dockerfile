FROM caddy:2.8-alpine

# Устанавливаем зависимости + tini
RUN apk add --no-cache \
    python3 \
    py3-pip \
    openssh-client \
    openssh-server \
    bash \
    tini \
    && rm -rf /var/cache/apk/*

WORKDIR /app

# Создаем пользователя и необходимые директории
RUN adduser -D -s /bin/bash tun && \
    passwd -d tun && \
    mkdir -p /home/tun/.ssh /run/sshd /etc/ssh/keys && \
    chown -R tun:tun /home/tun

# Копируем конфиги
COPY handler.py .
COPY sshd_config /etc/ssh/sshd_config
COPY Caddyfile /etc/caddy/Caddyfile
COPY start.sh /app/start.sh

RUN chmod +x /app/start.sh /app/handler.py

# Открываем порты (22 — внутренний для контейнера)
EXPOSE 80 443 22

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/app/start.sh"]