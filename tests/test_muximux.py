import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / "modules/self-hosted/muximux-save-config.php"


class MuximuxTests(unittest.TestCase):
    def test_initialized_application_is_patched_idempotently_and_unknown_code_fails(
        self,
    ):
        patcher = ROOT / "modules/self-hosted/muximux-patch-writer.php"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "muximux.php"
            target.write_text(
                "<?php\nfunction saveConfig($inConfig) {\n    die('old');\n}\n"
            )
            command = ["php", str(patcher), str(target), str(WRITER)]
            subprocess.run(command, check=True, capture_output=True)
            first = target.read_text()
            self.assertNotIn("die('old')", first)
            self.assertIn("rename($temporary, CONFIG)", first)
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(target.read_text(), first)
            target.write_text("<?php // changed upstream contract\n")
            result = subprocess.run(command, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_text(), "<?php // changed upstream contract\n")

    def test_atomic_settings_keep_guard_and_preserve_original_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "settings.ini.php"
            original = "; <?php die('Access denied'); ?>\n[general]\ntitle = initial\n"
            target.write_text(original)
            script = root / "write.php"
            script.write_text(
                "<?php\n"
                + "define('CONFIG', "
                + json.dumps(str(target))
                + ");\n"
                + "require "
                + json.dumps(str(WRITER))
                + ";\n"
                + """
class FixtureConfig {
    public $fail = false;
    function get() { return array(); }
    function write($path, $data, $flags) {
        file_put_contents($path, "[general]\\ntitle = complete\\n", $flags);
        if ($this->fail) { throw new RuntimeException('simulated writer failure'); }
        usleep(1000);
    }
}
$config = new FixtureConfig();
$config->fail = true;
$before = file_get_contents(CONFIG);
try { saveConfig($config); exit(2); } catch (RuntimeException $error) {}
if (file_get_contents(CONFIG) !== $before) { exit(3); }
$config->fail = false;
for ($i = 0; $i < 100; $i++) { saveConfig($config); }
"""
            )
            with subprocess.Popen(
                ["php", str(script)], stderr=subprocess.PIPE
            ) as process:
                while process.poll() is None:
                    data = target.read_text()
                    self.assertIn(
                        data, [original, original.replace("initial", "complete")]
                    )
                self.assertEqual(process.returncode, 0, process.stderr.read().decode())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(root.glob(".muximux-config-*")), [])
            result = subprocess.check_output(
                [
                    "php",
                    "-r",
                    "echo json_encode(parse_ini_file($argv[1], true));",
                    str(target),
                ],
                text=True,
            )
            self.assertEqual(json.loads(result), {"general": {"title": "complete"}})
