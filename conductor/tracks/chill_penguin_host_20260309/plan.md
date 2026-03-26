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

## Phase 2: `self-hosted` Module Structure & Data Restore Plan [~]
Set up the modular directory structure and prepare for data injection.

- [x] **Task: Create `modules/self-hosted` structure**
    - [x] Create `modules/self-hosted/default.nix`.
    - [x] Create `modules/self-hosted/common.nix` for shared settings.
- [ ] **Task: Implement Data Restore Protocol**
    - [ ] **Strategy**:
        1. **Pre-Start**: Use `systemd` activation scripts or one-shot jobs to ensure `/srv/apps/config/<service>` exists.
        2. **Inject**: Use `rsync` or `tar` to extract backed-up data into the target directories before the OCI containers start for the first time.
        3. **Permissions**: Ensure all restored files are owned by the new static UIDs (1000/1001).
        4. **Databases**: Use `mariadb-import` and `psql` to restore SQL dumps into the new NixOS-managed database containers.
        5. **Plex**: Specifically restore `com.plexapp.plugins.library.db` first, then metadata to avoid long re-scans.
- [x] **Task: Establish Data Directory Layout**
    - [x] Implement an activation script to ensure `/srv/apps/config` exists with correct permissions.

## Phase 3: Core Infrastructure and Networking [~]
Implement the base services referencing `old/chill-penguin/config`.

- [x] **Task: Implement Internal OCI Network**
    - [x] Define a bridge network `ghostship_net`.
- [x] **Task: Port Core Services**
    - [x] **Implement `gluetun` module** (Ref: `old/.../gluetun/`)
    - [x] **Implement `cloudflared` module** (Ref: `old/docker-compose.yml`)
    - [x] **Implement `homepage` module** (Ref: `old/.../homepage/`)
    - [x] **Implement `muximux` module** (Ref: `old/.../muximux/`)
- [~] **Task: Implement SOPS Secrets Integration**
    - [~] Define secrets based on values found in `old/docker-compose.yml` and config files.

## Phase 4: Database Stack
Implement isolated database containers.

- [ ] **Task: Implement Database Modules**
    - [ ] **MariaDB / MySQL** (Ref: `old/.../romm-db/`, etc.)
    - [ ] **PostgreSQL** (Ref: `old/.../warracker-db/`, etc.)

## Phase 5: Media Acquisition and Management
Port the download and indexing suite.

- [ ] **Task: Implement VPN-Routed Downloaders**
    - [ ] **Port `qbittorrent`** (Ref: `old/.../qbittorrent/`)
    - [ ] **Port `nzbget` / `sabnzbd`** (Ref: `old/.../nzbget/`, `old/.../sabnzbd/`)
- [ ] **Task: Port *Arr Suite**
    - [ ] **Port `prowlarr`, `sonarr`, `radarr`, `bazarr`** (Ref: `old/.../*arr/`)
- [ ] **Task: Port Management Utilities**
    - [ ] **Port `recyclarr`, `huntarr`, `flaresolverr`** (Ref: `old/.../recyclarr/`, etc.)

## Phase 6: Streaming and Content
Port media servers and library managers.

- [ ] **Task: Port Plex Stack**
    - [ ] **Port `plex`** (Ref: `old/.../plex/`)
    - [ ] **Port `tautulli`** (Ref: `old/.../tautulli/`)
    - [ ] **Port `plex-auto-languages`** (Ref: `old/.../plex-auto-languages/`)
- [ ] **Task: Port Library Managers**
    - [ ] **Port `romm`, `booklore`, `metube`** (Ref: `old/.../romm/`, etc.)

## Phase 7: Utility, Automation, and Specialized
Port the remaining specialized services.

- [ ] **Task: Port Home Automation**
    - [ ] **Port `homeassistant`** (Ref: `old/.../homeassistant/`)
    - [ ] **Port `windmill`** (Replacing `activepieces`)
- [ ] **Task: Port remaining utilities**
    - [ ] **Port `manyfold`, `fileflows`, `warracker`, `syncthing`, `searxng`, `convertx`, `it-tools`, `bentopdf`, `zerobyte`.** (Ref: `old/config/...`)

## Phase 8: NixOS Provisioning and Validation
Validate the new host after it has been wiped and running NixOS.

- [ ] **Task: Perform Global Build Check**
    - [ ] Execute `nixos-rebuild build --flake .#chill-penguin`.
    - [ ] Fix any compilation or type errors.
- [ ] **Task: Verify Service Initialization**
    - [ ] Verify `systemd` services for NixOS-native modules are active.
    - [ ] Verify all OCI containers are running and healthy.
- [ ] **Task: Validate Inter-Service Connectivity**
    - [ ] Confirm containers can communicate over `ghostship_net`.
    - [ ] Verify `gluetun` VPN routing for downloaders.
- [ ] **Task: Functional Verification**
    - [ ] Verify `homepage` dashboard is accessible and widgets are populating.
    - [ ] Verify `plex` hardware acceleration (`/dev/dri`) is functional.
    - [ ] Verify NFS shares are correctly mounted and accessible by services.
