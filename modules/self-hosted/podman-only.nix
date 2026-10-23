{ config, lib, ... }:
let
  forbidden =
    package:
    builtins.match "(docker|docker-ce|docker-cli|docker-compose|moby)([-_].*)?" (lib.getName package)
    != null;
  accounts = builtins.attrNames config.users.users ++ builtins.attrNames config.users.groups;
in
{
  assertions = [
    {
      assertion = !(config.virtualisation.docker.enable or false);
      message = "The container runtime must be Podman.";
    }
    {
      assertion =
        !(config.virtualisation.podman.dockerCompat or false)
        && !(config.virtualisation.podman.dockerSocket.enable or false);
      message = "Runtime compatibility binaries and sockets are not allowed.";
    }
    {
      assertion = !lib.any forbidden config.environment.systemPackages;
      message = "Only Podman runtime packages may be installed.";
    }
    {
      assertion = !lib.any (name: builtins.match "(t3code-)?docker" name != null) accounts;
      message = "Obsolete container runtime accounts and groups are forbidden.";
    }
  ];
}
