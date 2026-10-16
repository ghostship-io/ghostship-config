# T3 Code

T3 Code runs at `https://t3code.ghostship.io` on `chill-penguin`. The repo builds
`localhost/ghostship-t3code:t3code-runtime` with a systemd platform: UID/GID
3000, persistent user services, nested Docker, Nix, build tools, Git/GitHub
CLI, and Cloudflared Quick Tunnels. The access gateway
listens on `t3code:3773` inside `ghostship_net`; the T3 backend listens only on
container loopback port `3774`. No host ports are published.

## Projects and state

The container user is `t3code`, with home `/home/t3code`. Host state lives in
`/srv/apps/t3code/{home,workspace,docker,nix-root}`. At container startup each missing top-level repository is copied to the new
workspace, including Git history and uncommitted files. Copies use filesystem
reflinks when available and publish only after copying completes. Existing
destinations are never overwritten or synchronized. Project registration uses
T3's native CLI.

The initial project set is `ghostship-agent`, `ghostship-newsletter`,
`ghostship-roms`, `nixos-config`, and `OneConfig`. Stop editing a source project
while its initial copy runs if you need a consistent multi-file snapshot.
Git `result` links and build caches can refer to the source container's store;
rebuild them through each project's Nix flake in T3's independent store.

Provider sessions and credentials are separate from these project copies. Project-owned services can be installed in
`~/.config/systemd/user` and enabled with `t3code-user-units enable-now <unit>`.
Do not enable duplicate newsletter delivery or other external automations unless
you intend both containers to run them.

## Ghostship agent installation and hooks

`t3code-install-ghostship-agent` uses the shared catalog installer to build
`/workspace/ghostship-agent#default` with the project's pinned dependencies and
install its tools, shared skills, provider guidance, and native Chromium wrapper.
It uses the local checkout, including local edits; it does not pull or reset the
project. Provider settings and plugins remain under their existing owners.

The container re-creates its `40-ghostship-agent-install` hook in each of
`bootstrap.d`, `before-t3code.d`, `doctor.d`, and `after-update.d`. Other executable
hooks in `~/.t3code-container/hooks/` are preserved and run in filename order as
the `t3code` user. `before-t3code.d` runs on every server start, including restarts
after tool updates. Hook failures are logged and do not prevent web access.
Custom projects can install their own executable hooks in these directories.

The home, hook files, tool wrappers, and independent Nix store persist across
container replacement. Installation serializes concurrent calls; the shared
installer maintains persistent GC roots and records the links it owns. It
preserves unrelated files and refuses to overwrite unmanaged commands.

From a T3 terminal:

```sh
t3code-install-ghostship-agent
t3code-run-hooks doctor.d
agent --help
bw --version
agent-browser --version
```

## Browser access and provider sign-in

Open `https://t3code.ghostship.io` and complete Cloudflare sign-in. No separate
T3 account is required for this web interface. The internal gateway supplies a
native T3 bearer session for HTTP and WebSocket requests. The credential stays
in `~/.t3code-container/access/session.json` with mode `0600`, and the gateway
renews it before expiry. It rejects cross-origin browser requests. Cloudflare
Access remains the public authentication boundary. The gateway grants automatic
access only to the actual Cloudflared TCP peer and container loopback; other
containers retain native T3 authentication. Forwarded headers cannot grant access.

Use **Settings > Providers** for model-account sign-in:

- **Codex / OpenAI:** run `codex login --device-auth` in a T3 project terminal,
  complete the browser sign-in, then refresh provider status in Settings.
- **OpenCode:** configure the desired model provider and authenticate as needed.
- **Antigravity:** the official ACP executable and its matching helper are
  preinstalled. Choose **Sign in with Google**. For remote browser sign-in, paste
  the full localhost callback URL into T3's return-URL field and wait for account
  confirmation. Antigravity IDE/CLI login does not authenticate this ACP agent.

All three instances are enabled on the first launch. Later user settings are
preserved. Shared GitHub, OpenCode, OpenRouter, and Bitwarden environment fields
come from the existing encrypted secret catalog through the dedicated `t3code`
projection. The Google account and Codex login remain user-owned.

The image defines the `nobody`/`nogroup` (uid/gid 65534) account. Google's ACP
harness drops to this unprivileged account for sandboxed tool work; when it
cannot resolve the account the agent aborts instead of running the turn. The
offline updater probe fails closed when the account is absent. The separate
`-32000` "Authentication required" reply means the profile has no `auth.type` or
the Google account is not signed in yet; it is not an account-mapping problem.

The image includes Google's `1.1.1` ACP release with SHA-256 verification as a
fallback. Google's ACP server aborts natively on Asahi's 16 KB memory pages, so
on ARM64 it stays on the x86_64 archive under container-local QEMU, whose x86
guest supplies the required 4 KB pages. The `localharness_external` helper is a
static Go binary with no page-size assumption: emulating it corrupts its runtime
and panics mid-turn (`mergeStringNoZero`), which T3 reports as "Harness process
exited unexpectedly (WS close code 1006)"; it therefore runs natively on ARM64.
The server and helper wrappers run from the matching archive per architecture.
Emulation adds startup and execution overhead; account sign-in and authenticated
model requests still need live verification with the user's account.
The automatic updater reads the official ACP registry and accepts only the
corresponding `dl.google.com` archive URLs. It stages the x86_64 server and the
native harness together, checks ACP initialization offline, and only then
atomically switches the persistent `current` link. A failed download or protocol
check keeps the previous release. Releases live under
`~/.local/share/t3code-tools/antigravity`; the harness wrapper refuses to emulate
and falls back to the bundled native binary when a staged runtime harness is not
ARM64. T3's binary path stays `/bin/agy_acp_server.par` across updates.

Upstream: [provider setup](https://github.com/pingdotgg/t3code/blob/main/docs/user/install.md),
[Antigravity sign-in](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-antigravity.md),
and [official ACP registry](https://github.com/agentclientprotocol/registry/tree/main/antigravity-acp).

## OpenCode 2 upgrades

OpenCode 2 uses `@opencode/cli`; `opencode-ai@latest` remains on version 1.
Maintenance resolves the stable version, installs its matching native package
into an immutable prefix, and probes its version and authenticated `/api/info`
in disposable state before selecting it. Failed installation or probes retain
the old executable. Existing release directories remain available to running
processes. The user shim and legacy npm launcher resolve the same selected
release after promotion.

Build `.#nixosConfigurations.chill-penguin.config.system.build.t3codeToolMaintenance`
to obtain the exact updater without building or activating the container image.
Its `--stage-opencode` mode only stages and probes OpenCode; it leaves the
production launchers, database, other providers, and T3 server untouched.
Use `--activate-opencode` with the migration flag below for an OpenCode-only
promotion; it does not update other providers or restart T3. Its user launcher
translates legacy `run --dir` into the working directory and lowercases legacy
log levels, preserving existing noninteractive research commands on V2.
Keep the built closure rooted in both host and container stores when staging
through root SSH.

The first promotion of an existing V1 installation requires
`OPENCODE_ALLOW_V2_MIGRATION=1`. Before setting it, pause every producer of
OpenCode jobs, let all existing OpenCode processes exit, and take a consistent
SQLite backup. The process guard defers promotion while any OpenCode process
remains. Version 2 converts session history in the shared database; reverting
the executable alone is insufficient rollback. Restore the matching backup
with all OpenCode processes stopped if rollback is required. Fresh homes with
no V1 installation or database can install V2 directly.

Rehearse migration in a disposable container with separate home and no
production mounts, using `tests/t3code-upgrade-smoke.py --help`. Pass absolute
candidate paths and expected versions, plus `--opencode-db` pointing to a
consistent V1 backup. It checks T3's V2 endpoint, waits for OpenCode's background
migration, reads an existing V1 session, creates a session, rejects anonymous
API access, and confirms persistence after restarting only the canary server.
It supplies no account credentials or model prompts.

For already-deployed V1 maintenance scripts after T3 moves to Orchestrator V2,
run the committed `scripts/t3code-v2-maintenance-guard` as root on the host.
It reloads only maintenance unit definitions and selects the unsupported probe
adapter so updates/restarts defer. The legacy server-monitor oneshot is skipped
on V2 because it can bypass its probe after repeated HTTP failures. Podman
health checks and process memory containment remain active. These `/run`
drop-ins expire on host reboot/container replacement; deploy the committed
probe and monitor fixes before removing them. Automatic maintenance remains
deferred until a V2 activity adapter is implemented and verified.

## Android installation

Open `https://t3code.ghostship.io` in Android Chrome and complete Cloudflare
sign-in. Use Chrome's menu, then **Install app** or **Add to home screen >
Install**. T3 Code opens from its own launcher icon in a standalone window.
If a shortcut was created before installation support was added, install the
app from a refreshed Chrome tab and remove the old shortcut.

The gateway supplies a named manifest, 192px/512px icons with maskable safe
areas, and a manifest link that includes Cloudflare cookies. A root-scoped
service worker shows a reconnect screen when offline. Coding still requires a
connection to the server. The worker caches no application bundles, code,
messages, or credentials; normal navigation uses the current server version.
Gateway-owned assets persist across T3 npm updates and container replacement.

Validate with `nix develop .#browser -c node --test tests/t3code-pwa.browser.cjs`.
The Chrome fixture checks real install eligibility and the browser's install
event behind cookie authentication, offline navigation, and fresh content after
reconnection. Physical Android installation must still be verified on a phone.
The icon PNGs are rendered from `packages/t3code/pwa/icon.svg` using
`rsvg-convert -w <size> -h <size>` in the browser shell. Change the versioned icon
URLs when artwork changes so Chrome can update installed icons.

## Antigravity terminal CLI

`agy` is the official Antigravity terminal CLI, separate from T3's ACP provider.
Install it with `python3 packages/t3code/update-agy.py`. This also installs
persistent bootstrap and after-update hooks. The executable lives at
`~/.local/bin/agy` in the persistent container home. Bootstrap
and the four-hour tool updater check Google's platform manifest, verify its
SHA-512 checksum, and run a version probe before atomically replacing the CLI.
The CLI's own background updater remains available too.

Run `agy --version` or `agy --help` in the T3 terminal. On first use, run `agy`
and complete its Google sign-in; T3's ACP login does not authenticate the CLI.
For scripted tasks, use `agy -p "your task"`. The ARM64 CLI launcher was verified
on Chill Penguin; authenticated execution requires the separate CLI login.

## Grok Build CLI and T3 provider

Run `python3 packages/t3code/setup-grok.py` to install the official
`@xai-official/grok` npm package and persistent bootstrap/after-update hooks.
The `grok` command is exposed in `~/.local/bin`; its isolated npm installation
and `~/.grok` credentials persist in the container home. The existing four-hour
tool updater refreshes it when T3 is idle. Grok's `agent` alias is not installed,
preserving the shared Ghostship command.

Use `grok login --device-auth` to authenticate from another browser. In T3's
provider settings, enable Grok and set its binary path to
`/home/t3code/.local/bin/grok`, then refresh provider status. CLI and T3 use the
same user home and login. Verify an authenticated T3 task before treating an
installed/ready badge as proof of model access.

## Memory budget

The T3 server service includes all provider processes and their child tools in
one cgroup. It has a 36 GiB `MemoryHigh` threshold and a 40 GiB `MemoryMax`
ceiling on Chill Penguin. The previous 12/16 GiB limits caused repeated CLI
health-check and Git timeouts once the combined workload exceeded 12 GiB,
even when the host had available memory.

When direct CLI probes succeed but T3 probes time out, inspect
`memory.events` and `memory.pressure` in the service cgroup. Increasing probe
timeouts does not fix memory reclaim stalls. The limits can be applied to the
running service with `systemctl set-property --runtime t3code-server.service
MemoryHigh=36G MemoryMax=40G` inside the container as root, without restarting
active agents; the image configuration supplies the same limits on recreation.

Podman's systemd mode creates a RAM-backed `/tmp` unless a mount overrides it.
T3 now binds `/srv/apps/t3code/tmp` to `/tmp` with mode `1777`. On October 13,
CAD evaluation checkouts occupied about 30 GiB of tmpfs, charged as `shmem`
to the server cgroup. With no swap, those pages could not be reclaimed;
the 32 GiB high threshold stalled the UI despite modest process RSS.
Inspect `shmem` in `memory.stat` and `df -h /tmp` as well as anonymous memory.
Raising the running threshold to 36 GiB restored HTTP responses without a
restart or deleting work. The disk mount takes effect on the next explicitly
authorized container recreation; do not remount over active temporary files.
The disk directory retains files across recreations; preserve active work when
cleaning it, and monitor its disk usage rather than treating it as disposable RAM.

The one-minute server monitor records the main process RSS, combined anonymous
memory, total cgroup memory, and memory pressure in
`~/.t3code-container/logs/t3code-server-monitor.log`. These distinguish process
growth from reclaimable file cache; high usage alone does not prove a leak.
Memory observations are diagnostic and never trigger a server restart, even
while idle. At least 8 GiB of anonymous memory, any full reclaim stalls over
the last ten or sixty seconds, or an unavailable memory measurement veto web
recovery. Pressure-related web failures reset the recovery streak; memory is
checked again immediately before any recovery attempt. Missing providers wait
for idle. The monitor shares the updater lock and rechecks activity before
restarting for non-memory failures.

The five-second process guard protects both the service MainPID and the native
`t3 serve` child spawned by npm's Node launcher. It stops one tool over 12 GiB
RSS, or the largest tool of at least 1 GiB when total memory reaches
`memory.high`, anonymous memory exceeds 75% of that limit, and full reclaim
stalls exceed 10% over ten seconds. This handles combined tool allocations
below the individual limit: on October 11, about 20 GiB of anonymous memory
at the 24 GiB high limit stalled the UI until the watchdog restarted two active
sessions. Cache usage alone does not trigger tool termination. The guard
rechecks pressure and process identity before signaling, cancels escalation
after recovery, and escalates TERM to KILL after 20 seconds if the tool still
qualifies through its own RSS or continuing pressure.
Containment can abort the selected tool, but leaves other sessions running;
timestamped actions in `t3code-process-memory-guard.log` identify the reason.
The guard also sets `oom_score_adj=-1000` on the launcher and native server,
making them ineligible for kernel OOM selection. Provider and tool processes
receive `500`, including newly spawned children that inherited server immunity.
This preserves the server when the 40 GiB hard limit or host pressure requires
an OOM victim. Recovery may start a stopped server; forced recovery of a web
endpoint requires five consecutive failures with no memory veto.

Maintenance ignores deleted threads and pending requests superseded by a later
turn. Live provider sessions that are still starting or running, unresolved
pending requests from the last 10 minutes, and user messages from the last 15
minutes block restarts. A session that is starting or running keeps its turn
active even after a mid-turn checkpoint stamps `completed_at` on the turn row;
only the session leaving the running state settles the turn. No conversation records are modified.

## Maintenance

`system.autoUpgrade` deploys GitHub `main` nightly (04:00 UTC plus up to 45
minutes, with `--impure` for Asahi firmware; missed runs catch up after boot).
It waits for a running backup and alerts through `ghostship-failure@` on
failure; the next run retries an interrupted switch. To deploy manually, run
`nixos-rebuild switch --impure --flake .#chill-penguin -L` on the host after
pulling the committed configuration. This updates the system profile and boot
entry as well as the running system. Running a built system's
`switch-to-configuration switch` directly does not advance the system profile;
reboot can therefore return to a generation without T3 Code.

The four-hour tool timer resolves the current registry version online before it
updates T3, Codex, and Claude, then verifies the installed package manifest
matches that exact version. T3 installs into a versioned directory and keeps
earlier releases so an update cannot remove the web assets used by a running
server. It installs and verifies the matching native package even when npm
skips optional dependencies. A persistent activation marker queues the next idle
restart if maintenance is run manually. The next server start uses the new
release. A lookup, install, or verification failure is reported as maintenance
failure instead of silently accepting stale tooling.
It also updates OpenCode and Antigravity when the database reports no pending or
running turns, then runs `after-update.d` to reapply Ghostship tooling. Unknown
activity defers maintenance and recovery. Deferred tool checks retry on the
one-minute maintenance timer once work becomes idle. Each provider update is
attempted even if another fails. Cursor reads the release pinned by its
installer and downloads only when that release is not already active. Changed provider tools or T3 settings queue a
server restart, which waits for T3 to become idle. Ghostship tool package
changes do not: its command wrappers load the new package on every invocation.

The daily `t3code-retention` timer keeps storage bounded. It rotates container,
provider, server-trace, and OpenCode logs that grow past 50 MiB, deletes aged
rotated logs after 14 days, rebuilds OpenCode's SQLite database when the
unbounded `event` table crosses 2 GiB or 100k rows (keeping projected
session/message data), archives settled unpinned threads older than 7 days, and
deletes unpinned threads whose latest activity is older than 180 days. When a
thread is archived, retention also deletes its worktree under `~/.t3/worktrees`
once no active thread still references that path (shared checkouts used by open
threads are kept). Archive and delete go through T3's orchestration API; pinned
 threads and threads with active turns are skipped. Manual dry runs use
`t3code-retention --dry-run`.

The container's isolated Nix store at `/srv/apps/t3code/nix-root/nix` is
garbage-collected daily on the host. GC roots only the paths in the image
contents (`t3codeImageContents`), which `podman-t3code` seeds and symlinks under
the store's `gcroots` on every start. Every binary a container unit can start
must be in that list, or a GC deletes it and the unit fails to exec with no log
line; `t3code-retention` was the missing entry that let OpenCode's event log
grow to 10 GiB.

The image includes OpenSSL as well as the CA bundle because Cursor's Node runtime
uses OpenSSL's compiled-in certificate directory when it probes system trust.
Container health reports web/server failures as unhealthy. The server monitor
restarts only after work is idle; provider authentication failures do not
trigger restart loops.

`t3code-apply-config` validates JSON/TOML and OpenCode configuration, restarts the
server, and restores the last healthy configuration snapshot if recovery fails.
`t3code-tunnel start <name> <port>` exposes a project server with an ephemeral
Cloudflare Quick Tunnel. Before installing Ghostship tooling, doctor, after-update, and the 30-minute
`t3code-ghostship-agent-sync.timer` (first run 15 minutes after boot) fast-forward
`/workspace/ghostship-agent` and `/workspace/nixos-config` from `origin/main`.
They skip a checkout that is off `main`, has tracked changes, has a merge or
rebase in progress, or cannot fast-forward. Container boot and server starts
skip the fetch so recovery never waits on GitHub. Sync output is in
`~/.t3code-container/logs/t3code-ghostship-agent-sync.log`. Container lifecycle hooks live in
`~/.t3code-container/hooks/`; hook output is recorded in
`~/.t3code-container/logs/t3code-hooks.log`. Update output is in
`t3code-tool-auto-update.log` in the same directory.

The host unit preserves running work across rebuilds. Image updates do not
interrupt active tasks: `nixos-rebuild switch` stages the desired deployment ID,
and `t3code-deploy-when-idle.timer` (running every minute) automatically applies
the update after 30 seconds of sustained idle. The V1 activity probe reads
`state.sqlite`: idle means no running or recently pending turn, no starting or
running provider session, no user message in 15 minutes, no thread activity in
10 minutes, and no unsettled Claude background task (shell, subagent, or
monitor) started in the last 12 hours. Background tasks outlive the turn that
started them, so a settled turn alone does not prove idle. Orchestrator V2 keeps
that V1 database after switching to `statev2.sqlite`; its stale projections
cannot establish idle. Until a V2 adapter is verified, the probe returns unknown
when V2 state exists, and automatic updates and restarts defer. Missing state
also returns unknown. The deployer leaves a
unit that is starting or stopping alone; only a stopped or failed unit is
started without the idle gate. The deployer holds the container's tool-maintenance lock
(`~/.local/state/t3code-tool-update/tool-update.lock`, shared through the home
bind mount) across the restart. Each container carries its deployment ID in the
`io.ghostship.t3code.deployment` label, so after a reboot, an interrupted
deploy, or a slow health check, a container already running the desired image
is recorded as applied once healthy instead of restarted again; one still in
its health start period is left alone. An unhealthy new image gets at most
three idle-gated restarts. Each failed start alerts through
`ghostship-failure@`; after the third the deployer stops, whether that image is running, exited, or
never started, until a new image is desired or an operator runs `t3code-safe-restart`. A host switch does not
restart an in-flight deploy. Operators can also queue a safe idle-aware restart at any time
with `t3code-safe-restart` (or pass `--force` to bypass). Backups include the
home and projects but exclude the Docker and Nix stores.

```sh
systemctl status podman-t3code.service --no-pager
podman exec t3code systemctl --failed --no-pager
podman exec t3code curl -fsS http://127.0.0.1:3773/ >/dev/null
podman exec t3code curl -fsS http://127.0.0.1:3773/.well-known/t3/environment >/dev/null
podman exec --user 3000:3000 t3code t3 --version
podman exec --user 3000:3000 t3code docker info
podman exec --user 3000:3000 t3code nix store ping --store daemon
```

Exercise ACP initialization offline in a disposable container using the built
image (no account or project access):

```sh
podman run --rm -i --network none --user 3000:3000 --entrypoint /bin/python \
  localhost/ghostship-t3code:t3code-runtime - < tests/t3code-acp-smoke.py
```
