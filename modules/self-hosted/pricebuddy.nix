{ config, lib, pkgs, ... }:

let
  pricebuddy-secrets = config.sops.secrets."pricebuddy-secrets".path;
  pricebuddy-env = "/srv/apps/pricebuddy/pricebuddy.env";
  pricebuddy-db-env = "/srv/apps/pricebuddy/pricebuddy-db.env";
  pricebuddy-agent-env = "/srv/apps/pricebuddy/pricebuddy-agent.env";
  pricebuddy-env-sync = pkgs.writeShellScriptBin "pricebuddy-env-sync" ''
    set -eu

    config_dir="/srv/apps/pricebuddy"
    app_env_file="${pricebuddy-env}"
    db_env_file="${pricebuddy-db-env}"
    agent_env_file="${pricebuddy-agent-env}"

    if [ ! -f "${pricebuddy-secrets}" ]; then
      echo "Missing PriceBuddy secret file: ${pricebuddy-secrets}" >&2
      exit 1
    fi

    set -a
    . "${pricebuddy-secrets}"
    set +a

    ${pkgs.coreutils}/bin/mkdir -p "$config_dir"

    cat > "$app_env_file" <<EOF
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

    cat > "$db_env_file" <<EOF
MYSQL_DATABASE=pricebuddy
MYSQL_USER=$PRICEBUDDY_DB_USER
MYSQL_PASSWORD=$PRICEBUDDY_DB_PASS
MYSQL_ROOT_PASSWORD=$PRICEBUDDY_MYSQL_ROOT_PASS
MYSQL_ROOT_HOST=127.0.0.1
EOF

    ${pkgs.coreutils}/bin/chmod 600 "$app_env_file" "$db_env_file"
    ${pkgs.coreutils}/bin/chown 3000:3000 "$app_env_file" "$db_env_file"
  '';
  pricebuddy-pre-start = pkgs.writeShellScriptBin "pricebuddy-pre-start" ''
    set -eu

    ${pricebuddy-env-sync}/bin/pricebuddy-env-sync
  '';
  pricebuddy-token-sync = pkgs.writeShellScriptBin "pricebuddy-token-sync" ''
    set -eu

    podman_bin="${pkgs.podman}/bin/podman"
    token_file="${pricebuddy-agent-env}"
    container="pricebuddy"

    if [ ! -s "$token_file" ]; then
      echo "Missing PriceBuddy agent token file: $token_file" >&2
      exit 1
    fi

    token="$(${pkgs.gnused}/bin/sed -n 's/^PRICEBUDDY_API_TOKEN=//p' "$token_file" | ${pkgs.coreutils}/bin/head -n 1)"
    if [ -z "$token" ]; then
      echo "PriceBuddy agent token file does not contain PRICEBUDDY_API_TOKEN" >&2
      exit 1
    fi

    case "$token" in
      \"*\")
        token="''${token#\"}"
        token="''${token%\"}"
        ;;
    esac

    echo "Waiting for PriceBuddy to become ready for agent token sync..."
    token_id=""
    for _ in $(${pkgs.coreutils}/bin/seq 1 120); do
      if token_id="$("$podman_bin" exec -i -e PRICEBUDDY_API_TOKEN="$token" "$container" php <<'PHP'
<?php
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

$email = env('APP_USER_EMAIL');
$token = env('PRICEBUDDY_API_TOKEN');

if (! $token) {
    fwrite(STDERR, "PriceBuddy API token is missing\n");
    exit(1);
}

$user = \App\Models\User::where('email', $email)->first();
if (! $user) {
    fwrite(STDERR, "PriceBuddy bootstrap user not found\n");
    exit(1);
}

$tokenHash = hash('sha256', $token);
$query = \Illuminate\Support\Facades\DB::table('personal_access_tokens')
    ->where('tokenable_type', \App\Models\User::class)
    ->where('tokenable_id', $user->id)
    ->where('name', 'ghostship-agent');
$existing = $query->first();
$payload = [
    'tokenable_type' => \App\Models\User::class,
    'tokenable_id' => $user->id,
    'name' => 'ghostship-agent',
    'token' => $tokenHash,
    'abilities' => json_encode(['*']),
    'last_used_at' => null,
    'expires_at' => null,
    'updated_at' => now(),
];

if ($existing) {
    $query->update($payload);
    $tokenId = $existing->id;
} else {
    $payload['created_at'] = now();
    $tokenId = \Illuminate\Support\Facades\DB::table('personal_access_tokens')->insertGetId($payload);
}
echo $tokenId;
PHP
      )"; then
        if [ -n "$token_id" ]; then
          break
        fi
      fi
      ${pkgs.coreutils}/bin/sleep 1
    done

    if [ -z "$token_id" ]; then
      echo "Failed to sync the PriceBuddy API token" >&2
      exit 1
    fi

    cat > "$token_file" <<EOF
PRICEBUDDY_API_TOKEN="''${token_id}|''${token}"
EOF

    ${pkgs.coreutils}/bin/chmod 600 "$token_file"
    ${pkgs.coreutils}/bin/chown 3000:3000 "$token_file"
  '';
in
{
  virtualisation.oci-containers.containers."pricebuddy" = {
    image = "docker.io/jez500/pricebuddy:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "3000:3000";
    environmentFiles = [
      pricebuddy-env
    ];
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
    user = "3000:3000";
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
    preStart = ''
      ${pricebuddy-pre-start}/bin/pricebuddy-pre-start
    '';
    postStart = ''
      ${pricebuddy-token-sync}/bin/pricebuddy-token-sync
    '';
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/pricebuddy 0755 apps apps -"
    "d /srv/apps/pricebuddy/storage 0755 apps apps -"
    "d /srv/apps/pricebuddy-db 0755 apps apps -"
  ];

}
