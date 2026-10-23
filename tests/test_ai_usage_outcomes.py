"""The observed outcomes of the delegation rounds: the counts and the trust.

The ranking needs, per model and task type, the rounds that were observed
(n, s) and the trust level of the model with the reason it holds. These
tests pin the reading of the three files the outcomes are collected from: the
model identities, the ledger of the rounds and the backfill of the rounds
the ledger does not carry.

The cases are the ones the owner's review named: a checkpoint tag that never
pools with the untagged model of the same name, a free model that is one
model on every provider, a ledger whose environment rounds are not rounds,
a policy that speaks for one task type only, and a fabrication that needs
three accepted rounds before the model is trusted again.
"""

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

COLLECTOR = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))

FIXTURES = Path(__file__).resolve().parent / "fixtures/ai-usage/outcomes"


def outcomes_module():
    """The module under test, imported on demand.

    The import is on demand so that a revision without the module reports
    every case as a failure of its own, and not as one broken import.
    """
    if "outcomes" not in sys.modules:
        import outcomes  # noqa: F401
    return sys.modules["outcomes"]


def fixture(name):
    """The bytes of a committed fixture."""
    return (FIXTURES / name).read_bytes()


def identities():
    """The model identities of the fixture."""
    return outcomes_module().load_identities(FIXTURES / "model-identities.json")


def policy():
    """The runtime policy of the fixture."""
    return json.loads(fixture("runtime-policy.json").decode("utf-8"))


def backfill():
    """The backfill of the fixture."""
    return outcomes_module().load_backfill(FIXTURES / "backfill.json")


def build_ledger(directory, name):
    """The ledger of a fixture, built as a database in a temporary directory.

    The repository holds the rounds as JSON, and the ledger is a database:
    the test builds the database in a temporary directory, so the committed
    fixture stays the only thing the test reads.
    """
    document = json.loads(fixture(name).decode("utf-8"))
    columns = list(document["columns"])
    path = Path(directory) / "ledger.sqlite"
    connection = sqlite3.connect(path)
    try:
        kinds = {
            "fabrication": "INTEGER",
            "started_at": "TEXT",
        }
        connection.execute(
            "CREATE TABLE rounds ({})".format(
                ", ".join(f"{column} {kinds.get(column, 'TEXT')}" for column in columns)
            )
        )
        for row in document["rounds"]:
            connection.execute(
                "INSERT INTO rounds ({}) VALUES ({})".format(
                    ", ".join(columns), ", ".join("?" for _ in columns)
                ),
                [row.get(column) for column in columns],
            )
        connection.commit()
    finally:
        connection.close()
    return path


class IdentityTests(unittest.TestCase):
    """The identity of a route: one model, one id, whatever the provider."""

    def test_a_checkpoint_tag_keeps_its_own_identity(self):
        outcomes = outcomes_module()
        self.assertEqual(
            outcomes.identity_of("ollama", "deepseek-v4.1-flash:1017", identities()),
            "deepseek-v4.1-flash-1017",
        )

    def test_the_untagged_model_is_not_the_tagged_one(self):
        outcomes = outcomes_module()
        self.assertEqual(
            outcomes.identity_of("ollama", "deepseek-v4.1-flash", identities()),
            "deepseek-v4.1-flash",
        )

    def test_the_free_suffix_is_stripped(self):
        outcomes = outcomes_module()
        self.assertEqual(
            outcomes.identity_of("opencode-go", "minimax-m3.1-flash-free", identities()),
            "minimax-m3.1-flash",
        )

    def test_the_free_suffix_of_a_vendor_prefix_is_stripped(self):
        outcomes = outcomes_module()
        self.assertEqual(
            outcomes.identity_of(
                "openrouter", "minimax/minimax-m3.1-flash:free", identities()
            ),
            "minimax-m3.1-flash",
        )

    def test_the_free_model_is_one_identity_on_every_provider(self):
        outcomes = outcomes_module()
        self.assertEqual(
            outcomes.identity_of("opencode-go", "beam-free", identities()), "beam"
        )
        self.assertEqual(outcomes.identity_of("ollama", "beam", identities()), "beam")

    def test_the_model_name_keeps_its_own_spelling(self):
        outcomes = outcomes_module()
        self.assertEqual(
            outcomes.identity_of("claude", "claude-haiku-5-5", identities()),
            "claude-haiku-5-5",
        )

    def test_a_ledger_round_names_its_provider(self):
        outcomes = outcomes_module()
        self.assertEqual(
            outcomes.identity_of_round("ollama-cloud/minimax-m3.1-flash", identities()),
            "minimax-m3.1-flash",
        )

    def test_a_ledger_round_without_a_provider_is_the_model(self):
        outcomes = outcomes_module()
        self.assertEqual(
            outcomes.identity_of_round("gemini-3.8-flash", identities()),
            "gemini-3.8-flash",
        )

    def test_the_real_identity_file_is_read(self):
        outcomes = outcomes_module()
        self.assertEqual(
            outcomes.identity_of("ollama", "deepseek-v4.1-flash:1017", identities()),
            "deepseek-v4.1-flash-1017",
        )

    def test_no_input_answers_the_map_of_the_identities(self):
        outcomes = outcomes_module()
        records = outcomes.load_identities(FIXTURES / "model-identities.json")
        self.assertTrue(records)
        for record in records:
            self.assertNotEqual(record["id"], "models")
        models = (
            "deepseek-v4.1-flash:1017",
            "deepseek-v4.1-flash",
            "minimax-m3.1-flash-free",
            "minimax/minimax-m3.1-flash:free",
            "beam-free",
            "beam",
            "gemini-3.8-flash",
            "claude-haiku-5-5",
            "gpt-6-luna",
        )
        for model in models:
            with self.subTest(model=model):
                self.assertNotEqual(
                    outcomes.identity_of("ollama", model, identities()), "models"
                )


class LedgerTests(unittest.TestCase):
    """The ledger: read only, and every column it has."""

    def test_the_rounds_of_the_ledger_are_read(self):
        outcomes = outcomes_module()
        with tempfile.TemporaryDirectory() as directory:
            path = build_ledger(directory, "ledger-rounds.json")
            rounds = outcomes.read_ledger(path)
        self.assertEqual(len(rounds), 11)
        self.assertEqual(rounds[0]["round_id"], "r-1")
        self.assertEqual(rounds[0]["model"], "ollama/beam")
        self.assertEqual(rounds[0]["task_type"], "implementation")
        self.assertEqual(rounds[0]["verdict"], "accepted")
        self.assertEqual(rounds[0]["verdict_source"], "observed")
        self.assertEqual(rounds[0]["started_at"], "2026-10-18T09:00:00Z")

    def test_a_missing_ledger_is_an_empty_history(self):
        outcomes = outcomes_module()
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "no-ledger.sqlite"
            self.assertEqual(outcomes.read_ledger(missing), [])

    def test_an_older_ledger_without_the_verdict_source_is_read(self):
        outcomes = outcomes_module()
        with tempfile.TemporaryDirectory() as directory:
            path = build_ledger(directory, "ledger-rounds-legacy.json")
            rounds = outcomes.read_ledger(path)
        self.assertEqual(len(rounds), 2)
        self.assertEqual(rounds[0]["verdict"], "accepted")
        self.assertEqual(rounds[1]["verdict"], "reworked")
        self.assertNotIn("verdict_source", rounds[0])

    def test_the_ledger_is_not_written(self):
        outcomes = outcomes_module()
        with tempfile.TemporaryDirectory() as directory:
            path = build_ledger(directory, "ledger-rounds.json")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            outcomes.read_ledger(path)
            after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after)


class CountTests(unittest.TestCase):
    """The counts of the rounds: n is the rounds, s is the accepted ones."""

    def counts(self, name="ledger-rounds.json"):
        outcomes = outcomes_module()
        with tempfile.TemporaryDirectory() as directory:
            path = build_ledger(directory, name)
            rounds = outcomes.read_ledger(path)
        return outcomes.outcome_counts(rounds, backfill(), identities())

    def test_the_accepted_and_the_reworked_rounds_count(self):
        counts = self.counts()
        self.assertEqual(counts[("beam", "implementation")]["n"], 4)
        self.assertEqual(counts[("beam", "implementation")]["s"], 3)

    def test_the_environment_round_is_not_a_round(self):
        counts = self.counts()
        self.assertEqual(counts[("beam", "implementation")]["n"], 4)

    def test_the_backfill_replaces_the_verdict_of_a_round(self):
        counts = self.counts()
        # m-2 is reworked in the ledger and accepted in the backfill, the
        # older row of the backfill counts, and the row the ledger already
        # covers does not.
        self.assertEqual(counts[("beam", "research")]["n"], 3)
        self.assertEqual(counts[("beam", "research")]["s"], 3)

    def test_a_manual_verdict_stands(self):
        counts = self.counts()
        # m-1 is accepted in the ledger and rejected in the backfill, and the
        # manual verdict of the ledger is the one that counts.
        self.assertEqual(counts[("beam", "research")]["s"], 3)

    def test_the_fabrications_are_listed(self):
        counts = self.counts()
        fabrications = counts[("beam", "research")]["fabrications"]
        self.assertEqual(len(fabrications), 1)
        self.assertEqual(fabrications[0]["date"], "2026-10-20T10:00:00Z")
        self.assertEqual(fabrications[0]["ref"], "chat-77")
        self.assertEqual(fabrications[0]["source"], "backfill")

    def test_the_fabrication_of_the_ledger_is_listed(self):
        counts = self.counts()
        fabrications = counts[("gemini-3.8-flash", "research")]["fabrications"]
        self.assertEqual(len(fabrications), 1)
        self.assertEqual(fabrications[0]["date"], "2026-10-21T09:00:00Z")
        self.assertEqual(fabrications[0]["ref"], "g-1")
        self.assertEqual(fabrications[0]["source"], "ledger")


class TrustTests(unittest.TestCase):
    """The trust of a model: the policy, the ledger, and the worse of the two."""

    def trust(self, identity, task_type, name="ledger-rounds.json", policy_document=None):
        outcomes = outcomes_module()
        with tempfile.TemporaryDirectory() as directory:
            path = build_ledger(directory, name)
            rounds = outcomes.read_ledger(path)
        return outcomes.trust_for(
            identity,
            task_type,
            policy() if policy_document is None else policy_document,
            rounds,
            backfill(),
            identities(),
        )

    def test_the_policy_speaks_for_its_task_type(self):
        trust = self.trust("beam", "implementation")
        self.assertEqual(trust["level"], "untrusted")
        self.assertEqual(trust["source"], "policy")
        self.assertEqual(
            trust["reason"], "the owner does not trust the model for implementation"
        )

    def test_a_policy_entry_does_not_leak_into_another_task_type(self):
        trust = self.trust("gemini-3.8-flash", "cad-execution")
        self.assertEqual(trust["level"], "trusted")
        self.assertEqual(trust["source"], "default")

    def test_an_excluded_policy_entry_is_the_worst(self):
        trust = self.trust("gemini-3.8-flash", "implementation")
        self.assertEqual(trust["level"], "excluded")
        self.assertEqual(trust["source"], "policy")

    def test_a_model_without_a_policy_or_a_fabrication_is_trusted(self):
        trust = self.trust("claude-haiku-5-5", "implementation")
        self.assertEqual(trust["level"], "trusted")
        self.assertEqual(trust["source"], "default")

    def test_a_fabrication_untrusts_the_model(self):
        trust = self.trust("gemini-3.8-flash", "research")
        self.assertEqual(trust["level"], "untrusted")
        self.assertEqual(trust["source"], "ledger")
        self.assertIn("2026-10-21", trust["reason"])
        self.assertIn("g-1", trust["reason"])

    def test_three_accepted_rounds_restore_the_trust(self):
        trust = self.trust(
            "gemini-3.8-flash", "research", name="ledger-rounds-recovered.json"
        )
        self.assertEqual(trust["level"], "trusted")
        self.assertEqual(trust["source"], "ledger")

    def test_the_worse_of_the_policy_and_the_ledger_wins(self):
        trust = self.trust("minimax-m3.1-flash", "implementation")
        self.assertEqual(trust["level"], "untrusted")
        self.assertEqual(trust["source"], "ledger")

    def test_the_policy_may_be_read_from_a_path(self):
        outcomes = outcomes_module()
        with tempfile.TemporaryDirectory() as directory:
            path = build_ledger(directory, "ledger-rounds.json")
            rounds = outcomes.read_ledger(path)
        trust = outcomes.trust_for(
            "beam",
            "implementation",
            str(FIXTURES / "runtime-policy.json"),
            rounds,
            backfill(),
            identities(),
        )
        self.assertEqual(trust["level"], "untrusted")
        self.assertEqual(trust["source"], "policy")


if __name__ == "__main__":
    unittest.main()


class LeadCauseTests(unittest.TestCase):
    """A round the lead caused is not the model's outcome."""

    def rounds(self):
        rows = []
        verdicts = (
            [("accepted", None)] * 7
            + [("accepted", "brief")]
            + [("reworked", "brief")] * 3
            + [("reworked", "model")]
            + [("rejected", "chief")]
        )
        for index, (verdict, cause) in enumerate(verdicts):
            rows.append(
                {
                    "round_id": f"r-{index}",
                    "model": "ollama-cloud/deepseek-v4.1-flash:1017",
                    "task_type": "implementation",
                    "verdict": verdict,
                    "verdict_source": "manual",
                    "cause": cause,
                    "fabrication": 0,
                    "started_at": f"2026-10-22T{10 + index:02d}:00:00Z",
                }
            )
        return rows

    def test_a_brief_or_chief_round_counts_in_neither_n_nor_s(self):
        # Catches the lead's own mistakes being charged to the model: only
        # the seven clean accepts and the one model-caused rework count.
        outcomes = outcomes_module()
        counts = outcomes.outcome_counts(self.rounds(), [], identities())
        entry = counts[("deepseek-v4.1-flash-1017", "implementation")]
        self.assertEqual((entry["n"], entry["s"]), (8, 7))

    def test_a_backfill_summary_is_never_read_as_a_cause(self):
        # The backfill has no cause field; a summary that names the brief is
        # still the model's outcome.
        outcomes = outcomes_module()
        row = {
            "model": "ollama-cloud/deepseek-v4.1-flash:1017",
            "task_type": "implementation",
            "started_at": "2026-09-30T10:00:00Z",
            "verdict": "reworked",
            "fabrication": False,
            "ref": "opencode:s-1",
            "summary": "brief",
        }
        counts = outcomes.outcome_counts([], [row], identities())
        self.assertEqual(counts[("deepseek-v4.1-flash-1017", "implementation")]["n"], 1)
