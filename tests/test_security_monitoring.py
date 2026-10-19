import importlib.util
from pathlib import Path
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
        # Recreated with a new address; the old one keeps its owner for a day.
        names = flows.remember_addresses(state, {"10.89.0.190": "uptime-kuma"}, 3600)
        self.assertEqual(names["10.89.0.151"], "uptime-kuma")
        # A reused address belongs to its current owner.
        names = flows.remember_addresses(state, {"10.89.0.151": "romm"}, 7200)
        self.assertEqual(names["10.89.0.151"], "romm")
        names = flows.remember_addresses(state, {}, 7200 + flows.ADDRESS_MEMORY_SECONDS + 1)
        self.assertEqual(names, {})

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


if __name__ == "__main__":
    unittest.main()
