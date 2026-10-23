"""CI runner isolation and root-only registration use the actual Nix module."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CIRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        expression = '''let
          module = import %s {
            config.ghostship.selfHostedSecrets.projections.ghostship-ci-registration.path = "/fixture/registration.env";
            lib.genAttrs = names: f: builtins.listToAttrs (map (name: { inherit name; value = f name; }) names);
            pkgs = (builtins.listToAttrs (map (name: { inherit name; value = "/fixture/" + name; })
              [ "coreutils" "curl" "jq" "openssh" "python3" "unzip" "xz" ])) // {
                writeShellScript = name: text: name + "\\n" + text;
              };
          };
          in module''' % (ROOT / 'modules/self-hosted/github-ci.nix')
        cls.module = json.loads(subprocess.check_output(
            ['nix-instantiate', '--eval', '--strict', '--json', '--expr', expression], text=True))

    def test_ephemeral_repo_bound_runners_preserve_only_private_caches(self):
        runners = self.module['services']['github-runners']
        self.assertEqual(set(runners), {'ghostship-agent', 'ghostship-config', 'ghostship-3dprinting'})
        for repo, runner in runners.items():
            self.assertEqual(runner['url'], 'https://github.com/ghostship-io/' + repo)
            self.assertTrue(runner['ephemeral'])
            self.assertEqual(runner['extraLabels'], ['ghostship-fast'])
            hook = runner['extraEnvironment']['ACTIONS_RUNNER_HOOK_JOB_STARTED']
            self.assertTrue(hook.splitlines()[0].endswith('.sh'), 'the runner only executes a script with a supported suffix')
            self.assertIn('python3 -I -S', hook)
            self.assertIn('github-ci-guard.py', hook)
            self.assertIn('ghostship-io/' + repo, hook)
            self.assertNotIn('user', runner)  # upstream DynamicUser, never root
            self.assertEqual(runner['serviceOverrides']['CacheDirectoryMode'], '0700')
            self.assertEqual(runner['serviceOverrides']['CPUQuota'], '400%' if repo == 'ghostship-3dprinting' else '200%')

    def test_registration_is_after_secret_render_and_never_exported_to_jobs(self):
        activation = self.module['system']['activationScripts']['ghostship-ci-registration']
        self.assertEqual(activation['deps'], ['ghostship-secret-projections'])
        self.assertFalse(activation['supportsDryActivation'])
        self.assertIn('umask 077', activation['text'])
        self.assertIn('chmod 0600', activation['text'])
        for runner in self.module['services']['github-runners'].values():
            self.assertNotIn('GITHUB_TOKEN', runner['extraEnvironment'])
        projection = self.module['ghostship']['secretProjections']['ghostship-ci-registration']
        self.assertEqual(projection['owner'], 'root')
        self.assertEqual(projection['mode'], '0400')
        self.assertEqual(projection['fields']['GITHUB_TOKEN'],
                         {'unit': 'github-runner-registration', 'key': 'TOKEN'})
        # General agent environments must never receive the registration credential.
        expression = """let
          recipients = import %s;
          catalog = import %s { inherit recipients; };
          fields = builtins.concatLists (map (p: builtins.attrValues p.fields)
            (builtins.attrValues catalog.projections));
        in {
          engineering = catalog.projections.t3code.fields.GITHUB_TOKEN;
          runnerExports = catalog.units.github-runner-registration.exports;
          exposed = builtins.filter (f: f.unit == "github-runner-registration") fields;
        }""" % (ROOT / 'secrets/recipients.nix', ROOT / 'secrets/catalog.nix')
        bindings = json.loads(subprocess.check_output(
            ['nix-instantiate', '--eval', '--strict', '--json', '--expr', expression], text=True))
        self.assertEqual(bindings['engineering'], {'unit': 'github', 'key': 'TOKEN'})
        self.assertEqual(bindings['runnerExports'], ['TOKEN'])
        self.assertEqual(bindings['exposed'], [])


if __name__ == '__main__':
    unittest.main()
