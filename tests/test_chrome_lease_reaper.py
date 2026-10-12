"""The desktop lease reaper closes only expired lease windows and their popups."""
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "containers/agent-desktop/root/opt/ghostship-agent-desktop/chrome-lease-reaper"
loader = importlib.machinery.SourceFileLoader("chrome_lease_reaper", str(PATH))
spec = importlib.util.spec_from_loader("chrome_lease_reaper", loader)
reaper = importlib.util.module_from_spec(spec)
loader.exec_module(reaper)

HEX = "0123456789abcdef" * 2
NOW = 1_800_000_000


def anchor(expires=None, token=HEX):
    return f"about:blank#ghostship-window-{token}" + ("" if expires is None else f".{expires}")


def page(target_id, url="https://example.test/", opener=None):
    info = {"targetId": target_id, "url": url, "type": "page"}
    if opener:
        info["openerId"] = opener
    return info


class Matching(unittest.TestCase):
    def test_expiry_parsing(self):
        self.assertEqual(reaper.expires_at(anchor(NOW)), NOW)
        for url in (anchor(), anchor(12345678), anchor(NOW) + "x", anchor(NOW, "A" * 32),
                    anchor(NOW, "0" * 31), "https://x/#ghostship-window-" + HEX + ".1800000000",
                    "about:blank", ""):
            self.assertIsNone(reaper.expires_at(url), url)

    def test_slack_is_respected(self):
        pages = [page("a", anchor(NOW - 120)), page("b", anchor(NOW - 121))]
        self.assertEqual(reaper.expired_anchors(pages, NOW, 120), ["b"])


class Plan(unittest.TestCase):
    def test_reaps_expired_window_its_tabs_and_popups_anchor_last(self):
        pages = [
            page("tab", opener="anc"), page("anc", anchor(NOW - 1000)),
            page("popup", opener="tab"), page("grandpopup", opener="popup"),
            page("live", anchor(NOW + 60)), page("live-tab", opener="live"),
            page("legacy", anchor()), page("legacy-tab"),
            page("user"),
        ]
        windows = {"tab": 1, "anc": 1, "popup": 2, "grandpopup": 3, "live": 4, "live-tab": 4,
                   "legacy": 5, "legacy-tab": 5, "user": 6}
        [(window, targets)] = reaper.plan(pages, windows, NOW, 120)
        self.assertEqual(window, 1)
        self.assertEqual(targets[-1], "anc")
        self.assertEqual(set(targets), {"tab", "anc", "popup", "grandpopup"})

    def test_never_touches_unexpired_legacy_or_user_windows(self):
        pages = [page("live", anchor(NOW + 60)), page("legacy", anchor()), page("user")]
        self.assertEqual(reaper.plan(pages, {"live": 1, "legacy": 2, "user": 3}, NOW, 120), [])

    def test_window_with_any_other_anchor_is_protected(self):
        pages = [page("old", anchor(NOW - 1000)), page("legacy", anchor(token="f" * 32))]
        self.assertEqual(reaper.plan(pages, {"old": 1, "legacy": 1}, NOW, 120), [])

    def test_popup_in_another_lease_window_survives(self):
        pages = [page("old", anchor(NOW - 1000)), page("live", anchor(NOW + 60, "e" * 32)),
                 page("opened", opener="old")]
        [(_, targets)] = reaper.plan(pages, {"old": 1, "live": 2, "opened": 2}, NOW, 120)
        self.assertEqual(targets, ["old"])

    def test_anchor_without_known_window_is_skipped(self):
        self.assertEqual(reaper.plan([page("old", anchor(NOW - 1000))], {}, NOW, 120), [])


if __name__ == "__main__":
    unittest.main()
