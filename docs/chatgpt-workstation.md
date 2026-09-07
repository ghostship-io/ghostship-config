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
keyboard do not push the composer below the screen. The inner zoomed app frame
also follows the visual viewport in portrait and touch-phone landscape, and
mobile home suggestions do not retain the
desktop negative margin that overlaps project headings. Chrome can install the
same-origin web app using its install action or the app's installation prompt.
The manifest fetch includes credentials so installation works behind the
existing Cloudflare Access login.
Project changes invalidate upstream state in place in every connected browser,
preserving the current conversation and unsent draft instead of reloading tabs.
Each tab has distinct native transport channels, including tabs sharing the
same browser profile. Saved projects, chat history, live replies, pins, and
upstream persisted state are shared. Drafts survive transport reconnects.
Request replies go only to the requesting tab; shared events still fan out.
The window adapter preserves Electron's `BrowserWindow` constructor name so
native window enumeration includes the application in state broadcasts.
The relay acknowledges native chunks itself, so a stalled hidden renderer cannot
block later state updates. It forwards complete
messages. Project updates refresh only the sidebar snapshot. Large HTTP and
WebSocket payloads use compression to reduce startup traffic on slower links.

On another device, an upstream login callback may still target localhost on
port 1455 or 1457. Replace the failed callback URL's host with this app's host,
keeping `/auth/callback` and its query string, to reach the pending listener.
Do not share the callback URL: it contains login state.

## Notifications and microphone

Enable notifications on each browser/device using the app's permission offer.
Completion alerts use both the live connection and encrypted Web Push, with a
shared upstream notification tag to avoid duplicate entries. Task routes are
matched at the native notification boundary; ambiguous shared-title alerts open
the app rather than selecting the wrong task. Push can wake the service
worker without an open app tab; clicking an alert focuses an existing tab or
opens the app at the task route, which survives runtime upgrades. Background
alerts open the task for its current approval controls instead of retaining
process-local action callbacks. Browser/OS notification settings and background restrictions
still control delivery. A failed push registration displays a retry action.
Subscriptions and VAPID keys persist in `~/.local/state/codex-web/push.json`;
include that private file in home backups. Push sends only to supported browser
vendor endpoints and removes expired subscriptions.

Use the public HTTPS address for microphone access. The Dictate control records
from the current device and inserts the returned transcript in its composer;
grant microphone permission separately on each device. Local acceptance uses
`espeak-ng` and Chrome's fake audio capture to test recording and transcription
without accessing the operator's microphone. The separate live Voice mode still
uses audio devices in the hidden native avatar window and is not bridged to the
client microphone; dictation is the verified browser voice-input path. Physical audio devices and OS
permission prompts require their own device check.

## OpenChamber migration

The September 7 migration copied `ghostship-agent`, `ghostship-newsletter`,
`ghostship-roms`, `OneConfig` and `nixos-config` into `/workspace`, retaining Git
metadata and uncommitted/untracked files. These are independent copies; later
filesystem edits in OpenChamber do not mirror into Codex. All Codex browser
sessions use the same copied repositories and project registrations.

Git identity, templates/hooks, SSH keys/config and GitHub CLI settings were
copied into `/home/codex`, with home paths adjusted. The imported Nix profile's
closure is registered in Codex's own store and rooted under
`~/.local/state/codex-imports/openchamber-profile`. Its tools are available through
`~/.nix-profile`; `~/tools` points to `/workspace/ghostship-agent/tools`.
OpenChamber-specific maintenance jobs were not enabled in Codex.
The protected migration backup is
`/srv/apps/chatgpt/migration-openchamber-20260907T085424Z` on the host.

## Updates and recovery

`codex-tool-auto-update.service` checks OpenAI's signed Linux repository every
15 minutes. The pinned OpenAI public key verifies InRelease, which authenticates
the package index and package checksum. A candidate is built against this repo's
pinned Nix package set, with the official runtime and Linux native modules.
Missing required preload channels fail preparation. An isolated empty-profile
startup must connect the native relay before a candidate is queued.

`codex-tool-update-restart.service` waits for idle tasks and 15 minutes without
input in every connected browser. Open terminals, active microphone/camera
tracks, pending dialogs and clients that have not reported presence block
activation. Idle open tabs can remain connected and reload after the update;
closing all tabs also allows a queued update to apply. Image deployment applies matching-version
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
