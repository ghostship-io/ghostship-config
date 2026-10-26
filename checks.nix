{
  pkgs,
  self,
  agentSource,
}:
let
  securityPkgs = pkgs.extend (import ./packages/security-fixes).overlay;
  antigravityPkgs = import pkgs.path {
    system = pkgs.stdenv.hostPlatform.system;
    config.allowUnfreePredicate = pkg: pkgs.lib.getName pkg == "antigravity-acp";
  };
  python = pkgs.python3.withPackages (ps: [
    ps.lxml
    ps.ruamel-yaml
    ps.requests
    ps.python-socketio
    ps.json5
    ps.tomli-w
  ]);
  hosts = builtins.attrValues self.nixosConfigurations;
  agentUnits = map (name: self.nixosConfigurations.chill-penguin.config.systemd.services.${name}) [
    "podman-t3code"
  ];
  # Base and managed tooling closures are seeded and rooted separately in the
  # isolated store. A helper missing its tooling root would disappear at GC.
  t3codePreStart =
    self.nixosConfigurations.chill-penguin.config.systemd.services.podman-t3code.preStart;
  # The switch restarts every unit with restartIfChanged. The T3 Code
  # container must never be one of them: an activation that interrupts an
  # active session breaks the work in flight.
  t3codeRestartedBySwitch = builtins.filter (
    name: self.nixosConfigurations.chill-penguin.config.systemd.services.${name}.restartIfChanged
  ) (builtins.attrNames self.nixosConfigurations.chill-penguin.config.systemd.services);
  t3codePreStartSeedsTooling = pkgs.lib.hasInfix "ghostship-t3code-tools" t3codePreStart;
  t3codeConfig = self.nixosConfigurations.chill-penguin.config;
  routePolicyPath = "/etc/ghostship/route-policy.json";
  t3codeServerUnitSource = builtins.readFile ./packages/t3code/image.nix;
  t3codeContainer = t3codeConfig.virtualisation.oci-containers.containers.t3code;
  t3codeUnit = t3codeConfig.systemd.services.podman-t3code;
  t3codeDeploy = t3codeConfig.systemd.services.ghostship-t3code-deploy;
  t3codeDeployImageArchive = t3codeDeploy.environment.IMAGE_ARCHIVE;
  githubCoordinator =
    t3codeConfig.virtualisation.oci-containers.containers.ghostship-github-coordinator;
  goCoordinator =
    t3codeConfig.virtualisation.oci-containers.containers.ghostship-go-coordinator;
  goCoordinatorUnit = t3codeConfig.systemd.services.podman-ghostship-go-coordinator;
  t3codeServiceToken =
    t3codeConfig.ghostship.selfHostedSecrets.projections.t3code.fields.GHOSTSHIP_COORDINATOR_TOKEN;
  goCoordinatorServiceToken =
    t3codeConfig.ghostship.selfHostedSecrets.projections.ghostship-go-coordinator.fields.GHOSTSHIP_COORDINATOR_TOKEN;
  goCoordinatorSecrets = t3codeConfig.ghostship.selfHostedSecrets.projections.ghostship-go-coordinator.fields;
  githubCoordinatorSecrets =
    t3codeConfig.ghostship.selfHostedSecrets.projections.ghostship-github-coordinator.fields;
  githubCoordinatorRuntime =
    t3codeConfig.ghostship.containerRuntimes.ghostship-github-coordinator.runtime;
  t3codeCandidatePodmanPath = t3codeConfig.systemd.services.t3code-podman-candidate.environment.PATH;
  routePolicy = builtins.fromJSON (
    builtins.readFile t3codeConfig.environment.etc."ghostship/route-policy.json".source
  );
  routeKey = route: "${route.provider}/${route.model}";
  expectedFreeRoutes =
    map (entry: "opencode-free/${entry.provider}/${entry.model}")
      (builtins.fromJSON (builtins.readFile ./modules/self-hosted/ai-usage/approved-free-workers.json))
      .entries;
  expectedWorkerRoutes = [
    "codex/gpt-6-luna"
    "claudeAgent/claude-sonnet-5-5"
    "opencode/command-code/deepseek/deepseek-v4.1-flash"
    "opencode/ollama-cloud/deepseek-v4.1-flash:1017"
    "opencode/ollama-cloud/deepseek-v4.1-flash"
    "opencode/opencode-go/deepseek-v4.1-flash"
    "grok/grok-4.7"
    "antigravity/gemini-3.8-flash"
    "antigravity/gemini-3.8-flash-high"
    "antigravity/gemini-4-argon"
  ]
  ++ expectedFreeRoutes;
  actualWorkerRoutes = map routeKey routePolicy.roles.worker.allow;
  expectedOrchestratorRoutes = [ "claudeAgent/claude-opus-5-5" "codex/gpt-6.1-sol" ];
  actualOrchestratorRoutes = map routeKey routePolicy.roles.orchestrator.allow;
  fastBillingDenied = role: builtins.any
    (entry: entry.provider == "*" && entry.model == "*"
      && entry.billing_tier == "priority"
      && builtins.all (tier: builtins.elem tier entry.tiers)
        [ "fastMode=true" "serviceTier=fast" ])
    routePolicy.roles.${role}.deny;
  fableDenied =
    role:
    builtins.all
      (
        model:
        builtins.any (
          entry: entry.provider == "claudeAgent" && entry.model == model
        ) routePolicy.roles.${role}.deny
      )
      [
        "claude-fable-5"
        "claude-fable-5-1"
      ];
  failures = pkgs.lib.concatMap (
    host: map (a: a.message) (builtins.filter (a: !a.assertion) host.config.assertions)
  ) hosts;
in
{
  antigravity-native-loader =
    (antigravityPkgs.callPackage "${agentSource}/packages/t3code/antigravity-acp.nix" { })
    .tests.native-loader;
  podman-ipam = import ./packages/podman-network/regression.nix { pkgs = securityPkgs; };
  config-package = self.packages.${pkgs.stdenv.hostPlatform.system}.ghostship-config;
  config-tests =
    pkgs.runCommand "ghostship-config-tests"
      {
        # The integration tests import the exact pinned coordinator without
        # invoking Nix or fetching inputs inside the build sandbox.
        GHOSTSHIP_TEST_AGENT_SOURCE = agentSource;
        nativeBuildInputs = [
          python
          pkgs.gnutar
          pkgs.inetutils
          pkgs.git
          pkgs.jq
          pkgs.coreutils
          pkgs.php
          pkgs.util-linux
          pkgs.nodejs_24
          pkgs.procps
          pkgs.nginx
        ];
      }
      ''
        cp -r ${self} source
        chmod -R u+w source
        cd source
        python modules/common/scripts/ghostship-config.py --test
        bash tests/test_t3code_deploy_image.sh
        bash tests/test_t3code_activate_deployment.sh
        bash tests/test_t3code_receipt_self_check.sh
        python -m unittest discover -s tests -v
        node --test ${agentSource}/packages/t3code/activity-probe/probe-v1-sqlite.test.cjs
        node --test ${agentSource}/packages/t3code/activity-probe/probe-v2-sqlite.test.cjs
        python -m compileall -q modules/self-hosted/private-relay-render.py modules/self-hosted/secret-project.py modules/self-hosted/monitoring-provision.py modules/self-hosted/render-owner-config.py modules/self-hosted/monitoring-heartbeats.py modules/self-hosted/ghostship-notify.py modules/self-hosted/seerr-provision.py modules/self-hosted/dashboard-sync.py modules/self-hosted/cloudflare-sync.py containers/agent-desktop/root/opt/ghostship-agent-desktop/agent_desktop_api.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/cdp_client.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/run_cdp_matrix.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/run_retailer.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/check_cdp_regression.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/run_extension.py modules/self-hosted/agent-desktop-mcp.py
        touch "$out"
      '';
  # The Python coordinator runs the pinned Go coordinator for review request
  # and review record. Depend on the published runtime, not its source, so a
  # missing binary, a dropped PATH export or a non-review build fails here.
  go-coordinator-review-path =
    pkgs.runCommand "ghostship-go-coordinator-review-path" { } ''
      cli=${githubCoordinatorRuntime}/bin/ghostship-coordinator
      test -x "$cli"
      ${pkgs.gnugrep}/bin/grep -q 'export PATH=/run/ghostship-runtime/current/bin:' \
        ${githubCoordinatorRuntime}/bin/start
      "$cli" review > usage 2>&1 || true
      ${pkgs.gnugrep}/bin/grep -q 'review request' usage
      touch $out
    '';
  host-evaluation =
    assert failures == [ ];
    # The unit always names the stable accepted alias, and never imports the
    # current Nix image archive when systemd starts it. Only the receipt-checked
    # deployer can move this alias.
    assert t3codeContainer.image == "localhost/ghostship-t3code:accepted";
    assert (t3codeContainer.imageFile or null) == null;
    assert pkgs.lib.hasInfix "t3code-receipt-self-check" t3codeUnit.serviceConfig.ExecStartPost;
    assert t3codeUnit.environment.STATE_DIR == "/var/lib/ghostship/t3code-deployment";
    assert pkgs.lib.hasSuffix "/bin/podman" t3codeUnit.environment.PODMAN_BIN;
    assert pkgs.lib.hasSuffix "/bin/jq" t3codeUnit.environment.JQ_BIN;
    assert pkgs.lib.hasSuffix "/bin/t3code-receipt-self-check" t3codeDeploy.environment.RECEIPT_SELF_CHECK;
    assert builtins.all (
      unit:
      !unit.restartIfChanged
      && !unit.stopIfChanged
      && !(builtins.elem "init-ghostship-net.service" unit.requires)
    ) agentUnits;
    assert !(self.nixosConfigurations.chill-penguin.config.systemd.services ? t3code-deploy-when-idle);
    assert !(self.nixosConfigurations.chill-penguin.config.systemd.timers ? t3code-deploy-when-idle);
    assert self.nixosConfigurations.chill-penguin.config.systemd.services ? ghostship-t3code-deploy;
    assert !(self.nixosConfigurations.chill-penguin.config.systemd.timers ? ghostship-t3code-deploy);
    assert builtins.elem "ghostship-failure@%n.service"
      self.nixosConfigurations.chill-penguin.config.systemd.services.ghostship-t3code-deploy.onFailure;
    assert builtins.head (pkgs.lib.splitString ":" t3codeCandidatePodmanPath) == "/run/wrappers/bin";
    assert routePolicy.schema == "ghostship.route-policy/v1";
    assert
      builtins.isInt routePolicy.worker_capacity.default && routePolicy.worker_capacity.default > 0;
    assert
      builtins.isInt routePolicy.worker_capacity.p0_override
      && routePolicy.worker_capacity.p0_override > 0;
    assert
      builtins.sort builtins.lessThan actualWorkerRoutes
      == builtins.sort builtins.lessThan expectedWorkerRoutes;
    assert
      builtins.sort builtins.lessThan actualOrchestratorRoutes
      == builtins.sort builtins.lessThan expectedOrchestratorRoutes;
    assert fableDenied "worker" && fableDenied "orchestrator" && fableDenied "reviewer";
    assert fastBillingDenied "worker" && fastBillingDenied "orchestrator" && fastBillingDenied "reviewer";
    assert routePolicy.authorizations == [ ];
    # Fail host evaluation if the container loses its configured policy path,
    # the server unit stops passing that environment into provider sessions,
    # or the read-only policy mount drifts from the configured path.
    assert t3codeContainer.environment.GHOSTSHIP_ROUTE_POLICY_PATH == routePolicyPath;
    assert pkgs.lib.hasInfix "PassEnvironment=GHOSTSHIP_ROUTE_POLICY_PATH" t3codeServerUnitSource;
    assert builtins.elem "${routePolicyPath}:${routePolicyPath}:ro" t3codeContainer.volumes;
    assert githubCoordinator.environment.GHOSTSHIP_ROUTE_POLICY_PATH == routePolicyPath;
    assert builtins.elem "${routePolicyPath}:${routePolicyPath}:ro" githubCoordinator.volumes;
    assert goCoordinator.imageFile != null;
    assert builtins.elem "127.0.0.1:18765:18765" goCoordinator.ports;
    assert builtins.elem "/var/lib/ghostship-github/go-state:/state:rw,noexec,nosuid,nodev"
      goCoordinator.volumes;
    assert t3codeConfig.ghostship.apps.go-coordinator.apparmorHeartbeat
      == [ "/opt/ghostship-go-coordinator-heartbeat/read-file" "/proc/sys/kernel/random/boot_id" ];
    assert builtins.any (volume: builtins.match ".*:ro" volume != null)
      (builtins.filter (volume: builtins.match ".*ghostship-go-coordinator-heartbeat.*" volume != null)
        goCoordinator.volumes);
    assert builtins.elem "/run/ghostship-secrets/ghostship-github/go-coordinator.env"
      goCoordinator.environmentFiles;
    assert t3codeServiceToken.unit == "go-coordinator-auth";
    assert goCoordinatorServiceToken.unit == "go-coordinator-auth";
    assert goCoordinatorSecrets.GHOSTSHIP_COORDINATOR_GITHUB_WEBHOOK_SECRET.unit == "hooks";
    assert goCoordinatorSecrets.GHOSTSHIP_COORDINATOR_GITHUB_WEBHOOK_SECRET.key == "GITHUB_WEBHOOK_SECRET";
    assert goCoordinator.environment.T3_SERVER_URL == "http://t3code:3773";
    assert goCoordinator.environment.GHOSTSHIP_COORDINATOR_GITHUB_REPOSITORIES
      == "ghostship-io/ghostship-agent";
    assert goCoordinator.environment.GHOSTSHIP_COORDINATOR_GITHUB_REPOSITORY
      == "ghostship-io/ghostship-agent";
    assert t3codeConfig.ghostship.apps.hooks.cloudflareBypassPaths
      == [ "/github" "/cloudflare" "/shadow/github/webhook" ];
    assert t3codeConfig.ghostship.apps.hooks.cloudflarePathRoutes == [ {
      path = "/shadow/github/webhook";
      origin = "http://ghostship-go-coordinator:18765";
    } ];
    assert builtins.elem "ghostship-github-t3-token.service" goCoordinatorUnit.requires;
    assert pkgs.lib.hasInfix "/run/ghostship-github/t3-token" goCoordinatorUnit.preStart;
    assert pkgs.lib.hasInfix "T3_BRIDGE_TOKEN" goCoordinatorUnit.preStart;
    assert pkgs.lib.hasInfix "GHOSTSHIP_COORDINATOR_GITHUB_OWNER_LOGIN" goCoordinatorUnit.preStart;
    assert goCoordinatorUnit.serviceConfig.EnvironmentFile == [ "/etc/ghostship/owner-identity.env" ];
    # The Python coordinator runs the pinned Go coordinator from its published
    # runtime, with a review store directory that exists at boot. Its GitHub
    # token stays in the projected environment file, never the container
    # environment.
    assert builtins.elem
      "d /var/lib/ghostship-github/state/ghostship-coordinator-shadow 0700 ghostship-github ghostship-github -"
      t3codeConfig.systemd.tmpfiles.rules;
    assert builtins.elem
      "${t3codeConfig.ghostship.selfHostedSecrets.projections.ghostship-github-coordinator.path}:/run/secrets/github.env:ro"
      githubCoordinator.volumes;
    assert builtins.elem "--secrets" githubCoordinator.cmd;
    assert builtins.elem "/run/secrets/github.env" githubCoordinator.cmd;
    assert githubCoordinatorSecrets.GITHUB_TOKEN.unit == "github";
    assert githubCoordinatorSecrets.GITHUB_TOKEN.key == "TOKEN";
    assert !(githubCoordinator.environment ? GH_TOKEN);
    assert !(githubCoordinator.environment ? GITHUB_TOKEN);
    assert builtins.elem
      "/etc/ghostship/approved-free-workers.json:/etc/ghostship/approved-free-workers.json:ro"
      t3codeConfig.virtualisation.oci-containers.containers.t3code.volumes;
    assert t3codePreStartSeedsTooling;
    assert !(builtins.elem "podman-t3code" t3codeRestartedBySwitch);
    # Temporary CAD checkouts once filled a 32 GiB tmpfs and stalled the
    # shared T3 cgroup. Check the evaluated mount and its writable sticky mode.
    assert builtins.elem "/srv/apps/t3code/tmp:/tmp:rw"
      self.nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers.t3code.volumes;
    assert builtins.elem "d /srv/apps/t3code/tmp 1777 root root -"
      self.nixosConfigurations.chill-penguin.config.systemd.tmpfiles.rules;
    pkgs.runCommand "ghostship-host-evaluation"
      {
        # Force complete derivation evaluation without building the fleet in CI.
        evaluated = builtins.unsafeDiscardStringContext (
          builtins.toJSON (map (host: host.config.system.build.toplevel.drvPath) hosts)
        );
      }
      ''
        printf '%s\n' "$evaluated" > "$out"
      '';
}
// pkgs.lib.optionalAttrs
  (pkgs.stdenv.hostPlatform.system == t3codeConfig.nixpkgs.hostPlatform.system)
  {
    t3code-deployer-image-archive = pkgs.runCommand "t3code-deployer-image-archive" { } ''
      ${t3codeDeploy.serviceConfig.ExecStart} --list-manifest ${t3codeDeployImageArchive} > manifest.json
      ${pkgs.jq}/bin/jq -e '.[0].Config | strings | length > 0' manifest.json >/dev/null
      touch "$out"
    '';
  }
