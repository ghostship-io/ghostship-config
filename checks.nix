{ pkgs, self }:
let
  python = pkgs.python3.withPackages (ps: [
    ps.lxml
    ps.ruamel-yaml
    ps.requests
    ps.python-socketio
  ]);
  hosts = builtins.attrValues self.nixosConfigurations;
  agentUnits = map (name: self.nixosConfigurations.chill-penguin.config.systemd.services.${name}) [
    "podman-t3code"
  ];
  # Every binary a container unit starts must be seeded into the isolated Nix
  # store and rooted through podman-t3code's preStart, or the daily store GC
  # deletes it and the unit silently fails (e.g. the retention timer).
  t3codeImagePreStart =
    self.nixosConfigurations.chill-penguin.config.systemd.services.podman-t3code.preStart;
  t3codeImageSeedsRetention = pkgs.lib.hasInfix "t3code-retention" t3codeImagePreStart;
  failures = pkgs.lib.concatMap (
    host: map (a: a.message) (builtins.filter (a: !a.assertion) host.config.assertions)
  ) hosts;
in
{
  config-package = self.packages.${pkgs.stdenv.hostPlatform.system}.ghostship-config;
  config-tests =
    pkgs.runCommand "ghostship-config-tests"
      {
        nativeBuildInputs = [
          python
          pkgs.git
          pkgs.php
          pkgs.util-linux
          pkgs.nodejs_24
        ];
      }
      ''
        cp -r ${self} source
        chmod -R u+w source
        cd source
        python modules/common/scripts/ghostship-config.py --test
        python -m unittest discover -s tests -v
        node --test tests/t3code-access-proxy.test.cjs
        python -m compileall -q modules/self-hosted/private-relay-render.py modules/self-hosted/secret-project.py modules/self-hosted/monitoring-provision.py modules/self-hosted/monitoring-heartbeats.py modules/self-hosted/seerr-provision.py modules/self-hosted/dashboard-sync.py modules/self-hosted/cloudflare-sync.py containers/agent-desktop/root/opt/ghostship-agent-desktop/agent_desktop_api.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/cdp_client.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/run_cdp_matrix.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/run_retailer.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/check_cdp_regression.py containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/run_extension.py modules/self-hosted/agent-desktop-mcp.py
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
    assert t3codeImageSeedsRetention;
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
