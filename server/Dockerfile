FROM caddy:2.8-alpine AS caddy-builder

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

COPY handler.py .
COPY sshd_config /etc/ssh/sshd_config
COPY Caddyfile /etc/caddy/Caddyfile

RUN chmod +x handler.py && \
    adduser -D -s /bin/bash tun && \
    passwd -d tun && \
    mkdir -p /home/tun/.ssh && \
    chown -R tun:tun /home/tun /app && \
    ssh-keygen -A

RUN mkdir -p /var/log/caddy /run/sshd && \
    chmod 0755 /run/sshd

RUN printf '#!/bin/sh\n\
    echo "🚀 Starting LocRun Server (No Password Mode)..."\n\
    /usr/sbin/sshd\n\
    caddy start --config /etc/caddy/Caddyfile > /var/log/caddy/caddy.log 2>&1\n\
    echo "⚡ Services are running."\n\
    exec python3 /app/handler.py\n\
    ' > /app/start.sh && chmod +x /app/start.sh

EXPOSE 80 443 2019 22

CMD ["/app/start.sh"]