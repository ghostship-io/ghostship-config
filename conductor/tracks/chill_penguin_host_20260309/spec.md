# Specification: Add Host `chill-penguin` (Mac Studio)

## Overview
This track involves migrating the `chill-penguin` host from Fedora Asahi Remix to a native NixOS configuration. `chill-penguin` is a Mac Studio (M1/M2 Max/Ultra) that functions as a high-performance headless server for media, home automation, and LLM services. It previously ran a massive Docker-based stack (~40 services) with NFS-backed storage.

## Functional Requirements

### 1. Host Configuration
- **Platform**: Mac Studio (Apple Silicon).
- **Architecture**: `aarch64-linux` with **16k page size** support.
- **Boot**: Integration with Asahi Linux firmware and m1n1/uboot.
- **Headless**: Optimized for remote management via SSH.
- **NixOS Output**: Define `nixosConfigurations.chill-penguin` in `flake.nix`.

### 2. Service Architecture (NixOS + OCI)
- **Modular Structure**: Implement services in `modules/self-hosted/`.
- **Hybrid Approach**: Use NixOS-native modules where performance or system integration is critical (e.g., NFS, Graphics); use OCI containers (via `virtualisation.oci-containers`) for complex application stacks.
- **Hardware Acceleration**: Enable `/dev/dri` access for Plex (transcoding) and `llama-vulkan` (inference).

### 3. User & Group Management
- **Fleet Consistency**: Map UID/GID 1000/1001 to maintain consistency with the rest of the fleet and existing data permissions.
- **Shared Access**: Implement a `media-data` group for shared access to `/srv/apps/config` and `/mnt/share`.

### 4. Storage & Persistence
- **System Layout**: Btrfs with subvolumes for `/`, `/home`, and `/var`.
- **App Data**: Local persistence at `/srv/apps/config/`.
- **Media Storage**: NixOS-native **NFS mount** for `192.168.200.106:/volume1/share` mapped to `/mnt/share`.
    - **Robustness**: Must use `nofail` and `x-systemd.automount` options to ensure the system boots successfully even if the NFS server is unreachable.

### 5. Configuration & Merging Strategy
- **Reference Source**: All configurations are derived from `old/chill-penguin/` (captured from the previous Fedora install).
- **Environment**: Use variables from `.env` and `.env.global` to populate `sops-nix` secrets.
- **Dasel Merging**: Use `dasel` for structured merging into app-generated configs (Plex, *Arr, HA, etc.) to maintain declarative control while allowing app-level state.

### 6. Service List (Migration Scope)
- **Infrastructure**: Gluetun (VPN), Cloudflared, Homepage (Dashboard), Muximux.
- **Media**: Plex, Tautulli, Plex-auto-languages, Sonarr, Radarr, Prowlarr, Bazarr.
- **Downloads**: qBittorrent, NZBGet, Sabnzbd.
- **Databases**: MariaDB (RomM, Booklore), PostgreSQL (Warracker, PriceGhost).
- **Automation**: Home Assistant, Windmill (replacing Activepieces).
- **Utilities**: Syncthing, MeTube, RomM, Booklore, Manyfold, FileFlows, Recyclarr, Huntarr, FlareSolverr, BentoPDF, IT-Tools, ConvertX, Zerobyte, Warracker, SearXNG.

## Non-Functional Requirements
- **16k Page Size**: All binaries and OCI images must be compatible with the 16k page size (common on Apple Silicon).
- **Secrets Isolation**: No secrets in the Nix store; all sensitive data managed via `sops-nix`.
- **Network Isolation**: Use a dedicated `ghostship_net` bridge for inter-service communication.

### 7. Networking
- **VPN Routing**: Replicate the `gluetun` routing logic for `qbittorrent`, `nzbget`, `sabnzbd`, and `searxng`.
    - These services **MUST** share the `gluetun` network namespace (e.g., `extraOptions = [ "--network=container:gluetun" ]`).
    - Ensure `gluetun` handles the port forwarding and health checks for these services.
- **Internal Network**: All other containers must be accessible on the `ghostship_net` bridge.
- **Gateway**: `cloudflared` must have connectivity to the internal stack for remote access.

## Acceptance Criteria
- [ ] `chill-penguin` boots NixOS with functional 10GbE and NVMe.
- [ ] `/mnt/share` is automatically mounted via NFS on boot.
- [ ] All 40+ services are defined in Nix and running as OCI containers or native services.
- [ ] Plex hardware transcoding is functional via `/dev/dri`.
- [ ] `gluetun` successfully routes traffic for specified downloaders.
- [ ] `homepage` dashboard is live and correctly displays service statuses.
- [ ] All secrets are successfully injected via `sops-nix`.
