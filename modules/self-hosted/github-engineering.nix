{ config, lib, pkgs, inputs, ... }:
# GitHub-driven T3 engineering and Cloudflare alerts (ghostship-agent
# docs/github-engineering.md). hooks.ghostship.io receives signed GitHub
# webhooks on POST /github and Cloudflare notifications on POST /cloudflare;
# Access bypasses exactly those paths (user-approved) and requires Google
# identity everywhere else. The receiver verifies, reduces and spools; the
# private coordinator re-reads every GitHub pointer from GitHub, routes it to the
# owning T3 thread, and publishes Cloudflare alerts to ntfy. The receiver sits
# alone with cloudflared on an internal network: no egress, no route to T3 or
# other services, and only its two webhook secrets.
let
  cfg = config.ghostship.githubEngineering;
  system = pkgs.stdenv.hostPlatform.system;
  github = (inputs.ghostship-private-agent.lib.mkPrivateIntegrations { inherit system; }).github;
  # Under /var/lib: tmpfiles refuses root-owned children of the apps-owned /srv/apps.
  root = "/var/lib/ghostship-github";
  network = "ghostship_github_net";
  # T3 projects per repository (ids from the T3 orchestration shell).
  repositories = {
    "ghostship-io/ghostship-config".project_id = "the owner's local area";
    "ghostship-io/ghostship-agent".project_id = "the owner's local area";
    "ghostship-io/ghostship-3dprinting".project_id = "the owner's local area";
    "ghostship-io/goship-roms".project_id = "the owner's local area";
    "ghostship-io/ghostship-xplus4".project_id = "the owner's local area";
    "ghostship-io/ghostship-newsletter".project_id = "the owner's local area";
    "ghostship-io/ghostship-orca".project_id = "the owner's local area";
  };
  coordinatorConfig = pkgs.writeText "ghostship-github-coordinator.json" (builtins.toJSON {
    allowed_user_ids = [ a local store id ];
    ntfy_url = "http://ntfy:8080";
    t3_environment_id = "the owner's local area";
    model_selection = { instanceId = "codex"; model = "gpt-6.1-sol"; };
    repositories = lib.mapAttrs (_: r: r // { base = "main"; }) repositories;
  });
  hardening = [ "--read-only" "--cap-drop=ALL" "--security-opt=no-new-privileges"
                "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=8m" ];
in
{
  options.ghostship.githubEngineering.enable =
    lib.mkEnableOption "hooks.ghostship.io webhook receiver and T3 engineering coordinator";

  config = lib.mkIf cfg.enable {
    ghostship.apps.hooks = {
      name = "Webhooks";
      container = "ghostship-hooks";
      group = "Infrastructure";
      description = "Signed GitHub and Cloudflare webhooks";
      hostname = "hooks.ghostship.io";
      origin = "http://ghostship-hooks:8080";
      healthPath = "/healthz";
      apparmorProfile = "ghostship-hooks";
      cloudflareBypassPaths = [ "/github" "/cloudflare" ];
      cloudflareBypassApproval = "the owner 2026-10-19: approved Access bypass for exact POST paths /cloudflare and /github on hooks.ghostship.io only; GitHub HMAC and the Cloudflare webhook secret authenticate them";
      muximux.enable = false;
    };
    ghostship.apps.github-coordinator = {
      name = "GitHub coordinator";
      container = "ghostship-github-coordinator";
      group = "Infrastructure";
      description = "Routes GitHub issues, comments and PRs to T3 threads";
      hostname = null;
      origin = null;
    };

    users.groups.ghostship-hooks.gid = 62030;
    users.users.ghostship-hooks = {
      isSystemUser = true; uid = 62030; group = "ghostship-hooks";
      extraGroups = [ "ghostship-github-spool" ];
    };
    users.groups.ghostship-github-spool.gid = 62032;
    users.groups.ghostship-github.gid = 62031;
    users.users.ghostship-github = {
      isSystemUser = true; uid = 62031; group = "ghostship-github";
      extraGroups = [ "ghostship-github-spool" ];
    };

    ghostship.secretProjections.ghostship-github-coordinator = {
      fileName = "ghostship-github/github.env";
      owner = "ghostship-github";
      group = "ghostship-github";
      mode = "0400";
      raw = true;
      fields.GITHUB_TOKEN = { unit = "github"; key = "TOKEN"; };
      fields.NTFY_PUBLISH_PASSWORD = { unit = "monitoring"; key = "NTFY_PUBLISH_PASSWORD"; };
    };
    ghostship.secretProjections.ghostship-hooks = {
      fileName = "ghostship-github/hooks.env";
      owner = "ghostship-hooks";
      group = "ghostship-hooks";
      mode = "0400";
      raw = true;
      fields.GITHUB_WEBHOOK_SECRET = { unit = "hooks"; key = "GITHUB_WEBHOOK_SECRET"; };
      fields.CLOUDFLARE_WEBHOOK_SECRET = { unit = "hooks"; key = "CLOUDFLARE_WEBHOOK_SECRET"; };
    };

    systemd.tmpfiles.rules = [
      "d ${root} 0755 root root -"
      # setgid: spooled files stay readable and removable by the coordinator.
      "d ${root}/spool 2770 root ghostship-github-spool -"
      "d ${root}/state 0700 ghostship-github ghostship-github -"
      "d /run/ghostship-secrets/ghostship-github 0750 root ghostship-github -"
      "d /run/ghostship-github 0750 root ghostship-github -"
    ];

    systemd.services.init-ghostship-github-net = {
      description = "Create the internal ${network} podman network";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = { Type = "oneshot"; RemainAfterExit = true; };
      script = ''
        ${pkgs.podman}/bin/podman network inspect ${network} >/dev/null 2>&1 || \
        ${pkgs.podman}/bin/podman network create --internal --subnet 10.89.9.0/24 ${network}
      '';
    };

    # cloudflared reaches the receiver over the internal network.
    virtualisation.oci-containers.containers.cloudflared.extraOptions = [ "--network=${network}" ];
    systemd.services.podman-cloudflared = {
      after = [ "init-ghostship-github-net.service" ];
      requires = [ "init-ghostship-github-net.service" ];
    };

    virtualisation.oci-containers.containers.ghostship-hooks = {
      image = "ghostship-github-ingress:${github.ingressImage.imageTag}";
      imageFile = github.ingressImage;
      pull = "never";
      user = "62030:62032";
      cmd = [ "--port" "8080" "--spool" "/spool" "--secrets" "/run/secrets/hooks.env"
              "--repositories" (lib.concatStringsSep "," (builtins.attrNames repositories)) ];
      volumes = [
        "${root}/spool:/spool:rw"
        "${config.ghostship.selfHostedSecrets.projections.ghostship-hooks.path}:/run/secrets/hooks.env:ro"
      ];
      extraOptions = hardening ++ [ "--network=${network}" "--pids-limit=64" "--memory=128m" "--cpus=0.5" ];
    };
    systemd.services.podman-ghostship-hooks = {
      after = [ "init-ghostship-github-net.service" ];
      requires = [ "init-ghostship-github-net.service" ];
      preStart = lib.mkBefore ''
        ${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project ghostship-hooks
      '';
    };

    # A T3 session token for the coordinator alone, refreshed daily like the MCP's.
    systemd.services.ghostship-github-t3-token = {
      description = "Issue the GitHub coordinator's T3 session token";
      wantedBy = [ "multi-user.target" ];
      after = [ "podman-t3code.service" ];
      serviceConfig = {
        Type = "oneshot";
        UMask = "0077";
        ExecStart = pkgs.writeShellScript "ghostship-github-t3-token" ''
          set -eu
          dir=/run/ghostship-github
          printf 'http://t3code:3773' > $dir/t3-server.json.new
          chmod 0444 $dir/t3-server.json.new
          mv $dir/t3-server.json.new $dir/t3-server.json
          for attempt in $(seq 1 30); do
            if token=$(${pkgs.podman}/bin/podman exec t3code \
                env HOME=/home/t3code T3CODE_HOME=/home/t3code/.t3 \
                /home/t3code/.local/bin/t3 auth session issue \
                --ttl 30d --label ghostship-github-coordinator --token-only 2>/dev/null) \
                && [ -n "$token" ]; then
              printf '%s' "$token" > $dir/t3-token.new
              chown 62031:62031 $dir/t3-token.new
              chmod 0400 $dir/t3-token.new
              mv $dir/t3-token.new $dir/t3-token
              exit 0
            fi
            sleep 10
          done
          echo "could not issue a T3 session token from the t3code container" >&2
          exit 1
        '';
      };
    };
    systemd.timers.ghostship-github-t3-token = {
      wantedBy = [ "timers.target" ];
      timerConfig = { OnBootSec = "10min"; OnCalendar = "daily"; Persistent = true; RandomizedDelaySec = 600; };
    };

    virtualisation.oci-containers.containers.ghostship-github-coordinator = {
      image = "ghostship-github-coordinator:${github.coordinatorImage.imageTag}";
      imageFile = github.coordinatorImage;
      pull = "never";
      user = "62031:62032";
      cmd = [ "--config" "/etc/ghostship-github/config.json" "--spool" "/spool" "--state" "/state"
              "--secrets" "/run/secrets/github.env" ];
      volumes = [
        "${root}/spool:/spool:rw"
        "${root}/state:/state:rw"
        "${coordinatorConfig}:/etc/ghostship-github/config.json:ro"
        # The bridge's default credential paths.
        "/run/ghostship-github:/run/ghostship-integrations:ro"
        "${config.ghostship.selfHostedSecrets.projections.ghostship-github-coordinator.path}:/run/secrets/github.env:ro"
      ];
      extraOptions = hardening ++ [ "--network=ghostship_net" "--pids-limit=64" "--memory=256m" "--cpus=0.5" ];
    };
    systemd.services.podman-ghostship-github-coordinator = {
      after = [ "init-ghostship-net.service" "ghostship-github-t3-token.service" ];
      requires = [ "init-ghostship-net.service" ];
      wants = [ "ghostship-github-t3-token.service" ];
      preStart = lib.mkBefore ''
        ${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project ghostship-github-coordinator
      '';
    };
  };
}
