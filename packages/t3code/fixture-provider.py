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
        authorization = self.headers.get("authorization", "")
        if authorization != PLACEHOLDER:
            # Only the acceptance's placeholder is served; any other credential
            # is refused and recorded as a kind only, never as a value.
            self.server.requests.append({
                "model": None,
                "prompt": None,
                "path": self.path,
                "auth": "absent" if not authorization else "other",
                "refused": True,
            })
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
        authorization = self.headers.get("authorization", "")
        auth_kind = ("placeholder" if authorization == PLACEHOLDER
                     else ("absent" if not authorization else "other"))
        self.server.requests.append({
            "model": request.get("model"),
            "prompt": prompt[:4000],
            "path": self.path,
            "auth": auth_kind,
        })
        model = request.get("model") or "probe"
        if request.get("stream"):
            # OpenAI-compatible SSE: opencode requires a finish_reason event.
            events = [
                {"id": "chatcmpl-fixture", "object": "chat.completion.chunk",
                 "created": 0, "model": model,
                 "choices": [{"index": 0, "delta": {"role": "assistant", "content": self.server.reply},
                              "finish_reason": None}]},
                {"id": "chatcmpl-fixture", "object": "chat.completion.chunk",
                 "created": 0, "model": model,
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
            ]
            body = b"".join(
                b"data: " + json.dumps(event).encode() + b"\n\n" for event in events
            ) + b"data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            return
        self._send(200, {
            "id": "chatcmpl-fixture",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": self.server.reply},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=38917)
    parser.add_argument("--reply", default=REPLY)
    parser.add_argument("--pid-file")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.requests = []
    server.reply = args.reply
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
