"""Load-bearing checks for app-session: keyboard arguments and the pause/busy protocol."""
import asyncio
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
loader = importlib.machinery.SourceFileLoader("app_session", os.path.join(HERE, "app-session"))
spec = importlib.util.spec_from_loader("app_session", loader)
app_session = importlib.util.module_from_spec(spec)
sys.modules["app_session"] = app_session
loader.exec_module(app_session)


class KeyArgsTest(unittest.TestCase):
    def test_combos_press_and_release_every_modifier(self):
        """Catches a modifier left held (every later keystroke becomes a shortcut) or a key name wtype types literally."""
        self.assertEqual(app_session.Session.key_args("ctrl+shift+s"),
                         ["-M", "ctrl", "-M", "shift", "s", "-m", "shift", "-m", "ctrl"])
        self.assertEqual(app_session.Session.key_args("Enter"), ["-k", "Return"])
        self.assertEqual(app_session.Session.key_args("cmd+Tab"), ["-M", "logo", "-k", "Tab", "-m", "logo"])
        for bad in ("hyper+a", "", "ctrl+", "a b c d e f g h i j k l m n o p q r s t u v w x y z 0 1 2 3 4 5 6"):
            with self.assertRaises(ValueError, msg=bad):
                app_session.Session.key_args(bad)


class PauseProtocolTest(unittest.TestCase):
    def test_agent_input_refused_while_paused_and_busy_always_cleared(self):
        """Catches agent input landing after a person took over, or a stale busy marker that blocks takeovers."""
        with tempfile.TemporaryDirectory() as runs:
            app_session.RUNS = runs
            sid = "a" * 32
            session = app_session.Session.__new__(app_session.Session)
            session.sid, session.lock = sid, None
            done = []
            session.act = lambda action: done.append(action) or {"ok": True}

            async def run(actor):
                session.lock = asyncio.Lock()
                return await session.input_actions([{"action": "wait", "duration": 0}], actor)

            self.assertEqual(asyncio.run(run("agent"))["results"], [{"ok": True}])
            os.makedirs(os.path.join(runs, "paused"))
            open(os.path.join(runs, "paused", sid), "w").close()
            with self.assertRaises(app_session.AppError) as caught:
                asyncio.run(run("agent"))
            self.assertEqual(caught.exception.kind, "paused")
            self.assertEqual(len(done), 1)
            self.assertFalse(os.path.exists(os.path.join(runs, "busy", sid)))
            asyncio.run(run("human"))  # the person keeps control while paused
            self.assertEqual(len(done), 2)


class CloseTest(unittest.TestCase):
    def test_forced_close_asks_again_past_a_dialog_and_plain_close_never_forces(self):
        """Catches a person's x leaving the app open behind a dialog, or an agent's close discarding work."""
        class Proc:
            def __init__(self, closes_needed):
                self.left, self.pid = closes_needed, 0
            def poll(self):
                return 0 if self.left <= 0 else None

        def session(closes_needed):
            s = app_session.Session.__new__(app_session.Session)
            s.proc, s.sway, s.done = Proc(closes_needed), None, asyncio.Event()
            s.kills = 0
            def swaymsg(*args):
                s.kills += 1
                s.proc.left -= 1
            s.swaymsg = swaymsg
            return s

        app_session.CLOSE_SECONDS = 5
        forced = session(2)  # the first close only dismisses a dialog
        self.assertTrue(asyncio.run(forced.close(force=True)))
        self.assertEqual(forced.kills, 2)
        plain = session(2)
        self.assertFalse(asyncio.run(plain.close(force=False)))
        self.assertEqual(plain.kills, 1)


class AdoptTest(unittest.TestCase):
    def test_agent_joining_a_persons_session_takes_ownership(self):
        """Catches an agent driving a person-launched app the viewer never pauses (owner left "human")."""
        with tempfile.TemporaryDirectory() as runs:
            app_session.RUNS = runs
            sid = "b" * 32
            app_session.write_json(app_session.record_path(sid), {"kind": "app", "app": "orca",
                                                                  "owner": {"harness": "human"}})
            agent = {"harness": "claude-code", "model": "m", "t3_thread_id": "t", "t3_thread_title": "x"}
            app_session.Supervisor.adopt(sid, {"harness": "human"})
            self.assertEqual(app_session.read_record(sid)["owner"]["harness"], "human")
            app_session.Supervisor.adopt(sid, agent)
            self.assertEqual(app_session.read_record(sid)["owner"], agent)
            app_session.Supervisor.adopt(sid, dict(agent, harness="codex"))  # first agent keeps it
            self.assertEqual(app_session.read_record(sid)["owner"]["harness"], "claude-code")


if __name__ == "__main__":
    unittest.main()
