{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.ghostship.t3Worker;
  user = cfg.user;
  home = config.users.users.${user}.home or "/home/${user}";

  # The shared catalog is owned by the ghostship-agent repository. Worker hosts
  # reuse that repository's own installer so skills, provider skill paths, and
  # compatibility copies stay identical to the T3 Code container.
  ghostshipAgentSync = pkgs.writeShellScriptBin "ghostship-agent-sync" ''
    set -eu

    source=${lib.escapeShellArg cfg.sharedAgentSource}
    repository=${lib.escapeShellArg cfg.sharedAgentRepo}
    branch=${lib.escapeShellArg cfg.sharedAgentRef}

    export HOME=${lib.escapeShellArg home}
    export PATH=${
      lib.makeBinPath [
        pkgs.git
        pkgs.python3
        pkgs.openssh
      ]
    }:$PATH

    if [ ! -d "$source/.git" ]; then
      mkdir -p "$(dirname "$source")"
      git clone --branch "$branch" "$repository" "$source"
    else
      git -C "$source" fetch --prune origin "$branch"
      git -C "$source" checkout --quiet "$branch"
      git -C "$source" merge --ff-only "origin/$branch"
    fi

    if [ ! -f "$source/tools/setup-container-agents.py" ]; then
      printf 'error: shared installer missing under %s; update ghostship-agent\n' "$source" >&2
      exit 1
    fi

    # Skills only: this host's Home Manager owns the provider AGENTS.md files,
    # so the installer must not write its own guidance. `--no-guidance` is owned
    # by ghostship-agent; detect it so a host reports the exact state instead of
    # failing opaquely when the checkout predates the flag.
    guidance_flag=""
    if python3 "$source/tools/setup-container-agents.py" --help 2>&1 \
      | grep -q -- '--no-guidance'; then
      guidance_flag="--no-guidance"
    else
      printf 'warning: shared catalog lacks --no-guidance; update ghostship-agent so skills can link without overwriting Home Manager guidance\n' >&2
      exit 1
    fi

    exec python3 "$source/tools/setup-container-agents.py" \
      --home "$HOME" \
      --source "$source" \
      --skills-only \
      $guidance_flag
  '';
in
{
  config = lib.mkIf cfg.enable {
    systemd.services.ghostship-agent-sync = {
      description = "Sync shared Ghostship skills for the T3 Code worker";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        Type = "oneshot";
        User = user;
        Group = user;
        ExecStart = "${ghostshipAgentSync}/bin/ghostship-agent-sync";
      };
    };

    systemd.timers.ghostship-agent-sync = {
      description = "Refresh shared Ghostship skills every 6 hours";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "3m";
        OnUnitActiveSec = "6h";
        Persistent = true;
        Unit = "ghostship-agent-sync.service";
      };
    };
  };
}
