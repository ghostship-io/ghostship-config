# Unified NixOS Configuration Fleet

A robust, modular, and reproducible NixOS configuration repository managing a diverse fleet of systems—replacing legacy Ansible-based infrastructure with a modern, declarative Nix-native approach.

## 🚀 Vision
To create an identical state across personal workstations, servers, and embedded devices using Nix Flakes and Home Manager, ensuring absolute reproducibility and seamless platform integration (especially for WSL2).

## 🛠 Tech Stack

### Core Ecosystem
- **Nix & Nix Flakes**: Dependency management and standardized outputs.
- **NixOS**: The primary operating system.
- **Home Manager**: Declarative user environment and dotfile management.
- **sops-nix**: Secure secret management using Mozilla SOPS (age/gpg).

### Development & Shell
- **Fish Shell**: Primary interactive shell with a rich plugin ecosystem.
- **Starship**: Cross-shell prompt for a consistent visual experience.
- **devenv**: Declarative development environments.
- **direnv & nix-direnv**: Automatic shell activation.
- **Inshellisense**: IDE-style autocomplete for the CLI.
- **Modern CLI Utils**: `eza` (ls), `bat` (cat), `fd` (find), `zoxide` (cd), `fzf` (search), `nh` (nix helper).

## 💻 Systems
- **launch-octopus**: Primary WSL2 development environment on Windows 11.
- **boomer-kuwanger**: Dedicated emulation-focused NixOS PC running on a Minisforum HX100G.
- **chill-penguin**: Mac Studio M1 Ultra (Apple Silicon) - Successfully running the official NixOS ARM64 installer (Kernel 6.19.9-asahi). Partitioned with a 3.6 TiB Btrfs layout (`@`, `@home`, `@nix`, `@log`) with ZSTD compression. Currently in the installation phase.

## ✨ Key Features

### WSL2 Integration
- **notify-send Bridge**: Forwards Linux notifications to the Windows Action Center with native branding.
- **wsl-open**: Seamlessly open Linux files/directories in Windows applications.
- **win-home Symlink**: Direct access to your Windows user profile at `~/win-home`.
- **WSLENV Integration**: Shared environment variables between host and guest.

### Security
- **Secrets Management**: Encrypted `secrets.yaml` integrated directly into NixOS modules via `sops-nix`.

### Agent Tooling
- **Unified Assistant Stack**: Gemini, OpenCode, and Codex share a common `~/.agents` instruction/skills source, aligned MCP servers, and a Gemini delegation MCP for repo research and planning.

### Surgical Configuration Management (`ghostship-config`)
- **Unified Tooling**: A fleet-wide Python utility (`ghostship-config`) for idempotent, surgical updates to XML, YAML, INI, and KV files.
- **Identity Enforcement**: Automatically enforces "Ghostship Standard" identity (e.g., `InstanceName`, `FriendlyName`) across all self-hosted apps.
- **Privacy First**: Automatically disables analytics and ensures update mechanics are set to "Manual" (since Nix handles versioning).
- **Secure Secrets**: Injects secrets from environment variables or files using `env:` or `file:` prefixes, ensuring sensitive values never appear in process lists or the Nix store.
- **Idempotency**: Only writes to disk if a change is actually needed, reducing I/O and service restarts.

## 📖 Usage

### Apply Configuration
To rebuild the system and switch to the latest configuration using `nh` (Nix Helper):
```bash
nh os switch .
```
Alternatively, for traditional `nixos-rebuild`:
```bash
sudo nixos-rebuild switch --flake .#launch-octopus
```

### 🆕 Bootstrap a New Host
When setting up a brand-new machine, follow these steps to integrate it into the fleet:

1. **Boot into NixOS**: Start the system from a NixOS installer (ISO) or a minimal existing installation.
2. **Clone the Repository**:
   ```bash
   nix-shell -p git
   git clone https://github.com/jpetrucciani/nixos-config.git ~/nixos-config
   cd ~/nixos-config
   ```
3. **Run the Bootstrap Script**:
   The installer-time script uses `nix-shell` to provide `age-keygen`, `jq`, and `nixos-generate-config`, then sets the hostname, ensures `/etc/nix/secrets/age.key` exists without overwriting an existing key, and prints a JSON payload containing the hostname, public key, and hardware configuration:
   ```bash
   sudo ./bootstrap.sh NEW_HOSTNAME
   ```
4. **Register the Host**:
   - On your management machine, run the existing registration helper and paste the JSON when prompted:
     ```bash
     sudo sops-register-host
     ```
   - Paste the JSON block and press `Ctrl+D`.
   - This will automatically:
     - Add the public key to `.sops.yaml`.
     - Update secrets access list.
     - Create `hosts/NEW_HOSTNAME/hardware-configuration.nix`.
     - Re-encrypt `secrets.yaml`.
5. **Finalize Setup**:
   - Add `NEW_HOSTNAME` to `flake.nix` under `nixosConfigurations`.
   - Commit and push the changes.
   - On the new host, apply the configuration: `sudo nixos-rebuild switch --flake .#NEW_HOSTNAME`.

### Manage Secrets

The system is configured for automated daily maintenance:
- **Garbage Collection**: Unused store paths are automatically deleted daily.
- **Generation Cleanup**: System generations older than 7 days are automatically purged to optimize disk space.
- **Manual Cleanup**: To manually trigger a cleanup and keep only the last 5 generations:
```bash
nh clean all --keep 5
```

### Manage Secrets
The configuration includes several helper scripts for managing secrets via `sops-nix`:

- **List public keys**: Show all public keys and their associated systems defined in `.sops.yaml`:
  ```bash
  secrets-list-keys
  ```
- **Edit secrets**: Decrypt and edit the secrets file:
  ```bash
  secrets-edit secrets.yaml
  ```
- **Add a new key**: Add a new age public key and optionally associate it with a system:
  ```bash
  secrets-add-key <age1...> [system-name]
  ```
- **Re-encrypt**: After adding/removing keys, re-encrypt the secrets file to apply the new access list:
  ```bash
  secrets-reencrypt
  ```
- **Generate age key**: Create a new age key pair if one doesn't exist:
  ```bash
  generate-age-key
  ```
- **Get public key**: Show the public key derived from the local age key:
  ```bash
  secrets-get-public-key
  ```

### Notifications
Standard Linux notification commands are automatically forwarded to Windows:
```bash
notify-send "Task Complete" "The build has finished."
```

## 📂 Structure
- `hosts/`: Hardware-specific configurations for each machine.
- `modules/`: Shared system-level NixOS modules (common, services, etc.).
- `home/`: User-level Home Manager configurations.
- `conductor/`: Project management, specifications, and implementation plans.
