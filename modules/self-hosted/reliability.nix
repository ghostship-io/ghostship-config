{
  config,
  lib,
  pkgs,
  ...
}:
let
  containers = config.virtualisation.oci-containers.containers;
  # These images include wget; do not invent HTTP checks for scheduled jobs.
  endpoints = {
    sonarr = "http://127.0.0.1:8989/ping";
    radarr = "http://127.0.0.1:7878/ping";
    prowlarr = "http://127.0.0.1:9696/ping";
    plex = "http://127.0.0.1:32400/identity";
    muximux = "http://127.0.0.1/";
  };
  active = lib.filterAttrs (name: _: name != "codex") containers;
in
{
  virtualisation.oci-containers.containers = lib.mkMerge [
    (lib.mapAttrs (name: url: {
      podman.sdnotify = "healthy";
      extraOptions = [
        "--health-cmd=wget -q -O /dev/null --timeout=5 ${url}"
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=2m"
        "--health-on-failure=kill"
      ];
    }) endpoints)
  ];

  systemd.services = lib.mapAttrs' (
    name: container:
    let
      usesNetwork = builtins.elem "--network=ghostship_net" container.extraOptions;
      usesNas = lib.any (v: lib.hasPrefix "/mnt/share/" v) container.volumes;
      database =
        {
          romm = "romm-db";
          grimmory = "grimmory-db";
        }
        .${name} or null;
    in
    lib.nameValuePair "podman-${name}" {
      after =
        lib.optional usesNetwork "init-ghostship-net.service"
        ++ lib.optional (database != null) "podman-${database}.service";
      requires =
        lib.optional usesNetwork "init-ghostship-net.service"
        ++ lib.optional (database != null) "podman-${database}.service";
      unitConfig.RequiresMountsFor = lib.optional usesNas "/mnt/share";
      serviceConfig.TimeoutStartSec = lib.mkDefault "10min";
      serviceConfig.UMask = lib.mkDefault "0077";
      preStart = lib.mkBefore (
        lib.optionalString usesNas ''
          ${pkgs.util-linux}/bin/findmnt -rn -t nfs,nfs4 --mountpoint /mnt/share >/dev/null || {
            echo "Required NAS filesystem is not mounted" >&2
            exit 1
          }
        ''
      );
    }
  ) active;
}
