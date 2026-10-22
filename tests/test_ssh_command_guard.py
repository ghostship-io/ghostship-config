"""The agent SSH command guard: real commands from the fleet's own history.

The guard refuses the recursive content reads the host policy forbids and
executes everything else unchanged. The refused and allowed command strings
below are the ones agents actually ran against the host.
"""
import importlib.util
import os
import shutil
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules/self-hosted/ssh-command-guard.py"
spec = importlib.util.spec_from_file_location("ssh_command_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

# The shell a session runs in. The test pins it, because the account's login
# shell is a property of the machine that runs the test: a build sandbox has
# no account database, and an account may name a shell the machine does not
# have. The guard then has no shell to start and every session fails.
SESSION_SHELL = shutil.which("bash") or shutil.which("sh") or "/bin/sh"
# A command that exists wherever the test runs. An absolute path under /bin
# does not: a build sandbox has no /bin/echo.
ECHO = shutil.which("echo") or "echo"

# The commands an agent ran against the host on 2026-10-22, and the fleet
# commands that must keep working.
ALLOWED = [
    "systemctl --failed",
    "journalctl -u ghostship-private-integrations",
    "readlink -f /run/current-system",
    "cat /root/t3-force-restart-result.json",
    "nix-store --serve",
    "nix-daemon --stdio",
    "podman inspect t3code",
    "systemctl --failed | journalctl -u podman-t3code --no-pager -n 20",
    "readlink -f /nix/var/nix/profiles/system",
    "grep -r build /workspace/nixos-config",
    "rg token /workspace/ghostship-agent",
    "find /workspace -name '*.env' -exec cat {} \\;",
    "find /etc -maxdepth 1 -type f",
    "cat /etc/ghostship-version",
    "ls -la /root",
    "sh -c 'systemctl is-active podman-t3code'",
    "nix copy --to ssh-ng://root@chill-penguin /nix/store/abc",
    "/nix/store/abc-openssh-10.5p1/libexec/sftp-server",
    "cd /workspace/nixos-config && git status --short",
]

REFUSED = [
    # The command that read the host's credential databases and opened a SIEM
    # investigation on 2026-10-22.
    "grep -rl <keyword> /etc /root",
    "rg token /root",
    "find / -name '*.env' -exec cat {} \\;",
    "grep -R secret /etc",
    "grep --recursive secret /var/lib",
    "egrep -r secret /home",
    "rg -n token /etc",
    "find /etc -type f",
    "find /root -maxdepth 3",
    "find /var/lib -name '*.db' -exec grep -H secret {} \\;",
    "find / -name '*.env'",
    "cat /etc/shadow",
    "cat /etc/shadow-",
    "cat /etc/gshadow",
    "cat /etc/shadow*",
    "head -n 5 /etc/gshadow",
    "cd /etc && grep -r password .",
    "grep -r password /etc; systemctl --failed",
    "sh -c 'grep -r password /root'",
    "xargs grep -r secret /etc",
    "cat /etc/shadow > /tmp/out",
]


class ClassifierTests(unittest.TestCase):
    def test_allowed_commands_are_not_refused(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                verdict = guard.classify(command, cwd="/root", home="/root")
                self.assertFalse(verdict.refused, f"{command}: {verdict.reason}")

    def test_refused_commands_are_refused_with_a_reason(self):
        for command in REFUSED:
            with self.subTest(command=command):
                verdict = guard.classify(command, cwd="/root", home="/root")
                self.assertTrue(verdict.refused, command)
                self.assertTrue(verdict.reason)

    def test_a_recursive_read_outside_the_protected_roots_stays_allowed(self):
        for command in ("grep -r token /workspace", "rg token /srv/apps",
                        "find /srv -name '*.env' -exec cat {} \\;"):
            with self.subTest(command=command):
                self.assertFalse(guard.classify(command, cwd="/root", home="/root").refused)

    def test_a_named_file_under_a_protected_root_stays_readable(self):
        for command in ("cat /root/t3-force-restart-result.json",
                        "cat /etc/ghostship-version",
                        "head -n 2 /var/lib/ghostship-notify/state.json"):
            with self.subTest(command=command):
                self.assertFalse(guard.classify(command, cwd="/root", home="/root").refused)

    def test_the_working_directory_decides_a_relative_read(self):
        self.assertTrue(guard.classify("grep -r token .", cwd="/root", home="/root").refused)
        self.assertFalse(guard.classify("grep -r token .", cwd="/workspace", home="/root").refused)

    def test_an_unparsable_command_is_refused(self):
        verdict = guard.classify("grep -r 'unterminated /etc", cwd="/root", home="/root")
        self.assertTrue(verdict.refused)


class WrapperTests(unittest.TestCase):
    """The wrapper itself: refuse with 126, or execute the command unchanged."""

    def run_guard(self, command, stdin=None, **environment):
        env = {**os.environ, **environment}
        if command is None:
            env.pop("SSH_ORIGINAL_COMMAND", None)
        else:
            env["SSH_ORIGINAL_COMMAND"] = command
        return subprocess.run([sys.executable, str(SCRIPT), "--journal", "/bin/false",
                               "--shell", SESSION_SHELL],
                              env=env, capture_output=True, text=True, timeout=30,
                              stdin=stdin)

    def test_a_refused_command_exits_126_with_a_message(self):
        result = self.run_guard("grep -rl keyword /etc /root")
        self.assertEqual(result.returncode, 126)
        self.assertIn("refused", result.stderr.lower())
        self.assertNotIn("keyword", result.stdout)

    def test_an_allowed_command_runs_unchanged(self):
        result = self.run_guard("echo guard-ok")
        self.assertEqual(result.returncode, 0)
        self.assertIn("guard-ok", result.stdout)

    def test_the_sftp_server_command_is_executed_unchanged(self):
        result = self.run_guard(f"{ECHO} sftp-server")
        self.assertEqual(result.returncode, 0)
        self.assertIn("sftp-server", result.stdout)

    def test_the_sshng_transport_command_runs_unchanged(self):
        """The ssh-ng transport runs `nix-daemon --stdio` on the host."""
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / "nix-daemon"
            stub.write_text("#!/bin/sh\nprintf 'nix-daemon %s\\n' \"$*\"\n")
            stub.chmod(0o700)
            result = self.run_guard("nix-daemon --stdio", PATH=f"{directory}:{os.environ['PATH']}")
        self.assertEqual(result.returncode, 0)
        self.assertIn("nix-daemon --stdio", result.stdout)

    def test_a_session_without_a_command_starts_a_shell(self):
        """An interactive session sends no SSH_ORIGINAL_COMMAND."""
        result = self.run_guard(None, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("refused", result.stderr.lower())


class ShellTests(unittest.TestCase):
    """The shell a session runs in."""

    def test_the_pinned_shell_is_used(self):
        self.assertEqual(guard.login_shell("/bin/true"), "/bin/true")

    def test_a_session_always_has_a_shell_that_exists(self):
        """The account's shell may name a path the machine does not have."""
        shell = guard.login_shell()
        self.assertTrue(os.path.exists(shell), shell)


class PruneTests(unittest.TestCase):
    """A copy of the agent key outside the managed file would bypass the guard."""

    MATERIAL = "AAAAC3NzaC1lZDI1NTE5AAAAIAPNLcXkA3IdqGKkbpWyl2xd4v5cCqzp8OblCDILPlL8"
    # A role placeholder with synthetic key material: the repository is public
    # and holds no personal identifier.
    OWNER = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFIXTUREOWNERKEYMATERIALFORTHETESTONLY owner@example.invalid"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / "authorized_keys"
        self.file.write_text(
            f"{self.OWNER}\n"
            f"ssh-ed25519 {self.MATERIAL} agent-workspace@ghostship\n"
            f"command=\"/nix/store/guard/bin/ghostship-ssh-command-guard\" ssh-ed25519 {self.MATERIAL} agent-workspace@ghostship\n")
        os.chmod(self.file, 0o600)

    def test_prune_removes_the_unguarded_copy_only(self):
        guard.prune(str(self.file), [self.MATERIAL])
        lines = self.file.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn(self.OWNER, lines[0])
        self.assertTrue(lines[1].startswith("command="))
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_prune_is_idempotent_and_leaves_other_files_alone(self):
        guard.prune(str(self.file), [self.MATERIAL])
        before = self.file.read_text()
        guard.prune(str(self.file), [self.MATERIAL])
        self.assertEqual(self.file.read_text(), before)

    def test_prune_does_nothing_without_materials(self):
        before = self.file.read_text()
        guard.prune(str(self.file), [])
        self.assertEqual(self.file.read_text(), before)


if __name__ == "__main__":
    unittest.main()
