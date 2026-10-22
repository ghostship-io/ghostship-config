"""The AI usage collector says which metric series it dropped as a repeat.

A repeated series is dropped, counted, and published as a count. The count
alone does not tell the owner what to fix, so the run names every series it
dropped, and says whether the repeat carried the value that was kept.
"""
import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


metrics = load("ai_usage_metrics", "metrics.py")
main = load("ai_usage_main", "main.py")


def collect(extra):
    """Run the collector's renderer and return the file and what it logged."""
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        text = main.render([], list(extra), 1000.0, 0.5, None)
    return text, stderr.getvalue()


def logged_lines(logged):
    """The lines the run logged, without the trailing newline."""
    return [line for line in logged.splitlines() if line]


def duplicate_count(text):
    """The number the collector published as its duplicate counter."""
    for line in text.splitlines():
        if line.startswith("ghostship_ai_collection_duplicate_series "):
            return float(line.split(" ", 1)[1])
    return 0.0


class DuplicateSeriesTests(unittest.TestCase):
    def test_a_repeat_with_the_same_value_is_named(self):
        text, logged = collect(
            [
                ("ghostship_ai_quota_used_ratio", {"provider": "grok"}, 0.25),
                ("ghostship_ai_quota_used_ratio", {"provider": "grok"}, 0.25),
            ]
        )
        # The series is published once, and the first value is the one that
        # is kept.
        self.assertEqual(
            text.count('ghostship_ai_quota_used_ratio{provider="grok"} 0.25'), 1
        )
        self.assertEqual(duplicate_count(text), 1)
        self.assertEqual(
            logged_lines(logged),
            [
                "ai-usage: dropped repeated series "
                'ghostship_ai_quota_used_ratio{provider="grok"} (same value)'
            ],
        )

    def test_a_repeat_with_a_different_value_is_named(self):
        text, logged = collect(
            [
                ("ghostship_ai_quota_used_ratio", {"provider": "grok"}, 0.25),
                ("ghostship_ai_quota_used_ratio", {"provider": "grok"}, 0.75),
            ]
        )
        # The first value is the one that is kept.
        self.assertEqual(
            text.count('ghostship_ai_quota_used_ratio{provider="grok"} 0.25'), 1
        )
        self.assertNotIn("0.75", text)
        self.assertEqual(duplicate_count(text), 1)
        self.assertEqual(
            logged_lines(logged),
            [
                "ai-usage: dropped repeated series "
                'ghostship_ai_quota_used_ratio{provider="grok"} (different value)'
            ],
        )

    def test_the_labels_are_sorted_as_they_appear_in_the_file(self):
        _text, logged = collect(
            [
                ("ghostship_ai_quota_used_ratio", {"window": "weekly", "provider": "grok"}, 1.0),
                ("ghostship_ai_quota_used_ratio", {"window": "weekly", "provider": "grok"}, 1.0),
            ]
        )
        self.assertIn(
            'ghostship_ai_quota_used_ratio{provider="grok",window="weekly"}', logged
        )

    def test_many_repeats_are_named_up_to_the_limit(self):
        extra = [("ghostship_ai_quota_used_ratio", {"provider": "grok"}, 1.0)] * 26
        text, logged = collect(extra)
        lines = logged_lines(logged)
        named = [line for line in lines if "dropped repeated series" in line]
        self.assertEqual(len(named), 20)
        self.assertEqual(lines[-1], "ai-usage: and 5 more")
        self.assertEqual(duplicate_count(text), 25)

    def test_a_different_label_set_is_not_a_repeat(self):
        text, logged = collect(
            [
                ("ghostship_ai_quota_used_ratio", {"provider": "grok"}, 1.0),
                ("ghostship_ai_quota_used_ratio", {"provider": "openai"}, 2.0),
            ]
        )
        self.assertEqual(logged_lines(logged), [])
        self.assertEqual(duplicate_count(text), 0)
        self.assertIn('ghostship_ai_quota_used_ratio{provider="openai"} 2', text)


class MetricWriterTests(unittest.TestCase):
    def test_the_writer_keeps_the_first_value_and_counts_the_repeat(self):
        writer = metrics.MetricWriter()
        writer.add("m", {"provider": "grok"}, 1.0)
        writer.add("m", {"provider": "grok"}, 2.0)
        self.assertEqual(writer.duplicates, 1)
        self.assertEqual(len(writer.samples()), 1)
        self.assertEqual(writer.samples()[0][2], 1.0)

    def test_the_writer_names_every_dropped_series(self):
        writer = metrics.MetricWriter()
        writer.add("m", {"provider": "grok"}, 1.0)
        writer.add("m", {"provider": "grok"}, 1.0)
        writer.add("m", {"provider": "openai"}, 1.0)
        writer.add("m", {"provider": "openai"}, 2.0)
        self.assertEqual(writer.duplicates, 2)
        self.assertEqual(
            [dropped.describe() for dropped in writer.dropped],
            ['m{provider="grok"}', 'm{provider="openai"}'],
        )
        self.assertEqual(
            [dropped.same_value for dropped in writer.dropped], [True, False]
        )


if __name__ == "__main__":
    unittest.main()
