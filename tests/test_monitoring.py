import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from engineio.packet import MESSAGE, Packet
from engineio.payload import Payload
from test_config import load

provision = load(
    "monitoring_provision", "modules/self-hosted/monitoring-provision.py"
)
heartbeats = load(
    "monitoring_heartbeats", "modules/self-hosted/monitoring-heartbeats.py"
)


class MonitoringTests(unittest.TestCase):
    def test_populated_fleet_login_burst_can_be_decoded(self):
        # Login sends multiple heartbeat/stat events per monitor before its ACK.
        burst = Payload(
            packets=[Packet(MESSAGE, data="fleet-event") for _ in range(128)]
        )
        decoded = Payload(encoded_payload=burst.encode())
        self.assertEqual(len(decoded.packets), 128)
        self.assertTrue(all(packet.data == "fleet-event" for packet in decoded.packets))

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
