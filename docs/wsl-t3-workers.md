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
| `user` | `nixos` | Fixed owner shared with the managed CLI installer |
| `baseDir` | `/home/nixos/.t3` | T3 Code data directory |
| `port` | `3774` | Loopback server port |
| `enableAntigravity` | `true` | Install the Antigravity ACP provider |
| `directTunnel.enable` | `false` | Publish the worker through its own Cloudflare tunnel |
| `directTunnel.hostname` | empty | Stable HTTPS backend hostname |
| `directTunnel.tokenFile` | `~/.t3/cloudflare-tunnel-token` | Persistent connector credential |

## Standalone-by-design

A worker is a Windows development box for its own repositories, not a Ghostship
runtime host. Only this repository's tooling is installed:

- No `ghostship-agent` checkout, installer, or tool package. Provider skills
  are limited to the small set under `home/config/skills/`, linked into
  `~/.agents/skills`, `~/.claude/skills`, and `~/.gemini/config/skills`.
- No shared `agent`, `bw`, CloakBrowser, Google Workspace, or Printing Press
  tooling, and no Ghostship secrets projection.
- Provider authentication and the Cloudflare connector credential stay in the
  worker user's home, untouched by the Nix store.

## What the host runs

- `t3code-worker.service` runs `t3 serve` as the worker user on loopback and
  restarts on failure or reboot. The worker is never exposed directly to the
  LAN.
- `t3code-worker-cloudflare.service` maintains a dedicated outbound named
  tunnel to the loopback server. It does not use T3 Connect.
- `t3code-worker-health.timer` checks the local HTTP server and public tunnel
  every two minutes. It starts stopped units immediately, restarts a wedged
  worker only after three failures and an idle check, and repairs the tunnel
  independently without interrupting agent work.
- Both services are wanted by `multi-user.target`, so they start automatically
  whenever the NixOS WSL distribution starts. No Windows scheduled task or
  Windows-side watchdog is installed.
- `t3code-worker-update.timer` runs every four hours. It compares installed
  T3 and provider versions against the last-seen set and queues a worker
  restart only when something changed. The health timer applies that restart
  after two consecutive idle checks, never during active or unknown work. The
  develop-role maintenance timer owns the actual install and upgrade.
- Provider CLIs are seeded into `~/.t3/userdata/settings.json` only when that
  file does not exist yet. Later user changes are preserved.

T3 discovers providers on the service `PATH`, so the develop-role wrappers for
Codex, OpenCode, Claude, Cursor, and Gemini are visible without extra
configuration. Antigravity uses its packaged ACP executable directly.

## One-time direct-tunnel setup

The connector token is intentionally runtime state rather than a Nix value.
Provision the dedicated tunnel with the Cloudflare management projection on
`chill-penguin`, then install the resulting private file on the worker:

```sh
set -a
. /run/ghostship-secrets/cloudflare-management.env
set +a
python modules/agent-worker/cloudflare-tunnel.py \
  --name t3-worker-armored-armadillo \
  --hostname armored-armadillo-t3.ghostship.io \
  --port 3774 \
  --token-file /tmp/armored-armadillo-t3.token
```

Copy the token over an authenticated SSH connection, make it owned by the
worker user with mode `0600`, and remove the staging copy. Re-running the
provisioner reconciles the same tunnel, DNS record, ingress, Access coverage,
and token without creating duplicates.

Provider setup remains user-owned:

1. Authenticate each provider on the worker, for example `codex login`,
   `opencode auth login`, `claude`, `cursor`, or `grok login`. Credentials stay
   in the worker user's home.
2. Ensure T3 Connect is disabled, then create a direct pairing link:

   ```sh
   t3 connect unlink --base-dir ~/.t3
   t3 auth pairing create --base-dir ~/.t3 --ttl 1h \
     --base-url https://armored-armadillo-t3.ghostship.io \
     --label "armored-armadillo direct"
   ```

   In `https://t3code.ghostship.io/settings/connections`, choose **Add
   environment**, paste the worker hostname and one-time pairing code, and add
   it. The authorized client credential is retained by that browser; the
   Cloudflare hostname and tunnel remain stable across Windows and WSL restarts.

## Verify

```sh
systemctl status t3code-worker.service
systemctl status t3code-worker-cloudflare.service
systemctl list-timers 't3code-worker-*.timer'
curl -I https://armored-armadillo-t3.ghostship.io/
ls ~/.agents/skills ~/.claude/skills ~/.gemini/config/skills
codex --version && opencode --version
```

Open the normal T3 web interface and select the saved worker environment. The
Docker T3 Code environment is still the main interface and is unaffected; each
machine keeps its own projects, threads, and provider state.
