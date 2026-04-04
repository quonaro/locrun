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
def get_ssh_tunnel_port():
    """
    Находит порт туннеля, выделенный текущей SSH-сессией.
    Использует SSH_CONNECTION для определения PID sshd процесса,
    затем ищет порты, привязанные к этому PID через ss.
    """
    # Пробуем SSH_CONNECTION, затем SSH_CLIENT
    ssh_conn = os.getenv("SSH_CONNECTION") or os.getenv("SSH_CLIENT")
    if not ssh_conn:
        print(
            "⚠️ SSH_CONNECTION/SSH_CLIENT not set, falling back to legacy method",
            file=sys.stderr,
        )
        return get_my_tunnel_port_legacy()

    # SSH_CONNECTION: client_ip client_port server_ip server_port
    # SSH_CLIENT: client_ip client_port server_port (без server_ip)
    parts = ssh_conn.split()
    if len(parts) < 3:
        print(f"⚠️ Unexpected SSH_CONNECTION format: {ssh_conn}", file=sys.stderr)
        return get_my_tunnel_port_legacy()

    client_ip, client_port = parts[0], parts[1]

    for i in range(30):
        time.sleep(0.5)
        try:
            # Находим PID sshd процесса по client_ip:client_port
            output = subprocess.check_output(
                ["ss", "-ntp"], stderr=subprocess.DEVNULL
            ).decode()

            sshd_pids = set()
            for line in output.splitlines():
                if "ESTAB" not in line or "sshd" not in line:
                    continue
                if f"{client_ip}:{client_port}" in line:
                    # Пробуем разные форматы вывода ss
                    # Alpine/busybox ss: users:(sshd,pid,fd) или users:(("sshd",pid,fd))
                    pid = None
                    if 'users:(("sshd",' in line:
                        pid_part = line.split('users:(("sshd",')[1].split(",")[0]
                        if pid_part.isdigit():
                            pid = pid_part
                    elif "users:((sshd," in line:
                        pid_part = line.split("users:((sshd,")[1].split(",")[0]
                        if pid_part.isdigit():
                            pid = pid_part
                    elif "users:(sshd," in line:
                        pid_part = line.split("users:(sshd,")[1].split(",")[0]
                        if pid_part.isdigit():
                            pid = pid_part

                    if pid:
                        sshd_pids.add(pid)

            if not sshd_pids:
                if i % 5 == 0:
                    print(
                        f"⏳ Waiting for sshd connection... (attempt {i + 1})",
                        file=sys.stderr,
                    )
                continue

            print(f"🔍 Found sshd PIDs: {sshd_pids}", file=sys.stderr)

            # Теперь ищем LISTEN порты, привязанные к найденным PID
            output = subprocess.check_output(
                ["ss", "-ntlp"], stderr=subprocess.DEVNULL
            ).decode()

            tunnel_ports = []
            for line in output.splitlines():
                if "LISTEN" not in line:
                    continue
                # Проверяем, принадлежит ли порт одному из наших sshd PID
                for pid in sshd_pids:
                    # Пробуем разные форматы
                    if (
                        f'users:(("sshd",{pid},' in line
                        or f"users:((sshd,{pid}," in line
                        or f"users:(sshd,{pid}," in line
                        or f"pid={pid}" in line
                    ):
                        parts_ss = line.split()
                        local_addr = parts_ss[3]  # например 0.0.0.0:40475
                        if ":" not in local_addr:
                            continue
                        addr, port_str = local_addr.rsplit(":", 1)
                        port_str = port_str.strip("]")
                        if port_str.isdigit():
                            port = int(port_str)
                            # Исключаем известные порты
                            if port not in [22, 80, 443, 2019, 8080, 41907]:
                                tunnel_ports.append(port)

            if tunnel_ports:
                chosen = tunnel_ports[0]
                print(f"✅ Found tunnel port via PID: {chosen}", file=sys.stderr)
                return str(chosen)

        except Exception as e:
            if i % 5 == 0:
                print(f"⚠️ Error checking ports: {e}", file=sys.stderr)

    print("❌ Port not found after 30 attempts via PID method", file=sys.stderr)
    return get_my_tunnel_port_legacy()


def get_my_tunnel_port_legacy():
    """
    Legacy метод: берем первый попавшийся эфемерный порт.
    Может быть неточным при параллельных сессиях.
    """
    for i in range(30):
        time.sleep(0.5)
        try:
            output = subprocess.check_output(
                ["ss", "-ntlp"], stderr=subprocess.DEVNULL
            ).decode()

            ports = []
            for line in output.splitlines():
                if "LISTEN" not in line:
                    continue
                parts = line.split()
                local_addr = parts[3]
                if ":" not in local_addr:
                    continue
                addr, port_str = local_addr.rsplit(":", 1)
                port_str = port_str.strip("]")
                if not port_str.isdigit():
                    continue
                port = int(port_str)
                if port in [22, 80, 443, 2019, 8080, 41907]:
                    continue
                if port > 32768:  # Только ephemeral порты
                    ports.append(port)

            if ports:
                chosen = ports[0]
                print(f"✅ Found tunnel port (legacy): {chosen}", file=sys.stderr)
                return str(chosen)

        except Exception as e:
            if i % 5 == 0:
                print(f"⚠️ Error checking ports: {e}", file=sys.stderr)

    print("❌ Port not found after 30 attempts", file=sys.stderr)
    return None


# --- Управление Caddy API ---
def manage_caddy_route(route_id, domain, port, delete=False):
    if delete:
        try:
            requests.delete(f"{CADDY_API}/id/{route_id}", timeout=2)
        except Exception:
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
    port = get_ssh_tunnel_port()
    if not port:
        print("❌ Error: Remote port forwarding not detected. Did you use -R?")
        sys.exit(1)

    # 3. Генерация данных сессии
    session_id = uuid.uuid4().hex[:8]
    current_session_domain = f"{session_id}.{BASE_DOMAIN}"
    route_id = f"tun-{session_id}"

    # 4. Регистрация в Caddy
    if manage_caddy_route(route_id, current_session_domain, port):
        print("\n" + "=" * 50)
        print("🚀 LOCRUN TUNNEL IS LIVE")
        print(f"🔗 URL: https://{current_session_domain}")
        print(f"🛠  Forwarding: localhost:{port} -> Remote")
        print("=" * 50 + "\n")
        sys.stdout.flush()
    else:
        print("❌ Failed to register route in Caddy. Check admin API.")
        sys.exit(1)

    # 5. Обработка завершения
    def cleanup(signum, frame):
        print("\nCleaning up {}...".format(current_session_domain))
        manage_caddy_route(route_id, current_session_domain, port, delete=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Держим процесс живым, пока жива SSH-сессия
    print("🔄 Keeping connection alive... (Press Ctrl+C to disconnect)")
    sys.stdout.flush()
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
