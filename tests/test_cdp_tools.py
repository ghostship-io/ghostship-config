import importlib.util
import pathlib
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1] / "containers/agent-desktop/root/opt/ghostship-agent-desktop/tools"


def load(name):
    spec = importlib.util.spec_from_file_location(f"cdp_tools_{name}", TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetailerHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retailer = load("run_retailer")

    def test_classify(self):
        self.assertEqual(self.retailer.classify("Oops!! Something went wrong. Please refresh page"), "error_page")
        self.assertEqual(self.retailer.classify("Access Denied"), "error_page")
        self.assertEqual(self.retailer.classify("Request blocked by Akamai"), "blocked")
        self.assertEqual(self.retailer.classify("Verify you are human"), "challenge")
        self.assertEqual(self.retailer.classify("Cordless Drills"), "ok")

    def test_incomplete_pages_are_rejected(self):
        self.assertEqual(self.retailer.classify("Cordless Drills", "search"), "incomplete")
        self.assertEqual(self.retailer.classify("225 results Add to Cart All Filters", "search"), "ok")
        self.assertEqual(self.retailer.classify("Add to Cart $189.00", "product"), "ok")

    def test_stats_deduplicates_products(self):
        stats = self.retailer.stats(
            "price $ 189 and $99 see /p/abc",
            ["https://www.homedepot.com/p/abc/1", "https://www.homedepot.com/p/abc/1", "https://www.homedepot.com/p/def/2"],
        )
        self.assertEqual(stats["prices"], 2)
        self.assertEqual(stats["unique_products"], 2)
        self.assertEqual(len(stats["product_urls"]), 2)


class MatrixDefinitionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = load("run_cdp_matrix")

    def test_positive_control_enables_runtime(self):
        self.assertIn("runtime_enable", self.matrix.VARIANTS["A13"])

    def test_clean_variants_never_enable_runtime(self):
        for variant in ("A6", "A7", "A8", "A9", "A10", "A11", "A12", "B7P"):
            self.assertNotIn("runtime_enable", self.matrix.VARIANTS[variant], variant)
        self.assertNotIn("runtime_enable", self.matrix.CLEAN_OPS)


class RegressionEvaluatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.check = load("check_cdp_regression")

    def row(self, variant, detected, ready=True, reports=10, error=None, executed=None, output="ok"):
        return {
            "variant": variant,
            "ready": ready,
            "reports": reports,
            "error": error,
            "after_detected": detected,
            "detected_reports": 4 if detected else 0,
            "executed": executed or [],
            "output": output,
        }

    def base_rows(self):
        return [
            self.row("A6", False, executed=["Target.attachToTarget"]),
            self.row("A10", False, executed=["Runtime.evaluate"]),
            self.row("A13", True, executed=["Runtime.enable"]),
            self.row("C2", False, executed=["bladebro see content --port 9330 exit=0"]),
        ]

    def test_clean_matrix_passes(self):
        self.assertEqual(self.check.evaluate_results(self.base_rows()), [])

    def test_missing_result_fails(self):
        failures = self.check.evaluate_results(self.base_rows()[:-1])
        self.assertTrue(any("C2: missing result" in failure for failure in failures))

    def test_zero_samples_fails(self):
        rows = self.base_rows()
        rows[0]["reports"] = 0
        failures = self.check.evaluate_results(rows)
        self.assertTrue(any("too few page samples" in failure for failure in failures))

    def test_chrome_startup_failure_fails(self):
        rows = self.base_rows()
        rows[0]["ready"] = False
        failures = self.check.evaluate_results(rows)
        self.assertTrue(any("chrome not ready" in failure for failure in failures))

    def test_command_error_fails(self):
        rows = self.base_rows()
        rows[3]["error"] = "chrome exited"
        failures = self.check.evaluate_results(rows)
        self.assertTrue(any("C2: error chrome exited" in failure for failure in failures))

    def test_failed_command_fails(self):
        rows = self.base_rows()
        rows[3]["executed"] = ["bladebro see content --port 9330 exit=1"]
        failures = self.check.evaluate_results(rows)
        self.assertTrue(any("command did not succeed" in failure for failure in failures))

    def test_wrong_detection_fails(self):
        rows = self.base_rows()
        rows[0]["after_detected"] = True
        rows[0]["detected_reports"] = 3
        failures = self.check.evaluate_results(rows)
        self.assertTrue(any("A6: detected=True expected=False" in failure for failure in failures))

    def test_unstable_positive_control_fails(self):
        rows = self.base_rows()
        rows[2]["detected_reports"] = 1
        failures = self.check.evaluate_results(rows)
        self.assertTrue(any("unstable detection" in failure for failure in failures))

    def test_missing_operation_fails(self):
        rows = self.base_rows()
        rows[1]["executed"] = []
        failures = self.check.evaluate_results(rows)
        self.assertTrue(any("expected operation Runtime.evaluate missing" in failure for failure in failures))


class ExtensionTransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ext = TOOLS / "ext"

    def test_manifest_is_valid_mv3(self):
        import json

        manifest = json.loads((self.ext / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertIn("tabs", manifest["permissions"])
        self.assertIn("scripting", manifest["permissions"])

    def test_service_worker_present(self):
        source = (self.ext / "background.js").read_text(encoding="utf-8")
        self.assertIn("chrome.scripting.executeScript", source)
        self.assertIn("/ext/next", source)


if __name__ == "__main__":
    unittest.main()
