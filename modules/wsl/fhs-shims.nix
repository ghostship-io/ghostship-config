{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.wsl;

  renderShim = entry:
    let
      target = lib.escapeShellArg entry.target;
      source = lib.escapeShellArg entry.source;
      mode = lib.escapeShellArg entry.mode;
    in
    ''
      ${pkgs.coreutils}/bin/mkdir -p "$(${pkgs.coreutils}/bin/dirname -- ${target})"
      ${if entry.copy then
        "${pkgs.coreutils}/bin/install -D -m ${mode} ${source} ${target}"
      else
        "${pkgs.coreutils}/bin/ln -sfnT ${source} ${target}"
      }
    '';
in
{
  options.ghostship.wsl.fhsShims = lib.mkOption {
    type = lib.types.listOf (lib.types.submodule {
      options = {
        target = lib.mkOption {
          type = lib.types.str;
          description = "Absolute FHS path to create.";
        };
        source = lib.mkOption {
          type = lib.types.str;
          description = "Path the FHS shim should point at or copy from.";
        };
        copy = lib.mkOption {
          type = lib.types.bool;
          default = false;
          description = "Copy the source instead of creating a symlink.";
        };
        mode = lib.mkOption {
          type = lib.types.str;
          default = "0555";
          description = "Mode used when copying the source.";
        };
      };
    });
    default = [ ];
    description = ''
      Explicit /bin and /usr/bin compatibility shims for WSL integrations that
      call hardcoded FHS paths.
    '';
  };

  config = lib.mkIf (config.wsl.enable or false) {
    services.envfs.enable = lib.mkForce false;
    wsl.populateBin = lib.mkForce true;

    system.activationScripts.binsh = lib.mkForce "";
    system.activationScripts.usrbinenv = lib.mkForce "";
    system.activationScripts.populateBin = lib.mkForce (lib.stringAfter [ ] ''
      echo "setting up WSL FHS shims..."

      skip_fhs_shims=false
      for target in /bin /usr/bin; do
        if ${pkgs.util-linux}/bin/findmnt --mountpoint "$target" --noheadings --output SOURCE,FSTYPE 2>/dev/null \
          | ${pkgs.gnugrep}/bin/grep -qx 'envfs fuse'; then
          echo "$target is still mounted by envfs; restart WSL after this switch to let explicit FHS shims take over"
          skip_fhs_shims=true
        fi
      done

      if [ "$skip_fhs_shims" != true ]; then
        ${lib.concatStringsSep "\n" (map renderShim cfg.fhsShims)}
      fi
    '');
  };
}
