import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "apparmor_review", Path(__file__).resolve().parents[1] / "modules/self-hosted/apparmor-review.py")
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)
DAY = review.DAY
GOOD = {"healthy": True, "heartbeat": True, "reasons": [], "policy_hash": "hash1",
        "image": "image1", "profile": "ghostship-plex", "mode": "complain", "source": "/policy"}
CONFIG = {"containers": {"plex": {"profile": "ghostship-plex", "source": "/policy", "mode": "complain"}}}
MESSAGE = ('apparmor="ALLOWED" operation="open" profile="ghostship-plex" '
           'name="/private/token" requested_mask="r" denied_mask="r" '
           'args="secret" env="secret"')


def week():
    state = None
    for day in range(8):
        state = review.advance(state, GOOD, [], (day + 1) * DAY, True)
    return state


class Coverage(unittest.TestCase):
    def test_full_week_and_daily_samples(self):
        state = week()
        self.assertTrue(review.status(state, 8 * DAY)["ready"])
        state = None
        for minute in range(8):
            state = review.advance(state, GOOD, [], DAY + minute * 60, True)
        self.assertFalse(review.status(state, DAY + 7 * 60)["ready"])
        self.assertFalse(review.status(week(), 10 * DAY)["ready"])

    def test_daily_timer_jitter_does_not_discard_samples(self):
        state = None
        for day in range(9):
            stamp = (day + 1) * DAY + (120 if day % 2 == 0 else 0)
            state = review.advance(state, GOOD, [], stamp, True)
        self.assertTrue(review.status(state, stamp)["ready"])

    def test_seven_samples_not_seven_full_days(self):
        state = None
        for day in range(7):
            state = review.advance(state, GOOD, [], (day + 1) * DAY, True)
        self.assertFalse(review.status(state, 7 * DAY)["ready"])

    def test_gap_cannot_count_outage(self):
        state = review.advance(week(), GOOD, [], 10 * DAY, True)
        self.assertIsNone(state["coverage_start"])
        state = review.advance(state, GOOD, [], 11 * DAY, True)
        self.assertEqual(state["coverage_start"], 11 * DAY)
        self.assertFalse(review.status(state, 11 * DAY)["ready"])

    def test_health_and_audit_failures_reset(self):
        for reason in ("apparmor-disabled", "process-profile-mismatch", "loaded-mode-mismatch"):
            state = review.advance(week(), {**GOOD, "healthy": False, "reasons": [reason]}, [], 9 * DAY, True)
            self.assertIsNone(state["coverage_start"])
        for obs, audit in (({**GOOD, "heartbeat": False}, True), (GOOD, False)):
            state = review.advance(week(), obs, [], 9 * DAY, audit)
            self.assertIsNone(state["coverage_start"])

    def test_identity_changes_reset(self):
        for field in ("image", "policy_hash", "profile", "mode", "boot_id"):
            state = review.advance(week(), {**GOOD, field: "changed"}, [], 9 * DAY, True)
            self.assertEqual(state["last_policy_change"], 9 * DAY)
            self.assertEqual(state["coverage_start"], 9 * DAY)
            self.assertFalse(review.status(state, 9 * DAY)["ready"])

    def test_unrelated_profile_changes_keep_coverage(self):
        # Another profile changing renames the shared apparmor.d tree, not this policy.
        state = review.advance(week(), {**GOOD, "source": "/nix/store/other-apparmor.d/ghostship-plex"},
                               [], 9 * DAY, True)
        self.assertEqual(state["coverage_start"], DAY)
        self.assertTrue(review.status(state, 9 * DAY)["ready"])

    def test_clock_regression_resets(self):
        state = review.advance(week(), GOOD, [], 7 * DAY, True)
        self.assertIsNone(state["coverage_start"])

    def test_all_events_block_until_explicit_expected_review(self):
        event = review.parse_event(8 * DAY, MESSAGE, "ghostship-plex")
        state = review.advance(week(), GOOD, [event], 9 * DAY, True)
        self.assertFalse(review.status(state, 9 * DAY)["ready"])
        state["reviews"] = {event["id"]: {"classification": "legitimate-needs-policy"}}
        self.assertFalse(review.status(state, 9 * DAY)["ready"])
        state["reviews"][event["id"]]["classification"] = "expected-denial"
        self.assertTrue(review.status(state, 9 * DAY)["ready"])
        # A new image must never silently discard unreviewed evidence.
        state["reviews"] = {}
        state = review.advance(state, {**GOOD, "image": "new"}, [], 10 * DAY, True)
        self.assertIn(event["id"], state["events"])

    def test_initial_24h_events_are_not_discarded(self):
        event = review.parse_event(DAY - 100, MESSAGE, "ghostship-plex")
        state = review.advance(None, GOOD, [event], DAY, True)
        self.assertIn(event["id"], state["events"])


class Collection(unittest.TestCase):
    def test_parse_projection_and_exact_profile(self):
        event = review.parse_event(1, MESSAGE, "ghostship-plex")
        self.assertEqual(event["name"], "/private/token")
        self.assertNotIn("args", event)
        self.assertNotIn("env", event)
        self.assertIsNone(review.parse_event(1, MESSAGE, "ghostship-plex-extra"))
        child = MESSAGE.replace('profile="ghostship-plex"', 'profile="ghostship-plex//server"')
        self.assertEqual(review.parse_event(1, child, "ghostship-plex")["profile"],
                         "ghostship-plex//server")
        self.assertFalse(review.heartbeat_event(event))

    def test_only_observed_probe_excluded(self):
        message = ('apparmor="AUDIT" operation="open" profile="ghostship-plex" '
                   f'name="{review.HEARTBEAT_PATH}" requested_mask="r"')
        intentional = review.parse_event(100, message, "ghostship-plex")
        unrelated = review.parse_event(99, message, "ghostship-plex")
        with patch.object(review, "inspect_container", return_value=GOOD.copy()), \
                patch.object(review, "probe", return_value=intentional), \
                patch.object(review, "journal", return_value=[(99, message), (100, message)]), \
                patch.object(review.time, "time", return_value=101):
            state = review.collect(CONFIG, {}, 100)
        self.assertEqual(list(state["containers"]["plex"]["events"]), [unrelated["id"]])

    def test_successful_probe_requires_exact_event_in_window(self):
        message = ('apparmor="AUDIT" operation="open" profile="ghostship-plex" '
                   f'name="{review.HEARTBEAT_PATH}" requested_mask="r" comm="cat"')
        with patch.object(review.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
                patch.object(review, "vlogs", side_effect=[[], [(101, message)]]) as vlogs, \
                patch.object(review.time, "sleep"):
            event = review.probe("plex", "ghostship-plex", ["/bin/cat", review.HEARTBEAT_PATH])
        self.assertIn('(aa_profile:="ghostship-plex" OR aa_profile:"ghostship-plex//"*)', vlogs.call_args.args[0])
        self.assertTrue(review.heartbeat_event(event))
        self.assertTrue(review.heartbeat_event({**event, "apparmor": "ALLOWED", "denied_mask": "r"}))
        self.assertFalse(review.heartbeat_event({**event, "operation": "exec"}))
        self.assertFalse(review.heartbeat_event({**event, "name": "/somewhere/else"}))
        self.assertFalse(review.heartbeat_event({**event, "apparmor": "DENIED"}))

    def test_heartbeat_command_defaults_to_cat_and_resolves_entrypoint(self):
        self.assertEqual(review.heartbeat_command("plex", {}), ["/bin/cat", review.HEARTBEAT_PATH])
        with patch.object(review, "run", return_value="/nix/store/x-python3/bin/python3\n") as run:
            command = review.heartbeat_command("coordinator", {"heartbeat": ["@entrypoint", "-c", "pass"]})
        self.assertEqual(command, ["/nix/store/x-python3/bin/python3", "-c", "pass"])
        self.assertIn("coordinator", run.call_args.args[0])

    def test_probe_fails_closed(self):
        with patch.object(review.subprocess, "run", side_effect=subprocess.TimeoutExpired("probe", 2)):
            self.assertIsNone(review.probe("plex", "ghostship-plex", ["/bin/cat", review.HEARTBEAT_PATH]))

    def test_process_that_exits_mid_inspection_is_skipped_not_fatal(self):
        reads = {"/policy": b"policy", "/sys/module/apparmor/parameters/enabled": "Y",
                 review.HEARTBEAT_PATH: "boot1",
                 "/sys/kernel/security/apparmor/profiles": "ghostship-plex (complain)\n",
                 "/proc/10/attr/current": "ghostship-plex (complain)"}

        def read_text(path):
            if str(path) not in reads:
                raise FileNotFoundError(str(path))
            return reads[str(path)]
        with patch.object(review.Path, "read_bytes", lambda p: reads[str(p)]), \
                patch.object(review.Path, "read_text", read_text), \
                patch.object(review, "run", side_effect=[json.dumps({"image": "id", "running": True,
                                                                      "profile": "ghostship-plex"}),
                                                        "HPID\n10\n12\n", "lost 0\n"]):
            observation = review.inspect_container("plex", {**CONFIG["containers"]["plex"],
                                                            "processProfiles": ["ghostship-plex"],
                                                            "requiredProcessProfiles": ["ghostship-plex"]})
        self.assertNotIn("inspection-failed", observation["reasons"])
        self.assertEqual([p["pid"] for p in observation["processes"]], [10])

    def test_all_host_pids_checked_without_env_inspection(self):
        reads = {"/policy": b"policy", "/sys/module/apparmor/parameters/enabled": "Y",
                 review.HEARTBEAT_PATH: "boot1",
                 "/sys/kernel/security/apparmor/profiles": "ghostship-plex (complain)\n",
                 "/proc/10/attr/current": "ghostship-plex (complain)",
                 "/proc/11/attr/current": "unconfined"}
        with patch.object(review.Path, "read_bytes", lambda p: reads[str(p)]), \
                patch.object(review.Path, "read_text", lambda p: reads[str(p)]), \
                patch.object(review, "run", side_effect=[json.dumps({"image": "id", "running": True,
                                                                      "profile": "ghostship-plex"}),
                                                        "HPID\n10\n11\n", "lost 0\n"]) as run:
            observation = review.inspect_container("plex", CONFIG["containers"]["plex"])
        self.assertFalse(observation["healthy"])
        self.assertIn("process-profile-mismatch", observation["reasons"])
        self.assertEqual(len(observation["processes"]), 2)
        self.assertNotIn(".Config", str(run.call_args_list))

    def test_mixed_policy_requires_each_domain_mode(self):
        """Catches an enforced domain silently loaded in complain mode."""
        config = {"profile": "ghostship-plex", "mode": "complain", "source": "/policy",
                  "processProfiles": ["ghostship-plex", "ghostship-plex//server"],
                  "processModes": {"ghostship-plex//server": "enforce"}}
        def observe(server_mode):
            reads = {"/policy": b"policy", "/sys/module/apparmor/parameters/enabled": "Y",
                     review.HEARTBEAT_PATH: "boot1",
                     "/sys/kernel/security/apparmor/profiles":
                         f"ghostship-plex (complain)\nghostship-plex//server ({server_mode})\n",
                     "/proc/10/attr/current": "ghostship-plex (complain)",
                     "/proc/11/attr/current": f"ghostship-plex//server ({server_mode})"}
            with patch.object(review.Path, "read_bytes", lambda p: reads[str(p)]), \
                    patch.object(review.Path, "read_text", lambda p: reads[str(p)]), \
                    patch.object(review, "run", side_effect=[json.dumps({"image": "id", "running": True,
                                                                          "profile": "ghostship-plex"}),
                                                            "HPID\n10\n11\n", "lost 0\n"]):
                return review.inspect_container("plex", config)
        self.assertTrue(observe("enforce")["healthy"])
        self.assertIn("loaded-mode-mismatch", observe("complain")["reasons"])

    def test_transient_tools_profile_is_allowed_but_not_required_running(self):
        config = {"profile": "ghostship-ntfy", "mode": "complain", "source": "/policy",
                  "processProfiles": ["ghostship-ntfy", "ghostship-ntfy//tools"],
                  "requiredProcessProfiles": ["ghostship-ntfy"]}
        reads = {"/policy": b"policy", review.HEARTBEAT_PATH: "boot1",
                 "/sys/module/apparmor/parameters/enabled": "Y",
                 "/sys/kernel/security/apparmor/profiles":
                 "ghostship-ntfy (complain)\nghostship-ntfy//tools (complain)\n",
                 "/proc/10/attr/current": "ghostship-ntfy (complain)"}
        with patch.object(review.Path, "read_bytes", lambda p: reads[str(p)]), \
                patch.object(review.Path, "read_text", lambda p: reads[str(p)]), \
                patch.object(review, "run", side_effect=[
                    json.dumps({"image": "id", "running": True, "profile": "ghostship-ntfy"}),
                    "HPID\n10\n", "lost 0\n"]):
            self.assertTrue(review.inspect_container("ntfy", config)["healthy"])

    def test_missing_previous_journal_anchor_resets_coverage(self):
        old = week()
        old["audit_anchor"] = {"id": "missing", "time": 8 * DAY - 1}
        message = ('apparmor="AUDIT" operation="open" profile="ghostship-plex" '
                   f'name="{review.HEARTBEAT_PATH}" requested_mask="r"')
        heartbeat = review.parse_event(9 * DAY, message, "ghostship-plex")
        with patch.object(review, "inspect_container", return_value=GOOD.copy()), \
                patch.object(review, "probe", return_value=heartbeat), \
                patch.object(review, "journal", return_value=[(9 * DAY, message)]), \
                patch.object(review.time, "time", return_value=9 * DAY):
            state = review.collect(CONFIG, {"containers": {"plex": old}}, 9 * DAY)
        self.assertIsNone(state["containers"]["plex"]["coverage_start"])
        self.assertIn("audit-collection-failed", state["containers"]["plex"]["reasons"])

    def test_one_journal_read_split_per_container(self):
        def beat(profile):
            message = (f'apparmor="ALLOWED" operation="open" profile="{profile}" '
                       f'name="{review.HEARTBEAT_PATH}" requested_mask="r" denied_mask="r"')
            return message, review.parse_event(9 * DAY, message, profile)
        plex_msg, plex_beat = beat("ghostship-plex")
        ntfy_msg, ntfy_beat = beat("ghostship-ntfy")
        config = {"containers": {"plex": {"profile": "ghostship-plex"},
                                 "ntfy": {"profile": "ghostship-ntfy"}}}
        with patch.object(review, "inspect_container", return_value=GOOD.copy()), \
                patch.object(review, "probe", side_effect=[plex_beat, ntfy_beat]), \
                patch.object(review, "journal", return_value=[(9 * DAY, plex_msg), (9 * DAY, ntfy_msg)]) as journal, \
                patch.object(review.time, "time", return_value=9 * DAY):
            state = review.collect(config, {"containers": {}}, 9 * DAY)
        # One server-filtered query per container profile.
        self.assertEqual(sorted(c.args[2] for c in journal.call_args_list), ["ghostship-ntfy", "ghostship-plex"])
        for name in ("plex", "ntfy"):
            self.assertNotIn("audit-collection-failed", state["containers"][name]["reasons"])
            self.assertEqual(state["containers"][name]["events"], {})

    def test_audit_error_resets(self):
        with patch.object(review, "inspect_container", return_value=GOOD.copy()), \
                patch.object(review, "probe", return_value={"id": "heartbeat", "time": 9 * DAY}), \
                patch.object(review, "journal", side_effect=ValueError()), \
                patch.object(review.time, "time", return_value=9 * DAY):
            state = review.collect(CONFIG, {"containers": {"plex": week()}}, 9 * DAY)
        self.assertIsNone(state["containers"]["plex"]["coverage_start"])

    def test_loss_without_profile_field_cannot_count_as_quiet(self):
        message = ('apparmor="AUDIT" operation="open" profile="ghostship-plex" '
                   f'name="{review.HEARTBEAT_PATH}" requested_mask="r"')
        previous = {}
        for day in range(8):
            stamp = (day + 1) * DAY
            heartbeat = review.parse_event(stamp, message, "ghostship-plex")
            rows = [(stamp, message), (stamp, "audit: audit_lost=45 audit_backlog_limit=64")]
            if day:
                rows.append((stamp - DAY, message))
            with patch.object(review, "inspect_container", return_value=GOOD.copy()), \
                    patch.object(review, "probe", return_value=heartbeat), \
                    patch.object(review, "journal", return_value=rows), \
                    patch.object(review.time, "time", return_value=stamp):
                previous = review.collect(CONFIG, previous, stamp)
        entry = previous["containers"]["plex"]
        self.assertFalse(review.status(entry, 8 * DAY)["ready"])
        self.assertIn("audit-collection-failed", entry["reasons"])

    def test_only_audit_ratelimits_count_as_loss(self):
        for message in ("audit: 12 callbacks suppressed", "kauditd_printk_skb: 3 callbacks suppressed",
                        "Suppressed 40 messages from plex.service"):
            self.assertTrue(review.AUDIT_LOSS.search(message), message)
        for message in ("rpc_check_timeout: 8 callbacks suppressed", "call_decode: 7 callbacks suppressed"):
            self.assertFalse(review.AUDIT_LOSS.search(message), message)

    def test_journal_reads_one_profile_and_loss_notices_from_victorialogs(self):
        with patch.object(review, "vlogs", return_value=[(5, "x")]) as vlogs:
            rows = review.journal(1, 2, "ghostship-plex")
        queries = [call.args[0] for call in vlogs.call_args_list]
        self.assertIn('transport:="audit" (aa_profile:="ghostship-plex" OR aa_profile:"ghostship-plex//"*)', queries)
        self.assertIn(review.LOSS_QUERY, queries)
        self.assertEqual(rows, [(5, "x"), (5, "x")])
        self.assertGreater(review.JOURNAL_TIMEOUT, 20)

    def test_vlogs_keeps_only_rows_inside_the_window(self):
        body = b'{"_time":"1970-01-01T00:00:05Z","_msg":"in"}\n{"_time":"1970-01-01T00:00:09Z","_msg":"out"}\n'
        class Response(list):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with patch.object(review.urllib.request, "urlopen", return_value=Response(body.splitlines(True))):
            self.assertEqual(review.vlogs("q", 1, 6), [(5.0, "in")])

    def test_kernel_lost_counter_resets_even_without_loss_log(self):
        state = review.advance(week(), {**GOOD, "audit_lost": 2}, [], 9 * DAY, True)
        self.assertIsNone(state["coverage_start"])
        self.assertIn("kernel-audit-loss-counter-changed", state["reasons"])


class FilesAndCLI(unittest.TestCase):
    def test_report_only_does_not_create_state_or_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps(CONFIG))
            directory = Path(tmp) / "absent"
            with patch.object(review.os, "geteuid", return_value=0), \
                    patch.object(review, "collect") as collect, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(review.main(["--config", str(config), "--state-dir", str(directory),
                                              "--report-only"]), 0)
            self.assertFalse(directory.exists())
            collect.assert_not_called()
            self.assertFalse(json.loads(output.getvalue())["containers"]["plex"]["ready"])

    def test_atomic_private_state_review_and_safe_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            config = directory / "config.json"
            config.write_text(json.dumps(CONFIG))
            event = review.parse_event(8 * DAY, MESSAGE, "ghostship-plex")
            state = review.advance(week(), GOOD, [event], 9 * DAY, True)
            review.write_state(directory, {"schema_version": 1, "containers": {"plex": state}})
            self.assertEqual((directory / "evidence.json").stat().st_mode & 0o777, 0o600)
            args = ["--config", str(config), "--state-dir", str(directory), "--review", event["id"],
                    "--classification", "expected-denial", "--note", "Reviewed intentional negative test"]
            original_stat = Path.stat
            def root_stat(path, **kwargs):
                parts = list(original_stat(path, **kwargs))
                parts[4] = 0
                return review.os.stat_result(parts)
            with patch.object(review.os, "geteuid", return_value=0), \
                    patch.object(Path, "stat", root_stat), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(review.main(args), 0)
                saved = review.read_state(directory)
            self.assertNotIn("/private/token", output.getvalue())
            self.assertEqual(saved["containers"]["plex"]["reviews"][event["id"]]["classification"],
                             "expected-denial")
            self.assertEqual(list(directory.glob(".evidence-*")), [])


    def run_cli(self, directory, *extra):
        config = directory / "c.json"
        if not config.exists():
            config.write_text(json.dumps(CONFIG))
        original_stat = Path.stat
        def root_stat(path, **kwargs):
            parts = list(original_stat(path, **kwargs))
            parts[4] = 0
            return review.os.stat_result(parts)
        with patch.object(review.os, "geteuid", return_value=0), patch.object(Path, "stat", root_stat), \
                contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            code = review.main(["--config", str(config), "--state-dir", str(directory), *extra])
        return code, output.getvalue()

    def test_report_flags_policy_content_not_tree_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            policy = directory / "ghostship-plex"
            policy.write_text("profile ghostship-plex {}")
            state = review.advance(week(), {**GOOD, "policy_hash": review.policy_hash(policy)}, [], 9 * DAY, True)
            review.write_state(directory, {"schema_version": 1, "containers": {"plex": state}})
            config = {"containers": {"plex": {**CONFIG["containers"]["plex"], "source": str(policy)}}}
            (directory / "c.json").write_text(json.dumps(config))
            def report():
                _, output = self.run_cli(directory, "--report-only")
                return json.loads(output)["containers"]["plex"]["reasons"]
            self.assertNotIn("configuration-mismatch", report())
            policy.write_text("profile ghostship-plex { capability, }")
            self.assertIn("configuration-mismatch", report())

    def test_brief_report_is_bounded_read_only_and_preserves_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            policy = directory / "policy"
            policy.write_text("profile ghostship-plex {}")
            observation = {**GOOD, "policy_hash": review.policy_hash(policy)}
            events = [{"id": f"private-event-{i}", "time": 8 * DAY} for i in range(2000)]
            previous = week()
            previous["policy_hash"] = observation["policy_hash"]
            state = review.advance(previous, observation, events, 9 * DAY, True)
            review.write_state(directory, {"schema_version": 1, "containers": {"plex": state}})
            (directory / "c.json").write_text(json.dumps({"containers": {
                "plex": {**CONFIG["containers"]["plex"], "source": str(policy)}}}))
            before = (directory / "evidence.json").read_bytes()
            with patch.object(review.time, "time", return_value=9 * DAY), \
                    patch.object(review, "collect") as collect:
                code, output = self.run_cli(directory, "--report-only", "--brief")
            self.assertEqual(code, 0)
            report = json.loads(output)
            self.assertEqual(report["profiles"], 1)
            self.assertEqual(report["ready"], 0)
            self.assertEqual(report["fresh"], 1)
            self.assertEqual(report["blocking_event_count"], 2000)
            self.assertEqual(report["coverage_days_max"], 8)
            self.assertEqual(report["reason_counts"], {})
            self.assertLess(len(output), 1000)
            self.assertNotIn("private-event", output)
            self.assertNotIn("plex", output)
            self.assertEqual((directory / "evidence.json").read_bytes(), before)
            collect.assert_not_called()

    def test_brief_collection_still_collects_and_reports_configuration_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            state = {"schema_version": 1, "containers": {"plex": week()}}
            with patch.object(review, "collect", return_value=state) as collect, \
                    patch.object(review.time, "time", return_value=8 * DAY):
                code, output = self.run_cli(directory, "--brief")
            collect.assert_called_once()
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["ready"], 0)
            self.assertEqual(json.loads(output)["reason_counts"], {"configuration-mismatch": 1})
            self.assertTrue((directory / "evidence.json").exists())

    def test_group_review_clears_only_matching_events(self):
        curl = ('apparmor="ALLOWED" operation="open" profile="ghostship-plex//null-/usr/bin/curl" '
                'name="/etc/nsswitch.conf" requested_mask="r" comm="curl"')
        trace = ('apparmor="ALLOWED" operation="ptrace" profile="ghostship-plex//server" '
                 'peer="ghostship-plex//server" requested_mask="read" comm="504D5320475450"')
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            events = [review.parse_event(8 * DAY + i, message, "ghostship-plex")
                      for i, message in enumerate((curl, curl.replace("nsswitch", "passwd"), trace, MESSAGE))]
            self.assertEqual(events[2]["peer"], "ghostship-plex//server")
            state = review.advance(week(), GOOD, events, 9 * DAY, True)
            review.write_state(directory, {"schema_version": 1, "containers": {"plex": state}})
            code, output = self.run_cli(directory, "--summary")
            groups = json.loads(output)["groups"]["plex"]
            self.assertEqual((code, len(groups)), (0, 4))
            self.assertIn("PMS GTP", {g.get("comm") for g in groups})
            base = ["--container", "plex", "--classification", "resolved-by-policy"]
            with self.assertRaises(SystemExit):
                self.run_cli(directory, *base, "--note", "no reference",
                             "--match", "profile=*curl", "--match", "operation=open")
            with self.assertRaises(SystemExit):
                self.run_cli(directory, *base, "--note", "#123", "--match", "profile=*curl")
            code, _ = self.run_cli(directory, *base, "--note", "Healthcheck profile, #123",
                                   "--match", "profile=ghostship-plex//null-/usr/bin/curl",
                                   "--match", "operation=open", "--match", "name=/etc/*")
            self.assertEqual(code, 0)
            code, _ = self.run_cli(directory, *base, "--note", "Self /proc reads, #123",
                                   "--match", "profile=ghostship-plex//server", "--match", "operation=ptrace",
                                   "--match", "comm=PMS GTP", "--match", "peer=ghostship-plex//server")
            saved = json.loads((directory / "evidence.json").read_text())["containers"]["plex"]
            report = review.status(saved, 9 * DAY)
            self.assertEqual(report["blocking_event_ids"], [events[3]["id"]])
            self.assertEqual(saved["reviews"][events[0]["id"]]["match"]["name"], "/etc/*")


if __name__ == "__main__":
    unittest.main()
