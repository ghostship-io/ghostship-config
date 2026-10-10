import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


retention = load("t3code_retention", "packages/t3code/retention.py")
opencode_prune = load("t3code_opencode_prune", "packages/t3code/opencode-db-prune.py")


def ts(days_ago: int) -> str:
    moment = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc) - retention.DAY * days_ago
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def thread(**patch) -> retention.ThreadRow:
    base = dict(
        thread_id="t1",
        title="demo",
        created_at=ts(30),
        updated_at=ts(30),
        settled_at=ts(30),
        archived_at=None,
        deleted_at=None,
        pinned_at=None,
        latest_user_message_at=ts(30),
        worktree_path=None,
        has_active_turn=False,
    )
    base.update(patch)
    return retention.ThreadRow(**base)


class RetentionSelection(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)

    def test_archives_settled_threads_older_than_seven_days(self):
        rows = [
            thread(thread_id="old", settled_at=ts(8)),
            thread(thread_id="fresh", settled_at=ts(2)),
            thread(thread_id="unsettled", settled_at=None, updated_at=ts(40)),
            thread(thread_id="pinned", settled_at=ts(40), pinned_at=ts(1)),
            thread(thread_id="active", settled_at=ts(40), has_active_turn=True),
            thread(thread_id="archived", settled_at=ts(40), archived_at=ts(1)),
        ]
        selected = retention.select_archive_candidates(rows, now=self.now, after_days=7)
        self.assertEqual([row.thread_id for row in selected], ["old"])

    def test_deletes_threads_with_activity_older_than_180_days(self):
        rows = [
            thread(
                thread_id="ancient",
                created_at=ts(200),
                updated_at=ts(200),
                settled_at=ts(200),
                latest_user_message_at=ts(200),
            ),
            thread(
                thread_id="recentish",
                created_at=ts(200),
                updated_at=ts(10),
                settled_at=ts(200),
                latest_user_message_at=ts(10),
            ),
            thread(
                thread_id="pinned",
                created_at=ts(200),
                updated_at=ts(200),
                settled_at=ts(200),
                latest_user_message_at=ts(200),
                pinned_at=ts(1),
            ),
        ]
        selected = retention.select_delete_candidates(rows, now=self.now, after_days=180)
        self.assertEqual([row.thread_id for row in selected], ["ancient"])


class WorktreeCleanup(unittest.TestCase):
    def test_removes_worktree_only_when_no_active_thread_keeps_it(self):
        root = Path("/home/t3code/.t3/worktrees")
        unique = root / "repo/unique"
        shared = root / "repo/shared"
        rows = [
            thread(
                thread_id="archiving",
                worktree_path=str(unique),
                settled_at=ts(10),
            ),
            thread(
                thread_id="already",
                worktree_path=str(root / "repo/old"),
                settled_at=ts(20),
                archived_at=ts(5),
            ),
            thread(
                thread_id="share-a",
                worktree_path=str(shared),
                settled_at=ts(10),
            ),
            thread(
                thread_id="share-active",
                worktree_path=str(shared),
                settled_at=None,
                archived_at=None,
            ),
        ]
        selected = retention.select_archive_worktrees(
            rows,
            archived_thread_ids={"archiving", "already", "share-a"},
            worktrees_root=root,
        )
        self.assertEqual(
            set(selected),
            {unique, root / "repo/old"},
        )

    def test_remove_worktree_refuses_paths_outside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "worktrees"
            root.mkdir()
            outside = Path(directory) / "other"
            outside.mkdir()
            with self.assertRaises(ValueError):
                retention.remove_worktree(outside, worktrees_root=root, dry_run=True)

    def test_remove_worktree_deletes_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "worktrees"
            target = root / "repo" / "leaf"
            target.mkdir(parents=True)
            (target / "file").write_text("x")
            self.assertTrue(
                retention.remove_worktree(target, worktrees_root=root, dry_run=False)
            )
            self.assertFalse(target.exists())


class LogPlanning(unittest.TestCase):
    def test_rotates_oversized_container_logs_and_deletes_aged_backups(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            big = root / "t3code-server.service.log"
            big.write_bytes(b"x" * (retention.DEFAULT_LOG_MAX_BYTES + 1))
            old = root / "t3code-server.service.log.old"
            old.write_text("old")
            aged = now.timestamp() - (retention.DEFAULT_LOG_KEEP_DAYS + 1) * 86400
            import os

            os.utime(old, (aged, aged))
            actions = retention.plan_container_log_actions(
                [big, old], now=now
            )
            self.assertEqual(
                {(action.path.name, action.action) for action in actions},
                {
                    ("t3code-server.service.log", "rotate"),
                    ("t3code-server.service.log.old", "delete"),
                },
            )

    def test_keeps_recent_trace_rotations_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = []
            for index in range(1, 9):
                path = root / f"server.trace.ndjson.{index}"
                path.write_text(str(index))
                import os

                os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
                files.append(path)
            live = root / "server.trace.ndjson"
            live.write_text("live")
            files.append(live)
            actions = retention.plan_trace_log_actions(files, keep=5)
            deleted = {action.path.name for action in actions if action.action == "delete"}
            self.assertEqual(
                deleted,
                {
                    "server.trace.ndjson.1",
                    "server.trace.ndjson.2",
                    "server.trace.ndjson.3",
                },
            )


class OpenCodePrune(unittest.TestCase):
    def test_should_prune_by_event_rows_or_bytes(self):
        metrics = {
            "tables": ["event", "message"],
            "event_rows": 50,
            "event_bytes": 100,
        }
        self.assertFalse(
            opencode_prune.should_prune(metrics, event_bytes=1000, event_rows=100)
        )
        metrics["event_rows"] = 100
        self.assertTrue(
            opencode_prune.should_prune(metrics, event_bytes=1000, event_rows=100)
        )
        metrics["event_rows"] = 1
        metrics["event_bytes"] = 1000
        self.assertTrue(
            opencode_prune.should_prune(metrics, event_bytes=1000, event_rows=100)
        )

    def test_rebuild_keeps_projected_rows_and_clears_events(self):
        with tempfile.TemporaryDirectory() as directory:
            src = Path(directory) / "opencode.db"
            dst = Path(directory) / "opencode.db.new"
            import sqlite3

            con = sqlite3.connect(src)
            con.executescript(
                """
                CREATE TABLE event (id TEXT PRIMARY KEY, aggregate_id TEXT, seq INTEGER, type TEXT, data TEXT);
                CREATE TABLE event_sequence (aggregate_id TEXT PRIMARY KEY, seq INTEGER, owner_id TEXT);
                CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT);
                CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, data TEXT);
                INSERT INTO event VALUES ('e1','s1',1,'message.updated.1','{}');
                INSERT INTO event_sequence VALUES ('s1',1,'owner');
                INSERT INTO session VALUES ('s1','hello');
                INSERT INTO message VALUES ('m1','s1','body');
                """
            )
            con.close()
            result = opencode_prune.rebuild_without_events(src, dst)
            check = sqlite3.connect(dst)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM event").fetchone()[0], 0)
            self.assertEqual(
                check.execute("SELECT COUNT(*) FROM event_sequence").fetchone()[0], 0
            )
            self.assertEqual(check.execute("SELECT COUNT(*) FROM session").fetchone()[0], 1)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM message").fetchone()[0], 1)
            self.assertEqual(check.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertGreater(result["kept_rows"], 0)
            check.close()


class RetentionSource(unittest.TestCase):
    def test_systemd_unit_is_wired(self):
        source = (
            Path(__file__).resolve().parents[1] / "modules/self-hosted/t3code.nix"
        ).read_text()
        self.assertIn("t3code-retention.service", source)
        self.assertIn("t3code-retention.timer", source)
        self.assertIn("packages/t3code/retention.py", source)
        self.assertIn("unset NO_COLOR", source)

    def test_retention_bundles_the_prune_sibling(self):
        # retention.py imports opencode-db-prune.py as a sibling, so the wrapper
        # must run it from a directory that contains both, never as a lone store
        # file where the sibling is absent.
        source = (
            Path(__file__).resolve().parents[1] / "modules/self-hosted/t3code.nix"
        ).read_text()
        self.assertIn("t3code-retention-tools", source)
        self.assertIn("$out/opencode-db-prune.py", source)
        self.assertIn("${t3codeRetentionTools}/retention.py", source)
        self.assertNotIn("python3 ${../../packages/t3code/retention.py}", source)


if __name__ == "__main__":
    unittest.main()
