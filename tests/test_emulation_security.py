import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "modules/emulation" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


assets = load("emulation_assets", "homebrew-assets.py")
leds = load("emulation_leds", "controller-led-write.py")
logs = load("emulation_logs", "runtime-log.py")
tui = load("emulation_tui", "settings-tui.py")


def embedded_python(file, marker):
    text = (ROOT / "modules/emulation" / file).read_text().split(marker, 1)[1]
    text = text.split("<<'PY'\n", 1)[1].split("\n    PY", 1)[0]
    return textwrap.dedent(text)


class EmulationSecurityTests(unittest.TestCase):
    def test_settings_tui_smoke_including_exact_star_mapping(self):
        for mode in ["bluetooth", "wifi", "maps"]:
            result = subprocess.run(
                [sys.executable, str(ROOT / "modules/emulation/settings-tui.py"), mode, "--smoke-test"],
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_asset_snapshot_refuses_links_and_preserves_previous_data_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "data", root / "sdcard/data"
            source.mkdir()
            target.parent.mkdir()
            (source / "asset.txt").write_text("ordinary asset")
            self.assertTrue(assets.snapshot(source, target))
            self.assertEqual((target / "asset.txt").read_text(), "ordinary asset")
            self.assertNotEqual(target.resolve(), source)
            (source / "nested").mkdir()
            (source / "nested/leak").symlink_to(root / "private-secret")
            with self.assertRaises(ValueError):
                assets.snapshot(source, target)
            self.assertEqual((target / "asset.txt").read_text(), "ordinary asset")
            self.assertEqual(len(list(root.glob("sdcard/.ghostship-assets-*"))), 1)

    def test_asset_snapshot_refuses_symlinked_root_and_detaches_stale_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "data"
            source.symlink_to(root, target_is_directory=True)
            target = root / "sdcard"
            target.symlink_to(root, target_is_directory=True)
            result = subprocess.run(
                [sys.executable, str(ROOT / "modules/emulation/homebrew-assets.py"), str(source), str(target)],
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(target.is_symlink())
            self.assertTrue(source.is_symlink())

    def test_asset_snapshot_preserves_operator_directory_and_reclaims_old_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "data", root / "sdcard/data"
            source.mkdir()
            target.mkdir(parents=True)
            (target / "save.txt").write_text("operator data")
            self.assertFalse(assets.snapshot(source, target))
            self.assertEqual((target / "save.txt").read_text(), "operator data")
            (target / "save.txt").unlink()
            target.rmdir()
            assets.snapshot(source, target)
            old = target.resolve()
            assets.snapshot(source, target)
            self.assertFalse(old.exists())

    def test_led_worker_only_writes_kernel_controller_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / "devices/controller/input/input0"
            device.mkdir(parents=True)
            (device / "uniq").write_text("AA:BB:CC:DD:EE:FF\n")
            event = root / "class/input/event0"
            event.mkdir(parents=True)
            (event / "device").symlink_to(device)
            ledroot = root / "devices/controller/leds"
            for index in range(1, 5):
                led = ledroot / f"controller:green:player-{index}"
                led.mkdir(parents=True)
                (led / "brightness").write_text("0\n")
            victim = root / "root-owned-surrogate"
            victim.write_text("unchanged")
            bad_led = ledroot / "other:green:player-1"
            bad_led.mkdir()
            (bad_led / "brightness").symlink_to(victim)
            rows = leds.player_rows(json.dumps({"players": [
                {"mac": "AA:BB:CC:DD:EE:FF", "player": 2, "connected": True},
                {"mac": "../../etc/shadow", "player": 1, "connected": True},
                {"mac": "11:22:33:44:55:66", "player": 99, "connected": True},
            ]}))
            self.assertEqual(rows, {"AA:BB:CC:DD:EE:FF": 2})
            leds.apply(rows, sys_root=root, delay=lambda _: None)
            self.assertEqual(victim.read_text(), "unchanged")
            self.assertEqual([(ledroot / f"controller:green:player-{i}/brightness").read_text().strip() for i in range(1, 5)], ["1", "1", "0", "0"])

    def test_missing_runtime_classifier_is_bounded_and_does_not_cross_lines(self):
        for line in ["BIOS missing", "required firmware", "cannot open prod.keys", "system card not found"]:
            self.assertTrue(logs.missing_runtime(line.lower()))
        self.assertFalse(logs.missing_runtime("missing artwork\nloaded bios"))
        start = time.monotonic()
        self.assertFalse(logs.missing_runtime("missing " * 500000))
        self.assertFalse(logs.missing_runtime("bios " * 500000))
        self.assertLess(time.monotonic() - start, 2)

    def test_wifi_password_uses_stdin_and_is_redacted_from_output(self):
        backend = tui.WifiBackend()
        with patch.object(backend, "apply_policy"), patch.object(tui.subprocess, "run", return_value=SimpleNamespace(
            returncode=0, stdout="fixture-password", stderr=""
        )) as run:
            code, out, err = backend.connect_network("fixture-network", "fixture-password")
        self.assertEqual(code, 0)
        self.assertNotIn("fixture-password", run.call_args.args[0])
        self.assertIn("--ask", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["input"], "fixture-password\n")
        self.assertNotIn("fixture-password", out + err)

    def test_secret_renderer_uses_esde_top_level_sibling_format(self):
        script = embedded_python("secrets.nix", 'python3 - "$secret_env" "$settings"')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret, settings = root / "secret.env", root / "es_settings.xml"
            secret.write_text("SCREENSCRAPER_USER=fixture\nSCREENSCRAPER_PASS=fixture-password\n")
            settings.write_text('<string name="Theme" value="existing"/>\n<bool name="Existing" value="true"/>\n')
            for _ in range(2):
                result = subprocess.run([sys.executable, "-c", script, str(secret), str(settings)], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                body = settings.read_text().split("?>", 1)[1]
                document = ET.fromstring("<fixture>" + body + "</fixture>")
                self.assertIsNone(document.find("settings"))
                self.assertEqual(document.find('string[@name="ScraperPasswordScreenScraper"]').get("value"), "fixture-password")
                self.assertEqual(document.find('string[@name="Theme"]').get("value"), "existing")

    def test_missing_secret_fallback_replaces_symlink_without_clobber(self):
        script = embedded_python("secrets.nix", 'python3 - "$secret_env" "$retroarch_cfg"')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "retroarch.cfg", root / "secrets.ini", root / "status.json"]
            victim = root / "sensitive-surrogate"
            victim.write_text("unchanged")
            for path in paths:
                path.symlink_to(victim)
                path.with_suffix(path.suffix + ".tmp").symlink_to(victim)
            result = subprocess.run([sys.executable, "-c", script, str(root / "missing.env"), *map(str, paths)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(victim.read_text(), "unchanged")
            self.assertIn('cheevos_enable = "false"', paths[0].read_text())
            self.assertTrue(all(not path.is_symlink() for path in paths))


if __name__ == "__main__":
    unittest.main()
