{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:

let
  upstreamNativeUtils = pkgs.callPackage "${inputs.nixos-wsl}/utils" { };
  codexCompatibleNativeUtils = pkgs.runCommand "nixos-wsl-utils-codex-compatible" { } ''
    mkdir -p "$out/bin"
    ln -s ${upstreamNativeUtils}/bin/split-path "$out/bin/split-path"
    ln -s ${upstreamNativeUtils}/bin/systemd-shim "$out/bin/systemd-shim"

    cat > "$out/bin/shell-wrapper" <<'EOF'
    #!${pkgs.bashInteractive}/bin/bash

    set -eo pipefail

    wrapper_path="''${BASH_SOURCE[0]}"
    wrapper_dir="$(${pkgs.coreutils}/bin/dirname -- "$wrapper_path")"
    wrapped_shell="$wrapper_dir/shell"
    shell_name="$(${pkgs.coreutils}/bin/readlink -- "$wrapped_shell" 2>/dev/null || printf '%s\n' "$wrapped_shell")"

    while [ ! -e /run/current-system/sw/bin ]; do
      ${pkgs.coreutils}/bin/sleep 0.05
    done

    if [ -z "''${__NIXOS_SET_ENVIRONMENT_DONE:-}" ] && [ -r /etc/set-environment ]; then
      # shellcheck disable=SC1091
      . /etc/set-environment
    fi

    export SHELL="$shell_name"

    import_fish_environment() {
      local entry name value
      while IFS= read -r -d "" entry; do
        name="''${entry%%=*}"
        value="''${entry#*=}"
        if [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
          printf -v "$name" '%s' "$value" 2>/dev/null && export "$name" 2>/dev/null || true
        fi
      done < <("$wrapped_shell" -c 'env -0' 2>/dev/null || true)
      export SHELL="$shell_name"
    }

    if [ "$#" -ge 2 ] \
      && [ "$1" = "-c" ] \
      && [[ "$2" == /usr/bin/bash\ -lc* || "$2" == /bin/bash\ -lc* ]]; then
      import_fish_environment
      exec ${pkgs.bashInteractive}/bin/bash -lc "$2"
    fi

    exec "$wrapped_shell" "$@"
    EOF

    chmod 0555 "$out/bin/shell-wrapper"
  '';
  nixos-enter = pkgs.nixos-enter or config.system.build.nixos-enter;
  nixos-enter' = nixos-enter.overrideAttrs (_: {
    runtimeShell = "/bin/bash";
  });

  nixosWslRecovery = pkgs.writeScriptBin "nixos-wsl-recovery" ''
    #! /bin/sh
    if [ -f /etc/NIXOS ]; then
      echo "nixos-wsl-recovery should only be run from the WSL system distribution."
      echo "Example:"
      echo "    wsl --system --distribution NixOS --user root -- /nix/var/nix/profiles/system/bin/nixos-wsl-recovery"
      exit 1
    fi
    mount -o remount,rw /mnt/wslg/distro
    exec /mnt/wslg/distro/${nixos-enter'}/bin/nixos-enter --root /mnt/wslg/distro "$@"
  '';
in
{
  # WSL develop hosts run multiple flake-aware shells and agent sessions at
  # once. Letting the daemon use every reported core makes it easy to saturate
  # memory and leave new clients waiting on a busy daemon.
  nix.settings.max-jobs = lib.mkForce 8;
  nix.settings.cores = lib.mkDefault 4;

  # Codex Desktop currently sends Bash-quoted worktree probes through the WSL
  # user's fish login shell. Keep fish as the default shell, but let those
  # nested Bash commands reach Bash after the normal NixOS and fish env setup.
  system.build.nativeUtils = lib.mkForce codexCompatibleNativeUtils;

  services.resolved.enable = false;
  networking.useNetworkd = false;
  systemd.network.enable = false;

  wsl = {
    enable = true;
    interop.register = true;
    wslConf = {
      automount.enabled = true;
      interop.enabled = true;
      interop.appendWindowsPath = true;
    };
    docker-desktop.enable = true;
    extraBin = [
      { src = "${pkgs.coreutils}/bin/whoami"; }
    ];
  };

  ghostship.wsl.fhsShims = [
    {
      target = "/bin/sh";
      source = config.wsl.binShExe;
    }
    {
      target = "/bin/bash";
      source = "${pkgs.bashInteractive}/bin/bash";
    }
    {
      target = "/bin/mount";
      source = "${pkgs.util-linux}/bin/mount";
    }
    {
      target = "/bin/wslpath";
      source = "/init";
    }
    {
      target = "/bin/login";
      source = "${pkgs.shadow}/bin/login";
    }
    {
      target = "/bin/cat";
      source = "${pkgs.coreutils}/bin/cat";
    }
    {
      target = "/bin/whoami";
      source = "${pkgs.coreutils}/bin/whoami";
    }
    {
      target = "/bin/groupadd";
      source = "${pkgs.shadow}/bin/groupadd";
    }
    {
      target = "/bin/usermod";
      source = "${pkgs.shadow}/bin/usermod";
    }
    {
      target = "/bin/nixos-wsl-recovery";
      source = "${nixosWslRecovery}/bin/nixos-wsl-recovery";
      copy = true;
    }
    {
      target = "/usr/bin/env";
      source = "${pkgs.coreutils}/bin/env";
    }
    {
      target = "/usr/bin/bash";
      source = "${pkgs.bashInteractive}/bin/bash";
    }
    {
      target = "/usr/bin/sh";
      source = config.wsl.binShExe;
    }
    {
      target = "/usr/bin/bwrap";
      source = "${pkgs.bubblewrap}/bin/bwrap";
    }
    {
      target = "/usr/bin/node";
      source = "${pkgs.nodejs}/bin/node";
    }
    {
      target = "/usr/bin/npm";
      source = "${pkgs.nodejs}/bin/npm";
    }
    {
      target = "/usr/bin/npx";
      source = "${pkgs.nodejs}/bin/npx";
    }
    {
      target = "/usr/bin/gh";
      source = "${pkgs.gh}/bin/gh";
    }
    {
      target = "/usr/bin/starship";
      source = "${pkgs.starship}/bin/starship";
    }
  ];

  environment.variables.WSLENV = "USERPROFILE/p";
}
