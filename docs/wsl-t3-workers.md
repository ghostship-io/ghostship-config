# WSL2 T3 Code workers

A NixOS-WSL2 desktop can join the existing T3 web interface as its own
environment instead of running work through the Docker T3 Code server. Each
worker owns its projects, threads, providers, files, and execution.

## Enable a host

Import the shared modules and set the role in the host configuration:

```nix
{
  imports = [
    ../../modules/common/default.nix
    ../../modules/develop/default.nix
    ../../modules/wsl/default.nix
  ];

  ghostship.host.roles = {
    develop = true;
    wsl = true;
    t3worker = true;
  };
}
```

The `t3worker` role is the only switch. It enables the worker platform, links
the shared skill catalog, and selects the Home Manager worker profile. Tune it
through `ghostship.t3Worker` when the defaults do not fit:

| Option | Default | Purpose |
| --- | --- | --- |
| `user` | `nixos` | User that owns the server and credentials |
| `baseDir` | `/home/nixos/.t3` | T3 Code data directory |
| `port` | `3774` | Loopback server port |
| `sharedAgentSource` | `/home/nixos/.local/share/ghostship-agent` | Managed catalog checkout |
| `sharedAgentRepo` | `git@github.com:ghostship-io/ghostship-agent.git` | Catalog remote |
| `sharedAgentRef` | `main` | Catalog branch |
| `enableAntigravity` | `true` | Install the Antigravity ACP provider |

## What the host runs

- `t3code-worker.service` runs `t3 serve` as the worker user on loopback and
  restarts on failure or reboot. `users.users.nixos.linger = true` keeps it
  running without an open login session.
- `t3code-worker-update.timer` runs every four hours. It triggers the existing
  `ghostship-agent-maintenance.service`, which installs or upgrades T3, Codex,
  OpenCode, Claude, Cursor, Gemini, Grok, and the shared `skills` CLI, then
  restarts the worker only when an installed version changed.
- `ghostship-agent-sync.timer` runs every six hours. It updates the managed
  `ghostship-agent` checkout and runs that repository's
  `tools/setup-container-agents.py --skills-only --no-guidance`, so the worker
  links the same skills into `~/.agents/skills`, `~/.claude/skills`, and
  `~/.gemini/config/skills` as the Docker T3 Code container.
- Provider CLIs are seeded into `~/.t3/userdata/settings.json` only when that
  file does not exist yet. Later user changes are preserved.

T3 discovers providers on the service `PATH`, so the develop-role wrappers for
Codex, OpenCode, Claude, Cursor, and Gemini are visible without extra
configuration. Antigravity uses its packaged ACP executable directly.

## One-time interactive setup

These steps are user-owned and stay outside the declarative configuration.

1. Authenticate each provider on the worker, for example `codex login`,
   `opencode auth login`, `claude`, `cursor`, or `grok login`. Credentials stay
   in the worker user's home.
2. Link the environment to T3 Connect:

   ```sh
   t3 connect login --headless
   t3 connect link --headless
   sudo systemctl restart t3code-worker.service
   ```

   The CLI prints a browser link and a short code; approve it on any device.
   Link state persists under `~/.t3` and reconnects after reboot, WSL restart,
   or a network interruption.
3. Authorize the worker's SSH key as a deploy key or collaborator on the
   private `ghostship-agent` repository if the six-hour skill sync reports a
   clone or fetch failure.

## Verify

```sh
systemctl status t3code-worker.service
systemctl list-timers 't3code-worker-update.timer' 'ghostship-agent-sync.timer'
t3 connect status
ls ~/.agents/skills ~/.claude/skills ~/.gemini/config/skills
codex --version && opencode --version
```

Open the normal T3 web interface and select the worker environment. The Docker
T3 Code environment is unaffected; each machine keeps its own state.
