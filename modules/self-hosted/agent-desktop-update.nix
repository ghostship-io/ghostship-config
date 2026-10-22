{
  config,
  lib,
  pkgs,
  ...
}:

# Daily canary-tested update of the agent desktop image (Chrome stable,
# BladeBro, webtop base); see agent-desktop-update.py for the pipeline, its
# trust model and its gates. Promotion commits containers/agent-desktop/
# versions.json to ghostship-config main and deploys it with nixos-upgrade.
let
  googleFingerprint = "EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796";

  # Google's Linux package signing key, as published at
  # https://dl.google.com/linux/linux_signing_key.pub; its primary
  # fingerprint is the one https://www.google.com/linuxrepositories/ lists.
  googleKeyring =
    pkgs.runCommand "google-linux-signing-keyring.gpg" { nativeBuildInputs = [ pkgs.gnupg ]; }
      ''
        export GNUPGHOME=$(mktemp -d)
        primary=$(gpg --show-keys --with-colons ${./agent-desktop-update-google-key.asc} \
          | awk -F: '$1 == "fpr" { print $10; exit }')
        if [ "$primary" != ${googleFingerprint} ]; then
          echo "pinned Google key has primary fingerprint $primary, expected ${googleFingerprint}" >&2
          exit 1
        fi
        gpg --dearmor < ${./agent-desktop-update-google-key.asc} > $out
      '';

  production = config.virtualisation.oci-containers.containers.agent-desktop;

  settings = pkgs.writeText "agent-desktop-update.json" (
    builtins.toJSON {
      keyring = "${googleKeyring}";
      notify = "${config.ghostship.notify.package}/bin/ghostship-notify";
      github_env = config.ghostship.selfHostedSecrets.units.github.path;
      # Canaries run with production's environment and resource options;
      # each canary picks its own network.
      canary_environment = production.environment;
      canary_options = builtins.filter (
        option: !(lib.hasPrefix "--network" option) && !(lib.hasPrefix "--health-on-failure" option)
      ) production.extraOptions;
    }
  );

  updater = pkgs.writeShellApplication {
    name = "ghostship-agent-desktop-update";
    runtimeInputs = [
      pkgs.btrfs-progs
      pkgs.coreutils
      pkgs.git
      pkgs.gnupg
      # The host's configured podman: it can apply the AppArmor profiles canaries run under.
      config.virtualisation.podman.package
      pkgs.rsync
      pkgs.systemd
      config.nix.package
    ];
    text = ''
      exec ${pkgs.python3}/bin/python3 ${./agent-desktop-update.py} --config ${settings} "$@"
    '';
  };
in
{
  environment.systemPackages = [ updater ];

  systemd.services.ghostship-agent-desktop-update = {
    description = "Canary-tested agent desktop image update";
    after = [
      "network-online.target"
      "podman-agent-desktop.service"
    ];
    wants = [ "network-online.target" ];
    # The run itself switches the system through nixos-upgrade; a switch must
    # never stop or restart it midway through deploy, verify or rollback.
    restartIfChanged = false;
    stopIfChanged = false;
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${updater}/bin/ghostship-agent-desktop-update";
      StateDirectory = "ghostship/agent-desktop-update";
      StateDirectoryMode = "0700";
      UMask = "0077";
      # Build, two canaries, drain (30 min), upgrade and verification.
      TimeoutStartSec = "8h";
    };
  };

  systemd.timers.ghostship-agent-desktop-update = {
    description = "Daily agent desktop update check";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      # Away from the 04:00 nixos-upgrade window and its maintenance lock.
      OnCalendar = "*-*-* 13:00:00";
      RandomizedDelaySec = "30min";
      Persistent = true;
    };
  };
}
