{
  config,
  lib,
  pkgs,
  ...
}:
let
  inherit (lib) mkOption types;
  apps = config.ghostship.apps;
  spec = pkgs.writeText "ghostship-apps.json" (builtins.toJSON apps);
  python = pkgs.python3.withPackages (ps: [
    ps.lxml
    ps.ruamel-yaml
  ]);
  dashboards = pkgs.writeShellScriptBin "ghostship-dashboard-sync" ''
    set -euo pipefail
    exec ${python}/bin/python ${./dashboard-sync.py} \
      ${../common/scripts/ghostship-config.py} ${spec} "$@"
  '';
in
{
  options.ghostship.apps = mkOption {
    default = { };
    description = "Per-container inventory shared by Cloudflare and both dashboards.";
    type = types.attrsOf (
      types.submodule (
        { name, config, ... }: {
          options = {
            name = mkOption {
              type = types.str;
              default = name;
            };
            container = mkOption {
              type = types.str;
              default = name;
            };
            group = mkOption {
              type = types.str;
              default = "Services";
            };
            description = mkOption {
              type = types.str;
              default = "";
            };
            icon = mkOption {
              type = types.str;
              default = "sh-${name}";
            };
            order = mkOption {
              type = types.int;
              default = 100;
            };
            hostname = mkOption {
              type = types.nullOr types.str;
              default = null;
            };
            origin = mkOption {
              type = types.nullOr types.str;
              default = null;
            };
            healthPath = mkOption {
              type = types.nullOr types.str;
              default = null;
              description = "Public internal HTTP endpoint for Uptime Kuma.";
            };
            cloudflareBypassApproval = mkOption {
              type = types.nullOr (types.strMatching ".+");
              default = null;
              description = "Reference to explicit user approval for direct Internet access outside Cloudflare Access. Never inferred from app/client requirements.";
            };
            cloudflareBypassPaths = mkOption {
              type = types.listOf (types.strMatching "/[a-z0-9-]+");
              default = [ ];
              description = "Exact request paths Cloudflare Access bypasses on this hostname; the origin must authenticate them itself. Requires cloudflareBypassApproval and an AppArmor profile.";
            };
            public = mkOption {
              type = types.bool;
              default = false;
              description = "Internet reachable without the Cloudflare Access gate (including router forwards). Requires an AppArmor profile.";
            };
            apparmorProfile = mkOption {
              type = types.nullOr (types.strMatching "[a-zA-Z0-9_-]+");
              default = null;
              description = "Declared AppArmor policy attached to this application's container.";
            };
            widget = mkOption {
              type = types.attrs;
              default = { };
            };
            muximux = {
              enable = mkOption {
                type = types.bool;
                default = config.hostname != null && name != "muximux";
              };
              url = mkOption {
                type = types.nullOr types.str;
                default = if config.hostname == null then null else "https://${config.hostname}";
              };
              icon = mkOption {
                type = types.str;
                default = "fa-cube";
              };
              color = mkOption {
                type = types.str;
                default = "#109f61";
              };
              dropdown = mkOption {
                type = types.bool;
                default = true;
              };
              label = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Nav label; null uses the app name, empty string hides the text.";
              };
            };
          };
        }
      )
    );
  };
  options.ghostship.appRegistryFile = mkOption {
    type = types.path;
    readOnly = true;
  };
  config = {
    ghostship.appRegistryFile = spec;
    environment.systemPackages = [ dashboards ];
    assertions = [
      {
        assertion = lib.all (
          app: builtins.hasAttr app.container config.virtualisation.oci-containers.containers
        ) (builtins.attrValues apps);
        message = "Every Ghostship app must refer to a declared container.";
      }
      {
        assertion = lib.all (name: lib.any (app: app.container == name) (builtins.attrValues apps)) (
          builtins.attrNames config.virtualisation.oci-containers.containers
        );
        message = "Every declared container must have a Homepage service entry.";
      }
      {
        assertion =
          let
            names = map (app: app.name) (builtins.attrValues apps);
          in
          builtins.length names == builtins.length (lib.unique names);
        message = "Ghostship dashboard display names must be unique.";
      }
      {
        assertion =
          let
            names = lib.filter (name: name != null) (map (app: app.hostname) (builtins.attrValues apps));
          in
          builtins.length names == builtins.length (lib.unique names);
        message = "Ghostship Cloudflare hostnames must be unique.";
      }
      {
        assertion = lib.all (app: (app.hostname == null) == (app.origin == null)) (
          builtins.attrValues apps
        );
        message = "Ghostship apps need both hostname and origin, or neither.";
      }
      {
        assertion = lib.all (app: !app.public || app.cloudflareBypassApproval != null) (
          builtins.attrValues apps
        );
        message = "Internet access outside Cloudflare Access requires recorded explicit user approval.";
      }
      {
        assertion = lib.all (
          app:
          app.cloudflareBypassPaths == [ ]
          || (app.cloudflareBypassApproval != null && app.apparmorProfile != null && app.hostname != null)
        ) (builtins.attrValues apps);
        message = "Cloudflare Access path bypasses require recorded explicit user approval and an AppArmor profile.";
      }
    ];
    systemd.tmpfiles.rules = [ "d /var/lib/ghostship-dashboards 0700 root root -" ];
    systemd.services.podman-homepage.preStart = lib.mkOrder 2000 ''
      ${dashboards}/bin/ghostship-dashboard-sync homepage /srv/apps/homepage/services.yaml \
        /var/lib/ghostship-dashboards/homepage.json \
        ${config.ghostship.selfHostedSecrets.projections.homepage.path}
      chown apps:apps /srv/apps/homepage/services.yaml
      chmod 600 /srv/apps/homepage/services.yaml
    '';
    systemd.services.podman-muximux.preStart = lib.mkOrder 2000 ''
      ${dashboards}/bin/ghostship-dashboard-sync muximux /srv/apps/muximux/www/muximux/settings.ini.php \
        /var/lib/ghostship-dashboards/muximux.json
      chown apps:apps /srv/apps/muximux/www/muximux/settings.ini.php
    '';
  };
}
