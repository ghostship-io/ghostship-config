"""Load-bearing checks for the agent viewer: input mapping and the pause file protocol."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server

META = {"deviceWidth": 1568, "deviceHeight": 768, "offsetTop": 0, "pageScaleFactor": 1,
        "scrollOffsetX": 0, "scrollOffsetY": 0}


class MapPointTest(unittest.TestCase):
    def test_plain_frame_maps_to_viewport_css_px(self):
        """Catches scaling by the displayed image size instead of the device viewport (clicks land off-target)."""
        self.assertEqual(server.map_point(0.5, 0.25, META), (784.0, 192.0))
        self.assertEqual(server.map_point(0, 0, META), (0.0, 0.0))
        self.assertEqual(server.map_point(1, 1, META), (1568.0, 768.0))

    def test_scroll_offset_is_not_added(self):
        """Catches adding scrollOffsetX/Y: Input coordinates are viewport-relative, so a scrolled page would be mis-hit."""
        scrolled = dict(META, scrollOffsetX=200, scrollOffsetY=5000)
        self.assertEqual(server.map_point(0.5, 0.5, scrolled), server.map_point(0.5, 0.5, META))

    def test_page_scale_divides(self):
        """Catches ignoring pinch zoom: Chrome multiplies Input coords by pageScaleFactor (measured live)."""
        self.assertEqual(server.map_point(0.5, 0.5, dict(META, pageScaleFactor=2)), (392.0, 192.0))

    def test_offset_top_is_subtracted_and_clamped(self):
        """Catches ignoring the top-controls offset, and negative coordinates from taps on that strip."""
        meta = dict(META, offsetTop=56)
        self.assertEqual(server.map_point(0.5, 0.5, meta), (784.0, 328.0))
        self.assertEqual(server.map_point(0.5, 0.01, meta), (784.0, 0.0))

    def test_out_of_range_and_bad_metadata(self):
        """Catches clicks outside the window from overshooting drags and crashes on bogus metadata."""
        self.assertEqual(server.map_point(-1, 2, META), (0.0, 768.0))
        self.assertEqual(server.map_point(0.5, 0.5, dict(META, pageScaleFactor=0)), (784.0, 384.0))
        self.assertEqual(server.map_point(0.5, 0.5, dict(META, pageScaleFactor="x")), (784.0, 384.0))


class PauseProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.runs = os.path.join(self.root, "runs")
        os.mkdir(self.runs, 0o700)

    def tearDown(self):
        self.tmp.cleanup()

    def paused(self):
        return sorted(os.listdir(os.path.join(self.runs, "paused")))

    def test_pause_blocks_every_member_and_resume_clears(self):
        """Catches a pause that leaves a tab/popup drivable or a resume that leaves the gate closed."""
        members = ["AAAA1111", "BBBB2222", "CCCC3333"]
        server.pause_run(self.runs, "run_1", members, now=1700000000)
        self.assertEqual(self.paused(), members)
        with open(os.path.join(self.runs, "run_1.pause")) as handle:
            self.assertEqual(json.load(handle), {"by": "viewer", "at": 1700000000})
        self.assertTrue(server.is_paused(self.runs, "run_1"))
        server.sync_paused(self.runs, members + ["DDDD4444"])  # a popup opened while paused
        self.assertIn("DDDD4444", self.paused())
        server.resume_run(self.runs, "run_1", members + ["DDDD4444"])
        self.assertFalse(server.is_paused(self.runs, "run_1"))
        self.assertEqual(self.paused(), [])
        self.assertEqual(sorted(os.listdir(self.runs)), ["paused"])  # no temp files left behind

    def test_crafted_ids_cannot_escape_runs_dir(self):
        """Catches path traversal: run/target ids come from URLs and Chrome and must not write outside runs/."""
        for bad in ("../x", "..", "a/b", "", "x" * 65, "a\x00b", "/etc/passwd", ".hidden"):
            with self.assertRaises(ValueError):
                server.pause_run(self.runs, bad, ["AAAA1111"])
            with self.assertRaises(ValueError):
                server.resume_run(self.runs, bad, [])
        for bad in ("../../escape", "..", "a.b", "", "x/y"):
            with self.assertRaises(ValueError):
                server.pause_run(self.runs, "run_2", ["AAAA1111", bad])
        # A rejected target id must not leave a half-applied pause behind.
        self.assertFalse(server.is_paused(self.runs, "run_2"))
        self.assertFalse(os.path.exists(os.path.join(self.runs, "paused", "AAAA1111")))
        self.assertEqual(sorted(os.listdir(self.root)), ["runs"])

    def test_symlinked_pause_entry_is_not_followed(self):
        """Catches following a planted symlink in paused/ to create a file elsewhere."""
        os.mkdir(os.path.join(self.runs, "paused"), 0o700)
        outside = os.path.join(self.root, "outside")
        os.symlink(outside, os.path.join(self.runs, "paused", "AAAA1111"))
        server.pause_run(self.runs, "run_3", ["AAAA1111"])
        self.assertFalse(os.path.exists(outside))


if __name__ == "__main__":
    unittest.main()
