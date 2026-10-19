"""ghostship-synology-health: MIB readings to findings, alert lifecycle, secret handling."""
import importlib.util
import os
import stat
import subprocess
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "synology_health", Path(__file__).resolve().parents[1] / "modules/self-hosted/synology-health.py")
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)

HEALTHY = """\
.1.3.6.1.4.1.6574.1.1.0 1
.1.3.6.1.4.1.6574.1.2.0 41
.1.3.6.1.4.1.6574.1.3.0 1
.1.3.6.1.4.1.6574.1.4.1.0 1
.1.3.6.1.4.1.6574.1.4.2.0 1
.1.3.6.1.4.1.6574.2.1.1.2.0 "Drive 1"
.1.3.6.1.4.1.6574.2.1.1.5.0 1
.1.3.6.1.4.1.6574.2.1.1.6.0 36
.1.3.6.1.4.1.6574.2.1.1.13.0 1
.1.3.6.1.4.1.6574.3.1.1.2.0 "Volume 1"
.1.3.6.1.4.1.6574.3.1.1.3.0 1
.1.3.6.1.2.1.25.2.3.1.3.31 "/volume1"
.1.3.6.1.2.1.25.2.3.1.5.31 -1000
.1.3.6.1.2.1.25.2.3.1.6.31 1000
.1.3.6.1.2.1.25.2.3.1.3.1 "Physical memory"
.1.3.6.1.2.1.25.2.3.1.5.1 100
.1.3.6.1.2.1.25.2.3.1.6.1 99
"""
CREDENTIALS = {"USER": "ghostship", "AUTH_PASS": "authsecret-123", "PRIV_PASS": "privsecret-456"}


def reading(**overrides):
    lines = dict(line.split(" ", 1) for line in HEALTHY.splitlines())
    lines.update({f".{oid}": value for oid, value in overrides.items()})
    return health.parse_walk("\n".join(f"{oid} {value}" for oid, value in lines.items()))


class EvaluateTests(unittest.TestCase):
    def test_mib_readings_map_to_findings(self):
        # Defect: a failed disk, RAID, fan or full volume reads as healthy, or a healthy NAS alerts.
        cases = [
            ({}, set()),
            ({"1.3.6.1.4.1.6574.1.1.0": "2"}, {("system.status", "critical")}),
            ({"1.3.6.1.4.1.6574.1.3.0": "2"}, {("system.power", "critical")}),
            ({"1.3.6.1.4.1.6574.1.4.2.0": "2"}, {("fan.cpu", "high")}),
            ({"1.3.6.1.4.1.6574.1.2.0": "63"}, {("system.temperature", "high")}),
            ({"1.3.6.1.4.1.6574.2.1.1.5.0": "5"}, {("disk.0.5", "critical")}),
            ({"1.3.6.1.4.1.6574.2.1.1.13.0": "2"}, {("disk.0.13", "high")}),
            ({"1.3.6.1.4.1.6574.2.1.1.6.0": "57"}, {("disk.0.temperature", "high")}),
            ({"1.3.6.1.4.1.6574.3.1.1.3.0": "11"}, {("raid.0", "critical")}),
            ({"1.3.6.1.4.1.6574.3.1.1.3.0": "7"}, set()),  # resync is not a fault
            # hrStorageSize wraps negative past 2^31 units; 1000 of 2^32-1000 is not full.
            ({"1.3.6.1.2.1.25.2.3.1.5.31": "1100"}, {("volume./volume1", "medium")}),
            ({"1.3.6.1.2.1.25.2.3.1.5.31": "1020"}, {("volume./volume1", "high")}),
            ({"1.3.6.1.2.1.25.2.3.1.6.31": "4294000000"}, {("volume./volume1", "high")}),
        ]
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                found = {(f.key, f.severity) for f in health.evaluate(reading(**overrides))}
                self.assertEqual(found, expected)


class Run:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.calls = []
        self.result = subprocess.CompletedProcess([], returncode, stdout, stderr)

    def __call__(self, argv, **kwargs):
        conf = Path(kwargs["env"]["SNMPCONFPATH"]) / "snmp.conf"
        self.calls.append((argv, conf, conf.read_text(), stat.S_IMODE(os.stat(conf).st_mode)))
        return self.result


class PollTests(unittest.TestCase):
    def test_passphrases_stay_off_argv(self):
        # Defect: SNMP passphrases appear in the process list or outlive the run on disk.
        run = Run(stdout=HEALTHY)
        health.poll("192.168.4.241", CREDENTIALS, run)
        self.assertEqual(len(run.calls), len(health.SUBTREES))
        for argv, conf, text, mode in run.calls:
            self.assertFalse({CREDENTIALS["AUTH_PASS"], CREDENTIALS["PRIV_PASS"]} & {*" ".join(argv).split()})
            self.assertIn("defAuthPassphrase authsecret-123", text)
            self.assertIn("defPrivPassphrase privsecret-456", text)
            self.assertIn("defSecurityLevel authPriv", text)
            self.assertEqual(mode, 0o600)
            self.assertFalse(conf.exists())

    def test_failed_poll_alerts_and_holds_active_findings(self):
        # Defect: an unreachable or misauthenticated NAS reads as healthy and resolves real alerts.
        sent = []
        state = {}
        sender = lambda f, s: sent.append((f.key, s)) or True  # noqa: E731
        failing = reading(**{"1.3.6.1.4.1.6574.3.1.1.3.0": "11"})
        health.dispatch(state, health.evaluate(failing), 0, sender)
        for run in (Run(stderr="Timeout: No Response from 192.168.4.241", returncode=1),
                    Run(stdout=".1.3.6.1.4.1.6574.1 No Such Object available on this agent at this OID")):
            health.dispatch(state, health.findings_for(state, "192.168.4.241", CREDENTIALS, run), 60, sender)
        self.assertEqual(sent, [("raid.0", "firing"), ("snmp.poll", "firing")])
        self.assertEqual(set(state["active"]), {"raid.0", "snmp.poll"})


class DispatchTests(unittest.TestCase):
    def test_fires_once_realerts_daily_resolves_and_retries(self):
        # Defect: every 10-minute run re-alerts, a cleared fault never resolves, or a failed publish is lost.
        sent = []
        outcomes = iter([False, True, True, True])
        sender = lambda f, s: sent.append((f.key, s)) or next(outcomes)  # noqa: E731
        state = {}
        disk = health.Finding("disk.0.5", "critical", "disk", "Drive 1 crashed")
        health.dispatch(state, [disk], 0, sender)
        health.dispatch(state, [disk], 600, sender)
        health.dispatch(state, [disk], 1200, sender)
        health.dispatch(state, [disk], 600 + health.REALERT_SECONDS, sender)
        health.dispatch(state, [], 700 + health.REALERT_SECONDS, sender)
        self.assertEqual(sent, [
            ("disk.0.5", "firing"),
            ("disk.0.5", "firing"),
            ("disk.0.5", "firing"),
            ("disk.0.5", "resolved"),
        ])
        self.assertEqual(state["active"], {})


if __name__ == "__main__":
    unittest.main()
