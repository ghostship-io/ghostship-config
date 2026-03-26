{ config, lib, pkgs, ... }:

let
  tautulli-secrets = config.sops.secrets."tautulli-secrets".path;
in
{
  virtualisation.oci-containers.containers."tautulli" = {
    image = "lscr.io/linuxserver/tautulli:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider http://127.0.0.1:8181/ || exit 1"
      "--health-interval=1m"
      "--health-timeout=10s"
      "--health-retries=3"
      "--health-start-period=30s"
    ];
    environment = {
      TZ = "UTC";
      PUID = "3000";
      PGID = "3000";
    };
    volumes = [
      "/srv/apps/tautulli:/config"
      "/srv/apps/plex/Library/Application Support/Plex Media Server/Logs:/logs:ro"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/tautulli 0755 apps apps -"
  ];

  systemd.services.podman-tautulli.after = [ "sops-nix.service" ];
  systemd.services.podman-tautulli.requires = [ "sops-nix.service" ];
  systemd.services.podman-tautulli.preStart = ''
    CONFIG_FILE="/srv/apps/tautulli/config.ini"

    if [ ! -d "/srv/apps/tautulli" ]; then
      echo "Tautulli config directory not found, skipping start hook"
      exit 0
    fi

    if [ -f "$CONFIG_FILE" ]; then
      echo "Surgically updating Tautulli config.ini..."
      ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" \
        --secrets-file "${tautulli-secrets}" \
        General.first_run_complete=literal:1 \
        General.http_proxy=literal:1 \
        General.show_advanced_settings=literal:1 \
        General.launch_startup=literal:0 \
        General.home_sections=literal:"current_activity, watch_stats, library_stats, recently_added" \
        General.home_library_cards=literal:"4, 1, 5, 3" \
        General.home_stats_cards=literal:"top_movies, popular_movies, top_tv, popular_tv, top_music, popular_music, last_watched, top_libraries, top_users, top_platforms, most_concurrent" \
        PMS.pms_name=literal:"Ghostship Plex" \
        PMS.pms_ip=literal:plex \
        PMS.pms_port=literal:32400 \
        PMS.pms_ssl=literal:0 \
        PMS.pms_url=literal:http://plex:32400 \
        PMS.pms_logs_folder=literal:/logs \
        PMS.pms_client_id=literal:"4ac0a66d-79e0-4387-9322-11e6d31c1e48" \
        PMS.pms_identifier=literal:9e16052c701c68f20d9955220df9f1a0e8acf57e \
        PMS.pms_token=env:TAUTULLI_PLEX_TOKEN \
        General.api_key=env:TAUTULLI_API_KEY
      echo "Tautulli config updated"
    else
      echo "Tautulli config.ini not found, skipping start hook"
    fi
  '';
}
