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


class ThreeDEvidenceTest(unittest.TestCase):
    """The tier has no prior: only a proven visual and measured usage."""

    def test_visual_capability_needs_the_image_modality(self) -> None:
        self.assertTrue(
            threed.visual_capable({"modalities": {"input": ["text", "image"]}})
        )
        self.assertFalse(threed.visual_capable({"attachment": True}))
        self.assertFalse(threed.visual_capable({"description": "good at CAD"}))
        self.assertFalse(threed.visual_capable(None))

    def test_there_is_no_prior_left(self) -> None:
        self.assertFalse(hasattr(threed, "three_d_prior"))
        self.assertFalse(hasattr(threed, "three_d_score"))


class ThreeDSampleTest(unittest.TestCase):
    def test_the_samples_carry_the_measured_usage_only(self) -> None:
        samples = threed.three_d_samples(
            "claude", "claude-opus-4-1", tokens=10, now=NOW
        )
        names = sorted(name for name, _labels, _value in samples)
        self.assertEqual(
            names,
            [
                "ghostship_ai_three_d_observed_timestamp_seconds",
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

    def test_collect_reports_the_measured_usage_and_the_visual_proof(self) -> None:
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
        catalog = {
            "antigravity": {
                "models": {"gemini-3-pro": {"modalities": {"input": ["text", "image"]}}}
            }
        }
        rows = threed.collect(
            str(self.home),
            catalog,
            [("antigravity", "gemini-3-pro")],
            NOW,
        )
        self.assertIn(("claude", "claude-opus-4-1"), rows)
        self.assertIn(("antigravity", "gemini-3-pro"), rows)
        used = rows[("claude", "claude-opus-4-1")]
        self.assertEqual(used["tokens"], 150)
        self.assertFalse(used["visual"])
        unused = rows[("antigravity", "gemini-3-pro")]
        self.assertEqual(unused["tokens"], 0)
        self.assertTrue(unused["visual"])
        self.assertNotIn("prior", unused)
        self.assertNotIn("score", unused)


if __name__ == "__main__":
    unittest.main()
