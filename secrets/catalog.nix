{ recipients }:
let
  mkUnit =
    {
      relativeFile,
      recipientGroup ? "self-hosted-runtime",
      owner ? null,
      group ? null,
      mode ? "0400",
      format ? "env",
      exports,
    }:
    {
      inherit
        relativeFile
        recipientGroup
        mode
        format
        exports
        ;
      path = ./. + "/${builtins.substring 8 ((builtins.stringLength relativeFile) - 8) relativeFile}";
      recipients = builtins.getAttr recipientGroup recipients.groups;
    }
    // (if owner == null then { } else { inherit owner; })
    // (if group == null then { } else { inherit group; });
in
{
  units = {
    agent-desktop = mkUnit {
      relativeFile = "secrets/files/sources/services/agent-desktop.env.age";
      exports = [ "API_TOKEN" ];
    };
    ghostship-relay = mkUnit {
      relativeFile = "secrets/files/sources/services/ghostship-relay.env.age";
      exports = [
        "TUNNEL_ID"
        "API_KEY"
      ];
    };
    backup = mkUnit {
      relativeFile = "secrets/files/sources/services/backup.env.age";
      exports = [ "RESTIC_PASSWORD" ];
    };
    monitoring = mkUnit {
      relativeFile = "secrets/files/sources/services/monitoring.env.age";
      exports = [
        "KUMA_PASSWORD"
        "NTFY_ADMIN_HASH"
        "NTFY_PUBLISH_HASH"
        "NTFY_READER_HASH"
        "NTFY_PUBLISH_PASSWORD"
        "NTFY_READER_PASSWORD"
      ];
    };
    bazarr = mkUnit {
      relativeFile = "secrets/files/sources/services/bazarr.env.age";
      exports = [
        "API_KEY"
        "FLASK_SECRET_KEY"
      ];
    };

    bitwarden = mkUnit {
      relativeFile = "secrets/files/sources/providers/bitwarden.env.age";
      exports = [
        "BW_CLIENTID"
        "BW_CLIENTSECRET"
        "BW_PASSWORD"
      ];
    };

    chaptarr = mkUnit {
      relativeFile = "secrets/files/sources/services/chaptarr.env.age";
      exports = [ "API_KEY" ];
    };

    cloudflare = mkUnit {
      relativeFile = "secrets/files/sources/providers/cloudflare.env.age";
      exports = [
        "TUNNEL_TOKEN"
        "ACCOUNT_ID"
        "TUNNEL_ID"
        "API_TOKEN"
      ];
    };

    cloudflare-workers-ai = mkUnit {
      relativeFile = "secrets/files/sources/providers/cloudflare-workers-ai.env.age";
      exports = [
        "API_KEY"
        "ACCOUNT_ID"
      ];
    };

    cohere = mkUnit {
      relativeFile = "secrets/files/sources/providers/cohere.env.age";
      exports = [ "API_KEY" ];
    };

    inference-bridge-token = mkUnit {
      relativeFile = "secrets/files/sources/services/inference-bridge-token.age";
      format = "raw";
      exports = [ ];
    };

    discord = mkUnit {
      relativeFile = "secrets/files/sources/providers/discord.env.age";
      exports = [
        "BOT_TOKEN"
        "WEBHOOK_SECRET"
      ];
    };

    dockerhub = mkUnit {
      relativeFile = "secrets/files/sources/providers/dockerhub.env.age";
      exports = [
        "USER"
        "TOKEN"
      ];
    };

    github = mkUnit {
      relativeFile = "secrets/files/sources/providers/github.env.age";
      exports = [ "TOKEN" ];
    };

    kilo = mkUnit {
      relativeFile = "secrets/files/sources/providers/kilo.env.age";
      exports = [ "API_KEY" ];
    };

    requesty = mkUnit {
      relativeFile = "secrets/files/sources/providers/requesty.env.age";
      exports = [ "API_KEY" ];
    };

    orcarouter = mkUnit {
      relativeFile = "secrets/files/sources/providers/orcarouter.env.age";
      exports = [ "API_KEY" ];
    };

    inception = mkUnit {
      relativeFile = "secrets/files/sources/providers/inception.env.age";
      exports = [ "API_KEY" ];
    };

    mistral = mkUnit {
      relativeFile = "secrets/files/sources/providers/mistral.env.age";
      exports = [ "API_KEY" ];
    };

    upstage = mkUnit {
      relativeFile = "secrets/files/sources/providers/upstage.env.age";
      exports = [ "API_KEY" ];
    };

    zai = mkUnit {
      relativeFile = "secrets/files/sources/providers/zai.env.age";
      exports = [ "API_KEY" ];
    };

    poolside = mkUnit {
      relativeFile = "secrets/files/sources/providers/poolside.env.age";
      exports = [ "API_KEY" ];
    };

    groq = mkUnit {
      relativeFile = "secrets/files/sources/providers/groq.env.age";
      exports = [ "API_KEY" ];
    };

    google-ai-studio = mkUnit {
      relativeFile = "secrets/files/sources/providers/google-ai-studio.env.age";
      exports = [ "API_KEY" ];
    };

    huggingface = mkUnit {
      relativeFile = "secrets/files/sources/providers/huggingface.env.age";
      exports = [ "TOKEN" ];
    };

    id-ed25519-dev = mkUnit {
      relativeFile = "secrets/files/sources/home/id_ed25519_dev.age";
      recipientGroup = "editors";
      format = "raw";
      exports = [ ];
    };

    gluetun = mkUnit {
      relativeFile = "secrets/files/sources/services/gluetun.env.age";
      exports = [ "HTTP_CONTROL_SERVER_API_KEY" ];
    };

    grimmory = mkUnit {
      relativeFile = "secrets/files/sources/services/grimmory.env.age";
      exports = [
        "DB_USER"
        "DB_PASS"
        "MYSQL_ROOT_PASS"
        "USER"
        "PASS"
      ];
    };

    igdb = mkUnit {
      relativeFile = "secrets/files/sources/providers/igdb.env.age";
      exports = [
        "CLIENT_ID"
        "CLIENT_SECRET"
      ];
    };

    ollama = mkUnit {
      relativeFile = "secrets/files/sources/providers/ollama.env.age";
      exports = [ "API_KEY" ];
    };

    nvidia = mkUnit {
      relativeFile = "secrets/files/sources/providers/nvidia.env.age";
      exports = [ "API_KEY" ];
    };

    opencode = mkUnit {
      relativeFile = "secrets/files/sources/services/opencode.env.age";
      exports = [ "GO_API_KEY" ];
    };

    openrouter = mkUnit {
      relativeFile = "secrets/files/sources/providers/openrouter.env.age";
      exports = [ "API_KEY" ];
    };

    opensubtitles = mkUnit {
      relativeFile = "secrets/files/sources/providers/opensubtitles.env.age";
      exports = [ "PASS" ];
    };

    plex = mkUnit {
      relativeFile = "secrets/files/sources/services/plex.env.age";
      exports = [
        "CLAIM"
        "API_KEY"
        "TOKEN"
      ];
    };

    prowlarr = mkUnit {
      relativeFile = "secrets/files/sources/services/prowlarr.env.age";
      exports = [ "API_KEY" ];
    };

    pyload = mkUnit {
      relativeFile = "secrets/files/sources/services/pyload.env.age";
      exports = [ "API_KEY" ];
    };

    radarr = mkUnit {
      relativeFile = "secrets/files/sources/services/radarr.env.age";
      exports = [ "API_KEY" ];
    };

    retroachievements = mkUnit {
      relativeFile = "secrets/files/sources/providers/retroachievements.env.age";
      recipientGroup = "shared-runtime";
      exports = [
        "USER"
        "PASS"
        "TOKEN"
        "API_KEY"
      ];
    };

    romm-db-admin = mkUnit {
      relativeFile = "secrets/files/sources/services/romm-db-admin.env.age";
      exports = [ "MYSQL_ROOT_PASSWORD" ];
    };

    romm = mkUnit {
      relativeFile = "secrets/files/sources/services/romm.env.age";
      exports = [
        "DB_USER"
        "DB_PASS"
        "USER"
        "PASS"
        "AUTH_SECRET"
      ];
    };

    screenscraper = mkUnit {
      relativeFile = "secrets/files/sources/providers/screenscraper.env.age";
      recipientGroup = "shared-runtime";
      exports = [
        "USER"
        "PASS"
      ];
    };

    sonarr = mkUnit {
      relativeFile = "secrets/files/sources/services/sonarr.env.age";
      exports = [ "API_KEY" ];
    };

    steamgriddb = mkUnit {
      relativeFile = "secrets/files/sources/providers/steamgriddb.env.age";
      exports = [ "API_KEY" ];
    };

    subdl = mkUnit {
      relativeFile = "secrets/files/sources/providers/subdl.env.age";
      exports = [ "API_KEY" ];
    };

    synology = mkUnit {
      relativeFile = "secrets/files/sources/providers/synology.env.age";
      exports = [
        "USER"
        "PASS"
      ];
    };

    # Wyze account login for the scale API (Bitwarden wyze.com: email, account_password, key_id, api_key).
    wyze = mkUnit {
      relativeFile = "secrets/files/sources/providers/wyze.env.age";
      exports = [ "EMAIL" "PASSWORD" "KEY_ID" "API_KEY" ];
    };

    # Ultrahuman UltraSignal personal API token (Bitwarden ultrahuman.com, field api_token).
    ultrahuman = mkUnit {
      relativeFile = "secrets/files/sources/providers/ultrahuman.env.age";
      exports = [ "API_TOKEN" ];
    };

    tautulli = mkUnit {
      relativeFile = "secrets/files/sources/services/tautulli.env.age";
      exports = [ "API_KEY" ];
    };

    usenet = mkUnit {
      relativeFile = "secrets/files/sources/providers/usenet.env.age";
      exports = [
        "NZBGET_SERVER1_USER"
        "NZBGET_SERVER1_PASS"
      ];
    };

    vpn = mkUnit {
      relativeFile = "secrets/files/sources/providers/vpn.env.age";
      exports = [
        "OPENVPN_USER"
        "OPENVPN_PASS"
      ];
    };

    vercel-ai-gateway = mkUnit {
      relativeFile = "secrets/files/sources/providers/vercel-ai-gateway.env.age";
      exports = [ "API_KEY" ];
    };

  };

  projections = {
    ghostship-relay = {
      fileName = "ghostship-relay.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        TUNNEL_ID = {
          unit = "ghostship-relay";
          key = "TUNNEL_ID";
        };
        API_KEY = {
          unit = "ghostship-relay";
          key = "API_KEY";
        };
      };
    };
    backup = {
      fileName = "backup.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields.RESTIC_PASSWORD = {
        unit = "backup";
        key = "RESTIC_PASSWORD";
      };
    };
    monitoring = {
      fileName = "monitoring.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = builtins.listToAttrs (
        map
          (key: {
            name = key;
            value = {
              unit = "monitoring";
              inherit key;
            };
          })
          [
            "KUMA_PASSWORD"
            "NTFY_ADMIN_HASH"
            "NTFY_PUBLISH_HASH"
            "NTFY_READER_HASH"
            "NTFY_PUBLISH_PASSWORD"
            "NTFY_READER_PASSWORD"
          ]
      );
    };
    bazarr = {
      fileName = "bazarr.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        BAZARR_API_KEY = {
          unit = "bazarr";
          key = "API_KEY";
        };
        BAZARR_FLASK_SECRET_KEY = {
          unit = "bazarr";
          key = "FLASK_SECRET_KEY";
        };
        BAZARR_OPENSUBTITLES_PASS = {
          unit = "opensubtitles";
          key = "PASS";
        };
        BAZARR_SUBDL_API_KEY = {
          unit = "subdl";
          key = "API_KEY";
        };
        SONARR_API_KEY = {
          unit = "sonarr";
          key = "API_KEY";
        };
        RADARR_API_KEY = {
          unit = "radarr";
          key = "API_KEY";
        };
      };
    };

    chaptarr = {
      fileName = "chaptarr.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        CHAPTARR_API_KEY = {
          unit = "chaptarr";
          key = "API_KEY";
        };
      };
    };

    cloudflared = {
      fileName = "cloudflared.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        CLOUDFLARED_TUNNEL_TOKEN = {
          unit = "cloudflare";
          key = "TUNNEL_TOKEN";
        };
        CLOUDFLARED_ACCOUNT_ID = {
          unit = "cloudflare";
          key = "ACCOUNT_ID";
        };
        CLOUDFLARED_TUNNEL_ID = {
          unit = "cloudflare";
          key = "TUNNEL_ID";
        };
      };
    };

    cloudflare-management = {
      fileName = "cloudflare-management.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        CLOUDFLARED_ACCOUNT_ID = {
          unit = "cloudflare";
          key = "ACCOUNT_ID";
        };
        CLOUDFLARED_TUNNEL_ID = {
          unit = "cloudflare";
          key = "TUNNEL_ID";
        };
        CLOUDFLARED_API_TOKEN = {
          unit = "cloudflare";
          key = "API_TOKEN";
        };
      };
    };

    cloudflared-runtime = {
      fileName = "cloudflared-runtime.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        TUNNEL_TOKEN = {
          unit = "cloudflare";
          key = "TUNNEL_TOKEN";
        };
      };
    };

    dockerhub = {
      fileName = "dockerhub.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        DOCKERHUB_USER = {
          unit = "dockerhub";
          key = "USER";
        };
        DOCKERHUB_TOKEN = {
          unit = "dockerhub";
          key = "TOKEN";
        };
      };
    };

    emulation-retroachievements = {
      fileName = "emulation-retroachievements.env";
      owner = "kiosk";
      group = "kiosk";
      mode = "0440";
      fields = {
        RETROACHIEVEMENTS_USER = {
          unit = "retroachievements";
          key = "USER";
        };
        RETROACHIEVEMENTS_PASS = {
          unit = "retroachievements";
          key = "PASS";
        };
        RETROACHIEVEMENTS_TOKEN = {
          unit = "retroachievements";
          key = "TOKEN";
        };
      };
    };

    emulation-scraper = {
      fileName = "emulation-scraper.env";
      owner = "kiosk";
      group = "kiosk";
      mode = "0440";
      fields = {
        SCREENSCRAPER_USER = {
          unit = "screenscraper";
          key = "USER";
        };
        SCREENSCRAPER_PASS = {
          unit = "screenscraper";
          key = "PASS";
        };
      };
    };

    gluetun = {
      fileName = "gluetun.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        OPENVPN_USER = {
          unit = "vpn";
          key = "OPENVPN_USER";
        };
        OPENVPN_PASS = {
          unit = "vpn";
          key = "OPENVPN_PASS";
        };
        HTTP_CONTROL_SERVER_API_KEY = {
          unit = "gluetun";
          key = "HTTP_CONTROL_SERVER_API_KEY";
        };
      };
    };

    grimmory = {
      fileName = "grimmory.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        GRIMMORY_DB_USER = {
          unit = "grimmory";
          key = "DB_USER";
        };
        GRIMMORY_DB_PASS = {
          unit = "grimmory";
          key = "DB_PASS";
        };
        GRIMMORY_USER = {
          unit = "grimmory";
          key = "USER";
        };
        GRIMMORY_PASS = {
          unit = "grimmory";
          key = "PASS";
        };
      };
    };

    grimmory-db = {
      fileName = "grimmory-db.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        GRIMMORY_DB_USER = {
          unit = "grimmory";
          key = "DB_USER";
        };
        GRIMMORY_DB_PASS = {
          unit = "grimmory";
          key = "DB_PASS";
        };
        GRIMMORY_MYSQL_ROOT_PASS = {
          unit = "grimmory";
          key = "MYSQL_ROOT_PASS";
        };
      };
    };

    homepage = {
      fileName = "homepage.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        HTTP_CONTROL_SERVER_API_KEY = {
          unit = "gluetun";
          key = "HTTP_CONTROL_SERVER_API_KEY";
        };
        PLEX_API_KEY = {
          unit = "plex";
          key = "API_KEY";
        };
        TAUTULLI_API_KEY = {
          unit = "tautulli";
          key = "API_KEY";
        };
        SONARR_API_KEY = {
          unit = "sonarr";
          key = "API_KEY";
        };
        RADARR_API_KEY = {
          unit = "radarr";
          key = "API_KEY";
        };
        PROWLARR_API_KEY = {
          unit = "prowlarr";
          key = "API_KEY";
        };
        BAZARR_API_KEY = {
          unit = "bazarr";
          key = "API_KEY";
        };
        CHAPTARR_API_KEY = {
          unit = "chaptarr";
          key = "API_KEY";
        };
        CLOUDFLARED_ACCOUNT_ID = {
          unit = "cloudflare";
          key = "ACCOUNT_ID";
        };
        CLOUDFLARED_TUNNEL_ID = {
          unit = "cloudflare";
          key = "TUNNEL_ID";
        };
        GRIMMORY_USER = {
          unit = "grimmory";
          key = "USER";
        };
        GRIMMORY_PASS = {
          unit = "grimmory";
          key = "PASS";
        };
      };
    };

    nzbget = {
      fileName = "nzbget.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        NZBGET_SERVER1_USER = {
          unit = "usenet";
          key = "NZBGET_SERVER1_USER";
        };
        NZBGET_SERVER1_PASS = {
          unit = "usenet";
          key = "NZBGET_SERVER1_PASS";
        };
      };
    };

    agent-desktop = {
      fileName = "agent-desktop.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields.AGENT_DESKTOP_API_TOKEN = {
        unit = "agent-desktop";
        key = "API_TOKEN";
      };
    };
    t3code = {
      fileName = "t3code.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        GROQ_API_KEY = {
          unit = "groq";
          key = "API_KEY";
        };
        GOOGLE_GENERATIVE_AI_API_KEY = {
          unit = "google-ai-studio";
          key = "API_KEY";
        };
        NVIDIA_API_KEY = {
          unit = "nvidia";
          key = "API_KEY";
        };
        HF_TOKEN = {
          unit = "huggingface";
          key = "TOKEN";
        };
        COHERE_API_KEY = {
          unit = "cohere";
          key = "API_KEY";
        };
        AI_GATEWAY_API_KEY = {
          unit = "vercel-ai-gateway";
          key = "API_KEY";
        };
        CLOUDFLARE_WORKERS_AI_API_KEY = {
          unit = "cloudflare-workers-ai";
          key = "API_KEY";
        };
        CLOUDFLARE_ACCOUNT_ID = {
          unit = "cloudflare-workers-ai";
          key = "ACCOUNT_ID";
        };
        OLLAMA_API_KEY = {
          unit = "ollama";
          key = "API_KEY";
        };
        OPENROUTER_API_KEY = {
          unit = "openrouter";
          key = "API_KEY";
        };
        KILO_API_KEY = {
          unit = "kilo";
          key = "API_KEY";
        };
        REQUESTY_API_KEY = {
          unit = "requesty";
          key = "API_KEY";
        };
        ORCAROUTER_API_KEY = {
          unit = "orcarouter";
          key = "API_KEY";
        };
        INCEPTION_API_KEY = {
          unit = "inception";
          key = "API_KEY";
        };
        MISTRAL_API_KEY = {
          unit = "mistral";
          key = "API_KEY";
        };
        UPSTAGE_API_KEY = {
          unit = "upstage";
          key = "API_KEY";
        };
        ZHIPU_API_KEY = {
          unit = "zai";
          key = "API_KEY";
        };
        POOLSIDE_API_KEY = {
          unit = "poolside";
          key = "API_KEY";
        };
        GITHUB_TOKEN = {
          unit = "github";
          key = "TOKEN";
        };
        BW_CLIENTID = {
          unit = "bitwarden";
          key = "BW_CLIENTID";
        };
        BW_CLIENTSECRET = {
          unit = "bitwarden";
          key = "BW_CLIENTSECRET";
        };
        BW_PASSWORD = {
          unit = "bitwarden";
          key = "BW_PASSWORD";
        };
        AGENT_DESKTOP_API_TOKEN = {
          unit = "agent-desktop";
          key = "API_TOKEN";
        };
      };
    };

    plex = {
      fileName = "plex.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        PLEX_CLAIM = {
          unit = "plex";
          key = "CLAIM";
        };
        PLEX_API_KEY = {
          unit = "plex";
          key = "API_KEY";
        };
        PLEX_TOKEN = {
          unit = "plex";
          key = "TOKEN";
        };
      };
    };

    prowlarr = {
      fileName = "prowlarr.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        PROWLARR_API_KEY = {
          unit = "prowlarr";
          key = "API_KEY";
        };
      };
    };

    pyload = {
      fileName = "pyload.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        PYLOAD_API_KEY = {
          unit = "pyload";
          key = "API_KEY";
        };
      };
    };

    radarr = {
      fileName = "radarr.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        RADARR_API_KEY = {
          unit = "radarr";
          key = "API_KEY";
        };
      };
    };

    recyclarr = {
      fileName = "recyclarr.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        SONARR_API_KEY = {
          unit = "sonarr";
          key = "API_KEY";
        };
        RADARR_API_KEY = {
          unit = "radarr";
          key = "API_KEY";
        };
      };
    };

    romm = {
      fileName = "romm.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        ROMM_DB_USER = {
          unit = "romm";
          key = "DB_USER";
        };
        ROMM_DB_PASS = {
          unit = "romm";
          key = "DB_PASS";
        };
        ROMM_USER = {
          unit = "romm";
          key = "USER";
        };
        ROMM_PASS = {
          unit = "romm";
          key = "PASS";
        };
        ROMM_AUTH_SECRET = {
          unit = "romm";
          key = "AUTH_SECRET";
        };
        ROMM_IGDB_CLIENT_ID = {
          unit = "igdb";
          key = "CLIENT_ID";
        };
        ROMM_IGDB_CLIENT_SECRET = {
          unit = "igdb";
          key = "CLIENT_SECRET";
        };
        ROMM_RETROACHIEVEMENTS_API_KEY = {
          unit = "retroachievements";
          key = "API_KEY";
        };
        ROMM_STEAMGRIDDB_API_KEY = {
          unit = "steamgriddb";
          key = "API_KEY";
        };
        ROMM_SCREENSCRAPER_USER = {
          unit = "screenscraper";
          key = "USER";
        };
        ROMM_SCREENSCRAPER_PASS = {
          unit = "screenscraper";
          key = "PASS";
        };
      };
    };

    romm-db = {
      fileName = "romm-db.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        MYSQL_ROOT_PASSWORD = {
          unit = "romm-db-admin";
          key = "MYSQL_ROOT_PASSWORD";
        };
        ROMM_DB_USER = {
          unit = "romm";
          key = "DB_USER";
        };
        ROMM_DB_PASS = {
          unit = "romm";
          key = "DB_PASS";
        };
      };
    };

    sonarr = {
      fileName = "sonarr.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        SONARR_API_KEY = {
          unit = "sonarr";
          key = "API_KEY";
        };
      };
    };

    tautulli = {
      fileName = "tautulli.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        TAUTULLI_API_KEY = {
          unit = "tautulli";
          key = "API_KEY";
        };
        PLEX_TOKEN = {
          unit = "plex";
          key = "TOKEN";
        };
      };
    };

  };
}
