#!/usr/bin/env bash

# notify-send (WSL to Windows Bridge)
# A drop-in replacement for notify-send that forwards notifications to Windows.
# Hardcoded to use the Windows Terminal icon for branding.
# Version: 1.1.0

APP_NAME="WSL"
URGENCY="normal"
EXPIRE_TIME=""
SUMMARY=""
BODY=""

# Function to show usage
show_help() {
    echo "Usage: notify-send [OPTIONS] <SUMMARY> [BODY]"
    echo ""
    echo "A WSL bridge that forwards Linux notifications to the Windows Action Center."
    echo ""
    echo "Options:"
    echo "  -a, --app-name=APP_NAME   Specify the application name (defaults to 'WSL')."
    echo "  -u, --urgency=LEVEL       Specify the urgency level (low, normal, critical)."
    echo "  -t, --expire-time=TIME    Specify the timeout in milliseconds (ignored)."
    echo "  -h, --help                Show this help message."
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -a|--app-name)
            APP_NAME="$2"
            shift 2
            ;;
        --app-name=*)
            APP_NAME="${1#*=}"
            shift
            ;;
        -u|--urgency)
            URGENCY="$2"
            shift 2
            ;;
        --urgency=*)
            URGENCY="${1#*=}"
            shift
            ;;
        -t|--expire-time)
            EXPIRE_TIME="$2"
            shift 2
            ;;
        --expire-time=*)
            EXPIRE_TIME="${1#*=}"
            shift
            ;;
        -i|--icon)
            # Icon is ignored as per hardcoding requirement
            shift 2
            ;;
        --icon=*)
            shift
            ;;
        -h|--help)
            show_help
            ;;
        *)
            if [[ "$1" == -* ]]; then
                # Ignore unknown options
                shift
            elif [ -z "$SUMMARY" ]; then
                SUMMARY="$1"
                shift
            elif [ -z "$BODY" ]; then
                BODY="$1"
                shift
            else
                shift
            fi
            ;;
    esac
done

if [ -z "$SUMMARY" ]; then
    show_help
fi

# Escape single quotes for PowerShell
SUMMARY_ESCAPED=$(echo "$SUMMARY" | sed "s/'/''/g")
BODY_ESCAPED=$(echo "$BODY" | sed "s/'/''/g")
APP_NAME_ESCAPED=$(echo "$APP_NAME" | sed "s/'/''/g")

# PowerShell command
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > \$null
    
    # Locate Windows Terminal 256x256 Icon
    \$wtPackage = Get-AppxPackage -Name Microsoft.WindowsTerminal
    if (\$wtPackage) {
        \$iconPath = Join-Path \$wtPackage.InstallLocation 'Images\Square44x44Logo.targetsize-256.png'
    }

    # Template
    \$Template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastImageAndText02)
    \$RawXml = [xml]\$Template.GetXml()
    
    # Set Text
    (\$RawXml.toast.visual.binding.text | Where-Object { \$_.id -eq '1' }).AppendChild(\$RawXml.CreateTextNode('$SUMMARY_ESCAPED')) > \$null
    (\$RawXml.toast.visual.binding.text | Where-Object { \$_.id -eq '2' }).AppendChild(\$RawXml.CreateTextNode('$BODY_ESCAPED')) > \$null
    
    # Set Image
    if (\$iconPath -and (Test-Path \$iconPath)) {
        \$imageNode = (\$RawXml.toast.visual.binding.image | Where-Object { \$_.id -eq '1' })
        if (\$imageNode) { \$imageNode.SetAttribute('src', \$iconPath) }
    }
    
    \$SerializedXml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]::New()
    \$SerializedXml.LoadXml(\$RawXml.OuterXml)
    
    \$Toast = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]::New(\$SerializedXml)
    \$Toast.Tag = '$APP_NAME_ESCAPED'
    \$Toast.Group = 'WSL'
    
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PowerShell').Show(\$Toast)
"
