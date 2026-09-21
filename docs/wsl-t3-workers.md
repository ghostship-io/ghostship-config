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

The `t3worker` role is the only switch. It enables the worker platform and
selects the Home Manager worker profile. Tune it through `ghostship.t3Worker`
when the defaults do not fit:

| Option | Default | Purpose |
| --- | --- | --- |
| `user` | `nixos` | User that owns the server and credentials |
| `baseDir` | `/home/nixos/.t3` | T3 Code data directory |
| `port` | `3774` | Loopback server port |
| `enableAntigravity` | `true` | Install the Antigravity ACP provider |

## Standalone-by-design

A worker is a Windows development box for its own repositories, not a Ghostship
runtime host. Only this repository's tooling is installed:

- No `ghostship-agent` checkout, installer, or tool package. Provider skills
  are limited to the small set under `home/config/skills/`, linked into
  `~/.agents/skills`, `~/.claude/skills`, and `~/.gemini/config/skills`.
- No shared `agent`, `bw`, CloakBrowser, Google Workspace, or Printing Press
  tooling, and no Ghostship secrets projection.
- Provider authentication and the T3 Connect link stay in the worker user's
  home, untouched by declarative configuration.

## What the host runs

- `t3code-worker.service` runs `t3 serve` as the worker user on loopback and
  restarts on failure or reboot.
- `t3code-worker-update.timer` runs every four hours. It compares installed
  T3 and provider versions against the last-seen set and restarts the worker
  only when something changed. The develop-role maintenance timer owns the
  actual install and upgrade.
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

## Verify

```sh
systemctl status t3code-worker.service
systemctl list-timers 't3code-worker-update.timer'
t3 connect status
ls ~/.agents/skills ~/.claude/skills ~/.gemini/config/skills
codex --version && opencode --version
```

Open the normal T3 web interface and select the worker environment. The Docker
T3 Code environment is unaffected; each machine keeps its own state.
