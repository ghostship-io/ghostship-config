#!/usr/bin/env python3
"""Minimal, dependency-free Chrome DevTools Protocol client for detection tests.

Implements just enough WebSocket framing to run a single CDP operation per
invocation, so each experiment enables exactly one thing.
"""

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import time
import urllib.request


class WsError(Exception):
    pass


class WebSocket:
    def __init__(self, host, port, path, timeout=10.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WsError("handshake closed early")
            data += chunk
        head, rest = data.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if "101" not in status:
            raise WsError(f"handshake rejected: {status}")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        if f"sec-websocket-accept: {accept}".lower() not in head.decode("latin-1").lower():
            raise WsError("bad Sec-WebSocket-Accept")
        self.buf = rest
        self.next_id = 0

    def _read_exact(self, size):
        while len(self.buf) < size:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WsError("connection closed")
            self.buf += chunk
        out, self.buf = self.buf[:size], self.buf[size:]
        return out

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def send_text(self, text):
        self._send_frame(0x1, text.encode())

    def _recv_message(self):
        frame = b""
        while True:
            b1, b2 = self._read_exact(2)
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x8:
                raise WsError("closed by peer")
            if opcode in (0x1, 0x2):
                frame = payload
            elif opcode == 0x0:
                frame += payload
            if fin:
                return frame.decode("utf-8", "replace")

    def call(self, method, params=None, session_id=None, timeout=10.0):
        self.next_id += 1
        message_id = self.next_id
        message = {"id": message_id, "method": method}
        if params is not None:
            message["params"] = params
        if session_id:
            message["sessionId"] = session_id
        self.send_text(json.dumps(message))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.sock.settimeout(max(0.1, deadline - time.time()))
            data = self._recv_message()
            try:
                parsed = json.loads(data)
            except ValueError:
                continue
            if parsed.get("id") == message_id:
                if "error" in parsed:
                    raise WsError(f"{method}: {parsed['error']}")
                return parsed.get("result", {})
        raise WsError(f"timeout waiting for {method}")

    def close(self):
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def http_json(port, path, timeout=5.0):
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def page_target(port):
    for target in http_json(port, "/json/list"):
        if target.get("type") == "page":
            return target
    raise WsError("no page target")


def run_operations(port, ops, log):
    """Run one experiment variant. Returns a list of executed step names."""
    executed = []
    if "http" in ops:
        http_json(port, "/json/version")
        http_json(port, "/json/list")
        executed.append("http:/json/version+/json/list")
    if not ops - {"http"}:
        return executed

    browser = None
    page_ws = None
    session_id = None
    if "browser" in ops or "attach" in ops or "runtime_enable" in ops:
        browser = WebSocket("127.0.0.1", port, f"/devtools/browser/{http_json(port, '/json/version')['webSocketDebuggerUrl'].rsplit('/', 1)[-1]}")
        executed.append("browser_ws:connect")
    if "page_ws" in ops:
        target = page_target(port)
        page_ws = WebSocket("127.0.0.1", port, target["webSocketDebuggerUrl"].split(str(port), 1)[1])
        executed.append("page_ws:connect")

    try:
        if "browser_version" in ops:
            browser.call("Browser.getVersion")
            executed.append("Browser.getVersion")
        if "targets" in ops:
            browser.call("Target.getTargets")
            executed.append("Target.getTargets")
        if "attach" in ops:
            target = page_target(port)
            result = browser.call("Target.attachToTarget", {"targetId": target["id"], "flatten": True})
            session_id = result.get("sessionId")
            executed.append("Target.attachToTarget")
        if "page_enable" in ops:
            (page_ws or browser).call("Page.enable", session_id=session_id)
            executed.append("Page.enable")
        if "network_enable" in ops:
            (page_ws or browser).call("Network.enable", session_id=session_id)
            executed.append("Network.enable")
        if "dom_enable" in ops:
            (page_ws or browser).call("DOM.enable", session_id=session_id)
            executed.append("DOM.enable")
        if "runtime_evaluate" in ops:
            (page_ws or browser).call(
                "Runtime.evaluate",
                {"expression": "document.title", "returnByValue": True},
                session_id=session_id,
            )
            executed.append("Runtime.evaluate")
        if "accessibility" in ops:
            (page_ws or browser).call("Accessibility.getFullAXTree", session_id=session_id)
            executed.append("Accessibility.getFullAXTree")
        if "input" in ops:
            (page_ws or browser).call(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": 120, "y": 120},
                session_id=session_id,
            )
            executed.append("Input.dispatchMouseEvent")
        if "runtime_enable" in ops:
            (page_ws or browser).call("Runtime.enable", session_id=session_id)
            executed.append("Runtime.enable")
        time.sleep(6)
    finally:
        if page_ws:
            page_ws.close()
        if browser:
            browser.close()
    return executed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ops", required=True, help="comma separated: http,browser,browser_version,targets,attach,page_ws,page_enable,network_enable,dom_enable,runtime_evaluate,accessibility,input,runtime_enable")
    parser.add_argument("--log", default="-")
    args = parser.parse_args()
    start = time.time()
    ops = set(filter(None, args.ops.split(","))) if args.ops != "none" else set()
    try:
        if not ops:
            print(json.dumps({"ok": True, "executed": [], "seconds": 0.0}))
            return 0
        executed = run_operations(args.port, ops, args.log)
        print(json.dumps({"ok": True, "executed": executed, "seconds": round(time.time() - start, 2)}))
        return 0
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error), "seconds": round(time.time() - start, 2)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
