{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.ghostship.mesh;
  warp = config.services.cloudflare-warp.package;
in
{
  options.ghostship.mesh = {
    enable = lib.mkEnableOption "unattended Cloudflare Mesh private networking";
    tokenFile = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/ghostship-mesh/node-token";
      description = "Root-owned Mesh node token, provisioned outside the Nix store.";
    };
    hostname = lib.mkOption {
      type = lib.types.str;
      default = "${config.networking.hostName}.mesh.ghostship.io";
      description = "Private DNS name for the Mesh HTTPS T3 endpoint.";
    };
    t3Upstream = lib.mkOption {
      type = lib.types.str;
      default = "http://127.0.0.1:${toString config.ghostship.t3Worker.port}";
      description = "Existing T3 backend reached by the private HTTPS proxy.";
    };
    resolver = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "DNS resolvers for a container-name T3 upstream.";
    };
  };

  config = lib.mkIf cfg.enable {
    # Preserve the existing Antigravity exception while permitting only the
    # headless networking client in addition to it.
    nixpkgs.config.allowUnfreePredicate = lib.mkForce (
      pkg:
      builtins.elem (lib.getName pkg) [
        "antigravity-acp"
        "cloudflare-warp-headless"
      ]
    );
    services.cloudflare-warp = {
      enable = true;
      package = pkgs.cloudflare-warp.override { headless = true; };
      openFirewall = false;
    };
    # Domain-specific forwarding never falls back to ordinary upstream DNS.
    # Keep the existing resolvconf subscribers for LAN/VPN DNS updates.
    services.dnsmasq = {
      enable = true;
      alwaysKeepRunning = true;
      settings = {
        conf-file = [
          "${./mesh-dns.conf}"
          "/etc/dnsmasq-conf.conf"
        ];
        resolv-file = lib.mkIf (config.ghostship.host.roles.wsl or false) "/mnt/wsl/resolv.conf";
      };
    };
    systemd.services.cloudflare-warp.unitConfig.StartLimitIntervalSec = 0;
    systemd.services.cloudflare-warp.after = [ "dnsmasq.service" ];
    systemd.services.cloudflare-warp.wants = [ "dnsmasq.service" ];
    systemd.services.cloudflare-warp.preStart = ''
      # WARP replaces resolv.conf atomically, so isolating that file alone
      # does not contain replacement of a host symlink. Project host /etc
      # through read-only links, with a private writable resolver entry.
      ${pkgs.coreutils}/bin/rm -rf /run/cloudflare-warp/etc
      ${pkgs.coreutils}/bin/mkdir -m 0700 /run/cloudflare-warp/etc
      ${pkgs.coreutils}/bin/cp -as /run/cloudflare-warp/host-etc/. /run/cloudflare-warp/etc/
      ${pkgs.coreutils}/bin/rm -f /run/cloudflare-warp/etc/resolv.conf
      ${pkgs.coreutils}/bin/install -m 0600 \
        /run/cloudflare-warp/host-etc/resolv.conf /run/cloudflare-warp/etc/resolv.conf
    '';
    systemd.services.cloudflare-warp.serviceConfig = {
      StateDirectoryMode = "0700";
      UMask = "0077";
      # ExecStartPre creates the projection before ExecStart's namespace.
      BindPaths = [ "-/run/cloudflare-warp/etc:/etc" ];
      BindReadOnlyPaths = [
        "/proc/1/root/etc:/run/cloudflare-warp/host-etc"
      ];
      ReadWritePaths = lib.mkForce [ "/var/lib/cloudflare-warp" ];
      # Use this namespace's resolver, not the host nscd cache, and prevent
      # alternate host DNS changes through resolved/NetworkManager.
      InaccessiblePaths = [
        "-/run/dbus/system_bus_socket"
        "-/run/nscd"
      ];
    };
    systemd.services.ghostship-mesh-health = {
      description = "Connect and recover the private Cloudflare Mesh node";
      after = [
        "network-online.target"
        "cloudflare-warp.service"
      ];
      wants = [
        "network-online.target"
        "cloudflare-warp.service"
      ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        StateDirectory = "ghostship-mesh";
        StateDirectoryMode = "0700";
        TimeoutStartSec = "3min";
        UMask = "0077";
        ExecStart = "${pkgs.python3}/bin/python ${./mesh-health.py} --warp-cli ${warp}/bin/warp-cli --systemctl ${pkgs.systemd}/bin/systemctl --state-dir /var/lib/ghostship-mesh --warp-state-dir /var/lib/cloudflare-warp --token-file ${cfg.tokenFile}";
      };
    };
    systemd.timers.ghostship-mesh-health = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "30s";
        OnUnitActiveSec = "30s";
        Persistent = true;
      };
    };
    # These are interface-scoped allowances, never public port openings.
    networking.firewall.enable = true;
    networking.firewall.interfaces.CloudflareWARP.allowedTCPPorts = [
      22
      443
    ];
    services.openssh = {
      enable = true;
      # Keep the server's existing management route until Mesh is verified.
      openFirewall = lib.mkIf (config.ghostship.host.roles.wsl or false) false;
      settings = {
        PasswordAuthentication = false;
        KbdInteractiveAuthentication = false;
      };
    };
    # DNS-01 certificates are free and renew without publishing this service
    # or opening an HTTP challenge port. Provision only a scoped DNS token.
    security.acme = {
      acceptTerms = true;
      certs.${cfg.hostname} = {
        dnsProvider = "cloudflare";
        credentialFiles.CF_DNS_API_TOKEN_FILE = "/var/lib/ghostship-mesh/cloudflare-dns-token";
        webroot = null;
      };
    };
    services.nginx = {
      enable = true;
      recommendedProxySettings = true;
      recommendedTlsSettings = true;
      resolver.addresses = cfg.resolver;
      virtualHosts.${cfg.hostname} = {
        onlySSL = true;
        enableACME = true;
        listen = [
          {
            addr = "0.0.0.0";
            port = 443;
            ssl = true;
          }
        ];
        extraConfig = "set $mesh_t3_upstream ${cfg.t3Upstream};";
        locations."/" = {
          proxyPass = "$mesh_t3_upstream";
          proxyWebsockets = true;
          extraConfig = "proxy_read_timeout 3600s; proxy_buffering off;";
        };
      };
    };
    assertions = [
      {
        assertion =
          config.networking.firewall.enable
          && !(builtins.elem 443 config.networking.firewall.allowedTCPPorts)
          && lib.all (
            range: range.from > 443 || range.to < 443
          ) config.networking.firewall.allowedTCPPortRanges;
        message = "The Mesh HTTPS endpoint requires the firewall and no global HTTPS allowance.";
      }
    ];
  };
}
