{
  pkgs,
  inputs,
  ...
}:

let
  agentTooling = import ../develop/agent-tooling.nix {
    inherit pkgs inputs;
  };
  paseoHome = "/home/nixos/.paseo";
  paseoListen = "127.0.0.1:6767";
  paseoHostnames = "localhost,.localhost";
  ensurePaseoInstalled = pkgs.writeShellScript "ghostship-ensure-paseo-installed" ''
    set -euo pipefail

    export HOME="/home/nixos"
    export PATH="${agentTooling.agentBinDir}:${agentTooling.runtimeBinPath}:$PATH"

    if [ ! -x "${agentTooling.agentBinDir}/paseo" ]; then
      exec ${agentTooling.agentMaintenance}/bin/ghostship-agent-maintenance
    fi
  '';
in
{
  systemd.services.ghostship-paseo = {
    description = "Managed Paseo daemon for WSL desktop attachment";
    after = [
      "network-online.target"
      "ghostship-agent-maintenance.service"
    ];
    wants = [
      "network-online.target"
      "ghostship-agent-maintenance.service"
    ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "simple";
      User = "nixos";
      Group = "nixos";
      WorkingDirectory = "/home/nixos";
      Environment = [
        "HOME=/home/nixos"
        "PASEO_HOME=${paseoHome}"
        "PATH=${agentTooling.agentBinDir}:${agentTooling.runtimeBinPath}"
        "SSH_AUTH_SOCK=/run/user/1000/ssh-agent"
      ];
      ExecStartPre = [
        "${pkgs.coreutils}/bin/mkdir -p ${paseoHome}"
        "${ensurePaseoInstalled}"
      ];
      ExecStart = "${agentTooling.agentBinDir}/paseo start --foreground --home ${paseoHome} --listen ${paseoListen} --hostnames ${paseoHostnames}";
      Restart = "on-failure";
      RestartSec = "5s";
    };
  };
}
