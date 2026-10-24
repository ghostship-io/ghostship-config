"""The OpenCode route carries the vendor catalog, ZDR, and no literal key."""

import importlib.util
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages/t3code/command-code"

spec = importlib.util.spec_from_file_location("command_code_configure", SOURCE / "configure.py")
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)

VENDOR = [
    {"id": "deepseek/deepseek-v4.1-flash", "name": "DeepSeek V4.1 Flash (latest)",
     "context_length": 1000000,
     "supported_endpoints": ["/chat/completions", "/responses"]},
    {"id": "deepseek/deepseek-v4-flash-fast", "name": "DeepSeek V4 Flash Fast",
     "context_length": 128000, "supported_endpoints": ["/chat/completions"]},
    {"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5",
     "context_length": 200000, "supported_endpoints": ["/messages"]},
    {"id": "typesafe/jev", "name": "Jev", "context_length": 64000,
     "supported_endpoints": []},
    # No age or price rule may remove a live model.
    {"id": "legacy/old-but-current", "name": "Old", "context_length": 32000,
     "supported_endpoints": ["/chat/completions"]},
]


def serving(entries):
    def call(key):
        assert key, "the key must reach the catalog request"
        return entries
    return call


def home_with(config=None, settings=None):
    root = Path(tempfile.mkdtemp())
    (root / ".config/opencode").mkdir(parents=True)
    if config is not None:
        (root / ".config/opencode/opencode.jsonc").write_text(json.dumps(config))
    if settings is not None:
        (root / ".t3/userdata").mkdir(parents=True)
        (root / ".t3/userdata/settings.json").write_text(json.dumps(settings))
    return root


def config_of(home):
    return json.loads((home / ".config/opencode/opencode.jsonc").read_text())


class ConfigureTests(unittest.TestCase):
    def run_main(self, home, *, key="fixture-key", fetch=None):
        return configure.main(home=home, source=SOURCE, key=key,
                              fetch=fetch or serving(VENDOR), environ={})

    def test_registers_both_routes_with_every_vendor_model(self):
        home = home_with({"permission": {"bash": {"*": "allow"}}, "model": "ollama-cloud/x",
                          "enabled_providers": ["ollama-cloud"]})
        self.assertEqual(self.run_main(home), 0)
        config = config_of(home)
        self.assertEqual(config["permission"], {"bash": {"*": "allow"}})
        self.assertEqual(config["model"], "ollama-cloud/x")
        self.assertEqual(config["enabled_providers"], ["ollama-cloud", "command-code", "command-code-anthropic"])
        openai = config["providers"]["command-code"]
        anthropic = config["providers"]["command-code-anthropic"]
        self.assertEqual(set(openai["models"]), {
            "deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-flash-fast",
            "legacy/old-but-current"})
        self.assertEqual(set(anthropic["models"]), {"claude-sonnet-5-5"})
        self.assertEqual(openai["models"]["deepseek/deepseek-v4.1-flash"],
                         {"name": "DeepSeek V4.1 Flash (latest)", "limit": {"context": 1000000}})
        for entry in (openai, anthropic):
            self.assertEqual(entry["settings"]["apiKey"], "{env:COMMAND_CODE_API_KEY}")
            self.assertEqual(entry["headers"], {"x-cmd-zdr": "1"})
            self.assertEqual(entry["settings"]["baseURL"], "https://api.commandcode.ai/provider/v1")
        self.assertEqual(openai["package"], "@ai-sdk/openai-compatible")
        self.assertEqual(anthropic["package"], "@ai-sdk/anthropic")
        self.assertNotIn("fixture-key", json.dumps(config))
        self.assertEqual((home / ".config/opencode/opencode.jsonc").stat().st_mode & 0o777, 0o600)

    def test_failed_refresh_keeps_the_last_good_catalog(self):
        home = home_with()
        self.run_main(home)
        before = config_of(home)
        def broken(key):
            raise OSError("synthetic")
        with self.subTest("broken fetch"):
            self.assertEqual(self.run_main(home, fetch=broken), 0)
            self.assertEqual(config_of(home), before)
        with self.subTest("empty catalog"):
            self.assertEqual(self.run_main(home, fetch=serving([])), 0)
            self.assertEqual(config_of(home), before)

    def test_missing_key_makes_no_request_and_adds_no_empty_provider(self):
        home = home_with({"enabled_providers": ["ollama-cloud"]})
        secrets = Path(tempfile.mkdtemp()) / "t3code.env"
        secrets.write_text("OTHER=" + "value" + "\n")

        def forbidden(key):
            raise AssertionError("no request without a key")

        self.assertEqual(configure.main(home=home, source=SOURCE, key=None,
                                        fetch=forbidden, environ={},
                                        secrets_file=secrets), 0)
        config = config_of(home)
        self.assertNotIn("providers", config)
        self.assertEqual(config["enabled_providers"], ["ollama-cloud"])

    def test_configured_xdg_directory_is_honoured(self):
        home = home_with()
        xdg = Path(tempfile.mkdtemp())
        self.assertEqual(configure.main(home=home, source=SOURCE, key="k",
                                        fetch=serving(VENDOR),
                                        environ={"XDG_CONFIG_HOME": str(xdg)}), 0)
        self.assertTrue((xdg / "opencode/opencode.jsonc").exists())
        self.assertFalse((home / ".config/opencode/opencode.jsonc").exists())

    def test_second_start_does_not_rewrite_the_config(self):
        home = home_with()
        self.run_main(home)
        path = home / ".config/opencode/opencode.jsonc"
        before = path.stat().st_mtime_ns
        self.run_main(home)
        self.assertEqual(path.stat().st_mtime_ns, before)

    def managed_settings(self):
        return {"providerInstances": {
            "commandCode": {"driver": "acpRegistry", "enabled": True,
                            "config": {"source": "local",
                                       "commandPath": "/home/t3code/.local/bin/cmd",
                                       "commandArgs": ["acp"]}},
            "unitProvider": {"driver": "unit"}}}

    def test_commented_jsonc_config_is_merged_and_the_acp_instance_retired(self):
        home = home_with(settings=self.managed_settings())
        path = home / ".config/opencode/opencode.jsonc"
        path.write_text("""{
  // OpenCode accepts comments and trailing commas.
  "$schema": "https://opencode.ai/config.json",
  "model": "ollama-cloud/x", /* the owner's default */
  "enabled_providers": ["ollama-cloud",],
}
""")
        self.assertEqual(self.run_main(home), 0)
        config = config_of(home)
        self.assertEqual(config["model"], "ollama-cloud/x")
        self.assertEqual(set(config["providers"]), {"command-code", "command-code-anthropic"})
        self.assertEqual(config["enabled_providers"],
                         ["ollama-cloud", "command-code", "command-code-anthropic"])
        settings = json.loads((home / ".t3/userdata/settings.json").read_text())
        self.assertNotIn("commandCode", settings["providerInstances"])
        self.assertEqual(settings["providerInstances"]["unitProvider"], {"driver": "unit"})

    def test_broken_config_keeps_the_config_and_the_acp_instance(self):
        home = home_with(settings=self.managed_settings())
        path = home / ".config/opencode/opencode.jsonc"
        path.write_text('{"providers": ')
        self.assertEqual(self.run_main(home), 0)
        self.assertEqual(path.read_text(), '{"providers": ')
        settings = json.loads((home / ".t3/userdata/settings.json").read_text())
        self.assertIn("commandCode", settings["providerInstances"])

    def test_no_replacement_catalog_keeps_the_acp_instance(self):
        home = home_with(settings=self.managed_settings())
        self.assertEqual(configure.main(home=home, source=SOURCE, key="",
                                        fetch=serving(VENDOR), environ={}), 0)
        settings = json.loads((home / ".t3/userdata/settings.json").read_text())
        self.assertIn("commandCode", settings["providerInstances"])

    def test_existing_replacement_survives_a_key_outage_and_retires(self):
        home = home_with(settings=self.managed_settings())
        self.run_main(home)
        settings_path = home / ".t3/userdata/settings.json"
        settings = json.loads(settings_path.read_text())
        settings["providerInstances"]["commandCode"] = self.managed_settings()[
            "providerInstances"]["commandCode"]
        settings_path.write_text(json.dumps(settings))
        self.assertEqual(configure.main(home=home, source=SOURCE, key="",
                                        fetch=serving(VENDOR), environ={}), 0)
        config = config_of(home)
        self.assertEqual(set(config["providers"]), {"command-code", "command-code-anthropic"})
        settings = json.loads(settings_path.read_text())
        self.assertNotIn("commandCode", settings["providerInstances"])

    def test_retires_only_the_managed_acp_instance(self):
        managed = {"driver": "acpRegistry", "enabled": True,
                   "config": {"source": "local", "commandPath": "/home/t3code/.local/bin/cmd",
                              "commandArgs": ["acp"]}}
        unmanaged = {"driver": "acpRegistry", "enabled": True,
                     "config": {"source": "local", "commandPath": "/usr/local/bin/other",
                                "commandArgs": ["acp"]}}
        other = {"driver": "unit"}
        for label, instance, removed in [
            ("managed", managed, True),
            ("unmanaged", unmanaged, False),
            ("other driver", {**managed, "driver": "unit"}, False),
            ("other args", {**managed, "config": {**managed["config"], "commandArgs": []}}, False),
        ]:
            with self.subTest(case=label):
                home = home_with(settings={"otherSetting": True,
                                           "providerInstances": {"commandCode": instance,
                                                                 "unitProvider": other}})
                self.run_main(home, fetch=serving(VENDOR))
                settings = json.loads((home / ".t3/userdata/settings.json").read_text())
                self.assertTrue(settings["otherSetting"])
                self.assertEqual(settings["providerInstances"]["unitProvider"], other)
                self.assertEqual("commandCode" in settings["providerInstances"], not removed)

    def test_malformed_or_absent_files_do_not_raise(self):
        home = home_with()
        (home / ".config/opencode/opencode.jsonc").write_text("{not json")
        self.run_main(home, fetch=serving(VENDOR))
        # A malformed owner config is left exactly as it was.
        self.assertEqual((home / ".config/opencode/opencode.jsonc").read_text(), "{not json")
        empty = home_with()
        self.assertEqual(configure.main(home=empty, source=SOURCE, key="",
                                        fetch=serving(VENDOR), environ={}), 0)
        # No key and no existing file: nothing to add, so nothing is created.
        self.assertFalse((empty / ".config/opencode/opencode.jsonc").exists())

    def test_image_runs_configure_directly_without_sourcing_secrets(self):
        image = (ROOT / "packages/t3code/image.nix").read_text()
        directive = "ExecStartPre=-${managedBin}/python3 /usr/share/t3code-command-code/configure.py"
        self.assertIn("cp -r ${./command-code}/.", image)
        self.assertIn(directive, image)
        self.assertLess(image.index(directive),
                        image.index("ExecStart=${managedBin}/t3code-server-run"))
        self.assertNotIn("set -a", image)
        self.assertNotIn(". /run/secrets/t3code.env", image)

    def test_catalog_fetch_identifies_itself(self):
        seen = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *arguments):
                return False

            def read(self, *arguments):
                return json.dumps({"data": VENDOR}).encode()

        def opener(request, timeout=None):
            seen.update(request.header_items())
            return Response()

        with patch("urllib.request.urlopen", opener):
            self.assertEqual(configure.fetch_models("fixture"), VENDOR)
        self.assertEqual(configure.USER_AGENT, "ghostship-t3code-command-code/1")
        self.assertEqual(seen.get("User-agent"), configure.USER_AGENT)
        self.assertNotIn("curl", configure.USER_AGENT.lower())
        self.assertNotIn("mozilla", configure.USER_AGENT.lower())

    def test_only_the_projected_key_is_read_and_nothing_is_evaluated(self):
        home = home_with()
        secrets = Path(tempfile.mkdtemp()) / "t3code.env"
        marker = secrets.parent / "executed"
        value = "pre$(touch " + str(marker) + ")post'quote\""
        seen = {}

        def capture(key):
            seen["key"] = key
            return VENDOR

        for label, encoded in (("projection quoting", shlex.quote(value)),
                               ("bare value", value)):
            with self.subTest(case=label):
                secrets.write_text("OTHER=" + "value" + "\n"
                                   "COMMAND_CODE_API_KEY=" + encoded + "\n")
                self.assertEqual(configure.main(home=home, source=SOURCE, key=None,
                                                fetch=capture, environ={},
                                                secrets_file=secrets), 0)
                self.assertEqual(seen["key"], value)
                self.assertFalse(marker.exists())

    def test_documented_route_and_terms_are_current(self):
        docs = (ROOT / "docs/t3code.md").read_text()
        self.assertIn("api.commandcode.ai/provider/v1", docs)
        self.assertIn("x-cmd-zdr", docs)
        self.assertIn("COMMAND_CODE_API_KEY", docs)
        self.assertIn("## Command Code GOAT through OpenCode", docs)
        self.assertNotIn("## Command Code GOAT ACP provider", docs)


if __name__ == "__main__":
    unittest.main()
