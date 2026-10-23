"""The private flake inputs are accepted under the organisation's namespace.

The organisation owns the private sources now. A lock written before the
transfer still names the previous account, so that owner is accepted while the
transition lasts; the deployment supplies the name (GHOSTSHIP_TRANSITION_OWNERS)
rather than this repository storing it. Any other owner is refused, because the
scoped read key must never reach a repository this deployment does not expect.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import private_source


PREVIOUS_OWNER = "previous-owner"


class PrivateSourceOwnerTests(unittest.TestCase):
    def test_the_canonical_owner_is_accepted(self):
        """The organisation that owns the private inputs is the expected owner."""
        self.assertEqual(private_source.CANONICAL_OWNER, "ghostship-io")
        self.assertTrue(private_source.accepted_owner(private_source.CANONICAL_OWNER))
        self.assertTrue(private_source.supported_source(
            {"type": "github", "owner": private_source.CANONICAL_OWNER, "repo": "agent"}, "agent"))

    def test_the_previous_owner_is_accepted_only_during_the_transition(self):
        """A lock written before the transfer keeps working while it is supplied."""
        with mock.patch.dict(
            os.environ, {private_source.TRANSITION_OWNERS_VARIABLE: PREVIOUS_OWNER}
        ):
            self.assertIn(PREVIOUS_OWNER, private_source.transition_owners())
            self.assertNotEqual(private_source.CANONICAL_OWNER, PREVIOUS_OWNER)
            self.assertTrue(private_source.accepted_owner(PREVIOUS_OWNER))
            self.assertTrue(private_source.supported_source(
                {"type": "github", "owner": PREVIOUS_OWNER, "repo": "agent"}, "agent"))

    def test_the_previous_owner_is_refused_when_it_is_not_supplied(self):
        """Without the supplied name no pre-transfer lock is accepted."""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(private_source.transition_owners(), frozenset())
            self.assertFalse(private_source.accepted_owner(PREVIOUS_OWNER))
            self.assertFalse(private_source.supported_source(
                {"type": "github", "owner": PREVIOUS_OWNER, "repo": "agent"}, "agent"))

    def test_any_other_owner_is_refused(self):
        """The scoped read key must not reach an unexpected owner."""
        with mock.patch.dict(
            os.environ, {private_source.TRANSITION_OWNERS_VARIABLE: PREVIOUS_OWNER}
        ):
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

    def test_the_accepted_owners_are_the_canonical_one_and_the_supplied_ones(self):
        """The accepted owners are one constant plus the supplied names."""
        with mock.patch.dict(
            os.environ, {private_source.TRANSITION_OWNERS_VARIABLE: PREVIOUS_OWNER}
        ):
            accepted = {
                owner
                for owner in (private_source.CANONICAL_OWNER, PREVIOUS_OWNER, "other")
                if private_source.accepted_owner(owner)
            }
            self.assertEqual(accepted, {private_source.CANONICAL_OWNER, PREVIOUS_OWNER})


if __name__ == "__main__":
    unittest.main()
