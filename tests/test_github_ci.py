"""CI runner isolation and root-only registration use the actual Nix module."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CIRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        expression = '''let
          module = import %s {
            config.ghostship.selfHostedSecrets.projections.ghostship-ci-registration.path = "/fixture/registration.env";
            config.services.github-runners = builtins.listToAttrs (map (name: {
              inherit name; value.package = "/fixture/runner";
            }) [ "ghostship-agent" "ghostship-agent-2" "ghostship-config" "ghostship-3dprinting" ]);
            lib.genAttrs = names: f: builtins.listToAttrs (map (name: { inherit name; value = f name; }) names);
            lib.mkForce = value: value;
            lib.escapeShellArgs = builtins.concatStringsSep " ";
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
        bindings = {'ghostship-agent': 'ghostship-agent', 'ghostship-agent-2': 'ghostship-agent',
                    'ghostship-config': 'ghostship-config', 'ghostship-3dprinting': 'ghostship-3dprinting'}
        self.assertEqual(set(runners), set(bindings))
        names = set()
        for identifier, runner in runners.items():
            repo = bindings[identifier]
            self.assertEqual(runner['url'], 'https://github.com/ghostship-io/' + repo)
            self.assertNotIn(runner['name'], names)
            names.add(runner['name'])
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
            self.assertEqual(runner['extraEnvironment']['XDG_CACHE_HOME'], '/var/cache/github-ci-' + identifier)
            commands = runner['serviceOverrides']['ExecStartPre']
            for command in commands:
                self.assertIn('--repository ghostship-io/' + repo + ' ', command)
                self.assertIn('--state-dir /var/lib/github-runner/' + identifier + ' ', command)
                self.assertIn('--work-dir /run/github-runner/' + identifier + ' ', command)
                self.assertIn('--logs-dir /var/log/github-runner/' + identifier, command)

    def test_runner_fetch_keeps_history_and_lazily_reads_blobs_without_eager_old_payloads(self):
        settings = self.module['services']['github-runners']['ghostship-config']['extraEnvironment']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {'PATH': os.environ['PATH'], 'HOME': directory,
                           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
                           'GIT_TERMINAL_PROMPT': '0'}
            def git(repository, *args, env=None):
                return subprocess.check_output(['git', '-C', str(repository), *args],
                                               env=env or environment, text=True, stderr=subprocess.PIPE)
            remote, checkout = root / 'remote', root / 'checkout'
            remote.mkdir(); checkout.mkdir()
            git(remote, 'init', '-q', '-b', 'main')
            git(remote, 'config', 'user.name', 'Fixture')
            git(remote, 'config', 'user.email', 'fixture@users.noreply.github.com')
            git(remote, 'config', 'uploadpack.allowFilter', 'true')
            git(remote, 'config', 'uploadpack.allowAnySHA1InWant', 'true')
            (remote / 'old.dat').write_bytes(b'obsolete fixture payload\n' * 16384)
            (remote / 'policy.txt').write_text('previous policy\n')
            git(remote, 'add', '.')
            git(remote, 'commit', '-q', '-m', 'base fixture')
            obsolete = git(remote, 'rev-parse', 'HEAD:old.dat').strip()
            git(remote, 'rm', '-q', 'old.dat')
            (remote / 'policy.txt').write_text('current policy\n')
            git(remote, 'commit', '-q', '-am', 'head fixture')
            git(checkout, 'init', '-q')
            git(checkout, 'remote', 'add', 'origin', remote.as_uri())
            fetch_env = {**environment, **{k: v for k, v in settings.items() if k.startswith('GIT_CONFIG_')}}
            # Same full-history fetch as checkout; the runner supplies the filter.
            git(checkout, '-c', 'protocol.version=2', 'fetch', '-q', 'origin',
                '+refs/heads/*:refs/remotes/origin/*', env=fetch_env)
            objects = git(checkout, 'cat-file', '--batch-all-objects', '--batch-check=%(objectname)',
                          env=fetch_env).splitlines()
            self.assertNotIn(obsolete, objects)
            git(checkout, 'checkout', '-q', '--detach', 'refs/remotes/origin/main', env=fetch_env)
            self.assertEqual((checkout / 'policy.txt').read_text(), 'current policy\n')
            self.assertEqual(git(checkout, 'show', 'HEAD^:policy.txt', env=fetch_env), 'previous policy\n')
            self.assertEqual(git(checkout, 'rev-list', '--count', 'HEAD', env=fetch_env).strip(), '2')

    def test_registration_is_after_secret_render_and_never_exported_to_jobs(self):
        activation = self.module['system']['activationScripts']['ghostship-ci-registration']
        self.assertEqual(activation['deps'], ['ghostship-secret-projections'])
        self.assertFalse(activation['supportsDryActivation'])
        self.assertIn('umask 077', activation['text'])
        self.assertIn('chmod 0600', activation['text'])
        for runner in self.module['services']['github-runners'].values():
            self.assertNotIn('GITHUB_TOKEN', runner['extraEnvironment'])
            commands = runner['serviceOverrides']['ExecStartPre']
            self.assertEqual(len(commands), 2)
            self.assertTrue(commands[0].startswith('+'))
            self.assertFalse(commands[1].startswith('+'))
            self.assertIn('--op prepare', commands[0])
            self.assertIn('--op configure', commands[1])
            self.assertIn('github-ci-register.py', commands[0])
            self.assertNotIn('--pat ', commands[0])
            self.assertEqual(runner['serviceOverrides']['InaccessiblePaths'],
                             ['-/run/ghostship-ci/registration-token'])
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
