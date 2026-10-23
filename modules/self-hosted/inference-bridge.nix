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
  endpoint = pkgs.writeText "inference-server.json" (builtins.toJSON {
    socket = "/run/ghostship-integrations/inference-socket/inference.sock";
  });
  managedInstall = pkgs.writeShellScript "ghostship-managed-agents-refresh" ''
    unset LD_LIBRARY_PATH
    exec ${pkgs.python3}/bin/python ${inputs.ghostship-private-agent}/tools/setup-container-agents.py \
      --source ${inputs.ghostship-private-agent} --home ${containerHome} \
      --tools-package ${tools.default} --managed-only "$@"
  '';
  sourceSync = import ../../packages/t3code/source-sync.nix {
    inherit lib pkgs;
    installer = managedInstall;
  };
  maintenance = config.system.build.t3codeToolMaintenance;
  toolUpdate = config.system.build.t3codeToolAutoUpdate;
  toolUpdateOverride = pkgs.writeText "t3code-free-worker-tool-update.conf" ''
    [Service]
    ExecStart=
    ExecStart=${toolUpdate}/bin/t3code-tool-auto-update
  '';
  syncOverride = pkgs.writeText "t3code-ghostship-agent-sync-managed.conf" ''
    [Service]
    ExecStart=
    ExecStart=${sourceSync}/bin/t3code-install-ghostship-agent
  '';
  workerHome = "/home/worker";
  workerData = "/srv/apps/ghostship-worker";
  workerSocket = "/run/ghostship-worker/socket/inference.sock";
  projection = "/run/ghostship-worker/secrets/credentials.env";
  clientEndpoint = pkgs.writeText "t3-inference-server.json" (builtins.toJSON {
    socket = "${containerHome}/${state}/socket/inference.sock";
  });
  disabledLocalPool = pkgs.writeText "t3-no-local-free-pool.json" (builtins.toJSON {
    providers = { };
    require_sandbox = true;
  });
  writeClient = pkgs.writeShellScript "ghostship-inference-client-write" ''
    set -eu
    umask 077
    install -d -m0755 /run/ghostship-integrations
    cat > /run/ghostship-integrations/inference-token.new
    chown 3000:62020 /run/ghostship-integrations/inference-token.new
    chmod 0400 /run/ghostship-integrations/inference-token.new
    mv -fT /run/ghostship-integrations/inference-token.new /run/ghostship-integrations/inference-token
    install -m0444 ${clientEndpoint} /run/ghostship-integrations/inference-server.json.new
    mv -fT /run/ghostship-integrations/inference-server.json.new /run/ghostship-integrations/inference-server.json
    install -D -m0600 -o3000 -g3000 ${disabledLocalPool} ${containerHome}/.config/ghostship/free-inference.json
  '';
  isolateT3Models = pkgs.writeShellScript "t3-free-worker-model-scope" ''
    set -eu
    exec ${pkgs.python3}/bin/python3 ${../../packages/t3code/opencode-model-catalog.py} \
      --source ${containerHome}/.cache/opencode/models.json \
      --config ${containerHome}/.config/opencode/opencode.jsonc \
      --output ${containerHome}/.local/state/t3code-opencode/models.json
  '';
  publish = pkgs.writeShellScript "ghostship-inference-bridge-prepare" ''
    set -eu
    umask 077
    # A replaced container runs t3code-container-setup at boot, whose `chown -R t3code:t3code
    # ~/.local` would reset the bridge socket and token to group t3code after this script
    # sets group 62020, locking the MCP container out (2026-10-17). Start only once it is done.
    for _ in $(seq 600); do
      if ${pkgs.podman}/bin/podman exec --user 0:0 t3code \
          systemctl is-active --quiet t3code-container-setup.service; then
        break
      fi
      sleep 2
    done
    ${pkgs.podman}/bin/podman exec --user 0:0 t3code \
      systemctl is-active --quiet t3code-container-setup.service
    # Copy pinned inference and managed tools without replacing the active T3 runtime.
    ${pkgs.nix}/bin/nix copy --no-check-sigs \
      --to local?root=/srv/apps/t3code/nix-root ${scheduler} ${managedInstall} ${sourceSync} ${syncOverride} ${writeClient} ${isolateT3Models} ${maintenance} ${toolUpdate} ${toolUpdateOverride}
    install -d -m0755 /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge
    ln -sfn ${scheduler} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/scheduler
    ln -sfn ${managedInstall} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/managed-installer
    ln -sfn ${sourceSync} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/source-sync
    ln -sfn ${syncOverride} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/source-sync-override
    ln -sfn ${writeClient} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/client-writer
    ln -sfn ${isolateT3Models} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/model-scope
    ln -sfn ${maintenance} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/tool-maintenance
    ln -sfn ${toolUpdate} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/tool-update
    ln -sfn ${toolUpdateOverride} /srv/apps/t3code/nix-root/nix/var/nix/gcroots/ghostship-inference-bridge/tool-update-override
    install -d -m0700 -o3000 -g3000 ${hostHome}/.local/state/t3code-shared-agents
    ln -sfn ${managedInstall} ${hostHome}/.local/state/t3code-shared-agents/managed-installer
    # Override only the old image's scheduled installer, preserving its timer and repo sync.
    ${pkgs.podman}/bin/podman exec --user 0:0 t3code ${pkgs.coreutils}/bin/install \
      -D -m0644 ${syncOverride} \
      /run/systemd/system/t3code-ghostship-agent-sync.service.d/50-nixos-managed-installer.conf
    ${pkgs.podman}/bin/podman exec --user 0:0 t3code ${pkgs.coreutils}/bin/install \
      -D -m0644 ${toolUpdateOverride} \
      /run/systemd/system/t3code-tool-auto-update.service.d/50-nixos-free-worker.conf
    ${pkgs.podman}/bin/podman exec --user 0:0 t3code systemctl daemon-reload
    ${pkgs.podman}/bin/podman exec --user 3000:3000 --env HOME=${containerHome} \
      t3code ${maintenance}/bin/t3code-tool-maintenance --refresh-opencode-shim
    ${pkgs.podman}/bin/podman exec --user 3000:3000 --env HOME=${containerHome} \
      --env T3CODE_HOOK_SET=bootstrap.d t3code ${sourceSync}/bin/t3code-install-ghostship-agent
    install -d -m0750 -o3000 -g62020 ${hostHome}/${state} ${hostHome}/${state}/socket
    install -d -m0750 -o0 -g62020 /run/ghostship-integrations /run/ghostship-integrations/inference-socket
    install -m0600 -o3000 -g62020 ${token} ${hostHome}/${state}/token.new
    mv -fT ${hostHome}/${state}/token.new ${hostHome}/${state}/token
    install -m0400 -o62020 -g62020 ${token} /run/ghostship-integrations/inference-token.new
    mv -fT /run/ghostship-integrations/inference-token.new /run/ghostship-integrations/inference-token
    install -m0444 ${endpoint} /run/ghostship-integrations/inference-server.json.new
    mv -fT /run/ghostship-integrations/inference-server.json.new /run/ghostship-integrations/inference-server.json
    # CLI and MCP share the authenticated proxy without adding mounts to T3.
    ${pkgs.podman}/bin/podman exec -i --user 0:0 t3code ${writeClient} < ${token}
    ${pkgs.podman}/bin/podman exec --user 3000:3000 --env HOME=${containerHome} \
      t3code ${isolateT3Models}
  '';
in
{
  config = lib.mkIf cfg.enable {
    systemd.services.ghostship-inference-bridge = {
      description = "Authenticated free inference broker in the separate worker container";
      wantedBy = [ "multi-user.target" ];
      after = [ "podman-ghostship-worker.service" "podman-t3code.service" ];
      requires = [ "podman-ghostship-worker.service" ];
      path = [ pkgs.coreutils ];
      restartTriggers = [ config.age.secrets.inference-bridge-token.file inputs.ghostship-private-agent ];
      serviceConfig = {
        EnvironmentFile = [ "/etc/ghostship/owner-identity.env" ];
        ExecStartPre = publish;
        ExecStart = lib.escapeShellArgs ([
          "${pkgs.podman}/bin/podman" "exec" "--user" "63000:62020"
          "--env" "HOME=${workerHome}"
          "--env" "XDG_STATE_HOME=${workerHome}/.local/state"
          "--env" "GHOSTSHIP_FREE_INFERENCE_CONFIG=${workerHome}/.config/ghostship/free-inference.json"
          "--env" "GHOSTSHIP_FREE_INFERENCE_PROJECTION=${projection}"
          "ghostship-worker" "${broker}/bin/ghostship-free-inference-bridge"
          "--token-file" "/run/ghostship-worker/control/token"
          "--socket" workerSocket
          "--socket-gid" "62020"
        ]);
        Restart = "on-failure";
        RestartSec = 10;
        # container setup may take up to its own 20-minute start timeout
        TimeoutStartSec = 1500;
        TimeoutStopSec = 90;
        NoNewPrivileges = true;
        PrivateTmp = true;
        UMask = "0077";
      };
    };
    # The scheduler owns execution; broker restarts cannot terminate model work.
    systemd.services.ghostship-inference-scheduler = {
      description = "Durable free inference scheduler in the separate worker container";
      wantedBy = [ "multi-user.target" ];
      after = [ "podman-ghostship-worker.service" "ghostship-free-worker-auth.service" ];
      requires = [ "podman-ghostship-worker.service" "ghostship-free-worker-auth.service" ];
      serviceConfig = {
        ExecStart = lib.escapeShellArgs [
          "${pkgs.podman}/bin/podman" "exec" "--user" "63000:62020"
          "--env" "HOME=${workerHome}"
          "--env" "XDG_STATE_HOME=${workerHome}/.local/state"
          "--env" "GHOSTSHIP_FREE_INFERENCE_CONFIG=${workerHome}/.config/ghostship/free-inference.json"
          "--env" "GHOSTSHIP_FREE_INFERENCE_PROJECTION=${projection}"
          "ghostship-worker" "${scheduler}/bin/agent" "free-inference" "serve"
          "--workers" "2" "--max-jobs" "4" "--poll-seconds" "30"
        ];
        Restart = "on-failure";
        RestartSec = 10;
        TimeoutStopSec = 900;
        # Killing the host Podman attachment reports exit 1 even for an orderly
        # stop. Signal the container scheduler and await both processes instead;
        # genuine scheduler exit 1 must still fail and trigger monitoring.
        ExecStop = "${pkgs.python3}/bin/python ${./inference-scheduler-stop.py} ${pkgs.podman}/bin/podman $MAINPID ghostship-worker";
        NoNewPrivileges = true;
        PrivateTmp = true;
        UMask = "0077";
      };
    };
    # Keep the existing mounted socket directory stable. The worker itself
    # mounts only its own socket; it never receives the T3 home or auth store.
    systemd.sockets.ghostship-inference-proxy = {
      wantedBy = [ "sockets.target" ];
      after = [ "ghostship-inference-bridge.service" ];
      requires = [ "ghostship-inference-bridge.service" ];
      socketConfig = {
        ListenStream = "${hostHome}/${state}/socket/inference.sock";
        SocketMode = "0660";
        SocketUser = "3000";
        SocketGroup = "62020";
        RemoveOnStop = true;
      };
    };
    systemd.services.ghostship-inference-proxy = {
      after = [ "ghostship-inference-bridge.service" ];
      requires = [ "ghostship-inference-bridge.service" ];
      serviceConfig = {
        ExecStart = "${pkgs.systemd}/lib/systemd/systemd-socket-proxyd ${workerData}/socket/inference.sock";
        User = "62020";
        Group = "62020";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        RestrictAddressFamilies = [ "AF_UNIX" ];
      };
    };
    virtualisation.oci-containers.containers.ghostship-private-integrations.volumes = [
      "${hostHome}/${state}/socket:/run/ghostship-integrations/inference-socket:ro"
    ];
    systemd.services.podman-ghostship-private-integrations = {
      after = [ "ghostship-inference-bridge.service" ];
      requires = [ "ghostship-free-worker-auth.service" ];
    };
  };
}
