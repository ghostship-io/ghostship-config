"""A read-only T3 Code RPC client.

T3 Code 0.1.1 exposes its usage summary, provider statuses, and subscription
limits over a WebSocket JSON protocol (Effect RPC with JSON envelopes). This
client speaks that protocol with the standard `websockets` library, so the
transport is the one the platform already uses: TLS with certificate
validation, a checked handshake, bounded frames, fragmentation, and ping and
pong handled by the library.

Wire shapes used here:

    request  {"_tag":"Request","id":1,"tag":"server.getUsageSummary","payload":{...},"headers":[]}
    response {"_tag":"Exit","requestId":1,"exit":{"_tag":"Success","value":{...}}}
    failure  {"_tag":"Exit","requestId":1,"exit":{"_tag":"Failure","cause":[...]}}

The server rejects an upgrade without the orchestration protocol parameter and
requires a bearer session with the matching scope. The client only ever calls
read methods, and it never copies a failure message out of the process: a
failure is a fixed reason code.
"""

from __future__ import annotations

import json
from time import monotonic as _monotonic
from typing import Any

import codes

try:  # pragma: no cover - the collector always ships the library
    from websockets.sync.client import connect as _websocket_connect
except ImportError:  # pragma: no cover - a missing library is a setup error
    _websocket_connect = None

DEFAULT_TIMEOUT = 60.0

# A usage summary with thirty days of buckets is small. Anything larger is
# refused rather than buffered.
MAX_MESSAGE_BYTES = 8 * 1024 * 1024


class T3Error(RuntimeError):
    """A T3 request failed.

    The message is a fixed reason code. A provider's own failure text can
    carry an identifier, an address, or a token, so it never leaves the
    process.
    """

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason = str(reason_code)


class T3Client:
    """A short-lived T3 Code RPC client. One instance serves one collection."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        orchestration_protocol: int = 2,
        max_size: int = MAX_MESSAGE_BYTES,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.orchestration_protocol = orchestration_protocol
        self.max_size = max_size
        self._connection = None
        self._request_id = 0

    # -- connection -----------------------------------------------------
    def socket_url(self) -> str:
        """The WebSocket URL of the server."""
        base = self.base_url
        if base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        elif base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        elif not base.startswith(("ws://", "wss://")):
            raise T3Error(codes.INVALID_RESPONSE)
        if not base.endswith("/ws"):
            base = base.rstrip("/") + "/ws"
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}orchestrationProtocol={self.orchestration_protocol}"

    def connect(self) -> None:
        """Open the connection.

        An `https` endpoint is always reached over TLS: the bearer session
        never crosses a plain socket.
        """
        if _websocket_connect is None:
            raise T3Error(codes.UNAVAILABLE)
        url = self.socket_url()
        if url.startswith("wss://"):
            import ssl

            context = ssl.create_default_context()
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
        else:
            context = None
        try:
            self._connection = _websocket_connect(
                url,
                additional_headers={"Authorization": f"Bearer {self.token}"},
                ssl=context,
                open_timeout=self.timeout,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=20,
                max_size=self.max_size,
                max_queue=16,
            )
        except T3Error:
            raise
        except Exception as error:  # noqa: BLE001 - the reason must stay a code
            raise T3Error(_reason_for(error)) from None

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:  # noqa: BLE001 - closing must never raise
                pass
            self._connection = None

    def __enter__(self) -> "T3Client":
        self.connect()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    # -- requests -------------------------------------------------------
    def call(self, tag: str, payload: dict[str, Any] | None = None) -> Any:
        """Call one read method and return its success value."""
        deadline = _monotonic() + self.timeout
        if self._connection is None:
            self.connect()
        assert self._connection is not None
        self._request_id += 1
        request_id = self._request_id
        request = {
            "_tag": "Request",
            "id": request_id,
            "tag": tag,
            "payload": payload or {},
            "headers": [],
        }
        try:
            self._connection.send(json.dumps(request))
            while True:
                remaining = deadline - _monotonic()
                if remaining <= 0:
                    raise TimeoutError("T3 RPC deadline elapsed")
                raw = self._connection.recv(timeout=remaining)
                message = json.loads(raw)
                kind = message.get("_tag")
                if kind in ("Ack", "Pong"):
                    continue
                if kind == "Exit":
                    if message.get("requestId") != request_id:
                        continue
                    exit_payload = message.get("exit") or {}
                    if exit_payload.get("_tag") == "Success":
                        return exit_payload.get("value")
                    # The cause of a failure is a provider message: it is not
                    # copied anywhere.
                    raise T3Error(codes.RPC_FAILED)
                if kind == "Defect":
                    raise T3Error(codes.PROTOCOL_ERROR)
        except T3Error as error:
            if error.reason != codes.RPC_FAILED:
                self.close()
            raise
        except Exception as error:  # noqa: BLE001 - the reason must stay a code
            # Never let a timed-out reply satisfy a following cached read.
            self.close()
            raise T3Error(_reason_for(error)) from None


def _reason_for(error: Exception) -> str:
    """Map a transport failure onto a fixed reason code."""
    name = type(error).__name__
    if "Timeout" in name:
        return codes.TIMEOUT
    if "SSL" in name or "Certificate" in name:
        return codes.CONNECTION_ERROR
    if "InvalidStatus" in name or "InvalidHandshake" in name:
        return codes.HANDSHAKE_REJECTED
    if "PayloadTooBig" in name or "MessageTooBig" in name:
        return codes.INVALID_RESPONSE
    if "ConnectionClosed" in name:
        return codes.CONNECTION_ERROR
    return codes.PROTOCOL_ERROR
