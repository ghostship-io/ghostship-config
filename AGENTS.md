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

## Agent Added Memories

- **GRUB Configuration Policy (CRITICAL)**: On `chill-penguin`, the ONLY functional GRUB config is **`/boot/grub/grub.cfg`** on partition **`p5`** (UUID: `2cd4968a-3953-4afe-9818-d9c10317e4a5`). NEVER rebuild or reformat this file.
    1.  **Primary Target**: `/boot/grub/grub.cfg` (The only file the system actually loads).
    2.  **Method**: Always use "Surgical Promotion" (cloning Attempt 29 via `sed`) to ensure formatting parity.
    3.  **Permissions**: Kernel binary MUST be `chmod 755`.
    4.  **Compression**: Kernel MUST be GZIP (`CONFIG_KERNEL_GZIP=y`).
    5.  **Validation**: **ALWAYS** run `sudo grub-script-check /boot/grub/grub.cfg` before committing.
    6.  **Recovery Disclosure**: **ALWAYS** provide the command `configfile /grub/grub.cfg.bak` whenever suggesting a reboot.
- **Kernel Compression Policy (CRITICAL)**: For the Apple Silicon / Asahi boot chain, the kernel MUST be compiled with `CONFIG_KERNEL_GZIP=y`. If `zstd` is used (`zimg` header says `zstd`), Fedora's GRUB will fail to parse/decompress the image and instantly crash/abort. This causes U-Boot to fall back to older ESP partitions (like the original NixOS ESP), mysteriously displaying a "GNU/Linux" default menu instead of the customized one.
- **Verification Policy**: Skip "User Manual Verification" steps in the Conductor protocol. Perform all verification autonomously using available tools (SSH, `lsblk`, `nix-store`, etc.). Only ask the user to run things if you cannot accomplish the verification yourself. Always verify system state both *before* and *after* builds or configuration changes. Ensure all intended state (e.g., kernel parameters, file system types, derivation updates) is empirically confirmed in the target environment (e.g., `/boot`, `/nix/store`, or active config files) before proceeding to critical actions like reboots.
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
- **Bootstrap Flake**: Replaced the legacy `bootstrap.sh` script with a minimal bootstrap flake located at `bootstrap/`. Use `nix run .#bootstrap <hostname>` to generate host registration data. This flake provides exactly the same functionality as the original script: generates hardware configuration, creates SOPS age keys, and outputs machine-readable JSON for host registration.
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
- **Chill Penguin Migration (In-Progress)**:
    - **Status**: Phase 6 (Rust Support & GPU Acceleration - Attempt 46).
    - **Host**: Mac Studio M1 Ultra (`mac13j`).
    - **Strategy**: Side-by-side subvolume install on `/dev/nvme0n1p7`. Using Fedora's GRUB to chainload.
    - **Current Action**: Attempt 46 built with Rust + Fedora-like config. Still uses kernel 6.18.10 which doesn't boot.
    - **Working Kernel**: Attempt 29 (6.14.2-asahi + GZIP + no Rust).
    - **m1n1**: v1.5.2 installed (confirmed from Asahi installer v0.8.0).
    - **Issue**: nixpkgs provides linux-asahi 6.18.10. Need 6.14.2 (Fedora's working kernel) but can't change without source override.
    - **Next Step**: Override kernel source to use asahi-6.14.2-1 tag with correct hash.
