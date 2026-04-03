FROM caddy:2.8-alpine AS caddy-builder

# Install Python and required packages
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
    && rm -rf /var/cache/apk/*

# Create appuser with random password
RUN adduser -D -s /bin/bash appuser && \
    PASSWORD=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 16) && \
    echo "appuser:$(echo $PASSWORD | openssl passwd -stdin -1)" | chpasswd -e && \
    echo "Generated password for appuser: $PASSWORD" && \
    echo "$PASSWORD" > /tmp/appuser_password && \
    mkdir -p /home/appuser/.ssh && \
    chown -R appuser:appuser /home/appuser && \
    ssh-keygen -A

# Set working directory
WORKDIR /app

# Copy application files
COPY handler.py .
COPY sshd_config /etc/ssh/sshd_config

# Copy Caddy configuration
COPY Caddyfile /etc/caddy/Caddyfile

# Create log directory
RUN mkdir -p /var/log/caddy

# Expose ports
EXPOSE 80 443 2019 8080 22

# Create startup script
RUN echo '#!/bin/sh' > /app/start.sh && \
    echo 'echo ""' >> /app/start.sh && \
    echo 'echo "🚀 Starting LocRun Server..."' >> /app/start.sh && \
    echo 'echo ""' >> /app/start.sh && \
    echo 'echo "📡 Server Information:"' >> /app/start.sh && \
    echo 'echo "   Domain: *.$BASE_DOMAIN"' >> /app/start.sh && \
    echo 'echo "   HTTPS Port: ${HTTPS_PORT:-443}"' >> /app/start.sh && \
    echo 'echo "   SSH Port: ${SSH_PORT:-22}"' >> /app/start.sh && \
    echo 'IP=$(curl -s ifconfig.me || echo "unknown")' >> /app/start.sh && \
    echo 'INTERNAL_IP=$(hostname -i | awk "{print \$1}")' >> /app/start.sh && \
    echo 'echo "   External IP: $IP"' >> /app/start.sh && \
    echo 'echo "   Internal IP: $INTERNAL_IP"' >> /app/start.sh && \
    echo 'PASSWORD=$(cat /tmp/appuser_password)' >> /app/start.sh && \
    echo 'echo "   SSH User: appuser"' >> /app/start.sh && \
    echo 'echo "   SSH Password: $PASSWORD"' >> /app/start.sh && \
    echo 'echo ""' >> /app/start.sh && \
    echo 'echo "🔗 How to connect:"' >> /app/start.sh && \
    echo 'echo "   ssh -R 0:localhost:YOUR_PORT -p 22 appuser@example.com"' >> /app/start.sh && \
    echo 'echo ""' >> /app/start.sh && \
    echo 'echo "📝 Replace YOUR_PORT with your local service port"' >> /app/start.sh && \
    echo 'echo ""' >> /app/start.sh && \
    echo 'echo "⚡ Starting services..."' >> /app/start.sh && \
    echo '/usr/sbin/sshd &' >> /app/start.sh && \
    echo 'caddy run --config /etc/caddy/Caddyfile --log-level ERROR > /dev/null 2>&1 &' >> /app/start.sh && \
    echo 'python3 /app/handler.py' >> /app/start.sh && \
    chmod +x /app/start.sh

# Use the startup script as the command
CMD ["/app/start.sh"]