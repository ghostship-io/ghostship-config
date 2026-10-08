import importlib.util
import pathlib
import tempfile
import unittest

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "containers/agent-desktop/root/opt/ghostship-agent-desktop/agent_desktop_api.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("agent_desktop_api_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StubHandler:
    def __init__(self, path="/pelorus/api/state", headers=None):
        self.path = path
        self.headers = headers or {}


class AuthorizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = load_module()
        cls.api.TOKEN = "test-token-0123456789"

    def test_bearer_header(self):
        handler = StubHandler(headers={"Authorization": "Bearer test-token-0123456789"})
        self.assertTrue(self.api.authorized(handler))

    def test_api_token_header(self):
        handler = StubHandler(headers={"X-Api-Token": "test-token-0123456789"})
        self.assertTrue(self.api.authorized(handler))

    def test_wrong_or_truncated_token(self):
        self.assertFalse(self.api.authorized(StubHandler(headers={"Authorization": "Bearer nope"})))
        self.assertFalse(
            self.api.authorized(StubHandler(headers={"Authorization": "Bearer test-token-01234567"}))
        )
        self.assertFalse(self.api.authorized(StubHandler()))

    def test_query_token_only_for_playwright(self):
        handler = StubHandler(path="/playwright/agent?token=test-token-0123456789")
        self.assertFalse(self.api.authorized(handler))
        self.assertTrue(self.api.authorized(handler, allow_query_token=True))


class PelorusPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = load_module()

    def test_allowed_desktop_endpoints(self):
        allowed = [pattern.match(path) for path in ["/api/state", "/api/windows"] for pattern in self.api.GET_ALLOWED]
        self.assertTrue(any(allowed))
        self.assertTrue(any(p.match("/api/desktop/screenshot") for p in self.api.GET_ALLOWED))
        self.assertTrue(any(p.match("/api/desktop/explore/1234") for p in self.api.GET_ALLOWED))
        self.assertTrue(any(p.match("/api/desktop/control") for p in self.api.POST_ALLOWED))
        self.assertTrue(any(p.match("/api/desktop/close/99") for p in self.api.POST_ALLOWED))

    def test_llm_and_mutation_routes_are_not_allowed(self):
        denied = [
            "/api/run",
            "/api/servers",
            "/api/servers/svr_1",
            "/api/models/fetch",
            "/ws",
            "/docs",
            "/openapi.json",
        ]
        for path in denied:
            self.assertFalse(any(p.match(path) for p in self.api.GET_ALLOWED), path)
            self.assertFalse(any(p.match(path) for p in self.api.POST_ALLOWED), path)

    def test_pelorus_path_rewrite(self):
        handler = self.api.Handler
        self.assertEqual(handler.pelorus_path("/pelorus/api/state"), "/api/state")
        self.assertEqual(handler.pelorus_path("/api/state"), "/api/state")
        self.assertIsNone(handler.pelorus_path("/browsers"))
        self.assertIsNone(handler.pelorus_path("/"))


class BrowserRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = load_module()

    def test_browser_route_shapes(self):
        for path in ["/browsers", "/browsers/agent", "/browsers/temp-ab12/close-tabs"]:
            self.assertIsNotNone(self.api.BROWSER_ROUTES.match(path), path)
        for path in ["/browsers/", "/browsers/a/b", "/playwright/agent"]:
            self.assertIsNone(self.api.BROWSER_ROUTES.match(path), path)

    def test_endpoint_file_parsing(self):
        api = self.api
        with tempfile.TemporaryDirectory() as directory:
            original = api.BROWSER_DIR
            api.BROWSER_DIR = directory
            try:
                path = pathlib.Path(directory) / "agent.json"
                path.write_text('{"endpoint": "ws://127.0.0.1:7901/abc123"}')
                parsed = api.read_browser_endpoint("agent")
                self.assertEqual(parsed.port, 7901)
                self.assertEqual(parsed.path, "/abc123")

                path.write_text('{"endpoint": "http://127.0.0.1:7901/abc123"}')
                self.assertIsNone(api.read_browser_endpoint("agent"))
                self.assertIsNone(api.read_browser_endpoint("../etc/passwd"))
                self.assertIsNone(api.read_browser_endpoint("missing"))
            finally:
                api.BROWSER_DIR = original


if __name__ == "__main__":
    unittest.main()
