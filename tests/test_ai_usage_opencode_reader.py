"""The OpenCode request reader: the classification, the mapping and the read.

The reader turns OpenCode's own request records into the events the AI
usage collector infers a route's window and budget from. These tests read
only the committed fixture and the directories they build themselves.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "modules" / "self-hosted" / "ai-usage" / "collector"

_MODULE = None


def reader():
    """The reader module, loaded on demand.

    The module is loaded inside the test, so a checkout without it fails
    every test with the same clear error instead of hiding the whole file
    behind one import failure.
    """
    global _MODULE
    if _MODULE is None:
        spec = importlib.util.spec_from_file_location(
            "ai_usage_opencode_reader", COLLECTOR / "opencode_reader.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["ai_usage_opencode_reader"] = module
        spec.loader.exec_module(module)
        _MODULE = module
    return _MODULE


def request(error=None, finish=None, tokens=None, provider="opencode-go", model="example-model", **extra):
    """One request record, shaped the way OpenCode writes it."""
    data = {"model": {"providerID": provider, "id": model}}
    if finish is not None:
        data["finish"] = finish
    if tokens is not None:
        data["tokens"] = tokens
    if error is not None:
        data["error"] = error
    data.update(extra)
    return data


def failure(kind, message):
    """A failed request, with the provider's own words in it."""
    return {"type": kind, "data": {"message": message}}

class ClassificationTests(unittest.TestCase):
    """Every outcome the reader can pick, one assertion each."""

    def classify(self, data):
        return reader().classify(data)

    def test_a_stop_is_a_success(self):
        self.assertEqual(self.classify(request(finish="stop")), ("success", None))

    def test_a_tool_call_stop_is_a_success(self):
        self.assertEqual(self.classify(request(finish="tool-calls")), ("success", None))

    def test_a_length_stop_is_a_success(self):
        self.assertEqual(self.classify(request(finish="length")), ("success", None))

    def test_a_content_filter_stop_is_a_success(self):
        self.assertEqual(self.classify(request(finish="content-filter")), ("success", None))

    def test_a_request_without_a_finish_is_other(self):
        self.assertEqual(self.classify(request()), ("other", None))

    def test_a_request_with_an_unknown_finish_is_other(self):
        self.assertEqual(self.classify(request(finish="unknown")), ("other", None))

    def test_the_session_usage_limit_names_a_five_hour_window(self):
        error = failure("provider.quota", "you (example-user) have reached your session usage limit")
        self.assertEqual(self.classify(request(error=error)), ("limit", "5h"))

    def test_the_weekly_usage_limit_names_a_seven_day_window(self):
        error = failure("provider.quota", "you (example-user) have reached your weekly usage limit")
        self.assertEqual(self.classify(request(error=error)), ("limit", "7d"))

    def test_the_go_usage_limit_is_a_limit_without_a_window(self):
        error = failure("provider.quota", "Go usage limit exceeded")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_the_quota_type_rate_limit_is_a_limit_without_a_window(self):
        error = failure("provider.quota", "Rate limit exceeded. Please try again later.")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_the_current_quota_refusal_is_a_limit_without_a_window(self):
        error = failure("provider.quota", "You exceeded your current quota, please check your plan")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_the_daily_limit_names_a_one_day_window(self):
        error = failure(
            "provider.rate-limit",
            "Rate limit exceeded: limit_rpd/example-model. Daily limit reached for example-model",
        )
        self.assertEqual(self.classify(request(error=error)), ("limit", "1d"))

    def test_the_free_models_daily_limit_names_a_one_day_window(self):
        error = failure("provider.rate-limit", "Rate limit exceeded: free-models-per-day")
        self.assertEqual(self.classify(request(error=error)), ("limit", "1d"))

    def test_a_payment_required_refusal_is_a_limit_without_a_window(self):
        error = failure("provider.quota", "This request requires a positive account balance")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_a_credit_card_refusal_is_a_limit_without_a_window(self):
        error = failure("provider.quota", "AI Gateway requires a valid credit card on file")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_too_many_concurrent_requests_is_not_a_limit(self):
        error = failure("provider.rate-limit", "Too Many Requests: too many concurrent requests")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_the_organization_concurrency_refusal_is_not_a_limit(self):
        error = failure(
            "provider.rate-limit", "Your organization reached its limit of concurrent requests"
        )
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_the_worker_concurrency_refusal_is_not_a_limit(self):
        error = failure("provider.rate-limit", "Worker local total request limit reached (8/8)")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_the_free_models_per_minute_refusal_is_not_a_limit(self):
        error = failure("provider.rate-limit", "Rate limit exceeded: free-models-per-min.")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_a_transient_rate_limit_is_not_a_limit(self):
        error = failure("provider.rate-limit", "Rate limit exceeded: abc123def.")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_an_upstream_refusal_is_not_a_limit(self):
        error = failure(
            "provider.rate-limit", "example-model is temporarily rate-limited upstream, retry later"
        )
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_a_request_that_is_too_large_is_not_a_limit(self):
        error = failure(
            "provider.error",
            "Request too large for model example-model on tokens per minute (TPM)",
        )
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_an_expired_key_is_not_a_limit(self):
        error = failure("provider.auth-error", "This API key has expired")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_an_invalid_token_is_not_a_limit(self):
        error = failure("provider.auth-error", "Your authentication token is invalid")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_an_aborted_run_is_not_a_limit(self):
        error = failure("provider.aborted", "Step interrupted")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_a_response_timeout_is_not_a_limit(self):
        error = failure("provider.error", "Timed out waiting for response headers")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_a_provider_error_without_budget_words_is_not_a_limit(self):
        error = failure("provider.error", "Provider returned error")
        self.assertEqual(self.classify(request(error=error)), ("other", None))

    def test_the_message_may_sit_at_the_top_of_the_error(self):
        error = {"type": "provider.quota", "message": "Go usage limit exceeded"}
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_the_refusal_is_read_case_insensitively(self):
        error = failure("provider.quota", "GO USAGE LIMIT EXCEEDED")
        self.assertEqual(self.classify(request(error=error)), ("limit", None))

    def test_a_limit_request_still_reports_its_usage(self):
        error = failure("provider.quota", "Go usage limit exceeded")
        data = request(error=error, tokens={"input": 0, "output": 0, "reasoning": 0})
        self.assertEqual(reader().usage_tokens(data), 0)

    def test_a_request_reports_the_sum_of_its_tokens(self):
        data = request(
            finish="stop",
            tokens={"input": 1200, "output": 340, "reasoning": 60, "cache": {"read": 800, "write": 5}},
        )
        self.assertEqual(reader().usage_tokens(data), 1600)

    def test_a_request_without_tokens_reports_no_usage(self):
        self.assertIsNone(reader().usage_tokens(request(finish="stop")))

    def test_a_retry_is_one_request_with_one_outcome(self):
        data = request(finish="stop", retry={"attempt": 2})
        self.assertEqual(self.classify(data), ("success", None))

class ProviderMappingTests(unittest.TestCase):
    """The provider table is committed, and nothing is guessed."""

    def test_the_known_providers_are_mapped(self):
        expected = {
            "ollama-cloud": "ollama",
            "opencode-go": "opencode-go",
            "opencode": "opencode",
            "openrouter": "openrouter",
            "google": "google",
            "requesty": "requesty",
            "nvidia": "nvidia",
            "ovh": "ovh",
            "upstage": "upstage",
            "inception": "inception",
            "groq": "groq",
            "mistral": "mistral",
            "cohere": "cohere",
            "zai": "zai",
            "vercel": "vercel",
            "poolside": "poolside",
            "orcarouter": "orcarouter",
        }
        for provider_id, name in expected.items():
            with self.subTest(provider=provider_id):
                self.assertEqual(reader().provider_for(provider_id), name)

    def test_an_unmapped_provider_is_not_mapped(self):
        for provider_id in ("kilo", "kilo-free", "groq-free", "cf-workers", "ghm"):
            with self.subTest(provider=provider_id):
                self.assertIsNone(reader().provider_for(provider_id))

    def test_an_unknown_provider_is_not_mapped(self):
        self.assertIsNone(reader().provider_for("a-provider-nobody-knows"))

if __name__ == "__main__":
    unittest.main()
