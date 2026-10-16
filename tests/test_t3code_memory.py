import re
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_config import load

watchdog = load("t3code_memory", "packages/t3code/memory-watchdog.py")
process_guard = load("t3code_process_guard", "packages/t3code/process-memory-guard.py")


class MemoryWatchdog(unittest.TestCase):
    def test_memory_veto_is_immediate_and_includes_recent_reclaim(self):
        for sample in (
            {'anon': 9 * watchdog.GIB, 'pressure': 0},
            {'anon': watchdog.GIB, 'pressure': 0.01},
            {'anon': watchdog.GIB, 'pressure': 0, 'recent_pressure': 0.01},
        ):
            self.assertTrue(watchdog.blocks_restart(sample))
        self.assertFalse(watchdog.blocks_restart({'anon': watchdog.GIB, 'pressure': 0}))

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


class ServerMonitorPolicy(unittest.TestCase):
    def test_real_monitor_shell_never_restarts_for_pressure_or_unknown_memory(self):
        source = (Path(__file__).resolve().parents[1] / 'modules/self-hosted/t3code.nix').read_text()
        body = source.split('t3codeDaemonMonitor = pkgs.writeShellScriptBin "t3code-server-monitor" \'\'')[1].split("\n  '';", 1)[0]
        for mode, expected in [('pressure', False), ('unknown', False), ('late-pressure', False), ('clear', True), ('v2-busy', False)]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = root / 'state'
                state.mkdir()
                (state / 'server-monitor-web-failures').write_text('4\n')
                probe = root / 'memory-probe'
                probe.write_text('#!/bin/sh\n' + {
                    'pressure': 'echo pressure\n',
                    'unknown': 'exit 1\n',
                    'late-pressure': f'if [ -f "{root}/sampled" ]; then echo pressure; fi; touch "{root}/sampled"\n',
                    'clear': 'exit 0\n',
                    'v2-busy': 'exit 0\n',
                }[mode])
                probe.chmod(0o755)
                script = body.replace('${t3codeRuntimeEnv}', '')
                script = script.replace('${t3codeIdleCheck}', 'is_t3code_idle() { return 0; }')
                if mode == 'v2-busy':
                    (root / 'userdata').mkdir()
                    (root / 'userdata/statev2.sqlite').touch()
                    script = script.replace('is_t3code_idle() { return 0; }', 'is_t3code_idle() { return 2; }')
                script = script.replace('${t3codeProviderCheck}', 't3code_providers_healthy() { return 0; }')
                script = script.replace('${pkgs.python3}/bin/python3 ${../../packages/t3code/memory-watchdog.py}', str(probe))
                script = script.replace('${pkgs.util-linux}/bin/flock', 'true')
                script = script.replace('${t3codeToolLock}', str(root / 'lock'))
                script = script.replace('/run/t3code-tool-update', str(state))
                self.assertNotIn('${', script)
                # Run the repository's actual shell branches with controlled probes.
                prelude = f'''systemctl() {{
                  case "$1" in
                    is-active) return 0;;
                    show) echo 10;;
                    restart) touch "{root}/restarted";;
                  esac
                }}
                curl() {{ return 1; }}
                '''
                result = subprocess.run(['bash', '-c', prelude + script],
                    env={**os.environ, 'HOME': str(root), 'T3CODE_HOME': str(root)}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / 'restarted').exists(), expected)
                if mode == 'v2-busy':
                    log = (root / '.t3code-container/logs/t3code-server-monitor.log').read_text()
                    self.assertIn('activity is active or unknown; restart deferred', log)
                elif not expected:
                    self.assertFalse((state / 'server-monitor-web-failures').exists())


class ProcessMemoryGuard(unittest.TestCase):
    def fixture(self, root):
        service = process_guard.EXPECTED_CGROUP
        cgroup = root / 'cgroup' / service.lstrip('/')
        cgroup.mkdir(parents=True)
        # Replay the Oct 11 stall: 24 GiB high limit, ~20 GiB anonymous,
        # >10% full memory pressure, with tools individually below 12 GiB.
        for name, value in {
            'cgroup.procs': '10\n11\n22\n23\n',
            'memory.high': str(24 * process_guard.GIB),
            'memory.current': str(24 * process_guard.GIB + 1024),
            'memory.stat': f'anon {20 * process_guard.GIB}\n',
            'memory.pressure': 'full avg10=25.00 avg60=25.00 avg300=0.00 total=1\n',
        }.items():
            (cgroup / name).write_text(value)
        proc = root / 'proc'
        for pid, ppid, rss, args in [
            (10, 1, 1, ['node', '/tools/bin/t3', 'serve']),
            (11, 10, 1, ['/tools/lib/node_modules/@t3code/t3-linux-arm64/t3', 'serve']),
            (22, 11, 9, ['python', 'cad.py']),
            (23, 11, 8, ['python', 'cad2.py']),
        ]:
            process = proc / str(pid)
            process.mkdir(parents=True)
            (process / 'cgroup').write_text(f'0::{service}\n')
            (process / 'status').write_text(f'VmRSS:\t{rss * 1024 * 1024} kB\n')
            (process / 'stat').write_text(f'{pid} (test) S {ppid} ' + '0 ' * 17 + '100 0\n')
            (process / 'cmdline').write_bytes(('\0'.join(args) + '\0').encode())
            (process / 'oom_score_adj').write_text('0\n')
        return cgroup, proc

    def test_only_server_processes_keep_kernel_oom_immunity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, proc = self.fixture(root)
            # Tools inherit the protected native server's initial score.
            (proc / '22/oom_score_adj').write_text('-1000')
            process_guard.configure_oom_protection(10, process_guard.EXPECTED_CGROUP, root / 'cgroup', proc)
            for pid in (10, 11):
                self.assertEqual(int((proc / str(pid) / 'oom_score_adj').read_text()), -1000)
            for pid in (22, 23):
                self.assertEqual(int((proc / str(pid) / 'oom_score_adj').read_text()), 500)

    def test_native_server_is_protected_behind_node_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, proc = self.fixture(root)
            (proc / '11/status').write_text(f'VmRSS:\t{13 * 1024 * 1024} kB\n')
            samples = process_guard.sample_processes(
                10, process_guard.EXPECTED_CGROUP, root / 'cgroup', proc
            )
            self.assertNotIn(11, [sample['pid'] for sample in samples])

    def test_combined_pressure_stops_one_tool_and_recovers_without_server_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cgroup, proc = self.fixture(root)
            actions = []
            def send(pidfd, sig):
                actions.append((pidfd, sig))
            with patch.object(process_guard.os, 'pidfd_open', side_effect=lambda pid, _: pid), \
                 patch.object(process_guard.os, 'close'), \
                 patch.object(process_guard.signal, 'pidfd_send_signal', side_effect=send), \
                 patch.object(process_guard.time, 'monotonic', return_value=50):
                process_guard.run_guard(10, root / 'cgroup', proc, root / 'state.json')
                self.assertEqual(actions, [(22, process_guard.signal.SIGTERM)])
                # Recovery cancels escalation even if the tool is still live.
                (cgroup / 'memory.pressure').write_text('full avg10=0 avg60=0 total=1\n')
                process_guard.run_guard(10, root / 'cgroup', proc, root / 'state.json')
                self.assertEqual(actions, [(22, process_guard.signal.SIGTERM)])

    def test_pressure_guard_ignores_cache_missing_measurements_and_recovery_race(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cgroup, proc = self.fixture(root)
            self.assertTrue(process_guard.under_memory_pressure(root / 'cgroup', process_guard.EXPECTED_CGROUP))
            (cgroup / 'memory.stat').write_text(f'anon {process_guard.GIB}\n')
            self.assertFalse(process_guard.under_memory_pressure(root / 'cgroup', process_guard.EXPECTED_CGROUP))
            (cgroup / 'memory.high').write_text('max')
            self.assertFalse(process_guard.under_memory_pressure(root / 'cgroup', process_guard.EXPECTED_CGROUP))
            with patch.object(process_guard.os, 'pidfd_open', return_value=22), \
                 patch.object(process_guard.os, 'close'), \
                 patch.object(process_guard.signal, 'pidfd_send_signal') as send:
                sent, _ = process_guard.signal_process(
                    22, 100, 10, process_guard.EXPECTED_CGROUP,
                    process_guard.signal.SIGTERM, root / 'cgroup', proc
                )
                self.assertFalse(sent)
                send.assert_not_called()

    def test_signaling_rechecks_native_server_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, proc = self.fixture(root)
            (proc / '11/status').write_text(f'VmRSS:\t{13 * 1024 * 1024} kB\n')
            with patch.object(process_guard.os, 'pidfd_open', return_value=11), \
                 patch.object(process_guard.os, 'close'), \
                 patch.object(process_guard.signal, 'pidfd_send_signal') as send:
                sent, reason = process_guard.signal_process(
                    11, 100, 10, process_guard.EXPECTED_CGROUP,
                    process_guard.signal.SIGTERM, root / 'cgroup', proc
                )
                self.assertFalse(sent)
                self.assertEqual(reason, 'T3 server process is protected')
                send.assert_not_called()

    def test_pressure_guard_signals_a_real_disposable_child(self):
        child = subprocess.Popen(
            [sys.executable, '-c',
             "import time; data=bytearray(64*1024**2); print('ready',flush=True); time.sleep(60)"],
            stdout=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                cgroup, proc = self.fixture(root)
                (cgroup / 'cgroup.procs').write_text(f'10\n11\n{child.pid}\n')
                process = proc / str(child.pid)
                process.mkdir()
                (process / 'cgroup').write_text(f'0::{process_guard.EXPECTED_CGROUP}\n')
                (process / 'oom_score_adj').write_text('0')
                for name in ('stat', 'status', 'cmdline'):
                    (process / name).symlink_to(Path('/proc') / str(child.pid) / name)
                # Scale the selection floor, not the signaling path. The fixture
                # supplies pressure while real procfs supplies identity and RSS.
                with patch.object(process_guard, 'PRESSURE_RSS_FLOOR', 32 * 1024**2):
                    process_guard.run_guard(10, root / 'cgroup', proc, root / 'state.json')
                self.assertEqual(child.wait(timeout=5), -process_guard.signal.SIGTERM)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            child.stdout.close()

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
            CREATE TABLE projection_thread_sessions(thread_id TEXT, status TEXT, active_turn_id TEXT);
            CREATE TABLE projection_thread_activities(
                thread_id TEXT, kind TEXT, payload_json TEXT, created_at TEXT, sequence INTEGER
            );
            INSERT INTO projection_threads VALUES ('a', NULL, NULL);
            INSERT INTO projection_turns VALUES ('a', NULL, 'pending', '2026-09-01', NULL);
        ''')

    def idle(self):
        return all(row[0] == 0 for row in self.db.execute(self.query, (10, 10, 12)))

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

    def test_running_session_keeps_checkpointed_turn_active(self):
        # A mid-turn checkpoint stamps completed_at on a turn that is still
        # running; the provider session status is authoritative.
        self.db.execute('DELETE FROM projection_turns')
        self.db.execute(
            "INSERT INTO projection_turns VALUES "
            "('a', 'turn-1', 'running', "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-60 minutes'), "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-59 minutes'))"
        )
        self.db.execute(
            "INSERT INTO projection_thread_sessions VALUES ('a', 'running', 'turn-1')"
        )
        self.assertFalse(self.idle())
        self.db.execute(
            "UPDATE projection_thread_sessions SET status='ready' WHERE thread_id='a'"
        )
        self.assertTrue(self.idle())

    def test_live_session_blocks_without_a_turn_row(self):
        self.db.execute('DELETE FROM projection_turns')
        for status in ('starting', 'running'):
            self.db.execute('DELETE FROM projection_thread_sessions')
            self.db.execute(
                "INSERT INTO projection_thread_sessions VALUES ('a', ?, NULL)", (status,)
            )
            self.assertFalse(self.idle(), status)
        for status in ('ready', 'stopped', 'error'):
            self.db.execute('DELETE FROM projection_thread_sessions')
            self.db.execute(
                "INSERT INTO projection_thread_sessions VALUES ('a', ?, NULL)", (status,)
            )
            self.assertTrue(self.idle(), status)
