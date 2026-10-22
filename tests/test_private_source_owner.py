"""The private flake inputs are accepted under the organisation's namespace.

The organisation owns the private sources now. A lock written before the
transfer still names the previous account, so that owner is accepted while the
transition lasts; any other owner is refused, because the scoped read key must
never reach a repository this deployment does not expect.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import private_source


class PrivateSourceOwnerTests(unittest.TestCase):
    def test_the_canonical_owner_is_accepted(self):
        """The organisation that owns the private inputs is the expected owner."""
        self.assertEqual(private_source.CANONICAL_OWNER, "ghostship-io")
        self.assertTrue(private_source.accepted_owner(private_source.CANONICAL_OWNER))
        self.assertTrue(private_source.supported_source(
            {"type": "github", "owner": private_source.CANONICAL_OWNER, "repo": "agent"}, "agent"))

    def test_the_previous_owner_is_accepted_only_during_the_transition(self):
        """A lock written before the transfer keeps working until it is rewritten."""
        self.assertIn("owner", private_source.TRANSITION_OWNERS)
        self.assertNotEqual(private_source.CANONICAL_OWNER, "owner")
        self.assertTrue(private_source.accepted_owner("owner"))
        self.assertTrue(private_source.supported_source(
            {"type": "github", "owner": "owner", "repo": "agent"}, "agent"))

    def test_any_other_owner_is_refused(self):
        """The scoped read key must not reach an unexpected owner."""
        for owner in ("ghostship-io-elsewhere", "unknown", "", "GHOSTSHIP-IO"):
            with self.subTest(owner=owner):
                self.assertFalse(private_source.accepted_owner(owner))
                self.assertFalse(private_source.supported_source(
                    {"type": "github", "owner": owner, "repo": "agent"}, "agent"))

    def test_a_locked_input_of_another_kind_is_refused(self):
        """Only a GitHub input is a private source."""
        for locked in ({"type": "git", "owner": private_source.CANONICAL_OWNER, "repo": "agent"},
                       {"type": "path", "owner": private_source.CANONICAL_OWNER, "repo": "agent"},
                       {"type": "github", "owner": private_source.CANONICAL_OWNER, "repo": "other"}):
            with self.subTest(locked=locked):
                self.assertFalse(private_source.supported_source(locked, "agent"))

    def test_the_owner_is_read_from_one_constant(self):
        """The accepted owners are the constant's set, not scattered literals."""
        self.assertEqual(private_source.ACCEPTED_OWNERS,
                         frozenset({private_source.CANONICAL_OWNER}) | private_source.TRANSITION_OWNERS)


if __name__ == "__main__":
    unittest.main()
