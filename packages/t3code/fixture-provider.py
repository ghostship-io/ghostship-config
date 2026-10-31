#!/usr/bin/env python3
"""Test-only OpenAI-compatible fixture endpoint for candidate acceptance.

It serves one deterministic assistant reply and records every request so the
acceptance can prove the candidate's turn actually reached this fixture. It
carries no account or production code. It only answers requests bearing the
placeholder credential "fixture", so a real account token (or any other
credential) is refused. The acceptance copies it into the disposable candidate
at run time and starts it on loopback; it is never part of the T3 image.
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = "PROBE_PASS"
PLACEHOLDER = "Bearer fixture"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def _send(self, status, payload):
        data = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.rstrip("/")
        if path == "/health":
            self._send(200, {"ok": True})
        elif path == "/requests":
            self._send(200, {"count": len(self.server.requests),
                             "requests": self.server.requests})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length)
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, {"error": "not found"})
            return
        if self.headers.get("authorization", "") != PLACEHOLDER:
            # Only the acceptance's placeholder is served; a real credential is
            # refused rather than exercised.
            self._send(403, {"error": "fixture accepts only the placeholder credential"})
            return
        try:
            request = json.loads(body)
        except ValueError:
            self._send(400, {"error": "invalid json"})
            return
        messages = request.get("messages") if isinstance(request, dict) else None
        prompt = " ".join(str(item.get("content") or "") for item in messages or []
                          if isinstance(item, dict))
        self.server.requests.append({
            "model": request.get("model"),
            "prompt": prompt[:500],
            "path": self.path,
        })
        self._send(200, {
            "id": "chatcmpl-fixture",
            "object": "chat.completion",
            "created": 0,
            "model": request.get("model") or "probe",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": REPLY},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=38917)
    parser.add_argument("--pid-file")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.requests = []
    if args.pid_file:
        with open(args.pid_file, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
