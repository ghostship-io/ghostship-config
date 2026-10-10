# Agent desktop

`desktop.ghostship.io` is a persistent Linux GUI workstation in a Podman
container on `chill-penguin`, built for agent automation and live human
intervention. It runs LXQt on a labwc Wayland session with Selkies 2
streaming, Pelorus desktop control (AT-SPI + Pixelflux), pinned Google Chrome
browsers, and Bladebro as the MCP browser driver.

Everything is defined in `modules/self-hosted/agent-desktop.nix` and
`containers/agent-desktop/`. The desktop lifecycle is independent of t3code:
it starts at boot, keeps its browsers across t3code restarts, and can be
updated without touching the T3 Code container.

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

Two persistent Chrome instances run under independent s6 services, launched
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
profile, a loopback DevTools port, native Wayland so compositor input
injection reaches the browser, first-run/crash UX suppression, the basic
password store, the US locale and a 1600x900 window. No sandbox, GPU or
fingerprint flags.

Never open one profile directory in two browser processes.

## Bladebro MCP

Bladebro is installed from its pinned upstream release and driven in
real-browser mode against the existing Chrome instances: it attaches to the
fixed DevTools port, never launches or owns a browser, and applies no page
patches (`BLADE_LANE=real`). Self-updates are disabled; the binary is
updated through the desktop image.

Two server identities match the browser profiles:

| MCP server | Desktop command | Chrome |
| --- | --- | --- |
| `bladebro` | `bladebro-mcp-agent` | agent, port 9222 |
| `bladebro-personal` | `bladebro-mcp-personal` | personal, port 9223 |

Bladebro's five tools (`act`, `see`, `state`, `run`, `vision`) are exposed
to agents over stdio JSON-RPC. MCP clients in t3code are provisioned
automatically by `agent-desktop-mcp.service`: it writes SSH wrappers into
`~/.local/bin`, pins the desktop host key in
`~/.ssh/known_hosts_agent_desktop`, and merges the server entries into
OpenCode and Codex configuration (backing up the previous file as
`*.pre-bladebro`). A new provider session picks them up; no manual SSH or
connection management is needed.

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

Pelorus is unchanged; the proxy forwards only the desktop-control surface.
Use `httpx` directly.

```python
import os
import httpx

base = os.environ["AGENT_DESKTOP_API_URL"]
headers = {"Authorization": f"Bearer {os.environ['AGENT_DESKTOP_API_TOKEN']}"}
client = httpx.Client(base_url=base, headers=headers, timeout=120)

state = client.get("/pelorus/api/state").json()          # text desktop state
windows = client.get("/pelorus/api/windows").json()      # geometry per window
tree = client.get(f"/pelorus/api/desktop/explore/{pid}").json()
png = client.get("/pelorus/api/desktop/screenshot").json()["data"]
client.post("/pelorus/api/desktop/control", json={"action": "left_click", "coordinate": [640, 400]})
client.post("/pelorus/api/desktop/control", json={"action": "type", "text": "hello"})
client.post(f"/pelorus/api/desktop/close/{pid}")          # close a window
```

Use Bladebro for browser operations and Pelorus for other graphical Linux
applications: install/launch utilities over SSH, inspect controls with
`/api/desktop/explore`, interact with `control`, and fall back to
screenshots when an application has no accessibility tree.

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
transfers are enabled; audio, webcam, gamepads and printing are off.

### Touch input

The Selkies client supports touch devices directly: tap clicks, drag moves
the pointer, long-press is a right click, and a two-finger drag scrolls.
The side menu also offers **Trackpad Mode** and a **Keyboard Button** for
mobile. Chrome runs as a native Wayland client so compositor-injected wheel
events from those gestures reach the browser; if scrolling seems dead,
make sure the pointer is over the page (not the tab strip) and try toggling
Trackpad Mode in the side menu.

## Updates and rollback

- The image is built on the host from `containers/agent-desktop/` with a
  content-addressed tag; changing the sources rebuilds and restarts only
  `podman-agent-desktop.service`.
- Google Chrome and Bladebro are pinned by version and SHA-256 in the
  Containerfile; the base image is pinned by digest. Refresh all three
  together and update the checksums from the vendors' release metadata.
  Roll back by rebuilding the previous revision of this directory.
- Chrome profiles, Bladebro state, SSH keys and downloads live under
  `/srv/apps/agent-desktop/config` and survive image updates. Chrome cache
  directories and the logs directory are excluded from Restic backups.

## Operations

```sh
systemctl status podman-agent-desktop.service agent-desktop-mcp.service
podman logs --tail 100 agent-desktop            # s6 + service logs
podman exec agent-desktop s6-rc -a list         # svc-agent-desktop-* services
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

Recovery: the s6 services relaunch Chrome after a crash; the run script
reaps stale processes and `Singleton*` locks for its profile first, so
unclean shutdowns recover automatically. If an instance is wedged,
`podman exec -u 0 agent-desktop pkill -f 'user-data-dir=.*/agent'` and s6
restarts it.

## Known limits

- Bladebro's Linux ARM64 binary is cross-compiled upstream and not
  live-verified there; this deployment verifies it on Asahi.
- In real-browser attach mode the agent browses **as the signed-in
  identity**: actions are attributable to that account. Use `bladebro` for
  routine work and `bladebro-personal` only for personal sessions.
- The desktop container restarts when its image changes. In-flight tabs are
  lost; profile authentication survives. Avoid updates during long runs.

## Retailer compatibility

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

For bot-managed sites, drive Chrome through Selkies (manual) or Pelorus
compositor input (agents) instead of Bladebro's CDP session. Never assume
automated bypass works; record challenge behaviour honestly.

## Driver policy

- **Bladebro real-lane attach is the default driver** for agents: it uses
  the persistent Google Chrome instances, never launches replacement
  browsers, and does not call `Runtime.enable`, so bot-managed sites accept
  it (Home Depot, Lowe's, Amazon, Walmart and Target all validated).
- **Playwright stays optional** for compatible workflows; connect it over an
  SSH tunnel to the loopback DevTools port and avoid `Runtime.enable` on
  sites that detect it.
- **Pelorus and Selkies remain** for native GUI automation and for sites
  where even clean CDP is challenged.
- No fingerprint spoofing, extra browser framework, or custom orchestration
  layer is used; Chrome stays an ordinary desktop installation.


Agent Desktop has a 4,096-task bound and a 16 GiB memory bound. Linux task
counts include threads; parallel workers can exhaust the default 2,048-task
bound before memory fills. Apply a task-bound change to the existing container
with `podman update --pids-limit=4096 agent-desktop`, preserving its container
identity and the active T3 session. Check `pids.current` and `pids.events` in the
desktop cgroup when validating parallel workloads.
