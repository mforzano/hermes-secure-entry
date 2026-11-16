"""Loopback-only HTTP. Tailscale Serve owns HTTPS; never bind a LAN/public address."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
from urllib.parse import parse_qs, urlsplit

MAX_BODY = 16384


class Server:
    def __init__(self, broker, host='127.0.0.1', port=8769):
        if host != '127.0.0.1':
            raise ValueError('only IPv4 loopback is allowed')
        self.broker, self.host, self.port = broker, host, port
        self.httpd = self.thread = None

    def __enter__(self):
        broker = self.broker
        allowed_hosts = {urlsplit(broker.base).netloc}

        class Handler(BaseHTTPRequestHandler):
            server_version = 'SecureEntry'
            sys_version = ''

            def log_message(self, *args):
                pass  # No URL, headers, body, credentials, or raw errors in logs.

            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def reply(self, status, body, content_type='text/html; charset=utf-8'):
                blob = body.encode('utf-8') if isinstance(body, str) else body
                self.send_response(status)
                for name, value in {
                    'Content-Type': content_type, 'Content-Length': str(len(blob)),
                    'Cache-Control': 'no-store', 'Pragma': 'no-cache',
                    'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
                    'X-Frame-Options': 'DENY', 'Connection': 'close',
                    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
                    'Content-Security-Policy': "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
                }.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(blob)
                self.close_connection = True

            def route(self):
                host = self.headers.get('Host', '')
                local_hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
                if host not in allowed_hosts | local_hosts:
                    self.reply(421, 'Unrecognized host')
                    return None
                if self.path == '/health':
                    self.reply(200, b'{"status":"ok","version":"0.3.0"}', 'application/json')
                    return None
                match = re.fullmatch(r'/r/([A-Za-z0-9_-]{43})', self.path)
                if not match:
                    self.reply(404, 'Unavailable')
                    return None
                return match.group(1)

            def do_GET(self):
                token = self.route()
                if token is not None:
                    self.reply(200, broker.page(token))

            def do_POST(self):
                token = self.route()
                if token is None:
                    return
                length = self.headers.get('Content-Length', '')
                if (not length.isdecimal() or not 0 < int(length) <= MAX_BODY
                        or self.headers.get('Transfer-Encoding')
                        or self.headers.get_content_type() != 'application/x-www-form-urlencoded'):
                    self.reply(400, 'Invalid request')
                    return
                try:
                    parsed = parse_qs(self.rfile.read(int(length)).decode('utf-8'),
                                      keep_blank_values=True, max_num_fields=9, errors='strict')
                    if any(len(values) != 1 for values in parsed.values()):
                        raise ValueError('duplicate fields')
                    fields = {name: values[0] for name, values in parsed.items()}
                    result = broker.submit(token, fields)
                    fields.clear()
                    parsed.clear()
                except Exception:
                    self.reply(400, 'Invalid request')
                    return
                if result['status'] in ('csrf_rejected', 'invalid_input'):
                    self.reply(403, 'Entry refused. Refresh the original page and try again.')
                else:
                    # POST/redirect/GET prevents mobile refresh from resubmitting a code.
                    self.send_response(303)
                    self.send_header('Location', '/r/' + token)
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Referrer-Policy', 'no-referrer')
                    self.send_header('Content-Length', '0')
                    self.end_headers()

        class QuietHTTPServer(ThreadingHTTPServer):
            daemon_threads = True
            def handle_error(self, request, client_address):
                pass

        self.httpd = QuietHTTPServer((self.host, self.port), Handler)
        self.port = self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, name='secure-entry-http', daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.broker.close()
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join(timeout=5)
            self.httpd = None

    def __exit__(self, *args):
        self.close()
