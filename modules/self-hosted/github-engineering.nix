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
  runtimes = import ./agent-service-runtimes.nix { agent = inputs.ghostship-private-agent; inherit system; };
  base = name: uid: import ./service-base-image.nix { inherit pkgs name uid; gid = "62032"; };
  ingressImage = base "ghostship-github-ingress" "62030";
  coordinatorImage = base "ghostship-github-coordinator" "62031";
  goCoordinatorImage = inputs.ghostship-private-agent.packages.${system}.github-go-coordinator-image;
  goCoordinatorHeartbeat = pkgs.pkgsStatic.runCommandCC "ghostship-go-coordinator-heartbeat" { } ''
    mkdir -p $out
    $CC -O2 -static -o $out/read-file ${./siem/heartbeat.c}
  '';
  # Under /var/lib: tmpfiles refuses root-owned children of the apps-owned /srv/apps.
  root = "/var/lib/ghostship-github";
  t3Home = lib.removeSuffix ":/home/t3code:rw" (lib.findFirst
    (volume: lib.hasSuffix ":/home/t3code:rw" volume)
    (throw "GitHub review receipts require the T3 home volume")
    config.virtualisation.oci-containers.containers.t3code.volumes);
  reviewStore = "${t3Home}/.local/state/ghostship/reviews";
  orchestratorDirectory = "${t3Home}/.local/state/ghostship/orchestrator";
  pointerPython = pkgs.python3.withPackages (ps: [ ps.websockets ]);
  network = "ghostship_github_net";
  # T3 projects per repository (ids from the T3 orchestration shell).
  repositories = {
    "ghostship-io/ghostship-config" = {
      project_id = "@GHOSTSHIP_T3_PROJECT_CONFIG@";
      required_checks = [ "check" "browser" ];
    };
    "ghostship-io/ghostship-agent".project_id = "@GHOSTSHIP_T3_PROJECT_AGENT@";
    "ghostship-io/ghostship-3dprinting".project_id = "@GHOSTSHIP_T3_PROJECT_3DPRINTING@";
    "ghostship-io/ghostship-roms".project_id = "@GHOSTSHIP_T3_PROJECT_ROMS@";
    "ghostship-io/ghostship-xplus4".project_id = "@GHOSTSHIP_T3_PROJECT_XPLUS4@";
    "ghostship-io/ghostship-newsletter".project_id = "@GHOSTSHIP_T3_PROJECT_NEWSLETTER@";
    "ghostship-io/ghostship-orca".project_id = "@GHOSTSHIP_T3_PROJECT_ORCA@";
  };
  # The previous owner and the two renamed repositories, so that existing
  # issue owners, queued deliveries, CI issue mappings and pull request links
  # survive the transfer. The alias targets are the canonical repositories
  # above; the coordinator resolves a legacy name to its canonical one and
  # keeps the pre-transfer identity for commands it has already sent. The
  # previous owner is supplied by the deployment outside this repository.
  repositoryAliases = {
    "@GHOSTSHIP_GITHUB_ACCOUNT@/nixos-config" = "ghostship-io/ghostship-config";
    "@GHOSTSHIP_GITHUB_ACCOUNT@/ghostship-agent" = "ghostship-io/ghostship-agent";
    "@GHOSTSHIP_GITHUB_ACCOUNT@/ghostship-3dprinting" = "ghostship-io/ghostship-3dprinting";
    "@GHOSTSHIP_GITHUB_ACCOUNT@/ghostship-roms" = "ghostship-io/ghostship-roms";
    "@GHOSTSHIP_GITHUB_ACCOUNT@/ghostship-xplus4" = "ghostship-io/ghostship-xplus4";
    "@GHOSTSHIP_GITHUB_ACCOUNT@/ghostship-newsletter" = "ghostship-io/ghostship-newsletter";
    "@GHOSTSHIP_GITHUB_ACCOUNT@/orca-advanced-calibration" = "ghostship-io/ghostship-orca";
  };
  renderOwnerConfig = pkgs.writeShellScriptBin "ghostship-render-owner-config" ''
    exec ${pkgs.python3}/bin/python3 ${./render-owner-config.py} "$@"
  '';
  coordinatorConfigTemplate = pkgs.writeText "ghostship-github-coordinator.json" (builtins.toJSON {
    allowed_user_ids = [ "@GHOSTSHIP_GITHUB_USER_ID@" ];
    ntfy_url = "http://ntfy:8080";
    t3_environment_id = "@GHOSTSHIP_T3_ENVIRONMENT_ID@";
    # One orchestrator reviews each diff; workers implement and ship their own approved PRs.
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
    repositories = lib.mapAttrs (_: r: r // {
      base = "main";
      # Off until the owner approves the ranking for routing: the review
      # routes are frontier (Codex/Claude) and their quota is reserved.
      automatic_review = {
        enabled = false;
        debounce_seconds = 30;
        max_active = 1;
        timeout_seconds = 1800;
      };
    }) repositories;
    # The coordinator resolves a legacy repository name to its canonical one
    # and keeps the pre-transfer identity for the commands it already sent.
    repository_aliases = repositoryAliases;
    # Host incidents launch bounded repair threads in the fleet's own project.
    incidents = { repository = "ghostship-io/ghostship-config"; daily_limit = 3; };
  });
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
      cloudflareBypassPaths = [ "/github" "/cloudflare" "/shadow/github/webhook" ];
      cloudflareBypassApproval = "the owner 2026-10-19: approved Access bypass for exact POST paths /cloudflare and /github on hooks.ghostship.io only; the owner 2026-10-26 (ghostship-agent#924 issuecomment-6405254835) approved exact POST /shadow/github/webhook; GitHub HMAC authenticates its signed Go coordinator ingress";
      cloudflarePathRoutes = [
        { path = "/shadow/github/webhook"; origin = "http://ghostship-go-coordinator:18765"; }
      ];
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
    ghostship.apps.go-coordinator = {
      name = "Go coordinator";
      container = "ghostship-go-coordinator";
      group = "Infrastructure";
      description = "Serves cached work status from the Go coordinator";
      hostname = null;
      origin = null;
      apparmorProfile = "ghostship-go-coordinator";
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
    users.groups.ghostship-coordinator.gid = 62033;
    users.users.ghostship-coordinator = {
      isSystemUser = true; uid = 62033; group = "ghostship-coordinator";
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
    ghostship.secretProjections.ghostship-go-coordinator = {
      fileName = "ghostship-github/go-coordinator.env";
      owner = "ghostship-coordinator";
      group = "ghostship-coordinator";
      mode = "0400";
      raw = true;
      fields.GITHUB_TOKEN = { unit = "github"; key = "TOKEN"; };
      fields.GHOSTSHIP_COORDINATOR_TOKEN = { unit = "go-coordinator-auth"; key = "TOKEN"; };
      fields.GHOSTSHIP_T3_PLAINTEXT_HOSTS = {
        unit = "go-coordinator-plaintext-hosts";
        key = "GHOSTSHIP_T3_PLAINTEXT_HOSTS";
      };
      fields.GHOSTSHIP_COORDINATOR_GITHUB_WEBHOOK_SECRET = {
        unit = "hooks";
        key = "GITHUB_WEBHOOK_SECRET";
      };
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
      # The Python coordinator runs the pinned Go coordinator for review
      # request and review record; those one-shot commands open their own
      # SQLite store and cannot create its directory.
      "d ${root}/state/ghostship-coordinator-shadow 0700 ghostship-github ghostship-github -"
      "d ${root}/go-state 0700 ghostship-coordinator ghostship-coordinator -"
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

    ghostship.containerRuntimes = {
      ghostship-hooks.runtime = runtimes.hooks;
      ghostship-github-coordinator.runtime = runtimes.coordinator;
    };
    virtualisation.oci-containers.containers.ghostship-hooks = {
      image = "ghostship-github-ingress:${ingressImage.imageTag}";
      imageFile = ingressImage;
      pull = "never";
      user = "62030:62032";
      cmd = [ "--port" "8080" "--spool" "/spool" "--secrets" "/run/secrets/hooks.env"
              # The receiver serves the canonical repositories.
              "--repositories" (lib.concatStringsSep ","
                (builtins.attrNames repositories)) ];
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
        ${config.ghostship.selfHostedSecrets.renderFor "ghostship-hooks"}/bin/ghostship-secret-project ghostship-hooks
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
      image = "ghostship-github-coordinator:${coordinatorImage.imageTag}";
      imageFile = coordinatorImage;
      pull = "never";
      user = "62031:62032";
      cmd = [ "--config" "/etc/ghostship-github/config.json" "--spool" "/spool" "--state" "/state"
              "--incidents" "/incidents" "--secrets" "/run/secrets/github.env" ];
      environment = {
        GHOSTSHIP_REVIEW_STORE = "/reviews";
        GHOSTSHIP_ORCHESTRATOR_FILE = "/run/ghostship-orchestrator/pointer.env";
        GHOSTSHIP_ROUTE_POLICY_PATH = "/etc/ghostship/route-policy.json";
      };
      volumes = [
        "${reviewStore}:/reviews:ro,noexec,nosuid,nodev"
        # Directory binding follows the canonical writer’s atomic replacements.
        "${orchestratorDirectory}:/run/ghostship-orchestrator:ro,noexec,nosuid,nodev"
        "${root}/spool:/spool:rw,noexec,nosuid,nodev"
        "${root}/state:/state:rw,noexec,nosuid,nodev"
        "${root}/incidents:/incidents:rw,noexec,nosuid,nodev"
        "${root}/config.json:/etc/ghostship-github/config.json:ro"
        "/etc/ghostship/route-policy.json:/etc/ghostship/route-policy.json:ro"
        # The bridge's default credential paths.
        "/run/ghostship-github:/run/ghostship-integrations:ro"
        "${config.ghostship.selfHostedSecrets.projections.ghostship-github-coordinator.path}:/run/secrets/github.env:ro"
      ];
      # Primary group is the spool's; the T3 token directory needs ghostship-github.
      extraOptions = hardening ++ [ "--group-add=62031" "--network=ghostship_net" "--pids-limit=64"
                                    "--memory=1g" "--cpus=0.5" ];
    };
    systemd.services.podman-ghostship-github-coordinator = {
      after = [ "init-ghostship-net.service" "ghostship-github-t3-token.service" ];
      requires = [ "init-ghostship-net.service" ];
      wants = [ "ghostship-github-t3-token.service" ];
      serviceConfig.EnvironmentFile = [ "/etc/ghostship/owner-identity.env" ];
      preStart = lib.mkBefore ''
        # Seed using the pinned writer as the home owner before the explicit
        # coordinator reader starts. No T3 restart or managed-CLI race.
        ${pkgs.util-linux}/bin/setpriv \
          --reuid="$(${pkgs.coreutils}/bin/stat -c %u ${lib.escapeShellArg t3Home})" \
          --regid="$(${pkgs.coreutils}/bin/stat -c %g ${lib.escapeShellArg t3Home})" --clear-groups \
          ${pkgs.coreutils}/bin/env -u GHOSTSHIP_ORCHESTRATOR_FILE \
          HOME=${lib.escapeShellArg t3Home} \
          XDG_CONFIG_HOME=${lib.escapeShellArg (t3Home + "/.config")} \
          XDG_STATE_HOME=${lib.escapeShellArg (t3Home + "/.local/state")} \
          PYTHONPATH=${inputs.ghostship-private-agent}/tools/python \
          ${pointerPython}/bin/python3 -c 'from ghostship_sessions.orchestrator import seed_pointer; seed_pointer()'
        # No ACL or per-file bind: new pointer inodes retain mode 0644.
        ${pkgs.coreutils}/bin/test -r ${lib.escapeShellArg (orchestratorDirectory + "/pointer.env")}
        ${pkgs.coreutils}/bin/test "$(${pkgs.findutils}/bin/find ${lib.escapeShellArg orchestratorDirectory} -mindepth 1 -maxdepth 1 ! -name pointer.env -print -quit)" = ""
        # A named-user ACL survives T3’s recursive owner/group reconciliation.
        # Default ACLs cover future atomic receipt replacements.
        # Export only approval metadata. Keep T3 state and credentials private.
        ${pkgs.coreutils}/bin/mkdir -p ${lib.escapeShellArg reviewStore}
        ${pkgs.coreutils}/bin/chown --reference=${lib.escapeShellArg t3Home} ${lib.escapeShellArg reviewStore}
        ${pkgs.coreutils}/bin/chmod 0750 ${lib.escapeShellArg reviewStore}
        ${pkgs.acl}/bin/setfacl -R -m u:62031:rX ${lib.escapeShellArg reviewStore}
        ${pkgs.findutils}/bin/find ${lib.escapeShellArg reviewStore} -type d -exec \
          ${pkgs.acl}/bin/setfacl -m d:u:62031:rX {} +
        ${config.ghostship.selfHostedSecrets.renderFor "ghostship-github-coordinator"}/bin/ghostship-secret-project ghostship-github-coordinator
        ${renderOwnerConfig}/bin/ghostship-render-owner-config ${coordinatorConfigTemplate} ${root}/config.json 644
      '';
    };

    virtualisation.oci-containers.containers.ghostship-go-coordinator = {
      image = "ghostship-go-coordinator:${goCoordinatorImage.imageTag}";
      imageFile = goCoordinatorImage;
      pull = "never";
      user = "62033:62033";
      cmd = [ "--state-dir" "/state" "--listen" "0.0.0.0:18765" ];
      environment = {
        T3_SERVER_URL = "http://t3code:3773";
        GHOSTSHIP_COORDINATOR_GITHUB_REPOSITORIES = "ghostship-io/ghostship-agent";
        GHOSTSHIP_COORDINATOR_GITHUB_REPOSITORY = "ghostship-io/ghostship-agent";
      };
      environmentFiles = [ config.ghostship.selfHostedSecrets.projections.ghostship-go-coordinator.path ];
      ports = [ "127.0.0.1:18765:18765" ];
      volumes = [
        "${root}/go-state:/state:rw,noexec,nosuid,nodev"
        "${goCoordinatorHeartbeat}:/opt/ghostship-go-coordinator-heartbeat:ro"
      ];
      extraOptions = hardening ++ [ "--network=ghostship_net" "--pids-limit=48" "--memory=256m" "--cpus=0.5" ];
    };
    systemd.services.podman-ghostship-go-coordinator = {
      after = [ "init-ghostship-net.service" "ghostship-github-t3-token.service" ];
      requires = [ "init-ghostship-net.service" "ghostship-github-t3-token.service" ];
      serviceConfig.EnvironmentFile = [ "/etc/ghostship/owner-identity.env" ];
      preStart = ''
        set -eu
        umask 077
        case "''${GHOSTSHIP_GITHUB_ACCOUNT:-}" in
          (""|*[!A-Za-z0-9-]*) echo "invalid GHOSTSHIP_GITHUB_ACCOUNT in owner identity" >&2; exit 1 ;;
        esac
        ${config.ghostship.selfHostedSecrets.renderFor "ghostship-go-coordinator"}/bin/ghostship-secret-project ghostship-go-coordinator
        token="$(${pkgs.coreutils}/bin/cat /run/ghostship-github/t3-token)"
        ${pkgs.coreutils}/bin/test -n "$token"
        env_file=${lib.escapeShellArg config.ghostship.selfHostedSecrets.projections.ghostship-go-coordinator.path}
        tmp="$env_file.new"
        ${pkgs.coreutils}/bin/cat "$env_file" > "$tmp"
        printf 'T3_BRIDGE_TOKEN=%s\n' "$token" >> "$tmp"
        printf 'GHOSTSHIP_COORDINATOR_GITHUB_OWNER_LOGIN=%s\n' "$GHOSTSHIP_GITHUB_ACCOUNT" >> "$tmp"
        ${pkgs.coreutils}/bin/chown 62033:62033 "$tmp"
        ${pkgs.coreutils}/bin/chmod 0400 "$tmp"
        ${pkgs.coreutils}/bin/mv -f "$tmp" "$env_file"
      '';
    };
  };
}
