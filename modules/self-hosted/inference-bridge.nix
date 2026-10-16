{ config, inputs, lib, pkgs, ... }:
let
  cfg = config.ghostship.privateIntegrations;
  tools = inputs.ghostship-private-agent.packages.${pkgs.stdenv.hostPlatform.system};
  broker = tools.free-inference-bridge;
  scheduler = tools.agent;
  token = config.age.secrets.inference-bridge-token.path;
  hostHome = "/srv/apps/t3code/home";
  containerHome = "/home/t3code";
  state = ".local/state/ghostship-free-inference-bridge";
  fixture = ".local/state/ghostship/free-inference/public-fixture";
  endpoint = pkgs.writeText "inference-server.json" (builtins.toJSON {
    socket = "/run/ghostship-integrations/inference-socket/inference.sock";
  });
  managedInstall = pkgs.writeShellScript "ghostship-managed-agents-refresh" ''
    exec ${pkgs.python3}/bin/python ${inputs.ghostship-private-agent}/tools/setup-container-agents.py \
      --source ${inputs.ghostship-private-agent} --home ${containerHome} \
      --tools-package ${tools.default} --managed-only
  '';
  poolConfig = ./inference-pool.json;
  repositories = (builtins.fromJSON (builtins.readFile poolConfig)).repositories;
  publish = pkgs.writeShellScript "ghostship-inference-bridge-prepare" ''
    set -eu
    umask 077
    # Copy pinned inference and managed tools without replacing the active T3 runtime.
    ${pkgs.nix}/bin/nix copy --no-check-sigs \
      --to local?root=/srv/apps/t3code/nix-root ${broker} ${scheduler} ${managedInstall}
    install -d -m0755 /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge
    ln -sfn ${broker} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/package
    ln -sfn ${scheduler} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/scheduler
    ln -sfn ${managedInstall} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/managed-installer
    ${pkgs.podman}/bin/podman exec --user 3000:3000 --env HOME=${containerHome} \
      t3code ${managedInstall}
    install -d -m0750 -o3000 -g62020 ${hostHome}/${state} ${hostHome}/${state}/socket
    install -d -m0750 -o0 -g62020 /run/ghostship-integrations /run/ghostship-integrations/inference-socket
    install -m0600 -o3000 -g62020 ${token} ${hostHome}/${state}/token.new
    mv -fT ${hostHome}/${state}/token.new ${hostHome}/${state}/token
    install -m0400 -o62020 -g62020 ${token} /run/ghostship-integrations/inference-token.new
    mv -fT /run/ghostship-integrations/inference-token.new /run/ghostship-integrations/inference-token
    install -m0444 ${endpoint} /run/ghostship-integrations/inference-server.json.new
    mv -fT /run/ghostship-integrations/inference-server.json.new /run/ghostship-integrations/inference-server.json
    install -d -m0700 -o3000 -g3000 ${hostHome}/.config/ghostship
    install -m0600 -o3000 -g3000 ${poolConfig} ${hostHome}/.config/ghostship/free-inference.json.new
    mv -fT ${hostHome}/.config/ghostship/free-inference.json.new ${hostHome}/.config/ghostship/free-inference.json
    # Seed public toy code only on first setup; preserve an existing Git history.
    if ! test -e ${hostHome}/${fixture}; then
      install -d -m0700 -o3000 -g3000 ${hostHome}/.local/state/ghostship/free-inference
      seed=$(mktemp -d ${hostHome}/${fixture}.seed.XXXXXX)
      trap 'rm -rf "$seed"' EXIT
      install -m0644 ${./inference-fixture/calc.py} "$seed/calc.py"
      install -m0644 ${./inference-fixture/test_calc.py} "$seed/test_calc.py"
      ${pkgs.git}/bin/git -C "$seed" -c init.defaultBranch=main init -q
      ${pkgs.git}/bin/git -C "$seed" add calc.py test_calc.py
      ${pkgs.git}/bin/git -C "$seed" -c user.name=Ghostship \
        -c user.email=ghostship@localhost commit -qm 'Seed public synthetic inference fixture'
      chown -R 3000:3000 "$seed"
      mv -T --no-clobber "$seed" ${hostHome}/${fixture}
    fi
    test -e ${hostHome}/${fixture}/.git
  '';
in
{
  config = lib.mkIf cfg.enable {
    systemd.services.ghostship-inference-bridge = {
      description = "Authenticated free inference broker in the existing T3 container";
      wantedBy = [ "multi-user.target" ];
      after = [ "podman-t3code.service" ];
      requires = [ "podman-t3code.service" ];
      path = [ pkgs.coreutils ];
      restartTriggers = [ config.age.secrets.inference-bridge-token.file poolConfig ];
      serviceConfig = {
        ExecStartPre = publish;
        ExecStart = lib.escapeShellArgs ([
          "${pkgs.podman}/bin/podman" "exec" "--user" "3000:62020"
          "--env" "HOME=${containerHome}"
          "--env" "XDG_STATE_HOME=${containerHome}/.local/state"
          "--env" "GHOSTSHIP_FREE_INFERENCE_CONFIG=${containerHome}/.config/ghostship/free-inference.json"
          "t3code" "${broker}/bin/ghostship-free-inference-bridge"
          "--token-file" "${containerHome}/${state}/token"
          "--socket" "${containerHome}/${state}/socket/inference.sock"
          "--socket-gid" "62020"
        ] ++ lib.concatMap (repository: [ "--repository-root" repository ]) repositories);
        Restart = "on-failure";
        RestartSec = 10;
        TimeoutStartSec = 300;
        TimeoutStopSec = 90;
        NoNewPrivileges = true;
        PrivateTmp = true;
        UMask = "0077";
      };
    };
    # The scheduler owns execution; broker restarts cannot terminate model work.
    systemd.services.ghostship-inference-scheduler = {
      description = "Durable free inference scheduler in the existing T3 container";
      wantedBy = [ "multi-user.target" ];
      after = [ "podman-t3code.service" "ghostship-inference-bridge.service" ];
      requires = [ "podman-t3code.service" ];
      wants = [ "ghostship-inference-bridge.service" ];
      serviceConfig = {
        ExecStart = lib.escapeShellArgs [
          "${pkgs.podman}/bin/podman" "exec" "--user" "3000:62020"
          "--env" "HOME=${containerHome}"
          "--env" "XDG_STATE_HOME=${containerHome}/.local/state"
          "--env" "GHOSTSHIP_FREE_INFERENCE_CONFIG=${containerHome}/.config/ghostship/free-inference.json"
          "t3code" "${scheduler}/bin/agent" "free-inference" "serve"
          "--workers" "2" "--max-jobs" "2" "--poll-seconds" "60"
        ];
        Restart = "on-failure";
        RestartSec = 10;
        TimeoutStopSec = 900;
        NoNewPrivileges = true;
        PrivateTmp = true;
        UMask = "0077";
      };
    };
    virtualisation.oci-containers.containers.ghostship-private-integrations.volumes = [
      "${hostHome}/${state}/socket:/run/ghostship-integrations/inference-socket:ro"
    ];
    systemd.services.podman-ghostship-private-integrations = {
      after = [ "ghostship-inference-bridge.service" ];
      wants = [ "ghostship-inference-bridge.service" ];
    };
  };
}
