#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("codex_queue.py")
SPEC = importlib.util.spec_from_file_location("codex_queue", SCRIPT)
assert SPEC and SPEC.loader
codex_queue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(codex_queue)


class FakeTmux:
    def __init__(self, pane: str) -> None:
        self.pane = pane
        self.continues: list[str] = []

    def capture(self, session: str) -> str:
        return self.pane

    def send_continue(self, session: str, sleep_seconds: float = 2.0) -> None:
        self.continues.append(session)


class CodexQueueTests(unittest.TestCase):
    def test_default_parallel_queues(self) -> None:
        self.assertEqual(codex_queue.default_parallel_queues(200), 1)
        self.assertEqual(codex_queue.default_parallel_queues(201), 2)
        self.assertEqual(codex_queue.default_parallel_queues(300), 2)
        self.assertEqual(codex_queue.default_parallel_queues(301), 3)
        self.assertEqual(codex_queue.default_parallel_queues(500, override=4), 4)
        self.assertEqual(codex_queue.default_parallel_queues(500, unknown_size=True), 1)

    def test_split_items_is_contiguous(self) -> None:
        items = [{"id": str(index)} for index in range(10)]
        chunks = codex_queue.split_items(items, 3)
        self.assertEqual([[item["id"] for item in chunk] for chunk in chunks], [
            ["0", "1", "2", "3"],
            ["4", "5", "6"],
            ["7", "8", "9"],
        ])

    def test_pane_is_working_near_bottom(self) -> None:
        self.assertTrue(codex_queue.pane_is_working("line\nWorking (5s)\n"))
        self.assertTrue(codex_queue.pane_is_working("Waiting for background terminal\n"))
        self.assertTrue(codex_queue.pane_is_working("long command (2m • esc to interrupt)\n"))
        self.assertFalse(codex_queue.pane_is_working("Working with untrusted contents\n"))
        far_above = "Working\n" + "\n".join(f"line {index}" for index in range(40))
        self.assertFalse(codex_queue.pane_is_working(far_above))

    def test_ledger_completion_requires_queue_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            queue = {"task_ids": ["a", "b"]}
            ledger.write_text(
                json.dumps({"task_id": "a", "manual_review": True}) + "\n"
                + json.dumps({"task_id": "b", "manual_review": True}) + "\n"
            )
            state = codex_queue.ledger_state(queue, ledger, unknown_size=False)
            self.assertFalse(state["complete"])
            with ledger.open("a") as handle:
                handle.write(json.dumps({"event": "queue_complete", "status": "queue_complete"}) + "\n")
            state = codex_queue.ledger_state(queue, ledger, unknown_size=False)
            self.assertTrue(state["complete"])

    def test_monitor_once_sends_continue_when_idle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / "ledger.jsonl"
            ledger.write_text("")
            run = {
                "unknown_size": False,
                "queues": [
                    {
                        "id": "queue-01",
                        "task_ids": ["a"],
                        "ledger_path": "ledger.jsonl",
                        "branch": "missing",
                        "tmux_session": "session-1",
                    }
                ],
            }
            fake = FakeTmux("Idle")
            actions = codex_queue.monitor_once(root, run, fake, sleep_seconds=0)
            self.assertEqual(actions, ["queue-01:continue_sent"])
            self.assertEqual(fake.continues, ["session-1"])

    def test_find_overlaps(self) -> None:
        overlaps = codex_queue.find_overlaps(
            {
                "branch-a": ["a.txt", "shared.db"],
                "branch-b": ["b.txt", "shared.db"],
                "branch-c": ["c.txt"],
            }
        )
        self.assertEqual(overlaps, {"shared.db": ["branch-a", "branch-b"]})

    def test_render_prompt_contains_manual_review_repetition(self) -> None:
        run = {
            "run_name": "test",
            "batch_size": 5,
            "objective": "Review each item.",
            "support_tooling": "Use search only.",
            "unknown_size": False,
        }
        queue = {
            "id": "queue-01",
            "queue_path": "queues/queue-01.jsonl",
            "ledger_path": "ledgers/queue-01.jsonl",
            "outputs_dir": "outputs/queue-01",
            "task_count": 2,
        }
        rendered = codex_queue.render_prompt(codex_queue.TEMPLATE_PATH, run, queue, "")
        self.assertGreaterEqual(rendered.lower().count("manual review"), 5)
        self.assertIn("cannot be automated away", rendered)
        self.assertIn("must not create tooling", rendered.lower())

    def test_codex_command_trusts_source_and_worktree(self) -> None:
        command = codex_queue.build_codex_command(
            Path("/tmp/source"),
            Path("/tmp/worktree"),
            {"prompt_path": "codex-queue/run/prompts/queue-01.md"},
            "gpt-5.5",
            "high",
        )
        self.assertIn('projects.\\"/tmp/source\\".trust_level=\\"trusted\\"', command)
        self.assertIn('projects.\\"/tmp/worktree\\".trust_level=\\"trusted\\"', command)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


if __name__ == "__main__":
    unittest.main()
