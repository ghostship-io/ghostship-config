{ config, pkgs, ... }:

let
  hermes-secrets = config.sops.secrets."hermes-secrets".path;
  romm-secrets = config.sops.secrets."romm-secrets".path;
  sonarr-secrets = config.sops.secrets."sonarr-secrets".path;
  radarr-secrets = config.sops.secrets."radarr-secrets".path;
  prowlarr-secrets = config.sops.secrets."prowlarr-secrets".path;
  plex-secrets = config.sops.secrets."plex-secrets".path;
  tautulli-secrets = config.sops.secrets."tautulli-secrets".path;
  bazarr-secrets = config.sops.secrets."bazarr-secrets".path;
  grimmory-secrets = config.sops.secrets."grimmory-secrets".path;
  chaptarr-secrets = config.sops.secrets."chaptarr-secrets".path;
  pyload-secrets = config.sops.secrets."pyload-secrets".path;
  hermes-home = "/srv/apps/hermes/home";
  hermes-workspace = "/srv/apps/hermes/workspace";
  hermes-nix = "/srv/apps/hermes/nix";
  hermes-runtime-env = "/srv/apps/hermes/runtime.env";
  pricebuddy-agent-env = "/srv/apps/pricebuddy/pricebuddy-agent.env";
  cloakbrowser-profiles-db = "/srv/apps/cloakbrowser/data/profiles.db";
  profile-names = [ "assistant" "operations" "supervisor" ];
  utility-service-env = {
    SEARXNG_URL = "http://searxng:8080";
    SONARR_URL = "http://sonarr:8989";
    RADARR_URL = "http://radarr:7878";
    PROWLARR_URL = "http://prowlarr:9696";
    PLEX_URL = "http://plex:32400";
    ROMM_URL = "http://romm:8080";
    NZBGET_URL = "http://gluetun:5001";
    QBITTORRENT_URL = "http://gluetun:5000";
    GRIMMORY_URL = "http://grimmory:6060";
    TAUTULLI_URL = "http://tautulli:8181";
    BAZARR_URL = "http://bazarr:6767";
    FLARESOLVERR_URL = "http://flaresolverr:8191";
    PYLOAD_URL = "http://pyload:8000";
    CLOAKBROWSER_URL = "http://cloakbrowser:8080";
    N8N_URL = "http://n8n:5678";
    N8N_PUBLIC_URL = "https://n8n.ghostship.io";
    CHANGEDETECTION_URL = "http://changedetection:5000";
    CHAPTARR_URL = "http://chaptarr:8789";
    PRICEBUDDY_URL = "http://pricebuddy";
    RSS_BRIDGE_URL = "http://rss-bridge";
    SYNOLOGY_URL = "http://192.168.200.106:5000/";
    SYNOLOGY_VERIFY_SSL = "false";
  };
  hermes-seed-profiles = {
    assistant = {
      soul = ./hermes-seeds/profiles/assistant/SOUL.md;
      skill-creator = ./hermes-seeds/profiles/assistant/skills/software-development/skill-creator;
    };
    operations = {
      soul = ./hermes-seeds/profiles/operations/SOUL.md;
      skill-creator = ./hermes-seeds/profiles/operations/skills/software-development/skill-creator;
    };
    supervisor = {
      soul = ./hermes-seeds/profiles/supervisor/SOUL.md;
      skill-creator = ./hermes-seeds/profiles/supervisor/skills/software-development/skill-creator;
    };
  };
  hermes-profile-env-sync = pkgs.writeTextFile {
    name = "hermes-profile-env-sync.py";
    destination = "/bin/hermes-profile-env-sync.py";
    executable = true;
    text = ''
      #!${pkgs.python3}/bin/python3
      import json
      import os
      import sqlite3
      import sys
      import tempfile
      import time
      from pathlib import Path

      MODE = sys.argv[1] if len(sys.argv) > 1 else "full"
      RUNTIME_ENV_PATH = Path(${builtins.toJSON hermes-runtime-env})
      PRICEBUDDY_AGENT_ENV = Path(${builtins.toJSON pricebuddy-agent-env})
      CLOAKBROWSER_PROFILES_DB = Path(${builtins.toJSON cloakbrowser-profiles-db})
      HERMES_HOME = Path(${builtins.toJSON hermes-home})
      PROFILE_NAMES = ${builtins.toJSON profile-names}
      UTILITY_SERVICE_ENV = ${builtins.toJSON utility-service-env}
      SECRET_SOURCES = [
          {
              "path": ${builtins.toJSON hermes-secrets},
              "map": {
                  "CHANGEDETECTION_API_KEY": "CHANGEDETECTION_API_KEY",
                  "N8N_API_KEY": "N8N_API_KEY",
                  "SYNOLOGY_USER": "SYNOLOGY_USER",
                  "SYNOLOGY_PASS": "SYNOLOGY_PASS",
              },
          },
          {
              "path": ${builtins.toJSON sonarr-secrets},
              "map": {
                  "SONARR_API_KEY": "SONARR_API_KEY",
              },
          },
          {
              "path": ${builtins.toJSON radarr-secrets},
              "map": {
                  "RADARR_API_KEY": "RADARR_API_KEY",
              },
          },
          {
              "path": ${builtins.toJSON prowlarr-secrets},
              "map": {
                  "PROWLARR_API_KEY": "PROWLARR_API_KEY",
              },
          },
          {
              "path": ${builtins.toJSON plex-secrets},
              "map": {
                  "PLEX_TOKEN": "PLEX_TOKEN",
              },
          },
          {
              "path": ${builtins.toJSON tautulli-secrets},
              "map": {
                  "TAUTULLI_API_KEY": "TAUTULLI_API_KEY",
              },
          },
          {
              "path": ${builtins.toJSON bazarr-secrets},
              "map": {
                  "BAZARR_API_KEY": "BAZARR_API_KEY",
              },
          },
          {
              "path": ${builtins.toJSON chaptarr-secrets},
              "map": {
                  "CHAPTARR_API_KEY": "CHAPTARR_API_KEY",
              },
          },
          {
              "path": ${builtins.toJSON pyload-secrets},
              "map": {
                  "PYLOAD_USER": "PYLOAD_USER",
                  "PYLOAD_PASS": "PYLOAD_PASS",
              },
          },
          {
              "path": ${builtins.toJSON romm-secrets},
              "map": {
                  "ROMM_USER": "ROMM_USERNAME",
                  "ROMM_PASS": "ROMM_PASSWORD",
              },
          },
          {
              "path": ${builtins.toJSON grimmory-secrets},
              "map": {
                  "GRIMMORY_USER": "GRIMMORY_USERNAME",
                  "GRIMMORY_PASS": "GRIMMORY_PASSWORD",
              },
          },
      ]
      MANAGED_KEYS = set(UTILITY_SERVICE_ENV) | {
          "SONARR_API_KEY",
          "RADARR_API_KEY",
          "PROWLARR_API_KEY",
          "PLEX_TOKEN",
          "TAUTULLI_API_KEY",
          "BAZARR_API_KEY",
          "CHAPTARR_API_KEY",
          "PYLOAD_USER",
          "PYLOAD_PASS",
          "ROMM_USERNAME",
          "ROMM_PASSWORD",
          "GRIMMORY_USERNAME",
          "GRIMMORY_PASSWORD",
          "CHANGEDETECTION_API_KEY",
          "N8N_API_KEY",
          "PRICEBUDDY_TOKEN",
          "SYNOLOGY_USER",
          "SYNOLOGY_PASS",
          "BROWSER_CDP_URL",
      }

      def parse_env_file(path: Path) -> dict[str, str]:
          values: dict[str, str] = {}
          if not path.is_file():
              return values
          for raw_line in path.read_text().splitlines():
              line = raw_line.strip()
              if not line or line.startswith("#"):
                  continue
              if line.startswith("export "):
                  line = line[7:].lstrip()
              if "=" not in line:
                  continue
              key, value = line.split("=", 1)
              key = key.strip()
              value = value.strip()
              if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                  value = value[1:-1]
              values[key] = value
          return values

      def build_projected_env() -> dict[str, str]:
          projected: dict[str, str] = {}
          for source in SECRET_SOURCES:
              source_values = parse_env_file(Path(source["path"]))
              for source_key, target_key in source["map"].items():
                  value = source_values.get(source_key)
                  if value:
                      projected[target_key] = value

          pricebuddy_values = parse_env_file(PRICEBUDDY_AGENT_ENV)
          pricebuddy_token = pricebuddy_values.get("PRICEBUDDY_API_TOKEN")
          if pricebuddy_token:
              projected["PRICEBUDDY_TOKEN"] = pricebuddy_token

          return projected

      def write_atomic(path: Path, content: str, mode: int, uid: int | None = None, gid: int | None = None) -> None:
          path.parent.mkdir(parents=True, exist_ok=True)
          with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
              handle.write(content)
              tmp_path = Path(handle.name)
          os.chmod(tmp_path, mode)
          if uid is not None and gid is not None:
              os.chown(tmp_path, uid, gid)
          tmp_path.replace(path)

      def write_runtime_env(projected: dict[str, str]) -> None:
          if projected:
              content = "".join(f"{key}={value}\n" for key, value in projected.items())
          else:
              content = ""
          write_atomic(RUNTIME_ENV_PATH, content, 0o400)

      def resolve_profile_cdp_urls(timeout_seconds: int = 60) -> dict[str, str]:
          deadline = time.time() + timeout_seconds
          expected = set(PROFILE_NAMES)
          while time.time() < deadline:
              if CLOAKBROWSER_PROFILES_DB.is_file():
                  try:
                      with sqlite3.connect(CLOAKBROWSER_PROFILES_DB) as connection:
                          rows = connection.execute(
                              "SELECT id, name FROM profiles WHERE name IN (?, ?, ?)",
                              PROFILE_NAMES,
                          ).fetchall()
                  except sqlite3.Error:
                      rows = []
                  if rows:
                      resolved = {
                          name: f"http://cloakbrowser:8080/api/profiles/{profile_id}/cdp"
                          for profile_id, name in rows
                          if name in expected
                      }
                      if resolved.keys() >= expected:
                          return resolved
              time.sleep(1)
          return {}

      def patch_profile_env(profile_name: str, projected: dict[str, str], profile_cdp_urls: dict[str, str]) -> None:
          profile_env_path = HERMES_HOME / ".hermes" / "profiles" / profile_name / ".env"
          if not profile_env_path.is_file():
              return

          lines = profile_env_path.read_text().splitlines()
          preserved: list[str] = []
          for line in lines:
              stripped = line.strip()
              if stripped.startswith("export "):
                  stripped = stripped[7:].lstrip()
              if stripped and "=" in stripped:
                  key = stripped.split("=", 1)[0].strip()
                  if key in MANAGED_KEYS:
                      continue
              preserved.append(line)

          managed_entries = dict(UTILITY_SERVICE_ENV)
          managed_entries.update(projected)
          cdp_url = profile_cdp_urls.get(profile_name)
          if cdp_url:
              managed_entries["BROWSER_CDP_URL"] = cdp_url

          while preserved and preserved[-1] == "":
              preserved.pop()
          if preserved:
              preserved.append("")
          preserved.extend(f"{key}={value}" for key, value in managed_entries.items())
          content = "\n".join(preserved) + "\n"
          write_atomic(profile_env_path, content, 0o600, uid=3000, gid=3000)

      def patch_profiles(projected: dict[str, str]) -> None:
          deadline = time.time() + 120
          while time.time() < deadline:
              if all((HERMES_HOME / ".hermes" / "profiles" / profile / ".env").is_file() for profile in PROFILE_NAMES):
                  break
              time.sleep(1)
          profile_cdp_urls = resolve_profile_cdp_urls()
          for profile_name in PROFILE_NAMES:
              patch_profile_env(profile_name, projected, profile_cdp_urls)

      def main() -> int:
          projected = build_projected_env()
          write_runtime_env(projected)
          if MODE != "runtime-only":
              patch_profiles(projected)
          return 0

      raise SystemExit(main())
    '';
  };
in
{
  virtualisation.oci-containers.containers."hermes" = {
    image = "ghcr.io/ghostship-io/ghostship-hermes:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--privileged"
      "--health-cmd=/run/current-system/sw/bin/curl -fsS http://127.0.0.1:7681/ >/dev/null || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = utility-service-env // {
      HOME = "/home/hermes";
      HERMES_HOME = "/home/hermes/.hermes";
      GHOSTSHIP_WORKSPACE_ROOT = "/workspace";
      TTYD_PORT = "7681";
      TTYD_TITLE = "Ghostship Hermes";
      TTYD_SESSION_NAME = "hermes";
      DISCORD_GENERAL_CHANNEL_ID = "1488255112169394309";
      DISCORD_ASSISTANT_ALLOWED_USERS = "126942974826381312";
      DISCORD_ASSISTANT_CHANNEL_ID = "1491229269127598281";
      DISCORD_OPERATIONS_ALLOWED_USERS = "126942974826381312";
      DISCORD_OPERATIONS_CHANNEL_ID = "1491229248856260799";
      DISCORD_SUPERVISOR_ALLOWED_USERS = "126942974826381312";
      DISCORD_SUPERVISOR_CHANNEL_ID = "1491229299452412044";
    };
    environmentFiles = [
      hermes-secrets
      hermes-runtime-env
    ];
    volumes = [
      "${hermes-home}:/home/hermes:rw"
      "${hermes-workspace}:/workspace:rw"
      "${hermes-nix}:/nix:rw"
    ];
  };

  systemd.services.podman-hermes = {
    preStart = ''
      install -d -m0755 -o apps -g apps "${hermes-home}" "${hermes-workspace}"
      install -d -m0755 "${hermes-nix}"
      install -d -m0755 -o apps -g apps \
        "${hermes-home}/seeds" \
        "${hermes-home}/seeds/profiles" \
        "${hermes-home}/seeds/profiles/assistant" \
        "${hermes-home}/seeds/profiles/assistant/skills" \
        "${hermes-home}/seeds/profiles/assistant/skills/software-development" \
        "${hermes-home}/seeds/profiles/operations" \
        "${hermes-home}/seeds/profiles/operations/skills" \
        "${hermes-home}/seeds/profiles/operations/skills/software-development" \
        "${hermes-home}/seeds/profiles/supervisor" \
        "${hermes-home}/seeds/profiles/supervisor/skills" \
        "${hermes-home}/seeds/profiles/supervisor/skills/software-development"

      if [ ! -e "${hermes-home}/seeds/profiles/assistant/skills/software-development/skill-creator" ]; then
        ${pkgs.coreutils}/bin/cp -a "${hermes-seed-profiles.assistant.skill-creator}" "${hermes-home}/seeds/profiles/assistant/skills/software-development/skill-creator"
        ${pkgs.coreutils}/bin/chown -R apps:apps "${hermes-home}/seeds/profiles/assistant/skills/software-development/skill-creator"
      fi

      if [ ! -e "${hermes-home}/seeds/profiles/operations/skills/software-development/skill-creator" ]; then
        ${pkgs.coreutils}/bin/cp -a "${hermes-seed-profiles.operations.skill-creator}" "${hermes-home}/seeds/profiles/operations/skills/software-development/skill-creator"
        ${pkgs.coreutils}/bin/chown -R apps:apps "${hermes-home}/seeds/profiles/operations/skills/software-development/skill-creator"
      fi

      if [ ! -e "${hermes-home}/seeds/profiles/supervisor/skills/software-development/skill-creator" ]; then
        ${pkgs.coreutils}/bin/cp -a "${hermes-seed-profiles.supervisor.skill-creator}" "${hermes-home}/seeds/profiles/supervisor/skills/software-development/skill-creator"
        ${pkgs.coreutils}/bin/chown -R apps:apps "${hermes-home}/seeds/profiles/supervisor/skills/software-development/skill-creator"
      fi

      if [ ! -e "${hermes-home}/seeds/profiles/assistant/SOUL.md" ]; then
        install -m0644 -o apps -g apps "${hermes-seed-profiles.assistant.soul}" "${hermes-home}/seeds/profiles/assistant/SOUL.md"
      fi

      if [ ! -e "${hermes-home}/seeds/profiles/operations/SOUL.md" ]; then
        install -m0644 -o apps -g apps "${hermes-seed-profiles.operations.soul}" "${hermes-home}/seeds/profiles/operations/SOUL.md"
      fi

      if [ ! -e "${hermes-home}/seeds/profiles/supervisor/SOUL.md" ]; then
        install -m0644 -o apps -g apps "${hermes-seed-profiles.supervisor.soul}" "${hermes-home}/seeds/profiles/supervisor/SOUL.md"
      fi

      if [ ! -f "${hermes-secrets}" ]; then
        echo "Waiting for Hermes secrets at ${hermes-secrets}..."
        for _ in $(seq 1 30); do
          if [ -f "${hermes-secrets}" ]; then
            break
          fi
          sleep 1
        done
      fi

      if [ ! -f "${hermes-secrets}" ]; then
        echo "Missing Hermes secrets file at ${hermes-secrets}" >&2
        exit 1
      fi

      ${hermes-profile-env-sync}/bin/hermes-profile-env-sync.py runtime-only

      seed_container=""
      seed_rootfs=""

      cleanup() {
        if [ -n "$seed_rootfs" ]; then
          ${pkgs.podman}/bin/podman unmount "$seed_container" >/dev/null 2>&1 || true
        fi
        if [ -n "$seed_container" ]; then
          ${pkgs.podman}/bin/podman rm -f "$seed_container" >/dev/null 2>&1 || true
        fi
      }

      trap cleanup EXIT
      ${pkgs.podman}/bin/podman pull ghcr.io/ghostship-io/ghostship-hermes:latest >/dev/null
      seed_container="$(${pkgs.podman}/bin/podman create ghcr.io/ghostship-io/ghostship-hermes:latest)"
      seed_rootfs="$(${pkgs.podman}/bin/podman mount "$seed_container")"

      seed_system="$(${pkgs.findutils}/bin/find "$seed_rootfs/nix/store" -maxdepth 1 -mindepth 1 -name '*-nixos-system-ghostship-hermes-*' -printf '%f\n' -quit)"
      current_store_entry="$(${pkgs.findutils}/bin/find "${hermes-nix}/store" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null || true)"

      if [ -z "$current_store_entry" ] || [ -z "$seed_system" ] || [ ! -e "${hermes-nix}/store/$seed_system" ]; then
        echo "Refreshing Hermes /nix from ghcr.io/ghostship-io/ghostship-hermes:latest"
        ${pkgs.rsync}/bin/rsync -aH --numeric-ids "$seed_rootfs/nix/" "${hermes-nix}/"
      fi

      cleanup
      trap - EXIT
    '';
    postStart = ''
      for _ in $(seq 1 30); do
        if ${pkgs.podman}/bin/podman exec hermes /run/current-system/sw/bin/systemctl --system list-unit-files >/dev/null 2>&1; then
          break
        fi
        sleep 1
      done

      ${pkgs.podman}/bin/podman exec hermes sh -lc '
        /run/current-system/sw/bin/systemctl --system start \
          ghostship-hermes-user-tooling-refresh.timer \
          ghostship-hermes-startup.service
      '

      ${pkgs.systemd}/bin/systemctl start hermes-profile-env-sync.service || true
    '';
  };

  systemd.services.hermes-profile-env-sync = {
    description = "Project Ghostship utility env into managed Hermes profile env files";
    after = [
      "podman-hermes.service"
      "podman-cloakbrowser.service"
      "podman-pricebuddy.service"
    ];
    wants = [
      "podman-cloakbrowser.service"
      "podman-pricebuddy.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${hermes-profile-env-sync}/bin/hermes-profile-env-sync.py";
    };
  };

  systemd.paths.hermes-profile-env-sync = {
    wantedBy = [ "multi-user.target" ];
    pathConfig = {
      PathChanged = [
        cloakbrowser-profiles-db
        pricebuddy-agent-env
      ];
      Unit = "hermes-profile-env-sync.service";
    };
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/hermes 0755 apps apps -"
    "d /srv/apps/hermes/home 0755 apps apps -"
    "d /srv/apps/hermes/workspace 0755 apps apps -"
    "d /srv/apps/hermes/nix 0755 root root -"
  ];
}
