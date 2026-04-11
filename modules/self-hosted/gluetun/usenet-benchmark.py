#!/usr/bin/env python3
import argparse
import json
import socket
import ssl
import sys
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

DEFAULT_GROUPS = [
    "alt.binaries.test",
    "alt.test",
]


class NNTPError(RuntimeError):
    pass


class NNTPClient:
    def __init__(self, host: str, port: int, username: str, password: str, timeout: float) -> None:
        raw_sock = socket.create_connection((host, port), timeout=timeout)
        context = ssl.create_default_context()
        self.sock = context.wrap_socket(raw_sock, server_hostname=host)
        self.sock.settimeout(timeout)
        self.reader = self.sock.makefile("rb")
        self._expect([200, 201])
        self._command(f"AUTHINFO USER {username}")
        code, _ = self._expect([281, 381])
        if code == 381:
            self._command(f"AUTHINFO PASS {password}")
            self._expect([281])

    def close(self) -> None:
        try:
            self._command("QUIT")
        except Exception:
            pass
        try:
            self.reader.close()
        except Exception:
            pass
        self.sock.close()

    def _command(self, command: str) -> None:
        self.sock.sendall(command.encode("utf-8") + b"\r\n")

    def _readline(self) -> bytes:
        line = self.reader.readline()
        if not line:
            raise NNTPError("Connection closed by server")
        return line.rstrip(b"\r\n")

    def _expect(self, allowed: list[int]) -> tuple[int, str]:
        line = self._readline().decode("utf-8", "replace")
        try:
            code = int(line[:3])
        except ValueError as exc:
            raise NNTPError(f"Invalid NNTP response: {line!r}") from exc
        if code not in allowed:
            raise NNTPError(f"Unexpected NNTP response {line!r}, expected {allowed}")
        return code, line[4:] if len(line) > 4 else ""

    def group(self, name: str) -> tuple[int, int]:
        self._command(f"GROUP {name}")
        _, payload = self._expect([211])
        parts = payload.split()
        if len(parts) < 3:
            raise NNTPError(f"Invalid GROUP payload: {payload!r}")
        low = int(parts[1])
        high = int(parts[2])
        return low, high

    def xover(self, start: int, end: int) -> list[dict[str, Any]]:
        self._command(f"XOVER {start}-{end}")
        self._expect([224])
        rows: list[dict[str, Any]] = []
        while True:
            raw = self._readline()
            if raw == b".":
                break
            if raw.startswith(b".."):
                raw = raw[1:]
            parts = raw.decode("utf-8", "replace").split("\t")
            if len(parts) < 8:
                continue
            try:
                article_number = int(parts[0])
                bytes_count = int(parts[6])
                lines_count = int(parts[7])
            except ValueError:
                continue
            rows.append(
                {
                    "article_number": article_number,
                    "subject": parts[1],
                    "from": parts[2],
                    "date": parts[3],
                    "message_id": parts[4],
                    "references": parts[5],
                    "bytes": bytes_count,
                    "lines": lines_count,
                }
            )
        return rows

    def body_bytes(self, message_id: str, byte_limit: int | None = None, deadline: float | None = None) -> int:
        self._command(f"BODY {message_id}")
        self._expect([222])
        transferred = 0
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            raw = self._readline()
            if raw == b".":
                break
            if raw.startswith(b".."):
                raw = raw[1:]
            transferred += len(raw) + 2
            if byte_limit is not None and transferred >= byte_limit:
                break
        return transferred


def discover(args: argparse.Namespace) -> int:
    client = NNTPClient(args.host, args.port, args.username, args.password, args.timeout)
    try:
        selected_group = None
        selected_rows: list[dict[str, Any]] = []
        for group in args.groups:
            try:
                low, high = client.group(group)
            except NNTPError:
                continue
            start = max(low, high - args.scan_window + 1)
            rows = client.xover(start, high)
            candidates = [
                row
                for row in rows
                if row["bytes"] >= args.min_bytes
                and row["message_id"].startswith("<")
                and row["message_id"].endswith(">")
            ]
            if not candidates:
                continue
            candidates.sort(
                key=lambda row: (row["bytes"], _safe_timestamp(row.get("date", ""))),
                reverse=True,
            )
            selected_rows = candidates[: args.sample_count]
            selected_group = group
            break
        if not selected_group or not selected_rows:
            raise NNTPError("No suitable benchmark articles found in configured groups")
        payload = {
            "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "group": selected_group,
            "articles": [
                {
                    "message_id": row["message_id"],
                    "bytes": row["bytes"],
                    "date": row.get("date", ""),
                    "subject": row.get("subject", ""),
                }
                for row in selected_rows
            ],
            "total_expected_bytes": sum(row["bytes"] for row in selected_rows),
        }
        print(json.dumps(payload))
        return 0
    finally:
        client.close()


def measure(args: argparse.Namespace) -> int:
    corpus = json.loads(Path(args.corpus_file).read_text())
    articles = corpus.get("articles", [])
    if not articles:
        raise NNTPError("Benchmark corpus is empty")

    client = NNTPClient(args.host, args.port, args.username, args.password, args.timeout)
    try:
        started = time.monotonic()
        deadline = started + args.time_limit
        bytes_target = args.bytes_target
        transferred = 0
        completed = 0
        attempts = 0
        for article in articles:
            if time.monotonic() >= deadline or transferred >= bytes_target:
                break
            message_id = article.get("message_id")
            if not message_id:
                continue
            attempts += 1
            remaining = max(1, bytes_target - transferred)
            transferred += client.body_bytes(message_id, byte_limit=remaining, deadline=deadline)
            completed += 1
        elapsed = max(time.monotonic() - started, 0.001)
        payload = {
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bytes_transferred": transferred,
            "elapsed_seconds": elapsed,
            "bytes_per_second": transferred / elapsed,
            "articles_attempted": attempts,
            "articles_completed": completed,
            "time_limit_seconds": args.time_limit,
            "bytes_target": bytes_target,
            "corpus_group": corpus.get("group"),
        }
        print(json.dumps(payload))
        return 0
    finally:
        client.close()


def _safe_timestamp(value: str) -> float:
    try:
        return parsedate_to_datetime(value).timestamp()
    except Exception:
        return 0.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded Usenet NNTP benchmark helper")
    parser.add_argument("mode", choices=["discover", "measure"])
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--groups", nargs="+", default=DEFAULT_GROUPS)
    parser.add_argument("--scan-window", type=int, default=1500)
    parser.add_argument("--sample-count", type=int, default=6)
    parser.add_argument("--min-bytes", type=int, default=262144)
    parser.add_argument("--corpus-file")
    parser.add_argument("--bytes-target", type=int, default=12582912)
    parser.add_argument("--time-limit", type=float, default=15.0)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.mode == "discover":
        return discover(args)
    if not args.corpus_file:
        parser.error("--corpus-file is required for measure mode")
    return measure(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except NNTPError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
