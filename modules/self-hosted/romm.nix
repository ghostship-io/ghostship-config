{ config, lib, pkgs, ... }:

let
  romm-secrets = config.sops.secrets."romm-secrets".path;
in
{
  virtualisation.oci-containers.containers."romm" = {
    image = "rommapp/romm:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:8080/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
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
      "/srv/apps/romm/nginx/default.conf.template:/etc/nginx/templates/default.conf.template:ro"
      "/mnt/share/Library/ROMs:/romm/library:rw"
      "/mnt/share/Library/ROMs/.romm:/romm/assets:rw"
    ];
  };

  systemd.services.podman-romm = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/romm 0755 apps apps -"
    "d /srv/apps/romm/resources 0755 apps apps -"
    "d /srv/apps/romm/redis-data 0755 apps apps -"
    "d /srv/apps/romm/config 0755 apps apps -"
    "d /srv/apps/romm/nginx 0755 apps apps -"
  ];

  systemd.services.podman-romm.preStart = ''
    CONFIG_DIR="/srv/apps/romm"
    CONFIG_FILE="$CONFIG_DIR/config/config.yml"
    ENV_FILE="$CONFIG_DIR/romm.env"
    NGINX_TEMPLATE="$CONFIG_DIR/nginx/default.conf.template"

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

    echo "Creating patched Nginx template..."
    mkdir -p "$(dirname "$NGINX_TEMPLATE")"
    cat > "$NGINX_TEMPLATE" <<EOF
# This template is used to generate the default.conf file for the nginx server,
# by using \`envsubst\` to replace the environment variables in the template with
# their actual values.

# Helper to get scheme regardless if we are behind a proxy or not
map \$http_x_forwarded_proto \$forwardscheme {
    default \$scheme;
    https https;
}

# Disable manifest fetches only when RomM is rendered inside an iframe.
# This tests whether the PWA manifest path is the embed-specific trigger.
map \$http_sec_fetch_dest \$romm_csp {
    default        "frame-ancestors https://*.ghostship.io https://ghostship.io https://apps.ghostship.io;";
    iframe         "frame-ancestors https://*.ghostship.io https://ghostship.io https://apps.ghostship.io; manifest-src 'none';";
}

# COEP and COOP headers for cross-origin isolation, which are set only for the
# EmulatorJS player path, to enable SharedArrayBuffer support, which is needed
# for multi-threaded cores.
map \$request_uri \$coep_header {
    default        "";
    ~^/rom/.*/ejs$ "require-corp";
}
map \$request_uri \$coop_header {
    default        "";
    ~^/rom/.*/ejs$ "same-origin";
}

server {
    root /var/www/html;
    listen ''${ROMM_PORT};
    ''${IPV6_LISTEN}
    server_name localhost;

    proxy_set_header Host \$http_host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$forwardscheme;

    location / {
        add_header Content-Security-Policy \$romm_csp always;
        try_files \$uri \$uri/ /index.html;
        proxy_redirect off;
        add_header Access-Control-Allow-Origin *;
        add_header Access-Control-Allow-Methods *;
        add_header Access-Control-Allow-Headers *;
        # These are disabled to avoid renderer crashes in iframes (STATUS_BREAKPOINT)
        # add_header Cross-Origin-Embedder-Policy \$coep_header;
        # add_header Cross-Origin-Opener-Policy \$coop_header;
    }

    # Static files
    location /assets {
        try_files \$uri \$uri/ =404;
    }

    # OpenAPI for swagger and redoc
    location /openapi.json {
        proxy_pass http://wsgi_server;
    }

    # Backend api calls
    location /api {
        proxy_pass http://wsgi_server;
        proxy_request_buffering off;
        proxy_buffering off;
    }
    location ~ ^/(ws|netplay) {
        proxy_pass http://wsgi_server;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Internally redirect download requests
    location /library/ {
        internal;
        alias "''${ROMM_BASE_PATH}/library/";
    }

    # Internal decoding endpoint, used to decode base64 encoded data
    location /decode {
        internal;
        js_content decode.decodeBase64;
    }
}
EOF
    chown 3000:3000 "$NGINX_TEMPLATE"

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
