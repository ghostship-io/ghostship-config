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
  t3codeContainer = t3codeConfig.virtualisation.oci-containers.containers.t3code;
  t3codeUnit = t3codeConfig.systemd.services.podman-t3code;
  githubCoordinator =
    t3codeConfig.virtualisation.oci-containers.containers.ghostship-github-coordinator;
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
    "antigravity/gemini-3.8-flash"
    "antigravity/gemini-3.8-flash-high"
    "antigravity/gemini-4-argon"
  ]
  ++ expectedFreeRoutes;
  actualWorkerRoutes = map routeKey routePolicy.roles.worker.allow;
  expectedOrchestratorRoutes = [ "claudeAgent/claude-opus-5-5" ];
  actualOrchestratorRoutes = map routeKey routePolicy.roles.orchestrator.allow;
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
    assert routePolicy.authorizations == [ ];
    # Fail host evaluation if either process cannot read the policy at the
    # path its CLI uses. This checks evaluated container definitions, not
    # source text, and keeps the environment and read-only mount in lockstep.
    assert t3codeContainer.environment.GHOSTSHIP_ROUTE_POLICY_PATH == routePolicyPath;
    assert builtins.elem "${routePolicyPath}:${routePolicyPath}:ro" t3codeContainer.volumes;
    assert githubCoordinator.environment.GHOSTSHIP_ROUTE_POLICY_PATH == routePolicyPath;
    assert builtins.elem "${routePolicyPath}:${routePolicyPath}:ro" githubCoordinator.volumes;
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
