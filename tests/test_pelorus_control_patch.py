"""Native input must return a valid response without repeating the action."""
import asyncio
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "containers/agent-desktop/root/opt/ghostship-agent-desktop/pelorus-control-patch.py"
spec = importlib.util.spec_from_file_location("pelorus_patch", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SOURCE = '''async def desktop_control(body):
    resp = await _cu_action(body)
    return resp
'''


class Contract(unittest.TestCase):
    def call(self, response):
        calls = []
        async def action(body):
            calls.append(body)
            return response
        class HttpError(Exception):
            def __init__(self, status_code, detail):
                self.status_code = status_code
        scope = {"_cu_action": action, "HTTPException": HttpError}
        exec(module.rewrite(SOURCE), scope)
        try:
            return asyncio.run(scope["desktop_control"]({"action": "fixture"}))
        finally:
            self.assertEqual(calls, [{"action": "fixture"}])

    def test_known_backend_success_preserves_response_and_adds_status(self):
        for value in ({"text": "X=1,Y=2"}, {"data": "PNG"}, {"position": [1, 2]}):
            self.assertEqual(self.call(value), {**value, "result": "ok"})

    def test_errors_are_not_success_and_existing_status_is_preserved(self):
        self.assertEqual(self.call({"error": "failed"}), {"error": "failed", "result": "error"})
        self.assertEqual(self.call({"result": "ok"}), {"result": "ok"})

    def test_unknown_response_fails_after_exactly_one_action(self):
        for value in ({}, "unexpected"):
            with self.assertRaises(Exception) as caught:
                self.call(value)
            self.assertEqual(caught.exception.status_code, 502)

    def test_idempotent_patch_and_upstream_drift_fails_closed(self):
        fixed = module.rewrite(SOURCE)
        self.assertEqual(module.rewrite(fixed), fixed)
        with self.assertRaises(ValueError):
            module.rewrite(SOURCE.replace("return resp", "return other"))


if __name__ == "__main__":
    unittest.main()
