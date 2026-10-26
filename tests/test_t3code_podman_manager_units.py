"""The preserved manager must always find the unit directory it loads from.

NixOS restarts a mandatory per-user ``nixos-activation.service`` on every
switch. The isolated Podman manager only sees its own store directory, so that
directory has to exist inside its ``RootDirectory`` for the restart to succeed.
A manager that outlives the generation it started on used to point at a
directory the private store never received, which made every switch exit 4.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "packages/t3code/dev-engine/manager-units.py"
SPEC = importlib.util.spec_from_file_location("podman_manager_units", SOURCE)
manager_units = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager_units)


class Completed:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def environ_reader(pid, values):
    environ = b"\0".join(
        key.encode() + b"=" + value.encode() for key, value in values.items()
    ) + b"\0"
    return lambda path: environ if str(path) == f"/proc/{pid}/environ" else b""


class ManagerUnitPaths(unittest.TestCase):
    def test_reads_the_running_managers_own_load_path(self):
        run = lambda *args, **kwargs: Completed(stdout="4242\n")
        paths = manager_units.unit_dirs(
            "user@62040.service",
            "/bin/systemctl",
            run=run,
            read_bytes=environ_reader(
                4242, {"SYSTEMD_UNIT_PATH": "/nix/store/a-units:/nix/store/b-units"}
            ),
        )
        self.assertEqual(paths, ["/nix/store/a-units", "/nix/store/b-units"])

    def test_an_inactive_manager_needs_no_seed(self):
        run = lambda *args, **kwargs: Completed(stdout="0\n")
        paths = manager_units.unit_dirs(
            "user@62040.service",
            "/bin/systemctl",
            run=run,
            read_bytes=lambda path: b"",
        )
        self.assertEqual(paths, [])

    def test_unreadable_manager_state_fails_closed(self):
        for run in (
            lambda *args, **kwargs: Completed(returncode=1),
            lambda *args, **kwargs: Completed(stdout="not-a-pid"),
        ):
            with self.subTest(run=run), self.assertRaises(ValueError):
                manager_units.unit_dirs(
                    "user@62040.service", "/bin/systemctl", run=run, read_bytes=lambda p: b""
                )


class Seeding(unittest.TestCase):
    def test_missing_directory_is_copied_and_pinned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            source = Path(temporary) / "store" / "units"
            source.mkdir(parents=True)
            (source / "nixos-activation.service").write_text("[Service]\n")
            (root / "nix").mkdir(parents=True)
            calls = []

            def run(args, check=False):
                calls.append(args)
                target = root / args[-1].lstrip("/")
                target.mkdir(parents=True, exist_ok=True)
                (target / "nixos-activation.service").write_text("[Service]\n")
                return Completed()

            manager_units.seed(
                root,
                [str(source)],
                Path("/srv/private"),
                Path("/srv/private/nix/var/nix/gcroots"),
                "/bin/nix",
                "/bin/nix-store",
                run=run,
            )

            self.assertEqual(calls[0][:3], ["/bin/nix", "copy", "--no-check-sigs"])
            self.assertIn("local?root=/srv/private", calls[0])
            self.assertIn("--add-root", calls[1])
            self.assertTrue(
                (root / source.relative_to("/") / "nixos-activation.service").is_file()
            )

    def test_present_directory_is_left_alone(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            source = Path(temporary) / "store" / "units"
            source.mkdir(parents=True)
            (root / source.relative_to("/")).mkdir(parents=True)
            calls = []
            manager_units.seed(
                root,
                [str(source)],
                Path("/srv/private"),
                Path("/srv/private/nix/var/nix/gcroots"),
                "/bin/nix",
                "/bin/nix-store",
                run=lambda args, check=False: calls.append(args),
            )
            self.assertEqual(calls, [])

    def test_the_same_directory_is_seeded_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            source = Path(temporary) / "store" / "units"
            source.mkdir(parents=True)
            calls = []

            def run(args, check=False):
                calls.append(args)
                (root / args[-1].lstrip("/")).mkdir(parents=True, exist_ok=True)
                return Completed()

            manager_units.seed(
                root,
                [str(source), str(source)],
                Path("/srv/private"),
                Path("/srv/private/nix/var/nix/gcroots"),
                "/bin/nix",
                "/bin/nix-store",
                run=run,
            )
            self.assertEqual(len(calls), 2)

    def test_only_the_live_roots_survive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            gcroot = Path(temporary) / "gcroots"
            gcroot.mkdir()
            for name in (
                "t3code-podman-manager-units-live",
                "t3code-podman-manager-units-current",
                "t3code-podman-manager-units-retired",
                # Another owner's root must never be touched.
                "t3code-podman-runtime-production",
            ):
                (gcroot / name).symlink_to(f"/nix/store/{name}")
            live = Path("/nix/store/live")
            current = Path("/nix/store/current")
            for directory in (live, current):
                (root / directory.relative_to("/")).mkdir(parents=True)
            manager_units.seed(
                root,
                [str(live), str(current)],
                Path("/srv/private"),
                gcroot,
                "/bin/nix",
                "/bin/nix-store",
                run=lambda args, check=False: self.fail("present directories need no copy"),
            )
            self.assertEqual(
                sorted(entry.name for entry in gcroot.iterdir()),
                [
                    "t3code-podman-manager-units-current",
                    "t3code-podman-manager-units-live",
                    "t3code-podman-runtime-production",
                ],
            )

    def test_a_failed_seed_retires_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            gcroot = Path(temporary) / "gcroots"
            gcroot.mkdir()
            stale = gcroot / "t3code-podman-manager-units-retired"
            stale.symlink_to("/nix/store/retired")
            with self.assertRaisesRegex(ValueError, "absent from the host store"):
                manager_units.seed(
                    root,
                    ["/nix/store/podman-units-missing"],
                    Path("/srv/private"),
                    gcroot,
                    "/bin/nix",
                    "/bin/nix-store",
                    run=lambda args, check=False: Completed(),
                )
            self.assertTrue(stale.is_symlink())

    def test_absent_host_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "absent from the host store"):
                manager_units.seed(
                    Path(temporary) / "root",
                    ["/nix/store/podman-units-missing"],
                    Path("/srv/private"),
                    Path("/srv/private/nix/var/nix/gcroots"),
                    "/bin/nix",
                    "/bin/nix-store",
                    run=lambda args, check=False: Completed(),
                )

    def test_relative_and_traversing_directories_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            for directory in ("nix/store/units", "/nix/../etc"):
                with self.subTest(directory=directory), self.assertRaises(ValueError):
                    manager_units.seed(
                        Path(temporary) / "root",
                        [directory],
                        Path("/srv/private"),
                        Path("/srv/private/nix/var/nix/gcroots"),
                        "/bin/nix",
                        "/bin/nix-store",
                        run=lambda args, check=False: Completed(),
                    )

    def test_a_directory_the_copy_did_not_deliver_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            source = Path(temporary) / "store" / "units"
            source.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "still absent"):
                manager_units.seed(
                    root,
                    [str(source)],
                    Path("/srv/private"),
                    Path("/srv/private/nix/var/nix/gcroots"),
                    "/bin/nix",
                    "/bin/nix-store",
                    run=lambda args, check=False: Completed(),
                )


class Reconcile(unittest.TestCase):
    def test_an_unmounted_root_is_not_touched(self):
        with patch.object(manager_units.os.path, "ismount", return_value=False):
            manager_units.reconcile(
                Path("/run/t3code-podman-rootfs"),
                "user@62040.service",
                Path("/nix/store/current-units"),
                Path("/srv/private"),
                Path("/srv/private/nix/var/nix/gcroots"),
                "/bin/systemctl",
                "/bin/nix",
                "/bin/nix-store",
                run=lambda *args, **kwargs: self.fail("a preserved root is required"),
            )

    def test_the_live_directory_and_the_current_generation_are_both_seeded(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(manager_units.os.path, "ismount", return_value=True),
            patch.object(manager_units, "seed") as seed,
            patch.object(
                manager_units,
                "unit_dirs",
                return_value=["/nix/store/live-units"],
            ),
        ):
            manager_units.reconcile(
                Path(temporary),
                "user@62040.service",
                Path("/nix/store/current-units"),
                Path("/srv/private"),
                Path("/srv/private/nix/var/nix/gcroots"),
                "/bin/systemctl",
                "/bin/nix",
                "/bin/nix-store",
            )
            self.assertEqual(
                seed.call_args.args[1],
                ["/nix/store/live-units", "/nix/store/current-units"],
            )


if __name__ == "__main__":
    unittest.main()
