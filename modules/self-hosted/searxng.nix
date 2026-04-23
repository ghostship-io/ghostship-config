{ config, lib, pkgs, ... }:

let
  searxng-secrets = config.ghostship.selfHostedSecrets.units."searxng-secrets".path;
  searxng-config-dir = "/srv/apps/searxng";
  searxng-cache-dir = "/srv/apps/searxng-cache";
  limiter-enabled = true;
  searxng-pypi-engine = pkgs.writeText "searxng-pypi_exact.py" ''
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
  searxng-wttr-engine = pkgs.writeText "searxng-wttr_exact.py" ''
    # SPDX-License-Identifier: AGPL-3.0-or-later
    """wttr.in weather lookup with a plain JSON parser."""

    from urllib.parse import quote

    from searx.network import raise_for_httperror

    about = {
        'website': 'https://wttr.in',
        'wikidata_id': 'Q107586666',
        'official_api_documentation': 'https://github.com/chubin/wttr.in#json-output',
        'use_official_api': True,
        'require_api_key': False,
        'results': 'JSON',
    }

    categories = ['weather']
    paging = False
    base_url = 'https://wttr.in'


    def request(query, params):
        params['query'] = query.strip()
        params['url'] = f"{base_url}/{quote(params['query'])}?format=j1&lang=en"
        params['raise_for_httperror'] = False
        return params


    def response(resp):
        if resp.status_code == 404:
            return []

        raise_for_httperror(resp)

        payload = resp.json()
        current = (payload.get('current_condition') or [{}])[0]
        title = f"{resp.search_params['query']} weather"
        desc = current.get('weatherDesc') or [{}]
        condition = (desc[0].get('value') if desc else None) or 'Unknown'
        content = (
            f"{condition}; {current.get('temp_C', '?')} C; "
            f"feels like {current.get('FeelsLikeC', '?')} C; "
            f"humidity {current.get('humidity', '?')}%; "
            f"wind {current.get('windspeedKmph', '?')} km/h"
        )

        return [
            {
                'url': f"{base_url}/{quote(resp.search_params['query'])}",
                'title': title,
                'content': content,
            }
        ]
  '';
  mkEngine = name: extra: {
    inherit name;
    disabled = false;
    inactive = false;
  } // extra;
  promoted-web-pool = [
    "startpage"
    "qwant"
    "mojeek"
    "presearch"
    "wikipedia"
    "wikidata"
  ];
  tech-pool = [
    "arch linux wiki"
    "nixos wiki"
    "askubuntu"
    "stackoverflow"
    "superuser"
    "mankier"
    "mdn"
    "github"
    "gitlab"
    "gitea.com"
    "sourcehut"
    "huggingface"
    "repology"
    "pypi"
    "npm"
    "crates.io"
    "pkg.go.dev"
    "packagist"
    "pub.dev"
    "rubygems"
    "hex"
    "lib.rs"
  ];
  research-pool = [
    "openalex"
    "semantic scholar"
    "pubmed"
    "arxiv"
    "crossref"
  ];
  news-pool = [
    "reuters"
    "tagesschau"
    "wikinews"
  ];
  utility-pool = [
    "currency"
    "lingva"
    "wttr.in"
    "openstreetmap"
    "photon"
  ];
  searxng-keep-only = lib.unique (
    promoted-web-pool
    ++ tech-pool
    ++ research-pool
    ++ news-pool
    ++ utility-pool
  );
  searxng-engine-overrides = [
    (mkEngine "startpage" {
      startpage_categ = "web";
      categories = [ "general" "web" ];
      weight = 4;
      timeout = 3.0;
    })
    (mkEngine "qwant" {
      qwant_categ = "web-lite";
      categories = [ "general" "web" ];
      weight = 3;
      timeout = 3.0;
    })
    (mkEngine "mojeek" {
      categories = [ "general" "web" ];
      weight = 3;
      timeout = 3.0;
    })
    (mkEngine "presearch" {
      categories = [ "general" "web" ];
      weight = 2;
      timeout = 3.0;
    })
    (mkEngine "wikipedia" {
      categories = [ "general" "web" ];
      weight = 6;
      timeout = 3.0;
    })
    (mkEngine "wikidata" {
      categories = [ "general" "web" ];
      weight = 3;
      timeout = 3.0;
    })

    (mkEngine "arch linux wiki" {
      categories = [ "software wikis" "it" ];
      weight = 5;
      timeout = 4.0;
    })
    (mkEngine "nixos wiki" {
      categories = [ "software wikis" "it" ];
      weight = 5;
      timeout = 4.0;
    })
    (mkEngine "askubuntu" {
      categories = [ "q&a" "it" ];
      weight = 4;
      timeout = 4.0;
    })
    (mkEngine "stackoverflow" {
      categories = [ "q&a" "it" ];
      weight = 4;
      timeout = 4.0;
    })
    (mkEngine "superuser" {
      categories = [ "q&a" "it" ];
      weight = 3;
      timeout = 4.0;
    })
    (mkEngine "mankier" {
      categories = [ "it" ];
      weight = 4;
      timeout = 4.0;
    })
    (mkEngine "mdn" {
      categories = [ "it" ];
      weight = 4;
      timeout = 4.0;
    })
    (mkEngine "github" {
      categories = [ "repos" "it" ];
      weight = 4;
      timeout = 4.0;
    })
    (mkEngine "gitlab" {
      categories = [ "repos" "it" ];
      weight = 3;
      timeout = 4.0;
    })
    (mkEngine "gitea.com" {
      categories = [ "repos" "it" ];
      weight = 2;
      timeout = 4.0;
    })
    (mkEngine "sourcehut" {
      categories = [ "repos" "it" ];
      weight = 2;
      timeout = 4.0;
    })
    (mkEngine "huggingface" {
      categories = [ "repos" "it" ];
      weight = 2;
      timeout = 4.0;
    })
    (mkEngine "repology" {
      categories = [ "packages" "it" ];
      weight = 8;
      timeout = 5.0;
    })
    (mkEngine "pypi" {
      engine = "pypi_exact";
      categories = [ "packages" "it" ];
      weight = 10;
      timeout = 5.0;
    })
    (mkEngine "npm" {
      categories = [ "packages" "it" ];
      weight = 4;
      timeout = 5.0;
    })
    (mkEngine "crates.io" {
      categories = [ "packages" "it" ];
      weight = 4;
      timeout = 5.0;
    })
    (mkEngine "pkg.go.dev" {
      categories = [ "packages" "it" ];
      weight = 4;
      timeout = 5.0;
    })
    (mkEngine "packagist" {
      categories = [ "packages" "it" ];
      weight = 3;
      timeout = 5.0;
    })
    (mkEngine "pub.dev" {
      categories = [ "packages" "it" ];
      weight = 3;
      timeout = 5.0;
    })
    (mkEngine "rubygems" {
      categories = [ "packages" "it" ];
      weight = 3;
      timeout = 5.0;
    })
    (mkEngine "hex" {
      categories = [ "packages" "it" ];
      weight = 3;
      timeout = 5.0;
    })
    (mkEngine "lib.rs" {
      categories = [ "packages" "it" ];
      weight = 4;
      timeout = 5.0;
    })

    (mkEngine "openalex" {
      categories = [ "science" "scientific publications" ];
      weight = 6;
      timeout = 5.0;
      mailto = "pricebuddy@ghostship.io";
    })
    (mkEngine "semantic scholar" {
      categories = [ "science" "scientific publications" ];
      weight = 5;
      timeout = 5.0;
    })
    (mkEngine "pubmed" {
      categories = [ "science" "scientific publications" ];
      weight = 5;
      timeout = 5.0;
    })
    (mkEngine "arxiv" {
      categories = [ "science" "scientific publications" ];
      weight = 4;
      timeout = 5.0;
    })
    (mkEngine "crossref" {
      categories = [ "science" "scientific publications" ];
      weight = 4;
      timeout = 5.0;
    })

    (mkEngine "reuters" {
      categories = [ "news" ];
      weight = 5;
      timeout = 4.0;
    })
    (mkEngine "tagesschau" {
      categories = [ "news" ];
      weight = 4;
      timeout = 4.0;
    })
    (mkEngine "wikinews" {
      categories = [ "news" ];
      weight = 2;
      timeout = 4.0;
    })

    (mkEngine "currency" {
      categories = [ "currency" ];
      weight = 1;
      timeout = 3.0;
    })
    (mkEngine "lingva" {
      categories = [ "translate" ];
      weight = 1;
      timeout = 3.0;
    })
    (mkEngine "wttr.in" {
      engine = "wttr_exact";
      categories = [ "weather" ];
      weight = 1;
      timeout = 5.0;
    })
    (mkEngine "openstreetmap" {
      categories = [ "map" ];
      weight = 4;
      timeout = 4.0;
    })
    (mkEngine "photon" {
      categories = [ "map" ];
      weight = 2;
      timeout = 4.0;
    })
  ];
  searxng-settings = {
    general = {
      instance_name = "Ghostship Search";
    };
    search = {
      safe_search = 0;
      autocomplete = "";
      formats = [ "html" "json" ];
    };
    server = {
      bind_address = "0.0.0.0";
      port = 8080;
      image_proxy = false;
      limiter = limiter-enabled;
    };
    outgoing = {
      request_timeout = 2.5;
      max_request_timeout = 5.0;
      pool_connections = 100;
      pool_maxsize = 10;
      keepalive_expiry = 5.0;
    };
    valkey = {
      url = "valkey://searxng-valkey:6379/0";
    };
    use_default_settings = {
      engines = {
        keep_only = searxng-keep-only;
      };
    };
    engines = searxng-engine-overrides;
    plugins = {
      "searx.plugins.calculator.SXNGPlugin" = { active = true; };
      "searx.plugins.hash_plugin.SXNGPlugin" = { active = true; };
      "searx.plugins.self_info.SXNGPlugin" = { active = true; };
      "searx.plugins.tracker_url_remover.SXNGPlugin" = { active = true; };
      "searx.plugins.unit_converter.SXNGPlugin" = { active = true; };
      "searx.plugins.oa_doi_rewrite.SXNGPlugin" = { active = true; };
    };
  };
  searxng-limiter-toml = ''
    [botdetection]
    trusted_proxies = [
      "127.0.0.0/8",
      "::1",
      "10.89.0.0/24",
    ]

    [botdetection.ip_limit]
    filter_link_local = false
    link_token = false

    [botdetection.ip_lists]
    pass_ip = [
      "127.0.0.0/8",
      "::1",
      "10.89.0.0/24",
    ]
    pass_searxng_org = true
  '';
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
      "${searxng-config-dir}:/etc/searxng:rw"
      "${searxng-cache-dir}:/var/cache/searxng:rw"
      "${searxng-pypi-engine}:/usr/local/searxng/searx/engines/pypi_exact.py:ro"
      "${searxng-wttr-engine}:/usr/local/searxng/searx/engines/wttr_exact.py:ro"
    ];
  };

  systemd.tmpfiles.rules = [
    "d ${searxng-config-dir} 0755 apps apps -"
    "d ${searxng-cache-dir} 0755 apps apps -"
  ];

  systemd.services.podman-searxng.preStart = ''
    CONFIG_DIR="${searxng-config-dir}"
    SETTINGS_FILE="$CONFIG_DIR/settings.yml"
    LIMITER_FILE="$CONFIG_DIR/limiter.toml"
    SECRETS_FILE="${searxng-secrets}"

    install -d -m0755 -o apps -g apps "$CONFIG_DIR" "${searxng-cache-dir}"

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

    set -a
    . "$SECRETS_FILE"
    set +a

    if [ -z "''${SEARXNG_SECRET_KEY:-}" ]; then
      echo "Missing SEARXNG_SECRET_KEY in $SECRETS_FILE" >&2
      exit 1
    fi

    SETTINGS_TEMPLATE="$CONFIG_DIR/settings.template.json"

    cat > "$SETTINGS_TEMPLATE" <<'EOF'
${builtins.toJSON searxng-settings}
EOF

    export SETTINGS_FILE SETTINGS_TEMPLATE
    ${pkgs.python3}/bin/python3 - <<'PYEOF'
import json
import os
from pathlib import Path

settings = json.loads(Path(os.environ["SETTINGS_TEMPLATE"]).read_text())
settings["server"]["secret_key"] = os.environ["SEARXNG_SECRET_KEY"]
Path(os.environ["SETTINGS_FILE"]).write_text(json.dumps(settings, indent=2) + "\n")
Path(os.environ["SETTINGS_TEMPLATE"]).unlink()
PYEOF

    cat > "$LIMITER_FILE" <<'EOF'
${searxng-limiter-toml}
EOF

    chown 3000:3000 "$SETTINGS_FILE" "$LIMITER_FILE"
    chmod 0640 "$SETTINGS_FILE" "$LIMITER_FILE"
  '';
}
