{ lib, pkgs, ... }:

let
  windowsPowerShell = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe";
  wslOpenWrapped = pkgs.writeShellScriptBin "wsl-open" ''
    export PowershellExe="${windowsPowerShell}"
    export WslOpenExe="${windowsPowerShell} Start"
    exec ${pkgs.wsl-open}/bin/wsl-open "$@"
  '';
  winPowerShell = pkgs.writeShellScriptBin "win-powershell" ''
    exec "${windowsPowerShell}" -NoProfile -ExecutionPolicy Bypass "$@"
  '';
  notifySend = pkgs.writeShellScriptBin "notify-send" ''
    # WSL notify-send Bridge (Forward to Windows)
    # Hardcoded to use Windows Terminal icon for branding.

    APP_NAME="WSL"
    SUMMARY=""
    BODY=""
    URGENCY="normal"

    while [[ $# -gt 0 ]]; do
      case "$1" in
        -a|--app-name) APP_NAME="$2"; shift 2 ;;
        --app-name=*) APP_NAME="''${1#*=}"; shift ;;
        -u|--urgency) URGENCY="$2"; shift 2 ;;
        --urgency=*) URGENCY="''${1#*=}"; shift ;;
        -t|--expire-time|--expire-time=*) shift 2 ;;
        -i|--icon|--icon=*) shift 2 ;;
        -h|--help)
          echo "Usage: notify-send [OPTIONS] <SUMMARY> [BODY]"
          exit 0
          ;;
        *)
          if [[ "$1" == -* ]]; then shift
          elif [ -z "$SUMMARY" ]; then SUMMARY="$1"; shift
          elif [ -z "$BODY" ]; then BODY="$1"; shift
          else shift; fi
          ;;
      esac
    done

    [ -z "$SUMMARY" ] && exit 1

    escape_powershell_single_quotes() {
      local value="$1"
      local single_quote="'"
      local double_single_quote
      double_single_quote=$(printf "%s%s" "$single_quote" "$single_quote")
      printf '%s' "''${value//''${single_quote}/''${double_single_quote}}"
    }

    SUMMARY_ESCAPED=$(escape_powershell_single_quotes "$SUMMARY")
    BODY_ESCAPED=$(escape_powershell_single_quotes "$BODY")
    APP_NAME_ESCAPED=$(escape_powershell_single_quotes "$APP_NAME")

    ${windowsPowerShell} -NoProfile -ExecutionPolicy Bypass -Command \
    "
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > \$null
        \$wtPackage = Get-AppxPackage -Name Microsoft.WindowsTerminal
        if (\$wtPackage) { \$iconPath = Join-Path \$wtPackage.InstallLocation 'Images\\Square44x44Logo.targetsize-256.png' }
        \$Template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastImageAndText02)
        \$RawXml = [xml]\$Template.GetXml()
        (\$RawXml.toast.visual.binding.text | Where-Object { \$_.id -eq '1' }).AppendChild(\$RawXml.CreateTextNode('$SUMMARY_ESCAPED')) > \$null
        (\$RawXml.toast.visual.binding.text | Where-Object { \$_.id -eq '2' }).AppendChild(\$RawXml.CreateTextNode('$BODY_ESCAPED')) > \$null
        if (\$iconPath -and (Test-Path \$iconPath)) {
            \$imageNode = (\$RawXml.toast.visual.binding.image | Where-Object { \$_.id -eq '1' })
            if (\$imageNode) { \$imageNode.SetAttribute('src', \$iconPath) }
        }

        if ('$URGENCY' -eq 'critical') {
            \$RawXml.toast.SetAttribute('scenario', 'reminder')
        }

        \$SerializedXml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]::New()
        \$SerializedXml.LoadXml(\$RawXml.OuterXml)

        \$Toast = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]::New(\$SerializedXml)
        \$Toast.Tag = '$APP_NAME_ESCAPED'; \$Toast.Group = 'WSL'

        if ('$URGENCY' -eq 'critical') {
            \$Toast.Priority = [Windows.UI.Notifications.ToastNotificationPriority]::High
        }

        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PowerShell').Show(\$Toast)
    "
  '';
in
{
  home.packages = [
    wslOpenWrapped
    winPowerShell
    notifySend
  ];

  home.sessionVariables = {
    PowershellExe = windowsPowerShell;
  };

  programs.fish = {
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

  systemd.user.services.agent-deck-web = {
    Unit = {
      Description = "Agent Deck web UI";
      After = [ "default.target" ];
    };
    Service = {
      ExecStart = "${lib.getExe pkgs.agent-deck} web --listen 127.0.0.1:8420";
      Restart = "on-failure";
      RestartSec = "5s";
      Type = "simple";
    };
    Install.WantedBy = [ "default.target" ];
  };

  home.activation.wslHomeSymlink = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    WSL_USER="nixos"
    USER_HOME="/home/$WSL_USER"

    if [ -d "$USER_HOME" ]; then
      WIN_USER=$(${windowsPowerShell} -NoProfile -ExecutionPolicy Bypass -Command '$env:UserName' 2>/dev/null | tr -d '\r')

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
