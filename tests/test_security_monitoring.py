import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


flows = load("security_flows", "security-flows.py")
check = load("security_check", "security-check.py")

CONFIG = {
    "ntfy_topic": "security",
    "expected_profiles": ["ghostship-plex"],
    "container_profiles": {"plex": "ghostship-plex"},
    "expected_tables": ["inet ghostship_flows"],
    "declared_containers": ["plex", "t3code", "gluetun"],
    "ephemeral_prefixes": ["gluetun-bench-"],
    "privileged_allow": ["t3code"],
    "cap_add_allow": {"gluetun": ["CAP_NET_ADMIN"]},
    "socket_mount_allow": [],
    "ssh_allowed_sources": ["10.89.7.3/32"],
    "host_ssh_clients": ["t3code"],
    "database_owners": {"romm-db": ["romm"]},
    "ssh_failure_threshold": 3,
}


def container(name, **host):
    return {"Name": name, "HostConfig": host, "Mounts": [], "State": {"Pid": 1}}


class FlowTests(unittest.TestCase):
    NAMES = {"10.89.0.172": "romm", "10.89.0.154": "romm-db"}
    HOST = {"10.89.0.1", "192.168.4.240"}

    def test_parse_counter_element(self):
        elem = {"elem": {"val": {"concat": ["10.0.0.1", "10.0.0.2", "tcp", 80]}, "counter": {"packets": 3}}}
        self.assertEqual(flows.parse_element(elem), (("10.0.0.1", "10.0.0.2", "tcp", 80), 3))
        self.assertIsNone(flows.parse_element({"elem": {"val": "x"}}))

    def test_classify(self):
        extra = {"192.168.4.241": "synology"}
        self.assertEqual(flows.classify("10.89.0.154", self.NAMES, self.HOST, extra), "romm-db")
        self.assertEqual(flows.classify("10.89.0.1", self.NAMES, self.HOST, extra), "host")
        self.assertEqual(flows.classify("192.168.4.241", self.NAMES, self.HOST, extra), "synology")
        self.assertEqual(flows.classify("192.168.4.9", self.NAMES, self.HOST, extra), "lan:192.168.4.9")
        self.assertEqual(flows.classify("1.1.1.1", self.NAMES, self.HOST, extra), "wan")
        for address in ("255.255.255.255", "10.89.0.255", "239.255.255.250", "ff02::fb"):
            self.assertEqual(flows.classify(address, self.NAMES, self.HOST, extra), "broadcast")

    def test_merge_counts_deltas_and_recreated_elements(self):
        state = {"edges": {}, "elements": {}}
        tuple_ = ("bridge", ("10.89.0.172", "10.89.0.154", "tcp", 3306))
        new = flows.merge(state, {tuple_: 2}, self.NAMES, self.HOST, {}, 100)
        self.assertEqual(new, ["romm|romm-db|tcp|3306"])
        flows.merge(state, {tuple_: 5}, self.NAMES, self.HOST, {}, 200)
        # A smaller counter is a recreated element, counted in full.
        flows.merge(state, {tuple_: 1}, self.NAMES, self.HOST, {}, 300)
        edge = state["edges"]["romm|romm-db|tcp|3306"]
        self.assertEqual((edge["connections"], edge["first_seen"], edge["last_seen"]), (6, 100, 300))
        self.assertEqual(edge["hooks"], ["bridge"])

    def test_recreated_container_keeps_its_name(self):
        state = {"edges": {}, "elements": {}}
        self.assertEqual(flows.remember_addresses(state, {"10.89.0.151": "uptime-kuma"}, 0), {"10.89.0.151": "uptime-kuma"})
        # Recreated with a new address; the old one keeps its owner for one run.
        names = flows.remember_addresses(state, {"10.89.0.190": "uptime-kuma"}, 300)
        self.assertEqual(names["10.89.0.151"], "uptime-kuma")
        # A reused address belongs to its current owner.
        names = flows.remember_addresses(state, {"10.89.0.151": "romm"}, 600)
        self.assertEqual(names["10.89.0.151"], "romm")
        names = flows.remember_addresses(state, {}, 600 + flows.ADDRESS_MEMORY_SECONDS + 1)
        self.assertEqual(names, {})

    def test_short_lived_container_is_not_named_after_an_old_owner(self):
        # bazarr held 10.89.0.220 before its restart; hours later a benchmark
        # container used that address between collections. Its traffic must
        # not be attributed to bazarr.
        state = {"edges": {}, "elements": {}}
        flows.remember_addresses(state, {"10.89.0.220": "bazarr"}, 0)
        names = flows.remember_addresses(state, {"10.89.0.180": "bazarr"}, 3 * 3600)
        self.assertNotIn("10.89.0.220", names)

    def test_report_is_the_default_command(self):
        seen = []
        original = flows.report
        flows.report = lambda args: seen.append((args.command, args.json, args.since_hours, args.state)) or 0
        try:
            flows.main(["--state", "/x", "--json", "--since-hours", "3"])
            flows.main([])
        finally:
            flows.report = original
        self.assertEqual(seen, [("report", True, 3.0, "/x"), ("report", False, 0, "/var/lib/ghostship-security/flows.json")])

    def test_accepted_sets_record_verdicts(self):
        state = {"edges": {}, "elements": {}}
        ssh = ("10.89.0.172", "10.89.0.1", "tcp", 22)
        kuma = ("10.89.0.172", "10.89.0.154", "tcp", 3306)
        observed = {("inet-accepted", kuma): 2, ("inet", ssh): 3, ("inet", kuma): 2}
        new = flows.merge(state, observed, self.NAMES, self.HOST, {}, 100)
        self.assertEqual(sorted(new), ["romm|host|tcp|22", "romm|romm-db|tcp|3306"])
        edges = state["edges"]
        self.assertEqual((edges["romm|host|tcp|22"]["connections"], edges["romm|host|tcp|22"]["accepted"]), (3, 0))
        self.assertEqual(flows.verdict(edges["romm|host|tcp|22"]), "dropped")
        self.assertEqual(flows.verdict(edges["romm|romm-db|tcp|3306"]), "accepted")
        self.assertEqual(flows.verdict({"connections": 9, "checked": 4, "accepted": 1}), "partial")
        self.assertEqual(flows.verdict({"connections": 4}), "unknown")
        self.assertEqual(edges["romm|romm-db|tcp|3306"]["hooks"], ["inet"])

    def test_verdicts_ignore_connections_before_accepted_sets(self):
        kuma = ("10.89.0.172", "10.89.0.154", "tcp", 3306)
        old = {"first_seen": 1, "last_seen": 1, "connections": 500, "accepted": 7, "hooks": ["inet"]}
        state = {"edges": {"romm|romm-db|tcp|3306": old}, "elements": {}}
        flows.merge(state, {("inet", kuma): 3, ("inet-accepted", kuma): 3}, self.NAMES, self.HOST, {}, 100)
        self.assertEqual((old["connections"], old["checked"], old["accepted"]), (503, 3, 3))
        self.assertEqual(flows.verdict(old), "accepted")
        flows.merge(state, {("inet", kuma): 5, ("inet-accepted", kuma): 3}, self.NAMES, self.HOST, {}, 200, verdicts=False)
        self.assertEqual((old["connections"], old["checked"]), (505, 3))

    def test_wan_samples_are_bounded(self):
        state = {"edges": {}, "elements": {}}
        observed = {("inet", ("10.89.0.172", f"8.8.{i}.1", "tcp", 443)): 1 for i in range(40)}
        flows.merge(state, observed, self.NAMES, self.HOST, {}, 1)
        edge = state["edges"]["romm|wan|tcp|443"]
        self.assertEqual(edge["connections"], 40)
        self.assertEqual(len(edge["wan_samples"]), flows.MAX_WAN_SAMPLES)


class CheckTests(unittest.TestCase):
    def test_apparmor_disabled_and_unloaded(self):
        files = {"/sys/module/apparmor/parameters/enabled": "Y\n", "/sys/kernel/security/apparmor/profiles": "other (enforce)\n"}
        keys = [f.key for f in check.check_apparmor(CONFIG, read=files.__getitem__)]
        self.assertEqual(keys, ["apparmor.unloaded.ghostship-plex"])
        files["/sys/module/apparmor/parameters/enabled"] = "N"
        self.assertEqual(check.check_apparmor(CONFIG, read=files.__getitem__)[0].severity, "critical")

    def test_label_mismatch(self):
        good = {"/proc/1/attr/apparmor/current": "ghostship-plex (complain)\n"}
        self.assertEqual(check.check_container_labels(CONFIG, [container("plex")], read=good.__getitem__), [])
        bad = {"/proc/1/attr/apparmor/current": "unconfined\n"}
        self.assertEqual(len(check.check_container_labels(CONFIG, [container("plex")], read=bad.__getitem__)), 1)

    def test_unconfined_process_beyond_pid_one(self):
        # PID 1 is confined, but a child left unconfined by a reload must alert.
        scope = "/sys/fs/cgroup/machine.slice/libpod-x.scope"
        files = {"/proc/1/attr/apparmor/current": "ghostship-plex (complain)\n",
                 "/proc/1/cgroup": "0::/machine.slice/libpod-x.scope/container\n",
                 f"{scope}/cgroup.procs": "", f"{scope}/container/cgroup.procs": "1 7 8\n",
                 "/proc/7/attr/apparmor/current": "unconfined\n",
                 "/proc/8/attr/apparmor/current": "ghostship-plex//server (complain)\n"}
        walk = lambda root: [(scope, ["container"], ["cgroup.procs"]),
                             (f"{scope}/container", [], ["cgroup.procs"])]
        found = check.check_container_labels(CONFIG, [container("plex")], read=files.__getitem__, walk=walk)
        self.assertEqual([(f.key, f.severity) for f in found], [("apparmor.unconfined.plex", "critical")])
        files["/proc/7/attr/apparmor/current"] = "ghostship-plex (complain)\n"
        self.assertEqual(check.check_container_labels(CONFIG, [container("plex")], read=files.__getitem__, walk=walk), [])

    def test_default_profile_unloaded_by_reload(self):
        # Podman recorded the default profile, but a reload removed it.
        radarr = {**container("radarr"), "AppArmorProfile": "ghostship-container-default"}
        bad = {"/proc/1/attr/apparmor/current": "unconfined\n"}
        found = check.check_container_labels(CONFIG, [radarr], read=bad.__getitem__)
        self.assertEqual([(f.key, f.severity) for f in found], [("apparmor.label.radarr", "critical")])
        good = {"/proc/1/attr/apparmor/current": "ghostship-container-default (enforce)\n"}
        self.assertEqual(check.check_container_labels(CONFIG, [radarr], read=good.__getitem__), [])
        # Only allowlisted privileged containers may run without a profile.
        rows = [container("t3code"), container("rogue")]
        keys = [f.key for f in check.check_container_labels(CONFIG, rows, read=bad.__getitem__)]
        self.assertEqual(keys, ["apparmor.label.rogue"])

    def test_container_privilege_caps_sockets_and_undeclared(self):
        rows = [
            container("t3code", Privileged=True),
            container("plex", Privileged=True, CapAdd=["CAP_SYS_ADMIN"]),
            container("gluetun", CapAdd=["CAP_NET_ADMIN"]),
            container("gluetun-bench-1"),
            container("rogue"),
        ]
        rows[4]["Mounts"] = [{"Source": "/run/podman/podman.sock"}]
        keys = sorted(f.key for f in check.check_containers(CONFIG, rows))
        self.assertEqual(
            keys,
            ["container.caps.plex", "container.privileged.plex", "container.socket.rogue", "container.undeclared.rogue"],
        )

    def test_audit_lost_delta(self):
        state = {}
        self.assertEqual(check.check_audit(CONFIG, state, "enabled 1\nlost 4\n"), [])
        found = check.check_audit(CONFIG, state, "enabled 1\nlost 6\n")
        self.assertEqual((found[0].key, found[0].event), ("audit.lost", True))
        self.assertEqual(check.check_audit(CONFIG, state, "enabled 0\nlost 6\n")[0].key, "audit.disabled")

    def test_ssh_logins(self):
        lines = [
            "Accepted publickey for root from 10.89.7.3 port 1 ssh2",
            "Accepted publickey for root from 203.0.113.9 port 1 ssh2",
            "Failed password for root from 203.0.113.9",
            "Invalid user admin from 203.0.113.9",
            "Failed password for root from 203.0.113.9",
        ]
        keys = sorted(f.key for f in check.check_ssh_logins(CONFIG, {}, lines))
        self.assertEqual(keys, ["ssh.failures", "ssh.login.root.203.0.113.9"])

    def test_ssh_clients_resolved_by_name_and_collapsed(self):
        t3 = {**container("t3code"), "NetworkSettings": {"Networks": {"a": {"IPAddress": "10.89.7.13"}}}}
        rogue = {**container("rogue"), "NetworkSettings": {"Networks": {"a": {"IPAddress": "10.89.7.99"}}}}
        clients = check.container_addresses([t3, rogue], ["t3code"])
        lines = ["Accepted publickey for root from 10.89.7.13 port 1 ssh2"] * 3
        lines += ["Accepted publickey for root from 10.89.7.99 port 1 ssh2"] * 2
        found = check.check_ssh_logins(CONFIG, {}, lines, clients)
        self.assertEqual([f.key for f in found], ["ssh.login.root.10.89.7.99"])
        self.assertIn("(2x)", found[0].message)

    def test_recreated_client_keeps_its_previous_address(self):
        state = {}
        old = check.remember_clients(state, check.container_addresses(
            [{**container("t3code"), "NetworkSettings": {"Networks": {"a": {"IPAddress": "10.89.7.13"}}}}], ["t3code"]), 0)
        new = check.remember_clients(state, {check.ipaddress.ip_address("10.89.7.16")}, 600)
        line = ["Accepted publickey for root from 10.89.7.13 port 1 ssh2"]
        self.assertEqual(check.check_ssh_logins(CONFIG, state, line, new), [])
        expired = check.remember_clients(state, set(), 600 + check.CLIENT_MEMORY_SECONDS + 1)
        self.assertEqual(len(check.check_ssh_logins(CONFIG, state, line, expired)), 1)
        self.assertTrue(old)

    def test_listeners_ignore_resolvers_and_ephemeral_udp(self):
        text = (
            "tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n"
            "udp UNCONN 0 0 10.89.0.1:53 0.0.0.0:*\n"
            "udp UNCONN 0 0 0.0.0.0:41234 0.0.0.0:*\n"
            "tcp LISTEN 0 128 [::]:22 [::]:*\n"
        )
        self.assertEqual(check.listeners(text), {"tcp 0.0.0.0:22", "tcp [::]:22"})

    def test_drift_baselines_then_reports(self):
        state = {}
        self.assertEqual(check.drift(state, "listeners", ["a"], "medium", "exposure", lambda i, c: i), [])
        found = check.drift(state, "listeners", ["a", "b"], "medium", "exposure", lambda i, c: i)
        self.assertEqual([f.key for f in found], ["listeners.b"])
        found = check.drift(state, "keys", {"/k": "1"}, "high", "sshd", lambda p, c: c)
        found = check.drift(state, "keys", {"/k": "2", "/n": "3"}, "high", "sshd", lambda p, c: c)
        self.assertEqual(sorted(f.message for f in found), ["added", "changed"])

    def test_flow_findings_and_acceptance(self):
        flows_state = {"edges": {
            "plex|host|tcp|22": {}, "t3code|host|tcp|22": {}, "romm|romm-db|tcp|3306": {}, "seerr|romm-db|tcp|3306": {},
        }}
        keys = sorted(f.key for f in check.flow_findings(CONFIG, flows_state, set()))
        self.assertEqual(keys, ["flow.db.seerr.romm-db", "flow.hostssh.plex"])
        self.assertEqual(len(check.flow_findings(CONFIG, flows_state, {"flow.hostssh.plex"})), 1)

    def test_dispatch_dedupes_resolves_and_skips_event_resolution(self):
        sent = []

        def sender(cfg, finding, state_name):
            sent.append((finding.key, state_name))
            return True

        state = {}
        persistent = check.Finding("container.privileged.plex", "critical", "containers", "m")
        event = check.Finding("ssh.failures", "high", "sshd", "m", event=True)
        check.dispatch(CONFIG, state, [persistent, event], 0, sender)
        check.dispatch(CONFIG, state, [persistent], 60, sender)
        check.dispatch(CONFIG, state, [persistent], check.REALERT_SECONDS + 1, sender)
        check.dispatch(CONFIG, state, [], check.REALERT_SECONDS + 2, sender)
        self.assertEqual(sent, [
            ("container.privileged.plex", "firing"),
            ("ssh.failures", "firing"),
            ("container.privileged.plex", "firing"),
            ("container.privileged.plex", "resolved"),
        ])

    def test_failed_delivery_retries(self):
        attempts = []
        finding = check.Finding("apparmor.disabled", "critical", "apparmor", "m")
        state = {}
        check.dispatch(CONFIG, state, [finding], 0, lambda c, f, s: attempts.append(s) or False)
        check.dispatch(CONFIG, state, [finding], 60, lambda c, f, s: attempts.append(s) or True)
        self.assertEqual(attempts, ["firing", "firing"])


class ScopedAcceptTests(unittest.TestCase):
    """A reviewer re-baselines one drift category or one flow finding.

    The stubs replace every host lookup, so the assertions cover the state
    file only: what the reviewer asked for is accepted, and everything else
    keeps alerting.
    """

    FLOWS = {"edges": {
        "plex|host|tcp|22": {},
        "romm|romm-db|tcp|3306": {},
        "seerr|romm-db|tcp|3306": {},
    }}
    BASELINES = {
        "listeners": ["tcp 0.0.0.0:22"],
        "sshkeys": {"/etc/ssh/authorized_keys.d/agent": "old-digest"},
        "persistence": {"/etc/systemd/system/legacy.service": "old-digest"},
        "suid": ["/usr/local/bin/legacy-suid"],
    }
    CURRENT_SSHKEYS = {"/etc/ssh/authorized_keys.d/agent": "new-digest"}
    CURRENT_PERSISTENCE = {"/etc/systemd/system/legacy.service": "new-digest"}
    CURRENT_SUID = ["/usr/local/bin/legacy-suid", "/usr/local/bin/fresh-suid"]
    COMMANDS = {
        "podman": "",
        "journalctl": "",
        "auditctl": "enabled 1\nlost 0\n",
        "nft": "table inet ghostship_flows\nchain nixos-fw \n",
        "ss": "tcp LISTEN 0 128 0.0.0.0:8080 0.0.0.0:*\n",
    }

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.config_path = root / "config.json"
        self.flows_path = root / "flows.json"
        self.state_path = root / "state.json"
        self.config_path.write_text(json.dumps({**CONFIG, "flows_state": str(self.flows_path)}))
        self.flows_path.write_text(json.dumps(self.FLOWS))
        self.write_state({"baselines": self.BASELINES, "accepted_flows": []})
        self.originals = {name: getattr(check, name) for name in
                          ("sh", "ssh_auth_files", "persistence_entries", "suid_files",
                           "check_apparmor", "dispatch")}
        check.sh = self.fake_sh
        check.ssh_auth_files = lambda: dict(self.CURRENT_SSHKEYS)
        check.persistence_entries = lambda: dict(self.CURRENT_PERSISTENCE)
        check.suid_files = lambda: list(self.CURRENT_SUID)
        check.check_apparmor = lambda cfg: []
        check.dispatch = lambda *arguments: None
        self.addCleanup(self.restore)

    def restore(self):
        for name, value in self.originals.items():
            setattr(check, name, value)

    def fake_sh(self, argv, check=True):
        return self.COMMANDS.get(argv[0], "")

    def write_state(self, state):
        self.state_path.write_text(json.dumps(state, indent=1, sort_keys=True))

    def read_state(self):
        return json.loads(self.state_path.read_text())

    def run_check(self, *arguments):
        """Run the checker over the stubs; return (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = check.main(["--config", str(self.config_path), "--state", str(self.state_path),
                                   *arguments])
            except SystemExit as exit:
                code = exit.code
        return code, out.getvalue(), err.getvalue()

    def findings(self):
        return [entry["key"] for entry in self.read_state()["last_findings"]]

    def test_accept_drift_rebaselines_only_the_named_category(self):
        before = self.read_state()["baselines"]
        code, _, _ = self.run_check("--accept-drift", "sshkeys")
        self.assertEqual(code, 0)
        after = self.read_state()["baselines"]
        for category in ("listeners", "persistence", "suid"):
            self.assertEqual(json.dumps(after[category], sort_keys=True),
                             json.dumps(before[category], sort_keys=True),
                             f"{category} changed by an sshkeys re-baseline")
        self.assertEqual(after["sshkeys"], self.CURRENT_SSHKEYS)
        found = self.findings()
        self.assertEqual([key for key in found if key.startswith("sshkeys.")], [])
        # The categories that were not named keep alerting.
        self.assertTrue(any(key.startswith("listeners.") for key in found))
        self.assertTrue(any(key.startswith("persistence.") for key in found))
        self.assertTrue(any(key.startswith("suid.") for key in found))

    def test_accept_drift_rebaselines_exactly_the_named_categories(self):
        before = self.read_state()["baselines"]
        code, _, _ = self.run_check("--accept-drift", "sshkeys", "--accept-drift", "suid")
        self.assertEqual(code, 0)
        after = self.read_state()["baselines"]
        for category in ("listeners", "persistence"):
            self.assertEqual(json.dumps(after[category], sort_keys=True),
                             json.dumps(before[category], sort_keys=True))
        self.assertEqual(after["sshkeys"], self.CURRENT_SSHKEYS)
        self.assertEqual(after["suid"], sorted(self.CURRENT_SUID))
        found = self.findings()
        self.assertEqual([key for key in found if key.startswith("sshkeys.")], [])
        self.assertEqual([key for key in found if key.startswith("suid.")], [])
        self.assertTrue(any(key.startswith("listeners.") for key in found))
        self.assertTrue(any(key.startswith("persistence.") for key in found))

    def test_accept_flow_accepts_only_that_key(self):
        code, _, _ = self.run_check("--accept-flow", "flow.hostssh.plex")
        self.assertEqual(code, 0)
        self.assertEqual(self.read_state()["accepted_flows"], ["flow.hostssh.plex"])
        found = self.findings()
        self.assertNotIn("flow.hostssh.plex", found)
        self.assertIn("flow.db.seerr.romm-db", found)

    def test_accept_flow_with_an_unknown_key_changes_nothing(self):
        before = self.state_path.read_bytes()
        code, _, err = self.run_check("--accept-flow", "nosuch")
        self.assertNotEqual(code, 0)
        self.assertIn("unknown flow finding", err)
        self.assertIn("nosuch", err)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_accept_cannot_be_combined_with_a_scoped_flag(self):
        before = self.state_path.read_bytes()
        for flag, value in (("--accept-drift", "sshkeys"), ("--accept-flow", "flow.hostssh.plex")):
            with self.subTest(flag=flag):
                code, _, err = self.run_check("--accept", flag, value)
                self.assertNotEqual(code, 0)
                self.assertIn("cannot be combined", err)
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_accept_still_rebaselines_everything(self):
        code, _, _ = self.run_check("--accept")
        self.assertEqual(code, 0)
        state = self.read_state()
        self.assertEqual(state["accepted_flows"], ["flow.db.seerr.romm-db", "flow.hostssh.plex"])
        self.assertEqual(state["baselines"]["sshkeys"], self.CURRENT_SSHKEYS)
        self.assertEqual(state["baselines"]["suid"], sorted(self.CURRENT_SUID))
        self.assertEqual(self.findings(), [])


if __name__ == "__main__":
    unittest.main()
