# Agent desktop

`desktop.ghostship.io` is a persistent Linux GUI workstation in a Podman
container on `chill-penguin`, built for agent automation and live human
intervention. It runs LXQt on a labwc Wayland session with Selkies 2
streaming, Pelorus desktop control (AT-SPI + Pixelflux), pinned Google Chrome
browsers in per-identity browser stages, Bladebro as the MCP browser driver,
and one web UI with two modes: **Browsers** (the agent viewer) and
**Desktop** (Selkies).

Everything is defined in `modules/self-hosted/agent-desktop.nix` and
`containers/agent-desktop/`. The desktop lifecycle is independent of t3code:
it starts at boot, keeps its browser profiles across t3code restarts, and can
be updated without touching the T3 Code container.

## Endpoints

The t3code container joins the private `agent_desktop_net` and reads these
environment values (with the token from the `agent-desktop` secret):

| Variable | Value | Purpose |
| --- | --- | --- |
| `AGENT_DESKTOP_API_URL` | `http://10.89.7.2:7080` | Authenticated Pelorus proxy |
| `AGENT_DESKTOP_API_TOKEN` | secret | Bearer token for the proxy |
| `AGENT_DESKTOP_PELORUS_URL` | `http://10.89.7.2:7080/pelorus` | Pelorus REST base |
| `AGENT_DESKTOP_SSH_HOST` | `10.89.7.2` | Desktop SSH host |
| `AGENT_DESKTOP_SSH_PORT` | `2222` | Desktop SSH port |
| `AGENT_DESKTOP_SSH_USER` | `abc` | Desktop SSH user |
| `AGENT_DESKTOP_SSH_KEY` | `~/.ssh/id_agent_desktop` | Provisioned automation key |

The web client is reachable at `https://desktop.ghostship.io` behind
Cloudflare Access, or `http://agent-desktop:3000` on `ghostship_net`.
Chrome's DevTools ports (9222/9223) and the manager-free Pelorus backend are
loopback-only; Pelorus agent/LLM routes and Pixelflux on port 5000 are never
proxied.

## Google Chrome browsers

Two on-demand Chrome instances run under independent s6 services, launched
as the desktop user inside the LXQt session:

| Identity | Profile | DevTools |
| --- | --- | --- |
| `agent` | `/config/agent-desktop/chrome/agent` | `127.0.0.1:9222` |
| `personal` | `/config/agent-desktop/chrome/personal` | `127.0.0.1:9223` |

Authentication (cookies, localStorage, IndexedDB, extensions, preferences)
lives in the profile directories and survives client disconnects, agent
restarts, image updates and container replacement. A human logs into a
service in the `personal` window through Selkies and agents keep using the
same instance. Neither port is published outside the container.

### Browser stages

Each identity's Chrome runs in its own **browser stage**: a headless Sway
compositor (`/etc/ghostship/browser-sway.conf`) started by `run-chrome`
together with `stage-control`. Chrome is the ordinary headed browser with GPU
rendering; only the monitors are virtual, as the labwc desktop's already are.

`stage-control` gives every Chrome window a 1920x1080 output of its own, with
the window tiled at a fixed 1600x900 in its top left (workspace gaps), so the
viewer and agents can see and use the **whole window**: tab strip, address
bar, toolbar, extension buttons, menus and popups. All outputs sit at 0,0, so
each window reports one ordinary screen (`screen.availLeft` 0). The stage
never moves focus on its own: new windows map on a hidden workspace, and
focus rests on an empty `idle` workspace. Using Chrome's own controls takes a
**focus lease** on one window (Chrome reads only one Wayland seat): focus
moves only between that window and `idle`, and its output moves to x=1920
while the lease lasts so the pointer can reach it; other windows are never
activated or deactivated. A lease ends when released or after 20 s without
input, and only one window holds it at a time (others get `busy`).
`stage-control` pairs sway windows with Chrome's DevTools window ids (home-tab
title, then unique tab titles, then elimination; ambiguous windows stay
unpaired), which tells the viewer which run a window belongs to.

Every agent drives its own window with target-scoped DevTools input, which
needs no focus and no global lock. Measured on Chrome 155 (2026-10-20): 8 and
16 agents, barrier-synchronised click/type/wheel/dialog/popup, 30,000 ops with
zero cross-talk and zero focus changes; with whole-window outputs and a
focus-lease loop opening Chrome's menu and typing in another window
throughout, 10,000 more with the same result. On labwc, by contrast, every new
window takes focus and blurs the field another agent is typing into, so agent
windows never live on the human desktop. Wait for a new page's first frame
before sending input (Chrome drops input that precedes it).

Stage windows are not visible in Selkies; people use them through the agent
viewer, which streams the whole window from its output and sends a person's
input through the lease. Agents use `browser_window` `screenshot` and `ui`
(`stage-control call <identity>` over SSH) for Chrome's own controls and
extensions; their input marks the run busy and fails with `paused` during a
takeover, as page input does. Debug a stage by nesting it on the desktop with
`GHOSTSHIP_STAGE_BACKEND=wayland` (never in production: a minimized nested
stage stops rendering and stalls every agent).

Chrome does not start at boot. Both services
(`svc-agent-desktop-chrome-agent`, `svc-agent-desktop-chrome-personal`) are
outside the s6-rc `user` bundle, so s6 supervises them in the down state:

- **Start:** `chrome-ensure <agent|personal>` (as `abc` over SSH) starts the
  identity's service if its DevTools port does not answer and waits up to 60 s
  (`CHROME_ENSURE_TIMEOUT_SECONDS`) for `/json/version`. It exits 0 once
  reachable and non-zero with a stderr message on a bad identity or timeout.
  It is idempotent and serialised per identity by
  `/tmp/ghostship-chrome-ensure-<identity>.lock`. The Bladebro wrappers call it
  before attaching; a human starts the personal window the same way from a
  desktop terminal.
- **No startup window:** Chrome runs with `--no-startup-window`, so a started
  profile has no window until an agent creates one with
  `Target.createTarget {newWindow: true, background: true}`.
- **Lease reaping:** each agent window's home tab is
  `about:blank#ghostship-window-<token>.<expires>` (Unix seconds), which the
  leasing runtime slides while the lease is in use. Every idle check runs
  `chrome-lease-reaper` on each reachable identity: once `expires` is more
  than 120 s past (`CHROME_LEASE_SLACK_SECONDS`), it closes that window's
  tabs and the popups they opened, anchor last, and logs one line. Legacy
  anchors without `.<expires>`, unexpired leases and other windows are never
  closed, whichever host opened them.
- **Idle stop:** `svc-agent-desktop-chrome-idle` samples `/json/list` every
  60 s (`CHROME_IDLE_CHECK_SECONDS`). When an identity has had no page
  targets, or only plain `about:blank` ones, for 10 minutes
  (`CHROME_IDLE_TIMEOUT_SECONDS`, 600), it stops that service and logs one
  line. Any other page, including a page a human opened and agent anchors in
  either form, and any `chrome-ensure` call reset the clock.
- **Supervision:** starting is `s6-svc -u` and stopping is `s6-svc -d`, so s6
  relaunches a crashed Chrome while it is wanted up and keeps an idle-stopped
  one down until the next `chrome-ensure`. The idle service grants the `abc`
  group control of both services with `s6-svperms -G abc` at boot; no sudo is
  involved.

Clients: the ghostship-agent client calls `chrome-ensure <identity>` over SSH
before its first CDP call whenever `/json/version` is unreachable. Other CDP
clients must do the same.

The environment keeps the signals a real desktop would have: GPU-backed
WebGL, enabled sandbox, PulseAudio audio devices, Noto Color Emoji, a
timezone matching the network location, and the detection/fingerprint
bookmark set from the retired CloakBrowser profiles (shipped as managed
Chrome bookmarks).

For an extra isolated instance (parallel or untrusted work), use the blessed
launcher so the command line stays identical to the supervised instances:

```sh
ssh -i ~/.ssh/id_agent_desktop -p 2222 abc@10.89.7.2 \
  ghostship-chrome-instance start task-1 9224
ssh -i ~/.ssh/id_agent_desktop -p 2222 abc@10.89.7.2 \
  'bladebro nav https://example.com --port 9224'
ssh -i ~/.ssh/id_agent_desktop -p 2222 abc@10.89.7.2 \
  ghostship-chrome-instance stop task-1
```

Chrome is launched with a deliberately minimal command line: a custom
profile, a loopback DevTools port, native Wayland, first-run/crash UX
suppression, the basic password store, the US locale and a 1600x900 window.
Because agent windows stack in the stage, background-timer throttling,
renderer backgrounding and occluded-window backgrounding are disabled (`--disable-background-timer-throttling`,
`--disable-renderer-backgrounding`, `--disable-backgrounding-occluded-windows`)
so background tabs keep rendering and running timers. No sandbox, GPU or
fingerprint flags.

Never open one profile directory in two browser processes.

## Bladebro MCP

Bladebro is installed from its pinned upstream release and driven in
real-browser mode against the desktop Chrome instances: its wrappers run
`chrome-ensure` first, then it attaches to the fixed DevTools port, never
launches or owns a browser, and applies no page
patches (`BLADE_LANE=real`). Self-updates are disabled; the binary is
updated through the desktop image.

MCP sessions run through `bladebro-gate`, which records each call's tool and
outcome (never arguments or page content) for the viewer in
`/config/agent-desktop/runs/state/` and refuses page-changing calls on a tab
whose run a person paused in the viewer (`runs/paused/<targetId>`): the
agent gets an error starting `paused:` and should wait. Reads still work.

Two server identities match the browser profiles:

| MCP server | Desktop command | Chrome |
| --- | --- | --- |
| `bladebro` | `bladebro-mcp-agent` | agent, port 9222 |
| `bladebro-personal` | `bladebro-mcp-personal` | personal, port 9223 |

Bladebro's five tools (`act`, `see`, `state`, `run`, `vision`) speak stdio
JSON-RPC. Coding agents in t3code reach them through the Ghostship MCP
browser tools (`browser_window`, `browser_op`, `browser_raw`), not as
separate MCP servers: a second copy of the browser tools only costs context.
`agent-desktop-mcp.service` writes the SSH wrappers above into `~/.local/bin`,
pins the desktop host key in `~/.ssh/known_hosts_agent_desktop` (published
to the Ghostship MCP by `ghostship-desktop-bridge`), and removes the direct
`bladebro`/`bladebro-personal` entries earlier versions merged into provider
configuration (backing up the previous file as `*.pre-bladebro`).

CLI usage over SSH (also useful for debugging):

```sh
ssh -i ~/.ssh/id_agent_desktop -p 2222 abc@10.89.7.2 bladebro-agent nav https://example.com
ssh -i ~/.ssh/id_agent_desktop -p 2222 abc@10.89.7.2 bladebro-agent see content
ssh -i ~/.ssh/id_agent_desktop -p 2222 abc@10.89.7.2 bladebro-personal -v
```

Multi-step flows must run in one invocation (`run @steps.json`, `act batch`)
or through the MCP session: one-shot CLI calls rebuild the page model and refs
from an earlier call are stale.

Diagnostics run inside the desktop container:

```sh
ssh -i ~/.ssh/id_agent_desktop -p 2222 abc@10.89.7.2 bladebro-agent doctor
ssh -i ~/.ssh/id_agent_desktop -p 2222 abc@10.89.7.2 bladebro-agent audit
```

For direct Playwright clients, tunnel the loopback DevTools port
(`ssh -L 9222:127.0.0.1:9222 ...`) and use `chromium.connect_over_cdp`.
Prefer Bladebro for routine agent work.

## Native GUI automation (Pelorus)

Use the managed `ghostship-gui` wrapper locally. It handles SSH application
launches internally and uses the canonical generated Pelorus CLI for API calls.

```sh
ghostship-gui windows
ghostship-gui launch -- xmessage 'Owned test window'
ghostship-gui explore --pid 1234
ghostship-gui screenshot --pid 1234
ghostship-gui batch --pid 1234 --actions '[{"action":"type","text":"hello"}]'
```

Batches hold the desktop input lock, confirm the target PID's focus before
each input, and stop on uncertain responses without replay. Only native
applications on this desktop share that lock; browser windows live in the
browser stages and never need it. Screenshots are private local PNGs,
and accessibility text is bounded. Ambiguous window targets fail before input.
Use Bladebro for browser workflows and this wrapper for native applications.

The image normalizes known Pixelflux control responses to Pelorus's required
`result` field. Backend errors remain errors; unknown responses fail explicitly.

## SSH and software installation

The host provisions an ed25519 keypair; the public key is in the desktop's
`authorized_keys` and the private key is `~/.ssh/id_agent_desktop` in t3code.
`sshd` reads the desktop session environment from `~/.ssh/environment`, so
every SSH command already has `DISPLAY`, `WAYLAND_DISPLAY` and the session
D-Bus address:

```sh
ssh -i ~/.ssh/id_agent_desktop -p 2222 abc@10.89.7.2
apt-get update && apt-get install -y <package>      # root needed for installs
ghostship-desktop-exec <command>                    # explicit env wrapper
```

Additional operator keys can be appended to
`/srv/apps/agent-desktop/config/agent-desktop/ssh/authorized_keys.local`
(managed keys are rewritten by `agent-desktop-ssh.service`).

## Human access

`desktop.ghostship.io` is a normal `ghostship.apps` entry: the tunnel route
and proxied CNAME are reconciled by `ghostship-cloudflare-sync`, and Access
uses the shared Google identity policy. Mouse, keyboard, clipboard and file
transfers are enabled; audio, webcam, gamepads and printing are off. The
desktop resizes to the client's screen, phones included; agent coordinates are
unaffected because agents work in the browser stages.

### Agent viewer

`https://desktop.ghostship.io/` is the viewer (nginx serves it at the root;
the old `/agents/` address redirects there) with a **Browsers | Desktop**
switch at the top. Desktop mode embeds Selkies, which lives at `/desktop/`
(`SUBFOLDER`), and leaving it ends the Selkies stream. Redirects are relative,
so they never expose nginx's internal port 3000. **+ Personal** and **+ Agent**
start an idle-stopped Chrome first.

The main page has one launcher, **Apps**, with a tile per `apps.json` entry:
Chrome · Personal and Chrome · Agent open a new browser window; OrcaSlicer and
Blender open the app, or show its running session. **Open** lists everything
running as live cards. **×** on a tab or card closes it at once: browser
windows close their tabs, and an app is asked to quit (every 2 s, so a dialog
cannot hold it) and stopped after 10 s, which discards unsaved work.

Browsers mode shows every agent
browser window as a card: label, identity, harness and model, T3 thread,
current action and a live preview. Tap a card for that agent's live view;
every open session is a tab along the top (× closes it, + opens a new window). Tap clicks, drag scrolls, the
keyboard button types, and the URL bar, tabs and back/reload work on that
window only. **Any touch pauses that agent** until you tap Resume; other
agents keep running. **New window** opens a person-owned window in either
identity, for example to sign in to a site from a phone.

### Desktop app sessions

Native apps in `apps.json` (OrcaSlicer and Blender) run in app sessions: each app on
its own headless Sway screen with its own pointer and keyboard, so input never
collides with the shared desktop, the browser stages or other sessions. The
`app-session` supervisor (s6 `svc-agent-desktop-apps`, as abc) opens, lists and
closes sessions through `/config/agent-desktop/runs/apps/control.sock`; each
session serves frames (grim, JPEG) and input (a virtual pointer, wtype for
keys) on its own socket and writes a run record (`kind: app`) the viewer shows
as a session tab. Agents use `ghostship-gui app` over SSH. A person's input
pauses agent input (`paused/<session>`; agent input marks
`busy/<session>` first). An agent's close only asks the app to quit, so it
never discards unsaved work without `--force`. Catalog apps are single-instance by default:
OrcaSlicer keeps one settings folder and cloud login, so `open` returns the
running session and refuses while Orca is open on the shared desktop.

GTK apps decode images through glycin, which sandboxes each loader with
bubblewrap; bwrap cannot mount inside this container, so sessions put
`nobwrap/bwrap` first on `PATH`, which reports unavailable namespaces and makes
glycin run its loaders unsandboxed. OrcaSlicer needs WebKitGTK 4.1, now part of
the image. App sessions run in the `desktop` AppArmor class.

The viewer (`viewer/server.py`, s6 `svc-agent-desktop-viewer`, 127.0.0.1:7090
behind the Selkies nginx) streams pages with DevTools screencasts and never
enables the Runtime domain. Every request must carry a valid Cloudflare Access
token (`Cf-Access-Jwt-Assertion`, verified against the team's signing keys and
the applications' AUD), so peers on the container network cannot use it. Before
a person's first input, the viewer waits for the agent's in-flight action to
finish (`runs/busy/<targetId>`, kept by the gate). It runs confined by the `ghostship-desktop-viewer`
AppArmor profile (`modules/self-hosted/agent-desktop-apparmor.profile`): it
can read its code and the run registry and write pause/state markers, nothing
else, and refuses to start unconfined. Browser UI outside the page (native
`<select>` popups, permission bubbles, password manager) is not in the stream.

### Touch input

The Selkies client supports touch devices directly: tap clicks, drag moves
the pointer, long-press is a right click, and a two-finger drag scrolls.
The side menu also offers **Trackpad Mode** and a **Keyboard Button** for
mobile. Chrome runs as a native Wayland client so compositor-injected wheel
events from those gestures reach the browser; if scrolling seems dead,
make sure the pointer is over the page (not the tab strip) and try toggling
Trackpad Mode in the side menu.

## Updates and rollback

- Pins live in `containers/agent-desktop/versions.json` (webtop digest,
  Chrome version and SHA-256s, Bladebro version and SHA-256s); the module
  passes them as build arguments and tags the image from the build context
  (`modules/self-hosted/agent-desktop-image-tag.nix`).
- `ghostship-agent-desktop-update` (daily 13:00) discovers updates: Chrome
  from Google's signed apt index, Bladebro from its release checksums, webtop
  by manifest digest, each after a 24 h soak and never downgraded. It builds
  the exact image a switch would deploy, gates it in lab canaries
  (concurrency, CDP detection, bot checks, fingerprint parity, profile
  compatibility on network-less snapshot copies), commits `versions.json` to
  main, drains active agent runs (30 min at most), snapshots `/srv`, deploys
  with `nixos-upgrade` and verifies production. A failed verification rolls
  back with a forward commit and restores the profiles from the snapshot when
  a newer Chrome opened them. Every outcome goes to NTFY.
- Manual runs: `ghostship-agent-desktop-update --discover-only`,
  `--dry-run`, `--components chrome,bladebro`, `--simulate-failure canary`.
- Stopping the container closes Chrome first (`chrome-stop-all` in the unit's
  pre-stop): Chrome writes recent cookies only on a normal shutdown.
- Chrome profiles, Bladebro state, SSH keys and downloads live under
  `/srv/apps/agent-desktop/config` and survive image updates. Chrome cache
  directories and the logs directory are excluded from Restic backups.

## Operations

```sh
systemctl status podman-agent-desktop.service agent-desktop-mcp.service
podman logs --tail 100 agent-desktop            # s6 + service logs
podman exec agent-desktop s6-rc -a list         # boot services; Chrome is on demand
podman inspect agent-desktop --format '{{.State.Health.Status}}'
podman exec -u 0 agent-desktop google-chrome-stable --version
podman exec -u 0 agent-desktop bladebro -v
```

Chrome starts with a fresh New Tab page after relaunch. Managed policy
`RestoreOnStartup=5` and the launcher omit session restoration; existing tabs
are not reopened. After stopping its profile, the launcher removes only tab/session
restoration files to cover unclean exits too. Cookies, credentials, history,
and site storage remain. This follows
the user's October 10 request and supersedes the earlier session-restoration
setting. The policy file is
`containers/agent-desktop/root/etc/opt/chrome/policies/managed/ghostship-desktop.json`.

Memory Saver discarding and background tab freezing are disabled so parallel
workers keep their page execution state. Background mode is disabled so closing
Chrome does not leave background apps running. These are supported Chrome
policies, not timing or throughput measurements. Inspect `chrome://policy` to
confirm the deployed browser accepts them before running workflow benchmarks.

Recovery: while an instance is wanted up, s6 relaunches Chrome after a crash;
the run script reaps stale processes and `Singleton*` locks for its profile
first, so unclean shutdowns recover automatically. If an instance is wedged,
`podman exec -u 0 agent-desktop pkill -f 'user-data-dir=.*/agent'` and s6
restarts it. `podman exec agent-desktop s6-svstat
/run/service/svc-agent-desktop-chrome-agent` shows whether an identity is up,
down after an idle stop, or never started.

## Known limits

- Bladebro's Linux ARM64 binary is cross-compiled upstream and not
  live-verified there; this deployment verifies it on Asahi.
- In real-browser attach mode the agent browses **as the signed-in
  identity**: actions are attributable to that account. Use `bladebro` for
  routine work and `bladebro-personal` only for personal sessions.
- The desktop container restarts when its image changes. In-flight tabs are
  lost; profile authentication survives. The update service drains active
  agent runs first (bounded wait).

## Browser realness checks

Every desktop change and update is checked without touching shops (retailers
can flag the shared egress address and accounts; Amazon has shown the agent
profile an "unauthorized AI agent" notice, so it is never automated):

- `tools/bench_fingerprint.py`: 40 browser signals (webdriver, client hints,
  screen/window, focus/visibility, WebGL/canvas/audio, media devices,
  permissions, fonts, media queries) must equal a known-good baseline.
- `tools/check_cdp_regression.py`: the local detector still sees
  `Runtime.enable`; Bladebro and minimal CDP stay clean.
- `tools/bench_botcheck.py`: deviceandbrowserinfo, bot.sannysoft and CreepJS,
  one load each through Bladebro, must report a human, non-headless browser.
- `tools/bench_input.py` and `tools/bench_bladebro.py`: concurrent agents with
  zero cross-talk and zero focus changes.

## Retailer compatibility (2026-10-08 baseline)

The desktop keeps the browser environment coherent so mainstream sites do
not flag it unnecessarily: the container timezone matches the egress
location, Chrome runs with its sandbox enabled, the GPU is passed through so
WebGL reports the real Apple GPU, audio hardware and emoji fonts are present,
and the CloakBrowser detection/fingerprint bookmark set is shipped as managed
Chrome bookmarks.

Measured on 2026-10-08:

- **Home Depot**: Bladebro's real-lane attach and the raw minimal CDP client
  both complete the journey (home → search → 13 extracted products → product
  page → reload). Playwright and any client that calls `Runtime.enable` are
  blocked; see [CDP detection testing](cdp-detection.md) for the isolation
  matrix and the per-site driver preference. The DevTools port can stay open
  as long as no Runtime-enabling client attaches.
- **Lowe's**: search and product pages load and `see extract auto` returns
  structured products.
- Third-party bot tests agree: without CDP, deviceandbrowserinfo reports
  "You are human", Fingerprint reports no bot/VM/proxy, and rebrowser shows
  no leaks; with CDP, the same browser is flagged.

For a site that challenges even clean CDP, a person takes over the agent's
window in the viewer. Never assume automated bypass works; record challenge
behaviour honestly.

## Driver policy

- **Bladebro real-lane attach is the default driver** for agents: it uses
  the on-demand Google Chrome instances (started by `chrome-ensure`), never launches replacement
  browsers, and does not call `Runtime.enable`, so bot-managed sites accept
  it (Home Depot, Lowe's, Amazon, Walmart and Target all validated).
- **Playwright stays optional** for compatible workflows; connect it over an
  SSH tunnel to the loopback DevTools port and avoid `Runtime.enable` on
  sites that detect it.
- **Pelorus and Selkies remain** for native GUI automation; the viewer is the
  manual path for browser windows.
- No fingerprint spoofing, extra browser framework, or custom orchestration
  layer is used; Chrome stays an ordinary desktop installation.


Agent Desktop has a 4,096-task bound and a 16 GiB memory bound. Linux task
counts include threads; parallel workers can exhaust the default 2,048-task
bound before memory fills. Apply a task-bound change to the existing container
with `podman update --pids-limit=4096 agent-desktop`, preserving its container
identity and the active T3 session. Check `pids.current` and `pids.events` in the
desktop cgroup when validating parallel workloads.
