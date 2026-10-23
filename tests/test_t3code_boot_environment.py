"""Minimal-image boot must provide tools before runtime-env initialization."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BootEnvironment(unittest.TestCase):
    def test_systemd_default_path_runs_the_real_early_desktop_probe(self):
        expression = '''let f = builtins.getFlake "path:__ROOT__";
          image = import __ROOT__/packages/t3code/image.nix {
            pkgs = f.inputs.nixpkgs.legacyPackages.${builtins.currentSystem};
          };
        in { commands = image.imageArgs.extraCommands;
          source = toString f.inputs.ghostship-private-agent; }'''.replace('__ROOT__', str(ROOT))
        result = subprocess.run(['nix','eval','--impure','--json','--expr',expression],
            capture_output=True,text=True,check=True,timeout=8)
        rendered = json.loads(result.stdout)
        # Read the command that failed in the actual managed helper, rather
        # than reproducing its implementation in a fixture.
        tooling = (Path(rendered['source'])/'packages/t3code/tooling.nix').read_text()
        probe = re.search(r'      desktop_host="\$\(sed.*', tooling).group(0).strip()
        commands = rendered['commands']
        self.assertTrue('for manager in system user;' in commands, 'both systemd managers need the startup PATH')
        startup_path = re.search(r'DefaultEnvironment=PATH=(.*)',commands)
        self.assertIsNotNone(startup_path, 'systemd helpers fail 127 before setting PATH')
        self.assertTrue(startup_path[1].startswith('/home/t3code/.local/state/ghostship-t3-tools/current/bin:'))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            tools = directory/'tools'
            tools.mkdir()
            for tool in ('sed','head'):
                (tools/tool).symlink_to(shutil.which(tool))
            known_hosts = directory/'known_hosts'
            known_hosts.write_text('[desktop.example.invalid]:2222 key\n')
            shell = 'set -eu\n'+probe+'\ntest "$desktop_host" = desktop.example.invalid\n'
            # Named host value is synthetic; no credentials or network needed.
            env = {'PATH':startup_path[1].replace('/home/t3code/.local/state/ghostship-t3-tools/current/bin', str(tools)),
                'desktop_hosts':str(known_hosts)}
            subprocess.run([shutil.which('bash'),'-c',shell],env=env,check=True,timeout=2)
