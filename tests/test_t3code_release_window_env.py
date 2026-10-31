"""The release-window's required environment has one list.

`manual_t3code_cross_generation.py` twice drifted from the tool's guard — first
COREUTILS_BIN, then WINDOW_HOLDER_BIN — and each time the cross-generation proof
aborted at preflight instead of at review. The list below is the contract the
harness validates itself against; this test keeps it equal to the guard.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packages/t3code/release-window.sh"
LIST = ROOT / "packages/t3code/release-window-env.list"


def guard_names():
    # The guard moved when shared helpers were prepended; find the line that
    # names the window state rather than depending on a fixed line number.
    for line in SCRIPT.read_text().splitlines():
        names = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*):\?\}", line))
        if "STATE_DIR" in names:
            return names
    return set()


def listed_names():
    return {line.strip() for line in LIST.read_text().splitlines() if line.strip()}


class RequiredEnv(unittest.TestCase):
    def test_the_list_matches_the_guard(self):
        self.assertEqual(guard_names(), listed_names())

    def test_every_required_name_is_present(self):
        missing = guard_names() - listed_names()
        self.assertEqual(missing, set(), f"guard names missing from the list: {missing}")

    def test_the_list_has_no_stale_names(self):
        stale = listed_names() - guard_names()
        self.assertEqual(stale, set(), f"list names no longer required: {stale}")


if __name__ == "__main__":
    unittest.main()
