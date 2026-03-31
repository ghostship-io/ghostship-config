{ config, lib, pkgs, ... }:

let
  pricebuddy-secrets = config.sops.secrets."pricebuddy-secrets".path;
  pricebuddy-env = "/srv/apps/pricebuddy/pricebuddy.env";
  pricebuddy-db-env = "/srv/apps/pricebuddy/pricebuddy-db.env";
  pricebuddy-agent-env = "/srv/apps/pricebuddy/pricebuddy-agent.env";
  pricebuddy-agent-token-script = pkgs.writeShellScriptBin "pricebuddy-agent-token" ''
    set -eu

    podman_bin="${pkgs.podman}/bin/podman"
    token_file="${pricebuddy-agent-env}"
    container="pricebuddy"

    if [ -s "$token_file" ] && ${pkgs.gnugrep}/bin/grep -q '^PRICEBUDDY_API_TOKEN=' "$token_file"; then
      exit 0
    fi

    echo "Waiting for PriceBuddy to become ready for agent token minting..."
    for _ in $(${pkgs.coreutils}/bin/seq 1 120); do
      if token=$(
        "$podman_bin" exec -i "$container" php <<'PHP'
<?php
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

$email = env('APP_USER_EMAIL');
$user = \App\Models\User::where('email', $email)->first();
if (! $user) {
    fwrite(STDERR, "PriceBuddy bootstrap user not found\n");
    exit(1);
}

echo $user->createToken('ghostship-agent')->plainTextToken;
PHP
      ); then
        if [ -n "$token" ]; then
          break
        fi
      fi
      ${pkgs.coreutils}/bin/sleep 1
    done

    if [ -z "$token" ]; then
      echo "Failed to mint a PriceBuddy API token" >&2
      exit 1
    fi

    ${pkgs.coreutils}/bin/mkdir -p "$(${pkgs.coreutils}/bin/dirname "$token_file")"
    {
      printf 'PRICEBUDDY_API_TOKEN=%s\n' "$token"
    } > "$token_file"
    ${pkgs.coreutils}/bin/chmod 600 "$token_file"
  '';
in
{
  virtualisation.oci-containers.containers."pricebuddy" = {
    image = "docker.io/jez500/pricebuddy:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=php -r 'exit(@file_get_contents(\"http://127.0.0.1/\") === false ? 1 : 0);' || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "/srv/apps/pricebuddy/storage:/app/storage:rw"
      "/srv/apps/pricebuddy/pricebuddy.env:/app/.env:rw"
    ];
  };

  virtualisation.oci-containers.containers."pricebuddy-db" = {
    image = "docker.io/library/mysql:8.2";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=mysqladmin ping -h 127.0.0.1 || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environmentFiles = [
      pricebuddy-db-env
    ];
    volumes = [
      "/srv/apps/pricebuddy-db:/var/lib/mysql:rw"
    ];
  };

  virtualisation.oci-containers.containers."pricebuddy-scraper" = {
    image = "docker.io/jez500/seleniumbase-scrapper:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=python3 -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:3000/\", timeout=5).read(1)' || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
  };

  systemd.services.podman-pricebuddy = {
    after = [
      "podman-pricebuddy-db.service"
      "podman-pricebuddy-scraper.service"
    ];
    wants = [
      "podman-pricebuddy-db.service"
      "podman-pricebuddy-scraper.service"
    ];
    postStart = ''
      ${pricebuddy-agent-token-script}/bin/pricebuddy-agent-token
    '';
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/pricebuddy 0755 apps apps -"
    "d /srv/apps/pricebuddy/storage 0755 apps apps -"
    "d /srv/apps/pricebuddy-db 0755 apps apps -"
  ];

  system.activationScripts.pricebuddy-config = {
    text = ''
      CONFIG_DIR="/srv/apps/pricebuddy"
      APP_ENV_FILE="${pricebuddy-env}"
      DB_ENV_FILE="${pricebuddy-db-env}"

      if [ -f "${pricebuddy-secrets}" ]; then
        echo "Surgically updating PriceBuddy env files..."
        set -a
        . "${pricebuddy-secrets}"
        set +a

        ${pkgs.coreutils}/bin/mkdir -p "$CONFIG_DIR"

        cat > "$APP_ENV_FILE" <<EOF
        APP_KEY=$PRICEBUDDY_APP_KEY
APP_ENV=production
APP_DEBUG=false
        APP_USER_EMAIL=$PRICEBUDDY_APP_USER_EMAIL
        APP_USER_PASSWORD=$PRICEBUDDY_APP_USER_PASSWORD
        DB_HOST=pricebuddy-db
DB_PORT=3306
DB_USERNAME=$PRICEBUDDY_DB_USER
DB_PASSWORD=$PRICEBUDDY_DB_PASS
DB_DATABASE=pricebuddy
SCRAPER_BASE_URL=http://pricebuddy-scraper:3000
AFFILIATE_ENABLED=false
EOF

        cat > "$DB_ENV_FILE" <<EOF
MYSQL_DATABASE=pricebuddy
MYSQL_USER=$PRICEBUDDY_DB_USER
MYSQL_PASSWORD=$PRICEBUDDY_DB_PASS
MYSQL_ROOT_PASSWORD=$PRICEBUDDY_MYSQL_ROOT_PASS
MYSQL_ROOT_HOST=127.0.0.1
EOF

        ${pkgs.coreutils}/bin/chmod 600 "$APP_ENV_FILE" "$DB_ENV_FILE"
        ${pkgs.coreutils}/bin/chown 3000:3000 "$APP_ENV_FILE" "$DB_ENV_FILE"
      fi
    '';
  };
}
