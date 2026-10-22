"""Guard the agent SSH key against recursive host searches.

The agent key on the host runs this program as its forced command. It reads
SSH_ORIGINAL_COMMAND, refuses the recursive content reads the host policy
forbids, and otherwise executes the command unchanged.

The policy is "read named files only". A recursive content read rooted at
/etc, /root, /home, /var/lib or / reaches credential databases and private
state, so those are refused with exit status 126 and a journal line. Named
single files stay readable, and interactive sessions, scp, sftp,
`nix-store --serve` and `ssh-ng` transfers keep working.

Refused shapes (each one is a recursive read of protected state):

  grep -r/-R/--recursive PATTERN /etc      recursive content read
  rg PATTERN /root                          ripgrep reads recursively
  find /etc                                 recursion without -maxdepth 1
  find /etc -exec cat {} \\;                recursion that reads file contents
  cat /etc/shadow, cat /etc/gshadow          credential database read
"""
from __future__ import annotations

import argparse
import os
import pwd
import re
import shlex
import subprocess
import sys
from pathlib import Path

# Roots a recursive content read may not be rooted at. "/" covers every path,
# so a search rooted there reaches all of them.
PROTECTED_ROOTS = ("/etc", "/root", "/home", "/var/lib")
# Credential databases, including the rotated copies.
CREDENTIAL_FILE = re.compile(r"^/etc/(?:gshadow|shadow)(?:[-.*].*)?$")

GREP_TOOLS = {"grep", "egrep", "fgrep", "zgrep", "rgrep", "ugrep"}
RIPGREP_TOOLS = {"rg", "ripgrep"}
# Shells a session falls back to when the account's shell is missing.
FALLBACK_SHELLS = ("/bin/sh", "/bin/bash", "/usr/bin/bash")
# Tools that read file contents. Only these are checked for credential files,
# so listing a name is not treated as reading it.
CONTENT_READERS = {
    "awk", "base64", "cat", "cp", "cut", "dd", "diff", "file", "head", "install",
    "less", "md5sum", "more", "nl", "od", "rsync", "sed", "sha256sum", "strings",
    "tail", "tar", "tee", "wc", "xxd",
}
# Tools that only run another command.
WRAPPERS = {"command", "doas", "env", "exec", "ionice", "nice", "nohup", "setsid",
            "stdbuf", "sudo", "time", "timeout", "unbuffer"}
# Shells that take a command string with -c.
SHELLS = {"sh", "bash", "zsh", "ksh", "dash", "ash", "busybox"}
# Options that consume the following token, so it is not a path.
GREP_VALUE_OPTIONS = {
    "-e", "--regexp", "-f", "--file", "-m", "--max-count", "-A", "--after-context",
    "-B", "--before-context", "-C", "--context", "--include", "--exclude",
    "--exclude-from", "--exclude-dir", "--include-dir", "--binary-files", "--devices",
    "--label", "--colour", "--color",
}
RIPGREP_VALUE_OPTIONS = GREP_VALUE_OPTIONS | {
    "-g", "--glob", "--iglob", "-t", "--type", "--type-list", "--max-depth", "--maxdepth",
    "--max-filesize", "--ignore-file", "--engine", "--encoding", "--pre", "--sort",
    "--dfa-size-limit", "--regex-size-limit", "--field-context-separator",
    "--field-match-separator",
}
FIND_VALUE_OPTIONS = {
    "-mindepth", "-name", "-iname", "-path", "-ipath", "-type", "-size", "-newer",
    "-newermt", "-user", "-group", "-perm", "-printf", "-links", "-inum", "-samefile",
    "-regex", "-iregex", "-lname", "-ilname", "-wholename", "-iwholename", "-fstype",
    "-xdev", "-follow", "-delete", "-fprint", "-fprintf", "-fprint0", "-fls",
}


class Verdict:
    """The classification of one command string."""

    def __init__(self, refused: bool, reason: str = ""):
        self.refused = refused
        self.reason = reason

    def __repr__(self) -> str:
        return f"Verdict(refused={self.refused!r}, reason={self.reason!r})"

    @classmethod
    def allow(cls) -> "Verdict":
        return cls(False)

    @classmethod
    def refuse(cls, reason: str) -> "Verdict":
        return cls(True, reason)


def protected(path: str) -> bool:
    """True when a path is inside a protected root."""
    if path == "/":
        return True
    return any(path == root or path.startswith(root + "/") for root in PROTECTED_ROOTS)


def absolute(path: str, cwd: str, home: str) -> str:
    """Resolve a command argument to an absolute path."""
    if not path:
        return path
    if path == "~":
        path = home
    elif path.startswith("~/"):
        path = os.path.join(home, path[2:])
    if not path.startswith("/"):
        path = os.path.join(cwd, path)
    return os.path.normpath(path)


def credential(path: str, cwd: str, home: str) -> bool:
    """True when a path names a credential database."""
    return bool(CREDENTIAL_FILE.match(absolute(path, cwd, home)))


def tokenize(command: str) -> list[str]:
    """Split a command into shell tokens, keeping the operators separate."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";|&\n")
    lexer.whitespace_split = True
    return list(lexer)


def is_operator(token: str) -> bool:
    return bool(token) and all(character in ";|&" for character in token)


def recursive_option(token: str) -> bool:
    """True when a grep option makes the search recursive."""
    if token in ("--recursive", "--dereference-recursive"):
        return True
    if not token.startswith("-") or token.startswith("--"):
        return False
    return "r" in token[1:] or "R" in token[1:]


def split_options(tokens: list[str], value_options: set[str]) -> tuple[list[str], list[str]]:
    """Return the option tokens and the positional arguments."""
    options: list[str] = []
    positionals: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            positionals.extend(tokens[index + 1:])
            break
        if token.startswith("-") and token != "-":
            options.append(token)
            if token in value_options and index + 1 < len(tokens):
                index += 1
                options.append(tokens[index])
        else:
            positionals.append(token)
        index += 1
    return options, positionals


def grep_paths(tokens: list[str], pattern_from_option: bool) -> list[str]:
    """The search paths of a grep-family command."""
    _, positionals = split_options(tokens, GREP_VALUE_OPTIONS)
    if not pattern_from_option and positionals:
        positionals = positionals[1:]
    return positionals


def parse_find(tokens: list[str]) -> tuple[list[str], bool, list[str]]:
    """Return the roots, whether the search is limited to one level, and the
    content-reading commands an -exec would run."""
    roots: list[str] = []
    readers: list[str] = []
    maxdepth_one = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            roots.extend(tokens[index + 1:])
            break
        if token in ("-exec", "-execdir", "-ok", "-okdir"):
            command: list[str] = []
            index += 1
            while index < len(tokens) and tokens[index] not in (";", "+"):
                command.append(tokens[index])
                index += 1
            if command and command[0] in CONTENT_READERS:
                readers.append(command[0])
            index += 1
            continue
        if token in ("-maxdepth", "-mindepth"):
            if token == "-maxdepth" and index + 1 < len(tokens) and tokens[index + 1] == "1":
                maxdepth_one = True
            index += 2
            continue
        if token.startswith("-") and token != "-":
            index += 2 if token in FIND_VALUE_OPTIONS else 1
            continue
        roots.append(token)
        index += 1
    return roots, maxdepth_one, readers


def tool_of(tokens: list[str]) -> tuple[str, list[str]]:
    """The command of a segment and the tokens that follow it."""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if "=" in token and not token.startswith("-") and token.split("=", 1)[0].isidentifier():
            index += 1
            continue
        break
    if index >= len(tokens):
        return "", []
    command = tokens[index]
    rest = tokens[index + 1:]
    while command in WRAPPERS and rest:
        command = rest[0]
        rest = rest[1:]
    return command, rest


def classify(command: str, cwd: str = "/root", home: str | None = None) -> Verdict:
    """Classify one command string against the host's read policy."""
    home = home or cwd
    try:
        tokens = tokenize(command)
    except ValueError:
        return Verdict.refuse("the command could not be parsed, so it cannot be shown to be safe")
    if not tokens:
        return Verdict.allow()
    working = cwd
    segments: list[list[str]] = [[]]
    for token in tokens:
        if is_operator(token):
            segments.append([])
            continue
        segments[-1].append(token)
    for segment in segments:
        if not segment:
            continue
        name, rest = tool_of(segment)
        if name == "cd" and rest:
            working = absolute(rest[0], working, home)
            continue
        verdict = classify_segment(name, rest, segment, working, home)
        if verdict.refused:
            return verdict
    return Verdict.allow()


def classify_segment(name: str, rest: list[str], segment: list[str], cwd: str, home: str) -> Verdict:
    """Classify one command of a compound command line."""
    if not name:
        return Verdict.allow()
    base = os.path.basename(name)
    if base in SHELLS and "-c" in rest:
        index = rest.index("-c")
        if index + 1 < len(rest):
            return classify(rest[index + 1], cwd=cwd, home=home)
        return Verdict.allow()
    if base == "xargs" and rest:
        return classify_segment(rest[0], rest[1:], rest, cwd, home)
    if base in GREP_TOOLS:
        options, _ = split_options(rest, GREP_VALUE_OPTIONS)
        if not any(recursive_option(option) for option in options):
            return Verdict.allow()
        pattern_from_option = any(option in ("-e", "--regexp", "-f", "--file")
                                  for option in options)
        paths = grep_paths(rest, pattern_from_option)
        for path in paths:
            if protected(absolute(path, cwd, home)):
                return Verdict.refuse(
                    f"a recursive search rooted at {absolute(path, cwd, home)} reads protected host state")
        if not paths and protected(cwd):
            return Verdict.refuse(
                f"a recursive search in {cwd} reads protected host state")
        return Verdict.allow()
    if base in RIPGREP_TOOLS:
        options, positionals = split_options(rest, RIPGREP_VALUE_OPTIONS)
        pattern_from_option = any(option in ("-e", "--regexp", "-f", "--file")
                                  for option in options)
        paths = positionals[1:] if not pattern_from_option and positionals else positionals
        for path in paths:
            if protected(absolute(path, cwd, home)):
                return Verdict.refuse(
                    f"a recursive search rooted at {absolute(path, cwd, home)} reads protected host state")
        if not paths and protected(cwd):
            return Verdict.refuse(
                f"a recursive search in {cwd} reads protected host state")
        return Verdict.allow()
    if base == "find":
        roots, maxdepth_one, readers = parse_find(rest)
        sensitive = [absolute(root, cwd, home) for root in roots if protected(absolute(root, cwd, home))]
        if sensitive:
            if not maxdepth_one:
                return Verdict.refuse(
                    f"a recursive search rooted at {sensitive[0]} reads protected host state")
            if readers:
                return Verdict.refuse(
                    f"a search rooted at {sensitive[0]} reads file contents with {readers[0]}")
        if readers and any(absolute(root, cwd, home) == "/" for root in roots):
            return Verdict.refuse(
                f"a search rooted at / reads file contents with {readers[0]}")
        return Verdict.allow()
    if base in CONTENT_READERS:
        for token in segment:
            if credential(token, cwd, home):
                return Verdict.refuse(
                    f"{absolute(token, cwd, home)} is a credential database")
    return Verdict.allow()


def login_shell(override: str | None = None) -> str:
    """The shell a session runs in.

    The host may pin the shell. Otherwise the account's login shell is used
    when it is there: an account may name a shell the host does not have, and
    a container or a build sandbox has no account database at all, which would
    leave the session without a shell to run in.
    """
    if override:
        return override
    candidates = []
    try:
        candidates.append(pwd.getpwuid(os.getuid()).pw_shell)
    except KeyError:
        pass
    candidates.extend(FALLBACK_SHELLS)
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return FALLBACK_SHELLS[0]


def run_login_shell(shell: str) -> int:
    """Start the login shell, as sshd does for a session without a command."""
    os.execv(shell, ["-" + os.path.basename(shell)])


def run_command(command: str, shell: str) -> int:
    """Run the requested command through the login shell, as sshd does."""
    os.execv(shell, [os.path.basename(shell), "-c", command])


def journal(program: str, message: str) -> None:
    """Record the refusal in the journal.

    systemd-cat runs its positional arguments as a command, so the message
    goes on stdin. Its own output is dropped, so a journal failure never
    mixes into the refusal the caller reads.
    """
    try:
        subprocess.run([program, "-t", "ghostship-ssh-command-guard", "-p", "warning"],
                       input=message + "\n", text=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def prune(path: str, materials: list[str]) -> int:
    """Remove unguarded copies of the guarded keys from an authorized keys file.

    sshd stops at the first authorized keys file that holds the key, so a copy
    without the forced command would authorize the agent key without the
    guard. The managed file keeps the guarded entry, so the copy is redundant.
    """
    target = Path(path)
    if not materials or not target.exists():
        return 0
    original = target.read_text()
    kept = []
    removed = 0
    for line in original.splitlines():
        if "command=" not in line and any(material in line for material in materials):
            removed += 1
            continue
        kept.append(line)
    if not removed:
        return 0
    temporary = target.with_name(target.name + ".guard-tmp")
    temporary.write_text("".join(f"{line}\n" for line in kept))
    os.chmod(temporary, target.stat().st_mode & 0o7777)
    os.replace(temporary, target)
    print(f"removed {removed} unguarded agent key entr{'y' if removed == 1 else 'ies'} from {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostship-ssh-command-guard", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--journal", default="/run/current-system/sw/bin/systemd-cat",
                        help="systemd-cat used to record a refusal")
    parser.add_argument("mode", nargs="?", default="guard", choices=("guard", "prune"),
                        help="guard runs a session command; prune removes unguarded key copies")
    parser.add_argument("--file", help="authorized keys file to prune")
    parser.add_argument("--material", action="append", default=[],
                        help="key material that must only be authorized through the guard")
    parser.add_argument("--shell",
                        help="the shell a session runs in; the account's login shell by default")
    args = parser.parse_args(argv)
    if args.mode == "prune":
        if not args.file:
            parser.error("prune needs --file")
        return prune(args.file, args.material)
    original = os.environ.get("SSH_ORIGINAL_COMMAND")
    shell = login_shell(args.shell)
    if original is None or not original.strip():
        run_login_shell(shell)
        return 0
    verdict = classify(original, cwd=os.getcwd(), home=os.path.expanduser("~"))
    if verdict.refused:
        message = (f"refused: {verdict.reason}. Agent sessions may read named files only; "
                   "they may not search the host recursively.")
        print(message, file=sys.stderr)
        journal(args.journal, f"{os.uname().nodename} {message} Command: {original[:512]}")
        return 126
    run_command(original, shell)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
