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
    Использует SSH_CONNECTION для определения PID sshd процесса,
    затем ищет порты, привязанные к этому PID через /proc/net/tcp.
    """
    # Пробуем SSH_CONNECTION, затем SSH_CLIENT
    ssh_conn = os.getenv("SSH_CONNECTION") or os.getenv("SSH_CLIENT")
    if not ssh_conn:
        print(
            "⚠️ SSH_CONNECTION/SSH_CLIENT not set, falling back to legacy method",
            file=sys.stderr,
        )
        return get_my_tunnel_port_legacy()

    print(f"🔍 SSH connection: {ssh_conn}", file=sys.stderr)

    # SSH_CONNECTION: client_ip client_port server_ip server_port
    # SSH_CLIENT: client_ip client_port server_port (без server_ip)
    parts = ssh_conn.split()
    if len(parts) < 3:
        print(f"⚠️ Unexpected SSH_CONNECTION format: {ssh_conn}", file=sys.stderr)
        return get_my_tunnel_port_legacy()

    client_ip, client_port = parts[0], parts[1]

    # Читаем /proc/net/tcp напрямую (надёжнее в контейнерах)
    for i in range(30):
        time.sleep(0.5)
        try:
            with open("/proc/net/tcp") as f:
                lines = f.readlines()

            # Формат /proc/net/tcp: sl  local_address rem_address   st ...
            # local_address в hex: 0100007F:1F90 = 127.0.0.1:8080
            sshd_pids = set()

            # Находим Established соединения к клиентскому порту
            client_port_hex = f"{int(client_port):04X}"
            for line in lines[1:]:  # Пропускаем заголовок
                parts_line = line.split()
                if len(parts_line) < 4:
                    continue
                local_addr = parts_line[1]
                rem_addr = parts_line[2]
                state = parts_line[3]

                # state 01 = ESTABLISHED
                if state != "01":
                    continue

                # Проверяем, соответствует ли rem_addr клиентскому IP:port
                # IP конвертируем в hex (обратный порядок)
                ip_parts = client_ip.split(".")
                ip_hex = f"{int(ip_parts[3]):02X}{int(ip_parts[2]):02X}{int(ip_parts[1]):02X}{int(ip_parts[0]):02X}"
                expected_rem = f"{ip_hex}:{client_port_hex}"

                if rem_addr == expected_rem:
                    # Нашли соединение, теперь нужно найти PID
                    # В newer kernels есть inode, можно использовать его
                    if len(parts_line) > 9:
                        inode = parts_line[9]
                        # Ищем PID по inode в /proc/*/fd
                        for pid_dir in os.listdir("/proc"):
                            if pid_dir.isdigit():
                                fd_dir = f"/proc/{pid_dir}/fd"
                                if os.path.exists(fd_dir):
                                    try:
                                        for fd in os.listdir(fd_dir):
                                            fd_path = os.path.join(fd_dir, fd)
                                            if os.path.islink(fd_path):
                                                target = os.readlink(fd_path)
                                                if f"socket:[{inode}]" in target:
                                                    sshd_pids.add(pid_dir)
                                                    break
                                    except (ProcessLookupError, PermissionError):
                                        continue

            if sshd_pids:
                print(f"🔍 Found sshd PIDs via /proc: {sshd_pids}", file=sys.stderr)
            else:
                if i % 5 == 0:
                    print(
                        f"⏳ Waiting for connection... (attempt {i + 1})",
                        file=sys.stderr,
                    )
                continue

            # Теперь ищем LISTEN порты с этими PID
            listening_ports = []
            for line in lines[1:]:
                parts_line = line.split()
                if len(parts_line) < 4:
                    continue
                state = parts_line[3]

                # state 0A = LISTEN
                if state != "0A":
                    continue

                local_addr = parts_line[1]
                if len(parts_line) > 9:
                    inode = parts_line[9]

                    # Проверяем, принадлежит ли этот inode нашим sshd PID
                    for pid in sshd_pids:
                        fd_dir = f"/proc/{pid}/fd"
                        if os.path.exists(fd_dir):
                            try:
                                for fd in os.listdir(fd_dir):
                                    fd_path = os.path.join(fd_dir, fd)
                                    if os.path.islink(fd_path):
                                        target = os.readlink(fd_path)
                                        if f"socket:[{inode}]" in target:
                                            # Парсим порт из local_addr
                                            # Формат: 00000000:8E2F -> 0.0.0.0:36399
                                            if ":" in local_addr:
                                                _, port_hex = local_addr.split(":")
                                                port = int(port_hex, 16)
                                                # Исключаем известные порты
                                                if port not in [
                                                    22,
                                                    80,
                                                    443,
                                                    2019,
                                                    8080,
                                                    41907,
                                                ]:
                                                    listening_ports.append(port)
                                                    break
                            except (ProcessLookupError, PermissionError):
                                continue

            if listening_ports:
                chosen = listening_ports[0]
                print(f"✅ Found tunnel port via /proc: {chosen}", file=sys.stderr)
                return str(chosen)

        except Exception as e:
            if i % 5 == 0:
                print(f"⚠️ Error checking ports: {e}", file=sys.stderr)

    print("❌ Port not found after 30 attempts via /proc method", file=sys.stderr)
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
    # 1. Ожидание проброшенного порта
    print("⏳ Waiting for tunnel port...")
    port = get_ssh_tunnel_port()
    if not port:
        print("❌ Error: Remote port forwarding not detected. Did you use -R?")
        sys.exit(1)

    # 2. Генерация данных сессии
    session_id = uuid.uuid4().hex[:8]
    current_session_domain = f"{session_id}.{BASE_DOMAIN}"
    route_id = f"tun-{session_id}"

    # 3. Регистрация в Caddy
    if manage_caddy_route(route_id, current_session_domain, port):
        # Уведомляем SSL check сервер
        notify_ssl_check(current_session_domain, add=True)
        print("\n" + "=" * 50)
        print("🚀 LOCRUN TUNNEL IS LIVE")
        print(f"🔗 URL: https://{current_session_domain}")
        print(f"🛠  Forwarding: localhost:{port} -> Remote")
        print("=" * 50 + "\n")
        sys.stdout.flush()
    else:
        print("❌ Failed to register route in Caddy. Check admin API.")
        sys.exit(1)

    # 4. Обработка завершения
    def cleanup(signum, frame):
        print("\nCleaning up {}...".format(current_session_domain))
        manage_caddy_route(route_id, current_session_domain, port, delete=True)
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
