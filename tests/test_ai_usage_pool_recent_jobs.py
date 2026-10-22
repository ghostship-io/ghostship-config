"""The free pool's recent jobs: one series per label set, and its count.

Two jobs that share a provider, a worker, a client and a status are the
same series: the series is that name with that label set. The series is
the number of those jobs, published once, so a repeat never reaches the
file and the published number is the count and not the first job of it.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NOW = 1_800_000_000.0


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


metrics = load("ai_usage_pool_recent_jobs_metrics", "metrics.py")
main = load("ai_usage_pool_recent_jobs_main", "main.py")
pool = load("ai_usage_pool_recent_jobs_pool", "pool.py")


def job(provider, worker="single_response", client="admission", status="succeeded"):
    """One recent job of the free pool."""
    return {"provider": provider, "worker": worker, "client": client, "status": status}


def emit(jobs):
    """The samples the pool's status emitter publishes for a set of jobs."""
    samples = []
    pool._emit_status(samples, {"jobs": jobs})
    return samples


def recent_jobs(samples):
    """The recent job series of a set of samples: their labels and value."""
    return [
        (labels, value)
        for name, labels, value in samples
        if name == "ghostship_ai_pool_recent_jobs"
    ]


def render(jobs):
    """The published textfile of a pool status that holds a set of jobs."""
    result = metrics.SourceResult(
        source="free_pool", status="ok", reason="ok", metrics=emit(jobs)
    )
    return main.render([result], [], NOW, 0.1, None)


class RecentJobCountTests(unittest.TestCase):
    def test_three_jobs_with_the_same_labels_are_one_series_of_three(self):
        series = recent_jobs(emit([job("kilo"), job("kilo"), job("kilo")]))
        # One series: the name with that label set is published once.
        self.assertEqual(len(series), 1)
        self.assertEqual(
            series[0][0],
            {
                "provider": "kilo",
                "worker": "single_response",
                "client": "admission",
                "status": "succeeded",
            },
        )
        # And its value is the number of those jobs.
        self.assertEqual(series[0][1], 3.0)

    def test_two_jobs_that_differ_only_in_status_are_two_series_of_one(self):
        series = recent_jobs(
            emit([job("kilo", status="succeeded"), job("kilo", status="queued")])
        )
        self.assertEqual(len(series), 2)
        self.assertEqual(sorted(value for _labels, value in series), [1.0, 1.0])
        self.assertEqual(
            sorted(labels["status"] for labels, _value in series),
            ["queued", "succeeded"],
        )

    def test_a_job_without_a_provider_is_skipped(self):
        series = recent_jobs(emit([job(""), job("kilo")]))
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0][0]["provider"], "kilo")

    def test_a_status_with_repeated_jobs_publishes_no_duplicate(self):
        text = render([job("kilo"), job("kilo"), job("nvidia")])
        # The repeats were counted by the emitter, so the renderer dropped
        # none and the count of dropped series is zero.
        self.assertIn("ghostship_ai_collection_duplicate_series 0", text)
        # The published series is the count of the jobs it holds.
        self.assertIn(
            'ghostship_ai_pool_recent_jobs{client="admission",provider="kilo",'
            'status="succeeded",worker="single_response"} 2',
            text,
        )

    def test_the_help_text_says_the_series_is_a_count(self):
        text = render([job("kilo")])
        help_lines = [
            line
            for line in text.splitlines()
            if line.startswith("# HELP ghostship_ai_pool_recent_jobs ")
        ]
        self.assertEqual(len(help_lines), 1)
        self.assertIn("count", help_lines[0])


if __name__ == "__main__":
    unittest.main()
