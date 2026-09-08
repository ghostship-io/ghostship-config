import json
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import requests
from test_config import load

seerr = load("seerr_provision", "modules/self-hosted/seerr-provision.py")


def response(data, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode()
    return result


class SeerrTests(unittest.TestCase):
    def run_setup(self, sync_status, existing_enabled=True):
        calls = []
        marker = Mock()
        marker.exists.return_value = False
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
                return response([])
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
            ),
        ):
            session.return_value.request.side_effect = dispatch
            if sync_status == 403:
                with self.assertRaises(requests.HTTPError):
                    seerr.main()
                marker.touch.assert_not_called()
            else:
                seerr.main()
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
