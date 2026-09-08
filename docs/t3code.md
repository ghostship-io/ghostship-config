# T3 Code

T3 Code runs at `https://t3code.ghostship.io` on `chill-penguin`. The repo builds
`localhost/ghostship-t3code:t3code-runtime`, using OpenChamber's container
platform: systemd, UID/GID 3000, persistent user services, nested Docker, Nix,
build tools, Git/GitHub CLI, and Cloudflared Quick Tunnels. The access gateway
listens on `t3code:3773` inside `ghostship_net`; the T3 backend listens only on
container loopback port `3774`. No host ports are published.

## Projects and state

The container user is `t3code`, with home `/home/t3code`. Host state lives in
`/srv/apps/t3code/{home,workspace,docker,nix-root}`. At container startup each
missing top-level OpenChamber project is copied to the new workspace, including
Git history and uncommitted files. Copies use filesystem reflinks when available
and publish only after copying completes. Existing destinations are never
overwritten or synchronized. Project registration uses T3's native CLI.

The initial project set is `ghostship-agent`, `ghostship-newsletter`,
`ghostship-roms`, `nixos-config`, and `OneConfig`. Stop editing a source project
while its initial copy runs if you need a consistent multi-file snapshot.
Git `result` links and build caches can refer to the source container's store;
rebuild them through each project's Nix flake in T3's independent store.

Provider sessions, credentials, and OpenChamber's scheduled automation are
separate from these project copies. Project-owned services can be installed in
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

The image includes Google's `1.1.1` Linux x64 ACP release with SHA-256
verification as a fallback. It runs natively on x64 and through container-local QEMU on ARM64:
Google's ARM binary aborts during initialization on Asahi's 16 KB memory pages,
whereas the x86 emulator supplies the required 4 KB guest pages. Both the ACP
agent and its helper use the wrapper. Emulation adds startup and execution
overhead; account sign-in and authenticated model requests still need live
verification with the user's account.
The automatic updater reads the official ACP registry and accepts only the
corresponding Linux x64 archive URL at `dl.google.com`. It records the downloaded
archive's SHA-256, stages the server and helper together, and checks ACP
initialization offline before atomically switching the persistent `current`
link. A failed download or protocol check keeps the previous release. Releases
live under `~/.local/share/t3code-tools/antigravity`; both wrappers continue to
use QEMU on ARM64. T3's binary path stays `/bin/agy_acp_server.par` across updates.

Upstream: [provider setup](https://github.com/pingdotgg/t3code/blob/main/docs/user/install.md),
[Antigravity sign-in](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-antigravity.md),
and [official ACP registry](https://github.com/agentclientprotocol/registry/tree/main/antigravity-acp).

## Maintenance

Deploy with `nixos-rebuild switch --flake .#chill-penguin -L` on the host after
pulling the committed configuration. This updates the system profile and boot
entry as well as the running system. Running a built system's
`switch-to-configuration switch` directly does not advance the system profile;
reboot can therefore return to a generation without T3 Code.

The four-hour tool timer updates T3, Codex, OpenCode, and Antigravity when the
database reports no pending or running turns, then runs `after-update.d` to
reapply Ghostship tooling. Unknown activity defers maintenance and recovery.
Each provider update is attempted even if another fails. Changed tools or the
Ghostship tool package queue a server restart, which waits for T3 to become idle.
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
home and projects but exclude the Docker and Nix stores, as for OpenChamber.

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
