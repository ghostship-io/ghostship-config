"""Nothing sensitive leaves the collector, not even in a failure.

A provider can fail with a message that carries a credential, an address, a
path, or a token. The collector never copies such a message into a metric, a
snapshot, or the journal: every failure is reduced to a fixed reason code.
"""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("ai_usage_privacy", ROOT / "main.py")
main = importlib.util.module_from_spec(spec)
sys.modules["ai_usage_privacy"] = main
spec.loader.exec_module(main)

spec = importlib.util.spec_from_file_location("ai_usage_privacy_providers", ROOT / "providers.py")
providers = importlib.util.module_from_spec(spec)
sys.modules["ai_usage_privacy_providers"] = providers
spec.loader.exec_module(providers)

# The sentinels a provider could put into a failure.
SENTINELS = (
    "sk-live-AAAABBBBCCCCDDDD",
    "<owner-email>",
    "/srv/apps/t3code/home/.grok/auth.json",
    "https://api.grok.com/v1/billing?token=EEEE",
)


class LeakingHttp:
    """A transport that fails the way a provider does: with a message."""

    def __init__(self, status=500, body=None, error=""):
        self.status = status
        self.body = json.dumps(body).encode() if body is not None else b""
        self.error = error

    def json(self):
        return json.loads(self.body) if self.body else None

    @property
    def ok(self):
        return 200 <= self.status < 300 and not self.error


def failing_http(*_args, **_kwargs):
    return LeakingHttp(status=500, body={"error": " ".join(SENTINELS)})


class PrivacyTests(unittest.TestCase):
    def _grok_home(self, directory: str) -> str:
        path = Path(directory) / ".grok"
        path.mkdir()
        (path / "auth.json").write_text(
            json.dumps({"https://auth.x.ai::key": {"auth_mode": "oidc", "key": "token"}})
        )
        return directory

    def test_a_provider_failure_keeps_its_message(self):
        with tempfile.TemporaryDirectory() as directory:
            home = self._grok_home(directory)
            result = providers.read_grok(home, 1000.0, http=failing_http)
        self.assertNotEqual(result.status, "ok")
        self.assertNotIn(" ".join(SENTINELS), json.dumps(result.reason))
        self.assertNotIn("sk-live", result.reason)
        self.assertIn(result.reason, {"http_error", "connection_error", "unknown"})

    def test_the_snapshot_keeps_the_message(self):
        with tempfile.TemporaryDirectory() as directory:
            home = self._grok_home(directory)
            result = providers.read_grok(home, 1000.0, http=failing_http)
        snapshot = main.build_snapshot([result], [], {}, 1000.0)
        text = json.dumps(snapshot)
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, text)
        self.assertIn(snapshot["coverage"]["sources"][0]["reason"], {"http_error", "unknown"})

    def test_the_metrics_keep_the_message(self):
        from metrics import MetricWriter

        with tempfile.TemporaryDirectory() as directory:
            home = self._grok_home(directory)
            result = providers.read_grok(home, 1000.0, http=failing_http)
        writer = MetricWriter()
        writer.add("ghostship_ai_source_status", {"source": result.source, "reason": result.reason}, 1.0)
        text = writer.render()
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, text)

    def test_the_journal_keeps_the_message(self):
        with tempfile.TemporaryDirectory() as directory:
            home = self._grok_home(directory)
            result = providers.read_grok(home, 1000.0, http=failing_http)
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            main.log(f"{result.source}: {result.status} ({result.reason})")
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, buffer.getvalue())

    def test_a_malformed_response_keeps_its_body(self):
        with tempfile.TemporaryDirectory() as directory:
            home = self._grok_home(directory)

            def http(*_args, **_kwargs):
                return LeakingHttp(status=200, body={"error": " ".join(SENTINELS)})

            result = providers.read_grok(home, 1000.0, http=http)
        self.assertNotIn("sk-live", result.reason)

    def test_the_reason_codes_are_a_closed_set(self):
        import codes

        for value in ("ok", "unknown", "sk-live-AAAABBBBCCCCDDDD", "boom"):
            self.assertIn(codes.reason(value), codes.CODES)


if __name__ == "__main__":
    unittest.main()
