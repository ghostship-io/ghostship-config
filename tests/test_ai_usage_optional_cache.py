"""Optional announcements cannot abort collection when CI cannot read host state."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))
import announced_resets


class OptionalCacheTests(unittest.TestCase):
    def test_unreadable_cache_stays_unavailable_without_announcements(self):
        with patch.object(Path, 'read_text', side_effect=PermissionError('unreadable')):
            result = announced_resets.load('/unreadable-cache.json')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['announcements'], [])
