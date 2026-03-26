{ pkgs, ... }:

{
  # WSL-specific networking tweaks
  # Disable systemd-resolved to let WSL manage /etc/resolv.conf
  services.resolved.enable = false;

  # Explicitly ensure we are not using networkd in WSL as per user preference
  networking.useNetworkd = false;
  systemd.network.enable = false;

  # WSL-specific integration
  wsl = {
    enable = true;
    interop.register = true;
    wslConf = {
      automount.enabled = true;
      interop.enabled = true;
    };
    
    # Enable Docker Desktop integration (provided by WSL)
    # This automatically adds the 'docker' group and configures the socket.
    docker-desktop.enable = true;

    # Expose specific binaries to /bin for 'wsl -e' or direct execution from Windows
    extraBin = [
      { src = "${pkgs.coreutils}/bin/whoami"; }
    ];
  };

  # Share USERPROFILE from Windows to WSL and translate the path (/p)
  # This makes $USERPROFILE available in WSL as /mnt/c/Users/$USER
  environment.variables.WSLENV = "USERPROFILE/p";

  environment.systemPackages = [
    # Allows opening files and directories in Windows applications
    # e.g., 'wsl-open .' opens the current folder in Windows Explorer
    pkgs.wsl-open

    # WSL notify-send Bridge
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

      # Escape single quotes for PowerShell
      SUMMARY_ESCAPED=\$(echo \"\$SUMMARY\" | sed \"s/'/''/g\")
      BODY_ESCAPED=\$(echo \"\$BODY\" | sed \"s/'/''/g\")
      APP_NAME_ESCAPED=\$(echo \"\$APP_NAME\" | sed \"s/'/''/g\")

      # Invoke PowerShell to show the toast
      # We use \\\$ to ensure the dollar signs reach PowerShell without being expanded by bash.
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
          
          # Set critical urgency attributes if requested
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

  # Activation script to create ~/win-home symlink for the nixos user
  system.activationScripts.wslHomeSymlink = {
    text = ''
      # Note: Activation scripts run as root, but we want to create the link for the 'nixos' user
      # We need to get the USERPROFILE from the environment if possible,
      # but WSLENV variables might not be available here.
      # As a fallback, we can use powershell.exe to detect it.

      WSL_USER="nixos"
      USER_HOME="/home/$WSL_USER"

      if [ -d "$USER_HOME" ]; then
        # Use PowerShell to get the Windows username and construct the home path
        WIN_USER=$(/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -Command '$env:UserName' 2>/dev/null | tr -d '\r')

        if [ -n "$WIN_USER" ]; then
          WIN_HOME="/mnt/c/Users/$WIN_USER"

          if [ -n "$WIN_USER" ] && [ -d "$WIN_HOME" ]; then
            echo "Creating symlink $USER_HOME/win-home -> $WIN_HOME"
            ln -sf "$WIN_HOME" "$USER_HOME/win-home"
            chown -h $WSL_USER:nixos "$USER_HOME/win-home"
          fi
        fi
      fi
    '';
    deps = [ "users" ];
  };
}
