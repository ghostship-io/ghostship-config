"""Periodic T3 Code retention: logs, settled-thread archive, and old-thread delete.

Runs inside the t3code container as a oneshot systemd timer. It:

1. Rotates and deletes oversized or stale operational logs (container, T3
   provider/server traces, OpenCode).
2. Rebuilds OpenCode's unbounded SQLite event log when it crosses thresholds.
3. Archives settled, unpinned threads older than seven days through T3's
   orchestration API (`thread.archive`), then removes that thread's worktree
   when no active thread still references the path.
4. Deletes unpinned threads whose latest activity is older than 180 days
   (`thread.delete`), which also triggers T3's worktree-on-delete cleanup.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

DAY = timedelta(days=1)
MIB = 1024**2

DEFAULT_ARCHIVE_AFTER_DAYS = 7
DEFAULT_DELETE_AFTER_DAYS = 180
DEFAULT_LOG_MAX_BYTES = 50 * MIB
DEFAULT_LOG_KEEP_DAYS = 14
DEFAULT_TRACE_KEEP = 5
DEFAULT_PROVIDER_ROTATION_KEEP = 2
DEFAULT_API = "http://127.0.0.1:3774"


@dataclass(frozen=True)
class ThreadRow:
    thread_id: str
    title: str | None
    created_at: str | None
    updated_at: str | None
    settled_at: str | None
    archived_at: str | None
    deleted_at: str | None
    pinned_at: str | None
    latest_user_message_at: str | None
    worktree_path: str | None
    has_active_turn: bool = False


@dataclass(frozen=True)
class LogAction:
    path: Path
    action: str  # rotate | delete


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def latest_activity(thread: ThreadRow) -> datetime | None:
    times = [
        parse_time(thread.latest_user_message_at),
        parse_time(thread.updated_at),
        parse_time(thread.settled_at),
        parse_time(thread.archived_at),
        parse_time(thread.created_at),
    ]
    present = [item for item in times if item is not None]
    return max(present) if present else None


def select_archive_candidates(
    threads: list[ThreadRow],
    *,
    now: datetime,
    after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
) -> list[ThreadRow]:
    cutoff = now - after_days * DAY
    selected: list[ThreadRow] = []
    for thread in threads:
        if thread.deleted_at or thread.archived_at or thread.pinned_at:
            continue
        if thread.has_active_turn:
            continue
        settled = parse_time(thread.settled_at)
        if settled is None or settled > cutoff:
            continue
        selected.append(thread)
    return selected


def select_delete_candidates(
    threads: list[ThreadRow],
    *,
    now: datetime,
    after_days: int = DEFAULT_DELETE_AFTER_DAYS,
) -> list[ThreadRow]:
    cutoff = now - after_days * DAY
    selected: list[ThreadRow] = []
    for thread in threads:
        if thread.deleted_at or thread.pinned_at:
            continue
        if thread.has_active_turn:
            continue
        activity = latest_activity(thread)
        if activity is None or activity > cutoff:
            continue
        selected.append(thread)
    return selected


def normalize_worktree_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    text = str(path).strip()
    if not text:
        return None
    return Path(text).expanduser()


def worktree_is_under_root(path: Path, worktrees_root: Path) -> bool:
    try:
        resolved = path.resolve()
        root = worktrees_root.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def active_worktree_refs(threads: list[ThreadRow]) -> dict[Path, set[str]]:
    """Map worktree path -> thread ids that still keep the checkout alive."""
    refs: dict[Path, set[str]] = defaultdict(set)
    for thread in threads:
        if thread.deleted_at or thread.archived_at:
            continue
        path = normalize_worktree_path(thread.worktree_path)
        if path is None:
            continue
        refs[path].add(thread.thread_id)
    return refs


def select_archive_worktrees(
    threads: list[ThreadRow],
    *,
    archived_thread_ids: set[str],
    worktrees_root: Path,
) -> list[Path]:
    """Worktrees that become unused once the given threads are archived.

    A path is removed only when every non-deleted thread that still points at it
    is archived (or is in this archive batch). Active/unsettled threads keep it.
    """
    pretend = [
        replace(thread, archived_at=thread.archived_at or "pending")
        if thread.thread_id in archived_thread_ids
        else thread
        for thread in threads
        if not thread.deleted_at
    ]
    kept = active_worktree_refs(pretend)
    selected: list[Path] = []
    seen: set[Path] = set()
    for thread in threads:
        if thread.thread_id not in archived_thread_ids and not thread.archived_at:
            continue
        if thread.deleted_at:
            continue
        path = normalize_worktree_path(thread.worktree_path)
        if path is None or path in seen:
            continue
        if not worktree_is_under_root(path, worktrees_root):
            continue
        if path in kept:
            continue
        seen.add(path)
        selected.append(path)
    return selected


def remove_worktree(path: Path, *, worktrees_root: Path, dry_run: bool = False) -> bool:
    """Remove a T3 worktree directory. Returns True when removal was attempted."""
    if not worktree_is_under_root(path, worktrees_root):
        raise ValueError(f"refusing to remove worktree outside {worktrees_root}: {path}")
    if not path.exists():
        print(f"info: worktree already absent {path}", file=sys.stderr)
        return False
    print(f"info: remove worktree {path}", file=sys.stderr)
    if dry_run:
        return True

    removed = False
    common = subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        capture_output=True,
        text=True,
    )
    if common.returncode == 0:
        common_dir = Path(common.stdout.strip())
        main = common_dir.parent if common_dir.name == ".git" else common_dir
        result = subprocess.run(
            ["git", "-C", str(main), "worktree", "remove", "--force", str(path)],
            capture_output=True,
            text=True,
        )
        removed = result.returncode == 0 and not path.exists()
        if not removed:
            print(
                f"warning: git worktree remove failed for {path}: {result.stderr.strip()}",
                file=sys.stderr,
            )

    if path.exists():
        shutil.rmtree(path)
        removed = True
        if common.returncode == 0:
            main = Path(common.stdout.strip())
            main = main.parent if main.name == ".git" else main
            subprocess.run(
                ["git", "-C", str(main), "worktree", "prune"],
                capture_output=True,
                text=True,
            )
    return removed


def plan_container_log_actions(
    files: list[Path],
    *,
    now: datetime,
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
    keep_days: int = DEFAULT_LOG_KEEP_DAYS,
) -> list[LogAction]:
    """Rotate oversized active logs; delete aged `.old`/backup siblings."""
    cutoff = now - keep_days * DAY
    actions: list[LogAction] = []
    for path in files:
        if not path.is_file():
            continue
        name = path.name
        if name.endswith(".old") or name.endswith(".pre-prune"):
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                actions.append(LogAction(path, "delete"))
            continue
        if path.suffix == ".log" and path.stat().st_size >= max_bytes:
            actions.append(LogAction(path, "rotate"))
    return actions


def plan_trace_log_actions(
    files: list[Path],
    *,
    keep: int = DEFAULT_TRACE_KEEP,
) -> list[LogAction]:
    """Keep the live trace plus the newest `keep` rotated numbered files."""
    live = [path for path in files if path.name == "server.trace.ndjson"]
    rotated = sorted(
        (
            path
            for path in files
            if path.name.startswith("server.trace.ndjson.")
            and path.name.split(".")[-1].isdigit()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    actions = [LogAction(path, "delete") for path in rotated[keep:]]
    for path in live:
        if path.stat().st_size >= DEFAULT_LOG_MAX_BYTES:
            actions.append(LogAction(path, "rotate"))
    return actions


def plan_provider_log_actions(
    files: list[Path],
    *,
    now: datetime,
    rotation_keep: int = DEFAULT_PROVIDER_ROTATION_KEEP,
    keep_days: int = DEFAULT_LOG_KEEP_DAYS,
) -> list[LogAction]:
    """Keep current provider logs and a few rotations; drop aged extras."""
    cutoff = now - keep_days * DAY
    by_stem: dict[str, list[Path]] = {}
    actions: list[LogAction] = []
    for path in files:
        if not path.is_file():
            continue
        name = path.name
        if ".log." in name:
            stem, _, suffix = name.rpartition(".log.")
            if not suffix.isdigit():
                continue
            by_stem.setdefault(stem, []).append(path)
        elif name.endswith(".log") and path.stat().st_size >= DEFAULT_LOG_MAX_BYTES:
            actions.append(LogAction(path, "rotate"))
    for paths in by_stem.values():
        ordered = sorted(
            paths,
            key=lambda path: int(path.name.rsplit(".", 1)[-1]),
        )
        for path in ordered[rotation_keep:]:
            actions.append(LogAction(path, "delete"))
        for path in ordered[:rotation_keep]:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            # Numbered rotations older than keep_days go even within the keep window
            # when the provider is long gone.
            if mtime < cutoff and int(path.name.rsplit(".", 1)[-1]) > 1:
                actions.append(LogAction(path, "delete"))
    # Deduplicate while preserving order.
    seen: set[Path] = set()
    unique: list[LogAction] = []
    for action in actions:
        if action.path in seen:
            continue
        seen.add(action.path)
        unique.append(action)
    return unique


def apply_log_action(action: LogAction, *, dry_run: bool) -> None:
    path = action.path
    if action.action == "delete":
        print(f"info: delete log {path}", file=sys.stderr)
        if not dry_run:
            path.unlink(missing_ok=True)
        return
    if action.action == "rotate":
        backup = path.with_suffix(path.suffix + ".old")
        print(f"info: rotate log {path}", file=sys.stderr)
        if dry_run:
            return
        if backup.exists():
            backup.unlink()
        path.replace(backup)
        path.write_text("")
        # Keep only one rotated sibling; aged .old files are removed later.
        return
    raise ValueError(f"unknown log action {action.action}")


def load_threads(db_path: Path) -> list[ThreadRow]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        active = {
            row["thread_id"]
            for row in con.execute(
                """
                SELECT DISTINCT turn.thread_id AS thread_id
                FROM projection_turns AS turn
                JOIN projection_threads AS thread USING (thread_id)
                WHERE thread.deleted_at IS NULL
                  AND turn.completed_at IS NULL
                  AND turn.state IN ('running', 'pending')
                """
            )
        }
        rows = con.execute(
            """
            SELECT thread_id, title, created_at, updated_at, settled_at, archived_at,
                   deleted_at, pinned_at, latest_user_message_at, worktree_path
            FROM projection_threads
            """
        )
        threads: list[ThreadRow] = []
        for row in rows:
            threads.append(
                ThreadRow(
                    thread_id=row["thread_id"],
                    title=row["title"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    settled_at=row["settled_at"],
                    archived_at=row["archived_at"],
                    deleted_at=row["deleted_at"],
                    pinned_at=row["pinned_at"],
                    latest_user_message_at=row["latest_user_message_at"],
                    worktree_path=row["worktree_path"],
                    has_active_turn=row["thread_id"] in active,
                )
            )
        return threads
    finally:
        con.close()


def issue_token(t3_bin: str, base_dir: Path, ttl: str = "30m") -> str:
    result = subprocess.run(
        [
            t3_bin,
            "auth",
            "session",
            "issue",
            "--token-only",
            "--ttl",
            ttl,
            "--label",
            "t3code-retention",
            "--base-dir",
            str(base_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    token = result.stdout.strip()
    if not token:
        raise RuntimeError("t3 auth session issue returned an empty token")
    return token


def dispatch_command(
    api_base: str,
    token: str,
    command: dict,
    *,
    timeout: float = 30.0,
) -> dict:
    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/api/orchestration/dispatch",
        data=json.dumps(command).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"dispatch {command.get('type')} failed: HTTP {exc.code}: {detail}") from exc


def archive_thread(api_base: str, token: str, thread_id: str) -> dict:
    return dispatch_command(
        api_base,
        token,
        {
            "type": "thread.archive",
            "commandId": str(uuid.uuid4()),
            "threadId": thread_id,
        },
    )


def delete_thread(api_base: str, token: str, thread_id: str) -> dict:
    return dispatch_command(
        api_base,
        token,
        {
            "type": "thread.delete",
            "commandId": str(uuid.uuid4()),
            "threadId": thread_id,
        },
    )


def load_opencode_prune():
    path = Path(__file__).with_name("opencode-db-prune.py")
    spec = importlib.util.spec_from_file_location("opencode_db_prune", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_storage_cleanup_settings(settings_path: Path, *, dry_run: bool) -> bool:
    """Fill missing storageCleanup keys; leave existing values alone."""
    defaults = {
        "worktreeAfterDays": 7,
        "worktreeOnMerge": True,
        "worktreeOnDelete": True,
        "worktreeUnchanged": True,
        "browserArtifactsAfterDays": 7,
        "logsAfterDays": 7,
    }
    if not settings_path.is_file():
        return False
    data = json.loads(settings_path.read_text())
    current = data.get("storageCleanup")
    if not isinstance(current, dict):
        current = {}
    changed = False
    merged = dict(current)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
            changed = True
    if not changed:
        return False
    print(f"info: fill missing storageCleanup keys in {settings_path}", file=sys.stderr)
    if dry_run:
        return True
    data["storageCleanup"] = merged
    temporary = settings_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.chmod(settings_path.stat().st_mode)
    temporary.replace(settings_path)
    return True


def collect_log_actions(home: Path, now: datetime) -> list[LogAction]:
    actions: list[LogAction] = []
    container_logs = home / ".t3code-container" / "logs"
    if container_logs.is_dir():
        actions.extend(
            plan_container_log_actions(
                sorted(container_logs.glob("*.log*")),
                now=now,
            )
        )
    userdata_logs = home / ".t3" / "userdata" / "logs"
    if userdata_logs.is_dir():
        actions.extend(
            plan_trace_log_actions(sorted(userdata_logs.glob("server.trace.ndjson*")))
        )
        provider = userdata_logs / "provider"
        if provider.is_dir():
            actions.extend(
                plan_provider_log_actions(sorted(provider.glob("events.*.log*")), now=now)
            )
    opencode_log = home / ".local" / "share" / "opencode" / "log" / "opencode.log"
    if opencode_log.is_file():
        actions.extend(plan_container_log_actions([opencode_log], now=now))
    return actions


def run(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser()
    t3_home = Path(args.t3_home).expanduser() if args.t3_home else home / ".t3"
    db_path = t3_home / "userdata" / "state.sqlite"
    settings_path = t3_home / "userdata" / "settings.json"
    now = datetime.now(timezone.utc)
    status = 0

    ensure_storage_cleanup_settings(settings_path, dry_run=args.dry_run)

    for action in collect_log_actions(home, now):
        try:
            apply_log_action(action, dry_run=args.dry_run)
        except OSError as exc:
            print(f"warning: log action failed for {action.path}: {exc}", file=sys.stderr)
            status = 1

    try:
        prune = load_opencode_prune()
        opencode_status = prune.prune(
            prune.default_db_path() if args.opencode_db is None else Path(args.opencode_db),
            dry_run=args.dry_run,
            log_path=None if args.opencode_db is not None else prune.default_log_path(),
        )
        if opencode_status != 0:
            status = opencode_status
    except Exception as exc:
        print(f"warning: opencode db prune failed: {exc}", file=sys.stderr)
        status = 1

    if not db_path.is_file():
        print(f"info: state db absent at {db_path}; skipping thread retention", file=sys.stderr)
        return status

    threads = load_threads(db_path)
    worktrees_root = t3_home / "worktrees"
    archive = select_archive_candidates(
        threads, now=now, after_days=args.archive_after_days
    )
    delete = select_delete_candidates(
        threads, now=now, after_days=args.delete_after_days
    )
    # Prefer delete over archive when both match.
    delete_ids = {thread.thread_id for thread in delete}
    archive = [thread for thread in archive if thread.thread_id not in delete_ids]
    already_archived_ids = {
        thread.thread_id
        for thread in threads
        if thread.archived_at and not thread.deleted_at
    }
    archive_ids = {thread.thread_id for thread in archive}
    worktrees = select_archive_worktrees(
        threads,
        archived_thread_ids=already_archived_ids | archive_ids,
        worktrees_root=worktrees_root,
    )

    print(
        "info: retention candidates "
        f"archive={len(archive)} delete={len(delete)} "
        f"worktrees={len(worktrees)}",
        file=sys.stderr,
    )

    if args.dry_run:
        for thread in archive[:20]:
            print(
                f"info: would archive {thread.thread_id} settled_at={thread.settled_at}",
                file=sys.stderr,
            )
        for thread in delete[:20]:
            print(
                f"info: would delete {thread.thread_id} activity={latest_activity(thread)}",
                file=sys.stderr,
            )
        for path in worktrees[:20]:
            print(f"info: would remove worktree {path}", file=sys.stderr)
        return status

    if archive or delete:
        token = issue_token(args.t3_bin, t3_home)
        archived_ok: set[str] = set()
        for thread in archive:
            try:
                result = archive_thread(args.api, token, thread.thread_id)
                print(
                    f"info: archived {thread.thread_id} sequence={result.get('sequence')}",
                    file=sys.stderr,
                )
                archived_ok.add(thread.thread_id)
                time.sleep(0.05)
            except Exception as exc:
                print(
                    f"warning: archive failed for {thread.thread_id}: {exc}",
                    file=sys.stderr,
                )
                status = 1

        for thread in delete:
            try:
                result = delete_thread(args.api, token, thread.thread_id)
                print(
                    f"info: deleted {thread.thread_id} sequence={result.get('sequence')}",
                    file=sys.stderr,
                )
                time.sleep(0.05)
            except Exception as exc:
                print(
                    f"warning: delete failed for {thread.thread_id}: {exc}",
                    file=sys.stderr,
                )
                status = 1

        # Only treat successful archives as archived for worktree eligibility.
        worktrees = select_archive_worktrees(
            threads,
            archived_thread_ids=already_archived_ids | archived_ok,
            worktrees_root=worktrees_root,
        )
    elif not worktrees:
        return status

    for path in worktrees:
        try:
            remove_worktree(path, worktrees_root=worktrees_root, dry_run=False)
        except Exception as exc:
            print(f"warning: worktree remove failed for {path}: {exc}", file=sys.stderr)
            status = 1

    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=os.environ.get("HOME", str(Path.home())))
    parser.add_argument("--t3-home", default=os.environ.get("T3CODE_HOME"))
    parser.add_argument("--t3-bin", default=os.environ.get("T3_BIN", "t3"))
    parser.add_argument("--api", default=os.environ.get("T3CODE_API", DEFAULT_API))
    parser.add_argument("--archive-after-days", type=int, default=DEFAULT_ARCHIVE_AFTER_DAYS)
    parser.add_argument("--delete-after-days", type=int, default=DEFAULT_DELETE_AFTER_DAYS)
    parser.add_argument("--opencode-db", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
