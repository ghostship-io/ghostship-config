{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  t3codeHome = "/srv/apps/t3code/home";
  hardened = config.ghostship.t3code.hardening.enable;
  t3codeDeploymentState = "/var/lib/ghostship/t3code-deployment";
  t3codeTmp = "/srv/apps/t3code/tmp";
  t3codeNixRoot = "/srv/apps/t3code/nix-root";
  t3codeWorkspace = config.ghostship.agentHost.workspacePath;
  t3codeSecrets = config.ghostship.selfHostedSecrets.projections.t3code.path;
  t3codeDeploymentScripts = pkgs.runCommand "t3code-deployment-scripts" { } ''
    mkdir -p "$out"
    cp ${../../packages/t3code/candidate-acceptance.py} "$out/candidate-acceptance.py"
    cp ${../../packages/t3code/hardening-probe.py} "$out/hardening-probe.py"
    cp ${../../packages/t3code/provider-turn-probe.py} "$out/provider-turn-probe.py"
    cp ${../../packages/t3code/runtime-caps.json} "$out/runtime-caps.json"
  '';
  t3codeSecretsFile = "/run/secrets/t3code.env";
  # Private store-scoped retail settings (COSTCO_*, SAFEWAY_*, TARGET_*,
  # WALMART_*, HOMEDEPOT_*, BESTBUY_*). Root-owned and outside the repository;
  # the generated clients fail with a usage error when a required value is unset.
  retailStoreEnv = "/etc/ghostship/retail-store.env";
  approvedFreeWorkers = ./ai-usage/approved-free-workers.json;
  approvedFreeWorkerRoutes = builtins.fromJSON (builtins.readFile approvedFreeWorkers);
  ownerRoutePolicy = pkgs.writeText "ghostship-route-policy.json" (
    builtins.toJSON {
      schema = "ghostship.route-policy/v1";
      worker_capacity = {
        default = 8;
        p0_override = 12;
      };
      roles = {
        worker = {
          allow = [
            {
              provider = "codex";
              model = "gpt-6-luna";
              rule = "owner-approved Codex worker route";
            }
            {
              provider = "claudeAgent";
              model = "claude-sonnet-5-5";
              # The route-policy schema has no task-kind dimension. The model
              # picker continues to enforce that this route is for UI work only.
              rule = "owner: UI work only";
            }
            {
              provider = "opencode";
              model = "command-code/deepseek/deepseek-v4.1-flash";
              rule = "owner-approved default paid worker route";
            }
            {
              provider = "antigravity";
              model = "gemini-3.8-flash";
              rule = "owner-approved Antigravity worker route";
            }
            {
              provider = "antigravity";
              model = "gemini-3.8-flash-high";
              rule = "owner-approved Antigravity worker route";
            }
            {
              provider = "antigravity";
              model = "gemini-4-argon";
              rule = "owner-approved Antigravity worker route";
            }
          ]
          ++ map (entry: {
            provider = "opencode-free";
            model = "${entry.provider}/${entry.model}";
            rule = "listed in approved-free-workers.json";
          }) approvedFreeWorkerRoutes.entries;
          deny = [
            {
              provider = "claudeAgent";
              model = "claude-fable-5";
              rule = "Claude Fable denied by owner";
            }
            {
              provider = "claudeAgent";
              model = "claude-fable-5-1";
              rule = "Claude Fable denied by owner";
            }
          ];
          allow_rule = "not in the owner-approved worker routes";
        };
        orchestrator = {
          allow = [
            {
              provider = "claudeAgent";
              model = "claude-opus-5-5";
              rule = "owner: no Codex orchestrator handover trial";
            }
          ];
          deny = [
            {
              provider = "claudeAgent";
              model = "claude-fable-5";
              rule = "Claude Fable denied by owner";
            }
            {
              provider = "claudeAgent";
              model = "claude-fable-5-1";
              rule = "Claude Fable denied by owner";
            }
          ];
          allow_rule = "not in the owner-approved orchestrator routes";
        };
        reviewer.deny = [
          {
            provider = "claudeAgent";
            model = "claude-fable-5";
            rule = "Claude Fable denied by owner";
          }
          {
            provider = "claudeAgent";
            model = "claude-fable-5-1";
            rule = "Claude Fable denied by owner";
          }
        ];
      };
      authorizations = [ ];
    }
  );
  engineSlice = "user-${toString config.ghostship.t3codePodman.uid}.slice";
  imageName = "localhost/ghostship-t3code";
  acceptedImageRef = "${imageName}:accepted";
  tooling = inputs.ghostship-private-agent.packages.${pkgs.stdenv.hostPlatform.system}.t3code-tools;
  t3codeContainerHome = builtins.elemAt (lib.splitString "/.local/state/" managedBin) 0;
  t3codeToolMaintenance = tooling;
  t3codeToolAutoUpdate = tooling;
  t3codeProcessMemoryGuard = tooling;
  t3codeDaemonMonitor = tooling;
  managedBin = "/home/t3code/.local/state/ghostship-t3-tools/current/bin";
  runtimeImage = import ../../packages/t3code/image.nix { inherit pkgs; };
  t3codeImage = runtimeImage.image;
  t3codeImageArgs = runtimeImage.imageArgs;
  t3codeImageContents = runtimeImage.contents;
  t3codeAgentRevision = inputs.ghostship-private-agent.rev;
  t3codeDeploymentId = builtins.hashString "sha256" (builtins.toJSON {
    image = runtimeImage.deploymentId;
    agent = t3codeAgentRevision;
  });
  t3codeImmediateDeploy = pkgs.writeShellApplication {
    name = "ghostship-t3code-deploy-image";
    # The single-quoted jq programs intentionally avoid shell interpolation.
    excludeShellChecks = [ "SC2016" ];
    runtimeInputs = [ pkgs.coreutils pkgs.gnutar pkgs.inetutils pkgs.jq pkgs.podman pkgs.systemd pkgs.util-linux ];
    text = builtins.readFile ../../packages/t3code/deploy-image.sh;
  };
  t3codeActivateDeployment = pkgs.writeShellApplication {
    name = "ghostship-t3code-activate-deployment";
    runtimeInputs = [ pkgs.coreutils pkgs.util-linux ];
    text = builtins.readFile ../../packages/t3code/activate-deployment.sh;
  };
  t3codeReceiptSelfCheck = pkgs.writeShellApplication {
    name = "t3code-receipt-self-check";
    excludeShellChecks = [ "SC2016" ];
    runtimeInputs = [ pkgs.coreutils pkgs.jq pkgs.podman pkgs.systemd ];
    text = builtins.readFile ../../packages/t3code/receipt-self-check.sh;
  };

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
    # This stable alias is moved only by the deployment script, after it has
    # verified a PASS receipt for the exact image ID. In particular, systemd
    # must not load the current Nix image archive during a plain restart.
    image = acceptedImageRef;
    pull = "never";
    labels."io.containers.autoupdate" = "disabled";
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
      "/etc/ghostship/route-policy.json:/etc/ghostship/route-policy.json:ro"
      "/etc/ghostship/approved-free-workers.json:/etc/ghostship/approved-free-workers.json:ro"
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
    environment = {
      # The picker and the probe recorder must read one store: the T3 home's
      # model evidence, not a provider sandbox or another HOME (#403).
      GHOSTSHIP_MODEL_EVIDENCE_PATH = "/home/t3code/.local/state/ghostship/model-evidence/model-evidence.jsonl";
      GHOSTSHIP_ROUTE_POLICY_PATH = "/etc/ghostship/route-policy.json";
    };
    environmentFiles = [ t3codeSecrets retailStoreEnv ];
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

  environment.etc."ghostship/route-policy.json".source = ownerRoutePolicy;
  environment.etc."ghostship/approved-free-workers.json".source = approvedFreeWorkers;

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
    environment = {
      STATE_DIR = t3codeDeploymentState;
      PODMAN_BIN = "${pkgs.podman}/bin/podman";
      JQ_BIN = "${pkgs.jq}/bin/jq";
    };
    serviceConfig.TimeoutStopSec = lib.mkForce "210s";
    serviceConfig.ExecStartPost = "-${lib.getExe t3codeReceiptSelfCheck}";
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

  system.activationScripts.t3code-deployment = {
    text = ''
      STATE_DIR=${lib.escapeShellArg t3codeDeploymentState} \
        DEPLOYMENT_ID=${lib.escapeShellArg t3codeDeploymentId} \
        AGENT_REVISION=${lib.escapeShellArg t3codeAgentRevision} \
        PROVIDER_SECRETS_FILE=${lib.escapeShellArg t3codeSecrets} \
        SYSTEMCTL_BIN=${pkgs.systemd}/bin/systemctl \
        ${lib.getExe t3codeActivateDeployment}
    '';
    supportsDryActivation = false;
  };

  systemd.services.ghostship-t3code-deploy = {
    description = "Accept and deploy a changed T3 Code image immediately";
    after = [ "podman.service" ];
    environment = {
      STATE_DIR = t3codeDeploymentState;
      ACCEPTED_IMAGE_REF = acceptedImageRef;
      RECEIPT_SELF_CHECK = lib.getExe t3codeReceiptSelfCheck;
      IMAGE_ARCHIVE = toString t3codeImage;
      DEPLOYMENT_ID = t3codeDeploymentId;
      HOME_DIR = t3codeHome;
      CANDIDATE_ACCEPTANCE = "${t3codeDeploymentScripts}/candidate-acceptance.py";
      PODMAN_BIN = "${pkgs.podman}/bin/podman";
      SYSTEMCTL_BIN = "${pkgs.systemd}/bin/systemctl";
      CANDIDATE_SOCKET = "/run/t3code-podman-candidate/podman.sock";
      CANDIDATE_UID = toString (config.ghostship.t3codePodman.uid + 1);
      CANDIDATE_RUNTIME_DIR = "/var/lib/t3code-podman-candidate/acceptance";
      CANDIDATE_HOME_TARGET = t3codeContainerHome;
      PROVIDER_SECRETS_FILE = t3codeSecrets;
      TOOLING_PATH = toString tooling;
      AGENT_REVISION = t3codeAgentRevision;
      PYTHON_BIN = "${pkgs.python3}/bin/python3";
      JQ_BIN = "${pkgs.jq}/bin/jq";
      RESTART_LEDGER = "/var/lib/t3code-restarts/ledger.jsonl";
      AUDIT_LOG = "${t3codeHome}/.t3code-container/logs/restart-audit.log";
    };
    restartIfChanged = false;
    serviceConfig = {
      Type = "oneshot";
      ExecStart = lib.getExe t3codeImmediateDeploy;
      TimeoutStartSec = "25m";
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
