# SIEM UI: Grafana, the single monitoring UI (#102 decision B, 2026-10-21):
# logs through the VictoriaLogs datasource, metrics through VictoriaMetrics.
# Alerting stays in vmalert and ghostship-siem-alerts; Grafana's is disabled.
#
# Boundaries:
# - Grafana reads the stores only through vmauth, which allows VictoriaLogs
#   /select/logsql/* and VictoriaMetrics' query APIs: no insert, write,
#   import, delete or admin path, so a compromised UI cannot alter evidence.
# - Grafana, vmauth and cloudflared share an internal network with no route
#   out and no host service but DNS; only vmauth also joins the stores' net.
# - Browser access is Cloudflare Access only. Grafana trusts the Access user
#   header from cloudflared's fixed address alone (auth proxy whitelist).
# - Image, plugin and dashboards are pinned in the repo; plugin installs,
#   update checks, telemetry, preinstalls and key retrieval are off.
{ config, lib, pkgs, ... }:
let
  network = "ghostship_siemui_net";
  bridge = "ghostsiemui0";
  subnet = "10.89.22.0/24";
  gateway = "10.89.22.1";
  cloudflaredAddress = "10.89.22.10";
  root = "/var/lib/ghostship-siem-ui";
  grafanaUid = "472";
  vmauthUid = "3101";

  # VictoriaMetrics' signed VictoriaLogs datasource, vendored (no runtime download).
  logsPluginZip = pkgs.fetchurl {
    url = "https://github.com/VictoriaMetrics/victorialogs-datasource/releases/download/v0.33.1/victoriametrics-logs-datasource-v0.33.1.zip";
    sha256 = "73e7ce379ae9a9ce6fdb978e5d6d43f67029b4c3e4d970f1ca8f7f4617f331c5";
  };
  # The Business Text panel (the Dynamic Text panel under its current name),
  # pinned by version and hash. The artifact is the signed release of 6.3.0,
  # the same pin nixpkgs carries, so the host never fetches a plugin.
  businessTextPluginZip = pkgs.fetchurl {
    url = "https://grafana.com/api/plugins/marcusolsson-dynamictext-panel/versions/6.3.0/download";
    sha256 = "sha256-nobTHc/GucfwyDGMsxPpDim9txzfygi1UFjd6XR+nLc=";
  };
  plugins = pkgs.runCommand "grafana-siem-plugins" { nativeBuildInputs = [ pkgs.unzip ]; } ''
    mkdir -p $out
    # Unmodified: the signed MANIFEST covers every file, so pruning the other
    # platforms' backends fails Grafana's signature check.
    unzip -q ${logsPluginZip} -d $out
    # The Business Text panel, pinned above. Its own directory, signed.
    unzip -q ${businessTextPluginZip} -d $out
  '';

  heartbeat = pkgs.pkgsStatic.runCommandCC "ghostship-heartbeat" { } ''
    mkdir -p $out
    $CC -O2 -static -o $out/read-file ${./heartbeat.c}
  '';

  vmauthConfig = pkgs.writeText "vmauth.yml" (builtins.toJSON {
    users = [
      {
        username = "grafana";
        password = "%{GRAFANA_VMAUTH_PASSWORD}";
        url_map = [
          {
            src_paths = [ "/select/logsql/.+" ];
            url_prefix = "http://victorialogs:9428";
          }
          {
            src_paths = [
              "/api/v1/(query|query_range|series|labels|label/[^/]+/values|metadata|query_exemplars|status/buildinfo)"
            ];
            url_prefix = "http://victoriametrics:8428";
          }
        ];
      }
    ];
  });

  datasource = name: uid: type: extra: {
    inherit name uid type;
    access = "proxy";
    url = "http://vmauth:8427";
    basicAuth = true;
    basicAuthUser = "grafana";
    # Datasource provisioning expands environment variables, not INI $__file.
    secureJsonData.basicAuthPassword = "$GRAFANA_VMAUTH_PASSWORD";
    editable = false;
  } // extra;
  datasourcesFile = pkgs.writeText "datasources.yaml" (builtins.toJSON {
    apiVersion = 1;
    prune = true;
    datasources = [
      (datasource "VictoriaLogs" "victorialogs" "victoriametrics-logs-datasource" { })
      (datasource "VictoriaMetrics" "victoriametrics" "prometheus" {
        isDefault = true;
        jsonData = { prometheusType = "Prometheus"; timeInterval = "30s"; };
      })
    ];
  });
  dashboardsFile = pkgs.writeText "dashboards.yaml" (builtins.toJSON {
    apiVersion = 1;
    providers = [
      {
        name = "siem";
        folder = "Ghostship";
        type = "file";
        disableDeletion = true;
        allowUiUpdates = false;
        updateIntervalSeconds = 300;
        options.path = "/etc/grafana/provisioning/dashboards-json";
      }
    ];
  });
  # Real files, not symlinks: only this directory is mounted in the container.
  # Grafana reads the plugin and the alerting provisioning directories on
  # every start and logs an error for each one it cannot find, so the tree
  # carries them empty: no plugin and no alerting configuration is
  # provisioned, the directories are there so the search finds nothing to
  # complain about.
  provisioning = pkgs.runCommand "grafana-siem-provisioning" { } ''
    mkdir -p $out/datasources $out/dashboards $out/dashboards-json
    mkdir -p $out/plugins $out/alerting
    cp ${datasourcesFile} $out/datasources/siem.yaml
    cp ${dashboardsFile} $out/dashboards/siem.yaml
    cp ${./dashboards}/*.json $out/dashboards-json/
  '';

  egressRules = pkgs.writeText "siemui-egress.nft" ''
    destroy table inet ghostship_siemui
    table inet ghostship_siemui {
      chain forward {
        type filter hook forward priority -10; policy accept;
        iifname "${bridge}" ct state established,related accept
        iifname "${bridge}" drop
      }
      chain input {
        type filter hook input priority -10; policy accept;
        iifname "${bridge}" ct state established,related accept
        # aardvark-dns, which answers container names only on internal networks.
        iifname "${bridge}" ip daddr ${gateway} meta l4proto { udp, tcp } th dport 53 accept
        iifname "${bridge}" drop
      }
    }
  '';
  hardening = [
    "--security-opt=no-new-privileges"
    "--pids-limit=256"
  ];
in
{
  ghostship.apps.grafana = {
    name = "Grafana";
    group = "Infrastructure";
    description = "Logs, metrics and security dashboards";
    icon = "sh-grafana";
    order = 259;
    hostname = "grafana.ghostship.io";
    origin = "http://grafana:3000";
  };
  ghostship.apps.vmauth = {
    name = "vmauth";
    group = "Infrastructure";
    description = "Read-only SIEM query proxy";
    icon = "sh-victoriametrics";
    order = 264;
  };

  virtualisation.oci-containers.containers = {
    vmauth = {
      # v1.154.1, the stores' release.
      image = "docker.io/victoriametrics/vmauth@sha256:8486c43b9ee1e20a9b558fd0b274991959123684c4aa60e614d6833c65e4c393";
      user = "${vmauthUid}:${vmauthUid}";
      environmentFiles = [ "${root}/vmauth.env" ];
      volumes = [ "${vmauthConfig}:/etc/vmauth.yml:ro" ];
      cmd = [ "-auth.config=/etc/vmauth.yml" "-httpListenAddr=:8427" ];
      extraOptions = hardening ++ [ "--network=${network}" "--network=ghostship_siem_net" "--memory=256m" ];
    };
    grafana = {
      # 13.2.4 distroless: no shell or package tools in the image.
      image = "docker.io/grafana/grafana@sha256:64dc24be9648cce6eeb2ad12bc91d79cafa71b5e76eb608c640afc798c578d9a";
      user = "${grafanaUid}:${grafanaUid}";
      environmentFiles = [ "${root}/vmauth.env" ];
      volumes = [
        "${root}/grafana:/var/lib/grafana:rw,noexec,nosuid,nodev"
        # The plugin backend runs from the store: read-only, executable.
        "${plugins}:/var/lib/grafana-plugins:ro"
        "${provisioning}:/etc/grafana/provisioning:ro"
        "${root}/grafana-vmauth-password:/run/secrets/vmauth-password:ro"
        "${heartbeat}:/opt/ghostship-heartbeat:ro"
      ];
      environment = {
        GF_SERVER_ROOT_URL = "https://grafana.ghostship.io";
        GF_USERS_HOME_PAGE = "/d/ghostship-autonomous-work";
        GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH = "/etc/grafana/provisioning/dashboards-json/autonomous-work.json";
        GF_PATHS_PLUGINS = "/var/lib/grafana-plugins";
        GF_LOG_MODE = "console";
        GF_PLUGINS_PREINSTALL_DISABLED = "true";
        GF_PLUGINS_PUBLIC_KEY_RETRIEVAL_DISABLED = "true";
        GF_PLUGINS_PLUGIN_ADMIN_ENABLED = "false";
        GF_ANALYTICS_REPORTING_ENABLED = "false";
        GF_ANALYTICS_CHECK_FOR_UPDATES = "false";
        GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES = "false";
        GF_ANALYTICS_FEEDBACK_LINKS_ENABLED = "false";
        GF_NEWS_NEWS_FEED_ENABLED = "false";
        GF_UNIFIED_ALERTING_ENABLED = "false";
        GF_SNAPSHOTS_EXTERNAL_ENABLED = "false";
        GF_PUBLIC_DASHBOARDS_ENABLED = "false";
        GF_SECURITY_DISABLE_GRAVATAR = "true";
        GF_SECURITY_COOKIE_SECURE = "true";
        GF_SECURITY_COOKIE_SAMESITE = "strict";
        GF_SECURITY_CONTENT_SECURITY_POLICY = "true";
        # No default administrator: Grafana would otherwise create admin/admin
        # on the first start, and the account outlives the login paths that are
        # closed below, so it would wait on the internal network for a
        # password path to be reopened. The auth proxy signs the users in and
        # assigns them Viewer, and the dashboards are provisioned, so nothing
        # needs an administrator.
        GF_SECURITY_DISABLE_INITIAL_ADMIN_CREATION = "true";
        GF_AUTH_DISABLE_LOGIN_FORM = "true";
        GF_AUTH_BASIC_ENABLED = "false";
        GF_AUTH_ANONYMOUS_ENABLED = "false";
        # Cloudflare Access sets this header after authenticating the user;
        # only cloudflared's fixed address may present it.
        GF_AUTH_PROXY_ENABLED = "true";
        GF_AUTH_PROXY_HEADER_NAME = "Cf-Access-Authenticated-User-Email";
        GF_AUTH_PROXY_HEADER_PROPERTY = "email";
        GF_AUTH_PROXY_AUTO_SIGN_UP = "true";
        GF_AUTH_PROXY_WHITELIST = cloudflaredAddress;
        GF_USERS_ALLOW_SIGN_UP = "false";
        GF_USERS_AUTO_ASSIGN_ORG_ROLE = "Viewer";
        # Explore (ad-hoc queries) for viewers; nothing they can save.
        GF_USERS_VIEWERS_CAN_EDIT = "true";
      };
      extraOptions = hardening ++ [ "--network=${network}" "--memory=1g" ];
    };
    cloudflared.extraOptions = [ "--network=${network}:ip=${cloudflaredAddress}" ];
  };

  systemd.tmpfiles.rules = [
    "d ${root} 0750 root root -"
    "d ${root}/grafana 0700 ${grafanaUid} ${grafanaUid} -"
  ];

  # Netavark adds no DNS input rule for internal networks (see github-engineering.nix).
  networking.firewall.extraCommands = lib.concatMapStrings (proto: ''
    iptables -w -A nixos-fw -s ${subnet} -d ${gateway} -p ${proto} --dport 53 -j nixos-fw-accept
  '') [ "udp" "tcp" ];

  systemd.services = {
    init-ghostship-siemui-net = {
      description = "Create the ${network} podman network";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = { Type = "oneshot"; RemainAfterExit = true; };
      script = ''
        ${pkgs.podman}/bin/podman network inspect ${network} >/dev/null 2>&1 || \
        ${pkgs.podman}/bin/podman network create --internal --interface-name ${bridge} \
          --subnet ${subnet} --gateway ${gateway} ${network}
      '';
    };
    siemui-egress = {
      description = "Block connections opened from the SIEM UI network";
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${pkgs.nftables}/bin/nft -f ${egressRules}";
        ExecStop = "${pkgs.nftables}/bin/nft destroy table inet ghostship_siemui";
      };
    };
    # The machine credential between Grafana and vmauth: generated once on the
    # host, never in the repo or the UI. Delete both files to rotate.
    ghostship-siemui-secret = {
      description = "Generate the Grafana-to-vmauth credential";
      serviceConfig = { Type = "oneshot"; RemainAfterExit = true; UMask = "0077"; };
      script = ''
        if [ ! -s ${root}/vmauth.env ] || [ ! -s ${root}/grafana-vmauth-password ]; then
          password=$(${pkgs.openssl}/bin/openssl rand -hex 32)
          printf 'GRAFANA_VMAUTH_PASSWORD=%s\n' "$password" > ${root}/vmauth.env
          printf '%s' "$password" > ${root}/grafana-vmauth-password
        fi
        chown root:root ${root}/vmauth.env
        chmod 0600 ${root}/vmauth.env
        chown ${grafanaUid}:${grafanaUid} ${root}/grafana-vmauth-password
        chmod 0400 ${root}/grafana-vmauth-password
      '';
    };
  }
  // lib.genAttrs [ "podman-vmauth" "podman-grafana" ] (_: {
    requires = [ "init-ghostship-siemui-net.service" "siemui-egress.service" "ghostship-siemui-secret.service" ];
    after = [ "init-ghostship-siemui-net.service" "siemui-egress.service" "ghostship-siemui-secret.service"
              "init-ghostship-siem-net.service" ];
    bindsTo = [ "siemui-egress.service" ];
  })
  // {
    podman-cloudflared = {
      after = [ "init-ghostship-siemui-net.service" ];
      requires = [ "init-ghostship-siemui-net.service" ];
    };
  };
}
