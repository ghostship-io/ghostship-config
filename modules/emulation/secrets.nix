{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;

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
    status_json="${cfg.configRoot}/retroachievements/status.json"
    [ -r "$secret_env" ] || {
      install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$(dirname "$status_json")"
      jq -n --arg checked_at "$(date -u +%FT%TZ)" '{checked_at:$checked_at, retroarch:"missing-secret-projection", standalone:"manual-login-required"}' >"$status_json.tmp"
      chown ${cfg.user}:${cfg.group} "$status_json.tmp"
      chmod 0644 "$status_json.tmp"
      mv "$status_json.tmp" "$status_json"
      exit 0
    }
    python3 - "$secret_env" "$retroarch_cfg" "$status_json" <<'PY'
    import json
    import os
    import shlex
    import sys
    import tempfile
    from datetime import datetime, timezone
    from pathlib import Path

    env_path = Path(sys.argv[1])
    retroarch_path = Path(sys.argv[2])
    status_path = Path(sys.argv[3])

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
    configured = bool(user and password)

    def retroarch_quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    retroarch_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="retroachievements.", dir=str(retroarch_path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        if configured:
            handle.write('cheevos_enable = "true"\n')
            handle.write('cheevos_hardcore_mode_enable = "false"\n')
            handle.write('cheevos_verbose_enable = "true"\n')
            handle.write('cheevos_auto_screenshot = "true"\n')
            handle.write(f"cheevos_username = {retroarch_quote(user)}\n")
            handle.write(f"cheevos_password = {retroarch_quote(password)}\n")
        else:
            handle.write('cheevos_enable = "false"\n')
    os.chmod(tmp, 0o640)
    Path(tmp).replace(retroarch_path)

    status_path.parent.mkdir(parents=True, exist_ok=True)
    status = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "retroarch": "configured" if configured else "missing-credentials",
        "standalone": "manual-login-required",
        "dolphin": "manual-login-required",
        "pcsx2": "manual-login-required",
        "ppsspp": "manual-login-required",
    }
    fd, tmp = tempfile.mkstemp(prefix="retroachievements-status.", dir=str(status_path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp, 0o640)
    Path(tmp).replace(status_path)
    PY
    chown ${cfg.user}:${cfg.group} "$retroarch_cfg" "$status_json"
    chmod 0640 "$retroarch_cfg" "$status_json"
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts = {
      inherit renderRetroAchievementsSettings renderScraperSettings;
    };

    age.identityPaths = lib.mkDefault [ "/etc/ssh/ssh_host_ed25519_key" ];
    age.secrets.emulation-scraper-secrets = {
      file = ../../secrets/files/services/emulation-scraper-secrets.env.age;
      mode = "0400";
    };
    age.secrets.emulation-retroachievements-secrets = {
      file = ../../secrets/files/services/emulation-retroachievements-secrets.env.age;
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
        scraper_secret_path="${config.age.secrets.emulation-scraper-secrets.path}"
        scraper_projection="/run/ghostship-secrets/emulation-scraper.env"
        if [ -r "$scraper_secret_path" ]; then
          install -d -m 0755 /run/ghostship-secrets
          awk -F= '
            /^[[:space:]]*($|#)/ { next }
            $1 ~ /^(SCREENSCRAPER_USER|SCREENSCRAPER_PASS)$/ { print }
          ' "$scraper_secret_path" >"$scraper_projection.tmp"
          chown ${cfg.user}:${cfg.group} "$scraper_projection.tmp"
          chmod 0440 "$scraper_projection.tmp"
          mv "$scraper_projection.tmp" "$scraper_projection"
          render-esde-scraper-settings || true
        fi

        retroachievements_secret_path="${config.age.secrets.emulation-retroachievements-secrets.path}"
        retroachievements_projection="/run/ghostship-secrets/emulation-retroachievements.env"
        if [ -r "$retroachievements_secret_path" ]; then
          install -d -m 0755 /run/ghostship-secrets
          awk -F= '
            /^[[:space:]]*($|#)/ { next }
            $1 ~ /^(RETROACHIEVEMENTS_USER|RETROACHIEVEMENTS_PASS)$/ { print }
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
