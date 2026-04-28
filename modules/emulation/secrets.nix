{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;

  boomerRenderScraperSettings = pkgs.writeShellScriptBin "boomer-render-esde-scraper-settings" ''
    set -euo pipefail
    export PATH=${emu.scriptPath}:${lib.makeBinPath [ pkgs.python3 ]}:$PATH
    secret_env="/run/ghostship-secrets/emulation-scraper.env"
    settings="${cfg.esde.appDataDir}/settings/es_settings.xml"
    [ -r "$secret_env" ] || exit 0
    python3 - "$secret_env" "$settings" <<'PY'
    import os
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
        tree = ET.parse(settings_path)
        root = tree.getroot()
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        root = ET.Element("settings")
        tree = ET.ElementTree(root)

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
    if values.get("THEGAMESDB_API_KEY"):
        set_entry("string", "ScraperTheGamesDBAPIKey", values["THEGAMESDB_API_KEY"])
        set_entry("string", "ScraperTheGamesDBApiKey", values["THEGAMESDB_API_KEY"])

    set_entry("string", "Scraper", "screenscraper")
    set_entry("bool", "ScrapeVideos", "true")
    set_entry("bool", "ScrapeScreenshots", "true")
    set_entry("bool", "ScrapeCovers", "true")
    set_entry("bool", "ScrapeMarquees", "true")
    set_entry("bool", "MiximageGenerate", "true")

    fd, tmp = tempfile.mkstemp(prefix="es_settings.", dir=str(settings_path.parent))
    os.close(fd)
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    os.chmod(tmp, 0o640)
    Path(tmp).replace(settings_path)
    PY
    chown ${cfg.user}:${cfg.group} "$settings"
    chmod 0640 "$settings"
  '';
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.scripts.boomerRenderScraperSettings = boomerRenderScraperSettings;

    age.identityPaths = lib.mkDefault [ "/etc/ssh/ssh_host_ed25519_key" ];
    age.secrets.emulation-scraper-secrets = {
      file = ../../secrets/files/services/emulation-scraper-secrets.env.age;
      mode = "0400";
    };

    systemd.services.boomer-emulation-secrets = {
      description = "Project Boomer Kuwanger emulation scraper secrets";
      wantedBy = [ "multi-user.target" ];
      after = [ "agenix.service" "boomer-emulation-setup.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      path = [ pkgs.coreutils pkgs.gawk boomerRenderScraperSettings ];
      script = ''
        secret_path="${config.age.secrets.emulation-scraper-secrets.path}"
        projection="/run/ghostship-secrets/emulation-scraper.env"
        if [ -r "$secret_path" ]; then
          install -d -m 0755 /run/ghostship-secrets
          awk -F= '
            /^[[:space:]]*($|#)/ { next }
            $1 ~ /^(SCREENSCRAPER_USER|SCREENSCRAPER_PASS|THEGAMESDB_API_KEY)$/ { print }
          ' "$secret_path" >"$projection.tmp"
          chown ${cfg.user}:${cfg.group} "$projection.tmp"
          chmod 0440 "$projection.tmp"
          mv "$projection.tmp" "$projection"
          boomer-render-esde-scraper-settings || true
        fi
      '';
    };
  };
}
