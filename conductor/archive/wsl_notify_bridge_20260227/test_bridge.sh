#!/usr/bin/env bash

# WSL notify-send Bridge Prototype (Windows Terminal 256x256 Icon - v2)
# Usage: ./test_bridge.sh "Title" "Message"

TITLE="${1:-WSL Notification}"
MESSAGE="${2:-Prototype check}"

# Escape single quotes for PowerShell
TITLE_ESCAPED=$(echo "$TITLE" | sed "s/'/''/g")
MESSAGE_ESCAPED=$(echo "$MESSAGE" | sed "s/'/''/g")

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > \$null
    
    # Locate Windows Terminal 256x256 Icon
    \$wtPackage = Get-AppxPackage -Name Microsoft.WindowsTerminal
    if (\$wtPackage) {
        \$iconPath = Join-Path \$wtPackage.InstallLocation 'Images\Square44x44Logo.targetsize-256.png'
    }

    # Template that supports an image and two lines of text
    \$Template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastImageAndText02)
    \$RawXml = [xml]\$Template.GetXml()
    
    # Set Text Nodes
    (\$RawXml.toast.visual.binding.text | Where-Object { \$_.id -eq '1' }).AppendChild(\$RawXml.CreateTextNode('$TITLE_ESCAPED')) > \$null
    (\$RawXml.toast.visual.binding.text | Where-Object { \$_.id -eq '2' }).AppendChild(\$RawXml.CreateTextNode('$MESSAGE_ESCAPED')) > \$null
    
    # Set Image Node using SetAttribute
    if (\$iconPath -and (Test-Path \$iconPath)) {
        \$imageNode = (\$RawXml.toast.visual.binding.image | Where-Object { \$_.id -eq '1' })
        if (\$imageNode) {
            \$imageNode.SetAttribute('src', \$iconPath)
        }
    }
    
    \$SerializedXml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]::New()
    \$SerializedXml.LoadXml(\$RawXml.OuterXml)
    
    \$Toast = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]::New(\$SerializedXml)
    \$Toast.Tag = 'PowerShell'
    \$Toast.Group = 'PowerShell'
    
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PowerShell').Show(\$Toast)
"
