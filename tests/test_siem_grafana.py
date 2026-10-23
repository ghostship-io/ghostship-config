"""Grafana's SIEM UI configuration (modules/self-hosted/siem/ui.nix).

The browser reaches Grafana through Cloudflare Access, and the auth proxy
trusts only cloudflared's address. Grafana must not also keep an account that
a password path could use, so it creates no administrator at all.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "modules/self-hosted/siem/ui.nix"


def grafana_environment():
    """The environment of the grafana container, as a mapping.

    A value is either a quoted string or a name from the module, such as the
    cloudflared address the auth proxy trusts.
    """
    text = UI.read_text()
    start = text.index("grafana = {")
    block = text[start:text.index("cloudflared.extraOptions", start)]
    begin = block.index("environment = {")
    end = block.index("};", begin)
    assignments = re.findall(
        r'(?m)^\s*([A-Z0-9_]+) = (?:"([^"]*)"|([A-Za-z0-9_.-]+));$', block[begin:end])
    return {key: quoted or bare for key, quoted, bare in assignments}


def grafana_volumes():
    """The volumes the grafana container mounts, as (source, target, options)."""
    text = UI.read_text()
    start = text.index("\n    grafana = {")
    block = text[start:text.index("\n    cloudflared.extraOptions", start)]
    begin = block.index("volumes = [")
    end = block.index("];", begin)
    mounts = []
    for entry in re.findall(r'"([^"]+)"', block[begin:end]):
        source, target, options = entry.rsplit(":", 2)
        mounts.append((source, target, options))
    return mounts


def provisioning_script():
    """The shell script that builds the store path mounted at /etc/grafana/provisioning."""
    text = UI.read_text()
    match = re.search(
        r'provisioning = pkgs\.runCommand "grafana-siem-provisioning"[^\n]*\n(.*?)\n[ \t]*\'\';',
        text, re.S)
    if not match:
        raise AssertionError("the module does not build the provisioning store path")
    return match.group(1)


def provisioning_tree():
    """The tree the provisioning store path holds, as paths relative to its root.

    The script is read the way the build runs it: `mkdir` makes a directory,
    `cp` puts a file into one, and a wildcard copy leaves the names of the
    files it copies to the build. A command the test does not know fails it,
    so the tree can never pass by leaving the store path unchecked.
    """
    directories = set()
    files = set()
    for line in provisioning_script().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        words = line.split()
        command = words[0]
        arguments = [word for word in words[1:] if not word.startswith("-")]
        if command == "mkdir":
            for argument in arguments:
                if not argument.startswith("$out/"):
                    continue
                parts = argument[len("$out/"):].strip("/").split("/")
                for index in range(len(parts)):
                    directories.add("/".join(parts[:index + 1]))
        elif command in ("cp", "install", "ln"):
            if len(arguments) < 2 or not arguments[-1].startswith("$out/"):
                continue
            name = arguments[-1][len("$out/"):]
            if name.endswith("/"):
                # A wildcard copy: the file names are only known at build time.
                files.add(name + "*")
            else:
                files.add(name)
        elif command in ("chmod", "chown", "rm", "true"):
            continue
        else:
            raise AssertionError(f"the provisioning script uses an unknown command: {command}")
    return directories, files


class GrafanaAccountTests(unittest.TestCase):
    def setUp(self):
        self.environment = grafana_environment()

    def test_grafana_creates_no_default_administrator(self):
        # Grafana creates admin/admin on the first start unless it is told
        # not to, and the account outlives the login paths below.
        self.assertEqual(
            self.environment.get("GF_SECURITY_DISABLE_INITIAL_ADMIN_CREATION"), "true")
        # The well-known password must not be configured either.
        self.assertNotIn("GF_SECURITY_ADMIN_PASSWORD", self.environment)
        self.assertNotIn("GF_SECURITY_ADMIN_USER", self.environment)

    def test_the_password_paths_stay_closed(self):
        # No form login, no basic auth, no anonymous access, no sign-up:
        # the only way in is the auth proxy, which trusts the header from
        # cloudflared's fixed address alone.
        self.assertEqual(self.environment.get("GF_AUTH_DISABLE_LOGIN_FORM"), "true")
        self.assertEqual(self.environment.get("GF_AUTH_BASIC_ENABLED"), "false")
        self.assertEqual(self.environment.get("GF_AUTH_ANONYMOUS_ENABLED"), "false")
        self.assertEqual(self.environment.get("GF_USERS_ALLOW_SIGN_UP"), "false")

    def test_the_auth_proxy_flow_still_signs_users_in(self):
        self.assertEqual(self.environment.get("GF_AUTH_PROXY_ENABLED"), "true")
        self.assertEqual(
            self.environment.get("GF_AUTH_PROXY_HEADER_NAME"), "Cf-Access-Authenticated-User-Email")
        self.assertEqual(self.environment.get("GF_AUTH_PROXY_AUTO_SIGN_UP"), "true")
        self.assertEqual(self.environment.get("GF_AUTH_PROXY_WHITELIST"), "cloudflaredAddress")
        # Without an administrator to promote them, the users are viewers.
        self.assertEqual(self.environment.get("GF_USERS_AUTO_ASSIGN_ORG_ROLE"), "Viewer")

    def test_the_dashboards_and_datasources_are_still_provisioned(self):
        text = UI.read_text()
        self.assertIn("cp ${./dashboards}/*.json", text)
        self.assertIn("datasources/siem.yaml", text)
        self.assertIn("dashboards/siem.yaml", text)


class GrafanaProvisioningTests(unittest.TestCase):
    """The tree the grafana container mounts at /etc/grafana/provisioning.

    Grafana reads the plugin and the alerting provisioning directories on
    every start and logs an error for each one it cannot find. The tree is
    mounted read-only, so Grafana cannot create them itself: the module
    must build them.
    """

    def setUp(self):
        self.directories, self.files = provisioning_tree()

    def test_the_provisioning_tree_is_the_whole_read_only_tree(self):
        # Everything the container reads under /etc/grafana/provisioning
        # comes from one store path, mounted read-only, so the tree that
        # store path holds is the tree the container sees.
        mounts = [(target, options) for _, target, options in grafana_volumes()
                  if target.startswith("/etc/grafana/provisioning")]
        self.assertEqual(mounts, [("/etc/grafana/provisioning", "ro")])

    def test_the_plugin_and_alerting_directories_exist(self):
        # Grafana logs an error for every provisioning directory it cannot
        # find, so the two it reads must be in the tree.
        for name in ("plugins", "alerting"):
            with self.subTest(directory=name):
                self.assertIn(name, self.directories)

    def test_the_plugin_and_alerting_directories_are_empty(self):
        # They exist so Grafana finds them. A plugin or an alerting
        # configuration in them would be provisioned from the store path,
        # which is not where this fleet keeps either.
        for name in ("plugins", "alerting"):
            with self.subTest(directory=name):
                self.assertIn(name, self.directories)
                self.assertEqual(
                    [path for path in self.files
                     if path == name or path.startswith(name + "/")], [])
                self.assertEqual(
                    [path for path in self.directories if path.startswith(name + "/")], [])


if __name__ == "__main__":
    unittest.main()
