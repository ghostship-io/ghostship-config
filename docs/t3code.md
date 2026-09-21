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
T3 pairing token is needed on desktop or mobile. The internal gateway supplies a
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
one cgroup. It has a 24 GiB `MemoryHigh` threshold and a 32 GiB `MemoryMax`
ceiling on Chill Penguin. The previous 12/16 GiB limits caused repeated CLI
health-check and Git timeouts once the combined workload exceeded 12 GiB,
even when the host had available memory.

When direct CLI probes succeed but T3 probes time out, inspect
`memory.events` and `memory.pressure` in the service cgroup. Increasing probe
timeouts does not fix memory reclaim stalls. The limits can be applied to the
running service with `systemctl set-property --runtime t3code-server.service
MemoryHigh=24G MemoryMax=32G` inside the container as root, without restarting
active agents; the image configuration supplies the same limits on recreation.

The one-minute server monitor records the main process RSS, combined anonymous
memory, total cgroup memory, and memory pressure in
`~/.t3code-container/logs/t3code-server-monitor.log`. These distinguish process
growth from reclaimable file cache; high usage alone does not prove a leak.
Three consecutive high samples trigger idle-only recovery: either 8 GiB of
anonymous memory, or 20 GiB total with at least 10% full memory stall time over
the last minute. A service must have run for 30 minutes before memory recovery
can restart it. Cache alone does not trigger recovery. Missing measurements or
unknown activity defer recovery. The monitor shares the updater lock and
rechecks activity before restarting; active work can delay recovery indefinitely.

Maintenance ignores deleted threads and pending requests superseded by a later
turn. Running turns, unresolved pending requests, and messages from the last
minute still block restarts. No conversation records are modified.

## Maintenance

Deploy with `nixos-rebuild switch --flake .#chill-penguin -L` on the host after
pulling the committed configuration. This updates the system profile and boot
entry as well as the running system. Running a built system's
`switch-to-configuration switch` directly does not advance the system profile;
reboot can therefore return to a generation without T3 Code.

The four-hour tool timer resolves the current registry version online before it
updates T3, Codex, and Claude, then verifies the installed package manifest
matches that exact version. A lookup, install, or verification failure is
reported as maintenance failure instead of silently accepting stale tooling.
It also updates OpenCode and Antigravity when the database reports no pending or
running turns, then runs `after-update.d` to reapply Ghostship tooling. Unknown
activity defers maintenance and recovery. Each provider update is attempted even
if another fails. Changed tools or the Ghostship tool package queue a server
restart, which waits for T3 to become idle.

The image includes OpenSSL as well as the CA bundle because Cursor's Node runtime
uses OpenSSL's compiled-in certificate directory when it probes system trust.
Container health checks web/server
availability; provider authentication failures do not trigger restart loops.

`t3code-apply-config` validates JSON/TOML and OpenCode configuration, restarts the
server, and restores the last healthy configuration snapshot if recovery fails.
`t3code-tunnel start <name> <port>` exposes a project server with an ephemeral
Cloudflare Quick Tunnel. Container lifecycle hooks live in
`~/.t3code-container/hooks/`; hook output is recorded in
`~/.t3code-container/logs/t3code-hooks.log`. Update output is in
`t3code-tool-auto-update.log` in the same directory.

The host unit preserves running work across unrelated rebuilds. To deploy a
changed image, explicitly restart `podman-t3code.service` during a maintenance
window after building and switching the host configuration. Backups include the
home and projects but exclude the Docker and Nix stores.

```sh
systemctl status podman-t3code.service --no-pager
podman exec t3code systemctl --failed --no-pager
podman exec t3code curl -fsS http://127.0.0.1:3773/ >/dev/null
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
