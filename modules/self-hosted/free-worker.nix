{ config, inputs, lib, pkgs, ... }:
let
  enabled = config.ghostship.privateIntegrations.enable;
  tools = inputs.ghostship-private-agent.packages.${pkgs.stdenv.hostPlatform.system};
  home = "/home/worker";
  data = "/srv/apps/ghostship-worker";
  token = config.age.secrets.inference-bridge-token.path;
  arch = if pkgs.stdenv.hostPlatform.isAarch64 then "arm64" else "x64";
  hashes = {
    arm64 = {
      "2.1.2" = "sha512-294IA9S1sXOAzOBRPMcnFuYpXlFeUaKTlpTk0a7TMvuc7cJbfS52poTw3AlIu7ycbn8TGmTmj27OOxsMmBCLEg==";
    };
    x64 = {
      "2.1.2" = "sha512-O8/8JT8SNmMReDmpYDsm04KmkrQQ2dzaKgaw06zCoUfh50ARGHs58E6zCh16GIUyEL8abrdSe268K5/ExE89Gw==";
    };
  };
  native = version: pkgs.stdenvNoCC.mkDerivation {
    pname = "free-worker-opencode-native";
    inherit version;
    src = pkgs.fetchurl {
      url = "https://registry.npmjs.org/@opencode/cli-linux-${arch}/-/cli-linux-${arch}-${version}.tgz";
      hash = hashes.${arch}.${version};
    };
    dontFixup = true;
    installPhase = ''
      mkdir -p $out/bin
      cp bin/opencode $out/bin/opencode
      chmod 0555 $out/bin/opencode
    '';
  };
  current = native "2.1.2";
  runtimeLibs = lib.makeLibraryPath [ pkgs.glibc pkgs.stdenv.cc.cc.lib ];
  opencode = pkgs.writeShellScriptBin "opencode" ''
    unset OPENCODE_API_KEY OPENCODE_GO_API_KEY
    export OPENCODE_DISABLE_FREE_MODELS=0
    export OPENCODE_MODELS_PATH=/run/ghostship-worker/opencode-models.json
    export LD_LIBRARY_PATH=${runtimeLibs}
    exec ${current}/bin/opencode "$@"
  '';
  # Only declared free model IDs are enabled, even when Console offers paid models.
  catalog = builtins.fromJSON (builtins.readFile ./free-worker-models.json);
  freeModels = lib.attrNames (lib.filterAttrs (_: allowed: allowed) catalog);
  authPlan = pkgs.writeText "free-worker-auth-plan.json" (builtins.toJSON {
    free_model = "opencode/${builtins.head freeModels}";
    go_model = "opencode-go/minimax-m3.1-flash";
    probe_key = "free-worker-auth-${builtins.substring 0 16 (builtins.hashString "sha256"
      ((inputs.ghostship-private-agent.rev or "development")
        + builtins.readFile ./free-worker.nix + builtins.readFile ./free-worker-auth.py))}";
  });
  nativeCatalog = pkgs.writeText "free-worker-native-catalog.json"
    (builtins.readFile ./free-worker-native-catalog.json);
  sourcePool = builtins.fromJSON (builtins.readFile ./inference-pool.json);
  pool = sourcePool // {
    require_sandbox = true;
    max_workers = 2;
    repositories = [ ];
    test_commands = { };
    probe_schedule = false;
    admission_schedule = false;
    providers = sourcePool.providers // {
      opencode = sourcePool.providers.opencode // {
        enabled = true;
        data_policy_approved = true;
        models = freeModels;
        allowed_workloads = [ "development" "evaluation" "research" ];
      };
    };
  };
  poolConfig = pkgs.writeText "free-worker-pool.json" (builtins.toJSON pool);
  providerData = builtins.fromJSON (builtins.readFile
    "${inputs.ghostship-private-agent}/tools/python/ghostship_inference/data/providers.json");
  credentialNames = pkgs.writeText "free-worker-credential-names.json" (builtins.toJSON
    (lib.concatMap (entry: if entry.id != "opencode" && builtins.hasAttr entry.id pool.providers
      then entry.env_vars else [ ]) providerData.providers));
  # A directory bind preserves atomic credential-file replacement. The complete
  # T3 projection and both paid provider credentials stay outside the worker.
  projectCredentials = pkgs.writeShellScript "free-worker-project-credentials" ''
    set -eu
    exec ${pkgs.python3}/bin/python3 ${./free-worker-credentials.py} \
      --names ${credentialNames} --source /run/ghostship-secrets/t3code.env \
      --destination ${data}/secrets/credentials.env --uid 63000 --gid 62020
  '';
  prepare = pkgs.writeShellScript "free-worker-prepare" ''
    set -eu
    umask 077
    install -d -m0710 -o0 -g62020 ${data}
    install -d -m0700 -o63000 -g63000 ${data}/home ${data}/home/.config \
      ${data}/home/.config/ghostship ${data}/home/.config/opencode \
      ${data}/home/.cache ${data}/home/.local ${data}/home/.local/share ${data}/home/.local/state
    install -d -m0750 -o63000 -g62020 ${data}/socket ${data}/control ${data}/secrets
    install -m0400 -o63000 -g62020 ${token} ${data}/control/token.new
    mv -fT ${data}/control/token.new ${data}/control/token
    ${pkgs.python3}/bin/python3 ${./render-owner-config.py} ${poolConfig} ${data}/home/.config/ghostship/free-inference.json.new
    chown 63000:63000 ${data}/home/.config/ghostship/free-inference.json.new
    mv -fT ${data}/home/.config/ghostship/free-inference.json.new ${data}/home/.config/ghostship/free-inference.json
    ${projectCredentials}
  '';
  opencodeConfig = pkgs.writeText "free-worker-opencode.jsonc" (builtins.toJSON {
    "$schema" = "https://opencode.ai/config.json";
    enabled_providers = [ "opencode" ];
    providers.opencode.models = lib.mapAttrs (_: allowed: { disabled = !allowed; }) catalog;
    permission = { "*" = "deny"; };
    mcp = { };
  });
  image = pkgs.dockerTools.buildLayeredImageWithNixDb {
    name = "ghostship-worker";
    tag = "free-runtime";
    contents = [
      tools.agent tools.free-inference-bridge opencode
      pkgs.bash pkgs.coreutils pkgs.python3 pkgs.git pkgs.curl pkgs.jq pkgs.ripgrep pkgs.nodejs
      pkgs.bubblewrap pkgs.cacert pkgs.glibc pkgs.stdenv.cc.cc.lib
      pkgs.dockerTools.binSh pkgs.dockerTools.usrBinEnv
    ];
    extraCommands = ''
      mkdir -p etc home/worker lib lib64 usr/bin tmp
      chmod 1777 tmp
      for library in ${pkgs.glibc}/lib/*.so* ${pkgs.stdenv.cc.cc.lib}/lib/*.so*; do
        ln -sf "$library" "lib/$(basename "$library")"
      done
      ln -sf ${pkgs.stdenv.cc.bintools.dynamicLinker} lib/$(basename ${pkgs.stdenv.cc.bintools.dynamicLinker})
      ln -sf ${pkgs.stdenv.cc.bintools.dynamicLinker} lib64/$(basename ${pkgs.stdenv.cc.bintools.dynamicLinker})
      echo 'root:x:0:0:root:/root:/bin/sh' > etc/passwd
      echo 'worker:x:63000:63000:Free worker:/home/worker:/bin/sh' >> etc/passwd
      echo 'root:x:0:' > etc/group
      echo 'worker:x:63000:' >> etc/group
      echo 'inference:x:62020:worker' >> etc/group
    '';
    config = {
      User = "63000:62020";
      Env = [ "HOME=${home}" "PATH=/bin" "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "GHOSTSHIP_FREE_WORKER_RUNTIME=1"
        "GHOSTSHIP_FREE_INFERENCE_CONSOLE_AUTH=1"
        "GHOSTSHIP_FREE_INFERENCE_CONFIG=${home}/.config/ghostship/free-inference.json"
        "GHOSTSHIP_FREE_INFERENCE_PROJECTION=/run/ghostship-worker/secrets/credentials.env" ];
      Cmd = [ "${pkgs.coreutils}/bin/sleep" "infinity" ];
    };
  };
in
{
  config = lib.mkIf enabled {
    ghostship.apps.ghostship-worker = {
      name = "Free workers";
      group = "Services";
      description = "Sandboxed public background tasks";
      icon = "mdi-cube-outline";
      order = 103;
      apparmorProfile = "ghostship-free-worker";
    };
    assertions = [{
      assertion = config.virtualisation.oci-containers.backend == "podman";
      message = "The free-worker runtime requires Podman.";
    }];
    systemd.tmpfiles.rules = [
      "d ${data} 0710 root 62020 -"
      "d ${data}/home 0700 63000 63000 -"
      "d ${data}/home/.config 0700 63000 63000 -"
      "d ${data}/home/.config/opencode 0700 63000 63000 -"
      "d ${data}/home/.config/ghostship 0700 63000 63000 -"
      "d ${data}/home/.cache 0700 63000 63000 -"
      "d ${data}/home/.local 0700 63000 63000 -"
      "d ${data}/home/.local/share 0700 63000 63000 -"
      "d ${data}/home/.local/state 0700 63000 63000 -"
      "d ${data}/home/.local/share/t3code-tools/opencode/releases/2.1.2/lib/node_modules/@opencode/cli-linux-${arch}/bin 0755 63000 63000 -"
    ];
    security.apparmor.policies.ghostship-free-worker = {
      state = "complain";
      profile = ''
        #include <tunables/global>
        profile ghostship-free-worker flags=(attach_disconnected,mediate_deleted) {
          #include <abstractions/base>
          network inet stream,
          network inet6 stream,
          network inet dgram,
          network inet6 dgram,
          network unix,
          userns,
          capability sys_admin,
          capability sys_chroot,
          capability setuid,
          capability setgid,
          mount,
          umount,
          pivot_root,
          signal (send,receive) peer=ghostship-free-worker,
          /nix/store/** mr,
          /nix/store/*/bin/* ixr,
          /bin/* ixr,
          /lib/** mr,
          /lib64/** mr,
          /etc/{passwd,group,nsswitch.conf,resolv.conf,hosts,localtime} r,
          /etc/ssl/** r,
          /home/worker/** rwk,
          /home/worker/.local/share/t3code-tools/opencode/releases/2.1.2/** ixr,
          /tmp/** rwkm,
          /run/** rwk,
          /proc/** r,
          /dev/{null,zero,random,urandom} rw,
        }
      '';
    };
    virtualisation.oci-containers.containers.ghostship-worker = {
      image = "ghostship-worker:free-runtime";
      imageFile = image;
      pull = "never";
      ports = [ ];
      volumes = [
        "${data}/home:${home}:rw,nosuid,nodev"
        "${opencodeConfig}:${home}/.config/opencode/opencode.jsonc:ro"
        "${nativeCatalog}:/run/ghostship-worker/opencode-models.json:ro"
        "${data}/control:/run/ghostship-worker/control:ro"
        "${data}/socket:/run/ghostship-worker/socket:rw"
        "${data}/secrets:/run/ghostship-worker/secrets:ro"
        "${current}/bin/opencode:${home}/.local/share/t3code-tools/opencode/releases/2.1.2/lib/node_modules/@opencode/cli-linux-${arch}/bin/opencode:ro"
      ];
      extraOptions = [
        "--network=ghostship_net"
        "--cap-drop=ALL"
        "--security-opt=no-new-privileges"
        "--security-opt=seccomp=unconfined"
        "--pids-limit=256"
        "--memory=8g"
        "--cpus=2"
      ];
    };
    systemd.services.podman-ghostship-worker.after = [ "apparmor.service" ];
    systemd.services.podman-ghostship-worker.path = [ pkgs.coreutils ];
    systemd.services.podman-ghostship-worker.serviceConfig.ExecStartPre = [ prepare ];
    systemd.services.podman-ghostship-worker.serviceConfig.EnvironmentFile = [ "/etc/ghostship/owner-identity.env" ];
    systemd.services.ghostship-free-worker-auth = {
      description = "Separate the Go and Zen Console OAuth roles";
      wantedBy = [ "multi-user.target" ];
      after = [ "ghostship-inference-bridge.service" ];
      requires = [ "ghostship-inference-bridge.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${pkgs.python3}/bin/python3 ${./free-worker-auth.py} --podman ${pkgs.podman}/bin/podman --manifest ${data}/oauth-roles.json --plan ${authPlan}";
        TimeoutStartSec = 600;
        UMask = "0077";
      };
    };
    systemd.paths.ghostship-free-worker-credentials = {
      wantedBy = [ "multi-user.target" ];
      pathConfig.PathChanged = "/run/ghostship-secrets/t3code.env";
    };
    systemd.services.ghostship-free-worker-credentials = {
      description = "Project only free-provider credentials for the trusted worker parent";
      serviceConfig = { Type = "oneshot"; ExecStart = projectCredentials; UMask = "0077"; };
    };
  };
}
