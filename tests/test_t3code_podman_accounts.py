"""Mutable host accounts must not redirect a new engine to an obsolete home."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace as Entry
import unittest

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "packages/t3code/dev-engine/reconcile-account.py"
)
spec = importlib.util.spec_from_file_location("accounts", SOURCE)
accounts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accounts)


def user(name, uid=62040):
    return Entry(
        pw_name=name,
        pw_uid=uid,
        pw_gid=uid,
        pw_dir=f"/var/lib/{name}/home",
        pw_shell="/bin/nologin",
    )


def group(name, gid=62040):
    return Entry(gr_name=name, gr_gid=gid, gr_mem=[])


class IdentityReconciliation(unittest.TestCase):
    def setUp(self):
        self.name = "t3code-podman"
        self.home = "/var/lib/t3code-podman/home"
        self.users = [user("t3code-previous"), user(self.name), user("unrelated", 62041)]
        self.groups = [
            group("t3code-previous"),
            group(self.name),
            group("unrelated", 62041),
        ]

    def reconcile(self):
        return accounts.retired_identities(
            self.users, self.groups, self.name, 62040, self.home
        )

    def test_retained_old_name_is_removed_even_when_first_for_the_uid(self):
        self.assertEqual(self.reconcile(), (["t3code-previous"], ["t3code-previous"]))
        self.users.pop(0)
        self.groups.pop(0)
        self.assertEqual(self.reconcile(), ([], []))

    def test_canonical_identity_must_exist_and_match_before_any_removal(self):
        self.users[1].pw_dir = "/unexpected/home"
        with self.assertRaisesRegex(ValueError, "canonical"):
            self.reconcile()
        self.users.pop(1)
        with self.assertRaisesRegex(ValueError, "canonical"):
            self.reconcile()

    def test_unexpected_alias_or_group_members_block_cleanup(self):
        self.users[0].pw_dir = "/home/retained-user"
        with self.assertRaisesRegex(ValueError, "unexpected account"):
            self.reconcile()
        self.users[0] = user("t3code-previous")
        self.groups[0].gr_mem = ["another-user"]
        with self.assertRaisesRegex(ValueError, "unexpected group"):
            self.reconcile()
