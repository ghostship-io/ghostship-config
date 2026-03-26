# Plan: Add Plex to chill-penguin

## Objective
Add Plex to `chill-penguin` as a NixOS OCI container (Podman), migrating existing metadata and databases from the old installation, and using `yq` in an activation script to recreate the configuration logic previously handled by Ansible.

## Key Files & Context
- **New Module**: `modules/self-hosted/plex.nix`
- **Secrets**: `modules/self-hosted/secrets.nix`
- **Root Include**: `modules/self-hosted/default.nix`
- **Old Data**:
  - `old/chill-penguin/config/plex/Preferences.xml`
  - `old/chill-penguin/data/plex/com.plexapp.plugins.library.db`
  - `old/chill-penguin/data/plex/plex_library.db`

## Implementation Steps

### 1. Create the `plex.nix` Module
Define `virtualisation.oci-containers.containers."plex"`:
- **Image**: `lscr.io/linuxserver/plex:latest`
- **Network**: Connect to `ghostship_net`.
- **Ports**: Expose `32400:32400`, `1900:1900/udp`, `3005:3005`, `5353:5353/udp`, `8324:8324`, `32410:32410/udp`, `32412:32412/udp`, `32413:32413/udp`, `32414:32414/udp`, `32469:32469`.
- **Environment**: `PUID = "3000"`, `PGID = "3000"`, `TZ = "UTC"`, `VERSION = "latest"`.
- **Secrets**: Use `environmentFiles = [ "/run/secrets/plex-env" ];` for `PLEX_CLAIM`.
- **Devices**: Forward `/dev/dri:/dev/dri` for hardware transcoding.
- **Volumes**:
  - `/srv/apps/config/plex:/config`
  - `/mnt/share/Library:/library` (The `192.168.200.106:/volume1/share` NFS is already mounted to `/mnt/share`).

### 2. Old Metadata Restoration
Include `systemd.tmpfiles.rules` to ensure the correct directory structure is pre-created:
```nix
"d '/srv/apps/config/plex/Library/Application Support/Plex Media Server/Plug-in Support/Databases' 0755 apps apps -"
```
Instruct the user (or automate via a one-time copy script in the module) to copy the old metadata into place:
- `Preferences.xml` -> `/srv/apps/config/plex/Library/Application Support/Plex Media Server/Preferences.xml`
- `*.db` files -> `/srv/apps/config/plex/Library/Application Support/Plex Media Server/Plug-in Support/Databases/`

### 3. XML Configuration via `yq`
Create a shell script (`plex-config.sh`) that runs via `system.activationScripts.plex-config`:
- The script will use `pkgs.yq-go` to parse and edit `Preferences.xml`.
- Replicate the Ansible playbook's modifications:
  - `FriendlyName = "chill-penguin"`
  - `LanNetworksBandwidth = "192.168.1.0/255.255.255.0,172.16.0.0/255.240.0.0"`
  - `customConnections = "http://192.168.200.135:32400"` (retained from old config)
  - `allowedNetworks = "192.168.1.0/255.255.255.0,172.16.0.0/255.240.0.0"`
- Example `yq` command logic:
  ```bash
  ${pkgs.yq-go}/bin/yq -i -p xml -o xml '.Preferences.+@FriendlyName = "chill-penguin" | .Preferences.+@LanNetworksBandwidth = "192.168.1.0/255.255.255.0,172.16.0.0/255.240.0.0" | .Preferences.+@customConnections = "http://192.168.200.135:32400" | .Preferences.+@allowedNetworks = "192.168.1.0/255.255.255.0,172.16.0.0/255.240.0.0"' "$PLEX_PREFS"
  ```

### 4. Wire up Secrets and Imports
- **`modules/self-hosted/secrets.nix`**: Add an entry for `plex-env` (owned by `apps`).
- **`modules/self-hosted/default.nix`**: Add `./plex.nix` to imports.

## Verification & Testing
- Deploy changes via `nh os build` and `nh os switch`.
- Check if Podman successfully brings up Plex (`podman ps | grep plex`).
- Verify `Preferences.xml` is modified correctly by `yq`.
- Ensure old libraries appear in the Plex web UI at port 32400.
