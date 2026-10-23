let
  flake = builtins.getFlake (toString ../.);
  host = flake.nixosConfigurations.chill-penguin;
  inherit (host.pkgs) lib;
  # Exercise the actual common module and native OCI options with a minimal
  # NixOS consumer; repeated full-fleet extensions make a small regression slow.
  base = flake.inputs.nixpkgs.lib.nixosSystem {
    system = "aarch64-linux";
    modules = [
      ../modules/self-hosted/common.nix
      ({ lib, pkgs, ... }: {
        options.ghostship = {
          notify.package = lib.mkOption {
            type = lib.types.package;
            default = pkgs.hello;
          };
          selfHostedSecrets.projections.dockerhub.path = lib.mkOption {
            type = lib.types.str;
            default = "/run/fixture/registry";
          };
        };
        config.system.stateVersion = "26.05";
      })
    ];
  };
  failure = "Shared network static addresses must be valid IPv4 addresses outside the dynamic allocation range.";
  ambiguous = "Shared network admission requires canonical --flag=value argv and unambiguous native networks.";
  failures =
    fields:
    map (a: a.message) (
      builtins.filter (a: !a.assertion)
        (base.extendModules {
          modules = [
            {
              virtualisation.oci-containers.containers.network-regression = {
                image = "scratch";
              }
              // fields;
            }
          ];
        }).config.assertions
    );
  native = extraOptions: {
    networks = [ "ghostship_net" ];
    inherit extraOptions;
  };
  cli = extraOptions: { inherit extraOptions; };
  rejected = fields: builtins.elem failure (failures fields);
  refused = fields: builtins.elem ambiguous (failures fields);
in
# Actual host modules reject static/dynamic collisions in all admitted forms.
assert builtins.all (a: a.assertion) host.config.assertions;
assert rejected (native [ "--ip=10.89.0.32" ]);
assert rejected (cli [
  "--network=ghostship_net"
  "--ip=10.89.0.254"
]);
assert rejected (cli [ "--net=ghostship_net:alias=probe,ip=10.89.0.99" ]);
assert rejected { networks = [ "ghostship_net:ip=10.89.0.50" ]; };
assert !(rejected (native [ "--ip=10.89.0.16" ]));
assert !(rejected { networks = [ "other:ip=10.89.0.50" ]; });
# Split values and hidden flags cannot evade the admission parser.
assert refused (cli [
  "--network"
  "ghostship_net"
  "--ip"
  "10.89.0.50"
]);
assert refused (native [
  "--label"
  "--ip=10.89.0.50"
]);
assert refused { networks = [ "ghostship_net,other" ]; };
assert !base.config.systemd.services.init-ghostship-net.restartIfChanged;
assert !base.config.systemd.services.init-ghostship-net.stopIfChanged;
assert
  !(builtins.elem "shared-network-range.service" host.config.systemd.services.podman-t3code.requires);
true
