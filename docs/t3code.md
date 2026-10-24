# T3 Code

T3 Code runs in a persistent systemd container with an independent Nix store.
`packages/t3code/image.nix` alone defines its image: base packages, boot units and
image parameters. Host switches, agent pins and tooling changes preserve the
container; only an image change queues replacement after sustained idle.
Ghostship-agent owns and refreshes tools, CLIs and skills in the persistent home.
T3 app releases update there too, restarting only the app when idle. Provider
CLI and skill updates do not queue an app or container restart.

For the staged unprivileged runtime and separate development Podman engine, use
the [hardening acceptance workflow](t3code-hardening.md). Root SSH administration
remains an explicit requirement; the active runtime stays intact during testing.

Host switches preserve the running container and its dedicated Podman relay,
user manager, runtime directory, network and rootfs helpers. Changes to those
helpers take effect at a separately authorized runtime restart.

The minimal image sets the system and user service `PATH` before managed helpers
run; helpers need `sed` and `head` during early desktop environment discovery.
Image replacement requires a candidate receipt for the exact image and deployment
ID at `/var/lib/ghostship/t3code-deployment/receipts/<deployment-id>.json`, including
signed-in app, provider turn, CLI, skills and desktop checks. An owner force request
bypasses idle only; it does not bypass that receipt.

## Projects and state

The container user is `t3code`, with home `/home/t3code`. Host state lives in
`/srv/apps/t3code/{home,workspace,nix-root}`. At container startup each missing top-level repository is copied to the new
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
after app updates. Hook failures are logged and do not prevent web access.
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

Open `https://t3code.ghostship.io` and complete Cloudflare sign-in.
The container hostname is the internal name `t3code`: assigning its public
hostname would also register that name in Podman DNS and `/etc/hosts`, shadowing
the Cloudflare HTTPS edge with the HTTP-only origin. Container hostname changes
apply at the next idle swap; never restart an active session to change one.

No separate T3 account is required for this web interface. The internal gateway supplies a
native T3 bearer session for HTTP and WebSocket requests. The credential stays
in `~/.t3code-container/access/session.json` with mode `0600`, and the gateway
renews it before expiry. It rejects cross-origin browser requests. Cloudflare
Access remains the public authentication boundary. The gateway grants automatic
access only to the actual Cloudflared TCP peer and container loopback; other
containers retain native T3 authentication. Forwarded headers cannot grant access.

After a T3 authorization-scope change, a still-valid gateway token can lack new
permissions, such as `diagnostics:read`, and the UI reports that diagnostics and
usage are unavailable. Confirm the gateway's `/api/auth/session` permissions,
verify that a newly issued native session has the required grant, then revoke
only the cached gateway session by its public session ID. The gateway renews it
on the next request without a service restart. Refresh the browser to reload
its session permissions; keep all bearer values inside the process using them.

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

A fourth, `opencode-free`, instance exposes the agent's owner-approved free
routes as ordinary one-off T3 workers. `t3code-managed-config` runs
`t3code-free-instance-reconcile` at container setup, `t3code-server.service`
runs it once before T3 starts, and `t3code-free-instance.timer` repeats it every
15 minutes. It generates a private config home under
`/home/t3code/.config/opencode-free` with its own `XDG_CONFIG_HOME` and a
filtered `OPENCODE_MODELS_PATH` catalog, so the main `opencode` instance and
`~/.config/opencode` are untouched. Provider entries name the projected
environment variables; no key is written to a file. While the agent's
`trust.approved_routes` is empty the instance is disabled and its config and
catalog are empty. T3 watches `settings.json`, so a reconciler update appears
without a restart; the timer exists because a one-off manual edit can race a T3
settings write.

The image defines the `nobody`/`nogroup` (uid/gid 65534) account. Google's ACP
harness drops to this unprivileged account for sandboxed tool work; when it
cannot resolve the account the agent aborts instead of running the turn. The
offline updater probe fails closed when the account is absent. The separate
`-32000` "Authentication required" reply means the profile has no `auth.type` or
the Google account is not signed in yet; it is not an account-mapping problem.

The managed Ghostship package includes Google's `1.1.1` ACP release with SHA-256 verification as a
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
ARM64. T3's managed binary path stays in `~/.local/bin` across updates.

Upstream: [provider setup](https://github.com/pingdotgg/t3code/blob/main/docs/user/install.md),
[Antigravity sign-in](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-antigravity.md),
and [official ACP registry](https://github.com/agentclientprotocol/registry/tree/main/antigravity-acp).

## Native subscription limits

Confirm an update through the running server's
`/.well-known/t3/environment` version, then inspect fresh provider
`usageLimits` readings. A staged executable's `--version` does not establish
activation. Official T3 Code 0.1.1 fixes missing zero-use Grok billing periods
and merges Antigravity quota summaries from both Google endpoints. Gemini
coverage can still be intermittent: a nonempty summary containing only the
Claude/GPT windows prevents the model-quota fallback from running. One good
reading does not establish stable Gemini coverage.
Flash uses the Gemini family label; selecting a Flash model does not create
a separate Flash quota row.

OpenCode 2's active Console OAuth login can work while T3 reads an expired
legacy Go key. In T3 0.1.1, its Go probe skips Console OAuth credentials;
replacing the working OAuth login is unnecessary. The existing
`OPENCODE_AUTH_CONTENT` instance environment override can supply
`{"opencode-go":{"type":"api","key":"<current Console OAuth access token>"}}`
to T3's quota reader. The usage endpoint accepts that access token as a bearer
credential; this compatibility format does not convert OpenCode's login to API
key authentication. See [upstream OAuth tracking](https://github.com/pingdotgg/t3code/issues/14983).

This is a temporary, manually synchronized override. Obtain the active token
inside the process applying the change, save the environment variable through
T3's settings API as **sensitive**, and verify that settings reads redact it.
OpenCode retains ownership of OAuth renewal; reapply the override when its
access token rotates or the selected account changes. Remove it when T3 can
read the native OAuth credential directly. Verify all three Go windows and
their reset times against the same account's usage response.

OpenRouter and Ollama model discovery does not provide native Limits entries.
T3 0.1.1 has no quota reader for either, and its configurable CLIProxyAPI usage
hub reader accepts only Codex and Claude accounts. A working provider usage API
alone cannot add those accounts to the native panel through settings.

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
Install it with the updater in `ghostship-agent/packages/t3code/update-agy.py`. This also installs
persistent bootstrap and after-update hooks. The executable lives at
`~/.local/bin/agy` in the persistent container home. Bootstrap
and the four-hour tool updater check Google's platform manifest, verify its
SHA-512 checksum, and run a version probe before atomically replacing the CLI.
The CLI's own background updater remains available too.

Run `agy --version` or `agy --help` in the T3 terminal. On first use, run `agy`
and complete its Google sign-in; T3's ACP login does not authenticate the CLI.
For scripted tasks, use `agy -p "your task"`. The ARM64 CLI launcher was verified
on Chill Penguin; authenticated execution requires the separate CLI login.

## Command Code GOAT ACP provider

The image installs `command-code` **1.88.0** from the committed npm lock under
`packages/t3code/command-code/`. The installer verifies the exact upstream
SHA-512 integrity and requires Node >=22 (the managed tools supply Node 24).
`npm ci --ignore-scripts` pins transitive packages too. Native self-updates and
remote catalog changes are disabled; changing the pin or paid allowlist needs
a reviewed configuration change. Installation is atomic and retries reuse the
completed release. T3's startup installs the managed `cmd` entry and merges only
the `commandCode` provider instance before the server reads its settings.
Each successful setup sets this managed instance to `enabled: true`; disabling
it in T3's settings does not persist across a successful server restart.
Setup is an optional, non-fatal `ExecStartPre=-` step: failure logs one sanitized
line, disables an existing managed instance where its settings remain readable,
and lets T3 start. Installation and configuration finish before the launcher
switches, so a failure preserves the previous ready CLI release. With a ready
release, subsequent startup needs no registry access.

The instance uses T3's [local ACP command support](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-acp.md)
with `cmd acp`. Command Code's [native ACP server](https://commandcode.ai/docs/acp)
owns the agent loop, tools and model options. A local stream guard exposes two
reviewed paid GOAT IDs: `deepseek/deepseek-v4.1-flash` (the default) and
`minimaxai/minimax-m2.7`. These lowercase IDs were confirmed in the native
1.88.0 ACP catalog; the vendor's [DeepSeek](https://commandcode.ai/models/deepseek-v4-1-flash)
and [MiniMax](https://commandcode.ai/models/minimax-m2-7) model-page catalogs
publish positive prices and `zeroDataRetention: true`. The checked sources and
values live beside the allowlist in `paid-models.json`. GLM-5.2 and Kimi K2.5
are excluded because the vendor catalog marks their zero-retention flag false.
The guard lists DeepSeek V4.1 Flash first and requests it through native
`session/set_model` before returning a new session to T3. If that selection
fails, session creation still succeeds with the guard recording it as
unselected: prompts are refused until an approved model selection is
acknowledged. Unapproved switches during a session still stop it.
The guard filters both model catalogs and rejects other model selections,
unknown configuration changes and slash commands that could bypass the picker.
Native ACP `loadSession` and list/resume/close capabilities pass through unchanged.
Loaded and resumed sessions record their reported current model and apply the
same catalog policy before a prompt can run. A missing or unapproved model
returns an ACP restoration error so T3 can try a fresh session; it never reuses
a stale paid selection from an earlier session. Use T3's model and mode controls. Native permission
requests and tool results still pass through ACP.

Every native process receives `CMD_ZDR=1`. Command Code's [ZDR contract](https://commandcode.ai/docs/resources/zdr)
requires a ZDR-capable upstream or fails the request; it must never fall back
to retained processing. An approved model with no ZDR capacity therefore fails.
Free models are excluded even on a paid account. The
[privacy policy](https://commandcode.ai/privacy) (checked 2026-10-23) permits up
to 30 days of request-content retention by default and sharing free-model
sessions with training partners. It describes no training of its own foundation
models on source code; default retention includes abuse review. The
[terms](https://commandcode.ai/terms) reserve monitoring rights and require rights
to submit inputs; no general ban on private code was found. With ZDR, request
content is processed transiently and only operational metadata remains. There
is no separate blanket promise excluding human review in the default terms.

Authentication uses **native `cmd login` only**, as the T3 user. The CLI manages
`~/.commandcode/auth.json`; agents must not read, copy or print its token.
`HOME=/home/t3code` is the writable persisted home bind in `t3code.nix`, so this
file survives image replacement and container restart. It is never baked into
the image. Startup preserves native authentication state; the fast tests cover
the bind, HOME, absence of image credentials and preservation across reinstalls.
The managed entry forwards `cmd login` directly to the native CLI for the owner
to complete its browser/device flow. It also supports `cmd --version`.

After exact-head review, use a candidate container to verify CLI startup and
ACP initialization without login; these checks do **not** establish account,
model, or inference availability. After deployment and the owner's native
login, verify T3 lists the paid models and answers a trivial public prompt with
ZDR enforced. Follow the candidate receipt and guarded deployment workflow.
A candidate with fresh T3 userdata still needs the matching persisted
`.t3/runtime` binaries. Omitting that directory can select an older bundled
runtime and incorrectly report that the ACP registry driver is unregistered.

For later usage integration, the vendor's [usage documentation](https://commandcode.ai/docs/resources/usage-limits)
names native `/usage` meters for balance and 5-hour/weekly caps and resets;
Studio Usage reports request cost and tokens. ACP reports per-session usage.
No machine-readable account-quota endpoint or local quota file is verified by
this integration. Collection and dashboards are separate work.

For the DeepSeek comparison and quota integration, the
[GOAT usage table](https://commandcode.ai/docs/plans/goat#usage-limits) explicitly
labels the DeepSeek V4.1 Flash (latest) row **Requests / 5 hours**, **Requests /
week**, **Requests / month**: **41,000 / 103,000 / 205,000**. These are estimated
request counts using a typical cached agent request, not fixed request quotas
or token allowances. The plan is metered in credits and actual request size and
model pricing determine usage. Treat these counts as planning estimates rather
than a provider-reported remaining balance.

The same GOAT model table and [model page](https://commandcode.ai/models/deepseek-v4-1-flash)
show a **1M-token context** and off-peak **$0.15 input / $0.60 output per million
tokens**. Peak is **$0.30 input / $1.20 output per million tokens**, during
**01:00–04:00 and 06:00–10:00 UTC, Monday–Friday**. The remaining 17 hours on
weekdays, and all weekend hours, are off-peak. These checked public prices can
change; ZDR routing may cost more depending on the upstream selected.

The exact Command Code alias is `deepseek/deepseek-v4.1-flash`, without a
`:1017` suffix. In its [October 19 announcement](https://x.com/CommandCodeAI/status/2112215504064819443),
Command Code states that all V4.1 requests use the latest 1017 version; the
[upstream October 17 changelog](https://api-docs.deepseek.com/updates/)
also describes moving its existing Flash API name to 1017. This is a vendor
announcement, not a per-response checkpoint attestation. The `(latest)` alias
is not an immutable checkpoint pin and can move. Each comparison run must
record the requested alias, resolved build if exposed by the native response,
time, and dated vendor provenance. If only the alias is exposed, record the
resolved build as unknown and the dated 1017 announcement separately; do not
claim that the run independently proved checkpoint equality with a pinned
1017 route. The CLI pin freezes the harness, not hosted model weights.

The collector's worker identity is
`commandCode/deepseek/deepseek-v4.1-flash`, separate from every OpenCode/Ollama
DeepSeek route and its outcome history. It publishes the GOAT table above as
`command_code.estimated_allowances`, not measured quota windows. Current usage
and remaining capacity come only from native Command Code reporting through T3;
until reported they stay unknown. The effective published input/output price
follows the UTC schedule above. CLI and MCP picks read the same published worker
selection. Eligibility requires the configured managed `cmd acp` launcher with
`CMD_ZDR=1`; this subscription route is always paid and never a free-route choice.
The existing quality evidence and priors remain in force; a successful public
transport prompt establishes no harness quality claim before the controlled pilot.

## Provider zero-data-retention state

Every inference provider's strongest available zero-retention or no-training
setting, its evidence, and the owner decisions it still needs are recorded in
[provider zero data retention](provider-zdr.md). The managed Claude Code setup
in `packages/t3code/provider-privacy/setup.py` turns off nonessential traffic,
telemetry, error reporting, and feedback before T3 starts.
`scripts/provider-zdr-doctor` re-checks the table, the Command Code `CMD_ZDR`,
the Claude opt-outs, the Grok upload setting, and the free-pool policy. Add
`--browser` to re-read the OpenRouter, Groq, ChatGPT, and Mistral account
toggles through the personal profile.

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

Deploy merged changes with `agent deploy run`; `--agent-rev REV` pins an agent
revision first. Its gates preserve busy T3 sessions, record the generation and
verify live health. Image updates wait for idle when a restart is needed.

The four-hour timer checks official T3 standalone releases and provider registry
versions. It verifies T3's SHA-256 checksum, executable version, web client and
runtime dependencies before selecting a versioned directory. Earlier releases
remain available to running servers. An interrupted promotion is reconciled on
retry; a persistent activation marker queues only an idle app restart. Failed
downloads or probes preserve the selected release and report maintenance failure.
Provider installs still verify their exact registry manifest versions.
It also updates OpenCode and Antigravity when the database reports no pending or
running turns, then runs `after-update.d` to reapply Ghostship tooling. Unknown
activity defers maintenance and recovery. Deferred tool checks retry on the
one-minute maintenance timer once work becomes idle. Each provider update is
attempted even if another fails. Cursor reads the release pinned by its
installer and downloads only when that release is not already active. Only a changed T3 app release queues a server restart after sustained idle.
Provider tools, settings, skills and Ghostship package updates take effect on
their next invocation without an app or container restart.

The `~/.local/bin/t3` wrapper keeps its Nix library environment and resolves the
selected standalone release through the persistent `current` link. App updates
change that link and restart only the app after sustained idle.

T3 shows a provider "Update available" notice when the npm registry's `latest`
tag is newer than the installed Codex, Claude, OpenCode or Grok version. The
ten-minute `t3code-provider-update-watch.timer` reads those same registry
entries and the installed manifests, and starts the tool updater once for each
newly published version. The updater keeps its idle and OpenCode process
guards. T3 re-probes provider versions every five minutes, so the notice clears
after installation without an app restart. If an update stays
blocked, the watcher does not retrigger for the same version; the four-hour
timer keeps retrying. Watcher output goes to the tool update log.

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
garbage-collected daily on the host. The base image closure and the pinned
Ghostship tooling payload have separate roots. The managed release resolver
also roots newer packages built in the container; all executable helpers must
remain reachable through one of those roots.

The managed tooling package includes OpenSSL as well as the CA bundle because Cursor's Node runtime
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
cannot establish idle. The probe uses the V2 adapter when that state exists,
including active runs, subagents and pending launches. Missing state
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
with `t3code-safe-restart`. A forced restart bypasses the idle gate and interrupts the work in
flight, so it needs the owner's own deploy or activate instruction, recorded with
`--owner-request "<short quote or reference>"`; without it the tool refuses the restart. Backups include the
home and projects but exclude the development engine and Nix stores.

```sh
systemctl status podman-t3code.service --no-pager
podman exec t3code systemctl --failed --no-pager
podman exec t3code curl -fsS http://127.0.0.1:3773/ >/dev/null
podman exec t3code curl -fsS http://127.0.0.1:3773/.well-known/t3/environment >/dev/null
podman exec --user 3000:3000 t3code t3 --version
podman exec --user 3000:3000 t3code podman info
podman exec --user 3000:3000 t3code nix store ping --store daemon
```

Exercise ACP initialization offline in a disposable container using the built
image (no account or project access):

```sh
podman run --rm -i --network none --user 3000:3000 --entrypoint /bin/python \
  localhost/ghostship-t3code:t3code-runtime - < ../ghostship-agent/packages/t3code/acp-smoke.py
```
