{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.agentHost;
  projects = config.ghostship.agentProjects;
  projectsJson = pkgs.writeText "agent-projects.json" (builtins.toJSON projects);
in
{
  config = lib.mkIf cfg.enable {
    environment.etc."ghostship/agent-projects.json".source = projectsJson;
  };
}
