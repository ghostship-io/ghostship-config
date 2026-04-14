{ config, pkgs, ... }:

let
  hermes-secrets = config.ghostship.selfHostedSecrets.units."hermes-secrets".path;
  pyload-secrets = config.ghostship.selfHostedSecrets.units."pyload-secrets".path;
  n8n-secrets = config.ghostship.selfHostedSecrets.units."n8n-secrets".path;
  bookstack-secrets = config.ghostship.selfHostedSecrets.units."bookstack-secrets".path;
  hermes-shared-secrets = config.ghostship.selfHostedSecrets.projections.hermes.path;
  render-hermes-shared-secrets = "${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project hermes";
  hermes-home = "/srv/apps/hermes/home";
  hermes-workspace = "/srv/apps/hermes/workspace";
  hermes-nix = "/srv/apps/hermes/nix";
  hermes-runtime-env = "/srv/apps/hermes/runtime.env";
  pricebuddy-agent-env = "/srv/apps/pricebuddy/pricebuddy-agent.env";
  hermes-seed-skill-creator = ./hermes-seeds/skills/skill-creator;
  hermes-seed-soul = ./hermes-seeds/SOUL.md;
  ghostship-router-channel = "1492841053642817606";
  ghostship-codex-channel = "1493462179725180959";
  discord-allowed-users = "126942974826381312";
  discord-free-response-channels = builtins.concatStringsSep "," [
    ghostship-router-channel
    ghostship-codex-channel
    "1491229269127598281"
    "1491229248856260799"
    "1491229299452412044"
  ];
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
    CHANGEDETECTION_URL = "http://changedetection:5000";
    CHAPTARR_URL = "http://chaptarr:8789";
    BOOKSTACK_URL = "http://bookstack";
    PRICEBUDDY_URL = "http://pricebuddy";
    RSS_BRIDGE_URL = "http://rss-bridge";
    SYNOLOGY_URL = "http://192.168.200.106:5000/";
    SYNOLOGY_VERIFY_SSL = "false";
  };
  hermes-runtime-env-sync = pkgs.writeTextFile {
    name = "hermes-runtime-env-sync.py";
    destination = "/bin/hermes-runtime-env-sync.py";
    executable = true;
    text = ''
      #!${pkgs.python3}/bin/python3
      import os
      import tempfile
      from pathlib import Path

      RUNTIME_ENV_PATH = Path(${builtins.toJSON hermes-runtime-env})
      PRICEBUDDY_AGENT_ENV = Path(${builtins.toJSON pricebuddy-agent-env})
      SHARED_SECRET_SOURCE = Path(${builtins.toJSON hermes-shared-secrets})

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
          projected.update(parse_env_file(SHARED_SECRET_SOURCE))

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

      def main() -> int:
          projected = build_projected_env()
          write_runtime_env(projected)
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
      "--health-cmd=[\"/bin/sh\",\"-lc\",\"curl -fsS http://127.0.0.1:7681/api/status >/dev/null || exit 1\"]"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = utility-service-env // {
      DISCORD_ALLOWED_USERS = discord-allowed-users;
      DISCORD_FREE_RESPONSE_CHANNELS = discord-free-response-channels;
      GHOSTSHIP_ROUTER_CHANNEL = ghostship-router-channel;
      GHOSTSHIP_CODEX_CHANNEL = ghostship-codex-channel;
    };
    environmentFiles = [
      hermes-secrets
      hermes-runtime-env
    ];
    volumes = [
      "${hermes-home}:/home/hermes:rw"
      "${hermes-workspace}:/workspace:rw"
      "${hermes-nix}:/nix:rw"
      "/mnt/share:/mnt/share:rw"
    ];
  };

  systemd.services.podman-hermes = {
    preStart = ''
      install -d -m0755 -o apps -g apps \
        "${hermes-home}" \
        "${hermes-home}/.hermes" \
        "${hermes-home}/.hermes/skills" \
        "${hermes-workspace}"
      install -d -m0755 "${hermes-nix}"

      if [ ! -e "${hermes-home}/.hermes/skills/skill-creator" ]; then
        ${pkgs.coreutils}/bin/cp -a "${hermes-seed-skill-creator}" "${hermes-home}/.hermes/skills/skill-creator"
        ${pkgs.coreutils}/bin/chown -R apps:apps "${hermes-home}/.hermes/skills/skill-creator"
        ${pkgs.coreutils}/bin/chmod -R u+rwX "${hermes-home}/.hermes/skills/skill-creator"
      fi

      if [ ! -e "${hermes-home}/.hermes/SOUL.md" ]; then
        install -m0644 -o apps -g apps "${hermes-seed-soul}" "${hermes-home}/.hermes/SOUL.md"
      fi

      for secret_file in \
        "${hermes-secrets}" \
        "${pyload-secrets}" \
        "${n8n-secrets}" \
        "${bookstack-secrets}"
      do
        if [ ! -f "$secret_file" ]; then
          echo "Waiting for Hermes runtime secret source at $secret_file..."
          for _ in $(seq 1 30); do
            if [ -f "$secret_file" ]; then
              break
            fi
            sleep 1
          done
        fi

        if [ ! -f "$secret_file" ]; then
          echo "Missing Hermes runtime secret source at $secret_file" >&2
          exit 1
        fi
      done

      ${render-hermes-shared-secrets}
      ${hermes-runtime-env-sync}/bin/hermes-runtime-env-sync.py
    '';
    postStart = ''
      ${pkgs.systemd}/bin/systemctl start --no-block hermes-runtime-env-sync.service || true
    '';
  };

  systemd.services.hermes-runtime-env-sync = {
    description = "Project Ghostship utility env into the Hermes runtime env file";
    after = [
      "podman-hermes.service"
      "podman-pricebuddy.service"
    ];
    wants = [
      "podman-pricebuddy.service"
    ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${hermes-runtime-env-sync}/bin/hermes-runtime-env-sync.py";
    };
  };

  systemd.paths.hermes-runtime-env-sync = {
    wantedBy = [ "multi-user.target" ];
    pathConfig = {
      PathChanged = [
        hermes-secrets
        hermes-shared-secrets
        pricebuddy-agent-env
        bookstack-secrets
      ];
      Unit = "hermes-runtime-env-sync.service";
    };
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/hermes 0755 apps apps -"
    "d /srv/apps/hermes/home 0755 apps apps -"
    "d /srv/apps/hermes/workspace 0755 apps apps -"
    "d /srv/apps/hermes/nix 0755 root root -"
  ];
}
