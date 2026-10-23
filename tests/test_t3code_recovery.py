"""Host recovery policy, exercised without touching a real service."""
import contextlib
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages/t3code/recovery/controller.py"


def down(**changes):
    value = dict(container=dict(id="fixture-container", started_at="fixture-start", running=True, pid=42),
                 host_state="active", server_state="empty", management="available", native=False, proxy=False, app=changes.get("native", False))
    value.update(changes)
    return value


def proposal(action="start_server", **changes):
    value = dict(action=action, diagnosis="Synthetic diagnosis", confidence="high", evidence=["Synthetic evidence"])
    value.update(changes)
    return value


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("recovery_under_test", SOURCE)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = {key: str(self.root / key) for key in ("state_dir", "runtime_dir", "home_dir", "deployment_state_dir")}
        self.config.update({key: key for key in ("podman_bin", "systemctl_bin", "nsenter_bin", "curl_bin", "probe_bin")})
        self.config.update(advisor_unit="fixture-advisor.service", owner_approval="approved recovery policy")
        self.now = 0
        self.wall = 100000
        self.sample = down()
        self.mutations = []
        self.advisors = 0
        self.answer = proposal()
        self.messages = []
        test = self

        class FakeHost:
            def probe(self):
                return copy.deepcopy(test.sample)

            @contextlib.contextmanager
            def gates(self, observation):
                yield not test.blocked

            def advise(self, diagnostics, keep_running):
                test.advisors += 1
                # The attempt and budget must already be durable at launch.
                saved = json.loads((Path(test.config["state_dir"]) / "state.json").read_text())
                test.assertTrue(saved["attempted"])
                test.assertEqual(len(saved["launches"]), test.advisors)
                return test.answer

            def mutate(self, action, observation):
                test.mutations.append(action)
                return True

            def notify(self, message):
                test.messages.append(message)

            def maintenance_held(self, observation):
                return test.blocked

            def verify_health(self):
                return True

        self.blocked = False
        self.host = FakeHost()
        self.new_controller()

    def new_controller(self):
        self.controller = self.m.Controller(self.config, host=self.host, clock=lambda: self.now,
                                            wall=lambda: self.wall, sleep=lambda _: None)

    def tick(self, second):
        self.now = second
        self.wall = 100000 + second
        self.controller.tick()

    def window(self, start=0):
        for second in range(start, start + 301, 30):
            self.tick(second)

    def test_static_http_with_stalled_authenticated_app_is_advice_only(self):
        self.sample = down(native=True, proxy=True, app=False, server_state="populated")
        self.answer = proposal("restart_proxy")
        self.assertEqual(self.m.health(self.sample), "down")
        self.assertEqual(self.m.eligible_actions(self.sample), set())
        self.window()
        self.assertEqual(self.advisors, 1)
        self.assertEqual(self.mutations, [])
        saved = json.loads((self.root / "state_dir/state.json").read_text())
        self.assertEqual(saved["runs"][-1]["outcome"], "ineligible-proposal")

    def test_stalled_app_advice_is_retained_without_mutation(self):
        self.sample = down(native=True, proxy=True, app=False, server_state="populated")
        self.answer = proposal("none")
        self.window()
        self.assertEqual((self.advisors, self.mutations), (1, []))
        saved = json.loads((self.root / "state_dir/state.json").read_text())
        self.assertEqual(saved["runs"][-1]["outcome"], "advice-only")

    def test_proxy_down_requires_authenticated_app_health(self):
        self.sample = down(native=True, proxy=False, app=True, server_state="populated")
        self.answer = proposal("restart_proxy")
        self.window()
        self.assertEqual(self.mutations, ["restart_proxy"])
        self.assertEqual(self.m.eligible_actions(dict(self.sample, app=False)), set())
        self.assertEqual(self.m.health(dict(self.sample, app=None)), "unknown")
        missing = dict(self.sample)
        del missing["app"]
        self.assertEqual(self.m.health(missing), "unknown")

    def test_authenticated_probe_keeps_bearer_off_argv_and_classifies_failures(self):
        host = self.m.Host(self.config)
        session = Path(self.config["home_dir"]) / ".t3code-container/access/session.json"
        session.parent.mkdir(parents=True)
        session.write_text(json.dumps({"token": "synthetic-bearer"}))
        cases = [((0, '{"authenticated":true}\n200'), True),
                 ((28, ""), False), ((0, "unavailable\n503"), False),
                 ((0, '{"authenticated":false}\n200'), None),
                 ((0, "unauthorized\n401"), None), ((0, "forbidden\n403"), None),
                 ((0, "<html>static fallback</html>\n200"), None),
                 ((0, '{"authenticated":true}\n302'), None), ((1, ""), None)]
        for result, expected in cases:
            with self.subTest(result=result), patch.object(host, "command", return_value=result) as command:
                self.assertIs(host.authenticated_app(42), expected)
                args, kwargs = command.call_args
                self.assertNotIn("synthetic-bearer", str(args))
                self.assertIn("/api/auth/session", args[0][-1])
                self.assertIn("--net", args[0])
                self.assertEqual(kwargs["input_data"], b"Authorization: Bearer synthetic-bearer\n")
                self.assertGreater(kwargs["timeout"], 5)
        for token in ("bad\nheader", "", None, "x" * 4001):
            session.write_text(json.dumps({"token": token}))
            with patch.object(host, "command") as command:
                self.assertIsNone(host.authenticated_app(42))
                command.assert_not_called()
        session.unlink()
        with patch.object(host, "command") as command:
            self.assertIsNone(host.authenticated_app(42))
            command.assert_not_called()

    def test_probe_distinguishes_stalled_app_from_failed_proxy(self):
        host = self.m.Host(self.config)
        container = down()["container"]
        for app, proxy, expected in ((False, True, "app-db-stalled"), (True, False, "proxy-down")):
            with patch.object(host, "inspect", return_value=container), \
                 patch.object(host, "command", return_value=(0, "active")), \
                 patch.object(host, "http", side_effect=[True, proxy]), \
                 patch.object(host, "authenticated_app", return_value=app), \
                 patch.object(host, "management", return_value="available"), \
                 patch.object(host, "server_cgroup", return_value="populated"), \
                 patch.object(host, "metrics", return_value={"status": "known"}):
                observed = host.probe()
            self.assertEqual(observed["failure"], expected)
            self.assertEqual(self.m.health(observed), "down")
            self.assertEqual(self.m.eligible_actions(observed), {"restart_proxy"} if app else set())
            if not app:
                with patch.object(host, "command") as command:
                    for action in self.m.ACTIONS:
                        self.assertFalse(host.mutate(action, observed))
                    command.assert_not_called()

    def test_299_seconds_never_launches(self):
        for second in list(range(0, 271, 30)) + [299]:
            self.tick(second)
        self.assertEqual(self.advisors, 0)

    def test_300_seconds_launches_once_and_mutates_once(self):
        self.window()
        for second in range(330, 1000, 30):
            self.tick(second)
        self.assertEqual((self.advisors, self.mutations), (1, ["start_server"]))

    def test_up_unknown_gap_and_identity_reset_down_evidence(self):
        for mode in ("up", "unknown", "gap", "identity", "eligibility"):
            with self.subTest(mode=mode):
                self.new_controller()
                self.sample = down()
                for second in range(0, 271, 30):
                    self.tick(second)
                if mode == "up":
                    self.sample.update(native=True, proxy=True, app=True)
                elif mode == "unknown":
                    self.sample["native"] = None
                elif mode == "identity":
                    self.sample["container"]["started_at"] = "another-start"
                elif mode == "eligibility":
                    self.sample["management"] = "unavailable"
                self.tick(316 if mode == "gap" else 300)
                self.sample = down()
                self.tick(330)
                self.assertEqual(self.advisors, 0)

    def test_each_eligibility_row_and_live_or_ambiguous_server(self):
        rows = [
            (down(), {"start_server"}),
            (down(management="unavailable"), {"restart_container"}),
            (down(management="unknown"), set()),
            (down(server_state="populated"), set()),
            (down(server_state="unknown"), set()),
            (down(native=True, server_state="populated"), {"restart_proxy"}),
            (down(container=dict(id="stopped", started_at="never", running=False, pid=0),
                  host_state="failed", management="unavailable", server_state="unknown"), {"start_container"}),
        ]
        for sample, expected in rows:
            with self.subTest(sample=sample):
                self.assertEqual(self.m.eligible_actions(sample), expected)
        for host_state in ("activating", "deactivating", "reloading", "unknown"):
            sample = down(host_state=host_state)
            self.assertEqual(self.m.eligible_actions(sample), set())

    def test_transitioning_host_never_counts(self):
        self.sample["host_state"] = "activating"
        self.window()
        self.assertEqual(self.advisors, 0)

    def test_locks_and_holds_reset_window(self):
        for second in range(0, 271, 30):
            self.tick(second)
        self.blocked = True
        self.tick(300)
        self.blocked = False
        self.tick(330)
        self.assertEqual(self.advisors, 0)

    def test_post_advisor_health_identity_and_gates_refuse(self):
        for mode in ("health", "identity", "gate", "server"):
            with self.subTest(mode=mode):
                self.root.joinpath("state_dir/state.json").unlink(missing_ok=True)
                self.advisors = 0
                self.new_controller()
                self.sample = down()
                self.blocked = False
                original = self.host.advise

                def advise(*args):
                    result = original(*args)
                    if mode == "health":
                        self.sample.update(native=True, proxy=True, app=True)
                    elif mode == "identity":
                        self.sample["container"]["id"] = "replacement"
                    elif mode == "server":
                        self.sample["server_state"] = "populated"
                    else:
                        self.blocked = True
                    return result

                with patch.object(self.host, "advise", side_effect=advise):
                    self.window()
                self.assertEqual(self.mutations, [])

    def test_proposal_cannot_choose_an_ineligible_action_or_shell(self):
        for action in ("restart_container", "restart_proxy", "start_container", "touch /tmp/untrusted"):
            self.assertFalse(self.m.validate_proposal(proposal(action)) and action in self.m.eligible_actions(down()))
        self.answer = proposal("restart_container")
        self.window()
        self.assertEqual(self.mutations, [])

    def test_strict_proposal_schema(self):
        invalid = [proposal(extra="command"), proposal(diagnosis="x" * 2001), proposal(confidence="certain"),
                   proposal(evidence=["x"] * 11), proposal(evidence=["x" * 201]), proposal(evidence="text"),
                   proposal(action=[]), proposal(diagnosis=None), {}, [], True]
        for value in invalid:
            with self.subTest(value=str(value)[:80]):
                self.assertFalse(self.m.validate_proposal(value))
        self.assertTrue(self.m.validate_proposal(proposal("none")))
        schema = json.loads((SOURCE.parent / "schema.json").read_text())
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(proposal()))
        self.assertEqual(set(schema["properties"]["action"]["enum"]), self.m.ACTIONS)

    def test_invalid_proposal_consumes_attempt_without_mutation(self):
        self.answer = proposal(extra="untrusted")
        self.window()
        self.assertEqual((self.advisors, self.mutations), (1, []))
        self.tick(330)
        self.assertEqual(self.advisors, 1)

    def test_restart_retains_attempt_and_budget_but_loses_continuity(self):
        for second in range(0, 271, 30):
            self.tick(second)
        self.new_controller()
        self.tick(300)
        self.assertEqual(self.advisors, 0)
        self.window(330)
        self.new_controller()
        self.window(660)
        self.assertEqual(self.advisors, 1)

    def healthy(self, start, duration=600):
        self.sample.update(native=True, proxy=True, app=True)
        for second in range(start, start + duration + 1, 30):
            self.tick(second)
        self.sample = down()

    def test_rearm_requires_600_seconds_of_uninterrupted_health(self):
        self.window()
        self.healthy(330, 570)
        self.window(930)
        self.assertEqual(self.advisors, 1)
        self.healthy(1260)
        self.window(1890)
        self.assertEqual(self.advisors, 2)

    def test_healthy_gap_and_unknown_cannot_rearm(self):
        self.window()
        self.healthy(330, 300)
        self.sample["native"] = None
        self.tick(660)
        self.healthy(690, 300)
        self.window(1020)
        self.assertEqual(self.advisors, 1)
        self.healthy(1350, 300)
        self.healthy(1696, 300)
        self.window(2026)
        self.assertEqual(self.advisors, 1)

    def test_healthy_container_replacement_restarts_rearm_evidence(self):
        self.window()
        self.healthy(330, 570)
        self.sample = down(native=True, proxy=True)
        self.sample["container"]["id"] = "replacement"
        self.tick(930)
        self.assertTrue(self.controller.state["attempted"])

    def test_successful_mutation_is_refused_if_server_cgroup_became_live(self):
        host = self.m.Host(self.config)
        with patch.object(host, "inspect", return_value=down()["container"]), \
             patch.object(host, "management", return_value="unavailable"), \
             patch.object(host, "server_cgroup", return_value="populated"), \
             patch.object(host, "command") as command:
            self.assertFalse(host.mutate("restart_container", down(management="unavailable")))
            command.assert_not_called()

    def test_three_launch_rolling_budget_survives_restart(self):
        self.window()
        for start in (330, 1290, 2250):
            self.healthy(start)
            self.new_controller()
            self.window(start + 630)
        self.assertEqual(self.advisors, 3)
        self.window(86430)
        self.assertEqual(self.advisors, 4)

    def test_crash_after_attempt_write_cannot_relaunch(self):
        with patch.object(self.host, "advise", side_effect=RuntimeError("synthetic crash")):
            self.window()
        saved = json.loads((self.root / "state_dir/state.json").read_text())
        self.assertTrue(saved["attempted"])
        self.assertEqual(len(saved["launches"]), 1)
        self.new_controller()
        self.window(330)
        self.assertEqual(self.advisors, 0)

    def test_corrupt_state_fails_closed(self):
        path = self.root / "state_dir/state.json"
        path.write_text("broken")
        with self.assertRaises(ValueError):
            self.new_controller()

    def test_audit_retains_only_last_twenty_bounded_runs(self):
        for index in range(25):
            self.controller.audit({"outcome": "x" * 100000, "index": index})
        runs = json.loads((self.root / "state_dir/state.json").read_text())["runs"]
        self.assertEqual(len(runs), 20)
        self.assertEqual(runs[0]["index"], 5)
        self.assertLess(len(json.dumps(runs)), 65536)

    def test_host_probes_namespace_using_state_pid_and_both_endpoints(self):
        host = self.m.Host(self.config)
        commands = []

        def command(argv, timeout=5):
            commands.append(argv)
            if "inspect" in argv:
                value = [dict(Id="fixture", State=dict(Pid=42, ConmonPid=999, Running=True, StartedAt="start"))]
                return 0, json.dumps(value)
            if "is-active" in argv:
                return 0, "active\n"
            if "show" in argv:
                return 0, "LoadState=loaded\nActiveState=inactive\n"
            return 0, ""

        with patch.object(host, "command", side_effect=command), patch.object(host, "server_cgroup", return_value="empty"), \
             patch.object(host, "metrics", return_value={"status": "known"}):
            observed = host.probe()
        curls = [argv for argv in commands if self.config["curl_bin"] in argv]
        self.assertEqual(len(curls), 4)
        for argv in curls:
            self.assertEqual(argv[:5], [self.config["nsenter_bin"], "--target", "42", "--net", "--"])
            self.assertIn("5", argv)
        self.assertTrue(observed["native"] and observed["proxy"])
        self.assertTrue(any(":3774/.well-known/t3/environment" in argv[-1] for argv in curls))
        self.assertTrue(any(":3773/" in argv[-1] for argv in curls))

    def test_cgroup_empty_includes_descendants_and_ambiguous_is_unknown(self):
        host = self.m.Host(self.config)
        proc = self.root / "proc"
        cgroups = self.root / "cgroup"
        (proc / "42").mkdir(parents=True)
        (proc / "42/cgroup").write_text("0::/fixture\n")
        service = cgroups / "fixture/system.slice/t3code-server.service"
        service.mkdir(parents=True)
        (cgroups / "fixture/cgroup.events").write_text("populated 1\nfrozen 0\n")
        (service / "cgroup.events").write_text("populated 0\nfrozen 0\n")
        with patch.object(self.m, "PROC_ROOT", proc), patch.object(self.m, "CGROUP_ROOT", cgroups):
            self.assertEqual(host.server_cgroup(42), "empty")
            (service / "cgroup.events").write_text("populated 1\nfrozen 0\n")
            self.assertEqual(host.server_cgroup(42), "populated")
            (service / "cgroup.events").write_text("unknown\n")
            self.assertEqual(host.server_cgroup(42), "unknown")
            (proc / "42/cgroup").write_text("0::/../../outside\n")
            self.assertEqual(host.server_cgroup(42), "unknown")

    def test_real_gate_files_and_flocks(self):
        host = self.m.Host(self.config)
        observed = down(container=dict(id="stopped", started_at="never", running=False, pid=0), host_state="inactive")
        for key in ("home_dir", "runtime_dir", "deployment_state_dir"):
            Path(self.config[key]).mkdir(parents=True, exist_ok=True)
        tool = Path(self.config["home_dir"]) / self.m.TOOL_LOCK
        tool.parent.mkdir(parents=True)
        for path in (Path(self.config["state_dir"]) / "hold", Path(self.config["runtime_dir"]) / "hold",
                     Path(self.config["deployment_state_dir"]) / "restart.pending"):
            path.touch()
            with host.gates(observed) as allowed:
                self.assertFalse(allowed)
            path.unlink()
        for lock in (tool, Path(self.config["deployment_state_dir"]) / "deploy.lock"):
            with lock.open("w") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with host.gates(observed) as allowed:
                    self.assertFalse(allowed)
        with patch.object(host, "maintenance_held", return_value=False):
            with host.gates(down()) as allowed:
                self.assertTrue(allowed)
                with (Path(self.config["deployment_state_dir"]) / "deploy.lock").open() as other:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_untrusted_proposal_file_is_bounded_regular_and_no_symlink(self):
        output = self.root / "proposal.json"
        output.write_text(json.dumps(proposal()))
        self.assertEqual(self.m.read_proposal(output), proposal())
        for content in ("x" * 16385, '{"action":"none","action":"start_server"}', '[]'):
            output.write_text(content)
            self.assertIsNone(self.m.read_proposal(output))
        output.unlink()
        output.symlink_to(self.root / "missing")
        self.assertIsNone(self.m.read_proposal(output))
        output.unlink()
        os.mkfifo(output)
        self.assertIsNone(self.m.read_proposal(output))

    def test_advisor_timeout_and_health_return_stop_static_unit(self):
        for healthy in (False, True):
            with self.subTest(healthy=healthy):
                host = self.m.Host(self.config)
                clock = [0]
                commands = []

                def command(argv, timeout=5):
                    commands.append(argv)
                    if "show" in argv:
                        active = any("start" in previous for previous in commands)
                        return 0, ("ActiveState=active\nSubState=running\nResult=success\n" if active
                                   else "ActiveState=inactive\nSubState=dead\nResult=success\n")
                    return 0, ""

                def sleep(seconds):
                    clock[0] += seconds

                with patch.object(host, "command", side_effect=command), \
                     patch.object(self.m.time, "monotonic", side_effect=lambda: clock[0]), \
                     patch.object(self.m.time, "sleep", side_effect=sleep), patch.object(os, "chown"), patch.object(os, "fchown"):
                    self.assertIsNone(host.advise({"synthetic": "diagnostics"}, lambda: not healthy))
                self.assertIn([self.config["systemctl_bin"], "stop", self.config["advisor_unit"]], commands)
                self.assertLessEqual(clock[0], 480)
                self.assertTrue((self.root / "runtime_dir/advisor/diagnostics.json").exists())

    def test_advisor_rejects_stale_output_and_excess_diagnostics(self):
        host = self.m.Host(self.config)
        output = self.root / "runtime_dir/advisor/proposal.json"
        output.parent.mkdir(parents=True)
        output.write_text(json.dumps(proposal()))
        with patch.object(host, "command", return_value=(0, "ActiveState=inactive\nSubState=dead\nResult=success\n")), \
             patch.object(os, "chown"), patch.object(os, "fchown"):
            self.assertIsNone(host.advise({}, lambda: True))
            self.assertEqual(output.read_bytes(), b"")
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertIsNone(host.advise({"data": "x" * 65537}, lambda: True))

    def test_mutation_commands_are_fixed_and_container_ledger_has_pre_and_post(self):
        host = self.m.Host(self.config)
        commands = []
        ledger = self.root / "ledger.jsonl"
        with patch.object(self.m, "RESTART_LEDGER", ledger), \
             patch.object(host, "command", side_effect=lambda argv, timeout=5: (commands.append(argv) or (0, ""))), \
             patch.object(host, "server_cgroup", return_value="empty"):
            for action in ("start_server", "restart_proxy", "start_container", "restart_container"):
                sample = down()
                if action == "restart_proxy":
                    sample.update(native=True, app=True, server_state="populated")
                elif action == "start_container":
                    sample.update(container=dict(id="stopped", started_at="never", running=False, pid=0), host_state="inactive")
                elif action == "restart_container":
                    sample["management"] = "unavailable"
                with patch.object(host, "inspect", return_value=sample["container"]), \
                     patch.object(host, "management", return_value=sample["management"]):
                    self.assertTrue(host.mutate(action, sample))
        self.assertEqual(commands, [
            [self.config["podman_bin"], "exec", "t3code", "systemctl", "start", "t3code-server.service"],
            [self.config["podman_bin"], "exec", "t3code", "systemctl", "restart", "t3code-access-proxy.service"],
            [self.config["systemctl_bin"], "start", "podman-t3code.service"],
            [self.config["systemctl_bin"], "restart", "podman-t3code.service"],
        ])
        entries = [json.loads(line) for line in ledger.read_text().splitlines()]
        self.assertTrue(all(entry["mode"] == "auto-recovery" for entry in entries))
        self.assertTrue(all(entry["reference"] == self.config["owner_approval"] for entry in entries))
        self.assertTrue(all("pre" in entry and "post" in entry for entry in entries))

    def test_mutation_refuses_missing_approval_and_arbitrary_action(self):
        host = self.m.Host(dict(self.config, owner_approval=""))
        with patch.object(host, "command") as command:
            self.assertFalse(host.mutate("restart_container", down()))
            self.assertFalse(host.mutate("arbitrary command", down()))
            command.assert_not_called()

    def test_authenticated_live_app_prevents_server_and_container_repair(self):
        # Contradictory static/cgroup observations cannot override DB liveness.
        for management in ("available", "unavailable"):
            self.assertEqual(self.m.eligible_actions(down(app=True, management=management)), set())

    def test_command_transports_bounded_header_over_stdin(self):
        host = self.m.Host(self.config)
        rc, output = host.command(["python3", "-c", "import sys; print(len(sys.stdin.buffer.read()))"],
                                  input_data=b"Authorization: Bearer synthetic\n")
        self.assertEqual(rc, 0)
        self.assertEqual(output.strip(), "32")

    def test_command_timeout_and_output_cap(self):
        host = self.m.Host(self.config)
        rc, output = host.command(["python3", "-c", "import time; time.sleep(10)"], timeout=0.05)
        self.assertIsNone(rc)
        rc, output = host.command(["python3", "-c", "print('x' * 1000000)"], timeout=5)
        self.assertIsNone(rc)
        self.assertLessEqual(len(output), 65536)

    def test_cgroup_init_scope_is_not_the_server_parent(self):
        host = self.m.Host(self.config)
        proc = self.root / "proc"
        cgroups = self.root / "cgroup"
        (proc / "42").mkdir(parents=True)
        (proc / "42/cgroup").write_text("0::/fixture/init.scope\n")
        (cgroups / "fixture/init.scope").mkdir(parents=True)
        (cgroups / "fixture/system.slice").mkdir()
        for path in (cgroups / "fixture", cgroups / "fixture/init.scope"):
            (path / "cgroup.events").write_text("populated 1\nfrozen 0\n")
        with patch.object(self.m, "PROC_ROOT", proc), patch.object(self.m, "CGROUP_ROOT", cgroups):
            self.assertEqual(host.server_cgroup(42), "empty")

    def test_host_mutator_independently_refuses_live_or_ambiguous_restart(self):
        host = self.m.Host(self.config)
        with patch.object(host, "command") as command, patch.object(self.m, "RESTART_LEDGER", self.root / "ledger.jsonl"):
            for state in ("populated", "unknown"):
                for action in ("restart_container", "start_server", "start_container"):
                    self.assertFalse(host.mutate(action, down(server_state=state, management="unavailable")))
            command.assert_not_called()

    def test_each_allowed_repair_runs_through_controller(self):
        rows = [
            (down(), "start_server"),
            (down(management="unavailable"), "restart_container"),
            (down(native=True, server_state="populated"), "restart_proxy"),
            (down(container=dict(id="stopped", started_at="never", running=False, pid=0),
                  host_state="inactive"), "start_container"),
        ]
        for sample, action in rows:
            with self.subTest(action=action):
                self.root.joinpath("state_dir/state.json").unlink(missing_ok=True)
                self.advisors = 0
                self.mutations.clear()
                self.new_controller()
                self.sample, self.answer = sample, proposal(action)
                self.window()
                self.assertEqual(self.mutations, [action])

    def test_audit_counts_runs_instead_of_mutation_phases(self):
        self.window()
        saved = json.loads((self.root / "state_dir/state.json").read_text())
        self.assertEqual(len(saved["runs"]), 1)
        self.assertEqual(saved["runs"][0]["outcome"], "repaired")

    def test_runtime_namespace_maintenance_hold_blocks_gate(self):
        host = self.m.Host(self.config)
        proc = self.root / "proc"
        hold = proc / "42/root/run/t3code-tool-update/hold"
        hold.parent.mkdir(parents=True)
        hold.touch()
        with patch.object(self.m, "PROC_ROOT", proc):
            with host.gates(down()) as allowed:
                self.assertFalse(allowed)

    def test_deploy_lock_is_held_through_mutation(self):
        real_host = self.m.Host(self.config)
        self.sample = down(container=dict(id="stopped", started_at="never", running=False, pid=0),
                           host_state="inactive")
        self.answer = proposal("start_container")

        def mutate(action, observation):
            lock = Path(self.config["deployment_state_dir"]) / "deploy.lock"
            with lock.open() as handle:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.mutations.append(action)
            return True

        with patch.object(self.host, "gates", side_effect=real_host.gates), \
             patch.object(self.host, "mutate", side_effect=mutate):
            self.window()
        self.assertEqual(self.mutations, ["start_container"])

    def test_hold_appearing_during_final_probe_refuses_mutation(self):
        original = self.host.probe
        calls = [0]

        def probe():
            calls[0] += 1
            if calls[0] == 12:  # Eleven samples, then the fresh post-advice probe.
                self.blocked = True
            return original()

        with patch.object(self.host, "probe", side_effect=probe):
            self.window()
        self.assertEqual(self.advisors, 1)
        self.assertEqual(self.mutations, [])

    def test_successful_exit_without_healthy_http_is_not_repaired(self):
        with patch.object(self.host, "verify_health", return_value=False):
            self.window()
        saved = json.loads((self.root / "state_dir/state.json").read_text())
        self.assertEqual(saved["runs"][-1]["outcome"], "repair-unhealthy")
        self.assertTrue(self.messages)

    def test_advisor_output_file_exists_before_start_and_curl_deadline_has_slack(self):
        host = self.m.Host(self.config)
        started = []

        def command(argv, timeout=5):
            if "start" in argv:
                output = self.root / "runtime_dir/advisor/proposal.json"
                self.assertTrue(output.is_file())
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                started.append(True)
            if "show" in argv:
                return 0, "ActiveState=inactive\nResult=success\n"
            if self.config["curl_bin"] in argv:
                self.assertGreater(timeout, 5)
                return 28, "curl timeout"
            return 0, ""

        with patch.object(host, "command", side_effect=command), patch.object(os, "chown"), patch.object(os, "fchown"):
            host.advise({}, lambda: True)
            self.assertFalse(host.http(42, 3774))
        self.assertEqual(started, [True])

    def test_host_verifies_health_with_real_probe_result(self):
        host = self.m.Host(self.config)
        with patch.object(host, "probe", return_value=down()), patch.object(self.m.time, "sleep"), \
             patch.object(self.m.time, "monotonic", side_effect=range(0, 1000, 30)):
            self.assertFalse(host.verify_health())
        with patch.object(host, "probe", return_value=down(native=True, proxy=True)):
            self.assertTrue(host.verify_health())

    def metrics_fixture(self):
        proc, cgroups = self.root / "proc", self.root / "cgroups"
        paths = {
            "42/cgroup": "0::/fixture/init.scope\n",
            "sys/kernel/pid_max": "65536\n",
            "sys/kernel/threads-max": "131072\n",
            "loadavg": "0.0 0.0 0.0 2/400 1234\n",
            "meminfo": "MemTotal: 1000 kB\nMemAvailable: 600 kB\nSwapTotal: 100 kB\nSwapFree: 90 kB\n",
        }
        for name, contents in paths.items():
            path = proc / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        for root in (cgroups, cgroups / "fixture", cgroups / "fixture/init.scope",
                     cgroups / "fixture/system.slice/t3code-server.service"):
            root.mkdir(parents=True, exist_ok=True)
            for name, contents in {
                "cgroup.events": "populated 1\nfrozen 0\n",
                "pids.current": "16384\n", "pids.max": "32768\n", "pids.events": "max 7\n",
                "memory.current": "1048576\n", "memory.max": "max\n", "memory.high": "2097152\n",
                "memory.events": "low 0\nhigh 1\nmax 2\noom 3\noom_kill 4\noom_group_kill 0\n",
            }.items():
                (root / name).write_text(contents)
        return proc, cgroups

    def test_diagnostics_include_numeric_host_and_both_cgroup_limits_and_events(self):
        proc, cgroups = self.metrics_fixture()
        host = self.m.Host(self.config)
        with patch.object(self.m, "PROC_ROOT", proc), patch.object(self.m, "CGROUP_ROOT", cgroups):
            metrics = host.metrics(down())
        self.assertEqual(metrics["status"], "known")
        self.assertEqual(metrics["host"]["pid_max"], 65536)
        self.assertEqual(metrics["host"]["threads"], 400)
        self.assertEqual(metrics["host"]["memory_available_bytes"], 600 * 1024)
        for key in ("container", "server"):
            self.assertEqual(metrics[key]["pids_current"], 16384)
            self.assertEqual(metrics[key]["pids_max"], 32768)
            self.assertEqual(metrics[key]["pids_events"]["max"], 7)
            self.assertEqual(metrics[key]["memory_current"], 1048576)
            self.assertIsNone(metrics[key]["memory_max"])
            self.assertEqual(metrics[key]["memory_events"]["oom_kill"], 4)
        self.assertLess(len(json.dumps(metrics)), 65536)
        self.sample.update(server_state="populated", metrics=metrics)
        self.assertEqual(self.m.eligible_actions(self.sample), set())

    def test_unreadable_or_malformed_metrics_fail_closed(self):
        proc, cgroups = self.metrics_fixture()
        host = self.m.Host(self.config)
        for value in ("not-a-number", "-1", "9" * 10000):
            with self.subTest(value=value[:20]):
                (cgroups / "fixture/pids.current").write_text(value)
                with patch.object(self.m, "PROC_ROOT", proc), patch.object(self.m, "CGROUP_ROOT", cgroups):
                    metrics = host.metrics(down())
                self.assertEqual(metrics["status"], "unknown")
                sample = down(metrics=metrics)
                self.assertEqual(self.m.health(sample), "unknown")
                self.assertEqual(self.m.eligible_actions(sample), set())
        (cgroups / "fixture/pids.current").write_text("123\n")
        (cgroups / "fixture/pids.events").unlink()
        with patch.object(self.m, "PROC_ROOT", proc), patch.object(self.m, "CGROUP_ROOT", cgroups):
            self.assertEqual(host.metrics(down())["status"], "unknown")

    def test_absent_empty_server_cgroup_has_no_fabricated_metrics(self):
        proc, cgroups = self.metrics_fixture()
        server = cgroups / "fixture/system.slice/t3code-server.service"
        for path in server.iterdir():
            path.unlink()
        server.rmdir()
        host = self.m.Host(self.config)
        with patch.object(self.m, "PROC_ROOT", proc), patch.object(self.m, "CGROUP_ROOT", cgroups):
            metrics = host.metrics(down())
            self.assertEqual(host.server_cgroup(42), "empty")
        self.assertEqual(metrics["status"], "known")
        self.assertEqual(metrics["server"], {"status": "absent"})
        self.assertEqual(self.m.eligible_actions(down(metrics=metrics)), {"start_server"})

    def test_collected_metrics_reach_the_advisor_without_private_logs(self):
        proc, cgroups = self.metrics_fixture()
        host = self.m.Host(self.config)
        with patch.object(self.m, "PROC_ROOT", proc), patch.object(self.m, "CGROUP_ROOT", cgroups):
            self.sample["metrics"] = host.metrics(self.sample)
        original = self.host.advise

        def advise(diagnostics, keep_running):
            self.assertEqual(diagnostics["observation"]["metrics"]["container"]["pids_events"]["max"], 7)
            self.assertNotIn("cmdline", json.dumps(diagnostics))
            return original(diagnostics, keep_running)

        with patch.object(self.host, "advise", side_effect=advise):
            self.window()
        self.assertEqual(self.advisors, 1)

    def test_cli_once_calls_exactly_one_controller_tick(self):
        config = self.root / "config.json"
        config.write_text(json.dumps(self.config))
        with patch.object(self.m.os, "geteuid", return_value=0), patch.object(self.m, "Controller") as cls:
            self.assertEqual(self.m.main(["--config", str(config), "--once"]), 0)
            cls.return_value.tick.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
