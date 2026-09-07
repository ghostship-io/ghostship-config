# ChatGPT workstation

Open <https://codex.ghostship.io> through the existing Cloudflare Access policy.
The upstream app renderer runs in your browser. Browser tabs share one native
app host and persistent app-server; closing a tab leaves tasks running.

## Development and persistence

The container is `codex`; its user is `codex`, UID/GID `3000:3000`. Use
`/workspace` for projects and per-project Nix flakes for dependencies:

```sh
cd /workspace/my-project
nix develop -c <project-command>
```

Nix uses a separate writable store and daemon. Docker connects to the container's
own daemon. `/mnt/share` provides the existing NAS mount. Host storage is:

| Host directory under `/srv/apps/chatgpt` | Container path |
| --- | --- |
| `home` | `/home/codex` |
| `workspace` | `/workspace` |
| `docker` | `/var/lib/docker` |
| `nix-root/nix` | `/nix` |

Use `~/.config/systemd/user/*.service` for persistent development servers, then
`systemctl --user daemon-reload` and `systemctl --user enable --now NAME.service`.
Cloudflared is available for project tunnels. No project port is automatically
published on the host. The internal protected origin is `http://codex:8214`.

Protect home backups: they include app credentials and the private unattended
keyring unlock key. Stop services for consistent snapshots. The workstation is
privileged for nested Docker and Nix; retain the existing protected ingress.

## Web controls

The adapter serves upstream HTML/CSS/JavaScript and transports Electron IPC
through a same-origin WebSocket. Container file pickers appear inside the app's
modal so selecting a directory does not dismiss the parent dialog, and use the
browser top layer to escape clipping by the project picker's dialog. Clipboard,
file uploads, notifications and fullscreen use browser APIs where available.
Native secondary windows and embedded browser content use dedicated surfaces;
the main application remains an ordinary browser DOM.
Project actions remain visible without hovering. The adapter selects upstream
web menus instead of native OS popups, and reconnects from fresh application
state rather than replaying stale responses and partial chunk streams. Bundled
plugins remain sealed in the Nix store; their runtime copies are writable so
upstream can apply Linux-specific plugin variants.
Desktop launch overrides are applied to each app-server thread so its tool-server
transport and credentials survive the persistent server connection.
On narrow screens the sidebar is a drawer and closes after selecting a chat.
The layout tracks the visible viewport so browser chrome and the software
keyboard do not push the composer below the screen. Chrome can install the
same-origin web app using its install action or the app's installation prompt.
Project changes invalidate upstream state in place in every connected browser,
preserving the current conversation and unsent draft instead of reloading tabs.
Each tab has distinct native transport channels, including tabs sharing the
same browser profile. Saved projects, chat history, live replies, and pins are
shared; each tab keeps its own draft and navigation.

On another device, an upstream login callback may still target localhost on
port 1455 or 1457. Replace the failed callback URL's host with this app's host,
keeping `/auth/callback` and its query string, to reach the pending listener.
Do not share the callback URL: it contains login state.

## Updates and recovery

`codex-tool-auto-update.service` checks OpenAI's signed Linux repository every
four hours. The pinned OpenAI public key verifies InRelease, which authenticates
the package index and package checksum. A candidate is built against this repo's
pinned Nix package set, with the official runtime and Linux native modules.
Missing required preload channels fail preparation. An isolated empty-profile
startup must connect the native relay before a candidate is queued.

`codex-tool-update-restart.service` waits for idle tasks and no connected browser
tabs before activation, protecting drafts and sign-in flows. Closing all app tabs
allows a queued update to apply. Image deployment applies matching-version
transport fixes at startup while preserving newer automatically installed releases.
Failed service starts or health checks restore the previous generation. Health
requires a recent heartbeat from the native renderer, including after a crash.
Application package rollback
does not reverse upstream profile migrations. No compatibility test guarantees
that every feature of an unknown future release will work: account-dependent
features and significant upstream API changes require live acceptance.
Successful activation removes older downloaded generation links, retaining the
current release and its rollback target so obsolete packages can be garbage-collected.

Current and last-good generations are under `~/.local/share/codex-tools`.
Logs are under `~/.codex-container/logs`. Operators can inspect:

```sh
podman exec codex systemctl status codex-web.service codex-app-server.service --no-pager
podman exec codex curl -fsS http://127.0.0.1:8214/health
podman exec codex systemctl start codex-tool-auto-update.service
podman exec codex systemctl start codex-tool-update-restart.service
```

Host deployment uses the NixOS OCI module in `modules/self-hosted/codex.nix`.
This image is built with Nix dockerTools and run by Podman, consistent with the
other development workstations. There is no separate divergent Dockerfile.

## Verification

```sh
nix develop -c npm --prefix packages/codex-desktop-web ci --ignore-scripts
nix develop -c npm --prefix packages/codex-desktop-web test
nix develop -c npm --prefix packages/codex-desktop-web run test:browser
```

Browser fixtures check binary IPC and modal interactions. Live acceptance must
also inspect the deployed app, menus, inputs, terminal and embedded browser.
Account-dependent tasks require a signed-in profile. Native desktop Computer Use
is unavailable in the official Linux preview. Mobile acceptance includes Chrome
emulation, narrow and short viewports, and installation eligibility; physical
Android installation must be distinguished from browser emulation.
