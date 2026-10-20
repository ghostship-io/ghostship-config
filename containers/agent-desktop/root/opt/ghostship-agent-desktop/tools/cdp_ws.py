"""Minimal asyncio Chrome DevTools websocket client (stdlib only).

Used by the desktop test harnesses. It speaks only the commands a caller
sends; it never enables the Runtime domain on its own.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import urllib.request
from typing import Any


class CdpError(RuntimeError):
    pass


class Cdp:
    """One browser-level websocket with flat target sessions."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        self._next = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._listeners: list[tuple[str, Any, asyncio.Queue]] = []
        self._task = asyncio.ensure_future(self._pump())

    @classmethod
    async def connect(cls, port: int, host: str = "127.0.0.1", ws_url: str | None = None) -> "Cdp":
        if ws_url is None:
            ws_url = await asyncio.to_thread(
                lambda: json.load(urllib.request.urlopen(f"http://{host}:{port}/json/version", timeout=5))[
                    "webSocketDebuggerUrl"])
        path = "/" + ws_url.split("/", 3)[3]
        reader, writer = await asyncio.open_connection(host, port, limit=64 * 1024 * 1024)
        key = base64.b64encode(os.urandom(16)).decode()
        writer.write((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        await writer.drain()
        head = await reader.readuntil(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise CdpError("websocket handshake refused")
        return cls(reader, writer)

    async def _frame(self) -> tuple[int, bytes]:
        b0, b1 = await self.reader.readexactly(2)
        n = b1 & 127
        if n == 126:
            n = int.from_bytes(await self.reader.readexactly(2), "big")
        elif n == 127:
            n = int.from_bytes(await self.reader.readexactly(8), "big")
        mask = await self.reader.readexactly(4) if b1 & 128 else None
        data = await self.reader.readexactly(n)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return b0 & 15, data

    async def _pump(self) -> None:
        buf = b""
        try:
            while True:
                op, data = await self._frame()
                if op == 8:
                    break
                if op not in (0, 1):
                    continue
                buf += data
                message = json.loads(buf)
                buf = b""
                if "id" in message:
                    fut = self._pending.pop(message["id"], None)
                    if fut and not fut.done():
                        fut.set_result(message)
                    continue
                for method, session, queue in list(self._listeners):
                    if message.get("method") == method and (session is None or message.get("sessionId") == session):
                        queue.put_nowait(message)
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            pass
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(CdpError("connection closed"))

    async def send(self, method: str, params: dict[str, Any] | None = None, session: str | None = None,
                   timeout: float = 30.0) -> dict[str, Any]:
        self._next += 1
        message: dict[str, Any] = {"id": self._next, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        fut = asyncio.get_running_loop().create_future()
        self._pending[self._next] = fut
        data = json.dumps(message).encode()
        mask = os.urandom(4)
        n = len(data)
        header = bytes([0x81, 0x80 | n]) if n < 126 else (
            bytes([0x81, 0x80 | 126]) + n.to_bytes(2, "big") if n < 65536 else bytes([0x81, 0x80 | 127]) + n.to_bytes(8, "big"))
        self.writer.write(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        await self.writer.drain()
        reply = await asyncio.wait_for(fut, timeout)
        if "error" in reply:
            raise CdpError(f"{method}: {reply['error'].get('message')}")
        return reply.get("result") or {}

    def listen(self, method: str, session: str | None = None) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.append((method, session, queue))
        return queue

    def unlisten(self, queue: asyncio.Queue) -> None:
        self._listeners = [entry for entry in self._listeners if entry[2] is not queue]

    async def evaluate(self, session: str, expression: str, timeout: float = 30.0) -> Any:
        """One-shot evaluation without enabling the Runtime domain."""
        result = await self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                      "awaitPromise": True}, session, timeout)
        if result.get("exceptionDetails"):
            raise CdpError(f"evaluate failed: {result['exceptionDetails'].get('text')}")
        return result.get("result", {}).get("value")

    async def close(self) -> None:
        self._task.cancel()
        self.writer.close()
