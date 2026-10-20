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


if __name__ == "__main__":
    unittest.main()
