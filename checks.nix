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
  failures = pkgs.lib.concatMap (
    host: map (a: a.message) (builtins.filter (a: !a.assertion) host.config.assertions)
  ) hosts;
in
{
  antigravity-native-loader =
    (antigravityPkgs.callPackage "${agentSource}/packages/t3code/antigravity-acp.nix" { }).tests.native-loader;
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
          pkgs.git
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
        python -m unittest discover -s tests -v
        node --test ${agentSource}/packages/t3code/activity-probe/probe-v1-sqlite.test.cjs
        node --test ${agentSource}/packages/t3code/activity-probe/probe-v2-sqlite.test.cjs
        python -m compileall -q modules/self-hosted/private-relay-render.py modules/self-hosted/secret-project.py modules/self-hosted/monitoring-provision.py modules/self-hosted/render-owner-config.py modules/self-hosted/monitoring-heartbeats.py modules/self-hosted/ghostship-notify.py modules/self-hosted/seerr-provision.py modules/self-hosted/dashboard-sync.py modules/self-hosted/cloudflare-sync.py containers/agent-desktop/root/opt/ghostship-agent-desktop/agent_desktop_api.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/cdp_client.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/run_cdp_matrix.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/run_retailer.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/check_cdp_regression.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/run_extension.py modules/self-hosted/agent-desktop-mcp.py
        touch "$out"
      '';
  host-evaluation =
    assert failures == [ ];
    assert builtins.all (
      unit:
      !unit.restartIfChanged
      && !unit.stopIfChanged
      && !(builtins.elem "init-ghostship-net.service" unit.requires)
    ) agentUnits;
    assert self.nixosConfigurations.chill-penguin.config.systemd.services ? t3code-deploy-when-idle;
    assert self.nixosConfigurations.chill-penguin.config.systemd.timers ? t3code-deploy-when-idle;
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
