import importlib.util
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("private_inputs", ROOT / "scripts/private-inputs.py")
PRIVATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PRIVATE)
CHECK_SPEC = importlib.util.spec_from_file_location("check_privacy", ROOT / "scripts/check-privacy.py")
CHECK = importlib.util.module_from_spec(CHECK_SPEC)
CHECK_SPEC.loader.exec_module(CHECK)

NIX = shutil.which("nix")

# The specimens are assembled rather than written out, so this file carries no
# literal that the published tree check would report.
SPECIMEN_REPOSITORY = "example/" + "private-project"
SPECIMEN_REVISION = "0" * 40


def nix(*arguments):
    return subprocess.run(
        ["nix", *arguments], capture_output=True, text=True, check=False
    )


@unittest.skipIf(NIX is None, "nix is not available")
class ImporterDurabilityTest(unittest.TestCase):
    """The importer must leave a resolution that survives its own exit.

    The defect this covers was an importer that pointed the lock at a working
    directory it then deleted, so the evaluation that followed the importer had
    nothing to resolve.
    """

    def make_source(self, directory):
        source = pathlib.Path(directory) / "source"
        (source / "lib").mkdir(parents=True)
        (source / "flake.nix").write_text(
            '{\n  outputs = { self }: { marker = "synthetic-source"; };\n}\n')
        (source / "lib" / "value.nix").write_text('"synthetic"\n')
        return source

    def test_the_store_copy_survives_the_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_source(directory)
            digest = nix("hash", "path", str(source)).stdout.strip()
            entry = {"narHash": digest, "lastModified": 0}
            store_path = PRIVATE.import_into_store(source, entry)
            self.assertTrue(store_path.startswith("/nix/store/"))
            self.assertTrue(pathlib.Path(store_path).is_dir())
            # The working directory is gone; the store copy is not.
            shutil.rmtree(directory)
            self.assertTrue(pathlib.Path(store_path).is_dir())
            listed = nix("path-info", store_path).stdout.strip()
            self.assertIn(store_path, listed)

    def test_an_evaluation_resolves_after_the_importer_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            source = self.make_source(base / "work")
            digest = nix("hash", "path", str(source)).stdout.strip()
            entry = {"narHash": digest, "lastModified": 0}
            store_path = PRIVATE.import_into_store(source, entry)

            consumer = base / "consumer"
            consumer.mkdir()
            (consumer / "flake.nix").write_text(
                (
                    '{\n'
                    '  inputs.src.url = "path:@STORE@";\n'
                    '  outputs = { self, src }: { marker = src.marker; };\n'
                    '}\n'
                ).replace("@STORE@", store_path)
            )
            subprocess.run(["git", "init", "-q", str(consumer)], check=True)
            subprocess.run(["git", "-C", str(consumer), "add", "-A"], check=True)
            subprocess.run(
                ["git", "-C", str(consumer), "-c", "user.name=t", "-c", "user.email=t@localhost",
                 "commit", "-qm", "consumer"],
                check=True,
            )
            # The working directory of the importer is removed before the
            # evaluation, exactly as the importer does.
            shutil.rmtree(base / "work")
            result = nix("eval", "--no-write-lock-file", "--raw", str(consumer) + "#marker")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "synthetic-source")

    def test_a_content_hash_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_source(directory)
            entry = {"narHash": "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                     "lastModified": 0}
            with self.assertRaises(PRIVATE.StepError):
                PRIVATE.import_into_store(source, entry)


@unittest.skipIf(NIX is None, "Nix integration tests run before source import in CI")
class PublicEvaluationTest(unittest.TestCase):
    """The public tree must evaluate without the private source.

    A continuous integration job that runs the browser tests, or any other
    check that does not use the private source, failed because the committed
    placeholder could not be resolved. The placeholder resolves, so those jobs
    need no credential at all.
    """

    def test_the_placeholder_directory_is_committed_and_resolves(self):
        placeholder = ROOT / "private-agent-source" / "flake.nix"
        self.assertTrue(placeholder.is_file())
        result = nix("flake", "metadata", str(ROOT / "private-agent-source"), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_development_shell_evaluates_without_the_private_source(self):
        result = nix(
            "eval", "--no-write-lock-file", "--raw",
            str(ROOT) + "#devShells.x86_64-linux.ci.drvPath",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().startswith("/nix/store/"))

    def test_the_evaluation_that_needs_the_private_source_says_so(self):
        result = nix(
            "eval", "--no-write-lock-file", "--raw",
            str(ROOT) + "#nixosConfigurations.chill-penguin.config.system.build.toplevel.drvPath",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("private agent source was not supplied", result.stderr)


class PlaceholderInvariantTest(unittest.TestCase):
    """The published tree must never name a private source."""

    def build_tree(self, directory, flake_nix):
        base = pathlib.Path(directory)
        (base / "secrets").mkdir(parents=True, exist_ok=True)
        (base / "flake.nix").write_text(flake_nix)
        (base / "flake.lock").write_text(json.dumps({
            "nodes": {
                "ghostship-private-agent": {
                    "locked": dict(PRIVATE.LOCKED_PLACEHOLDER),
                    "original": dict(PRIVATE.ORIGINAL_PLACEHOLDER),
                },
                "root": {"inputs": {"ghostship-private-agent": "ghostship-private-agent"}},
            },
            "root": "root",
            "version": 7,
        }, indent=2) + "\n")
        subprocess.run(["git", "init", "-q", str(base)], check=True)
        subprocess.run(["git", "-C", str(base), "config", "core.hooksPath", "/dev/null"], check=True)
        subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(base), "-c", "user.name=t", "-c", "user.email=t@localhost",
             "commit", "-qm", "tree"],
            check=True,
        )
        return base

    def test_a_placeholder_tree_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            base = self.build_tree(
                directory,
                '{\n  inputs.ghostship-private-agent.url = "path:./private-agent-source";\n}\n',
            )
            previous = os.getcwd()
            os.chdir(base)
            try:
                PRIVATE.require_committed_placeholder()
            finally:
                os.chdir(previous)

    def test_a_committed_private_source_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            base = self.build_tree(
                directory,
                '{\n  inputs.ghostship-private-agent.url = '
                '"github:' + SPECIMEN_REPOSITORY + "/" + SPECIMEN_REVISION + '";\n}\n',
            )
            previous = os.getcwd()
            os.chdir(base)
            try:
                with self.assertRaises(PRIVATE.StepError):
                    PRIVATE.require_committed_placeholder()
            finally:
                os.chdir(previous)

    def test_a_committed_lock_without_the_placeholder_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            base = self.build_tree(
                directory,
                '{\n  inputs.ghostship-private-agent.url = "path:./private-agent-source";\n}\n',
            )
            lock = json.loads((base / "flake.lock").read_text())
            lock["nodes"]["ghostship-private-agent"]["locked"] = {
                "lastModified": 1,
                "narHash": "sha256-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=",
                "owner": "example",
                "repo": SPECIMEN_REPOSITORY.split("/")[1],
                "rev": SPECIMEN_REVISION,
                "type": "github",
            }
            (base / "flake.lock").write_text(json.dumps(lock, indent=2) + "\n")
            subprocess.run(["git", "-C", str(base), "add", "-A"], check=True)
            subprocess.run(
                ["git", "-C", str(base), "-c", "user.name=t", "-c", "user.email=t@localhost",
                 "commit", "-qm", "lock"],
                check=True,
            )
            previous = os.getcwd()
            os.chdir(base)
            try:
                with self.assertRaises(PRIVATE.StepError):
                    PRIVATE.require_committed_placeholder()
            finally:
                os.chdir(previous)


class CommittedLockPolicyTest(unittest.TestCase):
    """A second source must not hide behind the managed placeholder node."""

    build_tree = PlaceholderInvariantTest.build_tree

    def test_additional_unapproved_sources_fail_both_command_guards(self):
        for kind in ("locked", "original", "unsupported", "extra-fields"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                base = self.build_tree(
                    directory,
                    '{ inputs.ghostship-private-agent.url = "path:./private-agent-source"; }',
                )
                lock = json.loads((base / "flake.lock").read_text())
                locked = dict(zip(("owner", "repo", "rev", "narHash", "type"),
                                  ("NixOS", "nixpkgs", "0" * 40,
                                   "sha256-" + "A" * 43 + "=", "github")))
                original = dict(zip(("owner", "repo", "type"),
                                    ("NixOS", "nixpkgs", "github")))
                if kind == "locked":
                    locked["repo"] = "synthetic-unapproved-source"
                elif kind == "original":
                    original["repo"] = "synthetic-unapproved-source"
                elif kind == "unsupported":
                    locked = dict(zip(("type", "path"), ("path", "./unapproved")))
                else:
                    locked["unreviewed"] = "synthetic-unapproved-source"
                lock["nodes"]["additional"] = dict(locked=locked, original=original)
                (base / "flake.lock").write_text(json.dumps(lock))
                subprocess.run(["git", "-C", str(base), "add", "-A"], check=True,
                               capture_output=True)
                subprocess.run(
                    ["git", "-C", str(base), "-c", "core.hooksPath=/dev/null",
                     "-c", "user.name=t", "-c", "user.email=t@localhost",
                     "commit", "-qm", "additional source"], check=True, capture_output=True,
                )
                # Both commands inspect this real committed tree. Import must
                # reject it before it asks for any private specification.
                for script, arguments in (("check-privacy.py", []),
                                          ("private-inputs.py", ["apply"])):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "scripts" / script), *arguments],
                        cwd=base, capture_output=True, text=True,
                        env={"PATH": os.environ["PATH"], "HOME": str(base)},
                    )
                    self.assertEqual(result.returncode, 1, script)
                    self.assertNotIn("synthetic-unapproved-source", result.stdout + result.stderr)
                    if script == "private-inputs.py":
                        self.assertIn("public source policy", result.stderr)

    def test_native_parent_input_paths_remain_valid_and_malformed_paths_are_refused(self):
        # Nix 2.34 serializes relative-input ancestry as an InputAttrPath list.
        from source_privacy import validate_lock, PolicyError
        # The Nix config-tests source intentionally has no .git directory.
        # A synthetic public lock keeps this policy regression independent of
        # checkout metadata and private-source substitutions in the caller.
        lock = {
            "version": 7, "root": "root",
            "nodes": {
                "root": {"inputs": {PRIVATE.INPUT: PRIVATE.INPUT, "nixpkgs": "nixpkgs"}},
                PRIVATE.INPUT: {
                    "locked": dict(PRIVATE.LOCKED_PLACEHOLDER),
                    "original": dict(PRIVATE.ORIGINAL_PLACEHOLDER),
                },
                "nixpkgs": {
                    "locked": {"type": "github", "owner": "NixOS", "repo": "nixpkgs",
                               "rev": "0" * 40, "narHash": "sha256-" + "A" * 43 + "="},
                    "original": {"type": "github", "owner": "NixOS", "repo": "nixpkgs"},
                },
            },
        }
        for parent in ([], ["nixpkgs"]):
            candidate = json.loads(json.dumps(lock))
            candidate["nodes"][PRIVATE.INPUT]["parent"] = parent
            with self.subTest(parent=parent):
                validate_lock(json.dumps(candidate))
        for parent in (None, "nixpkgs", [17], ["missing-input"], ["nixpkgs", "missing-input"]):
            candidate = json.loads(json.dumps(lock))
            candidate["nodes"][PRIVATE.INPUT]["parent"] = parent
            with self.subTest(invalid=parent), self.assertRaises(PolicyError):
                validate_lock(json.dumps(candidate))
        candidate = json.loads(json.dumps(lock))
        candidate["nodes"][PRIVATE.INPUT]["unreviewed"] = []
        with self.assertRaises(PolicyError):
            validate_lock(json.dumps(candidate))

    def test_public_sources_and_follows_keep_the_placeholder_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            base = self.build_tree(
                directory, '{ inputs.ghostship-private-agent.url = "path:./private-agent-source"; }')
            lock = json.loads((ROOT / "flake.lock").read_text())
            lock["nodes"][PRIVATE.INPUT]["locked"] = dict(PRIVATE.LOCKED_PLACEHOLDER)
            lock["nodes"][PRIVATE.INPUT]["original"] = dict(PRIVATE.ORIGINAL_PLACEHOLDER)
            lock["nodes"]["public-alias"] = dict(lock["nodes"]["nixpkgs"])
            lock["nodes"]["public-alias"]["inputs"] = {"nixpkgs": ["nixpkgs"]}
            (base / "flake.lock").write_text(json.dumps(lock))
            subprocess.run(["git", "-C", str(base), "add", "-A"], check=True,
                           capture_output=True)
            subprocess.run(
                ["git", "-C", str(base), "-c", "core.hooksPath=/dev/null",
                 "-c", "user.name=t", "-c", "user.email=t@localhost",
                 "commit", "-qm", "public sources"], check=True, capture_output=True,
            )
            previous = os.getcwd()
            os.chdir(base)
            try:
                PRIVATE.require_committed_placeholder()
                findings, _ = CHECK.scan([], files=["flake.lock"])
            finally:
                os.chdir(previous)
            self.assertEqual(findings, [])


class ImporterFailureOutputTest(unittest.TestCase):
    def test_failed_fetch_does_not_report_source_or_subprocess_output(self):
        with tempfile.TemporaryDirectory() as directory:
            base = PlaceholderInvariantTest().build_tree(
                directory, '{ inputs.ghostship-private-agent.url = "path:./private-agent-source"; }')
            specimen = dict(zip(("owner", "repo", "rev", "narHash"),
                                ("example", "synthetic-source", "0" * 40,
                                 "sha256-" + "A" * 43 + "=")))
            specification = base / "spec.json"
            specification.write_text(json.dumps({PRIVATE.INPUT: specimen}))
            real_run = subprocess.run

            def fail_fetch(arguments, *args, **kwargs):
                if "fetch" in arguments:
                    if kwargs.get("check"):
                        raise subprocess.CalledProcessError(1, arguments, stderr=b"synthetic-diagnostic")
                    return subprocess.CompletedProcess(arguments, 1, b"", b"synthetic-diagnostic")
                return real_run(arguments, *args, **kwargs)

            previous = os.getcwd()
            os.chdir(base)
            output = io.StringIO()
            try:
                with mock.patch.object(sys, "argv", ["private-inputs.py", "import", "--spec", str(specification)]), \
                        mock.patch.dict(os.environ, {"GHOSTSHIP_AGENT_READ_KEY": "synthetic", "GITHUB_META_TOKEN": ""}), \
                        mock.patch.object(PRIVATE.urllib.request, "urlopen", return_value=io.BytesIO(b'{"ssh_keys":[]}')), \
                        mock.patch.object(PRIVATE.subprocess, "run", side_effect=fail_fetch), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    result = PRIVATE.main()
            finally:
                os.chdir(previous)
            self.assertEqual(result, 1)
            self.assertIn("fetching the pinned private source", output.getvalue())
            self.assertNotIn(specimen["repo"], output.getvalue())
            self.assertNotIn("synthetic-diagnostic", output.getvalue())


if __name__ == "__main__":
    unittest.main()
