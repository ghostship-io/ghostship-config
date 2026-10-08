#!/usr/bin/env python3
"""Authenticated automation proxy for the Ghostship agent desktop.

Exposes a narrow, token-protected surface on the private agent desktop
network:

  /pelorus/api/...   whitelisted Pelorus desktop-control endpoints
  /playwright/<p>    raw TCP passthrough to a bound Playwright browser server
  /healthz           unauthenticated health probe

Pelorus agent/LLM endpoints and Pixelflux's raw service on port 5000 are
never proxied.
"""

import http.client
import json
import os
import re
import select
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

TOKEN = os.environ.get("AGENT_DESKTOP_API_TOKEN", "")
BIND = os.environ.get("AGENT_DESKTOP_API_BIND", "10.89.7.2")
PORT = int(os.environ.get("AGENT_DESKTOP_API_PORT", "7080"))
PELORUS_HOST = "127.0.0.1"
PELORUS_PORT = int(os.environ.get("AGENT_DESKTOP_PELORUS_PORT", "5100"))
MANAGER_PORT = int(os.environ.get("AGENT_DESKTOP_MANAGER_PORT", "7999"))
BROWSER_ROUTES = re.compile(r"^/browsers(?:/[A-Za-z0-9_-]+(?:/close-tabs)?)?$")
BROWSER_DIR = os.environ.get("AGENT_DESKTOP_BROWSER_DIR", "/config/agent-desktop/browsers")

GET_ALLOWED = [
    re.compile(r"^/api/state$"),
    re.compile(r"^/api/windows$"),
    re.compile(r"^/api/desktop/screenshot$"),
    re.compile(r"^/api/desktop/screenshot/\d+$"),
    re.compile(r"^/api/desktop/explore/\d+$"),
]
POST_ALLOWED = [
    re.compile(r"^/api/desktop/control$"),
    re.compile(r"^/api/desktop/close/\d+$"),
]
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def log(message):
    print(f"[agent-desktop-api] {message}", file=sys.stderr, flush=True)


def authorized(handler, allow_query_token=False):
    if not TOKEN:
        return False
    candidates = []
    header = handler.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        candidates.append(header[len("Bearer ") :])
    header = handler.headers.get("X-Api-Token")
    if header:
        candidates.append(header)
    if allow_query_token:
        query = dict(parse_qsl(urlsplit(handler.path).query))
        if "token" in query:
            candidates.append(query["token"])
    return any(
        len(candidate) == len(TOKEN) and all(a == b for a, b in zip(candidate, TOKEN))
        for candidate in candidates
    )


def read_browser_endpoint(profile):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
        return None
    path = os.path.join(BROWSER_DIR, f"{profile}.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    parsed = urlsplit(data.get("endpoint", ""))
    if parsed.scheme != "ws" or not parsed.hostname or not parsed.port:
        return None
    return parsed


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ghostship-agent-desktop-api"

    def log_message(self, fmt, *args):
        log(fmt % args)

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/healthz":
            self.send_json(200, {"status": "ok"})
            return
        if path.startswith("/playwright/"):
            self.handle_playwright(path[len("/playwright/") :])
            return
        if BROWSER_ROUTES.match(path):
            if not authorized(self):
                self.send_error(401)
                return
            self.forward("GET", PELORUS_HOST, MANAGER_PORT, path)
            return
        upstream = self.pelorus_path(path)
        if upstream is None or not any(p.match(upstream) for p in GET_ALLOWED):
            self.send_error(404)
            return
        if not authorized(self):
            self.send_error(401)
            return
        self.forward("GET", PELORUS_HOST, PELORUS_PORT, upstream)

    def do_POST(self):
        path = urlsplit(self.path).path
        if BROWSER_ROUTES.match(path):
            if not authorized(self):
                self.send_error(401)
                return
            length = self.headers.get("Content-Length") or "0"
            try:
                body = self.rfile.read(int(length))
            except (ValueError, OSError):
                self.send_error(400)
                return
            self.forward("POST", PELORUS_HOST, MANAGER_PORT, path, body)
            return
        upstream = self.pelorus_path(path)
        if upstream is None or not any(p.match(upstream) for p in POST_ALLOWED):
            self.send_error(404)
            return
        if not authorized(self):
            self.send_error(401)
            return
        length = self.headers.get("Content-Length") or "0"
        try:
            body = self.rfile.read(int(length))
        except (ValueError, OSError):
            self.send_error(400)
            return
        self.forward("POST", PELORUS_HOST, PELORUS_PORT, upstream, body)

    def do_DELETE(self):
        path = urlsplit(self.path).path
        if not BROWSER_ROUTES.match(path):
            self.send_error(404)
            return
        if not authorized(self):
            self.send_error(401)
            return
        self.forward("DELETE", PELORUS_HOST, MANAGER_PORT, path)

    @staticmethod
    def pelorus_path(path):
        if path.startswith("/pelorus/"):
            return path[len("/pelorus") :]
        if path.startswith("/api/"):
            return path
        return None

    def forward(self, method, host, port, upstream_path, body=None):
        query = urlsplit(self.path).query
        target = upstream_path + (f"?{query}" if query else "")
        connection = http.client.HTTPConnection(host, port, timeout=180)
        headers = {"Host": f"{host}:{port}"}
        for key, value in self.headers.items():
            if key.lower() not in HOP_BY_HOP and key.lower() != "host":
                headers[key] = value
        if body is not None:
            headers["Content-Length"] = str(len(body))
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
        except OSError as error:
            log(f"upstream {host}:{port} error: {error}")
            self.send_error(502)
            return
        try:
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP_BY_HOP and key.lower() != "content-length":
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
        finally:
            connection.close()

    def handle_playwright(self, profile):
        if not authorized(self, allow_query_token=True):
            self.send_error(401)
            return
        parsed = read_browser_endpoint(profile)
        if parsed is None:
            self.send_error(404)
            return
        try:
            upstream = socket.create_connection((parsed.hostname, parsed.port), timeout=30)
        except OSError as error:
            log(f"playwright upstream error: {error}")
            self.send_error(502)
            return
        try:
            request_target = parsed.path or "/"
            if parsed.query:
                request_target += f"?{parsed.query}"
            lines = [f"GET {request_target} HTTP/1.1"]
            for key, value in self.headers.items():
                if key.lower() == "host":
                    continue
                lines.append(f"{key}: {value}")
            lines.append(f"Host: {parsed.hostname}:{parsed.port}")
            lines.append("")
            lines.append("")
            upstream.sendall("\r\n".join(lines).encode("latin-1"))
            self.close_connection = True
            self.splice(self.connection, upstream)
        finally:
            upstream.close()

    @staticmethod
    def splice(client, upstream):
        sockets = [client, upstream]
        while True:
            readable, _, _ = select.select(sockets, [], [], 300)
            if not readable:
                return
            for source in readable:
                try:
                    data = source.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                target = upstream if source is client else client
                try:
                    target.sendall(data)
                except OSError:
                    return


def main():
    if not TOKEN:
        log("AGENT_DESKTOP_API_TOKEN is not set; refusing to start")
        return 1
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    server.daemon_threads = True
    log(f"listening on {BIND}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
