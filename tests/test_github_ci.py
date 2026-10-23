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
            pkgs = builtins.listToAttrs (map (name: { inherit name; value = "/fixture/" + name; })
              [ "coreutils" "curl" "jq" "openssh" "python3" "unzip" "xz" ]);
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


if __name__ == '__main__':
    unittest.main()
