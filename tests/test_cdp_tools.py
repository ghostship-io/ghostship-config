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
        self.assertEqual(self.retailer.classify("Access Denied"), "blocked")
        self.assertEqual(self.retailer.classify("Verify you are human"), "challenge")
        self.assertEqual(self.retailer.classify("Cordless Drills"), "ok")

    def test_product_stats(self):
        stats = self.retailer.product_stats("price $ 189 and $99 see /p/abc")
        self.assertEqual(stats["prices"], 2)
        self.assertEqual(stats["product_links"], 1)


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

    def test_regression_expectations(self):
        expected = load("check_cdp_regression").EXPECT
        self.assertFalse(expected["A6"])
        self.assertFalse(expected["A10"])
        self.assertTrue(expected["A13"])
        self.assertFalse(expected["C2"])


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
