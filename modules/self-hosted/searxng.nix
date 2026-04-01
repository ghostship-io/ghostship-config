{ config, lib, pkgs, ... }:

let
  searxng-secrets = config.sops.secrets."searxng-secrets".path;
  searxng-pypi-engine = pkgs.writeText "searxng-pypi.py" ''
    # SPDX-License-Identifier: AGPL-3.0-or-later
    """PyPI exact-match package lookup via the JSON API."""

    from urllib.parse import quote

    from dateutil import parser
    from searx.network import raise_for_httperror

    about = {
        'website': 'https://pypi.org',
        'wikidata_id': 'Q2984686',
        'official_api_documentation': 'https://docs.pypi.org/api/json/',
        'use_official_api': True,
        'require_api_key': False,
        'results': 'JSON',
    }

    categories = ['it', 'packages']
    paging = False
    base_url = 'https://pypi.org'


    def request(query, params):
        package_name = query.strip()
        params['package_name'] = package_name
        params['url'] = f"{base_url}/pypi/{quote(package_name)}/json"
        params['raise_for_httperror'] = False
        return params


    def response(resp):
        if resp.status_code == 404:
            return []

        raise_for_httperror(resp)

        payload = resp.json()
        info = payload.get('info', {})
        urls = payload.get('urls') or []
        release_url = info.get('package_url')

        published_date = None
        for artifact in urls:
            upload_time = artifact.get('upload_time_iso_8601') or artifact.get('upload_time')
            if upload_time:
                published_date = parser.parse(upload_time)
                break

        return [
            {
                'template': 'packages.html',
                'url': release_url or f"{base_url}/project/{info.get('name', resp.search_params['package_name'])}/",
                'title': info.get('name', resp.search_params['package_name']),
                'package_name': info.get('name', resp.search_params['package_name']),
                'content': info.get('summary') or "",
                'version': info.get('version'),
                'homepage': info.get('home_page') or info.get('project_url'),
                'license_name': info.get('license') or "",
                'publishedDate': published_date,
            }
        ]
  '';
  mkEngine = name: extra: {
    inherit name;
    disabled = false;
    inactive = false;
  } // extra;
  searxng-keep-only = [
    # General / web / context
    "brave"
    "bing"
    "google"
    "hackernews"
    "mojeek"
    "reddit"
    "wikidata"
    "wikipedia"

    # News
    "brave.news"
    "duckduckgo news"
    "google news"
    "reuters"
    "wikinews"

    # Images / video / media
    "brave.images"
    "brave.videos"
    "dailymotion"
    "deviantart"
    "duckduckgo images"
    "duckduckgo videos"
    "google images"
    "google videos"
    "mixcloud"
    "mojeek images"
    "openverse"
    "radio browser"
    "sepiasearch"
    "soundcloud"
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
    "apple maps"
    "currency"
    "dictzone"
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
    "devicons"
    "fdroid"
    "github"
    "gitea.com"
    "gitlab"
    "google play apps"
    "hex"
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
    "repology"
    "rubygems"
    "selfhst icons"
    "sourcehut"
    "stackoverflow"
    "superuser"
    "voidlinux"

    # Files / books / torrents / max-open surfaces
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
    "moviepilot"
    "rottentomatoes"
    "tmdb"
  ];
  searxng-engine-overrides = [
    # Helper / utility engines should stay out of general search.
    (mkEngine "currency" { categories = [ "currency" ]; })
    (mkEngine "ddg definitions" { categories = [ "define" "dictionaries" ]; })
    (mkEngine "dictzone" { categories = [ "translate" "dictionaries" ]; })
    (mkEngine "etymonline" { categories = [ "dictionaries" ]; })
    (mkEngine "lingva" { categories = [ "translate" ]; })
    (mkEngine "mymemory translated" { categories = [ "translate" ]; })
    (mkEngine "openmeteo" { categories = [ "weather" ]; })

    # Emphasize broader and less-filtered discovery engines.
    (mkEngine "arxiv" { weight = 4; })
    (mkEngine "alpine linux packages" { categories = [ "packages" ]; weight = 6; timeout = 8.0; })
    (mkEngine "apple maps" { categories = [ "map" ]; weight = 3; timeout = 5.0; })
    (mkEngine "arch linux wiki" { categories = [ "software wikis" "it" ]; weight = 4; timeout = 5.0; })
    (mkEngine "bing" { categories = [ "general" "web" ]; weight = 1; timeout = 5.0; })
    (mkEngine "bt4g" { weight = 3; categories = [ "files" ]; })
    (mkEngine "brave" { weight = 4; timeout = 4.0; })
    (mkEngine "brave.images" { weight = 3; timeout = 4.0; })
    (mkEngine "brave.news" { weight = 3; categories = [ "news" ]; timeout = 4.0; })
    (mkEngine "brave.videos" { weight = 3; timeout = 4.0; })
    (mkEngine "devicons" { categories = [ "icons" ]; weight = 3; timeout = 8.0; })
    (mkEngine "duckduckgo images" { weight = 3; timeout = 5.0; })
    (mkEngine "duckduckgo news" { weight = 4; categories = [ "news" ]; timeout = 5.0; })
    (mkEngine "duckduckgo videos" { weight = 3; timeout = 5.0; })
    (mkEngine "erowid" { categories = [ "other" ]; weight = 5; timeout = 8.0; })
    (mkEngine "cachy os packages" { categories = [ "it" ]; weight = 1; timeout = 5.0; })
    (mkEngine "crates.io" { categories = [ "it" ]; weight = 1; timeout = 5.0; })
    (mkEngine "fdroid" { categories = [ "apps" ]; weight = 2; timeout = 8.0; })
    (mkEngine "github" { weight = 4; categories = [ "repos" "it" ]; })
    (mkEngine "google" { weight = 1; categories = [ "general" "web" "it" ]; })
    (mkEngine "google images" { weight = 1; })
    (mkEngine "google news" { weight = 5; categories = [ "news" ]; timeout = 5.0; })
    (mkEngine "google play apps" { categories = [ "apps" ]; weight = 4; timeout = 8.0; })
    (mkEngine "google scholar" { weight = 2; timeout = 5.0; })
    (mkEngine "google videos" { weight = 1; })
    (mkEngine "hackernews" { weight = 3; categories = [ "q&a" "it" ]; })
    (mkEngine "hex" { categories = [ "it" ]; weight = 1; timeout = 5.0; })
    (mkEngine "imdb" { categories = [ "movies" ]; weight = 5; timeout = 5.0; })
    (mkEngine "lucide" { categories = [ "icons" ]; weight = 3; timeout = 8.0; })
    (mkEngine "material icons" { categories = [ "icons" ]; weight = 4; timeout = 8.0; })
    (mkEngine "mojeek" { weight = 3; timeout = 5.0; })
    (mkEngine "mojeek images" { weight = 2; timeout = 5.0; })
    (mkEngine "moviepilot" { categories = [ "movies" ]; weight = 2; timeout = 5.0; })
    (mkEngine "nixos wiki" { categories = [ "software wikis" ]; weight = 4; timeout = 5.0; })
    (mkEngine "lib.rs" { categories = [ "it" ]; weight = 1; timeout = 5.0; })
    (mkEngine "npm" { categories = [ "packages" ]; weight = 3; timeout = 8.0; })
    (mkEngine "openairepublications" { weight = 2; })
    (mkEngine "openverse" { weight = 3; })
    (mkEngine "openstreetmap" { categories = [ "map" ]; weight = 4; })
    (mkEngine "photon" { categories = [ "map" ]; weight = 2; })
    (mkEngine "packagist" { categories = [ "it" ]; weight = 1; timeout = 5.0; })
    (mkEngine "pkg.go.dev" { categories = [ "it" ]; weight = 1; timeout = 5.0; })
    (mkEngine "pub.dev" { categories = [ "it" ]; weight = 1; timeout = 5.0; })
    (mkEngine "pypi" { categories = [ "packages" ]; weight = 10; timeout = 8.0; })
    (mkEngine "reddit" { weight = 2; categories = [ "social media" "general" ]; })
    (mkEngine "repology" { categories = [ "packages" ]; weight = 8; timeout = 8.0; })
    (mkEngine "reuters" { weight = 6; categories = [ "news" ]; timeout = 5.0; })
    (mkEngine "rottentomatoes" { categories = [ "movies" ]; weight = 4; timeout = 5.0; })
    (mkEngine "rubygems" { categories = [ "it" ]; weight = 1; timeout = 5.0; })
    (mkEngine "sepiasearch" { weight = 3; })
    (mkEngine "selfhst icons" { categories = [ "icons" ]; weight = 4; timeout = 8.0; })
    (mkEngine "soundcloud" { categories = [ "music" ]; weight = 5; timeout = 8.0; })
    (mkEngine "stackoverflow" { weight = 3; categories = [ "q&a" "it" ]; })
    (mkEngine "tmdb" { categories = [ "movies" ]; weight = 3; timeout = 5.0; })
    (mkEngine "voidlinux" { categories = [ "it" ]; weight = 1; timeout = 5.0; })
    (mkEngine "wikipedia" { categories = [ "general" ]; weight = 7; timeout = 8.0; })
    (mkEngine "wikidata" { categories = [ "general" ]; weight = 2; timeout = 5.0; })
    (mkEngine "wikicommons.audio" { categories = [ "music" "wikimedia" ]; weight = 2; timeout = 5.0; })
    (mkEngine "wikicommons.files" { weight = 2; categories = [ "files" "wikimedia" ]; })
    (mkEngine "wikicommons.images" { weight = 2; categories = [ "images" "wikimedia" ]; })
    (mkEngine "wikicommons.videos" { categories = [ "videos" "wikimedia" ]; weight = 2; timeout = 5.0; })
    (mkEngine "youtube" { weight = 6; categories = [ "videos" "music" ]; timeout = 5.0; })

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
    "search.autocomplete=yaml:${builtins.toJSON "bing"}"
    "search.formats=yaml:${builtins.toJSON [ "html" "json" ]}"

    "server.port=yaml:${builtins.toJSON 8080}"
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
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:8080/config || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      SEARXNG_PORT = "8080";
      GRANIAN_PORT = "8080";
    };
    volumes = [
      "/srv/apps/searxng:/etc/searxng:rw"
      "${searxng-pypi-engine}:/usr/local/searxng/searx/engines/pypi.py:ro"
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
