"""Tests for the 3D model tier of the AI usage collector."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

COLLECTOR = (
    Path(__file__).resolve().parents[1]
    / "modules"
    / "self-hosted"
    / "ai-usage"
    / "collector"
)
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))

import threed  # noqa: E402

NOW = time.time()


def _write_jsonl(path: Path, records: list[object], *, mtime: float = NOW) -> Path:
    """Write JSONL fixture records, malformed lines included."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            if isinstance(record, str):
                handle.write(record + "\n")
            else:
                handle.write(json.dumps(record) + "\n")
    os.utime(path, (mtime, mtime))
    return path


class ThreeDUsageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.home = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)

    def test_claude_session_in_a_3dprint_directory_counts_its_tokens(self) -> None:
        _write_jsonl(
            self.home
            / ".claude"
            / "projects"
            / "-home-t3code--t3-worktrees-ghostship-3dprinting-enclosure"
            / "session.jsonl",
            [
                {
                    "type": "assistant",
                    "message": {
                        "model": "claude-opus-4-1",
                        "usage": {
                            "input_tokens": 10,
                            "cache_read_input_tokens": 5,
                            "cache_creation_input_tokens": 2,
                            "output_tokens": 3,
                        },
                    },
                }
            ],
        )
        usage = threed.collect_three_d_usage(str(self.home), NOW)
        self.assertEqual(usage, {("claude", "claude-opus-4-1"): 20})

    def test_session_outside_a_3dprint_directory_is_ignored(self) -> None:
        _write_jsonl(
            self.home / ".claude" / "projects" / "-home-t3code-notes" / "session.jsonl",
            [
                {
                    "message": {
                        "model": "claude-opus-4-1",
                        "usage": {"input_tokens": 100, "output_tokens": 100},
                    }
                }
            ],
        )
        _write_jsonl(
            self.home / ".codex" / "sessions" / "2026" / "10" / "21" / "rollout-1.jsonl",
            [
                {"type": "turn_context", "payload": {"model": "gpt-5.1-sol"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 50,
                                "cached_input_tokens": 10,
                                "output_tokens": 5,
                            }
                        },
                    },
                },
            ],
        )
        usage = threed.collect_three_d_usage(str(self.home), NOW)
        self.assertEqual(usage, {})

    def test_codex_session_counts_the_model_of_its_turn_context(self) -> None:
        _write_jsonl(
            self.home / ".codex" / "sessions" / "2026" / "10" / "3dprinting" / "rollout-2.jsonl",
            [
                {"type": "turn_context", "payload": {"model": "gpt-5.1-sol"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 100,
                                "cached_input_tokens": 40,
                                "output_tokens": 20,
                            }
                        },
                    },
                },
            ],
        )
        usage = threed.collect_three_d_usage(str(self.home), NOW)
        self.assertEqual(usage, {("codex", "gpt-5.1-sol"): 160})

    def test_a_malformed_line_is_ignored(self) -> None:
        _write_jsonl(
            self.home / ".grok" / "sessions" / "3dprinting" / "session.jsonl",
            [
                "{not json at all",
                "",
                {
                    "model": "grok-4",
                    "usage": {"input_tokens": 7, "output_tokens": 3},
                },
                "]]]",
            ],
        )
        usage = threed.collect_three_d_usage(str(self.home), NOW)
        self.assertEqual(usage, {("grok", "grok-4"): 10})

    def test_a_total_only_usage_counts_once(self) -> None:
        _write_jsonl(
            self.home / ".pi" / "agent" / "sessions" / "3dprinting" / "session.jsonl",
            [{"model": "qwen3-coder", "usage": {"total_tokens": 42}}],
        )
        usage = threed.collect_three_d_usage(str(self.home), NOW)
        self.assertEqual(usage, {("pi", "qwen3-coder"): 42})

    def test_a_session_older_than_thirty_days_is_ignored(self) -> None:
        _write_jsonl(
            self.home / ".claude" / "projects" / "-work-ghostship-3dprinting-old" / "s.jsonl",
            [
                {
                    "message": {
                        "model": "claude-opus-4-1",
                        "usage": {"input_tokens": 100, "output_tokens": 50},
                    }
                }
            ],
            mtime=NOW - 40 * 24 * 60 * 60,
        )
        usage = threed.collect_three_d_usage(str(self.home), NOW)
        self.assertEqual(usage, {})


class ThreeDPriorTest(unittest.TestCase):
    def test_the_frontier_ranks_above_an_unknown_model(self) -> None:
        unknown = threed.three_d_prior("somewhere", "some-unknown-model")
        self.assertLess(unknown, threed.three_d_prior("antigravity", "gemini-3-pro"))
        self.assertLess(unknown, threed.three_d_prior("antigravity", "claude-opus-4-1"))
        self.assertLess(unknown, threed.three_d_prior("antigravity", "gpt-5.1-sol"))

    def test_a_catalog_description_of_3d_work_lifts_the_prior(self) -> None:
        plain = threed.three_d_prior("claude", "claude-sonnet-4-5")
        lifted = threed.three_d_prior(
            "claude",
            "claude-sonnet-4-5",
            {"description": "Strong at CAD and mesh geometry for 3D printing"},
        )
        self.assertGreater(lifted, plain)

    def test_a_preview_model_loses_a_little_of_the_prior(self) -> None:
        settled = threed.three_d_prior("antigravity", "gemini-3-pro")
        preview = threed.three_d_prior("antigravity", "gemini-3-pro-preview")
        self.assertLess(preview, settled)

    def test_the_prior_stays_within_range(self) -> None:
        entry = {"description": "3d cad mesh geometry engineering physics", "attachment": True}
        for provider, model in (
            ("antigravity", "gemini-4-pro"),
            ("claude", "claude-opus-4-1"),
            ("grok", "grok-4"),
            ("somewhere", "unknown-model"),
        ):
            score = threed.three_d_prior(provider, model, entry)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


class ThreeDScoreTest(unittest.TestCase):
    def test_the_score_rises_with_usage(self) -> None:
        unused = threed.three_d_samples(
            "claude", "claude-opus-4-1", prior=0.92, tokens=0, now=NOW
        )
        used = threed.three_d_samples(
            "claude", "claude-opus-4-1", prior=0.92, tokens=1_000_000, now=NOW
        )
        scores = {name: value for name, _labels, value in unused}
        scores_used = {name: value for name, _labels, value in used}
        self.assertGreater(scores_used["ghostship_ai_three_d_score"], scores["ghostship_ai_three_d_score"])
        self.assertEqual(scores["ghostship_ai_three_d_usage_tokens"], 0.0)
        self.assertEqual(scores_used["ghostship_ai_three_d_usage_tokens"], 1_000_000.0)

    def test_the_samples_carry_the_expected_metric_names(self) -> None:
        samples = threed.three_d_samples(
            "claude", "claude-opus-4-1", prior=0.92, tokens=10, now=NOW
        )
        names = sorted(name for name, _labels, _value in samples)
        self.assertEqual(
            names,
            [
                "ghostship_ai_three_d_observed_timestamp_seconds",
                "ghostship_ai_three_d_prior",
                "ghostship_ai_three_d_score",
                "ghostship_ai_three_d_usage_tokens",
            ],
        )
        for _name, labels, _value in samples:
            self.assertEqual(labels["provider"], "claude")
            self.assertEqual(labels["model"], "claude-opus-4-1")


class ThreeDCollectTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.home = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)

    def test_collect_reports_the_prior_the_usage_and_the_score(self) -> None:
        _write_jsonl(
            self.home / ".claude" / "projects" / "-work-ghostship-3dprinting-bracket" / "s.jsonl",
            [
                {
                    "message": {
                        "model": "claude-opus-4-1",
                        "usage": {"input_tokens": 100, "output_tokens": 50},
                    }
                }
            ],
        )
        rows = threed.collect(
            str(self.home),
            None,
            [("antigravity", "gemini-3-pro")],
            NOW,
        )
        self.assertIn(("claude", "claude-opus-4-1"), rows)
        self.assertIn(("antigravity", "gemini-3-pro"), rows)
        used = rows[("claude", "claude-opus-4-1")]
        self.assertEqual(used["tokens"], 150)
        self.assertGreater(used["score"], threed.three_d_score(used["prior"], 0))
        unused = rows[("antigravity", "gemini-3-pro")]
        self.assertEqual(unused["tokens"], 0)
        self.assertGreater(unused["prior"], 0.9)

    def test_collect_uses_the_catalog_entry_of_a_model(self) -> None:
        catalog = {
            "anthropic": {
                "models": {
                    "claude-sonnet-4-5": {
                        "description": "Good at CAD and 3D printing meshes",
                        "modalities": {"input": ["text", "image"]},
                    }
                }
            }
        }
        rows = threed.collect(str(self.home), catalog, [("claude", "claude-sonnet-4-5")], NOW)
        row = rows[("claude", "claude-sonnet-4-5")]
        self.assertGreater(row["prior"], 0.85)


if __name__ == "__main__":
    unittest.main()
