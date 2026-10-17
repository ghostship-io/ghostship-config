"""Run the actual installer functions with disposable registry/native fixtures."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "modules/self-hosted/t3code.nix").read_text()
# The Nix build sandbox has no /usr/bin/env; fixtures run under this interpreter.
SHEBANG = f"#!{sys.executable}"


def installer_functions():
    source = SOURCE[SOURCE.index("    opencode_loader_name() {"):SOURCE.index("    install_user_shim() {")]
    source = textwrap.dedent(source).replace("''${", "${")
    source = source.replace("${sourceHmSessionVarsIfPresent}", "")
    source = re.sub(r"\$\{pkgs\.[\w]+\}/bin/", "", source)
    # Generated launchers use /usr/bin/env, which the Nix build sandbox lacks.
    # Fixture "native" binaries are scripts; never run them through a host glibc loader.
    source += "\nfind_nix_glibc_loader() { return 1; }\n"
    return source.replace("#!/usr/bin/env sh", "#!/bin/sh")


class OpenCodeUpdater(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.assertIsNotNone(shutil.which("pgrep"), "process guard tests require procps")
        # Scope the process guard to this test's fixture; real host jobs must not
        # make an isolated promotion test defer activation.
        self.script("pgrep", f'''            #!/usr/bin/env python3
            import os, subprocess, sys
            result = subprocess.run([{shutil.which("pgrep")!r}, *sys.argv[1:]], capture_output=True, text=True)
            allowed = os.environ.get("ALLOWED_PROCESS_PID")
            sys.exit(0 if allowed and allowed in result.stdout.splitlines() else 1)
        ''')
        self.data = self.root / "data"
        self.releases = self.data / "t3code-tools/opencode/releases"
        self.old = self.releases / "2.0.20"
        self.old.mkdir(parents=True)
        self.current = self.releases.parent / "current"
        self.current.symlink_to(self.old)
        self.prefix = self.root / "npm"
        (self.prefix / "bin").mkdir(parents=True)
        self.launcher = self.prefix / "bin/opencode"
        self.launcher.write_text("#!/bin/sh\nprintf 'legacy\\n'\n")
        self.launcher.chmod(0o755)
        self.script("npm", '''
            #!/usr/bin/env python3
            import json, os, pathlib, sys
            args = sys.argv[1:]
            with open(os.environ["INSTALL_LOG"], "a") as log:
                log.write(json.dumps(args) + "\\n")
            prefix = pathlib.Path(args[args.index("--prefix") + 1])
            assert "--ignore-scripts" in args and "--omit=optional" in args
            version = os.environ.get("EXPECTED_VERSION", "2.0.30")
            assert "@opencode/cli@" + version in args
            native = next(a.rsplit("@", 1)[0] for a in args if a.startswith("@opencode/cli-linux-"))
            assert native + "@" + version in args
            for name in ("@opencode/cli", native):
                dest = prefix / "lib/node_modules" / name
                dest.mkdir(parents=True)
                (dest / "package.json").write_text(json.dumps({"version": version}))
            binary = prefix / "lib/node_modules" / native / "bin/opencode"
            binary.parent.mkdir()
            binary.write_text(os.environ["NATIVE_FIXTURE"])
            binary.chmod(0o755)
        ''')
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "HOME": str(self.root / "home"),
            "XDG_DATA_HOME": str(self.data),
            "NPM_CONFIG_PREFIX": str(self.prefix),
            "INSTALL_LOG": str(self.root / "installs.log"),
            "OPENCODE_ALLOW_V2_MIGRATION": "1",
            "OPENCODE_CONFIG_CONTENT": "must not reach probe",
            "OPENCODE_DB": "/must/not/open/real/database",
            "NATIVE_FIXTURE": self.native(),
        }

    def script(self, name, source):
        target = self.bin / name
        target.write_text(textwrap.dedent(source).lstrip().replace("#!/usr/bin/env python3", SHEBANG))
        target.chmod(0o755)

    def native(self, mode="healthy"):
        return textwrap.dedent('''\
            #!/usr/bin/env python3
            import base64, http.server, json, os, pathlib, sys, time
            assert "OPENCODE_DB" not in os.environ
            assert os.environ["OPENCODE_DISABLE_AUTOUPDATE"] == "1"
            assert "OPENCODE_CONFIG_CONTENT" not in os.environ
            assert pathlib.Path.cwd() == pathlib.Path(os.environ["HOME"])
            for key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "TMPDIR"):
                assert os.environ[key].startswith(os.environ["HOME"] + "/")
            if sys.argv[1] == "--version":
                print("opencode v" + VERSION)
                sys.exit(0)
            pathlib.Path(SERVER_PID_FILE).write_text(str(os.getpid()))
            if MODE == "crash":
                sys.exit(23)
            if MODE == "leak":
                password = os.environ["OPENCODE_SERVER_PASSWORD"]
                pathlib.Path(PASSWORD_FILE).write_text(password)
                print("probe password " + password, file=sys.stderr)
                sys.exit(23)
            if MODE == "hang":
                time.sleep(120)
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    assert self.path == "/api/info"
                    expected = "Basic " + base64.b64encode(("opencode:" + os.environ["OPENCODE_SERVER_PASSWORD"]).encode()).decode()
                    assert self.headers["Authorization"] == expected
                    body = json.dumps({"version": VERSION, "pid": os.getpid()}).encode()
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(body)
                def log_message(self, *args):
                    pass
            http.server.HTTPServer(("127.0.0.1", int(sys.argv[-1])), Handler).serve_forever()
        ''').replace("#!/usr/bin/env python3", SHEBANG).replace("VERSION", repr("2.0.30")).replace("MODE", repr(mode)).replace("SERVER_PID_FILE", repr(str(self.root / "probe.pid"))).replace("PASSWORD_FILE", repr(str(self.root / "probe.password")))

    def run_installer(self, stage_cli=False, **env):
        script = "set -eu\nlog_info() { printf '%s\\n' \"$1\" >&2; }\nlog_warn() { log_info \"$1\"; }\n"
        script += installer_functions()
        script += '\nlatest_agent_version() { [ "$1" = @opencode/cli ]; printf "%s\\n" "${EXPECTED_VERSION:-2.0.30}"; }\n'
        if stage_cli:
            dispatch = SOURCE[SOURCE.index("    # A canary run"):SOURCE.index('    mkdir -p "$HOME/.local/bin" "$XDG_CONFIG_HOME"')]
            script += textwrap.dedent(dispatch).replace("''${", "${")
            script += "exit 99\n"  # Reaching normal provider maintenance is a failure.
        else:
            script += "install_opencode_cli\n"
        return subprocess.run(["bash", "-c", script, "--", "--stage-opencode"], env={**self.env, **env}, capture_output=True, text=True, timeout=60)

    def test_success_promotes_atomically_and_retains_old_release_and_legacy_package(self):
        legacy = self.prefix / "lib/node_modules/opencode-ai"
        legacy.mkdir(parents=True)
        (legacy / "retained").touch()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current.resolve(), self.releases / "2.0.30")
        self.assertEqual(self.launcher.resolve(), self.current.resolve() / "bin/opencode")
        self.assertTrue(self.old.is_dir())
        self.assertTrue((legacy / "retained").exists())
        self.assertFalse(list(self.releases.parent.glob(".staging.*")))
        # The promoted executable resolves its immutable prefix even via npm's link.
        version_env = {"PATH": self.env["PATH"], "HOME": str(self.root), "OPENCODE_DISABLE_AUTOUPDATE": "1"}
        version_env.update({key: str(self.root / key) for key in
                            ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "TMPDIR")})
        version = subprocess.run([str(self.launcher), "--version"], env=version_env, cwd=self.root, text=True, capture_output=True)
        self.assertNotIn("No such file", version.stderr)
        self.assertEqual(version.stdout.strip(), "opencode v2.0.30")

    def test_failed_launcher_replacement_rolls_back_current(self):
        self.script("mv", f'''
            #!/usr/bin/env python3
            import os, sys
            if sys.argv[-1] == {str(self.launcher)!r}:
                sys.exit(1)
            os.execv({shutil.which("mv")!r}, ["mv", *sys.argv[1:]])
        ''')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertFalse(self.launcher.is_symlink())

    def test_damaged_existing_release_is_retained_during_repair(self):
        damaged = self.releases / "2.0.30"
        damaged.mkdir()
        (damaged / "retained").write_text("old mapped executable")
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.current.resolve(), damaged)
        self.assertTrue(self.current.resolve().name.startswith("2.0.30-repair-"))
        self.assertEqual((damaged / "retained").read_text(), "old mapped executable")

    def test_failed_serve_probe_preserves_current_and_legacy_executable(self):
        result = self.run_installer(NATIVE_FIXTURE=self.native("crash"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertEqual(self.launcher.read_text(), "#!/bin/sh\nprintf 'legacy\\n'\n")
        self.assertFalse((self.releases / "2.0.30").exists())
        self.assertFalse(list(self.releases.parent.glob(".staging.*")))

    def test_hung_serve_probe_times_out_and_reaps_its_process(self):
        started = time.monotonic()
        result = self.run_installer(NATIVE_FIXTURE=self.native("hang"))
        self.assertNotEqual(result.returncode, 0)
        self.assertLess(time.monotonic() - started, 40)
        self.assertIn("within 30s", result.stderr)
        self.assertEqual(self.current.resolve(), self.old)
        pid = int((self.root / "probe.pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_version_probe_failure_preserves_current(self):
        result = self.run_installer(NATIVE_FIXTURE=self.native().replace("'2.0.30'", "'1.19.2'"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)

    def test_wrong_major_is_rejected_before_npm_install(self):
        for version in ("1.19.2", "3.0.0", "2.1.0-beta.1", "../../bad"):
            with self.subTest(version=version):
                result = self.run_installer(EXPECTED_VERSION=version)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "installs.log").exists())
                self.assertEqual(self.current.resolve(), self.old)

    def test_stage_only_preserves_both_active_links(self):
        result = self.run_installer(OPENCODE_STAGE_ONLY="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertFalse(self.launcher.is_symlink())
        self.assertTrue((self.releases / "2.0.30/bin/opencode").is_file())

    def test_staging_command_exits_before_regular_provider_maintenance(self):
        result = self.run_installer(stage_cli=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertFalse(self.launcher.is_symlink())
        self.assertTrue((self.releases / "2.0.30/bin/opencode").is_file())

    def test_clean_home_activates_without_migration_flag(self):
        self.current.unlink()
        self.launcher.unlink()
        result = self.run_installer(OPENCODE_ALLOW_V2_MIGRATION="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current.resolve(), self.releases / "2.0.30")
        self.assertEqual(self.launcher.resolve(), self.current.resolve() / "bin/opencode")
        self.assertTrue(os.access(self.launcher, os.X_OK))

    def test_existing_database_requires_migration_flag_without_legacy_launcher(self):
        self.current.unlink()
        self.launcher.unlink()
        database = self.data / "opencode/opencode.db"
        database.parent.mkdir(parents=True)
        database.write_text("existing database")
        result = self.run_installer(OPENCODE_ALLOW_V2_MIGRATION="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.current.exists())
        self.assertFalse(self.launcher.exists())
        self.assertEqual(database.read_text(), "existing database")
        self.assertIn("consistent database backup", result.stderr)

    def test_failed_probe_redacts_its_password(self):
        result = self.run_installer(NATIVE_FIXTURE=self.native("leak"))
        self.assertNotEqual(result.returncode, 0)
        password = (self.root / "probe.password").read_text()
        self.assertNotIn(password, result.stderr)
        self.assertIn("probe password [redacted]", result.stderr)
        self.assertEqual(self.current.resolve(), self.old)

    def test_first_v2_activation_requires_explicit_migration_authorization(self):
        self.current.unlink()
        result = self.run_installer(OPENCODE_ALLOW_V2_MIGRATION="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.current.exists())
        self.assertFalse(self.launcher.is_symlink())
        self.assertIn("consistent database backup", result.stderr)

    def test_running_opencode_process_defers_activation(self):
        process = subprocess.Popen([sys.executable, "-u", "-c",
            "import ctypes,time; ctypes.CDLL(None).prctl(15,b'opencode',0,0,0); print('ready'); time.sleep(60)"], stdout=subprocess.PIPE, text=True)
        self.assertEqual(process.stdout.readline().strip(), "ready")
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.wait)
        self.addCleanup(process.terminate)
        result = self.run_installer(ALLOWED_PROCESS_PID=str(process.pid))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertIn("running OpenCode processes", result.stderr)


if __name__ == "__main__":
    unittest.main()
