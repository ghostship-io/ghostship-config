"""Public lease records authorize only bound, expired Chrome windows."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / "containers/agent-desktop/root/opt/ghostship-agent-desktop/chrome-lease-reaper"
loader = importlib.machinery.SourceFileLoader("chrome_lease_reaper", str(PATH))
spec = importlib.util.spec_from_loader("chrome_lease_reaper", loader)
reaper = importlib.util.module_from_spec(spec)
loader.exec_module(reaper)
NOW = 1800000000


def lease(target="A", window=1, expiry=NOW-1000, marker="a"*32, identity="agent"):
    return dict(schema=2, run_id=marker, identity=identity, target_id=target,
                chrome_window_id=window, expires_at=expiry)


def page(tid, opener=None):
    return dict(targetId=tid, openerId=opener, type="page", url="https://example.test/")


class Plan(unittest.TestCase):
    def test_expired_owner_window_and_dedicated_popups_close_human_survives(self):
        pages = [page("A"), page("B"), page("POP", "B"), page("CHILD", "POP"), page("HUMAN")]
        windows = dict(A=1, B=1, POP=2, CHILD=3, HUMAN=4)
        [(wid, targets)] = reaper.plan(pages, windows, [lease()], NOW, 120)
        self.assertEqual(wid, 1)
        self.assertEqual(set(targets), {"A", "B", "POP", "CHILD"})

    def test_stale_target_binding_cannot_reap_a_reused_window_id(self):
        self.assertEqual(reaper.plan([page("HUMAN")], {"HUMAN": 1}, [lease()], NOW, 0), [])
        self.assertEqual(reaper.plan([page("A")], {"A": 9}, [lease()], NOW, 0), [])

    def test_surviving_recorded_tab_binds_window_after_first_tab_was_closed_by_hand(self):
        row = dict(lease(), target_ids=["A", "B"])
        self.assertEqual(reaper.plan([page("B")], {"B": 1}, [row], NOW, 0), [(1, ["B"])])

    def test_unexpired_and_slack_boundary_are_protected(self):
        for expires in (NOW+10, NOW-120):
            self.assertEqual(reaper.plan([page("A")], {"A": 1}, [lease(expiry=expires)], NOW, 120), [])

    def test_live_record_protects_window_even_with_an_expired_record(self):
        self.assertEqual(reaper.plan([page("A"), page("B")], dict(A=1, B=1),
                         [lease(), lease("B", expiry=NOW+60)], NOW, 0), [])

    def test_popup_moved_into_human_or_live_lease_window_is_untouched(self):
        pages = [page("A"), page("POP", "A"), page("HUMAN")]
        [(_, targets)] = reaper.plan(pages, dict(A=1, POP=2, HUMAN=2), [lease()], NOW, 0)
        self.assertEqual(targets, ["A"])
        [(_, targets)] = reaper.plan(pages, dict(A=1, POP=2, HUMAN=2),
                                  [lease(), lease("HUMAN", 2, NOW+60)], NOW, 0)
        self.assertEqual(targets, ["A"])


class Records(unittest.TestCase):
    def test_malformed_symlink_oversize_wrong_identity_and_nonfinite_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/("a"*32+".json")
            good = lease()
            path.write_text(json.dumps(good))
            self.assertEqual(reaper.records(directory, "agent"), [good])
            self.assertEqual(reaper.records(directory, "personal"), [])
            for change in ({"target_id": "../x"}, {"chrome_window_id": True}, {"expires_at": float("nan")},
                           {"schema": 1}, {"run_id": "b"*32}):
                path.write_text(json.dumps(dict(good, **change)))
                self.assertEqual(reaper.records(directory, "agent"), [])
            path.write_text("x"*16385)
            self.assertEqual(reaper.records(directory, "agent"), [])
            path.unlink()
            outside=Path(directory)/"outside"
            outside.write_text(json.dumps(good))
            path.symlink_to(outside)
            self.assertEqual(reaper.records(directory, "agent"), [])

    def test_idle_never_stops_a_human_blank_page(self):
        text=PATH.with_name("chrome-idle").read_text()
        function=text[text.index("no_pages() {"):text.index("\nreachable()")]
        for targets, idle in (([], True), ([dict(type="page", url="about:blank")], False),
                              ([dict(type="page",url="https://example.test/")], False)):
            result=subprocess.run(["bash","-c",function+"\nno_pages"], input=json.dumps(targets),
                                  text=True, capture_output=True)
            self.assertEqual(result.returncode == 0, idle, result.stderr)


if __name__ == "__main__":
    unittest.main()
