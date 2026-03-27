# Gemini CLI: Persistent Memory

## Current Focus
- Fleet management for NixOS systems including `chill-penguin` (Mac Studio M1 Ultra).
- Maintaining a stable, declarative configuration across diverse hardware.

## Lessons Learned
- **ISO Partitioning**: A custom ISO manually created from `iso-extract/` lacked a partition table (GPT/MBR), causing U-Boot's EFI boot manager to fail with `Cannot load any image`.
- **Successful ISO Build**: The working ISO was built using the official `nixos-apple-silicon` repository with the command: `nix build .#installer-bootstrap -o installer -j4 -L`.
- **M1 Ultra Multi-Die Addressing**: M1 Ultra (t6002) peripherals on Die 1 have an 80GB offset (`0x2000000000`). The current Asahi kernel (6.19.9) handles this correctly.
- **WiFi Firmware Compression**: The Asahi kernel (at least 6.19.x) fails to load `brcmfmac` drivers if they are ZSTD compressed. You MUST set `hardware.firmwareCompression = "none";` in the configuration.
- **Firmware Source Path**: The correct source for Apple firmware on NixOS is `/boot/asahi/`, containing `all_firmware.tar.gz` and `kernelcache*`.
- **Impure Rebuilds**: When `extractPeripheralFirmware` is enabled and pointing to `/boot/asahi`, `nixos-rebuild` REQUIRES the `--impure` flag to access files outside the flake.
- **Asahi Firmware Scope**: `/boot/asahi` is only relevant on `chill-penguin`; do not treat it as a repo-wide requirement. The peripheral-firmware module defaults `extractPeripheralFirmware = true`, so hosts without firmware must explicitly set it to `false` when `builtins.pathExists /boot/asahi` is false.
- **Gluetun Secret Ordering**: In this repo, `sops` installs secrets via activation scripts, not `sops-nix.service`, so do not add dependencies on `sops-nix.service`. Keep Gluetun's secret checks in `preStart` and wait for the actual files.
- **Podman Container Networking Dependencies**: Any container that uses `--network=container:gluetun` must explicitly declare `after = [ "podman-gluetun.service" ]` and `bindsTo = [ "podman-gluetun.service" ]`. Without that, the dependent container can survive a Gluetun replacement and block Podman from recreating the `gluetun` container.
- **Service Config Generation**: If a service config generator depends on `sops`-managed secret files, move it to `systemd.services.<unit>.preStart` instead of `system.activationScripts`. In this repo that is sufficient because `/run/secrets` is populated during activation before units are started.
- **Mutable Users Safety**: In early-stage hardware setups where WiFi might be unstable, set `users.mutableUsers = true;`. This prevents lockouts if `sops-nix` fails to decrypt the user password on boot.
- **Btrfs Layout**: A modern subvolume layout (`@`, `@home`, `@nix`, `@log`) with `compress=zstd` and `noatime` is preferred for large NVMe storage on Apple Silicon.
- **`nh os build` Flag Quirk**: `nh os build` passes extra arguments through to `nix build`; the `--no-build-output` flag is not accepted in this environment. Use the built-in `-q/--quiet` option or omit the flag entirely.
- **Ghostship Secret Resolution**: `modules/common/scripts/ghostship-config.py` must accept multiple `--secrets-file` inputs because activation scripts often combine several service-local secret files. Merge them in order so later files can override earlier values.
- **Ghostship YAML Scalars**: Use `yaml:` patches in `ghostship-config.py` when YAML fields must be written with native scalar types (for example booleans and integers in `searxng` settings). `literal:` always starts as a string and is only safe when the file already has the correct target type.
- **Ghostship YAML Paths**: `ghostship-config.py` YAML paths must handle dots inside bracket selectors (for example `[Infrastructure].[Llama.cpp]`), bracketed numeric list indices (for example `custom_formats[0].trash_ids[0]`), and bracket selectors against YAML mappings with dotted keys (for example `plugins[searx.plugins.calculator.SXNGPlugin].active`). Homepage, Recyclarr, and SearXNG all depend on those exact path forms.
- **qBittorrent Config Format**: `qBittorrent.conf` is an INI file despite the `.conf` extension. `ghostship-config.py` must special-case that basename as INI, and qBittorrent WebUI settings belong under `[Preferences]` as `WebUI\\...` keys, not legacy `WebUI.*` KV lines.
- **VueTorrent Alternate UI Layout**: qBittorrent's alternate WebUI expects `RootFolder` to be the parent directory that contains a `public/` subtree. VueTorrent must be unpacked so `public/index.html` exists, and auth bypass for the widget should rely on `WebUI\\AuthSubnetWhitelist` instead of a saved username/password when the UI is meant to be anonymous on trusted subnets.
- **VueTorrent Refresh Marker**: VueTorrent should only re-download its archive when the upstream redirected release URL changes. Keep a small marker file outside the UI tree and compare it against the current `curl -fsSLI -L` effective URL so activation does not unpack on every switch.
- **Cloudflared Secret Names**: Keep Cloudflared's credentials split by purpose in `cloudflared-secrets`: `CLOUDFLARED_TUNNEL_TOKEN` is for the `cloudflared` container itself, while Homepage's Cloudflared widget needs `CLOUDFLARED_ACCOUNT_ID`, `CLOUDFLARED_TUNNEL_ID`, and `CLOUDFLARED_API_TOKEN`. Reusing the tunnel token for the widget returns Cloudflare `400` auth failures and leaves `connections` null.
- **Cloudflared Secret Mirror**: When editing `secrets.dec.yaml`, preserve the existing service blocks and append Cloudflare's `CLOUDFLARED_*` values into the `cloudflared-secrets` block. Do not replace the whole file with only the new block.
- **Gluetun Secret Source**: Gluetun should use the single `gluetun-secrets` bundle for both container env and the runtime auth shim. Do not keep a separate `gluetun-api-key` secret.
- **Bazarr Config Path**: Bazarr's authoritative config lives under `/srv/apps/bazarr/config/config.yaml` because the container mounts `/srv/apps/bazarr` at `/config`. If a legacy root `/srv/apps/bazarr/config.yaml` appears, seed the nested file from it once, update the nested file, and remove the legacy root copy to avoid Homepage/API key drift.
- **Plaintext Secret Mirror**: `secrets.dec.yaml` is the ignored plaintext mirror generated from `secrets.yaml`; when auditing secrets, use it to inspect actual secret values, then re-encrypt with the normal `sops` workflow.
- **YAML Secret Style**: Keep every secret bundle in `secrets.dec.yaml` formatted with `|-` block scalars, even when a bundle contains only a single `KEY=value` line.
- **Service-Local Secrets**: Service-local secret bundles should use `*-secrets` names (`gluetun-secrets`, `plex-secrets`, `tautulli-secrets`, `sonarr-secrets`, `radarr-secrets`, `prowlarr-secrets`, `bazarr-secrets`, `romm-secrets`, `grimmory-secrets`, `searxng-secrets`, `smb-secrets`, `cloudflared-secrets`, `homeassistant-secrets`) with service-local env names instead of `HOMEPAGE_*`. Homepage should source those service-local secrets directly instead of keeping a shared homepage bundle.

## Gemini Added Memories
- The default `installer-bootstrap` build command is `nix build .#installer-bootstrap -o installer -j4 -L`.
- Use `comma` tool to run `parted` or other utilities not in the current environment.
- U-Boot's "Failed to load EFI variables" is usually non-fatal on Apple Silicon but can precede a boot failure if the boot target is missing.
- When creating Btrfs filesystems on Apple Silicon, use 4K sectors (default) even if the CPU page size is 16K, as it is supported by kernels 6.x+ and ensures compatibility.
- Declarative password management (`hashedPasswordFile`) was removed in favor of manual `passwd` to increase boot reliability on remote hosts.
- The repository's `conductor/` tree is a full task-management layer, not just `plan.md`; it also includes `tracks/`, `archive/`, `metadata.json`, `spec.md`, `index.md`, and `workflow.md`.
- The installer-time bootstrap flow is back to a repo-root `bootstrap.sh` script. It sets the hostname, creates `/etc/nix/secrets/age.key` if missing, preserves an existing key, and emits JSON for host registration.
- `nixos-install-tools` provides `nixos-generate-config` in `nix-shell` alongside `age` and `jq`, so the bootstrap script can self-provision its installer-time dependencies.
