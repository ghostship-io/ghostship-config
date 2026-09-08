# ChatGPT Linux container design

Research date: 2026-09-07. Target: chill-penguin (ARM64), a full Nix development
workstation with web-native app controls. Android device work is excluded.

## Decision

Port the previous `codex-desktop-web` adapter and Nix/systemd workstation to the
official Linux package. Serve the upstream renderer as HTML/CSS/JavaScript and
relay Electron IPC to its official native runtime. Keep the browser adapter at
the preload, main-process and gateway boundaries, without substitutions inside
minified renderer bundles. Use browser-native dialogs for filesystem operations.

The Linux runtime forces a sandboxed preload. Its relay therefore uses private
Electron IPC to a main-process WebSocket rather than loading Node dependencies
inside the preload. The browser cannot invoke those private relay channels.
Binary values must survive both directions of the WebSocket transport.

Preserve the official custom runtime and Linux native modules; substituting a
stock Electron runtime could remove capabilities supplied by OpenAI's build.
Nix patches ELF interpreter/library paths, supplies dependencies, and builds an
OCI image with an independent persistent Nix store, Docker daemon and systemd.

## Updates

Authenticate InRelease with OpenAI's pinned public key, verify the package index
hash and downloaded package hash, then build a separate candidate. Check the
preload contract and start the candidate with an empty profile before activation.
Retain the previous generation and restore it if live startup health fails.

Keep transport release identity separate from app version. Browser assets use
network fetches rather than retaining a stale app shell after an upgrade, and
WebSocket reconnects reload a page whose transport generation has changed.
Unknown future API changes can still need adapter changes; automated smoke
checks are an acceptance gate, not proof of every authenticated feature.

## Primary evidence

- [Official Linux installation](https://learn.chatgpt.com/docs/linux/linux-app):
  Linux preview packages include ARM64. Native desktop Computer Use is excluded.
- [Official ARM64 package index](https://persistent.oaistatic.com/codex-app-prod/linux/deb/dists/stable/main/binary-arm64/Packages):
  version 26.901.51231; package SHA256
  `02a2f5c6cb69509c62abcbdd13c76b139cdb2ca9edde7537239ddde024077ea0`.
- [Electron IPC](https://www.electronjs.org/docs/latest/tutorial/ipc):
  structured messages connect renderer and main processes; native objects need
  explicit lifecycle adapters across the browser transport.
- [Integrated terminal](https://learn.chatgpt.com/docs/integrated-terminal) and
  [browser](https://learn.chatgpt.com/docs/browser): these are app capabilities
  requiring live interaction checks, beyond a successful gateway response.
- [Remote connections](https://learn.chatgpt.com/docs/remote-connections): official
  remote hosts have platform restrictions; this web adapter is a separate path.

All active controls must be visible or reachable without clipping. Mutually
exclusive menus cannot all be displayed simultaneously. Test the actual deployed
renderer, file-picker round trips, account-dependent tasks and small browser
viewports; a healthy native relay alone is insufficient acceptance.
