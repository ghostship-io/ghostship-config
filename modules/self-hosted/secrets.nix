{
  config,
  lib,
  pkgs,
  ...
}:

let
  recipients = import ../../secrets/recipients.nix;
  catalog = import ../../secrets/catalog.nix { inherit recipients; };
  unitCatalog = lib.filterAttrs (
    _: meta:
    builtins.elem meta.recipientGroup [
      "self-hosted-runtime"
      "shared-runtime"
    ]
  ) catalog.units;
  projectionCatalog = lib.filterAttrs (
    name: _: !(lib.hasPrefix "emulation-" name)
  ) catalog.projections;
  projectionDir = "/run/ghostship-secrets";

  mkAgeSecret =
    meta:
    {
      file = meta.path;
    }
    // lib.optionalAttrs (meta ? owner) { owner = meta.owner; }
    // lib.optionalAttrs (meta ? group) { group = meta.group; }
    // lib.optionalAttrs (meta ? mode) { mode = meta.mode; };

  projectionRenderer = pkgs.writeTextFile {
    name = "ghostship-secret-project";
    destination = "/bin/ghostship-secret-project";
    executable = true;
    text = ''
      #!${pkgs.python3}/bin/python3
      import grp
      import json
      import os
      import pwd
      import shlex
      import sys
      import tempfile
      from pathlib import Path

      SPEC = json.loads(${
        builtins.toJSON (
          builtins.toJSON {
            units = lib.mapAttrs (name: _: {
              path = (builtins.getAttr name config.age.secrets).path;
            }) unitCatalog;
            projections = lib.mapAttrs (
              name: meta:
              meta
              // {
                path = "${projectionDir}/" + meta.fileName;
                containerPath = "${projectionDir}/" + meta.fileName + ".container";
              }
            ) projectionCatalog;
          }
        )
      })

      ${builtins.readFile ./secret-project.py}
    '';
  };
in
{
  options.ghostship.selfHostedSecrets = lib.mkOption {
    type = lib.types.attrs;
    default = { };
    description = "Read-only self-hosted secret unit and projection metadata.";
  };

  config = {
    age.identityPaths = [ "/etc/ssh/ssh_host_ed25519_key" ];

    age.secrets = lib.mapAttrs (_: meta: mkAgeSecret meta) unitCatalog;

    ghostship.selfHostedSecrets = {
      units = lib.mapAttrs (
        name: meta: meta // { path = (builtins.getAttr name config.age.secrets).path; }
      ) unitCatalog;
      projections = lib.mapAttrs (
        name: meta:
        meta
        // {
          path = "${projectionDir}/" + meta.fileName;
          containerPath = "${projectionDir}/" + meta.fileName + ".container";
        }
      ) projectionCatalog;
      render = projectionRenderer;
    };

    systemd.tmpfiles.rules = [
      "d ${projectionDir} 0755 root root -"
    ];

    system.activationScripts.ghostship-secret-projections = {
      deps = [
        "agenixInstall"
        "users"
      ];
      text = lib.concatStringsSep "\n" (
        map (name: "${projectionRenderer}/bin/ghostship-secret-project ${lib.escapeShellArg name}") (
          builtins.attrNames projectionCatalog
        )
      );
      supportsDryActivation = false;
    };
  };
}
