# ChatGPT Desktop Web

Serve the official Linux app's renderer directly in a browser. The official
preload runs against a browser Electron shim; its real native counterpart and
main process run in OpenAI's bundled Linux runtime. WebSocket IPC connects them.
The main app uses ordinary HTML controls. Native file dialogs become browser
pickers; secondary windows and embedded browser guests have lifecycle adapters.

The Nix/systemd OCI workstation is defined in `modules/self-hosted/codex.nix`.
See [the workstation guide](../../docs/chatgpt-workstation.md) for deployment,
persistent storage, development services, authentication and update operations.
The image is built with Nix dockerTools; this package has no separate Dockerfile.

## Release preparation

Release descriptors under `releases/` bind the official Linux package URL and
checksum. `discover-linux-release.mjs` authenticates OpenAI's repository using
the pinned public key. `prepare-linux.mjs` extracts the package, preserves its
native runtime and Linux modules, checks required preload channels, and installs
the transport. Nix resolves the runtime's ELF dependencies.

```sh
nix develop -c npm --prefix packages/codex-desktop-web ci --ignore-scripts
nix develop -c npm --prefix packages/codex-desktop-web test
nix develop -c npm --prefix packages/codex-desktop-web run test:browser
```

Automatic candidates also run `scripts/smoke-prepared.sh` with an isolated home
before being queued for an idle restart. A failed live health check restores the
previous generation. Renderer assets use network fetches, and the transport
identity forces reload after a changed generation. Unknown upstream changes may
still require new adapters and authenticated browser acceptance.

## Browser acceptance

The fixture suite exercises binary IPC, file-picker modal containment, secondary
window lifecycle, fullscreen and the install prompt. It does not prove Android
installation or authenticated app features.

`tests/live-acceptance.mjs` and `tests/live-ui-surface.mjs` contain the earlier
renderer acceptance scenarios. When updating upstream, inspect the real UI and
refresh any changed labels before using these suites as release evidence.
