{ config, lib, pkgs, ... }:

{
  sops.secrets."gluetun-secrets" = {
    sopsFile = ../../secrets.yaml;
    owner = "apps";
    group = "apps";
    mode = "0440";
  };

  sops.secrets."dockerhub-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

  sops.secrets."cloudflared-secrets" = {
    sopsFile = ../../secrets.yaml;
    owner = "apps";
    group = "apps";
    mode = "0440";
  };

  sops.secrets."plex-secrets" = {
    sopsFile = ../../secrets.yaml;
    owner = "apps";
    group = "apps";
    mode = "0440";
  };

  sops.secrets."romm-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

  sops.secrets."sonarr-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

  sops.secrets."radarr-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

  sops.secrets."prowlarr-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

  sops.secrets."nzbget-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

  sops.secrets."bazarr-secrets" = {
    sopsFile = ../../secrets.yaml;
    owner = "apps";
    group = "apps";
    mode = "0440";
  };

  sops.secrets."tautulli-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

  sops.secrets."grimmory-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

  sops.secrets."pricebuddy-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

  sops.secrets."searxng-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

  sops.secrets."hermes-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

  sops.secrets."litellm-secrets" = {
    sopsFile = ../../secrets.yaml;
    mode = "0400";
  };

}
