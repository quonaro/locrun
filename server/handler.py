#!/usr/bin/env python3
import os
import sys
import uuid
import time
import subprocess
import requests
import signal

# --- Конфигурация из окружения ---
BASE_DOMAIN = os.getenv("BASE_DOMAIN")
CADDY_API = os.getenv("CADDY_API_BASE", "http://127.0.0.1:2019")
CHECK_PORT = int(os.getenv("CHECK_PORT", "8080"))

if not BASE_DOMAIN:
    print("❌ FATAL: BASE_DOMAIN environment variable is required")
    sys.exit(1)


# --- Управление SSL check сервером ---
def notify_ssl_check(domain, add=True):
    """Уведомить глобальный SSL check сервер о добавлении/удалении домена"""
    try:
        endpoint = (
            f"http://127.0.0.1:{CHECK_PORT}/add"
            if add
            else f"http://127.0.0.1:{CHECK_PORT}/remove"
        )
        requests.post(endpoint, json={"domain": domain}, timeout=2)
        return True
    except Exception as e:
        print(f"⚠️ Failed to notify SSL check server: {e}")
        return False


# --- Логика определения порта ---
def get_ssh_tunnel_port():
    """
    Находит порт туннеля, выделенный текущей SSH-сессией.
    Сначала проверяет переменную окружения TUNNEL_PORT, затем ищет через ss.
    Возвращает кортеж (ip, port) для точного upstream адреса.
    """
    # Сначала проверяем переменную окружения (если клиент передал её)
    tunnel_port = os.getenv("TUNNEL_PORT")
    if tunnel_port and tunnel_port.isdigit():
        print(f"✅ Using tunnel port from env: {tunnel_port}", file=sys.stderr)
        return "127.0.0.11", tunnel_port  # SSH remote forward обычно на 127.0.0.11

    # Fallback: ищем через ss
    for _ in range(15):
        time.sleep(0.3)
        try:
            output = subprocess.check_output(
                ["ss", "-ntl"], stderr=subprocess.DEVNULL
            ).decode()
            candidates = []
            for line in output.splitlines():
                if "LISTEN" in line:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    local_addr = parts[3]
                    if ":" not in local_addr:
                        continue
                    ip, port_str = local_addr.rsplit(":", 1)
                    port_str = port_str.strip("]")
                    if port_str.isdigit():
                        p = int(port_str)
                        if p >= 10000 and p not in [2019, 8080, 22]:
                            candidates.append((ip, p))
            if candidates:
                # Берём порт с максимальным номером
                chosen = max(candidates, key=lambda x: x[1])
                ip, port = chosen
                print(f"✅ Found tunnel port: {port} on {ip}", file=sys.stderr)
                return ip, str(port)
        except Exception as e:
            print(f"⚠️ Error checking ports: {e}", file=sys.stderr)
            continue

    print("❌ Port not found after 15 attempts", file=sys.stderr)
    return None


# --- Управление Caddy API ---
def manage_caddy_route(route_id, domain, tunnel_ip, port, delete=False):
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
                "upstreams": [{"dial": f"{tunnel_ip}:{port}"}],
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

    # HTTP payload (без TLS заголовков)
    payload_http = {
        "@id": route_id,
        "match": [{"host": [domain]}],
        "handle": [
            {
                "handler": "reverse_proxy",
                "upstreams": [{"dial": f"{tunnel_ip}:{port}"}],
                "headers": {
                    "request": {
                        "set": {
                            "X-Real-IP": ["{http.request.remote.host}"],
                            "X-Forwarded-Proto": ["http"],
                        }
                    }
                },
            }
        ],
        "terminal": True,
    }

    try:
        # Создаём роуты для обоих серверов (srv0 = HTTPS, srv1 = HTTP)
        for server, payload in [("srv0", payload), ("srv1", payload_http)]:
            r = requests.post(
                f"{CADDY_API}/config/apps/http/servers/{server}/routes/0",
                json=payload,
                timeout=2,
            )
            if r.status_code not in [200, 201, 204]:
                print(
                    f"⚠️ Failed to add route to {server}: {r.status_code}",
                    file=sys.stderr,
                )
        return True
    except Exception as e:
        print(f"❌ Caddy API Error: {e}", file=sys.stderr)
        return False


# --- Основной цикл ---
def main():
    # 1. Ожидание проброшенного порта
    print("⏳ Waiting for tunnel port...")
    result = get_ssh_tunnel_port()
    if not result:
        print("❌ Error: Remote port forwarding not detected. Did you use -R?")
        sys.exit(1)
    tunnel_ip, port = result
    session_id = uuid.uuid4().hex[:8]
    current_session_domain = f"{session_id}.{BASE_DOMAIN}"
    route_id = f"tun-{session_id}"

    # 2. Регистрация в Caddy
    if manage_caddy_route(route_id, current_session_domain, tunnel_ip, port):
        # Уведомляем SSL check сервер
        notify_ssl_check(current_session_domain, add=True)
        print("\n" + "=" * 50)
        print("🚀 LOCRUN TUNNEL IS LIVE")
        print(f"🔗 URL: https://{current_session_domain}")
        print(f"🛠  Forwarding: {tunnel_ip}:{port} -> Remote")
        print("=" * 50 + "\n")
        sys.stdout.flush()
    else:
        print("❌ Failed to register route in Caddy. Check admin API.")
        sys.exit(1)

    # 3. Обработка завершения
    def cleanup(signum, frame):
        print("\nCleaning up {}...".format(current_session_domain))
        manage_caddy_route(
            route_id, current_session_domain, tunnel_ip, port, delete=True
        )
        notify_ssl_check(current_session_domain, add=False)
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
