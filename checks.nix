{
  pkgs,
  self,
  agentSource,
  routeCatalogSource,
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
  # Canonical model evidence the served Go selector reads. Each producer
  # replaces its file atomically, so the mounts are directories.
  modelRoutingHost = "/var/lib/ghostship-ai-usage";
  modelRoutingMount = "/run/ghostship-model-routing";
  modelOutcomesHost = "/srv/apps/t3code/home/.local/state/ghostship/model-evidence";
  modelOutcomesMount = "/run/ghostship-model-evidence";
  # The canonical orchestrator pointer the serving Go coordinator resolves the
  # current role from. Its writer replaces the file atomically, so the service
  # binds the directory and reads the named file inside it.
  orchestratorHost = "/srv/apps/t3code/home/.local/state/ghostship/orchestrator";
  orchestratorMount = "/run/ghostship-orchestrator";
  modelEvidenceAclExec =
    t3codeConfig.systemd.services.ghostship-model-evidence-acl.serviceConfig.ExecStart;
  t3codeServerUnitSource = builtins.readFile ./packages/t3code/image.nix;
  t3codeContainer = t3codeConfig.virtualisation.oci-containers.containers.t3code;
  t3codeUnit = t3codeConfig.systemd.services.podman-t3code;
  t3codeDeploy = t3codeConfig.systemd.services.ghostship-t3code-deploy;
  t3codeDeployImageArchive = t3codeDeploy.environment.IMAGE_ARCHIVE;
  # Issue #611: a switch that restarts the broker, worker or auth unit must
  # never leave the free-inference chain failed or inactive until a manual
  # reset. These are evaluated as data so a unit change that reintroduces the
  # permanent stop fails host evaluation.
  inferenceBridgeUnit = t3codeConfig.systemd.services.ghostship-inference-bridge;
  inferenceSchedulerUnit = t3codeConfig.systemd.services.ghostship-inference-scheduler;
  freeWorkerAuthUnit = t3codeConfig.systemd.services.ghostship-free-worker-auth;
  inferenceProxyUnit = t3codeConfig.systemd.services.ghostship-inference-proxy;
  inferenceProxySocket = t3codeConfig.systemd.sockets.ghostship-inference-proxy;
  privateIntegrationsUnit =
    t3codeConfig.systemd.services.podman-ghostship-private-integrations;
  inferenceDependents = [
    inferenceSchedulerUnit
    freeWorkerAuthUnit
    inferenceProxyUnit
    privateIntegrationsUnit
  ];
  # Issue #639: a switch can restart an inference unit while the runtime
  # publisher is still copying the new closure into the worker container (the
  # exec exited 127 on the missing path), so ordering is not enough. Each start
  # must gate on the exact executable.
  startGatesOnContainerExecutable = executable: unit:
    builtins.any
      (command:
        pkgs.lib.hasInfix "inference-container-wait.py" command
        && pkgs.lib.hasInfix "ghostship-worker" command
        && pkgs.lib.hasInfix executable command)
      (if builtins.isList unit.serviceConfig.ExecStartPre
      then unit.serviceConfig.ExecStartPre
      else [ unit.serviceConfig.ExecStartPre ]);
  githubCoordinator =
    t3codeConfig.virtualisation.oci-containers.containers.ghostship-github-coordinator;
  goCoordinator =
    t3codeConfig.virtualisation.oci-containers.containers.ghostship-go-coordinator;
  goCoordinatorUnit = t3codeConfig.systemd.services.podman-ghostship-go-coordinator;
  t3codeTokenProjection =
    t3codeConfig.ghostship.selfHostedSecrets.projections.t3code-coordinator-token;
  t3codeServiceToken = t3codeTokenProjection.fields.GHOSTSHIP_COORDINATOR_TOKEN;
  # PassEnvironment is the only route a container variable takes into the T3
  # server, whose cgroup includes every provider and its tools. A secret value
  # there is readable by any worker running `env`, so only non-secret paths and
  # URLs may cross. The names come from the secret catalog and the module
  # projections, so a new credential cannot slip through as another field.
  secretCatalog = import ./secrets/catalog.nix { recipients = import ./secrets/recipients.nix; };
  projectedSecretNames = pkgs.lib.unique (
    pkgs.lib.concatMap
      (name: builtins.attrNames secretCatalog.projections.${name}.fields)
      (builtins.attrNames secretCatalog.projections)
    ++ pkgs.lib.concatMap
      (name: builtins.attrNames t3codeConfig.ghostship.secretProjections.${name}.fields)
      (builtins.attrNames t3codeConfig.ghostship.secretProjections)
  );
  t3codePassedEnvironment = pkgs.lib.splitString " " (
    pkgs.lib.last (
      pkgs.lib.splitString "PassEnvironment=" (
        builtins.head (
          pkgs.lib.filter (line: pkgs.lib.hasInfix "PassEnvironment=" line) (
            pkgs.lib.splitString "\n" t3codeServerUnitSource
          )
        )
      )
    )
  );
  credentialsPassedToSessions = pkgs.lib.intersectLists t3codePassedEnvironment projectedSecretNames;
  goCoordinatorServiceToken =
    t3codeConfig.ghostship.selfHostedSecrets.projections.ghostship-go-coordinator.fields.GHOSTSHIP_COORDINATOR_TOKEN;
  goCoordinatorSecrets = t3codeConfig.ghostship.selfHostedSecrets.projections.ghostship-go-coordinator.fields;
  githubCoordinatorSecrets =
    t3codeConfig.ghostship.selfHostedSecrets.projections.ghostship-github-coordinator.fields;
  githubCoordinatorRuntime =
    t3codeConfig.ghostship.containerRuntimes.ghostship-github-coordinator.runtime;
  t3codeCandidatePodmanPath = t3codeConfig.systemd.services.t3code-podman-candidate.environment.PATH;
  # The controller's approved catalog, read back from the rendered /etc file.
  routePolicy = builtins.fromJSON (
    builtins.readFile t3codeConfig.environment.etc."ghostship/route-policy.json".source
  );
  # The reconciliation of 2026-10-30 (owner + orchestrator): only these exact
  # routes are approved. Everything else in the catalog is admit:false, so a
  # hand edit to the catalog that admits an unapproved model fails this check.
  approvedRoutes = [
    "opencode/ollama-cloud/deepseek-v4.1-flash"
    "opencode/ollama-cloud/deepseek-v4.1-flash:1017"
    "opencode/opencode-go/deepseek-v4.1-flash"
    "opencode-free/opencode/deepseek-v4.1-flash-free"
    "opencode/command-code/deepseek/deepseek-v4.1-flash"
    "opencode/literouter/deepseek-v4.1-flash-1017:full-context"
    "antigravity/gemini-3.8-flash"
    "claudeAgent/claude-sonnet-5-5"
    "codex/gpt-6.1-terra"
  ];
  actualApprovedRoutes = map
    (r: "${r.provider_instance}/${r.model}")
    (builtins.filter (r: r.admit) routePolicy.routes);
  # The coordinator's per-repository ceiling must never undercut the route
  # policy's global worker cap: a hidden default of 3 refused fast-lane
  # launches while the policy still had room.
  managedRepositories = t3codeConfig.ghostship.githubEngineering.repositories;
  underCappedRepositories = builtins.filter
    (name:
      !(managedRepositories.${name} ? max_active)
      || managedRepositories.${name}.max_active < routePolicy.worker_capacity.default)
    (builtins.attrNames managedRepositories);
  failures = pkgs.lib.concatMap (
    host: map (a: a.message) (builtins.filter (a: !a.assertion) host.config.assertions)
  ) hosts;
in
{
  mcp-rollout = import ./packages/mcp-rollout { inherit pkgs; };
  antigravity-native-loader =
    (antigravityPkgs.callPackage "${agentSource}/packages/t3code/antigravity-acp.nix" { })
    .tests.native-loader;
  podman-ipam = import ./packages/podman-network/regression.nix { pkgs = securityPkgs; };
  # The release-window holder must be proved as the *generated* wrapper, not as
  # the repository text: `$$` once reached the built script as `$`, which two
  # live releases discovered and no source-level test could.
  window-holder = let
    holder = import ./packages/t3code/window-holder.nix { inherit pkgs; };
    # The generated wrappers the host actually installs. Building them forces
    # their own text through shellcheck, so a quoting failure is a config check
    # failure instead of a release-build surprise.
    hostWrappers = builtins.filter
      (p: builtins.elem (p.name or "") [
        "ghostship-t3code-release-window"
        "ghostship-t3code-invalidate-failure"
      ])
      t3codeConfig.environment.systemPackages;
    # Building the generated release-window wrapper also proves it parses and
    # passes its own checks; the source text alone never did.
    window = pkgs.writeShellApplication {
      name = "ghostship-t3code-release-window";
      runtimeInputs = [ pkgs.coreutils pkgs.util-linux pkgs.systemd pkgs.podman pkgs.jq pkgs.su-exec ];
      text = builtins.readFile ./packages/t3code/release-window.sh;
    };
  in
  pkgs.runCommand "ghostship-t3code-window-holder-check" { } ''
    dir="$TMPDIR/window"; mkdir -p "$dir"
    : > "$TMPDIR/lock1"; : > "$TMPDIR/lock2"
    # Run the built binary in the environment the systemd manager provides.
    /usr/bin/env -i PATH=/nonexistent       ${holder}/bin/ghostship-t3code-window-holder "$TMPDIR/lock1" "$TMPDIR/lock2" "$dir" &
    holder=$!
    for _ in $(seq 1 200); do [ -f "$dir/holder.ready" ] && break; sleep 0.05; done
    [ -f "$dir/holder.ready" ] || { echo 'holder never wrote holder.ready' >&2; kill $holder; exit 1; }
    pid=$(cat "$dir/holder.ready")
    case "$pid" in
      '''|*[!0-9]*) echo "holder.ready is not a numeric PID: '$pid'" >&2; kill $holder; exit 1 ;;
    esac
    kill "$holder" 2>/dev/null || true
    # systemd expands `$$` in an ExecStart, so a PID written there arrives as
    # "$". Forbid it on the systemd-run command line specifically; `$$` is still
    # legitimate elsewhere in the script.
    if ${pkgs.gnugrep}/bin/grep -A1 'SYSTEMD_RUN_BIN" --quiet' \
        ${window}/bin/ghostship-t3code-release-window | ${pkgs.gnugrep}/bin/grep -q '\$\$'; then
      echo 'systemd-run command line contains $$, which systemd expands to $' >&2
      exit 1
    fi
    test -x ${window}/bin/ghostship-t3code-release-window
    # The host packages, not a copy: the release builds exactly these.
    [ ${toString (builtins.length hostWrappers)} -eq 2 ] || { echo 'host wrapper packages missing from systemPackages' >&2; exit 1; }
    ${pkgs.lib.concatMapStringsSep "\n    " (p: "test -x ${p}/bin/${p.name}") hostWrappers}
    touch "$out"
  '';

  # Issue #1747: a green check must build the deployment wrappers the host
  # installs. Their definitions are module-local, so each one below mirrors its
  # modules/self-hosted/t3code.nix definition with the check's own pkgs: same
  # source files, prepended constants, runtimeInputs and excluded checks. That
  # keeps their generated text in shellcheck without a host-platform build.
  # Shared definitions are the follow-up once #730 lands.
  deployment-wrappers =
    let
      t3codeWindowConfig = "/etc/ghostship/t3code-release-window-dir";
      t3codeDeploymentState = "/var/lib/ghostship/t3code-deployment";
      t3codeWindowConfigFile = pkgs.writeText "t3code-release-window-dir" "${t3codeDeploymentState}/release-window\n";
      t3codeWindowHolder = import ./packages/t3code/window-holder.nix { inherit pkgs; };
      # t3code.nix:73
      t3codeImmediateDeploy = pkgs.writeShellApplication {
        name = "ghostship-t3code-deploy-image";
        # The single-quoted jq programs intentionally avoid shell interpolation.
        excludeShellChecks = [ "SC2016" ];
        runtimeInputs = [ pkgs.coreutils pkgs.gnutar pkgs.gzip pkgs.inetutils pkgs.jq pkgs.podman pkgs.systemd pkgs.util-linux ];
        text = ''
          export WINDOW_CONFIG=${pkgs.lib.escapeShellArg t3codeWindowConfig}
          export WINDOW_INTENT_HELPER=${./packages/t3code/window-intent.sh}
          ${builtins.readFile ./packages/t3code/receipt-checks.sh}
          ${builtins.readFile ./packages/t3code/deploy-image.sh}
        '';
      };
      # t3code.nix:85
      t3codeInvalidateFailure = pkgs.writeShellApplication {
        name = "ghostship-t3code-invalidate-failure";
        text = ''
          export STATE_DIR=${pkgs.lib.escapeShellArg t3codeDeploymentState}
          export JQ_BIN=${pkgs.lib.getExe pkgs.jq}
          exec ${pkgs.lib.getExe t3codeImmediateDeploy} --invalidate-failure "$@"
        '';
      };
      # t3code.nix:93
      t3codeActivateDeployment = pkgs.writeShellApplication {
        name = "ghostship-t3code-activate-deployment";
        runtimeInputs = [ pkgs.coreutils pkgs.util-linux ];
        text = ''
          export WINDOW_CONFIG=${pkgs.lib.escapeShellArg t3codeWindowConfig}
          export WINDOW_INTENT_HELPER=${./packages/t3code/window-intent.sh}
          ${builtins.readFile ./packages/t3code/activate-deployment.sh}
        '';
      };
      # t3code.nix:102
      t3codeReleaseWindow = pkgs.writeShellApplication {
        name = "ghostship-t3code-release-window";
        runtimeInputs = [ pkgs.coreutils pkgs.util-linux pkgs.systemd pkgs.podman pkgs.jq pkgs.su-exec ];
        text = ''
          export WINDOW_CONFIG=${t3codeWindowConfigFile}
          export WINDOW_BOOTSTRAP=${./packages/t3code/window-bootstrap.sh}
          export WINDOW_INTENT_HELPER=${./packages/t3code/window-intent.sh}
          export STATE_DIR=${pkgs.lib.escapeShellArg t3codeDeploymentState}
          export SYSTEMCTL_BIN=${pkgs.systemd}/bin/systemctl
          export SYSTEMD_RUN_BIN=${pkgs.systemd}/bin/systemd-run
          export WINDOW_HOLDER_BIN=${pkgs.lib.getExe t3codeWindowHolder}
          export PODMAN_BIN=${pkgs.podman}/bin/podman
          export JQ_BIN=${pkgs.jq}/bin/jq
          export SUEXEC_BIN=${pkgs.su-exec}/bin/su-exec
          # The window holder runs under the systemd manager, which does not inherit
          # this script's PATH, so every command it uses must be an absolute path.
          export COREUTILS_BIN=${pkgs.coreutils}/bin
          export UTIL_LINUX_BIN=${pkgs.util-linux}/bin
          export BASH_BIN=${pkgs.bash}/bin/bash
          ${builtins.readFile ./packages/t3code/receipt-checks.sh}
          ${builtins.readFile ./packages/t3code/release-window.sh}
        '';
      };
      # t3code.nix:130
      t3codeReceiptSelfCheck = pkgs.writeShellApplication {
        name = "t3code-receipt-self-check";
        excludeShellChecks = [ "SC2016" ];
        runtimeInputs = [ pkgs.coreutils pkgs.jq pkgs.podman pkgs.systemd ];
        text = ''
          ${builtins.readFile ./packages/t3code/receipt-checks.sh}
          ${builtins.readFile ./packages/t3code/receipt-self-check.sh}
        '';
      };
      # t3code.nix:147
      t3codeNixStoreGc = pkgs.writeShellApplication {
        name = "t3code-nix-store-gc";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.util-linux
          pkgs.podman
        ];
        text = ''
          if test -z "$(podman ps --quiet --filter 'name=^t3code$')"; then
            echo "t3code container is not running; skipping isolated Nix store GC" >&2
            exit 0
          fi
          flock -w 300 /run/ghostship-maintenance.lock \
            podman exec t3code nix store gc
        '';
      };
      wrappers = [
        t3codeImmediateDeploy
        t3codeInvalidateFailure
        t3codeActivateDeployment
        t3codeReleaseWindow
        t3codeReceiptSelfCheck
        t3codeNixStoreGc
      ];
    in
    pkgs.runCommand "ghostship-t3code-deployment-wrappers-check" { } ''
      ${pkgs.lib.concatMapStringsSep "\n  " (p: "test -x ${p}/bin/${p.name}") wrappers}
      touch "$out"
    '';

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
        bash tests/test_t3code_deploy_script.sh
        # #804 shipped this proof without wiring it; the wiring guard refuses
        # an unwired T3 deployment proof.
        bash tests/test_t3code_deploy_status.sh
        bash tests/test_t3code_release_window.sh
        bash tests/test_t3code_unknown_ending.sh
        bash tests/test_t3code_worker_dev_env.sh
        bash tests/test_t3code_skills_publish_gate.sh
        bash tests/test_t3code_window_lock.sh
        bash tests/test_t3code_served_identity.sh
        bash tests/test_t3code_window_lock_slow.sh
        bash tests/test_t3code_checks_wiring.sh
        bash tests/test_t3code_activate_deployment.sh
        bash tests/test_t3code_receipt_self_check.sh
        bash tests/test_t3code_receipt_checks.sh
        bash tests/test_t3code_tooling_pointer.sh
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
    # A precondition miss (exit 75) is retried by systemd; deploy-image.sh bounds it.
    assert t3codeDeploy.serviceConfig.RestartForceExitStatus == "75" && t3codeDeploy.serviceConfig.RestartSec == "120";
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
    assert
      builtins.isInt routePolicy.worker_capacity.default && routePolicy.worker_capacity.default > 0;
    assert
      builtins.isInt routePolicy.worker_capacity.p0_override
      && routePolicy.worker_capacity.p0_override > 0;
    # Every managed repository carries a max_active at least the route policy's
    # worker_capacity default, so no hidden per-repository ceiling blocks a
    # launch the global cap would allow.
    assert managedRepositories != { };
    assert pkgs.lib.assertMsg (underCappedRepositories == [ ])
      "repository max_active is missing or below the route policy worker_capacity.default: ${builtins.concatStringsSep ", " underCappedRepositories}";
    # The installed catalog is the approved v2 file, verbatim from its pin, and
    # it admits exactly the owner-reconciled exact models.
    assert routePolicy.schema == "ghostship.route-policy/v2";
    assert t3codeConfig.environment.etc."ghostship/route-policy.json".source
      == "${routeCatalogSource}/config/agents/route-policy.json";
    assert
      builtins.sort builtins.lessThan actualApprovedRoutes
      == builtins.sort builtins.lessThan approvedRoutes;
    assert builtins.any
      (r: r.provider_instance == "antigravity" && r.model == "gemini-3.8-flash"
        && r.effort_source == "provider_default" && r.efforts == [ "provider_default" ]
        && r.buckets == [ "low" "medium" "high" ]) routePolicy.routes;
    assert pkgs.lib.assertMsg
      (builtins.any (r: r.provider_instance == "opencode"
        && r.model == "ollama-cloud/deepseek-v4-pro") routePolicy.routes)
      "the denied V4 Pro route must stay recorded in the catalog";
    assert builtins.all
      (r: r.admit == false)
      (builtins.filter (r: r.model == "ollama-cloud/deepseek-v4-pro") routePolicy.routes);
    assert builtins.all
      (r: r.fallback_only or false)
      (builtins.filter (r: r.provider_instance == "claudeAgent" || r.provider_instance == "codex")
        routePolicy.routes);
    assert builtins.elem "claudeAgent" routePolicy.deny.instances_for_subordinate_roles;
    assert builtins.elem "codex" routePolicy.deny.instances_for_subordinate_roles;
    assert routePolicy.deny.fast_mode == true;
    assert builtins.elem "priority" routePolicy.deny.billing_tiers;
    # Fail host evaluation if the container loses its configured policy path,
    # the server unit stops passing that environment into provider sessions,
    # or the read-only policy mount drifts from the configured path.
    assert t3codeContainer.environment.GHOSTSHIP_ROUTE_POLICY_PATH == routePolicyPath;
    assert pkgs.lib.hasInfix "PassEnvironment=GHOSTSHIP_ROUTE_POLICY_PATH" t3codeServerUnitSource;
    assert builtins.elem "${routePolicyPath}:${routePolicyPath}:ro" t3codeContainer.volumes;
    assert githubCoordinator.environment.GHOSTSHIP_ROUTE_POLICY_PATH == routePolicyPath;
    # Exec sessions resolve the pinned Go coordinator from the container PATH.
    assert pkgs.lib.hasPrefix "/run/ghostship-runtime/current/bin:" githubCoordinator.environment.PATH;
    assert builtins.elem "${routePolicyPath}:${routePolicyPath}:ro" githubCoordinator.volumes;
    # The Go CLI inside the T3 container calls the live coordinator over the
    # shared network, authenticated by the same secret the service reads. The
    # token comes only from the projected environment file, never the repo.
    assert t3codeContainer.environment.GHOSTSHIP_COORDINATOR_URL
      == "http://ghostship-go-coordinator:18765";
    assert credentialsPassedToSessions == [ ];
    assert pkgs.lib.hasInfix
      "PassEnvironment=GHOSTSHIP_ROUTE_POLICY_PATH GHOSTSHIP_COORDINATOR_URL GHOSTSHIP_COORDINATOR_TOKEN_FILE"
      t3codeServerUnitSource;
    assert !(t3codeContainer.environment ? GHOSTSHIP_COORDINATOR_TOKEN);
    assert t3codeContainer.environment.GHOSTSHIP_COORDINATOR_TOKEN_FILE
      == "/run/secrets/coordinator-token.env";
    assert !(
      t3codeConfig.ghostship.selfHostedSecrets.projections.t3code.fields
      ? GHOSTSHIP_COORDINATOR_TOKEN
    );
    assert builtins.elem
      "${t3codeTokenProjection.containerPath}:/run/secrets/coordinator-token.env:ro"
      t3codeContainer.volumes;
    assert builtins.elem t3codeConfig.ghostship.selfHostedSecrets.projections.t3code.path
      t3codeContainer.environmentFiles;
    assert t3codeServiceToken.unit == "go-coordinator-auth";
    assert t3codeServiceToken.key == "TOKEN";
    assert goCoordinatorSecrets.GHOSTSHIP_COORDINATOR_TOKEN.unit == t3codeServiceToken.unit;
    assert goCoordinatorSecrets.GHOSTSHIP_COORDINATOR_TOKEN.key == t3codeServiceToken.key;
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
    assert goCoordinatorServiceToken.unit == "go-coordinator-auth";
    assert goCoordinatorSecrets.GHOSTSHIP_T3_PLAINTEXT_HOSTS.unit == "go-coordinator-plaintext-hosts";
    assert goCoordinatorSecrets.GHOSTSHIP_T3_PLAINTEXT_HOSTS.key == "GHOSTSHIP_T3_PLAINTEXT_HOSTS";
    assert goCoordinatorSecrets.GHOSTSHIP_COORDINATOR_GITHUB_WEBHOOK_SECRET.unit == "hooks";
    assert goCoordinatorSecrets.GHOSTSHIP_COORDINATOR_GITHUB_WEBHOOK_SECRET.key == "GITHUB_WEBHOOK_SECRET";
    assert goCoordinator.environment.GOMEMLIMIT == "384MiB";
    assert builtins.elem "--memory=512m" goCoordinator.extraOptions;
    assert goCoordinator.environment.T3_SERVER_URL == "http://t3code:3773";
    assert goCoordinator.environment.GHOSTSHIP_COORDINATOR_GITHUB_REPOSITORIES
      == "ghostship-io/ghostship-agent";
    assert goCoordinator.environment.GHOSTSHIP_COORDINATOR_GITHUB_REPOSITORY
      == "ghostship-io/ghostship-agent";
    # The service must read current model evidence: the canonical routing
    # snapshot and the T3 outcome ledger are mounted read-only, and the
    # service is told the file path inside each mount. Without both, healthz
    # reports every source as unavailable.
    assert goCoordinator.environment.GHOSTSHIP_MODEL_RANKINGS_PATH
      == "${modelRoutingMount}/routing.json";
    assert goCoordinator.environment.GHOSTSHIP_MODEL_EVIDENCE_PATH
      == "${modelOutcomesMount}/model-evidence.jsonl";
    assert builtins.elem "${modelRoutingHost}:${modelRoutingMount}:ro,noexec,nosuid,nodev"
      goCoordinator.volumes;
    assert builtins.elem "${modelOutcomesHost}:${modelOutcomesMount}:ro,noexec,nosuid,nodev"
      goCoordinator.volumes;
    # The serving coordinator resolves the current orchestrator from the one
    # canonical pointer directory, never from its own home, and both
    # coordinators read the same projection so a rotation has one authority.
    assert goCoordinator.environment.GHOSTSHIP_ORCHESTRATOR_FILE
      == "${orchestratorMount}/pointer.env";
    assert builtins.elem "${orchestratorHost}:${orchestratorMount}:ro,noexec,nosuid,nodev"
      goCoordinator.volumes;
    assert builtins.elem "${orchestratorHost}:${orchestratorMount}:ro,noexec,nosuid,nodev"
      githubCoordinator.volumes;
    # The outcome ledger is written 0600 by the T3 recorder; the unit grants
    # this container's uid read through the directory ACL.
    assert pkgs.lib.hasInfix "u:62033:rx" goCoordinatorUnit.preStart;
    assert pkgs.lib.hasInfix "d:u:62033:rX" goCoordinatorUnit.preStart;
    # A rewrite replaces the ledger with a 0600 file, so the startup grant alone
    # does not survive. The path unit must re-apply it to the current file.
    assert t3codeConfig.systemd.paths.ghostship-model-evidence-acl.pathConfig.Unit
      == "ghostship-model-evidence-acl.service";
    assert t3codeConfig.systemd.paths.ghostship-model-evidence-acl.pathConfig.PathChanged
      == "${modelOutcomesHost}/model-evidence.jsonl";
    # PathExists= re-fires whenever the service goes inactive while the file
    # exists, so the oneshot loops into start-limit-hit. Activation runs it once.
    assert !(t3codeConfig.systemd.paths.ghostship-model-evidence-acl.pathConfig ? PathExists);
    assert builtins.elem "multi-user.target"
      t3codeConfig.systemd.services.ghostship-model-evidence-acl.wantedBy;
    # The unit must not watch the directory: the service's own metadata change
    # would retrigger it. A correct ACL is left untouched, so one rewrite causes
    # exactly one run and a run cannot retrigger itself.
    assert !(t3codeConfig.systemd.paths.ghostship-model-evidence-acl.pathConfig ? PathModified);
    assert pkgs.lib.hasInfix " ${modelOutcomesHost}/model-evidence.jsonl " modelEvidenceAclExec;
    assert pkgs.lib.hasSuffix "-acl-${pkgs.acl.version}-bin/bin/getfacl" modelEvidenceAclExec;
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
    # Issue #652: only the clean-stop status of the attached `podman run` is
    # accepted; a crash or a failed start still fails the unit.
    assert t3codeUnit.serviceConfig.SuccessExitStatus == "130";
    # An unplanned 130 exit must still restart the container, not end quietly.
    assert t3codeUnit.serviceConfig.Restart == "on-failure";
    assert t3codeUnit.serviceConfig.RestartForceExitStatus == "130";
    # Issue #611: a switch restarting any inference unit must recover without
    # a manual reset. The bridge/scheduler retry forever, and no dependent
    # carries a Requires edge that would deactivate it with its dependency.
    assert inferenceBridgeUnit.serviceConfig.Restart == "always";
    assert inferenceSchedulerUnit.serviceConfig.Restart == "always";
    assert inferenceBridgeUnit.unitConfig.StartLimitIntervalSec == 0;
    assert inferenceBridgeUnit.unitConfig.StartLimitBurst == 0;
    assert inferenceSchedulerUnit.unitConfig.StartLimitIntervalSec == 0;
    assert inferenceSchedulerUnit.unitConfig.StartLimitBurst == 0;
    assert builtins.elem "podman-ghostship-worker.service" inferenceBridgeUnit.after;
    assert builtins.elem "podman-ghostship-worker.service" inferenceBridgeUnit.wants;
    assert !(builtins.elem "podman-ghostship-worker.service" inferenceBridgeUnit.requires);
    # Issue #651: the bridge publishes under the managed refresh lock, so an
    # agent-bump switch must start it only after the release refresh.
    assert builtins.elem "ghostship-managed-agent-release-refresh.service" inferenceBridgeUnit.after;
    # Issue #639: a switch stop must signal the container process and wait for
    # it, never accept an arbitrary failure exit status from Podman. The braced
    # MAINPID keeps its (possibly empty) argument; the unbraced form is dropped.
    assert pkgs.lib.hasInfix "inference-container-stop.py" inferenceBridgeUnit.serviceConfig.ExecStop;
    assert pkgs.lib.hasInfix "--main-pid=\${MAINPID}" inferenceBridgeUnit.serviceConfig.ExecStop;
    assert pkgs.lib.hasInfix "ghostship_inference.server" inferenceBridgeUnit.serviceConfig.ExecStop;
    assert pkgs.lib.hasInfix "inference-container-stop.py" inferenceSchedulerUnit.serviceConfig.ExecStop;
    assert pkgs.lib.hasInfix "--main-pid=\${MAINPID}" inferenceSchedulerUnit.serviceConfig.ExecStop;
    assert pkgs.lib.hasInfix "ghostship_inference.cli serve" inferenceSchedulerUnit.serviceConfig.ExecStop;
    assert !(pkgs.lib.hasInfix " $MAINPID " inferenceBridgeUnit.serviceConfig.ExecStop);
    assert !(pkgs.lib.hasInfix " $MAINPID " inferenceSchedulerUnit.serviceConfig.ExecStop);
    assert !(inferenceBridgeUnit.serviceConfig ? SuccessExitStatus);
    assert !(inferenceSchedulerUnit.serviceConfig ? SuccessExitStatus);
    # The start gate must name the exact binary and the worker container, so a
    # switch restart waits for the published closure instead of executing a
    # path the container does not have yet.
    assert startGatesOnContainerExecutable "/bin/ghostship-free-inference-bridge" inferenceBridgeUnit;
    assert startGatesOnContainerExecutable "/bin/agent" inferenceSchedulerUnit;
    # The gate waits up to 1200 s. The systemd default would kill a slow but
    # successful publication, so each start must outlast the gate.
    assert inferenceBridgeUnit.serviceConfig.TimeoutStartSec == 1500;
    assert inferenceSchedulerUnit.serviceConfig.TimeoutStartSec == 1500;
    assert builtins.all (
      unit:
      !(builtins.elem "ghostship-inference-bridge.service" unit.requires)
      && !(builtins.elem "ghostship-free-worker-auth.service" unit.requires)
    ) inferenceDependents;
    assert inferenceProxySocket.socketConfig.TriggerLimitIntervalSec == 0;
    assert inferenceProxySocket.socketConfig.TriggerLimitBurst == 0;
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
