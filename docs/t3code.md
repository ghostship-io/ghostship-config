# T3 Code

T3 Code runs at `https://t3code.ghostship.io` on `chill-penguin`. The repo builds
`localhost/ghostship-t3code:t3code-runtime`, using OpenChamber's container
platform: systemd, UID/GID 3000, persistent user services, nested Docker, Nix,
build tools, Git/GitHub CLI, and Cloudflared Quick Tunnels. The web server listens
on `t3code:3773` inside `ghostship_net`; no host ports are published.

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

## Pair and sign in

From the host, issue a one-hour remote-browser pairing link:

```sh
podman exec --user 3000:3000 t3code /home/t3code/.local/bin/t3code-pair
```

Open that link, then use **Settings > Providers**:

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

The ACP runtime is pinned to Google's `1.1.1` Linux x64 release with SHA-256
verification. It runs natively on x64 and through container-local QEMU on ARM64:
Google's ARM binary aborts during initialization on Asahi's 16 KB memory pages,
whereas the x86 emulator supplies the required 4 KB guest pages. Both the ACP
agent and its helper use the wrapper. Emulation adds startup and execution
overhead; account sign-in and authenticated model requests still need live
verification with the user's account.
Update `packages/t3code/antigravity-acp.nix`, rebuild the host,
and restart the T3 container when changing that runtime. T3's Antigravity binary
path is `/bin/agy_acp_server.par`, so future image updates retain a stable path.

Upstream: [provider setup](https://github.com/pingdotgg/t3code/blob/main/docs/user/install.md),
[Antigravity sign-in](https://github.com/pingdotgg/t3code/blob/main/docs/user/providers-antigravity.md),
and [official ACP registry](https://github.com/agentclientprotocol/registry/tree/main/antigravity-acp).

## Maintenance

The four-hour tool timer updates T3, Codex, and OpenCode when the database reports
no pending or running turns. Unknown activity defers maintenance and recovery.
The ACP runtime updates only with the image. Container health checks web/server
availability; provider authentication failures do not trigger restart loops.

`t3code-apply-config` validates JSON/TOML and OpenCode configuration, restarts the
server, and restores the last healthy configuration snapshot if recovery fails.
`t3code-tunnel start <name> <port>` exposes a project server with an ephemeral
Cloudflare Quick Tunnel. Container lifecycle hooks live in
`~/.t3code-container/hooks/{bootstrap.d,before-t3code.d,doctor.d}`; bootstrap hooks
run before the first web-server start.

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
