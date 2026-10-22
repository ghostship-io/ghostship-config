"""The test fixture lint: a scratch path in a test fails the check, unless the
line states why the reference is harmless."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check-test-fixtures.py"
spec = importlib.util.spec_from_file_location("check_test_fixtures", SCRIPT)
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)


class LintTests(unittest.TestCase):
    def test_a_scratch_path_read_by_a_test_is_reported(self):
        source = (
            "def test_pull():\n"
            "    with open('/tmp/aa-pull/raw') as handle:\n"
            "        data = handle.read()\n"
        )
        findings = lint.scan_source(source, "test_pull.py")
        self.assertEqual(len(findings), 1)
        self.assertIn("/tmp/aa-pull/raw", findings[0].reason)
        self.assertEqual(findings[0].line, 2)

    def test_a_scratch_path_given_to_path_is_reported(self):
        findings = lint.scan_source("root = Path('/home/t3code/.t3/worktrees')\n", "test_x.py")
        self.assertEqual(len(findings), 1)

    def test_every_scratch_root_is_reported(self):
        for path in ("/tmp/x", "/var/tmp/x", "/home/t3code", "/workspace/nixos-config"):
            with self.subTest(path=path):
                findings = lint.scan_source(f"value = open({path!r})\n", "test_x.py")
                self.assertEqual(len(findings), 1)

    def test_a_committed_fixture_is_allowed(self):
        findings = lint.scan_source(
            "value = open('tests/fixtures/example.json')\n", "test_x.py")
        self.assertEqual(findings, [])

    def test_a_temporary_directory_is_allowed(self):
        source = (
            "import tempfile\n"
            "with tempfile.TemporaryDirectory() as directory:\n"
            "    value = open(Path(directory) / 'raw')\n"
        )
        self.assertEqual(lint.scan_source(source, "test_x.py"), [])

    def test_an_approved_line_is_allowed(self):
        source = "root = Path('/home/t3code/.t3/worktrees')  # fixture-path-ok: a name, never read\n"
        self.assertEqual(lint.scan_source(source, "test_x.py"), [])

    def test_an_approval_without_a_reason_is_reported(self):
        source = "root = Path('/home/t3code/.t3/worktrees')  # fixture-path-ok:\n"
        findings = lint.scan_source(source, "test_x.py")
        self.assertEqual(len(findings), 1)

    def test_a_path_that_only_looks_like_a_root_is_allowed(self):
        for path in ("/homepage", "/workspace-notes", "/tmpfile"):
            with self.subTest(path=path):
                self.assertEqual(lint.scan_source(f"value = open({path!r})\n", "test_x.py"), [])


class RepositoryTests(unittest.TestCase):
    def test_the_repository_tests_read_only_committed_fixtures(self):
        findings = lint.scan_tree(ROOT / "tests")
        self.assertEqual([str(finding) for finding in findings], [])


if __name__ == "__main__":
    unittest.main()
