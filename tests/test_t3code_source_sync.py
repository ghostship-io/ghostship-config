"""The host fallback selects the canonical managed agent installer."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

class HostManagedInstaller(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = {**os.environ, "HOME": str(self.home)}
    def test_host_bootstrap_fallback_executes_the_monotonic_selector(self):
        import json, re, sys
        module=Path(__file__).resolve().parents[1]/'modules/self-hosted/inference-bridge.nix'
        body=re.search(r'managedInstall = pkgs.writeShellScript "[^\"]+" \'\'\n(.*?)\n  \'\';',module.read_text(),re.S).group(1)
        source=self.root/'pinned-source'
        (source/'tools').mkdir(parents=True)
        (source/'tools/setup-container-agents.py').write_text(
            'import json,os,sys\nfrom pathlib import Path\n'
            'Path(os.environ["HOME"],"bootstrap-args").write_text(json.dumps(sys.argv[1:]))\n')
        for key,value in {'${pkgs.python3}/bin/python':sys.executable,
                          '${inputs.ghostship-private-agent}':str(source),
                          '${containerHome}':str(self.home),'${tools.default}':str(self.root/'package')}.items():
            body=body.replace(key,value)
        self.assertNotIn('${',body)
        subprocess.run(['bash','-c',body],env=self.env,check=True,timeout=5)
        args=json.loads((self.home/'bootstrap-args').read_text())
        self.assertIn('--refresh',args)
        self.assertIn('--managed-only',args)
        self.assertEqual(args[args.index('--source')+1],str(source))
