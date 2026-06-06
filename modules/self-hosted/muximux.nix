{ pkgs, ... }:

let
  rommIframeShimVersion = "20260402-2";
  rommIframeShim = pkgs.writeText "romm-iframe-shim.js" ''
    (() => {
      if (window.top === window.self) {
        return;
      }

      const shimVersion = "${rommIframeShimVersion}";
      const resolved = Promise.resolve();
      const noop = () => {};

      const startViewTransitionShim = callback => {
        if (typeof callback === "function") {
          try {
            callback();
          } catch (error) {
            queueMicrotask(() => {
              throw error;
            });
          }
        }

        return {
          ready: resolved,
          finished: resolved,
          updateCallbackDone: resolved,
          skipTransition: noop,
        };
      };

      const defineDocumentGetter = (name, value) => {
        try {
          Object.defineProperty(document, name, {
            configurable: true,
            get: () => value,
          });
        } catch (_error) {}
      };

      const safeMethod = fn => function (...args) {
        if (!this || !this.isConnected) {
          return undefined;
        }

        try {
          return fn.apply(this, args);
        } catch (_error) {
          return undefined;
        }
      };

      try {
        Object.defineProperty(document, "startViewTransition", {
          configurable: true,
          writable: true,
          value: startViewTransitionShim,
        });
      } catch (_error) {
        document.startViewTransition = startViewTransitionShim;
      }

      defineDocumentGetter("hidden", false);
      defineDocumentGetter("visibilityState", "visible");

      try {
        document.hasFocus = () => true;
      } catch (_error) {}

      if (window.HTMLElement?.prototype?.focus) {
        HTMLElement.prototype.focus = safeMethod(HTMLElement.prototype.focus);
      }

      if (window.Element?.prototype?.scrollIntoView) {
        Element.prototype.scrollIntoView = safeMethod(Element.prototype.scrollIntoView);
      }

      if (window.matchMedia) {
        const originalMatchMedia = window.matchMedia.bind(window);
        window.matchMedia = query => {
          const result = originalMatchMedia(query);

          if (!query || !query.includes("prefers-reduced-motion")) {
            return result;
          }

          return new Proxy(result, {
            get(target, prop, receiver) {
              if (prop === "matches") {
                return true;
              }

              return Reflect.get(target, prop, receiver);
            },
          });
        };
      }

      document.documentElement.setAttribute("data-romm-iframe-shim", shimVersion);

      const style = document.createElement("style");
      style.textContent = `
        html[data-romm-iframe-shim],
        html[data-romm-iframe-shim] * {
          scroll-behavior: auto !important;
        }

        html[data-romm-iframe-shim] *,
        html[data-romm-iframe-shim] *::before,
        html[data-romm-iframe-shim] *::after {
          animation-delay: 0s !important;
          animation-duration: 0s !important;
          transition-delay: 0s !important;
          transition-duration: 0s !important;
        }
      `;
      (document.head || document.documentElement).appendChild(style);

      window.__rommIframeShim = { version: shimVersion };
      window.addEventListener("error", event => {
        console.debug("[romm-iframe-shim:error]", event.message);
      }, true);
      window.addEventListener("unhandledrejection", event => {
        console.debug(
          "[romm-iframe-shim:rejection]",
          String(event.reason?.message ?? event.reason)
        );
      }, true);
    })();
  '';
  muximuxDefaultSite = pkgs.writeText "muximux-default.conf" ''
    server {
      listen 80 default_server;

      listen 443 ssl;

      root /config/www/muximux;
      index index.html index.htm index.php;

      server_name _;

      ssl_certificate /config/keys/cert.crt;
        ssl_certificate_key /config/keys/cert.key;

        client_max_body_size 0;
        resolver 10.89.0.1 valid=30s ipv6=off;
        set $romm_upstream romm:8080;
        set $grimmory_upstream grimmory:6060;
        set $pyload_upstream pyload:8000;

      location = /romm-iframe-shim.js {
        add_header Cache-Control "no-store";
      }

      location = /pyload {
        return 308 /pyload/;
      }

      location /pyload/ {
        rewrite ^/pyload/(.*)$ /$1 break;
        proxy_pass http://$pyload_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Accept-Encoding "";
        proxy_redirect / https://$host/pyload/;
        proxy_redirect http://$host/ https://$host/pyload/;
      }

      location /web/ {
        proxy_pass http://$pyload_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_redirect / https://$host/pyload/;
        proxy_redirect http://$host/ https://$host/pyload/;
      }

      location /json/ {
        proxy_pass http://$pyload_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_redirect / https://$host/pyload/;
        proxy_redirect http://$host/ https://$host/pyload/;
      }

      location = /grimmory {
        return 308 /grimmory/;
      }

      location /grimmory/ {
        rewrite ^/grimmory/(.*)$ /$1 break;
        proxy_pass http://$grimmory_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host grimmory:6060;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Accept-Encoding "";
        proxy_hide_header X-Frame-Options;
        proxy_cookie_path / /grimmory/;
        proxy_redirect / https://$host/grimmory/;
        proxy_redirect http://$host/ https://$host/grimmory/;

        sub_filter_once off;
        sub_filter_types text/html application/javascript text/javascript text/css;
        sub_filter '<head>' '<head><base href="/grimmory/" />';
        sub_filter 'href="/' 'href="/grimmory/';
        sub_filter 'src="/' 'src="/grimmory/';
        sub_filter '"/assets/' '"/grimmory/assets/';
        sub_filter '"/api/' '"/grimmory/api/';
        sub_filter "'/assets/" "'/grimmory/assets/";
        sub_filter "'/api/" "'/grimmory/api/";
        sub_filter '}/api/' '}/grimmory/api/';
      }

      location /romm/ {
        rewrite ^/romm/(.*)$ /$1 break;
        proxy_pass http://$romm_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host romm:8080;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Accept-Encoding "";

            # RomM emits root-relative asset and API paths even when proxied.
            # Newer builds also ship an empty Vite env object, so Vue Router
            # falls back to the document <base> tag for its runtime base.
        sub_filter_once off;
        sub_filter_types text/html application/javascript text/css;
    sub_filter '<head>' '<head><base href="/romm/" />';
        sub_filter 'src="/assets/index-' 'src="/romm-iframe-shim.js?v=${rommIframeShimVersion}"></script><script type="module" crossorigin src="/romm/assets/index-';
        sub_filter 'href="/' 'href="/romm/';
        sub_filter 'src="/' 'src="/romm/';
        sub_filter '"/assets/' '"/romm/assets/';
        sub_filter '"/api/' '"/romm/api/';
        sub_filter "'/assets/" "'/romm/assets/";
        sub_filter "'/api/" "'/romm/api/";
            # Keep the older bundle rewrite as a compatibility fallback.
        sub_filter 'BASE_URL:"/"' 'BASE_URL:"/romm/"';
        }

        location /ws/socket.io/ {
            proxy_pass http://$romm_upstream/ws/socket.io/;
            proxy_http_version 1.1;
            proxy_set_header Host romm:8080;
            proxy_set_header X-Forwarded-Host $host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }

      location /assets/ {
        proxy_pass http://$romm_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host romm:8080;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      }

      location /api/ {
        proxy_pass http://$romm_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host romm:8080;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      }

      location / {
        try_files $uri $uri/ /index.html /index.php?$args =404;
      }

      location ~ \.php$ {
        fastcgi_split_path_info ^(.+\.php)(/.+)$;
        # With php5-cgi alone:
        fastcgi_pass 127.0.0.1:9000;
        # With php5-fpm:
        #fastcgi_pass unix:/var/run/php5-fpm.sock;
        fastcgi_index index.php;
        include /etc/nginx/fastcgi_params;
      }
    }
  '';
in

{
  virtualisation.oci-containers.containers."muximux" = {
    image = "docker.io/linuxserver/muximux:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "0:3000";
    extraOptions = [
      "--network=ghostship_net"
    ];
    environment = {
      PUID = "3000";
      PGID = "3000";
      TZ = "UTC";
    };
    volumes = [
      "/srv/apps/muximux:/config:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/muximux 0755 apps apps -"
    "d /srv/apps/muximux/nginx/site-confs 0755 apps apps -"
    "d /srv/apps/muximux/www/muximux 0755 apps apps -"
  ];

  systemd.services.podman-muximux.preStart = ''
    install -d -m0755 -o apps -g apps /srv/apps/muximux/nginx/site-confs
    install -d -m0755 -o apps -g apps /srv/apps/muximux/www/muximux
    install -m0644 -o apps -g apps ${muximuxDefaultSite} /srv/apps/muximux/nginx/site-confs/default
    install -m0644 -o apps -g apps ${rommIframeShim} /srv/apps/muximux/www/muximux/romm-iframe-shim.js
    muximux_php="/srv/apps/muximux/www/muximux/muximux.php"
    if [ -f "$muximux_php" ] && ! grep -q "allow='clipboard-read; clipboard-write'" "$muximux_php"; then
      ${pkgs.gnused}/bin/sed -i \
        "s/allowfullscreen='true'/allow='clipboard-read; clipboard-write' allowfullscreen='true'/" \
        "$muximux_php"
      chown apps:apps "$muximux_php"
    fi
  '';

  system.activationScripts.muximux-config = {
    text = ''
      CONFIG_FILE="/srv/apps/muximux/www/muximux/settings.ini.php"

      if [ -f "$CONFIG_FILE" ]; then
        echo "Surgically updating Muximux settings..."
        
        mux_args=(
          general.title=literal:"ghostship.io"
          general.userNameInput=literal:"admin"
          Homepage.name=literal:""
          Homepage.url=literal:"https://homepage.ghostship.io"
          Homepage.scale=literal:1
          Homepage.icon=literal:"muximux-home2"
          Homepage.color=literal:"#109f61"
          Homepage.enabled=literal:"true"
          Homepage.default=literal:"true"
          Codex.name=literal:"Codex"
          Codex.url=literal:"https://codex.ghostship.io"
          Codex.scale=literal:1
          Codex.icon=literal:"muximux-code"
          Codex.color=literal:"#111827"
          Codex.enabled=literal:"true"
          Codex.dd=literal:"false"
          Synology.name=literal:"Synology"
          Synology.url=literal:"https://synology.ghostship.io"
          Synology.scale=literal:1
          Synology.icon=literal:"muximux-database"
          Synology.color=literal:"#3799ef"
          Synology.enabled=literal:"true"
          Synology.dd=literal:"true"
          Plex.name=literal:"Plex"
          Plex.url=literal:"https://plex.ghostship.io"
          Plex.scale=literal:1
          Plex.icon=literal:"muximux-plex"
          Plex.color=literal:"#ebaf00"
          Plex.enabled=literal:"true"
          NZBGet.name=literal:"NZBGet"
          NZBGet.url=literal:"https://nzbget.ghostship.io"
          NZBGet.scale=literal:1
          NZBGet.icon=literal:"fa-download"
          NZBGet.color=literal:"#4ad946"
          NZBGet.enabled=literal:"true"
          qBittorrent.name=literal:"qBittorrent"
          qBittorrent.url=literal:"https://qbittorrent.ghostship.io"
          qBittorrent.scale=literal:1
          qBittorrent.icon=literal:"fa-magnet"
          qBittorrent.color=literal:"#63cda9"
          qBittorrent.enabled=literal:"true"
          Sonarr.name=literal:"Sonarr"
          Sonarr.url=literal:"https://sonarr.ghostship.io"
          Sonarr.scale=literal:1
          Sonarr.icon=literal:"muximux-sonarr"
          Sonarr.color=literal:"#35c5f4"
          Sonarr.enabled=literal:"true"
          Radarr.name=literal:"Radarr"
          Radarr.url=literal:"https://radarr.ghostship.io"
          Radarr.scale=literal:1
          Radarr.icon=literal:"muximux-radarr"
          Radarr.color=literal:"#ffc230"
          Radarr.enabled=literal:"true"
          Prowlarr.name=literal:"Prowlarr"
          Prowlarr.url=literal:"https://prowlarr.ghostship.io"
          Prowlarr.scale=literal:1
          Prowlarr.icon=literal:"muximux-paw"
          Prowlarr.color=literal:"#e45124"
          Prowlarr.enabled=literal:"true"
          Grimmory.name=literal:"Grimmory"
          Grimmory.url=literal:"/grimmory/"
          Grimmory.scale=literal:1
          Grimmory.icon=literal:"muximux-book2"
          Grimmory.color=literal:"#49da7e"
          Grimmory.enabled=literal:"true"
          Grimmory.dd=literal:"false"
          CloakBrowser.name=literal:"CloakBrowser"
          CloakBrowser.url=literal:"https://cloakbrowser.ghostship.io"
          CloakBrowser.scale=literal:1
          CloakBrowser.icon=literal:"muximux-chrome"
          CloakBrowser.color=literal:"#000000"
          CloakBrowser.enabled=literal:"true"
          CloakBrowser.dd=literal:"false"
          RomM.name=literal:"RomM"
          RomM.url=literal:"/romm/"
          RomM.scale=literal:1
          RomM.icon=literal:"muximux-gamepad"
          RomM.color=literal:"#553f99"
          RomM.enabled=literal:"true"
          RomM.dd=literal:"false"
          Tautulli.name=literal:"Tautulli"
          Tautulli.url=literal:"https://tautulli.ghostship.io"
          Tautulli.scale=literal:1
          Tautulli.icon=literal:"muximux-plexivity"
          Tautulli.color=literal:"#e5a00d"
          Tautulli.enabled=literal:"true"
          Tautulli.dd=literal:"true"
          Chaptarr.name=literal:"Chaptarr"
          Chaptarr.url=literal:"https://chaptarr.ghostship.io"
          Chaptarr.scale=literal:1
          Chaptarr.icon=literal:"fa-book"
          Chaptarr.color=literal:"#4f8ef7"
          Chaptarr.enabled=literal:"true"
          Chaptarr.dd=literal:"true"
          Bazarr.name=literal:"Bazarr"
          Bazarr.url=literal:"https://bazarr.ghostship.io/"
          Bazarr.scale=literal:1
          Bazarr.icon=literal:"muximux-bazarr"
          Bazarr.color=literal:"#9c36b5"
          Bazarr.enabled=literal:"true"
          Bazarr.dd=literal:"true"
          pyLoad.name=literal:"pyLoad"
          pyLoad.url=literal:"/pyload/"
          pyLoad.scale=literal:1
          pyLoad.icon=literal:"fa-download"
          pyLoad.color=literal:"#ffcc00"
          pyLoad.enabled=literal:"true"
          pyLoad.dd=literal:"true"
          RSS-Bridge.name=literal:"RSS-Bridge"
          RSS-Bridge.url=literal:"https://rss-bridge.ghostship.io"
          RSS-Bridge.scale=literal:1
          RSS-Bridge.icon=literal:"fa-rss-square"
          RSS-Bridge.color=literal:"#f97316"
          RSS-Bridge.enabled=literal:"true"
          RSS-Bridge.dd=literal:"true"
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${mux_args[@]}"

        temp_file="$(mktemp)"
        ${pkgs.gawk}/bin/awk '
          function flush_section(    key) {
            if (!have_section) {
              return
            }

            key = section_name
            if (!(key in seen_section)) {
              seen_section[key] = 1
              section_order[++section_count] = key
            }
            section_data[key] = section_data[key] section_buffer

            section_buffer = ""
            have_section = 0
            section_name = ""
          }

          BEGIN {
            have_section = 0
            section_count = 0
            preamble = ""
          }

          /^\[/ {
            flush_section()
            have_section = 1
            section_name = $0
            sub(/^\[/, "", section_name)
            sub(/\]$/, "", section_name)
            section_buffer = $0 ORS
            next
          }

          {
            if (have_section) {
              section_buffer = section_buffer $0 ORS
            } else {
              preamble = preamble $0 ORS
            }
          }

          END {
            flush_section()
            printf "%s", preamble

            for (i = 1; i <= section_count; i++) {
              name = section_order[i]
              if (name == "Honcho" || name == "Codex" || name == "BookStack" || name == "Chaptarr" || name == "Hatchet" || name == "Prefect" || name == "Windmill" || name == "N8N" || name == "PriceBuddy" || name == "Changedetection" || name == "OmniTools" || name == "MeTube" || name == "ConvertX" || name == "BentoPDF" || name == "IT Tools" || name == "SearXNG" || name == "qBittorrent" || name == "SSH") {
                continue
              }

              if (name == "CloakBrowser" && ("Codex" in section_data)) {
                printf "%s", section_data["Codex"]
              }
              printf "%s", section_data[name]
              if (name == "NZBGet" && ("qBittorrent" in section_data)) {
                printf "%s", section_data["qBittorrent"]
              }
              if (name == "Tautulli" && ("Chaptarr" in section_data)) {
                printf "%s", section_data["Chaptarr"]
              }
            }

            if (!("CloakBrowser" in section_data) && ("Codex" in section_data)) {
              printf "%s", section_data["Codex"]
            }
            if (!("Tautulli" in section_data) && ("Chaptarr" in section_data)) {
              printf "%s", section_data["Chaptarr"]
            }
          }
        ' "$CONFIG_FILE" > "$temp_file"
        mv "$temp_file" "$CONFIG_FILE"
        
        chown apps:apps "$CONFIG_FILE"
      fi
    '';
  };
}
