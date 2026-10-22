{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.ghostship.newsletterHealth;
  repo = "/workspace/ghostship-newsletter";
  settings = pkgs.writeText "newsletter-health.json" (
    builtins.toJSON {
      state = "/var/lib/ghostship-newsletter-health/state.json";
      notify = "${config.ghostship.notify.package}/bin/ghostship-notify";
      # Keep execution unprivileged and use the newsletter's pinned environment.
      # This only reads outcomes; it cannot collect, prepare, repair or send mail.
      command = [
        "${pkgs.podman}/bin/podman"
        "exec"
        "--user"
        "3000:3000"
        "--env"
        "HOME=/home/t3code"
        "--env"
        "PATH=/home/t3code/.local/bin:/nix/var/nix/profiles/default/bin:/usr/bin:/bin"
        "--workdir"
        repo
        "t3code"
        # Bound the process inside the container as well as the host exec client.
        "/bin/timeout"
        "--signal=TERM"
        "--kill-after=10s"
        "150s"
        "${repo}/tools/bin/ghostship-am-agent-run"
        "run"
        "--nix"
        repo
        "--"
        "ghostship-am-monitor-status"
        "--runtime-only"
        "--json"
        "--fail-on-unhealthy"
      ];
    }
  );
in
{
  options.ghostship.newsletterHealth.enable = lib.mkEnableOption "host observation of newsletter delivery and daily runtime outcomes";
  config = lib.mkIf cfg.enable {
    systemd.services.ghostship-newsletter-health = {
      description = "Verify newsletter outcomes and escalate persistent failures";
      after = [ "podman-t3code.service" ];
      # Deliberately no Requires: a stopped container must produce an alert too.
      serviceConfig = {
        Type = "oneshot";
        StateDirectory = "ghostship-newsletter-health";
        StateDirectoryMode = "0700";
        UMask = "0077";
        ExecStart = "${pkgs.python3}/bin/python3 ${./newsletter-health.py} --config ${settings}";
        TimeoutStartSec = "5min";
      };
    };
    systemd.timers.ghostship-newsletter-health = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "10min";
        OnUnitInactiveSec = "10min";
        Unit = "ghostship-newsletter-health.service";
      };
    };
  };
}
