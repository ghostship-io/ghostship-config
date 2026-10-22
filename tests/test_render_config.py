import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
RENDER = ROOT / "modules/self-hosted/render-config.py"
SPEC = importlib.util.spec_from_file_location("check_privacy", ROOT / "scripts/check-privacy.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
RENDER_SPEC = importlib.util.spec_from_file_location("render_config", RENDER)
RENDERER = importlib.util.module_from_spec(RENDER_SPEC)
RENDER_SPEC.loader.exec_module(RENDERER)


# The specimen is assembled rather than written out, so this file carries no
# literal that the published tree check would report.
SPECIMEN_ACCOUNT = "0" * 32


class RenderConfigTest(unittest.TestCase):
    def render(self, template, env, target, mode="0600", owner=""):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            template_path = base / "template.json"
            env_path = base / "secrets.env"
            template_path.write_text(json.dumps(template))
            env_path.write_text(env)
            arguments = [sys.executable, str(RENDER), str(template_path), str(env_path),
                         str(target)]
            if mode:
                arguments += ["--mode", mode]
            if owner:
                arguments += ["--owner", owner]
            result = subprocess.run(arguments, capture_output=True, text=True)
            return result

    def published(self, directory, template, env, mode="0600", owner=""):
        base = pathlib.Path(directory)
        target = base / "config.json"
        result = self.render(template, env, target, mode, owner)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(target.read_text())

    def test_string_placeholder_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            rendered = self.published(
                directory,
                {"expected_email": "{{PERSONAL_ACCOUNT_EMAIL}}"},
                "PERSONAL_ACCOUNT_EMAIL=owner@example.invalid\n",
            )
            self.assertEqual(rendered["expected_email"], "owner@example.invalid")

    def test_embedded_placeholder_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            rendered = self.published(
                directory,
                {"base_url": "https://api.example.com/accounts/{{CF_ACCOUNT_ID}}/ai/v1"},
                "CF_ACCOUNT_ID=" + SPECIMEN_ACCOUNT + "\n",
            )
            self.assertEqual(
                rendered["base_url"],
                "https://api.example.com/accounts/" + SPECIMEN_ACCOUNT + "/ai/v1",
            )

    def test_json_placeholder_injects_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            rendered = self.published(
                directory,
                {"allowed_user_ids": "{{GITHUB_ALLOWED_USER_IDS:json}}"},
                "GITHUB_ALLOWED_USER_IDS=[4242]\n",
            )
            self.assertEqual(rendered["allowed_user_ids"], [4242])

    def test_json_placeholder_injects_object(self):
        with tempfile.TemporaryDirectory() as directory:
            rendered = self.published(
                directory,
                {"repositories": "{{T3_REPOSITORIES:json}}"},
                'T3_REPOSITORIES={"example/project":{"project_id":"identifier"}}\n',
            )
            self.assertEqual(
                rendered["repositories"],
                {"example/project": {"project_id": "identifier"}},
            )

    def test_quoted_value_is_unquoted(self):
        with tempfile.TemporaryDirectory() as directory:
            rendered = self.published(
                directory, {"name": "{{OPERATOR}}"}, "OPERATOR='operator account'\n")
            self.assertEqual(rendered["name"], "operator account")

    def test_missing_value_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            target = base / "config.json"
            result = self.render(
                {"expected_email": "{{PERSONAL_ACCOUNT_EMAIL}}"}, "OTHER=value\n", target)
            self.assertEqual(result.returncode, 1)
            self.assertIn("PERSONAL_ACCOUNT_EMAIL", result.stderr)
            self.assertFalse(target.exists())

    def test_unresolved_placeholder_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            target = base / "config.json"
            result = self.render(
                {"a": "{{KNOWN}}", "b": "{{OTHER}}"}, "KNOWN=value\n", target)
            self.assertEqual(result.returncode, 1)
            self.assertIn("OTHER", result.stderr)

    # --- publication boundaries -------------------------------------------

    def test_a_symbolic_link_target_is_replaced_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            victim = base / "victim.txt"
            victim.write_text("original\n")
            target = base / "config.json"
            target.symlink_to(victim)
            result = self.render({"a": "{{X}}"}, "X=value\n", target)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(victim.read_text(), "original\n")
            self.assertFalse(target.is_symlink())
            self.assertEqual(json.loads(target.read_text()), {"a": "value"})

    def test_a_pre_created_predictable_path_is_not_used(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            victim = base / "victim.txt"
            victim.write_text("original\n")
            decoy = base / "config.json.new"
            decoy.symlink_to(victim)
            target = base / "config.json"
            result = self.render({"a": "{{X}}"}, "X=value\n", target)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(victim.read_text(), "original\n")
            self.assertEqual(json.loads(target.read_text()), {"a": "value"})

    def test_a_group_writable_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            base.chmod(0o775)
            try:
                result = self.render({"a": "{{X}}"}, "X=value\n", base / "config.json")
                self.assertEqual(result.returncode, 1)
                self.assertIn("writable", result.stderr)
            finally:
                base.chmod(0o700)

    def test_a_world_writable_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            base.chmod(0o777)
            try:
                result = self.render({"a": "{{X}}"}, "X=value\n", base / "config.json")
                self.assertEqual(result.returncode, 1)
                self.assertIn("writable", result.stderr)
            finally:
                base.chmod(0o700)

    def test_a_symbolic_link_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            real = base / "real"
            real.mkdir()
            link = base / "link"
            link.symlink_to(real)
            result = self.render({"a": "{{X}}"}, "X=value\n", link / "config.json")
            self.assertEqual(result.returncode, 1)
            self.assertIn("symbolic link", result.stderr)

    def test_the_final_mode_is_applied_at_publication(self):
        # Broker/hostops use numeric --owner and 0640; the inference account
        # must receive a read-only file through the same CLI.
        for mode in ("0640", "0440"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                target = pathlib.Path(directory) / "config.json"
                result = self.render({"a": "{{X}}"}, "X=value\n", target, mode=mode,
                                     owner=f"{os.geteuid()}:{os.getegid()}")
                self.assertEqual(result.returncode, 0, result.stderr)
                info = target.stat()
                self.assertEqual(info.st_mode & 0o777, int(mode, 8))
                self.assertEqual((info.st_uid, info.st_gid), (os.geteuid(), os.getegid()))
                self.assertEqual(json.loads(target.read_text()), {"a": "value"})

    def test_no_temporary_file_is_left_behind(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            self.render({"a": "{{X}}"}, "X=value\n", base / "config.json")
            self.assertEqual(sorted(p.name for p in base.iterdir()), ["config.json"])


class PublicationTrustTest(unittest.TestCase):
    """A privileged writer must not follow an account's directory changes."""

    def test_untrusted_ownership_and_ancestors_are_refused(self):
        for kind in ("owner", "ancestor-symlink", "ancestor-writable", "parent-traversal"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                base = pathlib.Path(directory)
                parent = base / "parent"
                parent.mkdir()
                leaf = parent / "leaf"
                leaf.mkdir()
                target = leaf / "config.json"
                if kind == "ancestor-symlink":
                    alias = base / "alias"
                    alias.symlink_to(parent)
                    target = alias / "leaf" / "config.json"
                elif kind == "ancestor-writable":
                    parent.chmod(0o777)
                elif kind == "parent-traversal":
                    target = parent / ".." / "parent" / "leaf" / "config.json"
                # Fake only the process identity; directory ownership and all
                # filesystem operations remain real. No host privilege is used.
                identity = os.geteuid() + 1 if kind == "owner" else os.geteuid()
                with mock.patch.object(os, "geteuid", return_value=identity):
                    with self.assertRaises((ValueError, OSError)):
                        RENDERER.publish(target, "synthetic", 0o640, "")
                self.assertFalse((leaf / "config.json").exists())

    def test_directory_replacement_cannot_redirect_metadata_or_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            publication = base / "publication"
            publication.mkdir()
            saved = base / "saved"
            attacker = base / "attacker"
            attacker.mkdir()
            victim = attacker / "victim"
            victim.write_text("original")
            victim.chmod(0o644)
            before = victim.stat()
            real_fsync = os.fsync
            replaced = False

            def replace_directory(descriptor):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    temporary, = publication.iterdir()
                    (attacker / temporary.name).symlink_to(victim)
                    publication.rename(saved)
                    publication.symlink_to(attacker)
                return real_fsync(descriptor)

            with mock.patch.object(os, "fsync", side_effect=replace_directory):
                RENDERER.publish(publication / "config.json", "synthetic", 0o640,
                                 f"{os.geteuid()}:{os.getegid()}")
            self.assertTrue(replaced)
            after = victim.stat()
            self.assertEqual((after.st_mode, after.st_uid, after.st_gid),
                             (before.st_mode, before.st_uid, before.st_gid))
            self.assertEqual(victim.read_text(), "original")
            result = saved / "config.json"
            self.assertFalse(result.is_symlink())
            self.assertEqual(result.read_text(), "synthetic")
            self.assertEqual(result.stat().st_mode & 0o777, 0o640)
            self.assertEqual((result.stat().st_uid, result.stat().st_gid),
                             (os.geteuid(), os.getegid()))
            self.assertFalse((attacker / "config.json").exists())


if __name__ == '__main__':
    unittest.main()
