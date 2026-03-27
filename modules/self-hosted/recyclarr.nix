{ config, lib, pkgs, ... }:

let
  sonarr-secrets = config.sops.secrets."sonarr-secrets".path;
  radarr-secrets = config.sops.secrets."radarr-secrets".path;
in
{
  virtualisation.oci-containers.containers."recyclarr" = {
    image = "ghcr.io/recyclarr/recyclarr:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
    ];
    environment = {
      TZ = "UTC";
      CRON_SCHEDULE = "@daily";
    };
    volumes = [
      "/srv/apps/recyclarr:/config:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/recyclarr 0755 apps apps -"
  ];

  system.activationScripts.recyclarr-config = {
    text = ''
      CONFIG_FILE="/srv/apps/recyclarr/recyclarr.yml"
      
      if [ -f "$CONFIG_FILE" ] && [ -f "${sonarr-secrets}" ] && [ -f "${radarr-secrets}" ]; then
        echo "Surgically updating Recyclarr config..."
        set -a
        . "${sonarr-secrets}"
        . "${radarr-secrets}"
        set +a

        recyclarr_args=(
          --secrets-file "${sonarr-secrets}"
          --secrets-file "${radarr-secrets}"
          sonarr.sonarr.base_url=literal:http://sonarr:8989
          sonarr.sonarr.api_key=env:SONARR_API_KEY
          sonarr.sonarr.quality_definition.type=literal:series
          "sonarr.sonarr.quality_profiles[name=Optimal].reset_unmatched_scores.enabled=literal:true"
          "sonarr.sonarr.quality_profiles[name=Optimal].upgrade.allowed=literal:true"
          "sonarr.sonarr.quality_profiles[name=Optimal].upgrade.until_quality=literal:HDTV-1080p"
          "sonarr.sonarr.custom_formats[0].trash_ids[0]=literal:c9eafd50846d299b862ca9bb6ea91950"
          "sonarr.sonarr.custom_formats[0].assign_scores_to[name=Optimal].score=literal:900"
          "sonarr.sonarr.custom_formats[1].trash_ids[0]=literal:cddfb4e32db826151d97352b8e37c648"
          "sonarr.sonarr.custom_formats[1].assign_scores_to[name=Optimal].score=literal:800"
          radarr.radarr.base_url=literal:http://radarr:7878
          radarr.radarr.api_key=env:RADARR_API_KEY
          radarr.radarr.quality_definition.type=literal:movie
          "radarr.radarr.quality_profiles[name=Optimal].reset_unmatched_scores.enabled=literal:true"
          "radarr.radarr.quality_profiles[name=Optimal].upgrade.allowed=literal:true"
          "radarr.radarr.quality_profiles[name=Optimal].upgrade.until_quality=literal:HDTV-1080p"
          "radarr.radarr.custom_formats[0].trash_ids[0]=literal:9170d55c319f4fe40da8711ba9d8050d"
          "radarr.radarr.custom_formats[0].assign_scores_to[name=Optimal].score=literal:900"
          "radarr.radarr.custom_formats[1].trash_ids[0]=literal:2899d84dc9372de3408e6d8cc18e9666"
          "radarr.radarr.custom_formats[1].assign_scores_to[name=Optimal].score=literal:800"
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${recyclarr_args[@]}"
        chown 3000:3000 "$CONFIG_FILE"
      fi
    '';
  };
}
