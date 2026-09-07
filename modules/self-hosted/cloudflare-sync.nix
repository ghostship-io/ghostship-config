{
  config,
  lib,
  pkgs,
  ...
}:
let
  sync = pkgs.writeShellApplication {
    name = "ghostship-cloudflare-sync";
    runtimeInputs = [
      pkgs.python3
      pkgs.util-linux
    ];
    excludeShellChecks = [ "SC1091" ];
    text = ''
      set -a
      . ${config.ghostship.selfHostedSecrets.projections.cloudflare-management.path}
      set +a
      exec flock -w 60 /run/ghostship-cloudflare.lock \
        python ${./cloudflare-sync.py} ${config.ghostship.appRegistryFile} "$@"
    '';
  };
in
{
  environment.systemPackages = [ sync ];
  assertions = [
    {
      assertion = lib.all (
        name:
        name == "cloudflare-management"
        || !(lib.any (field: field.unit == "cloudflare" && field.key == "API_TOKEN") (
          builtins.attrValues config.ghostship.selfHostedSecrets.projections.${name}.fields
        ))
      ) (builtins.attrNames config.ghostship.selfHostedSecrets.projections);
      message = "Cloudflare management credentials must not enter application projections.";
    }
  ];
  systemd.services.ghostship-cloudflare-sync = {
    description = "Reconcile Nix-managed Cloudflare service routes and DNS";
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    onFailure = [ "ghostship-failure@%n.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${sync}/bin/ghostship-cloudflare-sync --apply";
      StateDirectory = "ghostship-cloudflare";
      StateDirectoryMode = "0700";
      UMask = "0077";
      TimeoutStartSec = "10min";
    };
  };
  systemd.timers.ghostship-cloudflare-sync = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "10min";
      OnUnitActiveSec = "6h";
      RandomizedDelaySec = "5min";
    };
  };
}
