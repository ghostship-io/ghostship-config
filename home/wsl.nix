{ config, lib, pkgs, ... }:

{
  programs.fish = {
    interactiveShellInit = ''
      # Initialize inshellisense
      test -f ~/.inshellisense/fish/init.fish && source ~/.inshellisense/fish/init.fish

      # Source SSH agent environment if it exists
      if test -f ~/.config/ssh-agent.env
        source ~/.config/ssh-agent.env
      end
    '';
    functions = {
      fish_title = {
        body = ''
          echo $argv[1]
        '';
      };
    };
    shellAliases = {
      open = "wsl-open";
    };
  };

  # SSH Agent with WSL-specific systemd service
  services.ssh-agent.enable = true;

  systemd.user.services.ssh-agent.Service = {
    ExecStart = lib.mkForce "${pkgs.openssh}/bin/ssh-agent -D -a /run/user/1000/ssh-agent -t 15m";
    ExecStartPre = "-${pkgs.coreutils}/bin/rm -f /run/user/1000/ssh-agent";
    ExecStartPost = let
      script = pkgs.writeShellScript "ssh-agent-post-start" ''
        ${pkgs.coreutils}/bin/mkdir -p $HOME/.config
        # Get socket from process arguments
        # We use $1 which is passed as $MAINPID
        ARGS=$(${pkgs.procps}/bin/ps -p $1 -o args=)
        SOCK=$(echo "$ARGS" | ${pkgs.gnugrep}/bin/grep -oP '(?<=-a\s)\S+')
        
        if [ -n "$SOCK" ]; then
          echo "set -gx SSH_AUTH_SOCK $SOCK;" > $HOME/.config/ssh-agent.env
          echo "set -gx SSH_AGENT_PID $1;" >> $HOME/.config/ssh-agent.env
        else
          echo "Could not find socket in ssh-agent arguments: $ARGS" >&2
          exit 1
        fi
      '';
    in "${script} $MAINPID";
  };
}
