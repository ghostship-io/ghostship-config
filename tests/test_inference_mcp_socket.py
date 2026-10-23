"""MCP transport must survive ownership reconciliation of the coding home."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InferenceSocketMountTests(unittest.TestCase):
    def test_mcp_socket_is_independent_of_the_coding_home(self):
        # This is a static configuration guard: no host, evaluator, package
        # graph or network is needed by the fast unit gate.
        module = (ROOT / 'modules/self-hosted/inference-bridge.nix').read_text()
        literals = dict(re.findall(r'^\s*(\w+) = "([^"\n]*)";', module, re.MULTILINE))
        block = re.search(
            r'virtualisation\.oci-containers\.containers\.ghostship-private-integrations'
            r'\.volumes\s*=\s*\[([^]]*)\]', module)
        self.assertIsNotNone(block, 'MCP socket bind must be declared')
        mounts = re.findall(r'"([^"\n]+)"', block.group(1))
        endpoint = '/run/ghostship-integrations/inference-socket'
        selected = [mount.split(':') for mount in mounts if mount.split(':')[1] == endpoint]
        self.assertEqual(len(selected), 1)
        source, _, access = selected[0]
        source = re.sub(r'\$\{(\w+)\}', lambda match: literals[match[1]], source)
        self.assertEqual(access, 'ro')
        self.assertFalse(Path(source).is_relative_to(literals['hostHome']),
                         'a coding-home chown can remove MCP access to the socket')
        self.assertEqual(Path(source).name, 'socket')
