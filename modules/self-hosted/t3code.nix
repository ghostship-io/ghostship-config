{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  t3codeActivityProbe = pkgs.callPackage "${inputs.ghostship-private-agent}/packages/t3code/activity-probe/default.nix" {};
  t3codeHome = "/srv/apps/t3code/home";
  hardened = config.ghostship.t3code.hardening.enable;
  t3codeDeploymentState = "/var/lib/ghostship/t3code-deployment";
  t3codeTmp = "/srv/apps/t3code/tmp";
  t3codeNixRoot = "/srv/apps/t3code/nix-root";
  t3codeWorkspace = config.ghostship.agentHost.workspacePath;
  t3codeSecrets = config.ghostship.selfHostedSecrets.projections.t3code.path;
  t3codeSecretsFile = "/run/secrets/t3code.env";
  engineSlice = "user-${toString config.ghostship.t3codePodman.uid}.slice";
  imageName = "localhost/ghostship-t3code";
  imageTag = "t3code-runtime";
  tooling = inputs.ghostship-private-agent.packages.${pkgs.stdenv.hostPlatform.system}.t3code-tools;
  t3codeToolMaintenance = tooling;
  t3codeToolAutoUpdate = tooling;
  t3codeProcessMemoryGuard = tooling;
  t3codeDaemonMonitor = tooling;
  managedBin = "/home/t3code/.local/state/ghostship-t3-tools/current/bin";
  runtimeImage = import ../../packages/t3code/image.nix { inherit pkgs; };
  t3codeImage = runtimeImage.image;
  t3codeImageArgs = runtimeImage.imageArgs;
  t3codeImageContents = runtimeImage.contents;
  t3codeDeploymentId = runtimeImage.deploymentId;
  t3codeDeployWhenIdleScript = pkgs.writeShellScriptBin "t3code-deploy-when-idle" ''
    set -eu
    exec ${pkgs.python3}/bin/python3 ${../../packages/t3code/deploy-when-idle.py} \
      --state-dir "${t3codeDeploymentState}" \
      --image-archive "${t3codeImage}" \
      --home-dir "${t3codeHome}" \
      --probe-bin "${t3codeActivityProbe}/bin/t3code-activity-probe" \
      --podman-bin "${pkgs.podman}/bin/podman" \
      --systemctl-bin "${pkgs.systemd}/bin/systemctl" \
      --audit-log "${t3codeHome}/.t3code-container/logs/restart-audit.log" \
      --restart-ledger "/var/lib/t3code-restarts/ledger.jsonl" \
      --journal-bin "${pkgs.systemd}/bin/systemd-cat" \
      "$@"
  '';

  t3codeSafeRestart = pkgs.writeShellScriptBin "t3code-safe-restart" ''
    set -eu
    exec ${t3codeDeployWhenIdleScript}/bin/t3code-deploy-when-idle --safe-restart "$@"
  '';

  # The container owns a persistent, isolated Nix store at ${t3codeNixRoot}/nix.
  # podman-t3code seeds it from the image closure on every deployment (nix copy)
  # and agent sessions build into it, but nothing ever garbage-collects it, so
  # dead paths and build results accumulate without bound. Nix GC honors GC
  # roots and active temporary roots, so it cannot delete a path a running
  # session still needs, and it never restarts the container. Serialize against
  # backups and image maintenance through the shared lock.
  t3codeNixStoreGc = pkgs.writeShellApplication {
    name = "t3code-nix-store-gc";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.util-linux
      pkgs.podman
    ];
    text = ''
      if test -z "$(podman ps --quiet --filter 'name=^t3code$')"; then
        echo "t3code container is not running; skipping isolated Nix store GC" >&2
        exit 0
      fi
      flock -w 300 /run/ghostship-maintenance.lock \
        podman exec t3code nix store gc
    '';
  };

in
{
  imports = [ ./t3code-recovery.nix ];

  # Permit memory-policy deployment without replacing the active T3 container.
  assertions = map (name: {
    assertion = false;
    message = "T3 dependency ${name} must disable switch restart and stop.";
  }) (import ../../packages/t3code/switch-guard.nix {
    services = config.systemd.services;
    seeds = [ "podman-t3code" "t3code-podman" "t3code-podman-ports"
      "user-runtime-dir@${toString config.ghostship.t3codePodman.uid}" ];
  });
  system.build.t3codeProcessMemoryGuard = t3codeProcessMemoryGuard;
  system.build.t3codeServerMonitor = t3codeDaemonMonitor;
  system.build.t3codeToolMaintenance = t3codeToolMaintenance;
  system.build.t3codeToolAutoUpdate = t3codeToolAutoUpdate;
  system.build.t3codeRuntimeClosure = pkgs.linkFarm "t3code-runtime-closure" (
    lib.imap0 (i: path: {
      name = toString i;
      inherit path;
    }) t3codeImageContents
  );
  # Candidate loading must never retag the production image beneath its updater.
  system.build.t3codeCandidateImage = lib.mkIf hardened (
    pkgs.dockerTools.buildLayeredImageWithNixDb (
      t3codeImageArgs
      // {
        name = "${imageName}-candidate";
        tag = "hardening";
      }
    )
  );

  # The Antigravity ACP archive is unfree; keep the exception scoped to this app.
  nixpkgs.config.allowUnfreePredicate =
    pkg:
    builtins.elem (lib.getName pkg) [
      "antigravity-acp"
    ];

  ghostship.agentHost.enable = true;
  ghostship.apps.t3code = {
    name = "T3 Code";
    group = "Services";
    description = "Codex, OpenCode, and Antigravity workspace";
    icon = "mdi-code-braces-#7c3aed";
    order = 102;
    hostname = "t3code.ghostship.io";
    origin = "http://t3code:3773";
    healthPath = "/";
    muximux = {
      icon = "muximux-code";
      color = "#7c3aed";
      dropdown = false;
    };
  };

  virtualisation.oci-containers.containers."t3code" = {
    image = "${imageName}:${imageTag}";
    imageFile = t3codeImage;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "disabled";
      "io.ghostship.t3code.deployment" = t3codeDeploymentId;
    };
    ports = [ ];
    extraOptions =
      (
        if hardened then
          [
            "--cap-drop=ALL"
            "--security-opt=unmask=/proc/*"
          ]
          ++ map (cap: "--cap-add=${cap}") (
            builtins.fromJSON (builtins.readFile ../../packages/t3code/runtime-caps.json)
          )
        else
          [ "--privileged" ]
      )
      ++ [
        "--systemd=always"
        "--stop-timeout=180"
        # Public HTTPS must resolve through Cloudflare, not this HTTP-only origin.
        "--hostname=t3code"
        "--network=ghostship_net"
        "--network=agent_desktop_net"
        "--health-cmd=${managedBin}/t3code-container-health"
        "--health-interval=30s"
        "--health-timeout=15s"
        "--health-retries=5"
        "--health-start-period=5m"
      ]
      ++ (
        if hardened then
          [
            "--pids-limit=${toString config.ghostship.t3code.hardening.containerPidsLimit}"
            # The container joins the engine's user slice so the aggregate
            # limits cover the container itself, not only conmon.
            "--cgroup-parent=${engineSlice}"
          ]
        else
          [ "--pids-limit=-1" ]
      );
    volumes = [
      # Podman's systemd mode otherwise mounts /tmp as tmpfs. Temporary
      # checkouts must not consume the shared server/provider memory budget.
      "${t3codeTmp}:/tmp:rw"
      "${t3codeWorkspace}:/workspace:rw"
      "${t3codeHome}:/home/t3code:rw"
      "${t3codeNixRoot}/nix:/nix:rw"
      "${t3codeSecrets}:${t3codeSecretsFile}:ro"
      "/run/t3code-podman/podman.sock:/var/run/podman/podman.sock:rw"
      "/run/t3code-podman/ports.sock:/var/run/t3code-podman-ports.sock:rw"
    ]
    ++ (
      if hardened then
        lib.mapAttrsToList (
          path: readOnly:
          "${config.ghostship.agentHost.sharedPath}/${path}:/mnt/share/${path}:${
            if readOnly then "ro" else "rw"
          },nosuid,nodev"
        ) config.ghostship.t3code.hardening.sharedMounts
      else
        [
          "${config.ghostship.agentHost.sharedPath}:/mnt/share:rw"
        ]
    );
    environmentFiles = [ t3codeSecrets ];
  };

  ghostship.t3codePodman.enable = true;

  systemd.tmpfiles.rules = [
    "d /srv/apps/t3code 0755 root root -"
    "d /var/lib/t3code-restarts 0700 root root -"
    "d ${t3codeDeploymentState} 0755 root root -"
    "d ${t3codeTmp} 1777 root root -"
    "d ${t3codeHome} 0755 3000 3000 -"
    "d ${t3codeNixRoot} 0755 root root -"
    "d ${t3codeNixRoot}/nix 0755 root root -"
    "d ${t3codeWorkspace} 0755 3000 3000 -"
  ];

  systemd.services.podman-t3code = {
    restartIfChanged = false;
    stopIfChanged = false;
    requires = [
      "t3code-podman.socket"
      "t3code-podman-ports.socket"
    ];
    after = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ]
    ++ [
      "t3code-podman.socket"
      "t3code-podman-ports.socket"
    ];
    wants = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    serviceConfig.TimeoutStopSec = lib.mkForce "210s";
    preStart = lib.mkAfter ''
      set -eu

      install -d -m0755 -o root -g root /srv/apps/t3code
      install -d -m1777 -o root -g root ${t3codeTmp}
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}
      install -d -m0755 -o root -g root ${t3codeNixRoot}
      install -d -m0755 -o 3000 -g 3000 ${t3codeWorkspace}

      ${pkgs.nix}/bin/nix copy --no-check-sigs \
        --to 'local?root=${t3codeNixRoot}' ${tooling} ${config.ghostship.t3codePodman.bridgePackage}
      # Home is container-writable: seed its links with the home owner's UID.
      ${pkgs.su-exec}/bin/su-exec 3000:3000 ${pkgs.bash}/bin/bash -euc ${lib.escapeShellArg ''
        tool_state=${t3codeHome}/.local/state/ghostship-t3-tools
        mkdir -p "$tool_state"
        if [ ! -e "$tool_state/current" ] && [ ! -L "$tool_state/current" ]; then
          ln -s ${tooling} "$tool_state/current"
        fi
        ln -sfn ${config.ghostship.t3codePodman.bridgePackage} ${t3codeHome}/.local/state/t3code-podman-bridge
      ''}
      install -d -m0755 ${t3codeNixRoot}/nix/var/nix/gcroots/ghostship-t3-tools
      ln -sfn ${tooling} ${t3codeNixRoot}/nix/var/nix/gcroots/ghostship-t3-tools/pinned
      ln -sfn ${config.ghostship.t3codePodman.bridgePackage} ${t3codeNixRoot}/nix/var/nix/gcroots/ghostship-t3-tools/bridge

      nix_store_uri='local?root=${t3codeNixRoot}'
      ${pkgs.nix}/bin/nix copy \
        --no-check-sigs \
        --to "$nix_store_uri" \
        ${lib.escapeShellArgs (map toString t3codeImageContents)}

      gcroot_dir=${t3codeNixRoot}/nix/var/nix/gcroots/ghostship-t3code-image
      rm -rf "$gcroot_dir"
      install -d -m0755 -o root -g root "$gcroot_dir"
      for store_path in ${lib.escapeShellArgs (map toString t3codeImageContents)}; do
        ln -s "$store_path" "$gcroot_dir/$(basename "$store_path")"
      done

      rm -f ${t3codeNixRoot}/nix/var/nix/temproots/*
      rm -rf ${t3codeNixRoot}/nix/var/nix/builds/*
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.local/bin
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.local/share
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.local/state
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.cache
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.config/opencode
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.codex
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.gemini/antigravity-cli
      install -d -m0700 -o 3000 -g 3000 ${t3codeHome}/.local/share/keyrings
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.automation
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.config/systemd/user
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3/userdata
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3/caches
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/logs/tunnels
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/recovery
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/tunnels
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/hooks/bootstrap.d
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/hooks/before-t3code.d
      install -d -m0755 -o 3000 -g 3000 ${t3codeHome}/.t3code-container/hooks/doctor.d

    '';
  };

  environment.systemPackages = [
    t3codeDeployWhenIdleScript
    t3codeSafeRestart
  ];

  system.activationScripts.t3code-deployment = {
    text = ''
      install -d -m 0755 ${t3codeDeploymentState}
      printf '%s\n' ${lib.escapeShellArg t3codeDeploymentId} \
        > ${t3codeDeploymentState}/desired.tmp
      mv ${t3codeDeploymentState}/desired.tmp ${t3codeDeploymentState}/desired
      ${pkgs.systemd}/bin/systemctl start --no-block t3code-deploy-when-idle.service || true
    '';
    supportsDryActivation = false;
  };

  systemd.services.t3code-deploy-when-idle = {
    description = "Deploy a changed T3 Code image after sustained idle";
    after = [ "podman.service" ];
    # Let an in-flight deploy finish during a host switch; the timer runs the
    # new script on its next tick.
    restartIfChanged = false;
    # Its central failure path (notify-coverage.nix) fires only on a failed
    # start attempt, which is bounded per image.
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${t3codeDeployWhenIdleScript}/bin/t3code-deploy-when-idle";
      TimeoutStartSec = "25m";
    };
  };

  systemd.timers.t3code-deploy-when-idle = {
    description = "Check for a queued T3 Code image deployment";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "2m";
      OnUnitActiveSec = "1m";
      Persistent = true;
      Unit = "t3code-deploy-when-idle.service";
    };
  };

  # Reclaim the container's unbounded isolated Nix store. nix store gc deletes
  # only paths unreachable from GC roots, so live profiles, active sessions, and
  # in-flight builds are preserved; it never restarts the container. Idle I/O
  # keeps it out of the way of transcodes and other host work.
  systemd.services.t3code-nix-store-gc = {
    description = "Garbage-collect the T3 Code container's isolated Nix store";
    after = [ "podman-t3code.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = lib.getExe t3codeNixStoreGc;
      TimeoutStartSec = "2h";
      Nice = 10;
      IOSchedulingClass = "idle";
    };
  };

  systemd.timers.t3code-nix-store-gc = {
    description = "Daily garbage collection of the T3 Code container Nix store";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "daily";
      Persistent = true;
      RandomizedDelaySec = "1h";
    };
  };

}
