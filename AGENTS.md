# Project Agent Memories

This file serves as the primary memory and persistent fact store for AI agents within this project.

## Lessons Learned

- **modDirVersion Alignment**: When using `prev.buildLinux` or similar kernel build functions in Nix, `modDirVersion` must exactly match the version string the kernel expects (often found in the top-level `Makefile`). A mismatch (e.g., `6.18.10-asahi` vs `6.18.10`) will cause a build failure late in the process during module installation.

- **yq-go INI Config Management**: For NixOS activation scripts managing INI config files:
  - Use `pkgs.yq-go` with `-p ini -o ini` flags for INI files
  - Use `pkgs.gnused` for sed commands in activation scripts (not coreutils sed)
  - Always reference tools with full path: `${pkgs.yq-go}/bin/yq`, `${pkgs.gnused}/bin/sed`
  - **INI-specific**: Delete old sections BEFORE adding new ones to preserve order
  - **Generic delete all sections except some**: `yq -i -p ini -o ini 'with_entries(select(.key == "section1" or .key == "section2"))' file.ini`
  - **Muximux-specific**:
    - yq adds backticks around `#` values - fix with: `sed -i 's/``\([^`]*\)``/"\1"/g'`
    - yq preserves PHP header when using `-i` flag
    - Homepage should be first service entry and only one with `default = "true"`
- **Homepage-specific**:
    - Use yq without `-p ini -o ini` flags (regular YAML parsing)
    - For large YAML configs, use `pkgs.writeText` to embed the YAML as a file, then `cp` to target
    - Use yq for partial updates (e.g., `.title = "value"`)

- **ISO Partitioning**: A custom ISO manually created from `iso-extract/` lacked a partition table (GPT/MBR), causing U-Boot's EFI boot manager to fail with `Cannot load any image`. The working ISO was built using the official `nixos-apple-silicon` repository with: `nix build .#installer-bootstrap -o installer -j4 -L`.
- **M1 Ultra Multi-Die Addressing**: M1 Ultra (t6002) peripherals on Die 1 have an 80GB offset (`0x2000000000`). The Asahi kernel (6.19.9) handles this correctly.
- **WiFi Firmware Compression**: The Asahi kernel (6.19.x) fails to load `brcmfmac` drivers if they are ZSTD compressed. Set `hardware.firmwareCompression = "none";` in the configuration.
- **Firmware Source Path**: The correct source for Apple firmware on NixOS is `/boot/asahi/`, containing `all_firmware.tar.gz` and `kernelcache*`.
- **Impure Rebuilds**: When `extractPeripheralFirmware` is enabled and pointing to `/boot/asahi`, `nixos-rebuild` REQUIRES the `--impure` flag to access files outside the flake.
- **Asahi Firmware Scope**: `/boot/asahi` is only relevant on `chill-penguin`; do not treat it as a repo-wide requirement. The peripheral-firmware module defaults `extractPeripheralFirmware = true`, so hosts without firmware must explicitly set it to `false` when `builtins.pathExists /boot/asahi` is false.
- **Gluetun Secret Ordering**: In this repo, `sops` installs secrets via activation scripts, not `sops-nix.service`. Do not add dependencies on `sops-nix.service`. Keep Gluetun's secret checks in `preStart` and wait for the actual files.
- **Podman Container Networking Dependencies**: Any container that uses `--network=container:gluetun` must explicitly declare `after = [ "podman-gluetun.service" ]` and `bindsTo = [ "podman-gluetun.service" ]`. Without that, the dependent container can survive a Gluetun replacement and block Podman from recreating the `gluetun` container.
- **Service Config Generation**: If a service config generator depends on `sops`-managed secret files, move it to `systemd.services.<unit>.preStart` instead of `system.activationScripts`. In this repo that is sufficient because `/run/secrets` is populated during activation before units are started.
- **Mutable Users Safety**: In early-stage hardware setups where WiFi might be unstable, set `users.mutableUsers = true;`. This prevents lockouts if `sops-nix` fails to decrypt the user password on boot.
- **Btrfs Layout**: A modern subvolume layout (`@`, `@home`, `@nix`, `@log`) with `compress=zstd` and `noatime` is preferred for large NVMe storage on Apple Silicon. When creating Btrfs filesystems on Apple Silicon, use 4K sectors (default) even if the CPU page size is 16K, as it is supported by kernels 6.x+ and ensures compatibility.
- **nh os build Flag Quirk**: `nh os build` passes extra arguments through to `nix build`; the `--no-build-output` flag is not accepted in this environment. Use the built-in `-q/--quiet` option or omit the flag entirely.
- **Ghostship Secret Resolution**: `modules/common/scripts/ghostship-config.py` must accept multiple `--secrets-file` inputs because activation scripts often combine several service-local secret files. Merge them in order so later files can override earlier values.
- **Ghostship YAML Scalars**: Use `yaml:` patches in `ghostship-config.py` when YAML fields must be written with native scalar types (for example booleans and integers in `searxng` settings). `literal:` always starts as a string and is only safe when the file already has the correct target type.
- **Ghostship YAML Paths**: `ghostship-config.py` YAML paths must handle dots inside bracket selectors (for example `[Infrastructure].[Llama.cpp]`), bracketed numeric list indices (for example `custom_formats[0].trash_ids[0]`), and bracket selectors against YAML mappings with dotted keys (for example `plugins[searx.plugins.calculator.SXNGPlugin].active`). Homepage, Recyclarr, and SearXNG all depend on those exact path forms.
- **qBittorrent Config Format**: `qBittorrent.conf` is an INI file despite the `.conf` extension. `ghostship-config.py` must special-case that basename as INI, and qBittorrent WebUI settings belong under `[Preferences]` as `WebUI\\...` keys, not legacy `WebUI.*` KV lines.
- **VueTorrent Alternate UI Layout**: qBittorrent 5.x expects `RootFolder` to point directly to the directory containing `index.html`. VueTorrent should be unpacked so `index.html` is at the top level of the mapped `RootFolder`. Auth bypass for the widget should rely on `WebUI\\AuthSubnetWhitelist`.
- **VueTorrent Refresh Marker**: VueTorrent should only re-download its archive when the upstream version changes. Use the stable versioned redirect URL from GitHub (e.g., `.../releases/download/vX.Y.Z/...`) as the marker, as the final signed URL contains expiration tokens and changes on every request.
- **Cloudflared Secret Names**: Keep Cloudflared's credentials split by purpose in `cloudflared-secrets`: `CLOUDFLARED_TUNNEL_TOKEN` is for the `cloudflared` container itself, while Homepage's Cloudflared widget needs `CLOUDFLARED_ACCOUNT_ID`, `CLOUDFLARED_TUNNEL_ID`, and `CLOUDFLARED_API_TOKEN`. Reusing the tunnel token for the widget returns Cloudflare `400` auth failures and leaves `connections` null.
- **Cloudflared Secret Mirror**: When editing `secrets.dec.yaml`, preserve the existing service blocks and append Cloudflare's `CLOUDFLARED_*` values into the `cloudflared-secrets` block. Do not replace the whole file with only the new block.
- **Cloudflared Tunnel Startup**: The `cloudflared` container must get a runtime `TUNNEL_TOKEN` env file and run with `cmd = [ "tunnel" "run" ]`. Passing a shell wrapper through `cmd` just becomes an extra `cloudflared` argument and still exits with "You did not specify any valid additional argument".
- **Gluetun Secret Source**: Gluetun should use the single `gluetun-secrets` bundle for both container env and the runtime auth shim. Do not keep a separate `gluetun-api-key` secret.
- **Bazarr Config Path**: Bazarr's authoritative config lives under `/srv/apps/bazarr/config/config.yaml` because the container mounts `/srv/apps/bazarr` at `/config`. If a legacy root `/srv/apps/bazarr/config.yaml` appears, seed the nested file from it once, update the nested file, and remove the legacy root copy to avoid Homepage/API key drift.
- **Plaintext Secret Mirror**: `secrets.dec.yaml` is the ignored plaintext mirror generated from `secrets.yaml`; when auditing secrets, use it to inspect actual secret values, then re-encrypt with the normal `sops` workflow.
- **YAML Secret Style**: Keep every secret bundle in `secrets.dec.yaml` formatted with `|-` block scalars, even when a bundle contains only a single `KEY=value` line.
- **Service-Local Secrets**: Service-local secret bundles should use `*-secrets` names (`gluetun-secrets`, `plex-secrets`, `tautulli-secrets`, `sonarr-secrets`, `radarr-secrets`, `prowlarr-secrets`, `bazarr-secrets`, `romm-secrets`, `grimmory-secrets`, `searxng-secrets`, `smb-secrets`, `cloudflared-secrets`) with service-local env names instead of `HOMEPAGE_*`. Homepage should source those service-local secrets directly instead of keeping a shared homepage bundle.
- **Bootstrap Script**: The installer-time bootstrap flow uses `bootstrap.sh` at repo root. It sets the hostname, creates `/etc/nix/secrets/age.key` if missing, preserves an existing key, and emits JSON for host registration. Use `nix-shell -p age jq nixos-install-tools` to provision installer-time dependencies.
- **Implementation Plans**: Active implementation plans are stored in `docs/superpowers/plans/`.
- **Comma Tool**: Use the `comma` tool to run utilities not in the current environment (e.g., `comma parted`).
- **U-Boot EFI Variables**: "Failed to load EFI variables" is usually non-fatal on Apple Silicon but can precede a boot failure if the boot target is missing.
- **Declarative Passwords Removed**: Declarative password management (`hashedPasswordFile`) was removed in favor of manual `passwd` to increase boot reliability on remote hosts.

## Agent Added Memories

- **GRUB Configuration Policy (CRITICAL)**: On `chill-penguin`, the ONLY functional GRUB config is **`/boot/grub/grub.cfg`** on partition **`p5`** (UUID: `2cd4968a-3953-4afe-9818-d9c10317e4a5`). NEVER rebuild or reformat this file.
    1.  **Primary Target**: `/boot/grub/grub.cfg` (The only file the system actually loads).
    2.  **Method**: Always use "Surgical Promotion" (cloning Attempt 29 via `sed`) to ensure formatting parity.
    3.  **Permissions**: Kernel binary MUST be `chmod 755`.
    4.  **Compression**: Kernel MUST be GZIP (`CONFIG_KERNEL_GZIP=y`).
    5.  **Validation**: **ALWAYS** run `sudo grub-script-check /boot/grub/grub.cfg` before committing.
    6.  **Recovery Disclosure**: **ALWAYS** provide the command `configfile /grub/grub.cfg.bak` whenever suggesting a reboot.
- **Kernel Compression Policy (CRITICAL)**: For the Apple Silicon / Asahi boot chain, the kernel MUST be compiled with `CONFIG_KERNEL_GZIP=y`. If `zstd` is used (`zimg` header says `zstd`), Fedora's GRUB will fail to parse/decompress the image and instantly crash/abort. This causes U-Boot to fall back to older ESP partitions (like the original NixOS ESP), mysteriously displaying a "GNU/Linux" default menu instead of the customized one.
- **Verification Policy**: Perform all verification autonomously using available tools (SSH, `lsblk`, `nix-store`, etc.). Only ask the user to run things if you cannot accomplish the verification yourself. Always verify system state both *before* and *after* builds or configuration changes. Ensure all intended state (e.g., kernel parameters, file system types, derivation updates) is empirically confirmed in the target environment (e.g., `/boot`, `/nix/store`, or active config files) before proceeding to critical actions like reboots.
- **Continuous Learning (HIGH PRIORITY)**: Record all hallucinations, errors, and new discoveries in this `AGENTS.md` file immediately to prevent repeating mistakes and to persist new discoveries.
- **Memory Management**: NEVER use the `save_memory` tool. Project-specific memory belongs here; global memory updates should be prompted to the user.
- **OSS Alignment**: Treat every project as if it were open source, following the baseline standards in `~/.agents/AGENTS.md`.
- **Sync Policy**: When syncing to `chill-penguin`, always exclude the `old/` and `.git/` directories to save time and bandwidth.
- **Command Policy**: Always use `tmux` (e.g., `tmux new-session -d -s <name> "<command>"`) for long-running commands (like `nix build`) to ensure they complete if the connection is lost. **On Fedora Asahi root, use a custom socket path (e.g., `tmux -S /tmp/nix-tmux ...`) to ensure session persistence and access.**
- **Parallel Research Policy**: While waiting for long-running builds (especially kernels), continuously research documented errors, search for similar issues in community forums (Asahi Linux, NixOS Apple Silicon), and deep-dive into the rationale behind experimental steps (e.g., why Attempt 18 is specific to 6.14.2). Document findings immediately in `troubleshooting.md`.
- **Troubleshooting Log**: Maintain and consult `troubleshooting.md` for all major system-level debugging efforts (e.g., Apple Silicon boot issues). Document every attempt, its rationale, and the outcome.
- **Kernel Alignment**: For Apple Silicon (chill-penguin), the NixOS kernel configuration is aligned with the functional Fedora Asahi kernel (6.14.2). Key options include `DRM_SIMPLEDRM=yes`, `FB_EFI=yes`, `VT_CONSOLE=yes`, and 16K pages. **Working kernel: 6.14.2-asahi with GZIP compression.**
- **m1n1 Bootloader**: Installed m1n1 is v1.5.2 (from Asahi installer v0.8.0). The `/boot/m1n1/boot.bin` is a composite of: m1n1.bin + DTB + U-Boot nodtb.bin + NVRAM vars. Version marker shows "unknown" due to installer modification.
- **Skill Refactor**: The `nixos` skill has been renamed to `system` and set as a default skill in `modules/common/gemini.nix`.
- **Automated Maintenance**: Automated daily garbage collection and generation cleanup (keeping 7 days) is configured in `modules/common/default.nix`. Use `nh clean all --keep X` for manual pruning.
- **Plan Mode Enabled**: Experimental plan mode has been enabled in `modules/develop/gemini.nix` while maintaining `default` as the default approval mode.
- **SSH MCP & Agent**: `mcp-ssh-manager` is configured to use the SSH agent at `/run/user/1000/ssh-agent`. Users must ensure their keys (especially password-protected ones) are loaded into the agent before using remote tasks.
- **MCP Runners**: `uv` and `nodejs` (for `npx`) are required for the current MCP server configurations (`agent-browser` and `mcp-ssh-manager`).
- **Python Skill Added**: A new `python` skill for modern development using `uv`, Nix flakes, and comprehensive testing/linting has been added to `~/.agents/skills/python/`.
- **System Packages**: `zip` has been added to the common system packages in `modules/common/default.nix`.
- **Build123d Skill Added**: A new `build123d` skill for Python-based CAD modeling with an emphasis on multi-perspective screenshot validation has been added.
- **Memory File Migration**: Treat `AGENTS.md` as the active project memory file for this workspace; ignore `GEMINI.md` for future memory updates.

- **SSH Skill Added**: A new `ssh` skill for expert remote server management via `mcp-ssh-manager` has been added to `~/.agents/skills/ssh/`.
- **Dynamic Skill Building**: The Nix configuration now dynamically zips skills from `home/config/skills/` during the build process, removing the need for manual `.skill` file check-ins.
- **Skills Location Migrated**: Skills have been migrated to the universal `~/.agents/skills/` directory. Global agent directives are in `~/.agents/AGENTS.md`.
- **OpenCode Wrapper Split**: OpenCode launch behavior is split between `modules/develop/opencode-wrapper.nix` (system wrapper) and `modules/develop/opencode.nix` (Home Manager). When changing launch-time OpenCode bootstrapping, update both so system and home setups stay aligned.
- **Gemini Delegation MCP**: The `@cainmaila/gemini-cli-mcp` package provides an MCP server that delegates prompts/tasks to the local Gemini CLI. It exposes useful tools like `executeTask`, `executePrompt`, and `inspectGeminiCli`, and is a good fit for repo-research / planning delegation.
- **Codex Configuration**: Codex reads global instructions from `~/.codex/AGENTS.md` and config from `~/.codex/config.toml`. It also supports `skills.config` entries pointing at `~/.agents/skills/*`, which makes `~/.agents` a viable shared source for Codex skill wiring.
- **Worktree Ignore Rule**: If a project-local `.worktrees/` directory is used for isolated development, it must be ignored in `.gitignore` before creating the worktree.
- **MCP Refresh on Switch**: A system `activationScripts` hook is a reasonable place to warm `npx`-managed MCP packages during `nh os switch`, so CLI-side MCP deps stay current without extra user steps.
- **Plugin Version Checks**: For GitHub-backed Gemini extensions and OpenCode plugins, compare the installed local `HEAD` to `git ls-remote` before updating. If the commit hash is unchanged, skip the update; if it changed, refresh or delete the local checkout so the launcher reinstalls it.
- **Encrypted Secrets Workflow**: If a task requires changing encrypted secret material (for example `secrets.yaml` or a `sops.secrets` payload), ask the user to decrypt and re-encrypt the secret rather than trying to edit ciphertext directly.
- **Chill Penguin Status**: Running NixOS on Apple Silicon (Mac Studio M1 Ultra) with kernel 6.19.9-asahi. Uses Fedora's GRUB to chainload. m1n1 bootloader v1.5.2 installed (from Asahi installer v0.8.0).
