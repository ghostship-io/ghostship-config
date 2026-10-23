# Development from the T3 Code container

Work in `/workspace/nixos-config` as the existing `t3code` user. This is a
Linux development container with a Nix daemon, not one of the fleet's NixOS
hosts. T3 Code, Codex, OpenCode, and Antigravity are maintained by the container
environment. Keep their existing launchers, credentials, and configuration.
Do not apply `home/profiles/develop.nix` or run
`ghostship-agent-maintenance` here; those target the NixOS develop hosts.

Git worktrees share `refs/stash`. Preserve uncommitted work with a private
patch or a recorded stash object ID; apply that exact object and verify the
result before any removal. An unqualified `git stash pop` can consume another
worker's entry even from a different worktree. Leave other workers' entries
and worktrees untouched.

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

Pull requests run `nix develop .#ci -c python3 scripts/check-unit.py`, workflow
and shell lint, and the existing redacted Gitleaks source scan. The job has a
four-minute budget. Main pushes retain `scripts/check`, all host evaluations,
configuration builds and the same secret scan. T3 browser integration also
runs after merge on main. Superseded PR runs are cancelled; main runs finish.
Review the exact diff and unit results, record approval, then use `agent pr land`.
Frontier authors self-review; other models need one frontier review.

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
worktree, verify and commit changes, push, and open a PR. Keep `VERSION` and
`CHANGELOG.md` out of its diff: `agent pr land` publishes the release on main.
Write release notes in the PR body under `## Changelog`; patch is the default,
with `Release: minor` or `Release: major` selecting a larger bump.

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
rather than restarting `podman-t3code.service` directly. A forced restart needs the
owner's own deploy or activate instruction, recorded with
`--owner-request "<short quote or reference>"`.

Record the container ID and start time plus the service MainPID before work.
Build first; inspect the candidate unit definitions, activation scripts, and
`switch-to-configuration dry-activate` output before a full switch. A clean
unit diff alone does not prove activation is safe: inspect dependencies and
imperative hooks too. If T3 Code could be interrupted, activate only the exact
new service's Nix-generated unit through root SSH and retain its build as a
GC root. Report the deferred full-system switch. Never stop T3 Code to make a
deployment pass. Verify the recorded identity, start time, and MainPID afterward.

The idle deployment helper protects active sessions itself: its probe reads T3
Code 2's `statev2.sqlite` and defers while a run, subagent or thread launch is
open, a user message is under 15 minutes old, or turn items changed in the last
10 minutes. No session guard is needed before a full switch.

For targeted activation on NixOS, `/etc/systemd/system` is store-backed and
read-only. A unit linked under `/run/systemd/system` also has lower precedence
than its existing `/etc` unit. Use a task-named runtime drop-in containing the
changed directives from the built Nix unit; reset list directives such as
`ExecStart` before appending their generated replacements. Verify the loaded
`ExecStart`/`ExecStartPre` and `DropInPaths` after `daemon-reload`, then restart
only the intended service. Retain the candidate as a GC root. Every full switch
removes runtime drop-ins and shadowed runtime unit links of declared units
(`clear-runtime-unit-overrides`); runtime masks stay.

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

The inference broker and scheduler are separate host units using `podman exec`
into the existing T3 container. Their pinned closures are copied into its Nix
store without replacing the container image or its application runtime. The
broker owns only authenticated Unix HTTP submission and status; the scheduler
owns execution through the same durable runtime store. Restart either unit
independently, waiting for graceful scheduler shutdown before starting its
replacement. The MCP mounts the socket directory so a recreated socket remains
visible. Its dedicated bearer comes from the encrypted source and is separate
from provider keys. Activation refreshes the managed CLI through the pinned
installer with `--managed-only`, preserving provider and global Git settings.
The host also projects the installer at
`~/.local/state/t3code-shared-agents/managed-installer` and updates only the
container sync service's `ExecStart` through a runtime drop-in. Both this command
and future images share the same guarded repository-sync script. Preserve its
30-minute timer and run the actual sync service twice after activation: checking
the CLI immediately after a one-time refresh misses an old image's later writer.
The host recreates the override on activation/container startup. Verify the real
mounted socket and authenticated request path after deployment, then repeat after
a broker restart.

The pool policy lives in `modules/self-hosted/inference-pool.json`, separately
from OpenCode configuration. Deployment seeds only the public synthetic fixture
when absent and preserves an existing fixture and Git history. The policy lists
approved repositories for selected-file reviews with public or private
sensitivity; broker roots derive from that same list. Trusted test commands are
configured per repository; the existing test command belongs to the fixture.

Use `agent deploy run` for merged changes. It preserves busy T3 sessions and
checks activation gates; a deployment that requires an unauthorized restart
waits for idle. Record the owner's explicit request for any authorized exception.

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

After landing the PR, deploy the committed configuration with:

```sh
agent deploy run
```

Use `agent deploy run --agent-rev REV` to pin an agent change first. The command
builds with local firmware support, checks dry-activation and live health, and
records the system generation. Other hosts retain their explicit target and
host-specific procedure. Do not bypass failed gates with a direct switch.
