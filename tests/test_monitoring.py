import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from engineio.packet import MESSAGE, Packet
from engineio.payload import Payload
from test_config import load

ROOT = Path(__file__).resolve().parents[1]

provision = load(
    "monitoring_provision", "modules/self-hosted/monitoring-provision.py"
)
heartbeats = load(
    "monitoring_heartbeats", "modules/self-hosted/monitoring-heartbeats.py"
)

NOTIFY_SCRIPT = ROOT / "modules/self-hosted/unit-notify.sh"
SCHEDULER = "ghostship-inference-scheduler.service"
AUTH = "ghostship-free-worker-auth.service"
DESCRIPTION = "Durable free inference scheduler in the separate worker container"


class UnitNotifyTests(unittest.TestCase):
    """ghostship-unit-notify failure texts follow what actually happened.

    A start job that fails on a dependency never runs the unit, so the unit's
    own Result/ExecMainStatus still read success/0. The 2026-10-24 scheduler
    incident journal (see issue 450) showed such an alert phrased as
    "success (exit status 0)".
    """

    HOST = "fixture-host"

    def run_notify(self, show):
        """Run the failure path with stubbed systemctl; return the notify line.

        ``show`` maps each expected ``systemctl show`` argument string to the
        output the incident's journal-backed queries would produce.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bindir = root / "bin"
            bindir.mkdir()
            log = root / "notify.log"
            cases = "\n".join(
                f'    "{invocation}") printf \'%s\\n\' {shlex.quote(output)} ;;'
                for invocation, output in show.items()
            )
            systemctl = bindir / "systemctl"
            systemctl.write_text(
                "#!/usr/bin/env bash\n"
                'case "$*" in\n'
                f"{cases}\n"
                "    *) exit 4 ;;\n"
                "esac\n"
            )
            systemctl.chmod(0o755)
            publisher = bindir / "ghostship-notify"
            publisher.write_text(
                "#!/usr/bin/env bash\n"
                'for argument in "$@"; do printf \'%s\\n\' "$argument" '
                '>> "$UNIT_NOTIFY_LOG"; done\n'
                "exit 0\n"
            )
            publisher.chmod(0o755)
            script = NOTIFY_SCRIPT.read_text().replace("@host@", self.HOST)
            result = subprocess.run(
                ["bash", "-c", script, "ghostship-unit-notify", "failure", SCHEDULER],
                env={
                    **os.environ,
                    "PATH": f"{bindir}:{os.environ['PATH']}",
                    "UNIT_NOTIFY_LOG": str(log),
                },
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            # ghostship-notify is exec'd with the flags, title and body, one
            # argument per line.
            return log.read_text().splitlines()

    def dependency_failed_start_fixture(self):
        # The evidence from the incident journal: the scheduler's start job
        # failed with result 'dependency', the unit never ran, and the
        # required auth unit itself exited 1, so systemd lists it as failed.
        return {
            f"show -P Description {SCHEDULER}": DESCRIPTION,
            f"show -P Result {SCHEDULER}": "success",
            f"show -P ExecMainStatus {SCHEDULER}": "0",
            f"show -p BindsTo,Requires,Requisite {SCHEDULER}": (
                f"Requires={AUTH}\nRequisite=other-dependency.service"
            ),
            f"show -P ActiveState {AUTH}": "failed",
            "show -P ActiveState other-dependency.service": "inactive",
        }

    def test_dependency_failed_start_names_the_job_and_the_dependency(self):
        arguments = self.run_notify(self.dependency_failed_start_fixture())
        self.assertEqual(arguments, [
            "--topic", "operations",
            "--priority", "4",
            "--source", "systemd",
            "--incident",
            "--dedupe", SCHEDULER,
            "--title", f"Service {SCHEDULER} failed on {self.HOST}",
            f"{DESCRIPTION}: start job failed: dependency {AUTH} failed. "
            f"Inspect: journalctl -b -u {SCHEDULER}",
        ])
        self.assertNotIn("success (exit status 0)", " ".join(arguments))

    def test_real_nonzero_exit_keeps_the_result_text(self):
        # The unit itself ran and exited 1; the message must keep the current
        # result (exit status N) form.
        show = self.dependency_failed_start_fixture()
        show[f"show -P Description {SCHEDULER}"] = DESCRIPTION
        show[f"show -P Result {SCHEDULER}"] = "exit-code"
        show[f"show -P ExecMainStatus {SCHEDULER}"] = "1"
        arguments = self.run_notify(show)
        self.assertEqual(arguments, [
            "--topic", "operations",
            "--priority", "4",
            "--source", "systemd",
            "--incident",
            "--dedupe", SCHEDULER,
            "--title", f"Service {SCHEDULER} failed on {self.HOST}",
            f"{DESCRIPTION}: exit-code (exit status 1). "
            f"Inspect: journalctl -b -u {SCHEDULER}",
        ])
        self.assertNotIn("start job failed", " ".join(arguments))

    def test_dependency_failed_start_without_a_failed_candidate_stays_named(self):
        # No dependency edge is itself failed at query time (the culprit is
        # further down the cascade); the alert still names the job outcome.
        show = self.dependency_failed_start_fixture()
        show[f"show -P ActiveState {AUTH}"] = "inactive"
        arguments = self.run_notify(show)
        self.assertEqual(
            arguments[-1],
            f"{DESCRIPTION}: start job failed: a dependency failed before the "
            f"unit ran. Inspect: journalctl -b -u {SCHEDULER}",
        )


class MonitoringTests(unittest.TestCase):
    def test_provisioning_waits_for_the_initial_info_before_setup_rpc(self):
        import threading
        import socketio

        class ReachedSettings(Exception):
            pass

        class DelayedServer:
            def __init__(self):
                self.handlers = {}
                self.ready = False
                self.disconnected = False
                self.timer = None

            def on(self, event):
                def register(handler):
                    self.handlers[event] = handler
                    return handler
                return register

            def connect(self, *args, **kwargs):
                # Kuma awaits sendInfo before registering public RPC handlers.
                # A request emitted before that step is not acknowledged.
                def finish_handshake():
                    self.ready = True
                    self.handlers.get('info', lambda _: None)({})
                self.timer = threading.Timer(0.01, finish_handshake)
                self.timer.start()

            def call(self, event, *args, **kwargs):
                if not self.ready:
                    raise socketio.exceptions.TimeoutError()
                if event == 'needSetup':
                    return False
                raise ReachedSettings()

            def disconnect(self):
                self.disconnected = True
                if self.timer:
                    self.timer.cancel()
                    self.timer.join()

        client = DelayedServer()
        with patch.object(provision.socketio, 'Client', return_value=client), patch.dict(
                provision.os.environ, {'KUMA_URL':'http://example.invalid', 'GHOSTSHIP_KUMA_USERNAME':'fixture'}):
            with self.assertRaises(ReachedSettings):
                provision.main()
        self.assertTrue(client.disconnected)

    def test_missing_initial_info_fails_boundedly_before_any_rpc(self):
        client = Mock()
        client.on.side_effect = lambda _event: lambda handler: handler
        event = Mock()
        event.wait.return_value = False
        with patch.object(provision.socketio, 'Client', return_value=client), patch.object(
                provision.threading, 'Event', return_value=event), patch.dict(
                provision.os.environ, {'KUMA_URL':'http://example.invalid'}):
            with self.assertRaisesRegex(RuntimeError, 'initial info handshake'):
                provision.main()
        event.wait.assert_called_once_with(20)
        client.call.assert_not_called()
        client.disconnect.assert_called_once()

    def test_existing_ntfy_notification_is_updated_without_changing_its_id(self):
        api = Mock(return_value={"id": 7})
        notification_id = provision.reconcile_ntfy_notification(
            api, [{"name": "Ghostship ntfy", "id": 7,
                   "config": json.dumps({"type": "ntfy", "ntfyserverurl": "http://ntfy"})}],
            "rotated-password"
        )
        self.assertEqual(notification_id, 7)
        event, (settings, existing_id) = api.call_args.args
        self.assertEqual((event, existing_id), ("addNotification", 7))
        self.assertEqual(settings["ntfyserverurl"], "http://ntfy:8080")
        self.assertEqual(settings["ntfypassword"], "rotated-password")

    def test_existing_managed_notification_of_another_type_is_not_overwritten(self):
        api = Mock()
        with self.assertRaisesRegex(RuntimeError, "changed type"):
            provision.reconcile_ntfy_notification(
                api, [{"name": "Ghostship ntfy", "id": 7,
                       "config": json.dumps({"type": "smtp"})}], "rotated-password"
            )
        api.assert_not_called()

    def test_populated_fleet_login_burst_can_be_decoded(self):
        # Login sends multiple heartbeat/stat events per monitor before its ACK.
        burst = Payload(
            packets=[Packet(MESSAGE, data="fleet-event") for _ in range(128)]
        )
        decoded = Payload(encoded_payload=burst.encode())
        self.assertEqual(len(decoded.packets), 128)
        self.assertTrue(all(packet.data == "fleet-event" for packet in decoded.packets))

    def test_provisioning_removes_only_known_retired_http_monitors(self):
        retired = {
            "name": "Ghostship Synara",
            "type": "http",
        }
        self.assertTrue(provision.is_retired_app_monitor(retired, set()))
        self.assertFalse(
            provision.is_retired_app_monitor(retired, {"Synara"})
        )
        self.assertFalse(
            provision.is_retired_app_monitor(
                {"name": "Ghostship Custom", "type": "http"}, set()
            )
        )
        self.assertFalse(
            provision.is_retired_app_monitor(
                {"name": "Ghostship Synara", "type": "push"}, set()
            )
        )

    def test_container_monitor_accepts_running_containers_without_healthchecks(self):
        with patch.object(
            heartbeats.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="running|\n"),
        ):
            self.assertEqual(
                heartbeats.container_health("sidecar"),
                (True, "Container is running and healthy"),
            )

    def test_container_monitor_rejects_unhealthy_and_stopped_containers(self):
        for state, expected in [
            ("running|unhealthy", "Container health is unhealthy"),
            ("exited|", "Container state is exited"),
        ]:
            with self.subTest(state=state), patch.object(
                heartbeats.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=state),
            ):
                healthy, message = heartbeats.container_health("service")
                self.assertFalse(healthy)
                self.assertEqual(message, expected)

    def test_container_monitor_reports_missing_containers(self):
        with patch.object(
            heartbeats.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=1, stdout=""),
        ):
            self.assertEqual(
                heartbeats.container_health("missing"),
                (False, "Container is missing or cannot be inspected"),
            )

    def test_provisioning_prunes_only_owned_retired_container_push_monitors(self):
        owned_stale = {
            "name": "Ghostship container retired-service",
            "type": "push",
            "pushToken": "managed-token",
        }
        custom_stale = {
            "name": "Ghostship container personal-check",
            "type": "push",
            "pushToken": "custom-token",
        }
        current = {
            "name": "Ghostship container current-service",
            "type": "push",
            "pushToken": "current-token",
        }
        self.assertTrue(
            provision.is_owned_stale_container_monitor(
                owned_stale, ["current-service"], {"managed-token"}
            )
        )
        self.assertFalse(
            provision.is_owned_stale_container_monitor(
                custom_stale, ["current-service"], {"managed-token"}
            )
        )
        self.assertFalse(
            provision.is_owned_stale_container_monitor(
                current, ["current-service"], {"current-token"}
            )
        )

    def test_push_tokens_are_persisted_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state" / "push.json"
            pushes = {"containers": {"service": "secret-token"}}
            provision.write_push_tokens(path, pushes)
            self.assertEqual(json.loads(path.read_text()), pushes)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_auth_setting_is_disabled_using_the_existing_account_password(self):
        settings = {"disableAuth": False, "otherSetting": "preserved"}
        socket_call = Mock(return_value={"data": settings})
        provision.enforce_access_only_auth(socket_call, "current-password")
        socket_call.assert_has_calls(
            [
                call("getSettings"),
                call(
                    "setSettings",
                    (
                        {"disableAuth": True, "otherSetting": "preserved"},
                        "current-password",
                    ),
                ),
            ]
        )

    def test_auth_setting_does_not_rewrite_already_disabled_configuration(self):
        socket_call = Mock(return_value={"data": {"disableAuth": True}})
        provision.enforce_access_only_auth(
            socket_call, "current-password"
        )
        socket_call.assert_called_once_with("getSettings")
