"""A minimal read-only T3 Code RPC client.

T3 Code 0.1.1 exposes its usage summary, provider statuses, and subscription
limits over a WebSocket JSON protocol (Effect RPC with JSON envelopes). This
client speaks that protocol directly so the collector never has to modify,
fork, or patch T3 Code, and it only ever calls read methods.

Wire shapes used here:

    request  {"_tag":"Request","id":1,"tag":"server.getUsageSummary","payload":{...},"headers":[]}
    response {"_tag":"Exit","requestId":1,"exit":{"_tag":"Success","value":{...}}}
    failure  {"_tag":"Exit","requestId":1,"exit":{"_tag":"Failure","cause":[...]}}

The server rejects an upgrade without the orchestration protocol parameter and
requires a bearer session with the matching scope.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import urllib.parse
from typing import Any

DEFAULT_TIMEOUT = 60.0


class T3Error(RuntimeError):
    """A T3 request failed."""


class T3Client:
    """A short-lived T3 Code RPC client. One instance serves one collection."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        orchestration_protocol: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.orchestration_protocol = orchestration_protocol
        self._socket: socket.socket | None = None
        self._buffer = b""
        self._next_id = 0

    # -- connection -----------------------------------------------------
    def connect(self) -> None:
        parts = urllib.parse.urlsplit(self.base_url)
        scheme = parts.scheme or "http"
        host = parts.hostname or "127.0.0.1"
        port = parts.port or (443 if scheme in ("https", "wss") else 80)
        path = parts.path or ""
        if not path.endswith("/ws"):
            path = path.rstrip("/") + "/ws"
        query = urllib.parse.parse_qsl(parts.query)
        query.append(("orchestrationProtocol", str(self.orchestration_protocol)))
        target = path + "?" + urllib.parse.urlencode(query)
        connection = socket.create_connection((host, port), self.timeout)
        connection.settimeout(self.timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {target} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Authorization: Bearer {self.token}\r\n"
            "\r\n"
        )
        connection.sendall(request.encode())
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = connection.recv(4096)
            if not chunk:
                connection.close()
                raise T3Error("t3 handshake closed")
            buffer += chunk
        head, remainder = buffer.split(b"\r\n\r\n", 1)
        status_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts_list = status_line.split(" ", 2)
        status = parts_list[1] if len(parts_list) > 1 else ""
        if status != "101":
            connection.close()
            raise T3Error(f"t3 handshake rejected ({status})")
        self._socket = connection
        self._buffer = remainder

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def __enter__(self) -> "T3Client":
        self.connect()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    # -- framing --------------------------------------------------------
    def _send(self, payload: str) -> None:
        assert self._socket is not None
        data = payload.encode()
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack("!H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", length)
        mask = os.urandom(4)
        header += mask
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self._socket.sendall(bytes(header) + masked)

    def _fill(self) -> None:
        assert self._socket is not None
        chunk = self._socket.recv(65536)
        if not chunk:
            raise T3Error("t3 connection closed")
        self._buffer += chunk

    def _recv_frame(self) -> bytes:
        while True:
            if len(self._buffer) >= 2:
                first, second = self._buffer[0], self._buffer[1]
                opcode = first & 0x0F
                length = second & 0x7F
                offset = 2
                if length == 126:
                    if len(self._buffer) < 4:
                        self._fill()
                        continue
                    length = struct.unpack("!H", self._buffer[2:4])[0]
                    offset = 4
                elif length == 127:
                    if len(self._buffer) < 10:
                        self._fill()
                        continue
                    length = struct.unpack("!Q", self._buffer[2:10])[0]
                    offset = 10
                if len(self._buffer) < offset + length:
                    self._fill()
                    continue
                payload = self._buffer[offset:offset + length]
                self._buffer = self._buffer[offset + length:]
                if opcode == 0x8:
                    raise T3Error("t3 server closed the socket")
                if opcode == 0x9:
                    continue
                if opcode in (0x1, 0x2):
                    return payload
                continue
            self._fill()

    # -- requests -------------------------------------------------------
    def call(self, tag: str, payload: dict[str, Any] | None = None) -> Any:
        """Call one read method and return its success value."""
        if self._socket is None:
            self.connect()
        self._next_id += 1
        request_id = self._next_id
        self._send(
            json.dumps(
                {
                    "_tag": "Request",
                    "id": request_id,
                    "tag": tag,
                    "payload": payload or {},
                    "headers": [],
                }
            )
        )
        while True:
            message = json.loads(self._recv_frame().decode("utf-8", "replace"))
            kind = message.get("_tag")
            if kind in ("Ack", "Pong"):
                continue
            if kind == "Exit":
                if message.get("requestId") != request_id:
                    continue
                exit_payload = message.get("exit") or {}
                if exit_payload.get("_tag") == "Success":
                    return exit_payload.get("value")
                cause = exit_payload.get("cause") or []
                detail = "; ".join(
                    str(item.get("error") or item.get("defect") or item) for item in cause
                )
                raise T3Error(f"{tag} failed: {detail[:200]}")
            if kind == "Defect":
                raise T3Error(f"{tag} defect: {str(message.get('defect'))[:200]}")
