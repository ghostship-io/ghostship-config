{ pkgs, ... }:

let
  n8n-state-dir = "/srv/apps/n8n";
in
{
  virtualisation.oci-containers.containers."n8n" = {
    image = "docker.n8n.io/n8nio/n8n:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:5678/healthz/readiness || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=2m"
      "--health-on-failure=kill"
    ];
    environment = {
      DB_TYPE = "sqlite";
      DB_SQLITE_DATABASE = "/home/node/.n8n/database.sqlite";
      GENERIC_TIMEZONE = "UTC";
      N8N_DIAGNOSTICS_ENABLED = "false";
      N8N_EDITOR_BASE_URL = "https://n8n.ghostship.io";
      N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS = "true";
      N8N_HIRING_BANNER_ENABLED = "false";
      N8N_HOST = "n8n.ghostship.io";
      N8N_METRICS = "true";
      N8N_PATH = "/";
      N8N_PERSONALIZATION_ENABLED = "false";
      N8N_PORT = "5678";
      N8N_PROTOCOL = "https";
      N8N_PUBLIC_API_DISABLED = "false";
      N8N_PUBLIC_API_SWAGGERUI_DISABLED = "true";
      N8N_VERSION_NOTIFICATIONS_ENABLED = "false";
      QUEUE_HEALTH_CHECK_ACTIVE = "true";
      TZ = "UTC";
      WEBHOOK_URL = "https://n8n.ghostship.io/";
    };
    volumes = [
      "${n8n-state-dir}:/home/node/.n8n:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d ${n8n-state-dir} 0755 1000 1000 -"
  ];

}
