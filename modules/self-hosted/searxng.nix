{ config, lib, pkgs, ... }:

let
  searxng-secrets = config.sops.secrets."searxng-secrets".path;
in
{
  virtualisation.oci-containers.containers."searxng" = {
    image = "searxng/searxng:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=container:gluetun"
      "--health-cmd=wget -q --spider http://127.0.0.1:5002 && wget -q --spider https://google.com || exit 1"
      "--health-interval=1m"
      "--health-timeout=10s"
      "--health-retries=3"
      "--health-start-period=30s"
    ];
    environment = {
      SEARXNG_PORT = "5002";
      GRANIAN_PORT = "5002";
    };
    volumes = [
      "/srv/apps/searxng:/etc/searxng:rw"
    ];
  };

  systemd.services.podman-searxng = {
    after = [ "podman-gluetun.service" ];
    bindsTo = [ "podman-gluetun.service" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/searxng 0755 apps apps -"
  ];

  system.activationScripts.searxng-config = {
    text = ''
      CONFIG_DIR="/srv/apps/searxng"
      SETTINGS_FILE="$CONFIG_DIR/settings.yml"
      SECRETS_FILE="${searxng-secrets}"

      if [ -f "$SETTINGS_FILE" ] && [ -f "$SECRETS_FILE" ]; then
        echo "Surgically updating SearXNG settings..."
        set -a
        . "$SECRETS_FILE"
        set +a

        if [ -z "''${SEARXNG_SECRET_KEY:-}" ]; then
          SEARXNG_SECRET_KEY=$(${pkgs.openssl}/bin/openssl rand -hex 32)
        fi
        export SEARXNG_SECRET_KEY
        
        ${pkgs.ghostship-config}/bin/ghostship-config set "$SETTINGS_FILE" \
          --secrets-file "$SECRETS_FILE" \
          server.secret_key=env:SEARXNG_SECRET_KEY \
          general.instance_name=literal:"Ghostship Search" \
          server.port=yaml:5002 \
          server.bind_address=literal:"0.0.0.0" \
          server.image_proxy=yaml:true \
          search.safe_search=yaml:0 \
          search.autocomplete=literal:duckduckgo \
          "valkey.url=literal:valkey://searxng-valkey:6379/0" \
          "plugins[searx.plugins.calculator.SXNGPlugin].active=yaml:true" \
          "plugins[searx.plugins.hash_plugin.SXNGPlugin].active=yaml:true" \
          "plugins[searx.plugins.self_info.SXNGPlugin].active=yaml:true" \
          "engines[name=google].disabled=yaml:false" \
          "engines[name=duckduckgo].disabled=yaml:false" \
          "engines[name=brave].disabled=yaml:false" \
          "engines[name=mojeek].disabled=yaml:false" \
          "engines[name=yep].disabled=yaml:false" \
          "engines[name=wikipedia].disabled=yaml:false" \
          "engines[name=annas archive].disabled=yaml:false"
        
        chown 3000:3000 "$SETTINGS_FILE"
      fi
    '';
  };
}
