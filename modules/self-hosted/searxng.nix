{ config, lib, pkgs, ... }:

let
  searxng-secrets = config.sops.secrets."searxng-secrets".path;
  mkEngine = name: extra: { inherit name; disabled = false; } // extra;
  searxng-keep-only = [
    # General / web / context
    "duckduckgo"
    "google"
    "hackernews"
    "mojeek"
    "reddit"
    "startpage"
    "wikidata"
    "wikipedia"

    # News
    "duckduckgo news"
    "google news"
    "reuters"
    "startpage news"
    "wikinews"

    # Images / video / media
    "dailymotion"
    "deviantart"
    "duckduckgo images"
    "duckduckgo videos"
    "google images"
    "google videos"
    "mixcloud"
    "mojeek images"
    "mojeek news"
    "openverse"
    "radio browser"
    "sepiasearch"
    "soundcloud"
    "startpage images"
    "wikicommons.audio"
    "wikicommons.images"
    "wikicommons.videos"
    "youtube"

    # Science / knowledge
    "arxiv"
    "ddg definitions"
    "etymonline"
    "google scholar"
    "openairedatasets"
    "openairepublications"
    "pdbe"
    "pubmed"
    "wikibooks"
    "wiktionary"
    "wordnik"

    # Translation / dictionaries / weather / maps / misc helpers
    "currency"
    "dictzone"
    "duckduckgo weather"
    "lingva"
    "mymemory translated"
    "openmeteo"
    "openstreetmap"
    "photon"

    # IT / packages / repos / apps
    "alpine linux packages"
    "arch linux wiki"
    "askubuntu"
    "cachy os packages"
    "crates.io"
    "docker hub"
    "fdroid"
    "gentoo"
    "github"
    "gitea.com"
    "gitlab"
    "google play apps"
    "hex"
    "hoogle"
    "lib.rs"
    "lucide"
    "mankier"
    "material icons"
    "mdn"
    "nixos wiki"
    "npm"
    "packagist"
    "pkg.go.dev"
    "pub.dev"
    "pypi"
    "rubygems"
    "selfhst icons"
    "sourcehut"
    "stackoverflow"
    "superuser"
    "voidlinux"

    # Files / books / torrents / max-open surfaces
    "annas archive"
    "bt4g"
    "piratebay"
    "wikicommons.files"

    # Social / fringe
    "erowid"
    "lemmy comments"
    "lemmy communities"
    "lemmy posts"
    "lemmy users"
    "mastodon hashtags"
    "mastodon users"

    # Movies / shopping
    "imdb"
    "rottentomatoes"
    "tmdb"
  ];
  searxng-engine-overrides = [
    # Helper / utility engines should stay out of general search.
    (mkEngine "currency" { categories = [ "currency" ]; })
    (mkEngine "ddg definitions" { categories = [ "define" "dictionaries" ]; })
    (mkEngine "dictzone" { categories = [ "translate" "dictionaries" ]; })
    (mkEngine "duckduckgo weather" { categories = [ "weather" ]; })
    (mkEngine "etymonline" { categories = [ "dictionaries" ]; })
    (mkEngine "lingva" { categories = [ "translate" ]; })
    (mkEngine "mymemory translated" { categories = [ "translate" ]; })
    (mkEngine "openmeteo" { categories = [ "weather" ]; })

    # Emphasize broader and less-filtered discovery engines.
    (mkEngine "annas archive" { weight = 4; categories = [ "files" "books" ]; })
    (mkEngine "arxiv" { weight = 4; })
    (mkEngine "bt4g" { weight = 3; categories = [ "files" ]; })
    (mkEngine "duckduckgo" { categories = [ ]; timeout = 5.0; weight = 1; })
    (mkEngine "duckduckgo images" { weight = 3; timeout = 5.0; })
    (mkEngine "duckduckgo news" { weight = 3; timeout = 5.0; })
    (mkEngine "duckduckgo videos" { weight = 3; timeout = 5.0; })
    (mkEngine "fdroid" { categories = [ "apps" "packages" ]; })
    (mkEngine "github" { weight = 4; categories = [ "repos" "it" ]; })
    (mkEngine "google" { weight = 1; })
    (mkEngine "google images" { weight = 1; })
    (mkEngine "google news" { weight = 1; })
    (mkEngine "google scholar" { weight = 2; timeout = 5.0; })
    (mkEngine "google videos" { weight = 1; })
    (mkEngine "hackernews" { weight = 3; categories = [ "q&a" "it" ]; })
    (mkEngine "mojeek" { weight = 3; timeout = 5.0; })
    (mkEngine "mojeek images" { weight = 2; timeout = 5.0; })
    (mkEngine "mojeek news" { weight = 2; timeout = 5.0; })
    (mkEngine "openairepublications" { weight = 2; })
    (mkEngine "openverse" { weight = 3; })
    (mkEngine "reddit" { weight = 3; categories = [ "social media" "general" ]; })
    (mkEngine "reuters" { weight = 4; categories = [ "news" ]; })
    (mkEngine "sepiasearch" { weight = 3; })
    (mkEngine "stackoverflow" { weight = 3; categories = [ "q&a" "it" ]; })
    (mkEngine "startpage" { weight = 2; timeout = 5.0; })
    (mkEngine "startpage images" { weight = 2; timeout = 5.0; })
    (mkEngine "startpage news" { weight = 2; timeout = 5.0; })
    (mkEngine "wikicommons.files" { weight = 2; categories = [ "files" "wikimedia" ]; })
    (mkEngine "wikicommons.images" { weight = 2; categories = [ "images" "wikimedia" ]; })
    (mkEngine "youtube" { weight = 4; categories = [ "videos" "music" ]; })

    # Default-off engines that are useful for agentic search when healthy.
    (mkEngine "gitlab" { categories = [ "repos" "it" ]; })
    (mkEngine "gitea.com" { categories = [ "repos" "it" ]; })
    (mkEngine "lemmy comments" { categories = [ "social media" ]; })
    (mkEngine "lemmy communities" { categories = [ "social media" ]; })
    (mkEngine "lemmy posts" { categories = [ "social media" ]; })
    (mkEngine "lemmy users" { categories = [ "social media" ]; })
    (mkEngine "mastodon hashtags" { categories = [ "social media" ]; })
    (mkEngine "mastodon users" { categories = [ "social media" ]; })
    (mkEngine "openstreetmap" { categories = [ "map" ]; })
    (mkEngine "photon" { categories = [ "map" ]; })
    (mkEngine "sourcehut" { categories = [ "repos" "it" ]; })
  ];
  searxng-patches = [
    "server.secret_key=env:SEARXNG_SECRET_KEY"

    "general.instance_name=yaml:${builtins.toJSON "Ghostship Search"}"

    "search.safe_search=yaml:${builtins.toJSON 0}"
    "search.autocomplete=yaml:${builtins.toJSON "duckduckgo"}"
    "search.formats=yaml:${builtins.toJSON [ "html" "json" ]}"

    "server.port=yaml:${builtins.toJSON 5002}"
    "server.bind_address=yaml:${builtins.toJSON "0.0.0.0"}"
    "server.image_proxy=yaml:${builtins.toJSON true}"
    "server.limiter=yaml:${builtins.toJSON false}"

    "outgoing.request_timeout=yaml:${builtins.toJSON 4.0}"
    "outgoing.max_request_timeout=yaml:${builtins.toJSON 8.0}"
    "outgoing.pool_connections=yaml:${builtins.toJSON 100}"
    "outgoing.pool_maxsize=yaml:${builtins.toJSON 20}"
    "outgoing.keepalive_expiry=yaml:${builtins.toJSON 10.0}"

    "valkey.url=yaml:${builtins.toJSON "valkey://searxng-valkey:6379/0"}"

    "use_default_settings.engines.keep_only=yaml:${builtins.toJSON searxng-keep-only}"
    "engines=yaml:${builtins.toJSON searxng-engine-overrides}"

    "plugins[searx.plugins.calculator.SXNGPlugin].active=yaml:${builtins.toJSON true}"
    "plugins[searx.plugins.hash_plugin.SXNGPlugin].active=yaml:${builtins.toJSON true}"
    "plugins[searx.plugins.self_info.SXNGPlugin].active=yaml:${builtins.toJSON true}"
    "plugins[searx.plugins.tracker_url_remover.SXNGPlugin].active=yaml:${builtins.toJSON true}"
    "plugins[searx.plugins.unit_converter.SXNGPlugin].active=yaml:${builtins.toJSON true}"
    "plugins[searx.plugins.oa_doi_rewrite.SXNGPlugin].active=yaml:${builtins.toJSON true}"
  ];
in
{
  virtualisation.oci-containers.containers."searxng" = {
    image = "docker.io/searxng/searxng:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:5002/config || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      SEARXNG_PORT = "5002";
      GRANIAN_PORT = "5002";
    };
    volumes = [
      "/srv/apps/searxng:/etc/searxng:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/searxng 0755 apps apps -"
  ];

  systemd.services.podman-searxng.preStart = ''
    CONFIG_DIR="/srv/apps/searxng"
    SETTINGS_FILE="$CONFIG_DIR/settings.yml"
    SECRETS_FILE="${searxng-secrets}"

    if [ ! -f "$SECRETS_FILE" ]; then
      echo "Waiting for SearXNG secrets at ${searxng-secrets}..."
      for _ in $(seq 1 30); do
        if [ -f "$SECRETS_FILE" ]; then
          break
        fi
        sleep 1
      done
    fi

    if [ ! -f "$SECRETS_FILE" ]; then
      echo "Missing SearXNG secrets file at ${searxng-secrets}" >&2
      exit 1
    fi

    if [ ! -f "$SETTINGS_FILE" ]; then
      echo "Missing SearXNG settings file at $SETTINGS_FILE" >&2
      exit 1
    fi

    echo "Surgically updating SearXNG settings..."
    set -a
    . "$SECRETS_FILE"
    set +a

    if [ -z "''${SEARXNG_SECRET_KEY:-}" ]; then
      SEARXNG_SECRET_KEY=$(${pkgs.openssl}/bin/openssl rand -hex 32)
    fi
    export SEARXNG_SECRET_KEY

    ${pkgs.ghostship-config}/bin/ghostship-config delete "$SETTINGS_FILE" \
      --allow-missing \
      use_default_settings \
      engines

    searx_args=(
      --secrets-file "$SECRETS_FILE"
${lib.concatStringsSep "\n" (map lib.escapeShellArg searxng-patches)}
    )

    ${pkgs.ghostship-config}/bin/ghostship-config set "$SETTINGS_FILE" "''${searx_args[@]}"

    chown 3000:3000 "$SETTINGS_FILE"
  '';
}
