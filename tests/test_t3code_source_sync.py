"""Exercise the recurring sync path with actual local Git repositories."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'packages/t3code/source-sync.sh'


class SourceSync(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home),
                    'XDG_STATE_HOME': str(self.home / '.local/state'),
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}
        self.env.pop('T3CODE_HOOK_SET', None)
        self.remotes = {}
        self.repos = {}
        for name in ('ghostship-agent', 'nixos-config'):
            remote = self.root / (name + '.git')
            self.git('init', '--bare', '--initial-branch=main', str(remote))
            repo = self.workspace / name
            self.git('clone', str(remote), str(repo))
            self.git('-C', str(repo), 'config', 'user.name', 'Fixture')
            self.git('-C', str(repo), 'config', 'user.email', 'fixture@localhost')
            (repo / 'flake.nix').write_text('{}\n')
            self.commit(repo, 'initial')
            self.git('-C', str(repo), 'push', 'origin', 'main')
            self.remotes[name] = remote
            self.repos[name] = repo
        self.fallback = self.root / 'old-installer'
        self.fallback.write_text('#!/bin/sh\nprintf old >> "$HOME/owners"\n')
        self.fallback.chmod(0o755)
        self.managed = self.root / 'new-installer'
        self.managed.write_text('#!/bin/sh\nprintf "new:%s\\n" "$*" >> "$HOME/owners"\n')
        self.managed.chmod(0o755)
        self.anchor = self.home / '.local/state/t3code-shared-agents/managed-installer'
        self.anchor.parent.mkdir(parents=True)
        self.anchor.symlink_to(self.managed)

    def git(self, *args):
        return subprocess.check_output(['git', *args], env=self.env,
                                       stderr=subprocess.DEVNULL, text=True).strip()

    def commit(self, repo, message):
        self.git('-C', str(repo), 'add', '.')
        self.git('-C', str(repo), 'commit', '-m', message)
        return self.git('-C', str(repo), 'rev-parse', 'HEAD')

    def remote_change(self, name):
        other = self.root / (name + '-upstream')
        self.git('clone', str(self.remotes[name]), str(other))
        self.git('-C', str(other), 'config', 'user.name', 'Fixture')
        self.git('-C', str(other), 'config', 'user.email', 'fixture@localhost')
        (other / 'new-file').write_text('upstream\n')
        revision = self.commit(other, 'upstream')
        self.git('-C', str(other), 'push', 'origin', 'main')
        return revision

    def sync(self, *args, hook=None):
        env = dict(self.env)
        if hook:
            env['T3CODE_HOOK_SET'] = hook
        subprocess.run(['bash', str(SCRIPT), str(self.workspace), str(self.fallback), *args],
                       env=env, check=True, capture_output=True, text=True, timeout=15)

    def test_clean_main_fast_forwards_and_repeated_sync_uses_projected_owner(self):
        revisions = {name: self.remote_change(name) for name in self.repos}
        self.sync('--skills-only')
        self.sync('--skills-only')
        for name, repo in self.repos.items():
            self.assertEqual(self.git('-C', str(repo), 'rev-parse', 'HEAD'), revisions[name])
        self.assertEqual((self.home / 'owners').read_text(), 'new:--skills-only\n' * 2)
        self.assertEqual(self.anchor.resolve(), self.managed)

    def test_monotonic_resolver_wins_over_an_older_host_installer(self):
        canonical = self.home/'.local/bin/t3code-shared-agents'
        canonical.parent.mkdir(parents=True)
        canonical.write_text('#!/bin/sh\nprintf resolver >> "$HOME/owners"\n')
        canonical.chmod(0o755)
        (self.anchor.parent/'release.json').write_text('{}')
        self.anchor.unlink()
        self.anchor.symlink_to(self.fallback)
        self.sync(hook='bootstrap.d')
        self.assertEqual((self.home/'owners').read_text(), 'resolver')

    def test_dirty_and_off_main_repositories_stay_unchanged(self):
        before = {name: self.git('-C', str(repo), 'rev-parse', 'HEAD')
                  for name, repo in self.repos.items()}
        for name in self.repos:
            self.remote_change(name)
        (self.repos['ghostship-agent'] / 'flake.nix').write_text('owner edit\n')
        self.git('-C', str(self.repos['nixos-config']), 'switch', '-c', 'owner-work')
        self.sync()
        for name, repo in self.repos.items():
            self.assertEqual(self.git('-C', str(repo), 'rev-parse', 'HEAD'), before[name])
        self.assertEqual((self.repos['ghostship-agent'] / 'flake.nix').read_text(), 'owner edit\n')
        self.assertEqual((self.home / 'owners').read_text(), 'new:\n')

    def test_bootstrap_skips_fetch_and_absent_projection_uses_fallback(self):
        repo = self.repos['ghostship-agent']
        before = self.git('-C', str(repo), 'rev-parse', 'HEAD')
        self.remote_change('ghostship-agent')
        self.anchor.unlink()
        self.sync(hook='bootstrap.d')
        self.assertEqual(self.git('-C', str(repo), 'rev-parse', 'HEAD'), before)
        self.assertEqual((self.home / 'owners').read_text(), 'old')


if __name__ == '__main__':
    unittest.main()
