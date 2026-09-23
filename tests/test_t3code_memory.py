import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from test_config import load

watchdog = load("t3code_memory", "packages/t3code/memory-watchdog.py")
process_guard = load("t3code_process_guard", "packages/t3code/process-memory-guard.py")


class MemoryWatchdog(unittest.TestCase):
    def sample(self, **patch):
        return dict(pid=10, time=1000, age=3600, anon=9 * watchdog.GIB,
                    current=12 * watchdog.GIB, pressure=0, **patch)

    def test_requires_sustained_samples_and_resets_after_recovery(self):
        sample = self.sample()
        state = {}
        for expected in (False, False, True):
            state, recover = watchdog.evaluate(sample, state)
            self.assertEqual(recover, expected)
            sample['time'] += 60
        sample['anon'] = watchdog.GIB
        state, recover = watchdog.evaluate(sample, state)
        self.assertFalse(recover)
        self.assertEqual(state['count'], 0)

    def test_cache_alone_does_not_restart(self):
        sample = self.sample()
        sample.update(anon=watchdog.GIB, current=22 * watchdog.GIB)
        state, recover = watchdog.evaluate(sample, {'pid': 10, 'time': 940, 'count': 10})
        self.assertFalse(recover)
        self.assertEqual(state['count'], 0)
        sample['pressure'] = 15
        _, recover = watchdog.evaluate(sample, {'pid': 10, 'time': 940, 'count': 2})
        self.assertTrue(recover)

    def test_cooldown_process_change_and_sample_gap(self):
        for patch in ({'age': 100}, {'pid': 11}, {'time': 1060}, {'time': 1500}):
            sample = self.sample()
            sample.update(patch)
            _, recover = watchdog.evaluate(sample, {'pid': 10, 'time': 940, 'count': 5})
            self.assertFalse(recover)


class ProcessMemoryGuard(unittest.TestCase):
    def sample(self, pid=22, rss=None, start_time=100):
        return {
            "pid": pid,
            "rss": process_guard.PROCESS_RSS_LIMIT if rss is None else rss,
            "start_time": start_time,
        }

    def test_selects_only_oversized_non_main_process(self):
        samples = [
            self.sample(pid=10, rss=16 * process_guard.GIB),
            self.sample(pid=22, rss=11 * process_guard.GIB),
            self.sample(pid=23, rss=14 * process_guard.GIB),
        ]
        self.assertEqual(
            process_guard.select_offender(samples, main_pid=10)["pid"], 23
        )
        self.assertIsNone(
            process_guard.select_offender(samples[:2], main_pid=10)
        )

    def test_terminates_then_kills_same_process_after_grace(self):
        candidate = self.sample()
        state, action = process_guard.evaluate(candidate, {}, 50)
        self.assertEqual(action, process_guard.signal.SIGTERM)
        state, action = process_guard.evaluate(candidate, state, 69)
        self.assertIsNone(action)
        state, action = process_guard.evaluate(candidate, state, 70)
        self.assertEqual(action, process_guard.signal.SIGKILL)
        _, action = process_guard.evaluate(candidate, state, 100)
        self.assertIsNone(action)

    def test_pid_reuse_restarts_term_grace_and_recovery_clears_state(self):
        previous = {"pid": 22, "start_time": 100, "term_sent_at": 10, "signal": "TERM"}
        state, action = process_guard.evaluate(self.sample(start_time=101), previous, 11)
        self.assertEqual(action, process_guard.signal.SIGTERM)
        self.assertEqual(state["term_sent_at"], 11)
        self.assertEqual(process_guard.evaluate(None, state, 12), ({}, None))

    def test_samples_only_processes_in_server_cgroup_and_excludes_main_pid(self):
        service_path = "/system.slice/t3code-server.service"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cgroup = root / "sys/fs/cgroup" / service_path.lstrip("/")
            cgroup.mkdir(parents=True)
            (cgroup / "cgroup.procs").write_text("10\n22\n23\n")
            proc = root / "proc"
            for pid, path, rss_kib in (
                (10, service_path, 16 * 1024 * 1024),
                (22, service_path + "/command.scope", 13 * 1024 * 1024),
                (23, "/system.slice/other.service", 15 * 1024 * 1024),
            ):
                process = proc / str(pid)
                process.mkdir(parents=True)
                (process / "cgroup").write_text(f"0::{path}\n")
                (process / "status").write_text(f"Name:\ttest\nVmRSS:\t{rss_kib} kB\n")
                (process / "stat").write_text(
                    f"{pid} (test) S " + "0 " * 18 + "100 0\n"
                )

            samples = process_guard.sample_processes(
                10,
                service_path,
                cgroup_root=root / "sys/fs/cgroup",
                proc_root=proc,
            )

        self.assertEqual([sample["pid"] for sample in samples], [22])
        self.assertEqual(samples[0]["start_time"], 100)


class IdleGuard(unittest.TestCase):
    def setUp(self):
        source = (
            Path(__file__).resolve().parents[1]
            / 'packages/t3code/activity-probe/probe-v1-sqlite.cjs'
        ).read_text()
        self.query = re.search(r'`(SELECT count\(\*\) AS active FROM projection_turns.*?)`', source, re.DOTALL)[1]
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE projection_threads(thread_id TEXT, deleted_at TEXT, latest_user_message_at TEXT);
            CREATE TABLE projection_turns(
                thread_id TEXT, turn_id TEXT, state TEXT, requested_at TEXT, completed_at TEXT
            );
            INSERT INTO projection_threads VALUES ('a', NULL, NULL);
            INSERT INTO projection_turns VALUES ('a', NULL, 'pending', '2026-09-01', NULL);
        ''')

    def idle(self):
        return all(row[0] == 0 for row in self.db.execute(self.query, (10,)))

    def test_recent_pending_blocks_until_superseded(self):
        now = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        self.db.execute(
            "INSERT INTO projection_turns VALUES "
            "('a', NULL, 'pending', "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 minute'), NULL)"
        )
        self.assertFalse(self.idle())
        self.db.execute(
            f"INSERT INTO projection_turns VALUES ('a', 'new', 'completed', {now}, {now})"
        )
        self.assertTrue(self.idle())
        self.db.execute(
            "UPDATE projection_turns SET state='running', completed_at=NULL WHERE turn_id='new'"
        )
        self.assertFalse(self.idle())

    def test_completed_turns_and_old_pending_starts_are_ignored(self):
        self.db.execute(
            "INSERT INTO projection_turns VALUES "
            "('a', 'finished', 'running', '2026-09-23T03:00:00Z', '2026-09-23T03:01:00Z')"
        )
        self.assertTrue(self.idle())

    def test_completed_pending_start_is_ignored(self):
        self.db.execute(
            "INSERT INTO projection_turns VALUES "
            "('a', NULL, 'pending', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
        self.assertTrue(self.idle())

    def test_deleted_thread_is_ignored(self):
        self.db.execute(
            "INSERT INTO projection_turns VALUES "
            "('a', NULL, 'pending', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NULL)"
        )
        self.db.execute("UPDATE projection_threads SET deleted_at='2026-09-03'")
        self.assertTrue(self.idle())

    def test_recent_message_protects_dispatch_window(self):
        self.db.execute('DELETE FROM projection_turns')
        self.assertTrue(self.idle())
        self.db.execute("UPDATE projection_threads SET latest_user_message_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
        self.assertFalse(self.idle())
