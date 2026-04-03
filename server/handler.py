#!/usr/bin/python3

import sys
import uuid
import time
import subprocess
import requests
import signal
import threading
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE_DOMAIN = os.getenv("BASE_DOMAIN")
if not BASE_DOMAIN:
    print("BASE_DOMAIN environment variable is required")
    sys.exit(1)
CADDY_API_BASE = os.getenv("CADDY_API_BASE", "http://localhost:2019")
CADDY_SERVER_NAME = os.getenv("CADDY_SERVER_NAME", "srv0")
CHECK_PORT = int(os.getenv("CHECK_PORT", "8080"))


class SSLCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/check?domain=") and BASE_DOMAIN in self.path:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(403)
            self.end_headers()

    def log_message(self, format, *args):
        return


def run_ssl_check_server():
    server = HTTPServer(("127.0.0.1", CHECK_PORT), SSLCheckHandler)
    server.serve_forever()


def get_ssh_allocated_port():
    for _ in range(15):
        time.sleep(0.3)
        try:
            output = subprocess.check_output(
                ["ss", "-ntl"], stderr=subprocess.DEVNULL
            ).decode()
            found_ports = []
            for line in output.splitlines():
                if "LISTEN" in line:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    local_addr = parts[3]
                    port_str = local_addr.split(":")[-1].strip("]")
                    if port_str.isdigit():
                        p = int(port_str)
                        if p >= 10000 and p != 2019:
                            found_ports.append(p)
            if found_ports:
                return str(max(found_ports))
        except (subprocess.SubprocessError, OSError, ValueError):
            pass
    return None


def manage_caddy(route_id, domain, port, delete=False):
    routes_url = f"{CADDY_API_BASE}/config/apps/http/servers/{CADDY_SERVER_NAME}/routes"

    if delete:
        try:
            requests.delete(f"{CADDY_API_BASE}/id/{route_id}", timeout=2)
        except (requests.RequestException, OSError):
            pass
        return

    payload = {
        "@id": route_id,
        "match": [{"host": [domain]}],
        "handle": [
            {
                "handler": "reverse_proxy",
                "upstreams": [{"dial": f"127.0.0.1:{port}"}],
                "transport": {"protocol": "http", "versions": ["1.1"]},
                "headers": {
                    "request": {
                        "set": {
                            "Host": ["localhost"],
                            "X-Real-IP": ["{http.request.remote.host}"],
                            "X-Forwarded-Proto": ["https"],
                            "X-Forwarded-Host": ["{http.reverse_proxy.header.Host}"],
                        }
                    }
                },
            }
        ],
        "terminal": True,
    }

    try:
        r = requests.post(f"{routes_url}/0", json=payload, timeout=2)
        return r.status_code in [200, 201, 204]
    except Exception as e:
        print(f"Caddy API Error: {e}")
        return False


def main():
    threading.Thread(target=run_ssl_check_server, daemon=True).start()

    port = get_ssh_allocated_port()
    if not port:
        print("\n[!] Error: No active tunnel port detected.")
        sys.exit(1)

    session_id = str(uuid.uuid4())[:8]
    domain = f"{session_id}.{BASE_DOMAIN}"
    route_id = f"tun-{session_id}"

    print(f"\n{'=' * 50}")
    print(" ^=^z^` LOCRUN TUNNEL ACTIVE")
    print(f" ^=^t^w URL:  https://{domain}")
    print(f" ^=^t^l Mapping: localhost:{port}")
    print(f"{'=' * 50}\n")

    if manage_caddy(route_id, domain, port):
        print(" ^|^e Caddy route created & SSL check active.")
    else:
        print(" ^z   ^o Warning: Could not update Caddy. Check CADDY_SERVER_NAME.")

    def shutdown(signum, frame):
        print(f"\n\n ^=   Cleaning up {domain}...")
        manage_caddy(route_id, domain, port, delete=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            time.sleep(1)
    except (EOFError, KeyboardInterrupt):
        shutdown(None, None)


if __name__ == "__main__":
    main()
