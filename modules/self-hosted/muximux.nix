{ lib, pkgs, ... }:

let
  muximuxWriterInit = pkgs.writeScript "muximux-writer-init" ''
    #!/usr/bin/with-contenv bash
    set -euo pipefail
    php /run/ghostship/muximux-patch-writer.php \
      /config/www/muximux/muximux.php /run/ghostship/muximux-save-config.php
    chown abc:abc /config/www/muximux/muximux.php
  '';
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
  config = lib.mkMerge [
    {
      ghostship.apps.muximux = {
        healthPath = "/favicon.ico";
        name = "Muximux";
        group = "Management";
        description = "Lightweight Portal";
        icon = "mdi-view-dashboard-#00c853";
        order = 20;
        hostname = "apps.ghostship.io";
        origin = "http://muximux:80";
      };

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
          S6_BEHAVIOUR_IF_STAGE2_FAILS = "2";
        };
        volumes = [
          "/srv/apps/muximux:/config:rw"
          "${muximuxWriterInit}:/etc/cont-init.d/50-ghostship-writer:ro"
          "${./muximux-patch-writer.php}:/run/ghostship/muximux-patch-writer.php:ro"
          "${./muximux-save-config.php}:/run/ghostship/muximux-save-config.php:ro"
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

    }
    {
      systemd.services.podman-muximux.preStart = lib.mkAfter ''
        CONFIG_FILE="/srv/apps/muximux/www/muximux/settings.ini.php"

        if [ ! -f "$CONFIG_FILE" ]; then
          printf "<?php die('Access denied'); ?>\n" > "$CONFIG_FILE"
        fi
        if [ -f "$CONFIG_FILE" ]; then
          echo "Surgically updating Muximux settings..."
          
          mux_args=(
            general.title=literal:"ghostship.io"
            general.userNameInput=literal:"admin"
            Synology.name=literal:"Synology"
            Synology.url=literal:"https://synology.ghostship.io"
            Synology.scale=literal:1
            Synology.icon=literal:"muximux-database"
            Synology.color=literal:"#3799ef"
            Synology.enabled=literal:"true"
            Synology.dd=literal:"true"
          )

          ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${mux_args[@]}"

          chown apps:apps "$CONFIG_FILE"
        fi
      '';
    }
  ];
}
