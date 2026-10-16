# Development from the T3 Code container

Work in `/workspace/nixos-config` as the existing `t3code` user. This is a
Linux development container with a Nix daemon, not one of the fleet's NixOS
hosts. T3 Code, Codex, OpenCode, and Antigravity are maintained by the container
environment. Keep their existing launchers, credentials, and configuration.
Do not apply `home/profiles/develop.nix` or run
`ghostship-agent-maintenance` here; those target the NixOS develop hosts.

## Runtime memory containment

The inner `t3code-server.service` shares a memory cgroup with provider tools.
The [memory budget and containment policy](t3code.md#memory-budget) prioritizes
the server: 32/40 GiB reclaim/hard limits, kernel OOM protection for its launcher
and native server, and tool containment instead of memory-driven restarts.

## Shared skills and tools

Install the existing Ghostship catalog for all three T3 Code providers:

```sh
python3 scripts/setup-container-agents.py
```

This builds `/workspace/ghostship-agent#default` with that repo's lock file,
keeps persistent Nix GC roots for the tools and native Chromium, and exposes
104 packaged commands through
`~/.local/bin`, already inherited by T3 Code and its providers. The package
includes `agent`, browser and Bitwarden tooling, Google Workspace tooling,
Printing Press, generated API clients, and shared Git tooling. Tool launchers
clear the provider-specific `LD_LIBRARY_PATH` so each Nix package uses its own
libraries. `agent-browser` defaults to the packaged Chromium because Chrome
for Testing does not ship a Linux ARM64 build. Explicit browser overrides are
preserved.

Codex/ChatGPT and OpenCode discover the same shared skills under
`~/.agents/skills`; Antigravity ACP reads links to them under
`~/.gemini/config/skills`. Missing optional Antigravity `name` metadata is
supplied in an installed copy for Codex/OpenCode compatibility. Supporting
resources and the original source remain intact. Shared preferences and the
container path guidance are also published to the providers' native user
instruction files. The setup command delegates to
`ghostship-agent/tools/setup-container-agents.py`; that repo owns the shared
instructions at `config/agents/AGENTS.md` and publishes them through
`~/.agents/AGENTS.md`. Change delivery defaults there, then run
`t3code-shared-agents --skills-only` to activate them.

Selected upstream skills installed in `~/.agents/skills` are shared with
Antigravity on refresh too. The current selection is recorded in the
[installed skill inventory](agent-skills-inventory.md).

The installer preserves unrelated skills and refuses to replace unmanaged
commands or instruction files. It records its links so later runs can update
or prune only its own entries. Provider credentials, model choices, plugin
settings, and Codex's built-in skills are left in place. Provider-specific
plugins and hosted connectors remain provider-specific; sharing filesystem
skills does not transfer those plugins or their authentication to another CLI.

Run `t3code-shared-agents` to rebuild and refresh the package, or
`t3code-shared-agents --skills-only` to refresh discovery without a build. The
installer persists this helper and a T3 Code bootstrap hook in the user home,
so refreshes survive removal of the development worktree. The Nix-managed
container bootstrap also refreshes skills on subsequent deployments.

Check discovery with `opencode debug skill` and Codex app-server `skills/list`.
Start a fresh provider session to reload cached skill catalogs. Antigravity's
ACP skill paths were also verified against the bundled 1.1.1 server source.
See the [Codex skill documentation](https://learn.chatgpt.com/docs/build-skills),
[OpenCode skill documentation](https://opencode.ai/docs/skills/), and
[Antigravity skill documentation](https://antigravity.google/docs/skills).

## Project tools and validation

Use the repository's pinned tools from any agent terminal:

```sh
cd /workspace/nixos-config
nix develop -c scripts/check
```

The default shell supplies Git, GitHub CLI, SSH, Nix, formatting and shell
validation tools, Node.js, Python, Ragenix, Age, and SSH-to-Age. It inherits
the container's agent launchers and authentication environment. It does not
require a login shell, Home Manager, Windows paths, or local root access.

For automatic shell activation, copy `.envrc.example` to `.envrc` if no local
file exists, then run `direnv allow`. `.envrc` stays ignored so existing local
environment settings and secrets are preserved. Non-interactive agent commands
can always use `nix develop -c` without direnv shell integration.

Use `nix develop .#browser` when a test needs local Playwright browser binaries
and `PLAYWRIGHT_BROWSERS_PATH`. Ordinary Nix work does not download those
browsers. The browser shell inherits the default tools. Browser tests still
need the relevant project's JavaScript dependencies and any site credentials.

`scripts/check` parses all tracked Nix files, runs ShellCheck on the workflow
script, checks patch whitespace, and evaluates ci/default/browser shells for
`x86_64-linux` and `aarch64-linux` plus every host's full system derivation.
It uses the checked-in lock file without updating it. Stage new Nix files
before running checks. These checks validate module assertions and derivation
construction; target-host builds and live verification remain necessary for
deployment.

GitHub Actions runs this same command for PRs and pushes to `main`. A single
Linux job evaluates both architectures without building their systems, and
new pushes cancel superseded runs. Review CI and any Codex review comments
before marking a draft PR ready. Leave merging to the user.

## Git access

The container may provide GitHub token authentication without an SSH key.
Check access with `gh auth status`. For this checkout, HTTPS can use that
authentication without storing the token in the repository or changing global
Git configuration:

```sh
git remote set-url origin https://github.com/ghostship-io/ghostship-config.git
git config --local credential.https://github.com.helper '!gh auth git-credential'
git ls-remote origin HEAD
```

Keep an existing SSH remote if its key is available. Use a named branch or
worktree, verify and commit changes, push, and open a draft PR. The repo's
`VERSION` and `CHANGELOG.md` track workflow changes as patch releases.

## Remote deployment

### Preserve the active T3 Code session

Every deployment from T3 Code must keep `podman-t3code.service`, the `t3code`
container, and its inner application runtime running. Restarting any of them
terminates the agent session. This restriction also covers Podman auto-update,
dependency restarts, host reboot, and container bootstrap/activation helpers.

Host configuration changes and image updates decouple deployment from container
interruption. `podman-t3code.service` does not restart on configuration switch.
Instead, image updates and restarts are queued and applied by
`t3code-deploy-when-idle` only after confirming sustained idle across active turns
and pending tasks. If a manual host restart is required, use `t3code-safe-restart`
rather than restarting `podman-t3code.service` directly.

Record the container ID and start time plus the service MainPID before work.
Build first; inspect the candidate unit definitions, activation scripts, and
`switch-to-configuration dry-activate` output before a full switch. A clean
unit diff alone does not prove activation is safe: inspect dependencies and
imperative hooks too. If T3 Code could be interrupted, activate only the exact
new service's Nix-generated unit through root SSH and retain its build as a
GC root. Report the deferred full-system switch. Never stop T3 Code to make a
deployment pass. Verify the recorded identity, start time, and MainPID afterward.

For targeted activation on NixOS, `/etc/systemd/system` is store-backed and
read-only. A unit linked under `/run/systemd/system` also has lower precedence
than its existing `/etc` unit. Use a task-named runtime drop-in containing the
changed directives from the built Nix unit; reset list directives such as
`ExecStart` before appending their generated replacements. Verify the loaded
`ExecStart`/`ExecStartPre` and `DropInPaths` after `daemon-reload`, then restart
only the intended service. Retain the candidate as a GC root. Remove the runtime
drop-in during the later full switch so it cannot mask newer generated commands.

For targeted secret updates, build and retain the committed Nix renderer and
encrypted sources, decrypt only the intended units, and render only their consumer
projection. Atomic replacement of `/run/ghostship-secrets/t3code.env` leaves the
running container's `/run/secrets/t3code.env` bound to its previous inode. Compare
the actual mounted content; refreshing the host path alone is insufficient.

Refresh that inode from a disposable private clone of the container's mount
namespace. Open its root directory before `setns`, use that descriptor to `chroot`,
then `unshare` the mount namespace and make propagation private. Remount only the
clone's existing secret bind writable, write the verified projection, restore
read-only protection, and exit the clone. Creating a new bind of the old unlinked
inode fails. Verify credential equality in process, preservation of existing
credential bytes, the real container's read-only mount, and unchanged T3 identity
and PIDs. New commands can source `/run/secrets/t3code.env`; existing process
environments retain their previous values.

An explicit later instruction scheduling a T3 Code restart is required to
override this guard; ordinary authorization to deploy is insufficient.

The container hostname identifies the coding environment. Always select the
target explicitly instead of using `.#$(hostname)` here. Host configuration
can be evaluated without root:

```sh
nix develop -c nix eval --raw \
  .#nixosConfigurations.chill-penguin.config.system.build.toplevel.drvPath
```

Provision the target's approved SSH identity and verified host key through the
container's persistent credential setup before deploying. The `chill-penguin`
SSH alias must select root on the real host. GitHub token access alone does
not provide host SSH access. Check it non-interactively:

```sh
ssh -o BatchMode=yes -o ConnectTimeout=10 chill-penguin id -u
```

The result must be `0`. If SSH access or Git push is unavailable, fix that
access before deployment. Do not substitute container-local activation or copy
uncommitted files onto the host.

After the user merges the PR, make sure the intended commit is on
`origin/main`. For an authorized deployment, use `ssh chill-penguin` and the
host checkout at `/home/nixos/nixos-config` to run these commands as root:

```sh
git -C /home/nixos/nixos-config pull --ff-only origin main
cd /home/nixos/nixos-config
nixos-rebuild build -L --impure --flake .#chill-penguin
./result/bin/switch-to-configuration switch
```

Run long or prompt-driven remote work in detached tmux, then inspect its output
with `capture-pane` and provide input with `send-keys`. The `--impure` flag on
Chill Penguin allows extraction from its local `/boot/asahi` firmware; the
container's pure evaluation cannot validate that hardware-specific step.
Verify affected live services after switching. Other hosts use their own
explicit flake target, root SSH access, and host-specific deployment procedure.
