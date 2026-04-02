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

    	location = /romm-iframe-shim.js {
    		add_header Cache-Control "no-store";
    	}

    	location /romm/ {
    		proxy_pass http://romm:8080/;
    		proxy_http_version 1.1;
    		proxy_set_header Host romm:8080;
    		proxy_set_header X-Forwarded-Host $host;
    		proxy_set_header X-Forwarded-Proto $scheme;
    		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    		proxy_set_header Accept-Encoding "";

            # RomM emits root-relative asset and API paths even when proxied.
    		sub_filter_once off;
    		sub_filter_types text/html application/javascript text/css;
    		sub_filter 'src="/assets/index-' 'src="/romm-iframe-shim.js?v=${rommIframeShimVersion}"></script><script type="module" crossorigin src="/romm/assets/index-';
    		sub_filter 'href="/' 'href="/romm/';
    		sub_filter 'src="/' 'src="/romm/';
    		sub_filter '"/assets/' '"/romm/assets/';
    		sub_filter '"/api/' '"/romm/api/';
    		sub_filter "'/assets/" "'/romm/assets/";
    		sub_filter "'/api/" "'/romm/api/";
    		sub_filter 'BASE_URL:"/"' 'BASE_URL:"/romm/"';
    	}

    	location /assets/ {
    		proxy_pass http://romm:8080/assets/;
    		proxy_http_version 1.1;
    		proxy_set_header Host romm:8080;
    		proxy_set_header X-Forwarded-Host $host;
    		proxy_set_header X-Forwarded-Proto $scheme;
    		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    	}

    	location /api/ {
    		proxy_pass http://romm:8080/api/;
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
          VueTorrent.name=literal:"VueTorrent"
          VueTorrent.url=literal:"https://vuetorrent.ghostship.io"
          VueTorrent.scale=literal:1
          VueTorrent.icon=literal:"muximux-qwiklabs"
          VueTorrent.color=literal:"#63cda9"
          VueTorrent.enabled=literal:"true"
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
          Grimmory.url=literal:"https://grimmory.ghostship.io"
          Grimmory.scale=literal:1
          Grimmory.icon=literal:"muximux-book2"
          Grimmory.color=literal:"#49da7e"
          Grimmory.enabled=literal:"true"
          Grimmory.dd=literal:"false"
          PriceBuddy.name=literal:"PriceBuddy"
          PriceBuddy.url=literal:"https://pricebuddy.ghostship.io"
          PriceBuddy.scale=literal:1
          PriceBuddy.icon=literal:"fa-money"
          PriceBuddy.color=literal:"#22c55e"
          PriceBuddy.enabled=literal:"true"
          PriceBuddy.dd=literal:"true"
          Hermes.name=literal:"Hermes"
          Hermes.url=literal:"https://hermes.ghostship.io"
          Hermes.scale=literal:1
          Hermes.icon=literal:"fa-terminal"
          Hermes.color=literal:"#06b6d4"
          Hermes.enabled=literal:"true"
          Hermes.dd=literal:"false"
          RomM.name=literal:"RomM"
          RomM.url=literal:"/romm/"
          RomM.scale=literal:1
          RomM.icon=literal:"muximux-gamepad"
          RomM.color=literal:"#553f99"
          RomM.enabled=literal:"true"
          RomM.dd=literal:"false"
          Synology.name=literal:"Synology"
          Synology.url=literal:"https://synology.ghostship.io"
          Synology.scale=literal:1
          Synology.icon=literal:"muximux-database"
          Synology.color=literal:"#3799ef"
          Synology.enabled=literal:"true"
          Synology.dd=literal:"true"
          Tautulli.name=literal:"Tautulli"
          Tautulli.url=literal:"https://tautulli.ghostship.io"
          Tautulli.scale=literal:1
          Tautulli.icon=literal:"muximux-plexivity"
          Tautulli.color=literal:"#e5a00d"
          Tautulli.enabled=literal:"true"
          Tautulli.dd=literal:"true"
          Bazarr.name=literal:"Bazarr"
          Bazarr.url=literal:"https://bazarr.ghostship.io/"
          Bazarr.scale=literal:1
          Bazarr.icon=literal:"muximux-bazarr"
          Bazarr.color=literal:"#9c36b5"
          Bazarr.enabled=literal:"true"
          Bazarr.dd=literal:"true"
          CloakBrowser.name=literal:"CloakBrowser"
          CloakBrowser.url=literal:"https://cloakbrowser.ghostship.io"
          CloakBrowser.scale=literal:1
          CloakBrowser.icon=literal:"muximux-chrome"
          CloakBrowser.color=literal:"#000000"
          CloakBrowser.enabled=literal:"true"
          CloakBrowser.dd=literal:"true"
          pyLoad.name=literal:"pyLoad"
          pyLoad.url=literal:"https://pyload.ghostship.io"
          pyLoad.scale=literal:1
          pyLoad.icon=literal:"fa-download"
          pyLoad.color=literal:"#ffcc00"
          pyLoad.enabled=literal:"true"
          pyLoad.dd=literal:"true"
          SearXNG.name=literal:"SearXNG"
          SearXNG.url=literal:"https://searxng.ghostship.io"
          SearXNG.scale=literal:1
          SearXNG.icon=literal:"muximux-search"
          SearXNG.color=literal:"#ffffff"
          SearXNG.enabled=literal:"true"
          SearXNG.dd=literal:"true"
          RSS-Bridge.name=literal:"RSS-Bridge"
          RSS-Bridge.url=literal:"https://rss-bridge.ghostship.io"
          RSS-Bridge.scale=literal:1
          RSS-Bridge.icon=literal:"fa-rss-square"
          RSS-Bridge.color=literal:"#f97316"
          RSS-Bridge.enabled=literal:"true"
          RSS-Bridge.dd=literal:"true"
          OmniTools.name=literal:"OmniTools"
          OmniTools.url=literal:"https://omnitools.ghostship.io"
          OmniTools.scale=literal:1
          OmniTools.icon=literal:"fa-wrench"
          OmniTools.color=literal:"#ff9800"
          OmniTools.enabled=literal:"true"
          OmniTools.dd=literal:"true"
          MeTube.name=literal:"MeTube"
          MeTube.url=literal:"https://metube.ghostship.io"
          MeTube.scale=literal:1
          MeTube.icon=literal:"muximux-cloud-download2"
          MeTube.color=literal:"#ff4c41"
          MeTube.enabled=literal:"true"
          MeTube.dd=literal:"true"
          ConvertX.name=literal:"ConvertX"
          ConvertX.url=literal:"https://convertx.ghostship.io"
          ConvertX.scale=literal:1
          ConvertX.icon=literal:"muximux-expertsexchange"
          ConvertX.color=literal:"#557f14"
          ConvertX.enabled=literal:"true"
          ConvertX.dd=literal:"true"
          BentoPDF.name=literal:"BentoPDF"
          BentoPDF.url=literal:"https://bentopdf.ghostship.io"
          BentoPDF.scale=literal:1
          BentoPDF.icon=literal:"muximux-file-pdf"
          BentoPDF.color=literal:"#7c86ff"
          BentoPDF.enabled=literal:"true"
          BentoPDF.dd=literal:"true"
          "IT Tools.name"=literal:"IT Tools"
          "IT Tools.url"=literal:"https://it-tools.ghostship.io"
          "IT Tools.scale"=literal:1
          "IT Tools.icon"=literal:"muximux-info2"
          "IT Tools.color"=literal:"#2c9a66"
          "IT Tools.enabled"=literal:"true"
          "IT Tools.dd"=literal:"true"
          SSH.name=literal:"SSH"
          SSH.url=literal:"https://ssh.ghostship.io"
          SSH.scale=literal:1
          SSH.icon=literal:"muximux-terminal3"
          SSH.color=literal:"#0045a6"
          SSH.enabled=literal:"true"
          SSH.dd=literal:"true"
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
              if (name == "Honcho" || name == "PriceBuddy") {
                continue
              }

              printf "%s", section_data[name]
              if (name == "Bazarr" && ("PriceBuddy" in section_data)) {
                printf "%s", section_data["PriceBuddy"]
              }
            }

            if (!("Bazarr" in section_data) && ("PriceBuddy" in section_data)) {
              printf "%s", section_data["PriceBuddy"]
            }
          }
        ' "$CONFIG_FILE" > "$temp_file"
        mv "$temp_file" "$CONFIG_FILE"
        
        chown apps:apps "$CONFIG_FILE"
      fi
    '';
  };
}
