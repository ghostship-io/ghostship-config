import datetime
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "packages/t3code/opencode-model-catalog.py"
spec = importlib.util.spec_from_file_location("opencode_model_catalog", SOURCE)
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)

TODAY = datetime.date(2026, 10, 19)


def model(model_id, released, *, tools=True, cost=1, status=None):
    entry = {"id": model_id, "release_date": released, "tool_call": tools,
             "cost": {"input": cost, "output": cost}}
    if status:
        entry["status"] = status
    return entry


class Trim(unittest.TestCase):
    def source(self):
        return {
            "ollama-cloud": {"id": "ollama-cloud", "models": {
                "new": model("new", "2026-10-01"),
                "old": model("old", "2025-08-05"),
                "pinned-old": model("pinned-old", "2025-01-01"),
                "no-tools": model("no-tools", "2026-09-01", tools=False),
                "deprecated": model("deprecated", "2026-09-01", status="deprecated"),
            }},
            "openrouter": {"id": "openrouter", "models": {
                "a/new:free": model("a/new:free", "2026-09-01", cost=0),
                "a/new-paid": model("a/new-paid", "2026-09-01"),
                "a/old:free": model("a/old:free", "2025-01-01", cost=0),
            }},
            "groq": {"id": "groq", "models": {"legacy": model("legacy", "2023-01-01")}},
        }

    def test_keeps_recent_tool_models_free_openrouter_and_pins(self):
        result = catalog.trim(self.source(), TODAY, {"ollama-cloud/pinned-old"})
        self.assertEqual(sorted(result["ollama-cloud"]["models"]), ["new", "pinned-old"])
        self.assertEqual(sorted(result["openrouter"]["models"]), ["a/new:free"])
        # Providers outside the trimmed set pass through unchanged.
        self.assertEqual(result["groq"], self.source()["groq"])

    def test_new_releases_are_accepted_without_a_list(self):
        source = self.source()
        source["ollama-cloud"]["models"]["future"] = model("future", "2026-10-18")
        self.assertIn("future", catalog.trim(source, TODAY, set())["ollama-cloud"]["models"])

    def test_main_writes_output_and_keeps_previous_when_cache_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, config, output = root / "models.json", root / "opencode.jsonc", root / "out/models.json"
            source.write_text(json.dumps(self.source()))
            config.write_text(json.dumps({"model": "ollama-cloud/pinned-old"}))
            args = ["--source", str(source), "--config", str(config), "--output", str(output)]
            self.assertEqual(catalog.main(args), 0)
            self.assertIn("pinned-old", json.loads(output.read_text())["ollama-cloud"]["models"])
            source.unlink()
            before = output.read_text()
            self.assertEqual(catalog.main(args), 0)
            self.assertEqual(output.read_text(), before)


if __name__ == "__main__":
    unittest.main()
