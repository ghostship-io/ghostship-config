"""The homepage widget destination file exists before the container starts (#463)."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOMEPAGE = ROOT / "modules/self-hosted/homepage.nix"


class WidgetEnvTests(unittest.TestCase):
    def test_the_private_widget_env_is_declared_and_mounted(self):
        text = HOMEPAGE.read_text()
        self.assertIn('f /etc/ghostship/homepage-widgets.env 0600 root root -', text)
        self.assertIn('"/etc/ghostship/homepage-widgets.env"', text)

    def test_the_widget_uses_runtime_coordinates_and_a_neutral_label(self):
        text = HOMEPAGE.read_text()
        self.assertIn('2.openmeteo.label=literal:Home', text)
        self.assertIn('{{HOMEPAGE_VAR_HOME_LAT}}', text)
        self.assertIn('{{HOMEPAGE_VAR_HOME_LON}}', text)


if __name__ == "__main__":
    unittest.main()
