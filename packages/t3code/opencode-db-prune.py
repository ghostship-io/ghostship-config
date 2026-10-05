"""Prune OpenCode's unbounded SQLite event log before it fills the disk.

OpenCode stores projected session state in message/part/session tables and also
appends every update to an event-sourcing `event` table with no retention
(upstream anomalyco/opencode#33356). On long-lived t3code hosts the event log
dominates `~/.local/share/opencode/opencode.db` and eventually makes ordinary
queries fail with "database or disk is full".

This tool rebuilds the database without `event` / `event_sequence` rows when
those tables cross a size or row threshold, keeping projected session data.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
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


def db_is_busy(db_path: Path) -> bool:
    """Return True when another connection holds a write lock."""
    try:
        con = sqlite3.connect(str(db_path), timeout=0.1)
        try:
            con.execute("BEGIN IMMEDIATE")
            con.rollback()
        finally:
            con.close()
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return True
        raise
    return False


def rebuild_without_events(src: Path, dst: Path) -> dict:
    """Copy src into dst, leaving event tables empty."""
    if dst.exists():
        dst.unlink()
    src_con = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5)
    try:
        tables = [
            row[0]
            for row in src_con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY 1"
            )
        ]
        table_sql = list(
            src_con.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
            )
        )
        index_sql = list(
            src_con.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            )
        )
    finally:
        src_con.close()

    dst_con = sqlite3.connect(str(dst))
    try:
        dst_con.execute("PRAGMA journal_mode=OFF")
        dst_con.execute("PRAGMA synchronous=OFF")
        dst_con.execute(f"ATTACH DATABASE '{src}' AS old")
        for _name, sql in table_sql:
            dst_con.execute(sql)
        for _name, sql in index_sql:
            dst_con.execute(sql)
        kept = 0
        for table in tables:
            if table in SKIP_TABLES:
                continue
            dst_con.execute(f'INSERT INTO main."{table}" SELECT * FROM old."{table}"')
            kept += dst_con.execute(f'SELECT COUNT(*) FROM main."{table}"').fetchone()[0]
            dst_con.commit()
        dst_con.execute("DETACH DATABASE old")
        dst_con.execute("PRAGMA journal_mode=WAL")
        dst_con.execute("PRAGMA synchronous=NORMAL")
        dst_con.commit()
        check = dst_con.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"rebuilt database failed quick_check: {check}")
    finally:
        dst_con.close()

    return {"tables": tables, "kept_rows": kept, "size": dst.stat().st_size}


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
            "info: would rebuild opencode db without event/event_sequence rows",
            file=sys.stderr,
        )
        return 0

    if db_is_busy(db_path):
        print(
            "warning: opencode db is busy; event prune deferred",
            file=sys.stderr,
        )
        return 0

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    rebuilt = db_path.with_name(f"opencode.db.rebuilt-{stamp}")
    backup = db_path.with_name(f"opencode.db.pre-prune-{stamp}")
    try:
        result = rebuild_without_events(db_path, rebuilt)
        # Swap atomically relative to readers that reopen the path.
        db_path.replace(backup)
        for side in (
            db_path.with_name("opencode.db-wal"),
            db_path.with_name("opencode.db-shm"),
        ):
            if side.exists():
                side.unlink()
        rebuilt.replace(db_path)
        # Drop the pre-prune copy once the new file is in place; reclaiming disk
        # is the point of this maintenance.
        backup.unlink()
    except Exception:
        if rebuilt.exists():
            rebuilt.unlink()
        raise

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
