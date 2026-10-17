import pathlib
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "modules/self-hosted/clear-runtime-unit-overrides.sh"


class ClearRuntimeUnitOverrides(unittest.TestCase):
    def test_clears_overrides_of_declared_units_and_keeps_masks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            runtime, declared, store = root / "run", root / "etc", root / "store"
            for path in (runtime, declared, store):
                path.mkdir()
            for unit in ("relay.service", "deploy.service", "broker.service", "podman-app.service"):
                (declared / unit).write_text("[Service]\n")
            (store / "old-relay.service").write_text("[Service]\n")

            # Targeted activation and session guard drop-ins of declared units.
            (runtime / "relay.service.d").mkdir()
            (runtime / "relay.service.d/90-task.conf").write_text("[Service]\nExecStart=\nExecStart=/old\n")
            (runtime / "deploy.service.d").mkdir()
            (runtime / "deploy.service.d/99-session-guard.conf").write_text("[Unit]\nConditionPathExists=!/run/x\n")
            # A shadowed runtime unit link and the dependency pointing at it.
            (runtime / "relay.service").symlink_to(store / "old-relay.service")
            (runtime / "podman-app.service.requires").mkdir()
            (runtime / "podman-app.service.requires/relay.service").symlink_to(runtime / "relay.service")
            # Deliberate runtime masks and overrides of undeclared units stay.
            (runtime / "retired.service").symlink_to("/dev/null")
            (runtime / "broker.service").symlink_to("/dev/null")
            (runtime / "other.service.d").mkdir()
            (runtime / "other.service.d/10-keep.conf").write_text("[Service]\n")

            result = subprocess.run(["bash", str(SCRIPT), str(runtime), str(declared)],
                                    capture_output=True, text=True, check=True)

            self.assertEqual(
                sorted(str(path.relative_to(runtime)) for path in runtime.rglob("*")),
                ["broker.service", "other.service.d", "other.service.d/10-keep.conf", "retired.service"],
            )
            self.assertIn("removing runtime override", result.stdout)
            self.assertIn("removing shadowed runtime unit", result.stdout)
            self.assertIn("removing dangling runtime dependency", result.stdout)

    def test_missing_runtime_directory_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            subprocess.run(["bash", str(SCRIPT), str(root / "missing"), str(root)], check=True)


if __name__ == "__main__":
    unittest.main()
