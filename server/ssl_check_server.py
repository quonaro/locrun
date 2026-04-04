#!/usr/bin/env python3
import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DOMAIN = os.getenv("BASE_DOMAIN")

if not BASE_DOMAIN:
    print("❌ FATAL: BASE_DOMAIN environment variable is required")
    exit(1)

# Set of allowed domains (populated by handlers)
allowed_domains = set()


class SSLCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Caddy шлет запрос: /check?domain=uuid.example.com
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/check":
            query = parse_qs(parsed_path.query)
            domain = query.get("domain", [None])[0]

            # Разрешаем SSL только если домен в списке разрешённых
            if domain and domain in allowed_domains:
                self.send_response(200)
                self.end_headers()
                return

        self.send_response(403)
        self.end_headers()

    def do_POST(self):
        # Handler.py шлёт команды: /add или /remove
        parsed_path = urlparse(self.path)
        if parsed_path.path in ["/add", "/remove"]:
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                data = json.loads(body) if body else {}
                domain = data.get("domain")

                if domain:
                    if parsed_path.path == "/add":
                        allowed_domains.add(domain)
                        print(f"✅ Added domain: {domain}")
                    else:
                        allowed_domains.discard(domain)
                        print(f"🗑️  Removed domain: {domain}")

                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok"}).encode())
                    return
            except Exception as e:
                print(f"❌ Error: {e}")

        self.send_response(400)
        self.end_headers()

    def log_message(self, format, *args):
        return  # Отключаем мусор в консоли


def main():
    server = HTTPServer(("127.0.0.1", 8080), SSLCheckHandler)
    print("🔒 SSL check server listening on 127.0.0.1:8080")
    server.serve_forever()


if __name__ == "__main__":
    main()
