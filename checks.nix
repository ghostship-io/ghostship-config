{ pkgs, self }:
let
  python = pkgs.python3.withPackages (ps: [
    ps.lxml
    ps.ruamel-yaml
  ]);
  hosts = builtins.attrValues self.nixosConfigurations;
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
          pkgs.util-linux
        ];
      }
      ''
        cp -r ${self} source
        chmod -R u+w source
        cd source
        python modules/common/scripts/ghostship-config.py --test
        python -m unittest discover -s tests -v
        python -m compileall -q modules/self-hosted/secret-project.py modules/self-hosted/monitoring-provision.py modules/self-hosted/monitoring-heartbeats.py modules/self-hosted/seerr-provision.py modules/self-hosted/dashboard-sync.py modules/self-hosted/cloudflare-sync.py
        touch "$out"
      '';
  host-evaluation =
    assert failures == [ ];
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
