import importlib.util
import os
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = load("config", "modules/common/scripts/ghostship-config.py")
projection = load("projection", "modules/self-hosted/secret-project.py")


class ConfigTests(unittest.TestCase):
    def test_secret_round_trip(self):
        values = [
            "",
            "plain",
            "two words",
            "quote's",
            '"quoted"',
            "$dollar`literal`",
            "a=b#c",
            "back\\slash",
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "secrets.env"
            for value in values:
                source.write_text(f"KEY={shlex.quote(value)}\n")
                self.assertEqual(
                    config.ValueResolver(str(source)).resolve("env:KEY"), value
                )
                self.assertEqual(
                    projection.parse_env_file(source)["KEY"], value
                )

    def test_required_secret_leaves_file_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.env"
            target.write_text("EXISTING=preserved\n")
            manager = config.ConfigManager(target)
            manager.load()
            resolver = config.ValueResolver(require_secrets=True)
            with (
                patch.dict(os.environ, {}, clear=True),
                self.assertRaises(ValueError),
            ):
                manager.driver.set("KEY", resolver.resolve("env:MISSING"))
            self.assertEqual(target.read_text(), "EXISTING=preserved\n")

    def test_empty_secret_does_not_use_environment_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "secrets.env"
            source.write_text("KEY=\n")
            with patch.dict(os.environ, KEY="unexpected"):
                self.assertEqual(
                    config.ValueResolver(str(source)).resolve("env:KEY"), ""
                )
                with self.assertRaises(ValueError):
                    config.ValueResolver(
                        str(source), require_secrets=True
                    ).resolve("env:KEY")

    def test_atomic_write_preserves_symlink_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "actual.env"
            link = Path(directory) / "config.env"
            target.write_text("KEY=old\n")
            target.chmod(0o640)
            link.symlink_to(target)
            manager = config.ConfigManager(link)
            manager.load()
            manager.driver.set("KEY", "new")
            manager.save()
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(), "KEY=new\n")
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_failed_replace_preserves_original_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.env"
            target.write_text("KEY=old\n")
            manager = config.ConfigManager(target)
            manager.load()
            manager.driver.set("KEY", "new")
            with (
                patch.object(
                    config.os,
                    "replace",
                    side_effect=OSError("simulated failure"),
                ),
                self.assertRaises(OSError),
            ):
                manager.save()
            self.assertEqual(target.read_text(), "KEY=old\n")
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_projection_emits_raw_container_values(self):
        import grp
        import pwd

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.env"
            target = Path(directory) / "output.env"
            value = "quote's and $literal"
            source.write_text(f"KEY={shlex.quote(value)}\n")
            projection.SPEC = {
                "units": {"test": {"path": str(source)}},
                "projections": {
                    "test": {
                        "path": str(target),
                        "mode": "0600",
                        "owner": pwd.getpwuid(os.getuid()).pw_name,
                        "group": grp.getgrgid(os.getgid()).gr_name,
                        "fields": {"TOKEN": {"unit": "test", "key": "KEY"}},
                    }
                },
            }
            projection.write_projection("test")
            self.assertEqual(
                target.with_suffix(".env.container").read_text(),
                f"TOKEN={value}\n",
            )
            self.assertEqual(
                config.ValueResolver(str(target)).resolve("env:TOKEN"), value
            )


if __name__ == "__main__":
    unittest.main()
