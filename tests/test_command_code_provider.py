"""Catch free-model bypasses, lost native login state, and mutable CLI installations."""

import importlib.util
import json
import os
import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages/t3code/command-code"


def load(name):
    spec = importlib.util.spec_from_file_location(f"command_code_{name}", SOURCE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


acp = load("acp")
setup = load("setup")
PAID = "zai-org/glm-5.2"
FREE = "unreviewed/free-model"


def request(method, params=None, number=1):
    return {"jsonrpc": "2.0", "id": number, "method": method, "params": params or {}}


class PolicyTest(unittest.TestCase):
    def test_stdio_process_filters_catalog_rejects_free_and_forwards_paid_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            node = home / "node"
            node.write_text(f'''#!{sys.executable}
import json, os, sys
assert os.environ['CMD_ZDR'] == '1'
for line in sys.stdin:
    message = json.loads(line)
    method = message['method']
    if method == 'session/new':
        result = {{'sessionId': 'unit-session', 'models': {{'currentModelId': {PAID!r},
            'availableModels': [{{'modelId': {PAID!r}}}, {{'modelId': {FREE!r}}}]}}}}
    elif method == 'session/set_model':
        assert message['params']['modelId'] != {FREE!r}, 'free request crossed boundary'
        result = {{}}
    else:
        result = {{'stopReason': 'end_turn'}}
    print(json.dumps({{'jsonrpc':'2.0', 'id':message['id'], 'result':result}}), flush=True)
''')
            node.chmod(0o755)
            env = dict(os.environ, HOME=str(home), PATH=str(home) + os.pathsep + os.environ["PATH"], CMD_ZDR="0")
            process = subprocess.Popen([sys.executable, str(SOURCE / "acp.py"), "acp"], env=env,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            def call(message):
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
                self.assertTrue(select.select([process.stdout], [], [], 2)[0], "ACP response timed out")
                return json.loads(process.stdout.readline())
            try:
                result = call(request("session/new"))["result"]
                self.assertEqual(result["models"]["availableModels"], [{"modelId": PAID}])
                denied = call(request("session/set_model", {"sessionId": "unit-session", "modelId": FREE}, 2))
                self.assertIn("error", denied)
                reply = call(request("session/prompt", {"sessionId": "unit-session", "prompt": [
                    {"type": "text", "text": "Reply with OK"}]}, 3))
                self.assertEqual(reply["result"]["stopReason"], "end_turn")
            finally:
                process.stdin.close()
                process.wait(timeout=2)
                process.stdout.close()
                process.stderr.close()

    def test_catalog_and_both_model_selection_paths_exclude_free(self):
        policy = acp.Policy()
        policy.request(request("session/new"))
        response = {"id": 1, "result": {"sessionId": "unit-session", "models": {
            "currentModelId": PAID,
            "availableModels": [{"modelId": PAID}, {"modelId": FREE}]}, "configOptions": [{
                "id": "model", "category": "model", "currentValue": PAID,
                "options": [{"value": PAID}, {"value": FREE}]}]}}
        policy.response(response)
        self.assertEqual(response["result"]["models"]["availableModels"], [{"modelId": PAID}])
        self.assertEqual(response["result"]["configOptions"][0]["options"], [{"value": PAID}])
        for method, params in [("session/set_model", {"modelId": FREE}),
                               ("session/set_config_option", {"configId": "model", "value": FREE})]:
            with self.assertRaises(ValueError):
                policy.request(request(method, params))
        policy.request(request("session/set_config_option", {"configId": "model", "value": PAID}))

    def test_unconfirmed_sessions_imports_unknown_options_and_slashes_fail_closed(self):
        policy = acp.Policy()
        for method, params in [("session/load", {}), ("session/resume", {}),
                               ("session/set_config_option", {"configId": "provider", "value": "other"}),
                               ("session/prompt", {"sessionId": "unknown"})]:
            with self.assertRaises(ValueError):
                policy.request(request(method, params))
        policy.sessions["unit-session"] = PAID
        with self.assertRaises(ValueError):
            policy.request(request("session/prompt", {"sessionId": "unit-session", "prompt": [
                {"type": "text", "text": " /model " + FREE}]}))
        policy.request(request("session/prompt", {"sessionId": "unit-session", "prompt": [
            {"type": "text", "text": "Reply with OK"}]}))

    def test_native_unapproved_switch_terminates_boundary(self):
        policy = acp.Policy()
        with self.assertRaises(ValueError):
            policy.response({"method": "session/update", "params": {"sessionId": "unit-session", "update": {
                "sessionUpdate": "current_model_update", "currentModelId": FREE}}})

    def test_import_and_slash_capabilities_are_honest(self):
        policy = acp.Policy()
        policy.request(request("initialize"))
        response = {"id": 1, "result": {"agentCapabilities": {"loadSession": True,
                    "sessionCapabilities": {"list": {}, "resume": {}}}}}
        policy.response(response)
        self.assertFalse(response["result"]["agentCapabilities"]["loadSession"])
        self.assertEqual(response["result"]["agentCapabilities"]["sessionCapabilities"], {"close": {}})
        message = {"method": "session/update", "params": {"update": {
            "sessionUpdate": "available_commands_update", "availableCommands": [{"name": "model"}]}}}
        policy.response(message)
        self.assertEqual(message["params"]["update"]["availableCommands"], [])

    def test_zdr_cannot_be_overridden_and_native_home_is_preserved(self):
        env = acp.provider_environment({"CMD_ZDR": "0", "PATH": "unit-path", "HOME": "unit-home",
                                        "COMMAND_CODE_UNUSED_OVERRIDE": "discard"})
        self.assertEqual(env["CMD_ZDR"], "1")
        self.assertEqual(env["HOME"], "unit-home")
        self.assertEqual(env["COMMANDCODE_SKIP_UPDATES"], "1")
        self.assertEqual(env["CMD_DISABLE_REMOTE_MODEL_CATALOG"], "1")
        self.assertNotIn("COMMAND_CODE_UNUSED_OVERRIDE", env)

    def test_login_executes_native_cli_without_reading_auth_state(self):
        class ExecCalled(Exception):
            pass
        with patch.object(acp.sys, "argv", ["cmd", "login"]), \
             patch.object(acp.os, "execvpe", side_effect=ExecCalled) as execute:
            with self.assertRaises(ExecCalled):
                acp.main()
        args = execute.call_args.args
        self.assertEqual(args[0], "node")
        self.assertEqual(args[1][-1], "login")
        self.assertEqual(args[2]["CMD_ZDR"], "1")


class InstallTest(unittest.TestCase):
    def test_committed_lock_rejects_wrong_integrity_and_mutable_version(self):
        setup.validate_lock(SOURCE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in ("package.json", "package-lock.json"):
                (root / filename).write_bytes((SOURCE / filename).read_bytes())
            data = json.loads((root / "package-lock.json").read_text())
            data["packages"]["node_modules/command-code"]["integrity"] = "sha512-wrong"
            (root / "package-lock.json").write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "integrity"):
                setup.validate_lock(root)
            (root / "package-lock.json").write_bytes((SOURCE / "package-lock.json").read_bytes())
            (root / "package.json").write_text('{"dependencies":{"command-code":"latest"}}')
            with self.assertRaisesRegex(ValueError, "version"):
                setup.validate_lock(root)

    def test_settings_merge_keeps_other_instances_and_has_only_zdr_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / ".t3/userdata/settings.json"
            original = {"otherSetting": True, "providerInstances": {
                "unitProvider": {"driver": "unit"}}}
            setup.atomic_json(path, original)
            setup.configure(home, SOURCE)
            data = json.loads(path.read_text())
            self.assertEqual(data["providerInstances"]["unitProvider"], original["providerInstances"]["unitProvider"])
            self.assertTrue(data["otherSetting"])
            provider = data["providerInstances"]["commandCode"]
            self.assertEqual(provider["config"]["commandArgs"], ["acp"])
            self.assertEqual(provider["environment"], [{"name": "CMD_ZDR", "value": "1"}])
            before = path.stat().st_mtime_ns
            setup.configure(home, SOURCE)
            self.assertEqual(path.stat().st_mtime_ns, before)

    def test_install_is_pinned_scriptless_and_retry_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            auth = home / ".commandcode/auth.json"
            auth.parent.mkdir()
            auth.write_text('{"synthetic": true}')
            auth_before = auth.stat().st_mtime_ns
            def run(command, **kwargs):
                if command[0] == "node":
                    return subprocess.CompletedProcess(command, 0, "v24.0.0\n")
                self.assertEqual(command[:2], ["npm", "ci"])
                self.assertIn("--ignore-scripts", command)
                stage = Path(command[command.index("--prefix") + 1])
                package = stage / "node_modules/command-code/package.json"
                package.parent.mkdir(parents=True)
                package.write_text(json.dumps({"version": setup.VERSION}))
                return subprocess.CompletedProcess(command, 0)
            with patch.object(setup.subprocess, "run", side_effect=run) as runner:
                setup.install(home)
                setup.install(home)
            self.assertEqual(sum(call.args[0][0] == "npm" for call in runner.call_args_list), 1)
            self.assertTrue((home / ".local/bin/cmd").is_file())
            self.assertEqual(auth.read_text(), '{"synthetic": true}')
            self.assertEqual(auth.stat().st_mtime_ns, auth_before)

    def test_image_installs_provider_before_t3_reads_settings(self):
        image = (ROOT / "packages/t3code/image.nix").read_text()
        self.assertIn("cp -r ${./command-code}/.", image)
        self.assertLess(image.index("ExecStartPre=${managedBin}/python3 /usr/share/t3code-command-code/setup.py"),
                        image.index("ExecStart=${managedBin}/t3code-server-run"))

    def test_auth_location_is_under_the_writable_persisted_home_not_the_image(self):
        module = (ROOT / "modules/self-hosted/t3code.nix").read_text()
        image = (ROOT / "packages/t3code/image.nix").read_text()
        self.assertIn('"${t3codeHome}:/home/t3code:rw"', module)
        self.assertIn("Environment=HOME=/home/t3code", image)
        self.assertNotIn(".commandcode/auth.json", image)
        self.assertNotIn("auth.json", (SOURCE / "setup.py").read_text())


if __name__ == "__main__":
    unittest.main()
