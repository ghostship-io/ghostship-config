# Plan: Configure Sonarr, Radarr, and Prowlarr

## Objective
Configure Sonarr, Radarr, and Prowlarr declaratively using `yq` in activation scripts, securely load API keys from their service-local `*-secrets` sops-nix secrets, and restore old SQLite databases from the backups if they pass integrity checks.

## Key Files & Context
- **Modules**: 
  - `modules/self-hosted/sonarr.nix`
  - `modules/self-hosted/radarr.nix`
  - `modules/self-hosted/prowlarr.nix`
  - `modules/self-hosted/secrets.nix`
- **Secrets**: `sonarr-secrets`, `radarr-secrets`, `prowlarr-secrets`
- **Databases**: 
  - `old/chill-penguin/remote_tmp/sonarr.db`
  - `old/chill-penguin/remote_tmp/radarr.db`
  - `old/chill-penguin/remote_tmp/prowlarr.db`

## Implementation Steps

### 1. Verification of Secrets
- Confirm `sonarr-secrets`, `radarr-secrets`, and `prowlarr-secrets` are correctly exposed in `modules/self-hosted/secrets.nix`.
- Ensure they contain `SONARR_API_KEY`, `RADARR_API_KEY`, and `PROWLARR_API_KEY`.

### 2. Update Modules with `yq` Activation Scripts
Modify the `.nix` modules for Sonarr, Radarr, and Prowlarr to include `system.activationScripts`. These scripts will:
- Read the API key securely from the service-local secret file by parsing the line.
- Use `yq` to set the XML configuration.
- Example logic for extracting key and updating XML:
  ```bash
  SECRETS_FILE="/run/secrets/sonarr-secrets"
  if [ -f "$SECRETS_FILE" ]; then
    APP_API_KEY=$(grep "SONARR_API_KEY" "$SECRETS_FILE" | cut -d'=' -f2)
    ${pkgs.yq-go}/bin/yq -i -p xml -o xml '.Config.ApiKey = "'$APP_API_KEY'" | .Config.AuthenticationMethod = "External" | .Config.AuthenticationRequired = "DisabledForLocalAddresses"' "$CONFIG_FILE"
  fi
  ```

### 3. Database Integrity Verification & Restoration
Manually perform the following steps to safely restore the data:
- Check integrity of local databases in `old/chill-penguin/remote_tmp/` using `sqlite3 "PRAGMA integrity_check;"`.
- Stop the respective podman services on `chill-penguin-root`.
- `rsync` the healthy databases to `/srv/apps/config/<app>/<app>.db` on the remote server.
- Set ownership to `apps:apps` (`chown 3000:3000`).
- Start the services.

### 4. Deploy changes
- Run `nh os switch .#chill-penguin --impure` to generate configs and apply the secrets.
- Note: User will handle re-encryption of `secrets.yaml`.
