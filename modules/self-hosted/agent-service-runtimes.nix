# Content-scoped GhostShip code. No release version or whole-flake revision is
# part of a service runtime; each service receives only its executable inputs.
{ agent, system, mcpIcon ? null }:
let
  pkgs = import agent.inputs.nixpkgs { inherit system; };
  inherit (pkgs) lib;
  sources = import ./agent-service-sources.nix { inherit agent lib; };
  github = root: import (root + "/lib/github-integration.nix") { inherit pkgs; };
  privateSource = sources.integrations;
  tools = import (agent.outPath + "/lib/mkPackages.nix") { inherit pkgs; };
  private = import (privateSource + "/lib/private-integrations.nix") {
    inherit pkgs mcpIcon;
    inherit (tools) serviceClients;
  };
  ingress = github sources.hooks;
  coordinator = github sources.coordinator;
  start = name: text: pkgs.writeTextFile {
    name = "ghostship-${name}-entrypoint";
    destination = "/bin/start";
    executable = true;
    text = "#!${pkgs.bash}/bin/bash\nset -eu\n" + text;
  };
in
{
  inherit private;
  # Stable image bootstrap calls these through a managed, atomic current link.
  hooks = start "hooks" ''
    exec ${ingress.ingressPython}/bin/python3 -I -B ${ingress.ingressScript}/share/ghostship-github/ingress.py "$@"
  '';
  coordinator = start "coordinator" ''
    export PYTHONPATH=${coordinator.coordinatorRuntime}/share/ghostship-github/python
    export SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    exec ${coordinator.coordinatorPython}/bin/python3 -B -m ghostship_github.coordinator "$@"
  '';
  integrations = start "integrations" ''
    export SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    exec ${pkgs.python3.withPackages (ps: [ ps.mcp ps.jsonschema ps.pypdf ps.websockets ps.pillow (import (privateSource + "/lib/python-wyze.nix") ps) ])}/bin/python3 \
      ${privateSource}/tools/python/ghostship_mcp/supervisor.py \
      ${private.relay}/bin/tunnel-client ${private.runtime}/bin/ghostship-mcp ${private.sharedSocket} "$@"
  '';
}
