{ lib, pkgs, ... }:

{
  home.packages = [
    pkgs.wsl-open
    (pkgs.writeShellScriptBin "notify-send" "
      # WSL notify-send Bridge (Forward to Windows)
      # Hardcoded to use Windows Terminal icon for branding.

      APP_NAME=\"WSL\"
      SUMMARY=\"\"
      BODY=\"\"
      URGENCY=\"normal\"

      # Parse arguments
      while [[ \$# -gt 0 ]]; do
          case \"\$1\" in
              -a|--app-name) APP_NAME=\"\$2\"; shift 2 ;;
              --app-name=*) APP_NAME=\"\${1#*=}\"; shift ;;
              -u|--urgency) URGENCY=\"\$2\"; shift 2 ;;
              --urgency=*) URGENCY=\"\${1#*=}\"; shift ;;
              -t|--expire-time|--expire-time=*) shift 2 ;; # Ignore timeout
              -i|--icon|--icon=*) shift 2 ;; # Ignore icon
              -h|--help)
                  echo \"Usage: notify-send [OPTIONS] <SUMMARY> [BODY]\"
                  exit 0
                  ;;
              *)
                  if [[ \"\$1\" == -* ]]; then shift
                  elif [ -z \"\$SUMMARY\" ]; then SUMMARY=\"\$1\"; shift
                  elif [ -z \"\$BODY\" ]; then BODY=\"\$1\"; shift
                  else shift; fi
                  ;;
          esac
      done

      [ -z \"\$SUMMARY\" ] && exit 1

      SUMMARY_ESCAPED=\$(echo \"\$SUMMARY\" | sed \"s/'/''/g\")
      BODY_ESCAPED=\$(echo \"\$BODY\" | sed \"s/'/''/g\")
      APP_NAME_ESCAPED=\$(echo \"\$APP_NAME\" | sed \"s/'/''/g\")

      /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \"
          [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > \\\$null
          \\\$wtPackage = Get-AppxPackage -Name Microsoft.WindowsTerminal
          if (\\\$wtPackage) { \\\$iconPath = Join-Path \\\$wtPackage.InstallLocation 'Images\\\\Square44x44Logo.targetsize-256.png' }
          \\\$Template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastImageAndText02)
          \\\$RawXml = [xml]\\\$Template.GetXml()
          (\\\$RawXml.toast.visual.binding.text | Where-Object { \\\$_.id -eq '1' }).AppendChild(\\\$RawXml.CreateTextNode('\$SUMMARY_ESCAPED')) > \\\$null
          (\\\$RawXml.toast.visual.binding.text | Where-Object { \\\$_.id -eq '2' }).AppendChild(\\\$RawXml.CreateTextNode('\$BODY_ESCAPED')) > \\\$null
          if (\\\$iconPath -and (Test-Path \\\$iconPath)) {
              \\\$imageNode = (\\\$RawXml.toast.visual.binding.image | Where-Object { \\\$_.id -eq '1' })
              if (\\\$imageNode) { \\\$imageNode.SetAttribute('src', \\\$iconPath) }
          }

          if ('$URGENCY' -eq 'critical') {
              \\\$RawXml.toast.SetAttribute('scenario', 'reminder')
          }

          \\\$SerializedXml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]::New()
          \\\$SerializedXml.LoadXml(\\\$RawXml.OuterXml)

          \\\$Toast = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]::New(\\\$SerializedXml)
          \\\$Toast.Tag = '\$APP_NAME_ESCAPED'; \\\$Toast.Group = 'WSL'

          if ('$URGENCY' -eq 'critical') {
              \\\$Toast.Priority = [Windows.UI.Notifications.ToastNotificationPriority]::High
          }

          [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PowerShell').Show(\\\$Toast)
      \"
    ")
  ];

  programs.fish = {
    interactiveShellInit = lib.mkAfter ''
      if test -f ~/.config/ssh-agent.env
        source ~/.config/ssh-agent.env
      end
    '';
    shellAliases = {
      open = "wsl-open";
    };
    functions = {
      fish_title = {
        body = ''
          echo $argv[1]
        '';
      };
    };
  };

  services.ssh-agent.enable = true;

  systemd.user.services.ssh-agent.Service = {
    ExecStart = lib.mkForce "${pkgs.openssh}/bin/ssh-agent -D -a /run/user/1000/ssh-agent -t 8h";
    ExecStartPre = "-${pkgs.coreutils}/bin/rm -f /run/user/1000/ssh-agent";
    ExecStartPost = let
      script = pkgs.writeShellScript "ssh-agent-post-start" ''
        ${pkgs.coreutils}/bin/mkdir -p $HOME/.config
        ARGS=$(${pkgs.procps}/bin/ps -p $1 -o args=)
        SOCK=$(echo "$ARGS" | ${pkgs.gnugrep}/bin/grep -oP '(?<=-a\\s)\\S+')

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

  home.activation.wslHomeSymlink = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    WSL_USER="nixos"
    USER_HOME="/home/$WSL_USER"

    if [ -d "$USER_HOME" ]; then
      WIN_USER=$(/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -Command '$env:UserName' 2>/dev/null | tr -d '\r')

      if [ -n "$WIN_USER" ]; then
        WIN_HOME="/mnt/c/Users/$WIN_USER"

        if [ -d "$WIN_HOME" ]; then
          echo "Creating symlink $USER_HOME/win-home -> $WIN_HOME"
          ln -sf "$WIN_HOME" "$USER_HOME/win-home"
          chown -h $WSL_USER:nixos "$USER_HOME/win-home"
        fi
      fi
    fi
  '';
}
