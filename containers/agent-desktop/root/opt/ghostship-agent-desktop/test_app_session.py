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


if __name__ == "__main__":
    unittest.main()
