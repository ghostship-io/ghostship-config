# Agent desktop

`desktop.ghostship.io` is a persistent Linux GUI workstation in a Podman
container on `chill-penguin`, built for agent automation and live human
intervention. It runs LXQt on a labwc Wayland session with Selkies 2
streaming, Pelorus desktop control (AT-SPI + Pixelflux), and Camoufox
browsers owned by supervised s6 services.

Everything is defined in `modules/self-hosted/agent-desktop.nix` and
`containers/agent-desktop/`. The desktop lifecycle is independent of t3code:
it starts at boot, keeps its browsers across t3code restarts, and can be
updated without touching the T3 Code container.

## Endpoints

The t3code container joins the private `agent_desktop_net` and reads these
environment values (with the token from the `agent-desktop` secret):

| Variable | Value | Purpose |
| --- | --- | --- |
| `AGENT_DESKTOP_API_URL` | `http://10.89.7.2:7080` | Authenticated automation proxy |
| `AGENT_DESKTOP_API_TOKEN` | secret | Bearer token for the proxy |
| `AGENT_DESKTOP_PELORUS_URL` | `http://10.89.7.2:7080/pelorus` | Pelorus REST base |
| `AGENT_DESKTOP_PLAYWRIGHT_BASE` | `ws://10.89.7.2:7080/playwright` | Browser endpoints, `<base>/<profile>` |
| `AGENT_DESKTOP_SSH_HOST` | `10.89.7.2` | Desktop SSH host |
| `AGENT_DESKTOP_SSH_PORT` | `2222` | Desktop SSH port |
| `AGENT_DESKTOP_SSH_USER` | `abc` | Desktop SSH user |
| `AGENT_DESKTOP_SSH_KEY` | `~/.ssh/id_agent_desktop` | Provisioned automation key |

The web client is reachable at `https://desktop.ghostship.io` behind
Cloudflare Access, or `http://agent-desktop:3000` on `ghostship_net`. Pelorus
agent/LLM routes, Pixelflux's raw port 5000 and the manager port 7999 are
never proxied.

## Native GUI automation (Pelorus)

The proxy forwards only the desktop-control surface; use `httpx` directly.

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

Pelorus returns the AT-SPI tree with screen-absolute coordinates for every
element. When an application has no accessibility tree, explore returns a
window screenshot instead, and control always accepts screen coordinates.

## Camoufox browsers

`browser_owner.py` supervises headed Camoufox instances on the desktop:

| Id | Lifecycle | Auth state |
| --- | --- | --- |
| `agent` | persistent, port 7901 | `/config/agent-desktop/profiles/agent.state.json` |
| `personal` | persistent, port 7902 | `/config/agent-desktop/profiles/personal.state.json` |
| `temp-<id>` | on demand | isolated (optionally seeded from a profile) |

Clients connect with native Playwright and share the instance's single
context; each client opens its own tabs. `Browser.bind()` endpoints cannot
serve a Playwright persistent context (upstream limitation), so persistent
authentication is restored from `storage_state` (cookies and localStorage),
which the owner saves every two minutes and on shutdown.

```python
import json
import os
import urllib.request
from playwright.sync_api import sync_playwright

base = os.environ["AGENT_DESKTOP_PLAYWRIGHT_BASE"]
headers = {"Authorization": f"Bearer {os.environ['AGENT_DESKTOP_API_TOKEN']}"}

with sync_playwright() as p:
    browser = p.firefox.connect(f"{base}/agent", headers=headers)
    context = browser.contexts[0]
    page = context.new_page()
    page.goto("https://example.com")
    # ... work ...
    page.close()          # close task-owned tabs
    # do not call browser.close(); the owner keeps the browser alive
```

Manage instances through the same proxy:

```python
import os, urllib.request, json
api = os.environ["AGENT_DESKTOP_API_URL"]
headers = {"Authorization": f"Bearer {os.environ['AGENT_DESKTOP_API_TOKEN']}", "Content-Type": "application/json"}

def request(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(api + path, data=data, method=method, headers=headers)
    return json.loads(urllib.request.urlopen(req).read() or b"{}")

request("GET", "/browsers")                                    # list + page counts
temp = request("POST", "/browsers", {"seed_profile": "agent"}) # isolated instance
# connect to f"{base}/{temp['id']}"
request("DELETE", f"/browsers/{temp['id']}")                   # shut it down
```

The owner closes unpinned tabs idle for 24 hours and shuts down idle
temporary instances after 4 hours. Pin a long-lived tab with
`page.evaluate("window.name = 'ghostship:pin'")`.

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
transfers are enabled; audio, webcam, gamepads and printing are off. A human
can log into a service in the `personal` browser and the agent can keep
using the same instance.

## Updates and rollback

- The image is built on the host from `containers/agent-desktop/` with a
  content-addressed tag; changing the sources rebuilds and restarts only
  `podman-agent-desktop.service`.
- The base image is pinned by digest in the Containerfile. Refresh the digest
  and the Camoufox/Playwright pins together; Camoufox currently requires
  `playwright<1.63` and `Browser.bind()` needs `>=1.59`.
- Profiles, SSH keys, downloads and the fetched Camoufox browser live under
  `/srv/apps/agent-desktop/config` and survive image updates. The browser
  cache is excluded from Restic backups (regenerated on demand), while
  `profiles/*.state.json` are backed up.

## Operations

```sh
systemctl status podman-agent-desktop.service
podman logs --tail 100 agent-desktop            # s6 + service logs
podman exec agent-desktop s6-rc -a list         # svc-agent-desktop-* services
podman inspect agent-desktop --format '{{.State.Health.Status}}'
systemctl start podman-agent-desktop.service    # recover the container
```

Owner recovery: if the browser owner dies, s6 restarts it and both instances
relaunch from their saved state. To force a fresh browser download, remove
`/srv/apps/agent-desktop/config/.cache/camoufox` and restart the service.

## Known limits

- Playwright cannot serve a persistent context over `bind()`; persistence is
  `storage_state` plus owner-managed processes, not a live shared profile.
- Clients that share an instance share its context; a client that calls
  `browser.close()` affects other clients. Close pages, not the browser.
- The desktop container restarts when its image changes. In-flight tabs are
  lost; saved authentication survives. Avoid updates during long agent runs.
- Pelorus is loopback-only inside the container; never publish ports 5100 or
  5000 on a shared network.
