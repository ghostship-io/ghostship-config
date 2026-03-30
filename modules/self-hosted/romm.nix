{ config, lib, pkgs, ... }:

let
  romm-secrets = config.sops.secrets."romm-secrets".path;
  romm-iframe-fix = pkgs.writeShellScript "romm-iframe-fix" ''
    set -euo pipefail

    podman_bin="${pkgs.podman}/bin/podman"
    container="romm"
    ready=0
    attempts=0

    while [ "$ready" -eq 0 ]; do
      if "$podman_bin" exec -u 0 "$container" test -f /var/www/html/index.html \
        >/dev/null 2>&1; then
        ready=1
      else
        attempts=$((attempts + 1))
        if [ "$attempts" -ge 60 ]; then
          echo "RomM container never became ready for iframe patching" >&2
          exit 1
        fi
        sleep 1
      fi
    done

    "$podman_bin" exec -i -u 0 "$container" python - <<'PY'
from pathlib import Path
import re

index_path = Path("/var/www/html/index.html")
match = re.search(
    r'src="(/assets/[^"]*index-[^"]*\.js)"',
    index_path.read_text(),
)
if not match:
    raise SystemExit("Unable to locate active RomM bundle from index.html")

bundle_path = Path("/var/www/html" + match.group(1))
text = bundle_path.read_text()
original = "Ll.beforeResolve(async()=>{await LU().captured})"
patched = "Ll.beforeResolve(async()=>{})"

if patched not in text:
    if original not in text:
        raise SystemExit(
            f"RomM iframe patch target not found in {bundle_path}"
        )
    bundle_path.write_text(text.replace(original, patched, 1))

for pattern in (
    "/var/www/html/assets/index-*-noguards.js",
    "/var/www/html/assets/index-*-noresolve.js",
    "/var/www/html/assets/index-*.js.pre-noresolve-*",
    "/var/www/html/assets/index-authlogin-direct.js",
    "/var/www/html/assets/index-authloginshell-direct.js",
    "/var/www/html/assets/index-login-minrouter.js",
    "/var/www/html/assets/index-runtime-noboot.js",
    "/var/www/html/iframe-authlogin-direct.html",
    "/var/www/html/iframe-authloginshell-direct.html",
    "/var/www/html/iframe-login-clean.html",
    "/var/www/html/iframe-login-minrouter.html",
    "/var/www/html/iframe-login-noguards.html",
    "/var/www/html/iframe-login-noresolve.html",
    "/var/www/html/iframe-test.html",
    "/var/www/html/index.html.pre-iframe-guard-*",
    "/var/www/html/romm-iframe-probe.html",
):
    for path in bundle_path.parent.parent.glob(pattern.replace(
        "/var/www/html/", ""
    )):
        path.unlink(missing_ok=True)
PY
  '';
in
{
  virtualisation.oci-containers.containers."romm" = {
    image = "docker.io/rommapp/romm:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:8080/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      # Most environment is now managed via env file in preStart to ensure consistency with secrets
    };
    environmentFiles = [
      "/srv/apps/romm/romm.env"
    ];
    volumes = [
      "/srv/apps/romm/resources:/romm/resources:rw"
      "/srv/apps/romm/redis-data:/redis-data:rw"
      "/srv/apps/romm/config:/romm/config:rw"
      "/mnt/share/Library/ROMs:/romm/library:rw"
      "/mnt/share/Library/ROMs/.romm:/romm/assets:rw"
    ];
  };

  systemd.services.podman-romm = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
    postStart = ''
      ${romm-iframe-fix}
    '';
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/romm 0755 apps apps -"
    "d /srv/apps/romm/resources 0755 apps apps -"
    "d /srv/apps/romm/redis-data 0755 apps apps -"
    "d /srv/apps/romm/config 0755 apps apps -"
  ];

  systemd.services.podman-romm.preStart = ''
    CONFIG_DIR="/srv/apps/romm"
    CONFIG_FILE="$CONFIG_DIR/config/config.yml"
    ENV_FILE="$CONFIG_DIR/romm.env"

    if [ -f "$CONFIG_FILE" ]; then
      echo "Surgically updating RomM config.yml..."
      
      romm_cfg_args=(
        library_path=literal:/romm/library
        assets_path=literal:/romm/assets
        resources_path=literal:/romm/resources
      )

      ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${romm_cfg_args[@]}"
      chown 3000:3000 "$CONFIG_FILE"
    fi

    echo "Surgically updating RomM env file..."
    mkdir -p "$(dirname "$ENV_FILE")"
    touch "$ENV_FILE"

    romm_env_args=(
      --secrets-file "${romm-secrets}"
      DB_HOST=literal:romm-db
      DB_NAME=literal:romm
      DB_USER=env:ROMM_DB_USER
      DB_PASSWD=env:ROMM_DB_PASS
      ROMM_AUTH_SECRET_KEY=env:ROMM_AUTH_SECRET
      IGDB_CLIENT_ID=env:ROMM_IGDB_CLIENT_ID
      IGDB_CLIENT_SECRET=env:ROMM_IGDB_CLIENT_SECRET
      RETROACHIEVEMENTS_API_KEY=env:ROMM_RETROACHIEVEMENTS_API_KEY
      STEAMGRIDDB_API_KEY=env:ROMM_STEAMGRIDDB_API_KEY
      SCREENSCRAPER_USER=env:ROMM_SCREENSCRAPER_USER
      SCREENSCRAPER_PASSWORD=env:ROMM_SCREENSCRAPER_PASS
      HASHEOUS_API_ENABLED=literal:true
      HLTB_API_ENABLED=literal:true
      ALLOWED_HOSTS=literal:romm.ghostship.io,apps.ghostship.io,*
      TRUSTED_PROXIES=literal:*
      ENABLE_CSP=literal:false
      ROMM_HTTP_PROXY=literal:true
    )

    ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" "''${romm_env_args[@]}"

    chown 3000:3000 "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  '';
}
