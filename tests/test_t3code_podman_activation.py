"""Reproduce a preserved isolated manager missing NixOS's mandatory unit."""

import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "packages/t3code/dev-engine/reconcile-activation.py"
)
SPEC = importlib.util.spec_from_file_location("activation", SOURCE)
activation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activation)


class ActivationMigration(unittest.TestCase):
    def reconcile(self, run):
        activation.reconcile(
            "engine",
            "1234",
            "systemctl",
            "systemd-run",
            "runuser",
            "env",
            "/private/bin/true",
            run,
        )

    def test_missing_unit_is_seeded_and_second_activation_preserves_it(self):
        commands = []
        loaded = False

        def run(args, **kwargs):
            nonlocal loaded
            commands.append(args)
            if "show" in args:
                return subprocess.CompletedProcess(
                    args, 0, "loaded\n" if loaded else "not-found\n"
                )
            if "systemd-run" in args:
                loaded = True
            return subprocess.CompletedProcess(args, 0)

        self.reconcile(run)
        self.reconcile(run)
        seeds = [c for c in commands if "systemd-run" in c]
        self.assertEqual(len(seeds), 1)
        self.assertIn("--unit=nixos-activation.service", seeds[0])
        self.assertIn("--property=RemainAfterExit=yes", seeds[0])
        self.assertEqual(seeds[0][-1], "/private/bin/true")
        self.assertIn("DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1234/bus", seeds[0])
        self.assertFalse(any("restart" in c or "stop" in c for c in commands))

    def test_inactive_manager_is_not_started(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 3))
        self.reconcile(run)
        self.assertEqual(run.call_count, 1)

    def test_unknown_unit_state_and_bus_failure_are_not_hidden(self):
        for state in ("error\n", "masked\n"):
            run = Mock(
                side_effect=[
                    subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0, state),
                ]
            )
            with self.assertRaises(ValueError):
                self.reconcile(run)
            self.assertEqual(run.call_count, 2)
        run = Mock(
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CalledProcessError(1, "systemctl"),
            ]
        )
        with self.assertRaises(subprocess.CalledProcessError):
            self.reconcile(run)

    def test_failed_unit_creation_fails_activation(self):
        run = Mock(
            side_effect=[
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0, "not-found\n"),
                subprocess.CalledProcessError(1, "systemd-run"),
            ]
        )
        with self.assertRaises(subprocess.CalledProcessError):
            self.reconcile(run)
