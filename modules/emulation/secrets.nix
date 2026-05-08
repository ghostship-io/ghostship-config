{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;
  recipients = import ../../secrets/recipients.nix;
  catalog = import ../../secrets/catalog.nix { inherit recipients; };

  renderScraperSettings = pkgs.writeShellScriptBin "render-esde-scraper-settings" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${lib.makeBinPath [ pkgs.python3 ]}:$PATH
    secret_env="/run/ghostship-secrets/emulation-scraper.env"
    settings="${cfg.esde.appDataDir}/settings/es_settings.xml"
    [ -r "$secret_env" ] || exit 0
    python3 - "$secret_env" "$settings" <<'PY'
    import os
    import re
    import shlex
    import sys
    import tempfile
    import xml.etree.ElementTree as ET
    from pathlib import Path

    env_path = Path(sys.argv[1])
    settings_path = Path(sys.argv[2])

    values = {}
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            value = shlex.split(value)[0] if value else ""
        except ValueError:
            pass
        values[key] = value

    if settings_path.exists():
        raw_settings = settings_path.read_text()
        try:
            root = ET.fromstring(raw_settings)
            if root.tag != "settings":
                wrapper = ET.Element("settings")
                wrapper.append(root)
                root = wrapper
        except ET.ParseError:
            body = re.sub(r"^\s*<\?xml[^>]*\?>", "", raw_settings, count=1)
            root = ET.fromstring(f"<settings>{body}</settings>")
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        root = ET.Element("settings")

    def set_entry(tag, name, value):
        for entry in root.findall(tag):
            if entry.get("name") == name:
                entry.set("value", value)
                return
        ET.SubElement(root, tag, {"name": name, "value": value})

    if values.get("SCREENSCRAPER_USER"):
        set_entry("string", "ScraperUsernameScreenScraper", values["SCREENSCRAPER_USER"])
    if values.get("SCREENSCRAPER_PASS"):
        set_entry("string", "ScraperPasswordScreenScraper", values["SCREENSCRAPER_PASS"])
    if values.get("SCREENSCRAPER_USER") and values.get("SCREENSCRAPER_PASS"):
        set_entry("bool", "ScraperUseAccountScreenScraper", "true")
    set_entry("string", "Scraper", "screenscraper")
    set_entry("bool", "ScrapeVideos", "true")
    set_entry("bool", "ScrapeScreenshots", "true")
    set_entry("bool", "ScrapeCovers", "true")
    set_entry("bool", "ScrapeMarquees", "true")
    set_entry("bool", "MiximageGenerate", "true")

    fd, tmp = tempfile.mkstemp(prefix="es_settings.", dir=str(settings_path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write('<?xml version="1.0"?>\n')
        for entry in root:
            handle.write(ET.tostring(entry, encoding="unicode"))
            handle.write("\n")
    os.chmod(tmp, 0o640)
    Path(tmp).replace(settings_path)
    PY
    chown ${cfg.user}:${cfg.group} "$settings"
    chmod 0640 "$settings"
  '';

  renderRetroAchievementsSettings = pkgs.writeShellScriptBin "render-retroachievements-settings" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${lib.makeBinPath [ pkgs.python3 ]}:$PATH
    secret_env="/run/ghostship-secrets/emulation-retroachievements.env"
    retroarch_cfg="${cfg.configRoot}/retroarch/retroachievements.cfg"
    pcsx2_secrets="${cfg.dataRoot}/xdg/config/PCSX2/inis/secrets.ini"
    status_json="${cfg.configRoot}/retroachievements/status.json"
    [ -r "$secret_env" ] || {
      install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$(dirname "$retroarch_cfg")"
      install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$(dirname "$pcsx2_secrets")"
      install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$(dirname "$status_json")"
      printf 'cheevos_enable = "false"\n' >"$retroarch_cfg.tmp"
      chown ${cfg.user}:${cfg.group} "$retroarch_cfg.tmp"
      chmod 0640 "$retroarch_cfg.tmp"
      mv "$retroarch_cfg.tmp" "$retroarch_cfg"
      printf '[Achievements]\n' >"$pcsx2_secrets.tmp"
      chown ${cfg.user}:${cfg.group} "$pcsx2_secrets.tmp"
      chmod 0640 "$pcsx2_secrets.tmp"
      mv "$pcsx2_secrets.tmp" "$pcsx2_secrets"
      jq -n --arg checked_at "$(date -u +%FT%TZ)" '{checked_at:$checked_at, retroarch:"missing-secret-projection", standalone:"manual-login-required"}' >"$status_json.tmp"
      chown ${cfg.user}:${cfg.group} "$status_json.tmp"
      chmod 0644 "$status_json.tmp"
      mv "$status_json.tmp" "$status_json"
      exit 0
    }
    python3 - "$secret_env" "$retroarch_cfg" "$pcsx2_secrets" "$status_json" <<'PY'
    import json
    import os
    import shlex
    import sys
    import tempfile
    from datetime import datetime, timezone
    from pathlib import Path

    env_path = Path(sys.argv[1])
    retroarch_path = Path(sys.argv[2])
    pcsx2_secrets_path = Path(sys.argv[3])
    status_path = Path(sys.argv[4])

    values = {}
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            value = shlex.split(value)[0] if value else ""
        except ValueError:
            pass
        values[key] = value

    user = values.get("RETROACHIEVEMENTS_USER", "")
    password = values.get("RETROACHIEVEMENTS_PASS", "")
    token = values.get("RETROACHIEVEMENTS_TOKEN", "")
    configured = bool(user and password)
    pcsx2_configured = bool(user and token)

    def retroarch_quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    retroarch_path.parent.mkdir(parents=True, exist_ok=True)
    output = [f"cheevos_enable = {retroarch_quote('true' if configured else 'false')}"]
    if configured:
        output.extend([
            f"cheevos_hardcore_mode_enable = {retroarch_quote('false')}",
            f"cheevos_verbose_enable = {retroarch_quote('true')}",
            f"cheevos_start_active = {retroarch_quote('true')}",
            f"cheevos_auto_screenshot = {retroarch_quote('true')}",
            f"cheevos_badges_enable = {retroarch_quote('true')}",
            f"cheevos_challenge_indicators = {retroarch_quote('true')}",
            f"cheevos_richpresence_enable = {retroarch_quote('true')}",
            f"cheevos_visibility_account = {retroarch_quote('true')}",
            f"cheevos_visibility_unlock = {retroarch_quote('true')}",
            f"cheevos_visibility_mastery = {retroarch_quote('true')}",
            f"cheevos_visibility_lboard_start = {retroarch_quote('true')}",
            f"cheevos_visibility_lboard_submit = {retroarch_quote('true')}",
            f"cheevos_visibility_lboard_trackers = {retroarch_quote('false')}",
            f"cheevos_unlock_sound_enable = {retroarch_quote('true')}",
            f"cheevos_test_unofficial = {retroarch_quote('false')}",
            f"cheevos_username = {retroarch_quote(user)}",
            f"cheevos_password = {retroarch_quote(password)}",
        ])

    fd, tmp = tempfile.mkstemp(prefix="retroarch.", dir=str(retroarch_path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(output))
        handle.write("\n")
    os.chmod(tmp, 0o640)
    Path(tmp).replace(retroarch_path)

    pcsx2_secrets_path.parent.mkdir(parents=True, exist_ok=True)
    pcsx2_output = ["[Achievements]"]
    if pcsx2_configured:
        pcsx2_output.append(f"Token = {token}")
    fd, tmp = tempfile.mkstemp(prefix="pcsx2-secrets.", dir=str(pcsx2_secrets_path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(pcsx2_output))
        handle.write("\n")
    os.chmod(tmp, 0o640)
    Path(tmp).replace(pcsx2_secrets_path)

    status_path.parent.mkdir(parents=True, exist_ok=True)
    status = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "retroarch": "configured" if configured else "missing-credentials",
        "standalone": "partial",
        "dolphin": "manual-login-required",
        "pcsx2": "configured" if pcsx2_configured else "missing-token",
        "ppsspp": "manual-login-required",
    }
    fd, tmp = tempfile.mkstemp(prefix="retroachievements-status.", dir=str(status_path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp, 0o640)
    Path(tmp).replace(status_path)
    PY
    chown ${cfg.user}:${cfg.group} "$retroarch_cfg" "$pcsx2_secrets" "$status_json"
    chmod 0640 "$retroarch_cfg" "$pcsx2_secrets" "$status_json"
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts = {
      inherit renderRetroAchievementsSettings renderScraperSettings;
    };

    age.identityPaths = lib.mkDefault [ "/etc/ssh/ssh_host_ed25519_key" ];
    age.secrets.screenscraper = {
      file = catalog.units.screenscraper.path;
      mode = "0400";
    };
    age.secrets.retroachievements = {
      file = catalog.units.retroachievements.path;
      mode = "0400";
    };

    systemd.services.emulation-secrets = {
      description = "Emulation scraper and RetroAchievements secrets";
      wantedBy = [ "multi-user.target" ];
      after = [ "agenix.service" "emulation-setup.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      path = [ pkgs.coreutils pkgs.gawk renderRetroAchievementsSettings renderScraperSettings ];
      script = ''
        scraper_secret_path="${config.age.secrets.screenscraper.path}"
        scraper_projection="/run/ghostship-secrets/emulation-scraper.env"
        if [ -r "$scraper_secret_path" ]; then
          install -d -m 0755 /run/ghostship-secrets
          awk -F= '
            /^[[:space:]]*($|#)/ { next }
            {
              key = $1
              sub(/^[^=]*=/, "")
              if (key == "USER") print "SCREENSCRAPER_USER=" $0
              if (key == "PASS") print "SCREENSCRAPER_PASS=" $0
            }
          ' "$scraper_secret_path" >"$scraper_projection.tmp"
          chown ${cfg.user}:${cfg.group} "$scraper_projection.tmp"
          chmod 0440 "$scraper_projection.tmp"
          mv "$scraper_projection.tmp" "$scraper_projection"
          render-esde-scraper-settings || true
        fi

        retroachievements_secret_path="${config.age.secrets.retroachievements.path}"
        retroachievements_projection="/run/ghostship-secrets/emulation-retroachievements.env"
        if [ -r "$retroachievements_secret_path" ]; then
          install -d -m 0755 /run/ghostship-secrets
          awk -F= '
            /^[[:space:]]*($|#)/ { next }
            {
              key = $1
              sub(/^[^=]*=/, "")
              if (key == "USER") print "RETROACHIEVEMENTS_USER=" $0
              if (key == "PASS") print "RETROACHIEVEMENTS_PASS=" $0
              if (key == "TOKEN") print "RETROACHIEVEMENTS_TOKEN=" $0
            }
          ' "$retroachievements_secret_path" >"$retroachievements_projection.tmp"
          chown ${cfg.user}:${cfg.group} "$retroachievements_projection.tmp"
          chmod 0440 "$retroachievements_projection.tmp"
          mv "$retroachievements_projection.tmp" "$retroachievements_projection"
        fi
        render-retroachievements-settings || true
      '';
    };
  };
}
