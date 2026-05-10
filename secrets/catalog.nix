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
        "BWS_ACCESS_TOKEN"
        "BW_CLIENTID"
        "BW_CLIENTSECRET"
        "BW_PASSWORD"
      ];
    };

    bookstack = mkUnit {
      relativeFile = "secrets/files/sources/services/bookstack.env.age";
      exports = [
        "APP_KEY"
        "APP_URL"
        "DB_DATABASE"
        "DB_USER"
        "DB_PASS"
        "DB_ROOT_PASS"
        "TOKEN_ID"
        "TOKEN_SECRET"
      ];
    };

    changedetection = mkUnit {
      relativeFile = "secrets/files/sources/services/changedetection.env.age";
      exports = [ "API_KEY" ];
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

    electron-hub = mkUnit {
      relativeFile = "secrets/files/sources/services/electron-hub.env.age";
      exports = [ "API_KEY" ];
    };

    firecrawl = mkUnit {
      relativeFile = "secrets/files/sources/services/firecrawl.env.age";
      exports = [
        "POSTGRES_PASSWORD"
        "BULL_AUTH_KEY"
        "API_KEY"
      ];
    };

    github = mkUnit {
      relativeFile = "secrets/files/sources/providers/github.env.age";
      exports = [ "TOKEN" ];
    };

    gluetun = mkUnit {
      relativeFile = "secrets/files/sources/services/gluetun.env.age";
      exports = [ "HTTP_CONTROL_SERVER_API_KEY" ];
    };

    google-ai-studio = mkUnit {
      relativeFile = "secrets/files/sources/providers/google-ai-studio.env.age";
      exports = [ "API_KEY" ];
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

    n8n = mkUnit {
      relativeFile = "secrets/files/sources/services/n8n.env.age";
      exports = [ "API_KEY" ];
    };

    nvidia-build = mkUnit {
      relativeFile = "secrets/files/sources/providers/nvidia-build.env.age";
      exports = [ "API_KEY" ];
    };

    ollama = mkUnit {
      relativeFile = "secrets/files/sources/providers/ollama.env.age";
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

    pricebuddy = mkUnit {
      relativeFile = "secrets/files/sources/services/pricebuddy.env.age";
      exports = [
        "APP_USER_EMAIL"
        "APP_USER_PASSWORD"
        "DB_USER"
        "DB_PASS"
        "MYSQL_ROOT_PASS"
        "APP_KEY"
        "API_TOKEN"
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

    searxng = mkUnit {
      relativeFile = "secrets/files/sources/services/searxng.env.age";
      exports = [ "SECRET_KEY" ];
    };

    smb = mkUnit {
      relativeFile = "secrets/files/sources/storage/smb.env.age";
      exports = [
        "USER"
        "PASS"
        "SERVER"
        "SHARE"
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

    zenmux = mkUnit {
      relativeFile = "secrets/files/sources/services/zenmux.env.age";
      exports = [ "API_KEY" ];
    };

  };

  projections = {
    agent-zero = {
      fileName = "agent-zero.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        BW_CLIENT_ID = {
          unit = "bitwarden";
          key = "BW_CLIENTID";
        };
        BW_CLIENT_SECRET = {
          unit = "bitwarden";
          key = "BW_CLIENTSECRET";
        };
        BW_PASSWORD = {
          unit = "bitwarden";
          key = "BW_PASSWORD";
        };
        OLLAMA_CLOUD_API_KEY = {
          unit = "ollama";
          key = "API_KEY";
        };
        OPENCODE_GO_API_KEY = {
          unit = "opencode";
          key = "GO_API_KEY";
        };
        NVIDIA_BUILD_FREE_API_KEY = {
          unit = "nvidia-build";
          key = "API_KEY";
        };
        OPENCODE_ZEN_FREE_API_KEY = {
          unit = "opencode";
          key = "GO_API_KEY";
        };
        OPENROUTER_FREE_API_KEY = {
          unit = "openrouter";
          key = "API_KEY";
        };
      };
    };

    agent-zero-registry = {
      fileName = "agent-zero-registry.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        GITHUB_TOKEN = {
          unit = "github";
          key = "TOKEN";
        };
      };
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

    bookstack = {
      fileName = "bookstack.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        BOOKSTACK_APP_KEY = {
          unit = "bookstack";
          key = "APP_KEY";
        };
        BOOKSTACK_APP_URL = {
          unit = "bookstack";
          key = "APP_URL";
        };
        BOOKSTACK_DB_DATABASE = {
          unit = "bookstack";
          key = "DB_DATABASE";
        };
        BOOKSTACK_DB_USER = {
          unit = "bookstack";
          key = "DB_USER";
        };
        BOOKSTACK_DB_PASS = {
          unit = "bookstack";
          key = "DB_PASS";
        };
        BOOKSTACK_DB_ROOT_PASS = {
          unit = "bookstack";
          key = "DB_ROOT_PASS";
        };
        BOOKSTACK_TOKEN_ID = {
          unit = "bookstack";
          key = "TOKEN_ID";
        };
        BOOKSTACK_TOKEN_SECRET = {
          unit = "bookstack";
          key = "TOKEN_SECRET";
        };
      };
    };

    bookstack-db = {
      fileName = "bookstack-db.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        BOOKSTACK_DB_DATABASE = {
          unit = "bookstack";
          key = "DB_DATABASE";
        };
        BOOKSTACK_DB_USER = {
          unit = "bookstack";
          key = "DB_USER";
        };
        BOOKSTACK_DB_PASS = {
          unit = "bookstack";
          key = "DB_PASS";
        };
        BOOKSTACK_DB_ROOT_PASS = {
          unit = "bookstack";
          key = "DB_ROOT_PASS";
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

    firecrawl-runtime = {
      fileName = "firecrawl-runtime.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        OPENAI_API_KEY = {
          unit = "google-ai-studio";
          key = "API_KEY";
        };
        POSTGRES_PASSWORD = {
          unit = "firecrawl";
          key = "POSTGRES_PASSWORD";
        };
        BULL_AUTH_KEY = {
          unit = "firecrawl";
          key = "BULL_AUTH_KEY";
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

    hermes = {
      fileName = "hermes-shared.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        CHANGEDETECTION_API_KEY = {
          unit = "changedetection";
          key = "API_KEY";
        };
        SYNOLOGY_USER = {
          unit = "synology";
          key = "USER";
        };
        SYNOLOGY_PASS = {
          unit = "synology";
          key = "PASS";
        };
        N8N_API_KEY = {
          unit = "n8n";
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
        PLEX_TOKEN = {
          unit = "plex";
          key = "TOKEN";
        };
        TAUTULLI_API_KEY = {
          unit = "tautulli";
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
        BOOKSTACK_TOKEN_ID = {
          unit = "bookstack";
          key = "TOKEN_ID";
        };
        BOOKSTACK_TOKEN_SECRET = {
          unit = "bookstack";
          key = "TOKEN_SECRET";
        };
        FIRECRAWL_API_KEY = {
          unit = "firecrawl";
          key = "API_KEY";
        };
        PYLOAD_API_KEY = {
          unit = "pyload";
          key = "API_KEY";
        };
        ROMM_USERNAME = {
          unit = "romm";
          key = "USER";
        };
        ROMM_PASSWORD = {
          unit = "romm";
          key = "PASS";
        };
        GRIMMORY_USERNAME = {
          unit = "grimmory";
          key = "USER";
        };
        GRIMMORY_PASSWORD = {
          unit = "grimmory";
          key = "PASS";
        };
      };
    };

    hermes-secrets = {
      fileName = "hermes-secrets.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        GOOGLE_AI_STUDIO_API_KEY = {
          unit = "google-ai-studio";
          key = "API_KEY";
        };
        OPENCODE_GO_API_KEY = {
          unit = "opencode";
          key = "GO_API_KEY";
        };
        OPENCODE_ZEN_API_KEY = {
          unit = "opencode";
          key = "GO_API_KEY";
        };
        ZENMUX_API_KEY = {
          unit = "zenmux";
          key = "API_KEY";
        };
        ELECTRON_HUB_API_KEY = {
          unit = "electron-hub";
          key = "API_KEY";
        };
        OPENROUTER_API_KEY = {
          unit = "openrouter";
          key = "API_KEY";
        };
        BWS_ACCESS_TOKEN = {
          unit = "bitwarden";
          key = "BWS_ACCESS_TOKEN";
        };
        DISCORD_BOT_TOKEN = {
          unit = "discord";
          key = "BOT_TOKEN";
        };
        WEBHOOK_SECRET = {
          unit = "discord";
          key = "WEBHOOK_SECRET";
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
        GITHUB_TOKEN = {
          unit = "github";
          key = "TOKEN";
        };
        NVIDIA_BUILD_API_KEY = {
          unit = "nvidia-build";
          key = "API_KEY";
        };
        OLLAMA_API_KEY = {
          unit = "ollama";
          key = "API_KEY";
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
        CLOUDFLARED_API_TOKEN = {
          unit = "cloudflare";
          key = "API_TOKEN";
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

    n8n = {
      fileName = "n8n.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        N8N_API_KEY = {
          unit = "n8n";
          key = "API_KEY";
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

    pricebuddy = {
      fileName = "pricebuddy.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        PRICEBUDDY_APP_USER_EMAIL = {
          unit = "pricebuddy";
          key = "APP_USER_EMAIL";
        };
        PRICEBUDDY_APP_USER_PASSWORD = {
          unit = "pricebuddy";
          key = "APP_USER_PASSWORD";
        };
        PRICEBUDDY_DB_USER = {
          unit = "pricebuddy";
          key = "DB_USER";
        };
        PRICEBUDDY_DB_PASS = {
          unit = "pricebuddy";
          key = "DB_PASS";
        };
        PRICEBUDDY_MYSQL_ROOT_PASS = {
          unit = "pricebuddy";
          key = "MYSQL_ROOT_PASS";
        };
        PRICEBUDDY_APP_KEY = {
          unit = "pricebuddy";
          key = "APP_KEY";
        };
        PRICEBUDDY_API_TOKEN = {
          unit = "pricebuddy";
          key = "API_TOKEN";
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

    searxng = {
      fileName = "searxng.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        SEARXNG_SECRET_KEY = {
          unit = "searxng";
          key = "SECRET_KEY";
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
