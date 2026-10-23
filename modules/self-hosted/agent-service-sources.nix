# The authoritative input boundary for managed service code. Keep it pure so
# fast checks can perturb sources without evaluating SDK or image packages.
{ agent, lib }:
let
  source = paths: builtins.path {
    path = agent.outPath;
    name = "ghostship-service-source";
    filter = path: type:
      let relative = lib.removePrefix (toString agent.outPath + "/") (toString path);
      in lib.any (wanted:
        relative == wanted || lib.hasPrefix (wanted + "/") relative
        || (type == "directory" && lib.hasPrefix (relative + "/") wanted)
      ) paths;
  };
in
{
  coordinator = source ([ "lib/github-integration.nix" "tools/python/ghostship_t3" ]
    ++ map (name: "tools/python/ghostship_github/${name}")
      (lib.filter (name: name != "ingress.py" && lib.hasSuffix ".py" name)
        (builtins.attrNames (builtins.readDir (agent.outPath + "/tools/python/ghostship_github")))));
  hooks = source [ "lib/github-integration.nix" "tools/python/ghostship_github/ingress.py" ];
  integrations = source ([ "lib/private-integrations.nix" "lib/python-wyze.nix"
    "tools/lib/ghostship-mcp-wrapper.sh" "config/google-web-services.json"
    "config/agents/runtime-policy.json" "config/agents/model-identities.json"
    "config/sandbox-profiles" ]
    ++ map (name: "tools/python/ghostship_${name}") [
      "mcp" "registry" "inference" "runtime" "browser" "desktop" "keep"
      "hostops" "services" "health" "t3"
      "sessions" "delegation" "deploy" "github" "worker" "workflows"
    ]);
}
