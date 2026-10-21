"""Load-bearing checks for stage-control: which Chrome window a sway window shows."""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
loader = importlib.machinery.SourceFileLoader("stage_control", os.path.join(HERE, "stage-control"))
spec = importlib.util.spec_from_loader("stage_control", loader)
stage_control = importlib.util.module_from_spec(spec)
loader.exec_module(stage_control)


def stage():
    s = stage_control.Stage.__new__(stage_control.Stage)
    s.pairs, s.anchor_titles = {}, {}
    return s


def node(con, title):
    return {"id": con, "name": f"{title} - Google Chrome"}


def tab(title, url="https://example.test/"):
    return {"title": title, "url": url, "targetId": title + url}


class PairTest(unittest.TestCase):
    def test_windows_mapped_out_of_creation_order_pair_by_title_not_order(self):
        """Catches showing another run's window when concurrent windows map out of order (seen with 8 agents)."""
        s = stage()
        nodes = [node(5, "bench-a2"), node(6, "bench-a1"), node(7, "bench-a3")]
        groups = {100: [tab("bench-a1")], 101: [tab("bench-a2")], 102: [tab("bench-a3")]}
        self.assertEqual(s.pair(nodes, groups), {5: 101, 6: 100, 7: 102})

    def test_identical_titles_stay_unpaired_until_they_differ_then_stick(self):
        """Catches guessing between two windows on the same page; a pair must survive later title collisions."""
        s = stage()
        nodes = [node(5, "Shop"), node(6, "Shop")]
        groups = {100: [tab("Shop")], 101: [tab("Shop")]}
        self.assertEqual(s.pair(nodes, groups), {})
        nodes[0] = node(5, "Cart")
        groups[100] = [tab("Cart")]
        self.assertEqual(s.pair(nodes, groups), {5: 100, 6: 101})  # the last one by elimination
        nodes[0] = node(5, "Shop")
        groups[100] = [tab("Shop")]
        self.assertEqual(s.pair(nodes, groups), {5: 100, 6: 101})

    def test_home_tab_title_pairs_a_run_window_even_among_identical_titles(self):
        """Catches a run window whose working tab title collides with another window's."""
        s = stage()
        s.anchor_titles = {6: "a" * 32}
        nodes = [node(5, "Shop"), node(6, "Shop"), node(7, "Shop")]
        anchor = tab("about:blank", "about:blank#ghostship-window-" + "a" * 32 + ".99")
        groups = {100: [tab("Shop")], 101: [anchor, tab("Shop")], 102: [tab("Shop")]}
        self.assertEqual(s.pair(nodes, groups), {6: 101})
        self.assertEqual(s.run_of(groups[101]), "a" * 32)


class AgentInputTest(unittest.TestCase):
    def test_agent_browser_controls_refused_while_a_person_holds_the_run(self):
        """Catches an agent clicking Chrome's toolbar during a takeover, or leaving busy markers behind."""
        with tempfile.TemporaryDirectory() as runs:
            stage_control.RUNS = runs
            s = stage()
            s.windows = {6: {"output": "HEADLESS-2"}}
            seen = []
            s._input = lambda con, actions, actor: seen.append(
                sorted(os.listdir(os.path.join(runs, "busy")))) or {"ok": True}
            s.input(6, [{"action": "wait"}], "agent", run_id="r" * 32, targets=["TAB1", "TAB2"])
            self.assertEqual(seen, [["TAB1", "TAB2"]])  # busy while acting
            open(os.path.join(runs, "r" * 32 + ".pause"), "w").close()
            with self.assertRaises(stage_control.StageError) as caught:
                s.input(6, [{"action": "wait"}], "agent", run_id="r" * 32, targets=["TAB1", "TAB2"])
            self.assertEqual(caught.exception.kind, "paused")
            self.assertEqual(len(seen), 1)
            self.assertEqual(os.listdir(os.path.join(runs, "busy")), [])
            s.input(6, [{"action": "wait"}], "human")  # the person keeps control
            self.assertEqual(len(seen), 2)


class FakeIpc:
    def __init__(self):
        self.commands = []

    def command(self, text):
        self.commands.append(text)

    def request(self, kind, payload=""):
        return [{"name": "HEADLESS-1", "active": True, "rect": {"x": 0, "y": 1080, "width": 1920, "height": 1080}},
                {"name": "HEADLESS-2", "active": True, "rect": {"x": 1920, "y": 0, "width": 1920, "height": 1080}}]


class FakeDevices:
    def __init__(self, on_button=None):
        self.moves, self.on_button = [], on_button

    def move(self, x, y, width, height):
        self.moves.append((x, y))

    def button(self, name, pressed):
        if self.on_button:
            self.on_button()


def live_stage(devices):
    import threading
    s = stage()
    s.ipc, s.devices, s.env = FakeIpc(), devices, {}
    s.windows, s.pointers, s.lease = {6: {"output": "HEADLESS-2"}}, {}, None
    s.lock, s.input_lock = threading.Lock(), threading.Lock()
    s.window_rect = lambda con: {"width": 1600, "height": 900}
    return s


class LeaseTest(unittest.TestCase):
    def test_a_long_batch_keeps_its_lease(self):
        """Catches the idle timer moving focus away while a batch is still typing (keys would go nowhere)."""
        idle, stage_control.LEASE_IDLE = stage_control.LEASE_IDLE, 0.0
        try:
            s = live_stage(None)
            s.devices = FakeDevices(on_button=lambda: (s.expire(), s.release(6)))
            s._input(6, [{"action": "left_click", "coordinate": [10, 10]}], "agent")
            self.assertNotIn("workspace idle", s.ipc.commands)  # neither expiry nor release cut in
            s.expire()  # once the batch is done, the lease ends as usual
            self.assertIsNone(s.lease)
        finally:
            stage_control.LEASE_IDLE = idle

    def test_coordinate_free_click_acts_where_the_window_pointer_was_left(self):
        """Catches a click after a separate mouse_move landing at the window centre."""
        s = live_stage(FakeDevices())
        s._input(6, [{"action": "mouse_move", "coordinate": [100, 200]}], "agent")
        s._input(6, [{"action": "left_click"}], "agent")
        self.assertEqual(s.devices.moves, [(2020, 200), (2020, 200)])
        self.assertEqual(s._input(6, [{"action": "cursor_position"}], "agent")["results"][0]["position"], [100, 200])


if __name__ == "__main__":
    unittest.main()
