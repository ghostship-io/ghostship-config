# Codex Desktop Web

This package serves the unmodified renderer from the official ChatGPT desktop
application in a browser. The official preload is rebuilt against a WebSocket
Electron transport, while the official main process runs on the matching Linux
Electron runtime.

The gateway multiplexes every browser onto one native app host. IPC events,
app-server MessagePorts, terminal state, and task updates are fanned out to all
connected devices. Native file dialogs become a container-side picker confined
to `CODEX_WEB_FILE_ROOTS`, which defaults to `/workspace,/home/codex`.

## Supported releases

Release descriptors live under `releases/`. Each descriptor binds the desktop
artifact, Electron runtime, Codex CLI, signatures, hashes, and compatibility
family. `latest-compatible` updates can reuse a family when the generated
preload and IPC contract remains compatible.

## Local Docker build

```sh
docker build -t ghostship-codex-desktop-web .
docker run --rm -p 8214:8214 \
  -v codex-home:/home/codex \
  -v codex-workspace:/workspace \
  ghostship-codex-desktop-web
```

Open `http://localhost:8214`. The image keeps the upstream renderer assets
unchanged and adds only the browser transport, PWA metadata, Linux runtime
adapters, and persistent storage mounts.

For a fresh CLI login, the upstream callback listener still binds to loopback
ports 1455 or 1457. If authentication occurs on another device, replace the
failed callback URL's host with the Codex web app host while preserving
`/auth/callback` and its query string; the gateway forwards it to the pending
desktop listener.

## Adding a desktop release

1. Add a signed release descriptor under `releases/`.
2. Run `npm run build:release -- --release VERSION`.
3. Run `npm run test:contract`.
4. Run the browser, multi-device, terminal, and PWA tests.
5. Add the version to `releases/supported.json` only after all checks pass.

A missing required preload channel or mismatched Electron version fails the
candidate build without modifying the active generation.
