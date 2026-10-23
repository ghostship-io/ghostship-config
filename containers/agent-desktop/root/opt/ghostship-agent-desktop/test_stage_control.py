"""Load-bearing checks for stage-control: which Chrome window a sway window shows."""
import importlib.machinery
import importlib.util
import os
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
loader = importlib.machinery.SourceFileLoader("stage_control", os.path.join(HERE, "stage-control"))
spec = importlib.util.spec_from_loader("stage_control", loader)
stage_control = importlib.util.module_from_spec(spec)
loader.exec_module(stage_control)


def stage():
    s = stage_control.Stage.__new__(stage_control.Stage)
    s.pairs, s.target_windows, s.identity = {}, {}, "agent"
    return s


def node(con, title):
    return {"id": con, "name": f"{title} - Google Chrome"}


def tab(title, url="https://example.test/"):
    return {"title": title, "url": url, "targetId": title + url}


RUN_A = "a" * 32
RUN_B = "b" * 32


def sway_window(con, run):
    """A sway window showing a real work tab with a distinct title."""
    return {"id": con, "pid": 100 + con, "rect": {"x": 0, "y": 0, "width": 1600, "height": 900},
            "name": f"Work {run} - Google Chrome"}


def sway_tree():
    """A sway tree with two Chrome windows, each on its own output and workspace."""
    return {"type": "root", "nodes": [
        {"type": "output", "name": "HEADLESS-0", "nodes": [{"type": "workspace", "name": "idle", "nodes": []}]},
        {"type": "output", "name": "HEADLESS-1", "nodes": [
            {"type": "workspace", "name": "w-HEADLESS-1", "nodes": [sway_window(5, RUN_A)]}]},
        {"type": "output", "name": "HEADLESS-2", "nodes": [
            {"type": "workspace", "name": "w-HEADLESS-2", "nodes": [sway_window(6, RUN_B)]}]}]}


def stage_outputs():
    return [{"name": name, "active": True, "rect": {"x": 1920 * index, "y": 0, "width": 1920, "height": 1080}}
            for index, name in enumerate(("HEADLESS-0", "HEADLESS-1", "HEADLESS-2"))]


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

    def test_identical_titles_without_an_anchor_stay_unpaired(self):
        s = stage()
        self.assertEqual(s.pair([node(5, "Shop"), node(6, "Shop")],
                                {100: [tab("Shop")], 101: [tab("Shop")]}), {})


class RestartTest(unittest.TestCase):
    def test_pairs_are_restored_after_a_stage_restart(self):
        """Catches a restart dropping the sway<->Chrome link: screenshot/ui then fail with not_found."""
        s = stage()
        s.ipc = FakeIpc(tree=sway_tree(), outputs=stage_outputs())
        s.devices = FakeDevices()
        s.windows, s.outputs, s.base_output = {}, [], None
        s.refresh_screens = lambda: None
        s.setup()
        groups = {100: [tab(f"Work {RUN_A}")],
                  101: [tab(f"Work {RUN_B}")]}
        self.assertEqual(s.pair(s.tree_windows(), groups), {5: 100, 6: 101})



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
    def __init__(self, tree=None, outputs=None):
        self.commands = []
        self.tree = tree or []
        self.outputs = outputs or [{"name": "HEADLESS-1", "active": True, "rect": {"x": 0, "y": 1080, "width": 1920, "height": 1080}},
                                   {"name": "HEADLESS-2", "active": True, "rect": {"x": 1920, "y": 0, "width": 1920, "height": 1080}}]

    def command(self, text):
        self.commands.append(text)

    def request(self, kind, payload=""):
        if kind == stage_control.GET_TREE:
            return self.tree
        return self.outputs


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
            s.devices = FakeDevices(on_button=lambda: (s.expire(), s.release(6, actor="agent")))
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


class ReleaseTest(unittest.TestCase):
    def held_lease(self, actor):
        s = live_stage(FakeDevices())
        s.lease = {"con": 6, "actor": actor, "last": time.monotonic(), "batches": 0}
        return s

    def test_the_viewer_dropping_its_client_does_not_close_an_agent_s_lease(self):
        """Catches the viewer closing the Chrome menu an agent is working with."""
        s = self.held_lease("agent")
        s.handle({"op": "release", "con": 6, "actor": "human"})
        self.assertIsNotNone(s.lease)
        self.assertNotIn("workspace idle", s.ipc.commands)

    def test_the_holder_releases_its_own_lease(self):
        """Catches a lease that nobody can give back: the window would keep the focus."""
        s = self.held_lease("agent")
        s.handle({"op": "release", "con": 6, "actor": "agent"})
        self.assertIsNone(s.lease)
        self.assertIn("workspace idle", s.ipc.commands)

    def test_an_admin_release_forces_the_lease_down(self):
        """Catches a lease with no way out but waiting for the idle timer."""
        s = self.held_lease("agent")
        s.handle({"op": "release", "con": 6, "admin": True})
        self.assertIsNone(s.lease)
        self.assertIn("workspace idle", s.ipc.commands)

    def test_an_agent_cannot_force_a_person_s_lease_away(self):
        """Catches an agent taking the window a person is working in."""
        request = stage_control.agent_request({"op": "release", "con": 6, "admin": True})
        self.assertEqual(request, {"op": "release", "con": 6, "actor": "agent"})
        s = self.held_lease("human")
        s.handle(request)
        self.assertIsNotNone(s.lease)
        self.assertNotIn("workspace idle", s.ipc.commands)


if __name__ == "__main__":
    unittest.main()
