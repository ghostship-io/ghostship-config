{ lib, pkgs, ... }:
let
  root = "/srv/apps/chatgpt";
  tools = pkgs.buildEnv {
    name = "chatgpt-workstation-tools";
    paths = with pkgs; [
      git
      git-lfs
      gh
      openssh
      nix
      cloudflared
      curl
      jq
      ripgrep
      fd
      direnv
      uv
      python3
      nodejs_24
      stdenv.cc
      gnumake
      pkg-config
      cmake
      binutils
      coreutils
      findutils
      gnugrep
      gnused
      gnutar
      gzip
      unzip
      p7zip
      which
      file
      bashInteractive
      cacert
    ];
    pathsToLink = [
      "/bin"
      "/share"
    ];
    ignoreCollisions = true;
  };
  context = lib.cleanSourceWith {
    src = ../../containers/chatgpt;
    filter =
      path: type:
      !(builtins.elem (baseNameOf path) [
        "node_modules"
        ".cache"
        "artifacts"
      ]);
  };
  image = "localhost/ghostship-chatgpt:${
    builtins.substring 0 16 (builtins.hashString "sha256" (toString context))
  }";
in
{
  virtualisation.oci-containers.containers.chatgpt = {
    inherit image;
    pull = "never";
    extraOptions = [
      "--network=ghostship_net"
      "--network-alias=codex-web"
      "--network-alias=codex"
      "--privileged"
      "--shm-size=2g"
      "--pids-limit=-1"
      "--stop-timeout=120"
    ];
    environment = {
      PUID = "3000";
      PGID = "3000";
      CUSTOM_PORT = "8214";
      GHOSTSHIP_TOOLS = toString tools;
      TITLE = "ChatGPT";
    };
    volumes = [
      "${root}/home:/config:rw"
      "${root}/workspace:/workspace:rw"
      "${root}/docker:/var/lib/docker:rw"
      "${root}/updates:/var/lib/chatgpt-updates:rw"
      "${root}/nix-root/nix:/nix:rw"
      "/mnt/share:/mnt/share:rw"
    ];
  };
  systemd.services.podman-chatgpt = {
    after = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    wants = [ "mnt-share.mount" ];
    requires = [ "init-ghostship-net.service" ];
    serviceConfig = {
      TimeoutStartSec = lib.mkForce "30m";
      TimeoutStopSec = lib.mkForce "150s";
    };
    preStart = lib.mkBefore ''
      set -eu
      install -d -m0755 -o 3000 -g 3000 ${root}/home ${root}/workspace
      install -d -m0755 ${root}/docker ${root}/nix-root ${root}/updates
      ${pkgs.nix}/bin/nix copy --no-check-sigs --to 'local?root=${root}/nix-root' ${tools}
      install -d -m0755 ${root}/nix-root/nix/var/nix/gcroots
      ln -sfn ${tools} ${root}/nix-root/nix/var/nix/gcroots/chatgpt-workstation
      if ! ${pkgs.podman}/bin/podman image exists ${image}; then
        ${pkgs.podman}/bin/podman build --pull=never -t ${image} ${context}
      fi
    '';
  };
}
