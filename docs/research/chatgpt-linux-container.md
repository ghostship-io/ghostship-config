# ChatGPT Linux container design

Research date: 2026-09-07. Target: chill-penguin (ARM64), desktop browsers and
web controls and inputs. Android device/emulator work was explicitly excluded. This replaces the retired macOS-derived Codex web
bridge with the official Linux desktop application.

## Decision

Run the complete official app in a Debian 13 X11 desktop and stream the whole
session with Selkies. Keep the mobile/PWA shell outside application files.
Full-session capture preserves native menus, dialogs and browser windows. A
private Electron IPC bridge must reimplement native objects and track upstream
changes; the existing bridge also rebuilt native modules and patched platform
assumptions. Those are avoidable upgrade dependencies.

Pin the streaming base by digest and test its updates separately. Use OpenAI's
signed apt channel for application updates, preserve the profile and workspace,
and retain a working package for recovery. Future upstream compatibility is
verified, never assumed.

## Evidence

- [Official Linux installation](https://learn.chatgpt.com/docs/linux/linux-app):
  Debian 13 and ARM64 are supported; installer supplies signed apt repository;
  native Wayland is experimental. X11 avoids documented focus/window problems.
- [Live ARM64 package index](https://persistent.oaistatic.com/codex-app-prod/linux/deb/dists/stable/main/binary-arm64/Packages):
  version 26.901.51231, package SHA256
  `02a2f5c6cb69509c62abcbdd13c76b139cdb2ca9edde7537239ddde024077ea0`.
- [LinuxServer Selkies base](https://github.com/linuxserver/docker-baseimage-selkies):
  ARM64 Debian base, X11, audio/microphone, clipboard and file transfer. Upstream
  warns of breaking base updates and supplies no implicit latest tag.
- [Electron IPC](https://www.electronjs.org/docs/latest/tutorial/ipc): native
  desktop objects cannot simply be serialized across a browser transport.
- [Selkies core interface](https://docs.selkies.io/reference/web-core/selkies-ws-core):
  documented display scaling, keyboard, clipboard and peripheral messages offer
  a transport-owned integration boundary.
- [Chrome install criteria](https://web.dev/articles/install-criteria): HTTPS,
  appropriate manifest, icons, start URL and display mode. Promotion and menu
  installation are distinct; a service worker alone is not installation proof.
- [Keyboard viewport](https://developer.chrome.com/blog/viewport-resize-behavior):
  use the visual viewport and `interactive-widget=resizes-content` to avoid
  hiding controls behind the keyboard.
- [Android debugging](https://developer.chrome.com/docs/devtools/remote-debugging/):
  verify installation and standalone launch in actual Android Chrome. Desktop
  viewport emulation is complementary layout coverage.

## Acceptance boundaries

All active controls must remain reachable and free of clipping. Mutually
exclusive menus cannot all be displayed simultaneously. Fit mode keeps the
whole desktop visible; phone text size is a tradeoff and needs real inspection.

The official Linux preview excludes desktop Computer Use. Official Remote only
supports Mac/Windows hosts. This container's PWA is a separate delivery path;
it does not claim either unsupported native capability. Terminal, built-in
browser, native dialogs, profile persistence, permissions and updates require
live verification. Login and account-gated features require an authenticated
profile; do not infer support from an unsigned-in screen.

Discovery stopped after primary sources established the supported package,
transport boundary, mobile criteria, and platform exclusions. Live acceptance
will resolve runtime uncertainty.

The workstation retains a separate persistent Nix store/daemon, Docker data, home,
workspace, and development tooling, as requested. NixOS manages the container
and seeds its isolated Nix store; Debian supplies the supported GUI runtime.
