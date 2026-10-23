{ config, lib, pkgs, ... }:
let
  cfg = config.ghostship.containerRuntimes;
  root = name: "/var/lib/ghostship-container-runtimes/${name}";
in
{
  options.ghostship.containerRuntimes = lib.mkOption {
    default = { };
    description = "Code delivered separately from stable container images.";
    type = lib.types.attrsOf (lib.types.submodule {
      options = {
        runtime = lib.mkOption { type = lib.types.package; };
        extraPackages = lib.mkOption { type = lib.types.listOf lib.types.package; default = [ ]; };
        restart = lib.mkOption { type = lib.types.bool; default = true; };
      };
    });
  };
  config = {
    virtualisation.oci-containers.containers = lib.mapAttrs (name: _: {
      volumes = [
        "${root name}/store/nix:/nix:ro"
        "${root name}/state:/run/ghostship-runtime:ro"
      ];
    }) cfg;
    systemd.services = lib.mkMerge (lib.mapAttrsToList (name: runtime: {
      "ghostship-runtime-${name}" = {
        description = "Publish the managed ${name} runtime without rebuilding its image";
        wantedBy = [ "multi-user.target" ];
        before = [ "podman-${name}.service" ];
        serviceConfig = { Type = "oneshot"; RemainAfterExit = true; UMask = "0022"; };
        script = ''
          set -eu
          install -d -m0755 ${root name}/store ${root name}/state
          ${pkgs.nix}/bin/nix copy --no-check-sigs \
            --to 'local?root=${root name}/store' \
            ${lib.escapeShellArgs (map toString ([ runtime.runtime pkgs.bash pkgs.coreutils pkgs.cacert ] ++ runtime.extraPackages))}
          install -d -m0755 ${root name}/store/nix/var/nix/gcroots/managed
          ${lib.concatMapStringsSep "\n" (package:
            "ln -sfn ${package} ${root name}/store/nix/var/nix/gcroots/managed/${builtins.baseNameOf (toString package)}"
          ) ([ runtime.runtime pkgs.bash pkgs.coreutils pkgs.cacert ] ++ runtime.extraPackages)}
          ${pkgs.python3}/bin/python3 ${./container-runtime-publish.py} \
            --state ${root name}/state --runtime ${runtime.runtime} \
            --unit podman-${name}.service ${lib.optionalString (!runtime.restart) "--no-restart"} \
            --systemctl ${pkgs.systemd}/bin/systemctl
        '';
      };
      # Wants supplies boot ordering without stop/restart propagation from the
      # publisher. A failed publication leaves startup unable to find its code.
      "podman-${name}" = {
        wants = [ "ghostship-runtime-${name}.service" ];
        after = [ "ghostship-runtime-${name}.service" ];
      };
    }) cfg);
  };
}
