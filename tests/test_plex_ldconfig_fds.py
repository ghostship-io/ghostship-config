"""Plex's ldconfig probe closes inherited descriptors and the denial is no longer exempt.

The confined ``ghostship-plex//ldconfig`` domain logged a ``file_inherit``
denial for every packaged runtime file the interpreter had open when Python 2
started ``/sbin/ldconfig -p``. The interpreter's sitecustomize now closes every
descriptor above stderr for that probe, and the SIEM rule treats any remaining
denial in the enforced domains as breakage.
"""
import subprocess
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "modules/self-hosted/plex-sitecustomize.py"
PLEX = ROOT / "modules/self-hosted/plex.nix"
RULES = ROOT / "modules/self-hosted/siem/rules/logs.yml"
DESTINATION = "Resources/Python/lib/python2.7/site-packages/sitecustomize.py"


def load_hook():
    """Run the hook against a fake ctypes.util and return that module."""
    util = types.ModuleType("ctypes.util")
    ctypes = types.ModuleType("ctypes")

    def find_library(name):
        subprocess.Popen(["/sbin/ldconfig", "-p"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return "libc.so.6"

    util.find_library = find_library
    ctypes.util = util
    saved = {name: sys.modules.get(name) for name in ("ctypes", "ctypes.util")}
    try:
        sys.modules["ctypes"] = ctypes
        sys.modules["ctypes.util"] = util
        namespace = {"__name__": "plex_sitecustomize"}
        exec(compile(HOOK.read_text(), str(HOOK), "exec"), namespace)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return util


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.original = subprocess.Popen
        self.addCleanup(setattr, subprocess, "Popen", self.original)
        self.kwargs = kwargs = {}

        class Recording(self.original):
            def __init__(self, *args, **extra):
                kwargs.update(extra)

        self.recording = Recording

    def test_the_probe_closes_inherited_descriptors(self):
        util = load_hook()
        subprocess.Popen = self.recording
        self.assertEqual(util.find_library("c"), "libc.so.6")
        self.assertIs(self.kwargs.get("close_fds"), True)

    def test_a_second_install_does_not_wrap_again(self):
        util = load_hook()
        wrapped = util.find_library
        namespace = {"__name__": "plex_sitecustomize"}
        sys.modules["ctypes"] = types.ModuleType("ctypes")
        sys.modules["ctypes"].util = util
        sys.modules["ctypes.util"] = util
        self.addCleanup(sys.modules.pop, "ctypes", None)
        self.addCleanup(sys.modules.pop, "ctypes.util", None)
        exec(compile(HOOK.read_text(), str(HOOK), "exec"), namespace)
        self.assertIs(util.find_library, wrapped)

    def test_the_container_mounts_the_hook_where_the_interpreter_imports_it(self):
        text = PLEX.read_text()
        self.assertIn("./plex-sitecustomize.py", text)
        site = [line.strip() for line in text.splitlines()
                if line.strip().startswith("plex-python-site =")]
        self.assertEqual(len(site), 1, site)
        self.assertTrue(site[0].rstrip(';"').endswith(DESTINATION.rsplit("/", 1)[0]), site[0])
        self.assertIn("${plex-sitecustomize}:${plex-python-site}/sitecustomize.py:ro", text)

    def test_the_enforced_denial_rule_keeps_no_file_inherit_exemption(self):
        expression = [line for line in RULES.read_text().splitlines()
                      if "aa_profile:~\"^ghostship-plex//" in line]
        self.assertEqual(len(expression), 1, expression)
        self.assertNotIn("NOT", expression[0])
        self.assertNotIn("file_inherit", expression[0])
