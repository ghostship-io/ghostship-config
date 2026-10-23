"""The deploy slot: one record of who may deploy chill-penguin.

Every case builds its own state directory in a temporary directory and pins
the clock, so a test never touches the real slot or the real system profile.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy-slot"

GENERATION = 412
STALE_MINUTES = 60


def interpreter() -> str:
    """The interpreter the tool's shebang names.

    A Nix build sandbox has no /usr/bin/env, so the kernel cannot resolve the
    shebang and the tool looks missing. The tests run it with the interpreter
    the shebang names, which the sandbox does have.
    """
    try:
        shebang = SCRIPT.read_text().splitlines()[0]
    except OSError:
        return shutil.which("python3") or "python3"
    parts = shebang[2:].split() if shebang.startswith("#!") else []
    if parts and os.path.basename(parts[0]) == "env":
        parts = parts[1:]
    name = parts[0] if parts else "python3"
    return shutil.which(name) or name


class DeploySlotTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state = self.root / "state"
        self.profile = self.root / "system-profile"
        self.profile.symlink_to(f"system-{GENERATION}-link")
        self.now = "2026-10-23T05:00:00Z"

    def environment(self, now=None, profile=None, stale_minutes=None):
        environment = {
            **os.environ,
            "GHOSTSHIP_DEPLOY_SLOT_DIR": str(self.state),
            "GHOSTSHIP_SYSTEM_PROFILE": str(profile or self.profile),
            "GHOSTSHIP_DEPLOY_SLOT_NOW": now or self.now,
        }
        environment.pop("GHOSTSHIP_DEPLOY_SLOT_STALE_MINUTES", None)
        if stale_minutes is not None:
            environment["GHOSTSHIP_DEPLOY_SLOT_STALE_MINUTES"] = str(stale_minutes)
        return environment

    def run_slot(self, *arguments, now=None, profile=None, stale_minutes=None):
        self.assertTrue(SCRIPT.exists(), "scripts/deploy-slot is missing")
        return subprocess.run(
            [interpreter(), str(SCRIPT), *arguments],
            env=self.environment(now=now, profile=profile, stale_minutes=stale_minutes),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def payload(self, result):
        self.assertTrue(result.stdout.strip(), f"no JSON on stdout: {result.stderr}")
        document = json.loads(result.stdout)
        self.assertEqual(document["schema"], 1)
        self.assertIn("result", document)
        return document

    def command(self, *arguments, now=None, profile=None, stale_minutes=None):
        result = self.run_slot(*arguments, now=now, profile=profile, stale_minutes=stale_minutes)
        return result.returncode, self.payload(result)

    def acquire(self, holder="alpha", purpose="release chill-penguin", now=None, *flags):
        return self.command("acquire", "--holder", holder, "--purpose", purpose, *flags, now=now)

    def status(self, now=None):
        return self.command("status", now=now)[1]

    def released(self, holder="alpha"):
        return self.command("release", "--holder", holder)

    def slot_bytes(self):
        path = self.state / "slot.json"
        return path.read_bytes() if path.exists() else None

    def ledger(self):
        path = self.state / "ledger.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def assert_refused(self, code, document, reason_fragment=None):
        self.assertEqual(code, 3, document)
        self.assertEqual(document["result"], "refused")
        self.assertIn("reason", document)
        if reason_fragment is not None:
            self.assertIn(reason_fragment, document["reason"])


class AcquireTests(DeploySlotTestCase):
    def test_acquire_a_free_slot_records_the_holder(self):
        code, document = self.acquire()
        self.assertEqual(code, 0, document)
        self.assertEqual(document["result"], "acquired")
        self.assertEqual(document["holder"], "alpha")
        self.assertEqual(document["purpose"], "release chill-penguin")
        self.assertEqual(document["acquired_at"], self.now)
        self.assertEqual(document["last_activity"], self.now)
        self.assertEqual(document["base_generation"], GENERATION)
        self.assertEqual(document["state"], "held")
        self.assertEqual(self.status()["holder"], "alpha")
        ledger = self.ledger()
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["event"], "acquired")
        self.assertEqual(ledger[0]["holder"], "alpha")
        self.assertEqual(ledger[0]["purpose"], "release chill-penguin")
        self.assertEqual(ledger[0]["generation"], GENERATION)
        self.assertEqual(ledger[0]["time"], self.now)

    def test_the_state_directory_and_its_files_are_private(self):
        self.assertEqual(self.acquire()[0], 0)
        self.assertEqual((self.state.stat().st_mode & 0o777), 0o700)
        self.assertEqual(((self.state / "slot.json").stat().st_mode & 0o777), 0o600)
        self.assertEqual(((self.state / "ledger.jsonl").stat().st_mode & 0o777), 0o600)

    def test_a_slot_without_a_readable_profile_records_no_generation(self):
        missing = self.root / "missing-profile"
        code, document = self.command(
            "acquire", "--holder", "alpha", "--purpose", "release", profile=missing)
        self.assertEqual(code, 0, document)
        self.assertEqual(document["result"], "acquired")
        self.assertIsNone(document["base_generation"])
        self.assertIsNone(self.status()["base_generation"])

    def test_acquiring_again_refreshes_the_clock_and_keeps_acquired_at(self):
        self.assertEqual(self.acquire(now="2026-10-23T05:00:00Z")[0], 0)
        code, document = self.acquire(now="2026-10-23T05:02:00Z")
        self.assertEqual(code, 0, document)
        self.assertEqual(document["result"], "refreshed")
        self.assertEqual(document["acquired_at"], "2026-10-23T05:00:00Z")
        self.assertEqual(document["last_activity"], "2026-10-23T05:02:00Z")
        self.assertEqual(document["holder"], "alpha")
        self.assertEqual(len(self.ledger()), 1)

    def test_another_holder_is_refused_while_the_slot_is_fresh(self):
        self.assertEqual(self.acquire(now="2026-10-23T05:00:00Z")[0], 0)
        before = self.slot_bytes()
        code, document = self.command(
            "acquire", "--holder", "bravo", "--purpose", "second release", now="2026-10-23T05:00:30Z")
        self.assert_refused(code, document)
        self.assertEqual(document["holder"], "alpha")
        self.assertEqual(document["purpose"], "release chill-penguin")
        self.assertEqual(document["since"], "2026-10-23T05:00:00Z")
        self.assertEqual(self.slot_bytes(), before)
        self.assertEqual(len(self.ledger()), 1)
        self.assertEqual(self.status(now="2026-10-23T05:00:30Z")["holder"], "alpha")

    def test_a_refused_holder_joins_the_queue_and_a_second_attempt_refreshes_it(self):
        self.assertEqual(self.acquire(now="2026-10-23T05:00:00Z")[0], 0)
        code, _ = self.command(
            "acquire", "--holder", "bravo", "--purpose", "second release", "--queue",
            now="2026-10-23T05:00:10Z")
        self.assertEqual(code, 3)
        queue = self.status(now="2026-10-23T05:00:10Z")["queue"]
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["holder"], "bravo")
        self.assertEqual(queue[0]["purpose"], "second release")
        self.assertEqual(queue[0]["since"], "2026-10-23T05:00:10Z")
        self.assertEqual(queue[0]["last_seen"], "2026-10-23T05:00:10Z")

        code, _ = self.command(
            "acquire", "--holder", "bravo", "--purpose", "second release", "--queue",
            now="2026-10-23T05:02:00Z")
        self.assertEqual(code, 3)
        queue = self.status(now="2026-10-23T05:02:00Z")["queue"]
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["since"], "2026-10-23T05:00:10Z")
        self.assertEqual(queue[0]["last_seen"], "2026-10-23T05:02:00Z")

    def test_a_live_queue_entry_holds_the_slot_for_the_holder_ahead(self):
        self.assertEqual(self.acquire(now="2026-10-23T05:00:00Z")[0], 0)
        self.assertEqual(self.command(
            "acquire", "--holder", "alpha2", "--purpose", "queued release", "--queue",
            now="2026-10-23T05:00:10Z")[0], 3)
        self.assertEqual(self.released("alpha")[0], 0)

        code, document = self.command(
            "acquire", "--holder", "bravo", "--purpose", "jump the queue", now="2026-10-23T05:00:20Z")
        self.assert_refused(code, document, "queued behind alpha2")
        self.assertEqual(self.status(now="2026-10-23T05:00:20Z")["state"], "free")

        code, document = self.command(
            "acquire", "--holder", "alpha2", "--purpose", "queued release", now="2026-10-23T05:00:20Z")
        self.assertEqual(code, 0, document)
        self.assertEqual(document["result"], "acquired")
        self.assertEqual(document["holder"], "alpha2")
        self.assertEqual(self.status(now="2026-10-23T05:00:20Z")["queue"], [])

    def test_a_queue_entry_older_than_three_minutes_is_dropped(self):
        self.assertEqual(self.acquire(now="2026-10-23T05:00:00Z")[0], 0)
        self.assertEqual(self.command(
            "acquire", "--holder", "alpha2", "--purpose", "queued release", "--queue",
            now="2026-10-23T05:00:00Z")[0], 3)
        self.assertEqual(self.released("alpha")[0], 0)

        self.assertEqual(self.status(now="2026-10-23T05:03:00Z")["queue"][0]["holder"], "alpha2")
        code, document = self.command(
            "acquire", "--holder", "bravo", "--purpose", "later release", now="2026-10-23T05:03:01Z")
        self.assertEqual(code, 0, document)
        self.assertEqual(document["result"], "acquired")
        self.assertEqual(self.status(now="2026-10-23T05:03:01Z")["queue"], [])

    def test_a_stale_slot_is_refused_without_force(self):
        self.assertEqual(self.acquire(now="2026-10-23T04:00:00Z")[0], 0)
        self.assertEqual(self.status(now="2026-10-23T05:00:01Z")["state"], "stale")
        before = self.slot_bytes()
        code, document = self.command(
            "acquire", "--holder", "bravo", "--purpose", "next release", now="2026-10-23T05:00:01Z")
        self.assert_refused(code, document)
        self.assertEqual(document["state"], "stale")
        self.assertEqual(document["holder"], "alpha")
        self.assertEqual(self.slot_bytes(), before)
        self.assertEqual(len(self.ledger()), 1)

    def test_a_stale_slot_is_taken_over_with_force_and_a_reason(self):
        self.assertEqual(self.acquire(now="2026-10-23T04:00:00Z")[0], 0)
        code, document = self.command(
            "acquire", "--holder", "bravo", "--purpose", "next release",
            "--force", "--reason", "the previous holder went quiet", now="2026-10-23T05:00:01Z")
        self.assertEqual(code, 0, document)
        self.assertEqual(document["result"], "taken_over")
        self.assertEqual(document["holder"], "bravo")
        self.assertEqual(document["previous_holder"], "alpha")
        self.assertEqual(document["base_generation"], GENERATION)
        ledger = self.ledger()
        self.assertEqual([line["event"] for line in ledger], ["acquired", "taken_over"])
        self.assertEqual(ledger[1]["holder"], "bravo")
        self.assertEqual(ledger[1]["previous_holder"], "alpha")
        self.assertEqual(ledger[1]["reason"], "the previous holder went quiet")
        self.assertEqual(ledger[1]["generation"], GENERATION)
        self.assertEqual(self.status(now="2026-10-23T05:00:01Z")["holder"], "bravo")

    def test_a_force_does_not_take_over_a_fresh_slot(self):
        self.assertEqual(self.acquire(now="2026-10-23T05:00:00Z")[0], 0)
        before = self.slot_bytes()
        code, document = self.command(
            "acquire", "--holder", "bravo", "--purpose", "next release",
            "--force", "--reason", "I want it", now="2026-10-23T05:00:30Z")
        self.assert_refused(code, document, "not stale")
        self.assertEqual(self.slot_bytes(), before)
        self.assertEqual(document["holder"], "alpha")
        self.assertEqual(len(self.ledger()), 1)

    def test_force_without_a_reason_is_a_usage_error_and_changes_nothing(self):
        self.assertEqual(self.acquire(now="2026-10-23T04:00:00Z")[0], 0)
        before = self.slot_bytes()
        for arguments in (
            ("acquire", "--holder", "bravo", "--purpose", "next release", "--force"),
            ("acquire", "--holder", "bravo", "--purpose", "next release", "--force", "--reason", ""),
        ):
            code, document = self.command(*arguments, now="2026-10-23T05:00:01Z")
            self.assertEqual(code, 2, document)
            self.assertEqual(document["result"], "usage")
        self.assertEqual(self.slot_bytes(), before)
        self.assertEqual(len(self.ledger()), 1)

    def test_empty_multiline_and_over_long_values_are_usage_errors(self):
        cases = (
            ("acquire", "--holder", "", "--purpose", "release"),
            ("acquire", "--holder", "alpha", "--purpose", ""),
            ("acquire", "--holder", "alpha", "--purpose", "two\nlines"),
            ("acquire", "--holder", "a\nline", "--purpose", "release"),
            ("acquire", "--holder", "h" * 201, "--purpose", "release"),
            ("acquire", "--holder", "alpha", "--purpose", "p" * 501),
        )
        for arguments in cases:
            code, document = self.command(*arguments)
            self.assertEqual(code, 2, (arguments, document))
            self.assertEqual(document["result"], "usage")
        self.assertIsNone(self.slot_bytes())
        self.assertFalse(self.state.exists())

    def test_the_stale_boundary_is_exactly_the_configured_minutes(self):
        self.assertEqual(self.acquire(now="2026-10-23T04:00:00Z")[0], 0)
        self.assertEqual(self.status(now="2026-10-23T05:00:00Z")["state"], "held")
        self.assertEqual(self.status(now="2026-10-23T05:00:01Z")["state"], "stale")

    def test_the_stale_threshold_is_read_from_the_environment(self):
        self.assertEqual(self.acquire(now="2026-10-23T04:00:00Z")[0], 0)
        document = self.status(now="2026-10-23T04:01:00Z", stale_minutes=1)
        self.assertEqual(document["stale_minutes"], 1)
        self.assertEqual(document["state"], "held")
        self.assertEqual(self.status(now="2026-10-23T04:01:01Z", stale_minutes=1)["state"], "stale")


class ReleaseTests(DeploySlotTestCase):
    def test_a_release_by_the_holder_frees_the_slot_and_records_the_generation(self):
        self.assertEqual(self.acquire()[0], 0)
        code, document = self.command("release", "--holder", "alpha", "--generation", "413")
        self.assertEqual(code, 0, document)
        self.assertEqual(document["result"], "released")
        self.assertEqual(document["state"], "free")
        self.assertEqual(document["last_release"]["holder"], "alpha")
        self.assertEqual(document["last_release"]["generation"], 413)
        status = self.status()
        self.assertEqual(status["state"], "free")
        self.assertIsNone(status["holder"])
        self.assertEqual(status["last_release"]["generation"], 413)
        ledger = self.ledger()
        self.assertEqual([line["event"] for line in ledger], ["acquired", "released"])
        self.assertEqual(ledger[1]["holder"], "alpha")
        self.assertEqual(ledger[1]["generation"], 413)
        self.assertEqual(ledger[1]["time"], self.now)

    def test_a_release_without_a_generation_records_the_current_generation(self):
        self.assertEqual(self.acquire()[0], 0)
        code, document = self.command("release", "--holder", "alpha")
        self.assertEqual(code, 0, document)
        self.assertEqual(document["last_release"]["generation"], GENERATION)
        self.assertEqual(self.ledger()[1]["generation"], GENERATION)

    def test_a_release_on_a_free_slot_says_already_free(self):
        code, document = self.command("release", "--holder", "alpha")
        self.assertEqual(code, 0, document)
        self.assertEqual(document["result"], "already_free")
        self.assertEqual(document["state"], "free")
        self.assertIsNone(document["last_release"])
        self.assertEqual(self.status()["state"], "free")
        self.assertEqual(self.ledger(), [])

    def test_a_release_by_another_holder_is_refused(self):
        self.assertEqual(self.acquire()[0], 0)
        before = self.slot_bytes()
        code, document = self.command("release", "--holder", "bravo")
        self.assert_refused(code, document, "alpha")
        self.assertEqual(self.slot_bytes(), before)
        self.assertEqual(len(self.ledger()), 1)
        self.assertEqual(self.status()["holder"], "alpha")

    def test_a_release_without_a_holder_is_a_usage_error(self):
        code, document = self.command("release")
        self.assertEqual(code, 2, document)
        self.assertEqual(document["result"], "usage")


class CheckTests(DeploySlotTestCase):
    def test_a_check_by_the_holder_refreshes_the_clock(self):
        self.assertEqual(self.acquire(now="2026-10-23T05:00:00Z")[0], 0)
        code, document = self.command("check", "--holder", "alpha", now="2026-10-23T05:01:00Z")
        self.assertEqual(code, 0, document)
        self.assertEqual(document["result"], "ok")
        self.assertEqual(document["last_activity"], "2026-10-23T05:01:00Z")
        self.assertEqual(self.status(now="2026-10-23T05:01:00Z")["last_activity"],
                         "2026-10-23T05:01:00Z")

    def test_a_check_by_the_holder_of_a_stale_slot_succeeds(self):
        self.assertEqual(self.acquire(now="2026-10-23T04:00:00Z")[0], 0)
        code, document = self.command("check", "--holder", "alpha", now="2026-10-23T06:00:00Z")
        self.assertEqual(code, 0, document)
        self.assertEqual(document["result"], "ok")
        self.assertEqual(document["last_activity"], "2026-10-23T06:00:00Z")
        self.assertEqual(self.status(now="2026-10-23T06:00:00Z")["state"], "held")

    def test_a_check_by_another_holder_is_refused(self):
        self.assertEqual(self.acquire(now="2026-10-23T05:00:00Z")[0], 0)
        before = self.slot_bytes()
        code, document = self.command("check", "--holder", "bravo", now="2026-10-23T05:00:10Z")
        self.assert_refused(code, document, "alpha")
        self.assertEqual(self.slot_bytes(), before)

    def test_a_check_on_a_free_slot_is_refused_and_names_free(self):
        code, document = self.command("check", "--holder", "alpha")
        self.assert_refused(code, document, "free")
        self.assertEqual(document["state"], "free")
        self.assertIsNone(document["holder"])


class StatusTests(DeploySlotTestCase):
    def test_a_status_of_an_empty_state_directory_is_free(self):
        code, document = self.command("status")
        self.assertEqual(code, 0, document)
        self.assertEqual(document["result"], "status")
        self.assertEqual(document["state"], "free")
        self.assertIsNone(document["holder"])
        self.assertIsNone(document["purpose"])
        self.assertIsNone(document["acquired_at"])
        self.assertIsNone(document["last_activity"])
        self.assertIsNone(document["base_generation"])
        self.assertIsNone(document["last_release"])
        self.assertEqual(document["queue"], [])
        self.assertEqual(document["stale_minutes"], STALE_MINUTES)

    def test_a_status_names_the_holder_purpose_and_queue(self):
        self.assertEqual(self.acquire(now="2026-10-23T05:00:00Z")[0], 0)
        self.assertEqual(self.command(
            "acquire", "--holder", "bravo", "--purpose", "later release", "--queue",
            now="2026-10-23T05:00:05Z")[0], 3)
        document = self.status(now="2026-10-23T05:00:06Z")
        self.assertEqual(document["state"], "held")
        self.assertEqual(document["holder"], "alpha")
        self.assertEqual(document["purpose"], "release chill-penguin")
        self.assertEqual(document["acquired_at"], "2026-10-23T05:00:00Z")
        self.assertEqual(document["last_activity"], "2026-10-23T05:00:00Z")
        self.assertEqual(document["base_generation"], GENERATION)
        self.assertEqual([entry["holder"] for entry in document["queue"]], ["bravo"])

    def test_an_unknown_command_is_a_usage_error(self):
        code, document = self.command("deploy")
        self.assertEqual(code, 2, document)
        self.assertEqual(document["result"], "usage")


class ConcurrencyTests(DeploySlotTestCase):
    def test_two_processes_acquire_a_free_slot_and_exactly_one_wins(self):
        environment = self.environment()
        processes = [
            subprocess.Popen(
                [interpreter(), str(SCRIPT), "acquire", "--holder", holder, "--purpose", "release"],
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for holder in ("alpha", "bravo")
        ]
        outputs = [process.communicate(timeout=60) for process in processes]
        codes = sorted(process.returncode for process in processes)
        self.assertEqual(codes, [0, 3], outputs)
        documents = [json.loads(stdout) for stdout, _ in outputs]
        winners = [document["holder"] for document in documents if document["result"] == "acquired"]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.status()["holder"], winners[0])
        self.assertEqual([line["event"] for line in self.ledger()], ["acquired"])


if __name__ == "__main__":
    unittest.main()
