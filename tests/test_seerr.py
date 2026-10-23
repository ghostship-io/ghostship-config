import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import requests

spec = importlib.util.spec_from_file_location(
    "seerr_provision",
    Path(__file__).resolve().parents[1] / "modules/self-hosted/seerr-provision.py",
)
seerr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seerr)


def response(data, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode()
    return result


class SeerrTests(unittest.TestCase):
    def test_reconcile_repairs_removed_profile_and_rotated_key_then_converges(self):
        settings = {
            "id": 0,
            "name": "Ghostship radarr",
            "hostname": "radarr",
            "port": 7878,
            "apiKey": "old",
            "activeProfileId": 11,
            "activeProfileName": "Optimal",
            "activeDirectory": "/movies",
            "isDefault": True,
            "preventSearch": True,
        }
        calls = []

        def api(method, path, data=None):
            calls.append((method, path, data))
            if method == "PUT":
                # Released Seerr validates id as readOnly in request bodies.
                if "id" in data:
                    raise requests.HTTPError(
                        "read-only property id", response=response({}, 400)
                    )
                settings.update(data)
            return [dict(settings)] if method == "GET" else dict(settings)

        desired = dict(settings, apiKey="current")
        profiles = [{"id": 12, "name": "Optimal"}]
        roots = [{"path": "/movies"}]
        for _ in range(2):
            seerr.reconcile_instance(api, "radarr", desired, profiles, roots)
        self.assertEqual(settings["activeProfileId"], 12)
        self.assertEqual(settings["apiKey"], "current")
        self.assertTrue(settings["preventSearch"])
        self.assertEqual(sum(method == "PUT" for method, *_ in calls), 1)

    def test_reconcile_preserves_valid_custom_profile_and_refuses_missing_root(self):
        current = {
            "id": 0,
            "hostname": "sonarr",
            "port": 8989,
            "name": "Ghostship sonarr",
            "apiKey": "current",
            "activeProfileId": 2,
            "activeProfileName": "Custom",
            "activeDirectory": "/tv",
        }
        api = Mock(return_value=[current])
        seerr.reconcile_instance(
            api,
            "sonarr",
            dict(current, activeProfileId=8),
            [{"id": 2, "name": "Custom"}, {"id": 8, "name": "Optimal"}],
            [{"path": "/tv"}],
        )
        self.assertEqual(api.call_count, 1)
        with self.assertRaisesRegex(RuntimeError, "root"):
            seerr.reconcile_instance(api, "sonarr", current, [], [])
        self.assertFalse(any(call.args[0] != "GET" for call in api.call_args_list))

    def test_reconcile_refuses_ambiguous_removed_profile_without_writes(self):
        current = {
            "id": 0,
            "name": "Ghostship radarr",
            "hostname": "radarr",
            "port": 7878,
            "apiKey": "current",
            "activeProfileId": 11,
            "activeProfileName": "Optimal",
            "activeDirectory": "/movies",
        }
        api = Mock(return_value=[current])
        with self.assertRaisesRegex(RuntimeError, "profile"):
            seerr.reconcile_instance(
                api,
                "radarr",
                current,
                [{"id": 12, "name": "Optimal"}, {"id": 13, "name": "Optimal"}],
                [{"path": "/movies"}],
            )
        self.assertEqual(api.call_count, 1)

    def test_notification_setup_tests_credentials_and_reads_back_before_converging(
        self,
    ):
        state = {"enabled": False, "types": 0, "options": {"topic": ""}}
        calls = []

        def api(method, path, data=None):
            calls.append((method, path))
            if method == "POST" and not path.endswith("/test"):
                state.update(data)
            return dict(state)

        with patch.dict(seerr.os.environ, NTFY_PUBLISH_PASSWORD="test"):
            seerr.reconcile_notifications(api)
            seerr.reconcile_notifications(api)
        self.assertTrue(state["enabled"])
        self.assertTrue(state["options"]["authMethodUsernamePassword"])
        self.assertEqual(state["options"]["username"], "publisher")
        self.assertEqual(state["options"]["password"], "test")
        self.assertEqual(
            [path for method, path in calls if method == "POST"],
            ["/settings/notifications/ntfy/test", "/settings/notifications/ntfy"],
        )

    def test_notification_auth_failure_does_not_save_settings(self):
        api = Mock(side_effect=[{"options": {}}, requests.HTTPError("rejected")])
        with (
            patch.dict(seerr.os.environ, NTFY_PUBLISH_PASSWORD="test"),
            self.assertRaises(requests.HTTPError),
        ):
            seerr.reconcile_notifications(api)
        self.assertEqual(api.call_count, 2)
        self.assertEqual(api.call_args.args[1], "/settings/notifications/ntfy/test")

    def test_custom_notification_destination_is_preserved(self):
        api = Mock(
            return_value={
                "enabled": True,
                "options": {
                    "url": "https://notify.example.invalid",
                    "topic": "custom",
                },
            }
        )
        seerr.reconcile_notifications(api)
        self.assertEqual(api.call_count, 1)

    def run_setup(self, sync_status, existing_enabled=True, provisioned=False):
        calls = []
        marker = Mock()
        marker.exists.return_value = provisioned
        instances = {"sonarr": [], "radarr": []}
        notifications = {"enabled": False, "types": 0, "options": {}}
        libraries = [
            {"id": "1", "type": "artist", "enabled": existing_enabled},
            {"id": "2", "type": "movie", "enabled": False},
            {"id": "3", "type": "show", "enabled": False},
        ]

        def dispatch(method, url, json=None, params=None, timeout=None):
            path = urlsplit(url).path.removeprefix("/api/v1")
            calls.append((method, path, json, params))
            if path == "/settings/plex":
                return response({"ip": "plex", "libraries": libraries})
            if path == "/settings/plex/library/sync":
                return response(libraries, sync_status)
            if path == "/settings/plex/library":
                if (params or {}).get("enable") == "":
                    return response({"message": "Empty enable value"}, 400)
                # Match the released API's destructive missing-enable behavior.
                enabled = (params or {}).get("enable", "").split(",")
                return response(
                    [dict(item, enabled=item["id"] in enabled) for item in libraries]
                )
            if method == "GET" and path in ("/settings/sonarr", "/settings/radarr"):
                return response(instances[path.rsplit("/", 1)[-1]])
            if method == "POST" and path in ("/settings/sonarr", "/settings/radarr"):
                instances[path.rsplit("/", 1)[-1]].append(dict(json, id=0))
                return response(dict(json, id=0))
            if path == "/settings/notifications/ntfy":
                if method == "POST":
                    notifications.update(json)
                return response(notifications)
            return response({})

        def servarr(url, **kwargs):
            if url.endswith("/qualityprofile"):
                return response([{"id": 1, "name": "Optimal"}])
            return response([{"path": "/tv" if "sonarr" in url else "/movies"}])

        with (
            patch.object(seerr, "Path", return_value=marker),
            patch.object(
                seerr, "address", side_effect=lambda name, port: f"http://{name}"
            ),
            patch.object(seerr.requests, "Session") as session,
            patch.object(seerr.requests, "get", side_effect=servarr),
            patch.dict(
                seerr.os.environ,
                SONARR_API_KEY="test",
                RADARR_API_KEY="test",
                PLEX_TOKEN="test",
                NTFY_PUBLISH_PASSWORD="test",
            ),
        ):
            session.return_value.request.side_effect = dispatch
            if sync_status == 403:
                with self.assertRaises(requests.HTTPError):
                    seerr.main()
                marker.touch.assert_not_called()
            else:
                seerr.main()
                if provisioned:
                    marker.touch.assert_not_called()
                else:
                    marker.touch.assert_called_once()
        return calls

    def test_released_api_preserves_existing_library_on_sync_and_enable(self):
        calls = self.run_setup(404)
        queries = [
            params for _, path, _, params in calls if path == "/settings/plex/library"
        ]
        self.assertEqual(
            queries, [{"sync": "true", "enable": "1"}, {"enable": "1,2,3"}]
        )
        self.assertFalse(any(method == "PUT" for method, *_ in calls))

    def test_first_setup_omits_empty_enable_parameter(self):
        calls = self.run_setup(404, existing_enabled=False)
        queries = [
            params for _, path, _, params in calls if path == "/settings/plex/library"
        ]
        self.assertEqual(queries, [{"sync": "true"}, {"enable": "2,3"}])

    def test_new_api_uses_per_library_updates(self):
        calls = self.run_setup(200)
        updates = [path for method, path, *_ in calls if method == "PUT"]
        self.assertEqual(
            updates, ["/settings/plex/library/2", "/settings/plex/library/3"]
        )
        self.assertFalse(any(path == "/settings/plex/library" for _, path, *_ in calls))

    def test_auth_failure_does_not_fall_back_or_initialize(self):
        calls = self.run_setup(403)
        self.assertFalse(
            any(
                path in ("/settings/plex/library", "/settings/initialize")
                for _, path, *_ in calls
            )
        )

    def test_existing_marker_still_reconciles_without_resetting_login_policy(self):
        calls = self.run_setup(200, provisioned=True)
        self.assertTrue(any(path == "/auth/plex" for _, path, *_ in calls))
        self.assertTrue(any(path == "/settings/radarr" for _, path, *_ in calls))
        self.assertFalse(
            any(
                path in ("/settings/main", "/settings/initialize")
                for _, path, *_ in calls
            )
        )
