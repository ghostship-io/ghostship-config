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
  # The T3 projects, the account id, and the environment id are personal or
  # name private repositories, so the committed template carries placeholders
  # and the coordinator receives a configuration rendered at activation time
  # from the github-engineering projection.
  coordinatorConfig = pkgs.writeText "ghostship-github-coordinator.json" (builtins.toJSON {
    allowed_user_ids = "{{GITHUB_ALLOWED_USER_IDS:json}}";
    ntfy_url = "http://ntfy:8080";
    t3_environment_id = "{{T3_ENVIRONMENT_ID}}";
    # The chief reviewer leads launched threads; the backup reviewer stands in
    # while it is unavailable (routing-policy.md "Roles"). Bulk implementation
    # remains delegated under the canonical engineering/routing policy.
    model_selection = {
      instanceId = "claudeAgent"; model = "claude-opus-5-5";
      options = [ { id = "effort"; value = "high"; } ];
    };
    frontier_models = [
      { instanceId = "claudeAgent"; model = "claude-opus-5-5"; }
      { instanceId = "codex"; model = "gpt-6.1-sol"; }
    ];
    # Existing authenticated subscriptions only. Each provider owns its options;
    # measured exhaustion skips it, and an unknown balance is shown as unknown.
    model_routes = [
      { instanceId = "claudeAgent"; model = "claude-opus-5-5";
        options = [ { id = "effort"; value = "high"; } ]; }
      { instanceId = "codex"; model = "gpt-6.1-sol";
        options = [ { id = "reasoningEffort"; value = "high"; } ]; }
    ];
    review_max_active = 2;
    model_rankings_path = "/run/ghostship-integrations/model-routing.json";
    repositories = "{{T3_REPOSITORIES:json}}";
    # Host incidents launch bounded repair threads in the fleet's own project.
    incidents = { repository = "{{GITHUB_INCIDENT_REPOSITORY}}"; daily_limit = 3; };
  });
  coordinatorConfigPath = "/run/ghostship-github/coordinator.json";
  renderCoordinatorConfig = pkgs.writeShellScript "ghostship-github-coordinator-render" ''
    set -eu
    umask 0077
    ${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project github-engineering
    ${pkgs.python3}/bin/python3 ${./render-config.py} \
      ${coordinatorConfig} \
      ${config.ghostship.selfHostedSecrets.projections.github-engineering.path} \
      ${coordinatorConfigPath}
    chown root:ghostship-github ${coordinatorConfigPath}
    chmod 0640 ${coordinatorConfigPath}
  '';
  hardening = [ "--read-only" "--cap-drop=ALL" "--security-opt=no-new-privileges"
                "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=8m" ];
in
{
  options.ghostship.githubEngineering.enable =
    lib.mkEnableOption "hooks.ghostship.io webhook receiver and T3 engineering coordinator";

  config = lib.mkIf cfg.enable {
    ghostship.notify.incidentSpool = "${root}/incidents";
    ghostship.apps.hooks = {
      name = "Webhooks";
      container = "ghostship-hooks";
      group = "Infrastructure";
      description = "Signed GitHub and Cloudflare webhooks";
      hostname = "hooks.ghostship.io";
      origin = "http://ghostship-hooks:8080";
      # Uptime Kuma cannot reach the receiver's internal network; its container
      # heartbeat covers it instead of an HTTP monitor.
      healthPath = null;
      apparmorProfile = "ghostship-hooks";
      apparmorProcessProfiles = [
        "ghostship-hooks"
        "ghostship-hooks//tools"
      ];
      apparmorRequiredProcessProfiles = [ "ghostship-hooks" ];
      cloudflareBypassPaths = [ "/github" "/cloudflare" ];
      cloudflareBypassApproval = "Owner 2026-10-19: approved Access bypass for exact POST paths /cloudflare and /github on hooks.ghostship.io only; GitHub HMAC and the Cloudflare webhook secret authenticate them";
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
      fields.GITHUB_REPOSITORIES = { unit = "github-engineering"; key = "GITHUB_REPOSITORIES"; };
    };

    systemd.tmpfiles.rules = [
      "d ${root} 0755 root root -"
      # setgid: spooled files stay readable and removable by the coordinator.
      "d ${root}/spool 2770 root ghostship-github-spool -"
      "d ${root}/state 0700 ghostship-github ghostship-github -"
      # Written by root's ghostship-notify only; the receiver cannot reach it.
      "d ${root}/incidents 2770 root ghostship-github -"
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

    # Netavark adds no DNS input rule for internal networks, so the host firewall
    # dropped queries to this network's aardvark-dns. It answers container names
    # only: aardvark never forwards an internal network's queries upstream.
    networking.firewall.extraCommands = lib.concatMapStrings (proto: ''
      iptables -w -A nixos-fw -s 10.89.9.0/24 -d 10.89.9.1 -p ${proto} --dport 53 -j nixos-fw-accept
    '') [ "udp" "tcp" ];

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
      # The repository names name private repositories, so the receiver reads
      # them from its secrets file rather than from the command line.
      cmd = [ "--port" "8080" "--spool" "/spool" "--secrets" "/run/secrets/hooks.env" ];
      volumes = [
        "${root}/spool:/spool:rw,noexec,nosuid,nodev"
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
              "--incidents" "/incidents" "--secrets" "/run/secrets/github.env" ];
      volumes = [
        "${root}/spool:/spool:rw,noexec,nosuid,nodev"
        "${root}/state:/state:rw,noexec,nosuid,nodev"
        "${root}/incidents:/incidents:rw,noexec,nosuid,nodev"
        "${coordinatorConfigPath}:/etc/ghostship-github/config.json:ro"
        # The bridge's default credential paths.
        "/run/ghostship-github:/run/ghostship-integrations:ro"
        "${config.ghostship.selfHostedSecrets.projections.ghostship-github-coordinator.path}:/run/secrets/github.env:ro"
      ];
      # Primary group is the spool's; the T3 token directory needs ghostship-github.
      extraOptions = hardening ++ [ "--group-add=62031" "--network=ghostship_net" "--pids-limit=64"
                                    "--memory=256m" "--cpus=0.5" ];
    };
    systemd.services.podman-ghostship-github-coordinator = {
      after = [ "init-ghostship-net.service" "ghostship-github-t3-token.service" ];
      requires = [ "init-ghostship-net.service" ];
      wants = [ "ghostship-github-t3-token.service" ];
      preStart = lib.mkBefore ''
        ${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project ghostship-github-coordinator
        ${renderCoordinatorConfig}
      '';
    };
  };
}
