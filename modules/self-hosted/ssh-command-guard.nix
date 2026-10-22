# The agent SSH key runs a forced command that refuses the recursive host
# searches the host policy forbids (see ssh-command-guard.py). The owner's own
# keys are authorized without a forced command and are not affected.
{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.sshCommandGuard;
  guard = pkgs.writeShellApplication {
    name = "ghostship-ssh-command-guard";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      exec ${pkgs.python3}/bin/python3 ${./ssh-command-guard.py} \
        --journal ${lib.getExe' pkgs.systemd "systemd-cat"} "$@"
    '';
  };
  # A guarded entry authorizes the key only through the wrapper.
  guarded = map (key: "command=\"${guard}/bin/ghostship-ssh-command-guard\" ${key}") cfg.keys;
  # The key material of a guarded key, so it can be found in any other entry.
  material = key:
    let fields = lib.splitString " " (lib.removePrefix "command=" key);
    in lib.findFirst (field: lib.hasPrefix "AAAA" field) "" fields;
  materials = map material cfg.keys;
  unguarded = lib.filter (entry: !(lib.hasPrefix "command=" entry))
    config.users.users.root.openssh.authorizedKeys.keys;
in
{
  options.ghostship.sshCommandGuard = {
    enable = lib.mkEnableOption "Run the agent SSH key through the host command guard";
    keys = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = ''
        Public keys of the agent accounts that run the guard's forced command.
        Each entry is an authorized_keys line without options. The owner's own
        keys are authorized without a forced command and are not listed here.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ guard ];
    users.users.root.openssh.authorizedKeys.keys = guarded;

    # sshd reads every file in AuthorizedKeysFile, and the first one that holds
    # the key decides its options. A copy of the agent key in a file outside the
    # managed one would authorize it without the guard, so the copy is removed.
    system.activationScripts.ghostship-ssh-command-guard = {
      deps = [ "users" ];
      text = ''
        ${pkgs.python3}/bin/python3 ${./ssh-command-guard.py} prune \
          --file /root/.ssh/authorized_keys \
          ${lib.concatMapStrings (blob: "--material ${blob}") materials}
      '';
    };

    assertions = [
      {
        assertion = lib.all
          (key: lib.all (entry: !(lib.strings.hasInfix (material key) entry)) unguarded)
          cfg.keys;
        message = ''
          The agent key must only be authorized through the command guard.
          Remove the unguarded copy of this key from root's authorized keys.
        '';
      }
      {
        # A forced command replaces the internal sftp subsystem, so the guard
        # needs the external server that the host's sshd_config names.
        assertion = config.services.openssh.sftpServerExecutable != "internal-sftp";
        message = ''
          The SSH command guard needs an external sftp server, because a forced
          command replaces the internal sftp subsystem. Set
          services.openssh.sftpServerExecutable to the external server.
        '';
      }
    ];
  };
}
