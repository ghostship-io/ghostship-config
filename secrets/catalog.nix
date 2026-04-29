{ recipients }:

{
  units = {
    gluetun-secrets = {
      relativeFile = "secrets/files/services/gluetun-secrets.env.age";
      path = ./files/services/gluetun-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      owner = "apps";
      group = "apps";
      mode = "0440";
      format = "env";
      exports = [ "OPENVPN_USER" "OPENVPN_PASS" "HTTP_CONTROL_SERVER_API_KEY" ];
    };

    dockerhub-secrets = {
      relativeFile = "secrets/files/services/dockerhub-secrets.env.age";
      path = ./files/services/dockerhub-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "DOCKERHUB_USER" "DOCKERHUB_TOKEN" ];
    };

    smb-secrets = {
      relativeFile = "secrets/files/misc/smb-secrets.env.age";
      path = ./files/misc/smb-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "SMB_USER" "SMB_PASS" "SMB_SERVER" "SMB_SHARE" ];
    };

    cloudflared-secrets = {
      relativeFile = "secrets/files/services/cloudflared-secrets.env.age";
      path = ./files/services/cloudflared-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      owner = "apps";
      group = "apps";
      mode = "0440";
      format = "env";
      exports = [ "CLOUDFLARED_TUNNEL_TOKEN" "CLOUDFLARED_ACCOUNT_ID" "CLOUDFLARED_TUNNEL_ID" "CLOUDFLARED_API_TOKEN" ];
    };

    plex-secrets = {
      relativeFile = "secrets/files/services/plex-secrets.env.age";
      path = ./files/services/plex-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      owner = "apps";
      group = "apps";
      mode = "0440";
      format = "env";
      exports = [ "PLEX_CLAIM" "PLEX_API_KEY" "PLEX_TOKEN" ];
    };

    tautulli-secrets = {
      relativeFile = "secrets/files/services/tautulli-secrets.env.age";
      path = ./files/services/tautulli-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "TAUTULLI_API_KEY" ];
    };

    sonarr-secrets = {
      relativeFile = "secrets/files/services/sonarr-secrets.env.age";
      path = ./files/services/sonarr-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "SONARR_API_KEY" ];
    };

    radarr-secrets = {
      relativeFile = "secrets/files/services/radarr-secrets.env.age";
      path = ./files/services/radarr-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "RADARR_API_KEY" ];
    };

    prowlarr-secrets = {
      relativeFile = "secrets/files/services/prowlarr-secrets.env.age";
      path = ./files/services/prowlarr-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "PROWLARR_API_KEY" ];
    };

    romm-secrets = {
      relativeFile = "secrets/files/services/romm-secrets.env.age";
      path = ./files/services/romm-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "ROMM_DB_USER" "ROMM_DB_PASS" "ROMM_USER" "ROMM_PASS" "ROMM_AUTH_SECRET" "ROMM_IGDB_CLIENT_ID" "ROMM_IGDB_CLIENT_SECRET" "ROMM_RETROACHIEVEMENTS_API_KEY" "ROMM_STEAMGRIDDB_API_KEY" "ROMM_SCREENSCRAPER_USER" "ROMM_SCREENSCRAPER_PASS" ];
    };

    grimmory-secrets = {
      relativeFile = "secrets/files/services/grimmory-secrets.env.age";
      path = ./files/services/grimmory-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "GRIMMORY_DB_USER" "GRIMMORY_DB_PASS" "GRIMMORY_MYSQL_ROOT_PASS" "GRIMMORY_USER" "GRIMMORY_PASS" ];
    };

    bookstack-secrets = {
      relativeFile = "secrets/files/services/bookstack-secrets.env.age";
      path = ./files/services/bookstack-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [
        "BOOKSTACK_APP_KEY"
        "BOOKSTACK_APP_URL"
        "BOOKSTACK_DB_DATABASE"
        "BOOKSTACK_DB_USER"
        "BOOKSTACK_DB_PASS"
        "BOOKSTACK_DB_ROOT_PASS"
        "BOOKSTACK_TOKEN_ID"
        "BOOKSTACK_TOKEN_SECRET"
      ];
    };

    pricebuddy-secrets = {
      relativeFile = "secrets/files/services/pricebuddy-secrets.env.age";
      path = ./files/services/pricebuddy-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "PRICEBUDDY_APP_USER_EMAIL" "PRICEBUDDY_APP_USER_PASSWORD" "PRICEBUDDY_DB_USER" "PRICEBUDDY_DB_PASS" "PRICEBUDDY_MYSQL_ROOT_PASS" "PRICEBUDDY_APP_KEY" "PRICEBUDDY_API_TOKEN" ];
    };


    firecrawl-secrets = {
      relativeFile = "secrets/files/services/firecrawl-secrets.env.age";
      path = ./files/services/firecrawl-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "FIRECRAWL_OPENAI_API_KEY" "FIRECRAWL_POSTGRES_PASSWORD" "FIRECRAWL_BULL_AUTH_KEY" "FIRECRAWL_API_KEY" ];
    };

    searxng-secrets = {
      relativeFile = "secrets/files/services/searxng-secrets.env.age";
      path = ./files/services/searxng-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "SEARXNG_SECRET_KEY" ];
    };

    bazarr-secrets = {
      relativeFile = "secrets/files/services/bazarr-secrets.env.age";
      path = ./files/services/bazarr-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      owner = "apps";
      group = "apps";
      mode = "0440";
      format = "env";
      exports = [ "BAZARR_API_KEY" "BAZARR_FLASK_SECRET_KEY" "BAZARR_OPENSUBTITLES_PASS" "BAZARR_SUBDL_API_KEY" ];
    };

    nzbget-secrets = {
      relativeFile = "secrets/files/services/nzbget-secrets.env.age";
      path = ./files/services/nzbget-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "NZBGET_SERVER1_USER" "NZBGET_SERVER1_PASS" ];
    };

    n8n-secrets = {
      relativeFile = "secrets/files/services/n8n-secrets.env.age";
      path = ./files/services/n8n-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "N8N_API_KEY" ];
    };

    hermes-secrets = {
      relativeFile = "secrets/files/services/hermes-secrets.env.age";
      path = ./files/services/hermes-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "SYNOLOGY_USER" "SYNOLOGY_PASS" "GOOGLE_AI_STUDIO_API_KEY" "OPENCODE_GO_API_KEY" "OPENCODE_ZEN_API_KEY" "ZENMUX_API_KEY" "ELECTRON_HUB_API_KEY" "OPENROUTER_API_KEY" "BWS_ACCESS_TOKEN" "DISCORD_BOT_TOKEN" "WEBHOOK_SECRET" "CHANGEDETECTION_API_KEY" "BW_CLIENTID" "BW_CLIENTSECRET" "BW_PASSWORD" "GITHUB_TOKEN" "NVIDIA_BUILD_API_KEY" ];
    };

    pyload-secrets = {
      relativeFile = "secrets/files/services/pyload-secrets.env.age";
      path = ./files/services/pyload-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "PYLOAD_API_KEY" ];
    };

    chaptarr-secrets = {
      relativeFile = "secrets/files/services/chaptarr-secrets.env.age";
      path = ./files/services/chaptarr-secrets.env.age;
      recipientGroup = "self-hosted-runtime";
      recipients = recipients.groups.self-hosted-runtime;
      mode = "0400";
      format = "env";
      exports = [ "CHAPTARR_API_KEY" ];
    };

    emulation-scraper-secrets = {
      relativeFile = "secrets/files/services/emulation-scraper-secrets.env.age";
      path = ./files/services/emulation-scraper-secrets.env.age;
      recipientGroup = "emulation-runtime";
      recipients = recipients.groups.emulation-runtime;
      mode = "0400";
      format = "env";
      exports = [ "SCREENSCRAPER_USER" "SCREENSCRAPER_PASS" ];
    };
  };

  projections = {
    homepage = {
      fileName = "homepage.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        HTTP_CONTROL_SERVER_API_KEY = { unit = "gluetun-secrets"; key = "HTTP_CONTROL_SERVER_API_KEY"; };
        PLEX_API_KEY = { unit = "plex-secrets"; key = "PLEX_API_KEY"; };
        TAUTULLI_API_KEY = { unit = "tautulli-secrets"; key = "TAUTULLI_API_KEY"; };
        SONARR_API_KEY = { unit = "sonarr-secrets"; key = "SONARR_API_KEY"; };
        RADARR_API_KEY = { unit = "radarr-secrets"; key = "RADARR_API_KEY"; };
        PROWLARR_API_KEY = { unit = "prowlarr-secrets"; key = "PROWLARR_API_KEY"; };
        BAZARR_API_KEY = { unit = "bazarr-secrets"; key = "BAZARR_API_KEY"; };
        CHAPTARR_API_KEY = { unit = "chaptarr-secrets"; key = "CHAPTARR_API_KEY"; };
        CLOUDFLARED_ACCOUNT_ID = { unit = "cloudflared-secrets"; key = "CLOUDFLARED_ACCOUNT_ID"; };
        CLOUDFLARED_TUNNEL_ID = { unit = "cloudflared-secrets"; key = "CLOUDFLARED_TUNNEL_ID"; };
        CLOUDFLARED_API_TOKEN = { unit = "cloudflared-secrets"; key = "CLOUDFLARED_API_TOKEN"; };
        GRIMMORY_USER = { unit = "grimmory-secrets"; key = "GRIMMORY_USER"; };
        GRIMMORY_PASS = { unit = "grimmory-secrets"; key = "GRIMMORY_PASS"; };
      };
    };

    bazarr = {
      fileName = "bazarr.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        BAZARR_API_KEY = { unit = "bazarr-secrets"; key = "BAZARR_API_KEY"; };
        BAZARR_FLASK_SECRET_KEY = { unit = "bazarr-secrets"; key = "BAZARR_FLASK_SECRET_KEY"; };
        BAZARR_OPENSUBTITLES_PASS = { unit = "bazarr-secrets"; key = "BAZARR_OPENSUBTITLES_PASS"; };
        BAZARR_SUBDL_API_KEY = { unit = "bazarr-secrets"; key = "BAZARR_SUBDL_API_KEY"; };
        SONARR_API_KEY = { unit = "sonarr-secrets"; key = "SONARR_API_KEY"; };
        RADARR_API_KEY = { unit = "radarr-secrets"; key = "RADARR_API_KEY"; };
      };
    };

    recyclarr = {
      fileName = "recyclarr.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        SONARR_API_KEY = { unit = "sonarr-secrets"; key = "SONARR_API_KEY"; };
        RADARR_API_KEY = { unit = "radarr-secrets"; key = "RADARR_API_KEY"; };
      };
    };

    tautulli = {
      fileName = "tautulli.env";
      owner = "apps";
      group = "apps";
      mode = "0440";
      fields = {
        TAUTULLI_API_KEY = { unit = "tautulli-secrets"; key = "TAUTULLI_API_KEY"; };
        PLEX_TOKEN = { unit = "plex-secrets"; key = "PLEX_TOKEN"; };
      };
    };

    cloudflared-runtime = {
      fileName = "cloudflared-runtime.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        TUNNEL_TOKEN = { unit = "cloudflared-secrets"; key = "CLOUDFLARED_TUNNEL_TOKEN"; };
      };
    };


    firecrawl-runtime = {
      fileName = "firecrawl-runtime.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        OPENAI_API_KEY = { unit = "firecrawl-secrets"; key = "FIRECRAWL_OPENAI_API_KEY"; };
        POSTGRES_PASSWORD = { unit = "firecrawl-secrets"; key = "FIRECRAWL_POSTGRES_PASSWORD"; };
        BULL_AUTH_KEY = { unit = "firecrawl-secrets"; key = "FIRECRAWL_BULL_AUTH_KEY"; };
      };
    };

    hermes = {
      fileName = "hermes-shared.env";
      owner = "root";
      group = "root";
      mode = "0400";
      fields = {
        CHANGEDETECTION_API_KEY = { unit = "hermes-secrets"; key = "CHANGEDETECTION_API_KEY"; };
        SYNOLOGY_USER = { unit = "hermes-secrets"; key = "SYNOLOGY_USER"; };
        SYNOLOGY_PASS = { unit = "hermes-secrets"; key = "SYNOLOGY_PASS"; };
        N8N_API_KEY = { unit = "n8n-secrets"; key = "N8N_API_KEY"; };
        SONARR_API_KEY = { unit = "sonarr-secrets"; key = "SONARR_API_KEY"; };
        RADARR_API_KEY = { unit = "radarr-secrets"; key = "RADARR_API_KEY"; };
        PROWLARR_API_KEY = { unit = "prowlarr-secrets"; key = "PROWLARR_API_KEY"; };
        PLEX_TOKEN = { unit = "plex-secrets"; key = "PLEX_TOKEN"; };
        TAUTULLI_API_KEY = { unit = "tautulli-secrets"; key = "TAUTULLI_API_KEY"; };
        BAZARR_API_KEY = { unit = "bazarr-secrets"; key = "BAZARR_API_KEY"; };
        CHAPTARR_API_KEY = { unit = "chaptarr-secrets"; key = "CHAPTARR_API_KEY"; };
        BOOKSTACK_TOKEN_ID = { unit = "bookstack-secrets"; key = "BOOKSTACK_TOKEN_ID"; };
        BOOKSTACK_TOKEN_SECRET = { unit = "bookstack-secrets"; key = "BOOKSTACK_TOKEN_SECRET"; };
        FIRECRAWL_API_KEY = { unit = "firecrawl-secrets"; key = "FIRECRAWL_API_KEY"; };
        PYLOAD_API_KEY = { unit = "pyload-secrets"; key = "PYLOAD_API_KEY"; };
        ROMM_USERNAME = { unit = "romm-secrets"; key = "ROMM_USER"; };
        ROMM_PASSWORD = { unit = "romm-secrets"; key = "ROMM_PASS"; };
        GRIMMORY_USERNAME = { unit = "grimmory-secrets"; key = "GRIMMORY_USER"; };
        GRIMMORY_PASSWORD = { unit = "grimmory-secrets"; key = "GRIMMORY_PASS"; };
      };
    };

    emulation-scraper = {
      fileName = "emulation-scraper.env";
      owner = "kiosk";
      group = "kiosk";
      mode = "0440";
      fields = {
        SCREENSCRAPER_USER = { unit = "emulation-scraper-secrets"; key = "SCREENSCRAPER_USER"; };
        SCREENSCRAPER_PASS = { unit = "emulation-scraper-secrets"; key = "SCREENSCRAPER_PASS"; };
      };
    };
  };
}
