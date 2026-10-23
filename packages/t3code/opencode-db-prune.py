"""Prune OpenCode's unbounded SQLite event log before it fills the disk.

OpenCode stores projected session state in message/part/session tables and also
appends every update to an event-sourcing `event` table with no retention
(upstream anomalyco/opencode#33356). On long-lived t3code hosts the event log
dominates `~/.local/share/opencode/opencode.db` and eventually makes ordinary
queries fail with "database or disk is full".

This tool deletes `event` / `event_sequence` rows and vacuums in place when
those tables cross a size or row threshold, keeping projected session data
and the database inode used by connected clients.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

GIB = 1024**3
MIB = 1024**2

# Defaults chosen below the sizes that already break SQLite temp work on a 32G
# /tmp and well below the 13G+ reports in upstream issue #33356.
DEFAULT_EVENT_BYTES = 2 * GIB
DEFAULT_EVENT_ROWS = 100_000
DEFAULT_LOG_BYTES = 50 * MIB
SKIP_TABLES = frozenset({"event", "event_sequence"})


def default_db_path() -> Path:
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(data) / "opencode" / "opencode.db"


def default_log_path() -> Path:
    return default_db_path().parent / "log" / "opencode.log"


def measure(db_path: Path) -> dict:
    """Return size metrics for an OpenCode SQLite database."""
    size = db_path.stat().st_size
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        page_count, page_size, freelist = (
            con.execute("PRAGMA page_count").fetchone()[0],
            con.execute("PRAGMA page_size").fetchone()[0],
            con.execute("PRAGMA freelist_count").fetchone()[0],
        )
        tables = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY 1"
            )
        ]
        event_rows = 0
        event_bytes = 0
        if "event" in tables:
            event_rows = con.execute("SELECT COUNT(*) FROM event").fetchone()[0]
            # dbstat is present on SQLite builds used here; fall back to 0.
            try:
                event_bytes = (
                    con.execute(
                        "SELECT COALESCE(SUM(pgsize), 0) FROM dbstat WHERE name='event'"
                    ).fetchone()[0]
                    or 0
                )
            except sqlite3.DatabaseError:
                event_bytes = 0
    finally:
        con.close()
    return {
        "path": str(db_path),
        "size": size,
        "page_count": page_count,
        "page_size": page_size,
        "freelist": freelist,
        "tables": tables,
        "event_rows": event_rows,
        "event_bytes": event_bytes,
    }


def should_prune(metrics: dict, *, event_bytes: int, event_rows: int) -> bool:
    if "event" not in metrics.get("tables", []):
        return False
    return metrics["event_bytes"] >= event_bytes or metrics["event_rows"] >= event_rows


def prune_in_place(db_path: Path) -> dict | None:
    """Prune under SQLite's write lock, preserving open clients' database inode."""
    con = sqlite3.connect(str(db_path), timeout=0.1)
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        try:
            con.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            if "locked" in str(error).lower() or "busy" in str(error).lower():
                return None
            raise
        tables = [row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )]
        for table in SKIP_TABLES:
            if table in tables:
                con.execute('DELETE FROM "' + table + '"')
        con.commit()
        # VACUUM retains the inode and incorporates committed writes, including
        # clients that were already connected before maintenance started.
        con.execute("VACUUM")
        if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("pruned database failed quick_check")
        kept = sum(con.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
                   for table in tables if table not in SKIP_TABLES)
        return {"size": db_path.stat().st_size, "kept_rows": kept}
    finally:
        con.close()


def rotate_log(log_path: Path, *, max_bytes: int) -> bool:
    if not log_path.is_file():
        return False
    if log_path.stat().st_size < max_bytes:
        return False
    backup = log_path.with_suffix(log_path.suffix + ".old")
    if backup.exists():
        backup.unlink()
    log_path.replace(backup)
    log_path.write_text("")
    backup.unlink(missing_ok=True)
    return True


def prune(
    db_path: Path,
    *,
    event_bytes: int = DEFAULT_EVENT_BYTES,
    event_rows: int = DEFAULT_EVENT_ROWS,
    log_path: Path | None = None,
    log_bytes: int = DEFAULT_LOG_BYTES,
    dry_run: bool = False,
) -> int:
    """Prune when thresholds are crossed. Returns process exit status."""
    if not db_path.is_file():
        print(f"info: opencode db absent at {db_path}; nothing to prune", file=sys.stderr)
        return 0

    metrics = measure(db_path)
    print(
        "info: opencode db "
        f"size={metrics['size']} event_rows={metrics['event_rows']} "
        f"event_bytes={metrics['event_bytes']}",
        file=sys.stderr,
    )

    rotated = False
    if log_path is not None and log_path.is_file():
        if dry_run:
            if log_path.stat().st_size >= log_bytes:
                print(
                    f"info: would rotate opencode log ({log_path.stat().st_size} bytes)",
                    file=sys.stderr,
                )
        else:
            rotated = rotate_log(log_path, max_bytes=log_bytes)
            if rotated:
                print(f"info: rotated opencode log at {log_path}", file=sys.stderr)

    if not should_prune(metrics, event_bytes=event_bytes, event_rows=event_rows):
        print("info: opencode event log within thresholds", file=sys.stderr)
        return 0

    if dry_run:
        print(
            "info: would prune opencode event/event_sequence rows and vacuum in place",
            file=sys.stderr,
        )
        return 0

    result = prune_in_place(db_path)
    if result is None:
        print("warning: opencode db is busy; event prune deferred", file=sys.stderr)
        return 0

    print(
        "info: pruned opencode event log; "
        f"new_size={result['size']} kept_rows={result['kept_rows']}",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="Path to opencode.db")
    parser.add_argument(
        "--event-bytes",
        type=int,
        default=DEFAULT_EVENT_BYTES,
        help="Prune when event table pages reach this many bytes",
    )
    parser.add_argument(
        "--event-rows",
        type=int,
        default=DEFAULT_EVENT_ROWS,
        help="Prune when event row count reaches this many rows",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Optional opencode.log path to rotate when oversized",
    )
    parser.add_argument(
        "--log-bytes",
        type=int,
        default=DEFAULT_LOG_BYTES,
        help="Rotate the log when it reaches this many bytes",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    db_path = args.db or default_db_path()
    log_path = args.log
    if log_path is None and args.db is None:
        log_path = default_log_path()
    return prune(
        db_path,
        event_bytes=args.event_bytes,
        event_rows=args.event_rows,
        log_path=log_path,
        log_bytes=args.log_bytes,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
