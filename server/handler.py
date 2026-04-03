#!/usr/bin/env python3
import os
import sys
import uuid
import time
import subprocess
import requests
import signal
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

# --- Конфигурация из окружения ---
BASE_DOMAIN = os.getenv("BASE_DOMAIN")
CADDY_API = os.getenv("CADDY_API_BASE", "http://127.0.0.1:2019")
CHECK_PORT = int(os.getenv("CHECK_PORT", "8080"))

if not BASE_DOMAIN:
    print("❌ FATAL: BASE_DOMAIN environment variable is required")
    sys.exit(1)

# Глобальная переменная для текущего активного домена сессии
# (Нужна для проверки в SSLCheckHandler)
current_session_domain = None


# --- Сервер проверки для On-Demand TLS ---
class SSLCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Caddy шлет запрос: /check?domain=uuid.example.com
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/check":
            query = parse_qs(parsed_path.query)
            domain = query.get("domain", [None])[0]

            # Разрешаем SSL только если домен совпадает с текущим в этой сессии
            if domain and domain == current_session_domain:
                self.send_response(200)
                self.end_headers()
                return

        self.send_response(403)
        self.end_headers()

    def log_message(self, format, *args):
        return  # Отключаем мусор в консоли


def run_ssl_check_server():
    server = HTTPServer(("127.0.0.1", CHECK_PORT), SSLCheckHandler)
    server.serve_forever()


# --- Логика определения порта ---
def get_my_tunnel_port():
    """
    Ищет TCP порт, который слушает родительский процесс (sshd)
    для Remote Forwarding этой конкретной сессии.
    """
    ppid = os.getppid()
    for _ in range(20):  # Ждем до 6 секунд (SSH открывает порт не мгновенно)
        time.sleep(0.3)
        try:
            # Ищем сокеты, открытые процессом ppid (наш sshd)
            # Флаг -ntlp покажет процессы
            output = subprocess.check_output(
                ["ss", "-ntlp"], stderr=subprocess.DEVNULL
            ).decode()
            for line in output.splitlines():
                if f"pid={ppid}" in line:
                    parts = line.split()
                    # Локальный адрес обычно 127.0.0.1:PORT или [::1]:PORT
                    port = parts[3].split(":")[-1].strip("]")
                    if port.isdigit():
                        return port
        except Exception:
            pass
    return None


# --- Управление Caddy API ---
def manage_caddy_route(route_id, domain, port, delete=False):
    if delete:
        try:
            requests.delete(f"{CADDY_API}/id/{route_id}", timeout=2)
        except:
            pass
        return True

    # Конфигурация роута через @id для легкого удаления
    payload = {
        "@id": route_id,
        "match": [{"host": [domain]}],
        "handle": [
            {
                "handler": "reverse_proxy",
                "upstreams": [{"dial": f"127.0.0.1:{port}"}],
                "headers": {
                    "request": {
                        "set": {
                            "X-Real-IP": ["{http.request.remote.host}"],
                            "X-Forwarded-Proto": ["https"],
                        }
                    }
                },
            }
        ],
        "terminal": True,
    }

    try:
        # Вставляем роут в начало списка сервера 'srv0'
        # Убедись, что в Caddyfile нет конфликтующих имен серверов
        r = requests.post(
            f"{CADDY_API}/config/apps/http/servers/srv0/routes/0",
            json=payload,
            timeout=2,
        )
        return r.status_code in [200, 201, 204]
    except Exception as e:
        print(f"❌ Caddy API Error: {e}")
        return False


# --- Основной цикл ---
def main():
    global current_session_domain

    # 1. Запуск сервера проверок в фоне
    threading.Thread(target=run_ssl_check_server, daemon=True).start()

    # 2. Ожидание проброшенного порта
    print("⏳ Waiting for tunnel port...")
    port = get_my_tunnel_port()
    if not port:
        print("❌ Error: Remote port forwarding not detected. Did you use -R?")
        sys.exit(1)

    # 3. Генерация данных сессии
    session_id = uuid.uuid4().hex[:8]
    current_session_domain = f"{session_id}.{BASE_DOMAIN}"
    route_id = f"tun-{session_id}"

    # 4. Регистрация в Caddy
    if manage_caddy_route(route_id, current_session_domain, port):
        print(f"\n{'=' * 50}")
        print(f"🚀 LOCRUN TUNNEL IS LIVE")
        print(f"🔗 URL: https://{current_session_domain}")
        print(f"🛠  Forwarding: localhost:{port} -> Remote")
        print(f"{'=' * 50}\n")
    else:
        print("❌ Failed to register route in Caddy. Check admin API.")
        sys.exit(1)

    # 5. Обработка завершения
    def cleanup(signum, frame):
        print(f"\nCleaning up {current_session_domain}...")
        manage_caddy_route(route_id, current_session_domain, port, delete=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Держим процесс живым, пока жива SSH-сессия
    try:
        while True:
            # Проверка: если родитель (sshd) умер — выходим
            if os.getppid() == 1:
                cleanup(None, None)
            time.sleep(2)
    except EOFError:
        cleanup(None, None)


if __name__ == "__main__":
    main()
