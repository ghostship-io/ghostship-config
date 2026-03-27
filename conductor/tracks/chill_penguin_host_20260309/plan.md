# Implementation Plan: Add Host `chill-penguin` (Mac Studio Asahi Linux)

## Phase 0: Existing Configuration Discovery & Backup [x]
- [x] **Task: Document existing Docker stack on Fedora Asahi**
    - [x] Connect to `owner@192.168.200.135`.
    - [x] Extract `docker-compose.yml` and service list.
    - [x] Identify hardware dependencies (16k pages, `/dev/dri`, aarch64).
    - [x] Identify network and storage dependencies (NFS mount `192.168.200.106:/volume1/share`).
- [x] **Task: Backup all configurations to local `old/` directory**
    - [x] Create `old/chill-penguin/config` locally.
    - [x] Transfer all non-binary config files (`.yml`, `.yaml`, `.xml`, `.conf`, `.json`, `.ini`, `.css`, `.js`) from `/home/apps/config/` to local `old/chill-penguin/config/`.
    - [x] Backup `/home/apps/.env` and `/home/apps/.env.global` for secrets reference.
- [x] **Task: Backup application data, databases, and library metadata**
    - [x] **Databases**: Backup `*.db` files and SQL dumps for all core services.
    - [x] **Library Metadata**: (Already captured in previous sessions or partially archived)
    - [x] Store all data in `old/chill-penguin/data/`.

## Phase 1: Foundation and Global Configuration [x]
Establish the base host configuration and common tools.

- [x] **Task: Add `dasel` to common system packages**
    - [x] Update `modules/common/default.nix` to include `dasel`.
- [x] **Task: Initialize `chill-penguin` host configuration**
    - [x] Create `hosts/chill-penguin/default.nix` with Asahi Linux basics.
    - [x] Implement NixOS-native NFS mount for `/mnt/share` with `nofail` and `x-systemd.automount`.
    - [x] Add `chill-penguin` to `flake.nix` outputs.
- [x] **Task: Define Static UID/GID Mapping and Shared Group**
    - [x] Register all service users and groups in the 'Fleet ID Registry' in `conductor/product-guidelines.md`.
    - [x] Ensure UID 1000/3000 consistency across the fleet.
    - [x] Create the `apps` service account.

## Phase 2: `self-hosted` Module Structure & Data Restore Plan [x]
Set up the modular directory structure and prepare for data injection.

- [x] **Task: Create `modules/self-hosted` structure**
    - [x] Create `modules/self-hosted/default.nix`.
    - [x] Create `modules/self-hosted/common.nix` for shared settings.
- [x] **Task: Implement Data Restore Protocol** (Simplified - using surgical config approach)
    - [x] **Strategy**: Use surgical config management instead of full file restoration
- [x] **Task: Establish Data Directory Layout**
    - [x] Implement an activation script to ensure `/srv/apps/config` exists with correct permissions.

## Phase 3: Core Infrastructure and Networking [x]
Implement the base services referencing `old/chill-penguin/config`.

- [x] **Task: Implement Internal OCI Network**
    - [x] Define a bridge network `ghostship_net`.
- [x] **Task: Port Core Services**
    - [x] **Implement `gluetun` module** (Ref: `old/.../gluetun/`)
    - [x] **Implement `cloudflared` module** (Ref: `old/docker-compose.yml`)
    - [x] **Implement `homepage` module** (Ref: `old/.../homepage/`)
    - [x] **Implement `muximux` module** (Ref: `old/.../muximux/`)
- [x] **Task: Implement SOPS Secrets Integration**
    - [x] Define secrets based on values found in `old/docker-compose.yml` and config files.

## Phase 4: Database Stack [x]
Implement isolated database containers.

- [x] **Task: Implement Database Modules**
    - [x] **Implement ROMM-DB and Grimmory-DB** (PostgreSQL-based)

## Phase 5: Media Acquisition and Management [x]
Port the download and indexing suite.

- [x] **Task: Implement VPN-Routed Downloaders**
    - [x] **Implement `nzbget`** (Ref: `old/.../nzbget/`)
    - [x] **Implement `qbittorrent` via Vuetorrent** (Ref: `old/.../qbittorrent/`)
- [x] **Task: Port *Arr Suite**
    - [x] **Implement `prowlarr`, `sonarr`, `radarr`, `bazarr`** (Ref: `old/.../*arr/`)
- [x] **Task: Port Management Utilities**
    - [x] **Implement `recyclarr`, `flaresolverr`** (Ref: `old/.../recyclarr/`, etc.)

## Phase 6: Streaming and Content [x]
Port media servers and library managers.

- [x] **Task: Port Plex Stack**
    - [x] **Implement `plex`** (Ref: `old/.../plex/`)
    - [x] **Implement `tautulli`** (Ref: `old/.../tautulli/`)
    - [x] **Implement `plex-auto-languages`** (Ref: `old/.../plex-auto-languages/`)
- [x] **Task: Port Library Managers**
    - [x] **Implement `romm`, `metube`** (Ref: `old/.../romm/`, etc.)

## Phase 7: Utility, Automation, and Specialized [x]
Port the remaining specialized services.

- [x] **Task: Port remaining utilities**
    - [x] **Implement `searxng`, `grimmory`, `convertx`, `it-tools`, `bentopdf`.** (Ref: `old/config/...`)

## Phase 8: NixOS Provisioning and Validation [x]
Validate the new host after it has been wiped and running NixOS.

- [x] **Task: Perform Global Build Check**
    - [x] Execute `nixos-rebuild build --flake .#chill-penguin`.
    - [x] Fix any compilation or type errors.
- [x] **Task: Verify Service Initialization**
    - [x] Verify `systemd` services for NixOS-native modules are active.
    - [x] Verify all OCI containers are running and healthy.
- [x] **Task: Validate Inter-Service Connectivity**
    - [x] Confirm containers can communicate over `ghostship_net`.
    - [x] Verify `gluetun` VPN routing for downloaders.
- [~] **Task: Functional Verification**
    - [~] Verify `homepage` dashboard is accessible and widgets are populating.
    - [~] Verify `plex` hardware acceleration (`/dev/dri`) is functional.
    - [~] Verify NFS shares are correctly mounted and accessible by services.
