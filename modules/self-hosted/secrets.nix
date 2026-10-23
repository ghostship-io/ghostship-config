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
  # Modules add consumer-scoped projections (for example the MCP service
  # executor) through ghostship.secretProjections; names must not collide.
  projectionCatalog =
    lib.filterAttrs (name: _: !(lib.hasPrefix "emulation-" name)) catalog.projections
    // config.ghostship.secretProjections;
  projectionDir = "/run/ghostship-secrets";

  mkAgeSecret =
    meta:
    {
      file = meta.path;
    }
    // lib.optionalAttrs (meta ? owner) { owner = meta.owner; }
    // lib.optionalAttrs (meta ? group) { group = meta.group; }
    // lib.optionalAttrs (meta ? mode) { mode = meta.mode; };

  mkProjectionRenderer = names: pkgs.writeTextFile {
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
            }) (lib.filterAttrs (name: _: builtins.elem name (
              lib.concatMap (projection: lib.concatMap (field:
                lib.optional (field ? unit) field.unit
              ) (builtins.attrValues projectionCatalog.${projection}.fields)) names
            )) unitCatalog);
            projections = lib.mapAttrs (
              name: meta:
              meta
              // {
                path = "${projectionDir}/" + meta.fileName;
                containerPath = "${projectionDir}/" + meta.fileName + ".container";
              }
            ) (lib.getAttrs names projectionCatalog);
          }
        )
      })

      ${builtins.readFile ./secret-project.py}
    '';
  };
  projectionRenderer = mkProjectionRenderer (builtins.attrNames projectionCatalog);
in
{
  options.ghostship.secretProjections = lib.mkOption {
    type = lib.types.attrsOf lib.types.attrs;
    default = { };
    description = ''
      Additional secret projections in the secrets/catalog.nix projection
      format. A field is either { unit, key } (a secret value) or { value }
      (a non-secret literal such as a base URL). `raw = true` writes the main
      file unquoted too, for dotenv readers that do not unquote shell syntax.
    '';
  };

  options.ghostship.selfHostedSecrets = lib.mkOption {
    type = lib.types.attrs;
    default = { };
    description = "Read-only self-hosted secret unit and projection metadata.";
  };

  config = {
    assertions = [
      {
        assertion = lib.all (name: !(builtins.hasAttr name catalog.projections)) (
          builtins.attrNames config.ghostship.secretProjections
        );
        message = "ghostship.secretProjections must not redefine a secrets/catalog.nix projection.";
      }
    ];

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
      # A container unit depends only on its own projection, so an unrelated
      # secret/catalog addition cannot change its preStart derivation.
      renderFor = name: mkProjectionRenderer [ name ];
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
