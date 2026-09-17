import re
import sqlite3
import unittest
from pathlib import Path

from test_config import load

watchdog = load("t3code_memory", "packages/t3code/memory-watchdog.py")


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
        for patch in ({'age': 100}, {'pid': 11}, {'time': 1500}):
            sample = self.sample()
            sample.update(patch)
            _, recover = watchdog.evaluate(sample, {'pid': 10, 'time': 940, 'count': 5})
            self.assertFalse(recover)


class IdleGuard(unittest.TestCase):
    def setUp(self):
        source = (Path(__file__).resolve().parents[1] / 'modules/self-hosted/t3code.nix').read_text()
        self.query = re.search(r'`(SELECT count\(\*\) AS active FROM projection_turns.*?)`', source, re.S)[1]
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE projection_threads(thread_id TEXT, deleted_at TEXT, latest_user_message_at TEXT);
            CREATE TABLE projection_turns(thread_id TEXT, turn_id TEXT, state TEXT, requested_at TEXT);
            INSERT INTO projection_threads VALUES ('a', NULL, NULL);
            INSERT INTO projection_turns VALUES ('a', NULL, 'pending', '2026-09-01');
        ''')

    def idle(self):
        return all(row[0] == 0 for row in self.db.execute(self.query))

    def test_pending_blocks_until_superseded(self):
        self.assertFalse(self.idle())
        self.db.execute("INSERT INTO projection_turns VALUES ('a', 'new', 'completed', '2026-09-02')")
        self.assertTrue(self.idle())
        self.db.execute("UPDATE projection_turns SET state='running' WHERE turn_id='new'")
        self.assertFalse(self.idle())

    def test_deleted_thread_is_ignored(self):
        self.db.execute("UPDATE projection_threads SET deleted_at='2026-09-03'")
        self.assertTrue(self.idle())

    def test_recent_message_protects_dispatch_window(self):
        self.db.execute('DELETE FROM projection_turns')
        self.assertTrue(self.idle())
        self.db.execute("UPDATE projection_threads SET latest_user_message_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
        self.assertFalse(self.idle())
