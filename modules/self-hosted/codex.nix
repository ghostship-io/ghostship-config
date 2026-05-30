{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:

let
  codexHome = "/srv/apps/codex/home";
  codexNix = "/srv/apps/codex/nix";
  codexDocker = "/srv/apps/codex/docker";
  codexWorkspace = "/srv/apps/codex/workspace";
  codexSecrets = config.ghostship.selfHostedSecrets.projections.codex.path;
  imageName = "localhost/ghostship-codex";
  imageTag = "codex-web-${inputs.codex-web.shortRev or inputs.codex-web.rev}";
  system = pkgs.stdenv.hostPlatform.system;

  codexWebUnpatched = inputs.codex-web.packages.${system}.default;
  codexWebCli = inputs.codex-web.packages.${system}.codex;

  codexWebManifest = pkgs.writeText "codex-web-manifest.json" ''
    {
      "id": "/",
      "name": "Codex",
      "short_name": "Codex",
      "description": "Ghostship Codex",
      "start_url": "/",
      "scope": "/",
      "display": "standalone",
      "background_color": "#0d0d0d",
      "theme_color": "#0d0d0d",
      "icons": [
        {
          "src": "/assets/pwa-icon-192.png",
          "sizes": "192x192",
          "type": "image/png",
          "purpose": "any maskable"
        },
        {
          "src": "/assets/pwa-icon-512.png",
          "sizes": "512x512",
          "type": "image/png",
          "purpose": "any maskable"
        }
      ]
    }
  '';

  codexMobileViewportStyle = pkgs.writeText "codex-mobile-viewport.css" ''
    @media (hover: none) and (pointer: coarse) {
      html,
      body,
      #root {
        height: 100svh !important;
        min-height: 100svh !important;
      }

      .app-shell-main-content-viewport {
        --thread-floating-content-bottom-inset: calc(
          72px + max(
            env(safe-area-inset-bottom, 0px),
            var(--codex-visual-viewport-bottom-inset, 0px)
          )
        ) !important;
      }

      .pointer-events-none.absolute[class*="bottom-(--thread-floating-content-bottom-inset)"] {
        bottom: var(--thread-floating-content-bottom-inset) !important;
      }

      @supports (height: 100dvh) {
        html,
        body,
        #root {
          height: min(var(--codex-visual-viewport-height, 100svh), 100svh) !important;
          min-height: min(var(--codex-visual-viewport-height, 100svh), 100svh) !important;
        }
      }
    }
  '';

  codexMobileViewportScript = pkgs.writeText "codex-mobile-viewport.js" ''
    (() => {
      const root = document.documentElement;
      const bottomInsetProperty = "--thread-floating-content-bottom-inset";
      let beforeInstallPromptFired = false;
      const runtimeErrors = [];

      const recordRuntimeError = (message) => {
        runtimeErrors.push(String(message).slice(0, 500));
        if (runtimeErrors.length > 8) {
          runtimeErrors.shift();
        }
        updateDebugOverlay();
      };

      window.addEventListener("error", (event) => {
        recordRuntimeError(event.message || event.error || "unknown error");
      });

      window.addEventListener("unhandledrejection", (event) => {
        recordRuntimeError(event.reason || "unhandled rejection");
      });

      window.addEventListener("beforeinstallprompt", (event) => {
        beforeInstallPromptFired = true;
        window.__ghostshipBeforeInstallPrompt = event;
        updateDebugOverlay();
      });

      const updateViewport = () => {
        const viewport = window.visualViewport;
        const height = viewport?.height || window.innerHeight;
        const bottomInset = viewport
          ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
          : 0;

        root.style.setProperty("--codex-visual-viewport-height", height + "px");
        root.style.setProperty("--codex-visual-viewport-bottom-inset", bottomInset + "px");
        document.querySelector(".app-shell-main-content-viewport")?.style.setProperty(
          bottomInsetProperty,
          `calc(72px + max(env(safe-area-inset-bottom, 0px), ''${bottomInset}px))`,
          "important",
        );
      };

      const findFloatingComposer = () =>
        document.querySelector(
          '.pointer-events-none.absolute[class*="bottom-(--thread-floating-content-bottom-inset)"]',
        ) || document.querySelector('[class*="bottom-(--thread-floating-content-bottom-inset)"]');

      const formatRect = (element) => {
        if (!element) {
          return null;
        }
        const rect = element.getBoundingClientRect();
        return {
          top: Math.round(rect.top),
          bottom: Math.round(rect.bottom),
          height: Math.round(rect.height),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
        };
      };

      async function getServiceWorkerState() {
        if (!("serviceWorker" in navigator)) {
          return { supported: false };
        }

        let registrations = "unknown";
        try {
          registrations = (await navigator.serviceWorker.getRegistrations()).map((registration) => ({
            scope: registration.scope,
            active: Boolean(registration.active),
            waiting: Boolean(registration.waiting),
            installing: Boolean(registration.installing),
          }));
        } catch (error) {
          registrations = "error: " + error;
        }

        return {
          supported: true,
          controller: Boolean(navigator.serviceWorker.controller),
          registrations,
        };
      }

      async function collectDebugState() {
        const viewport = window.visualViewport;
        const contentViewport = document.querySelector(".app-shell-main-content-viewport");
        const floatingComposer = findFloatingComposer();
        const input = document.querySelector('[contenteditable="true"], textarea, input');
        const floatingStyle = floatingComposer ? getComputedStyle(floatingComposer) : null;
        const contentStyle = contentViewport ? getComputedStyle(contentViewport) : null;
        const rootStyle = getComputedStyle(root);

        return {
          href: location.href,
          userAgent: navigator.userAgent,
          displayModeStandalone: window.matchMedia("(display-mode: standalone)").matches,
          beforeInstallPromptFired,
          runtimeErrors,
          serviceWorker: await getServiceWorkerState(),
          manifestHref: document.querySelector('link[rel="manifest"]')?.href || null,
          window: {
            innerHeight: window.innerHeight,
            innerWidth: window.innerWidth,
            scrollY: Math.round(window.scrollY),
          },
          visualViewport: viewport
            ? {
                height: Math.round(viewport.height),
                width: Math.round(viewport.width),
                offsetTop: Math.round(viewport.offsetTop),
                offsetLeft: Math.round(viewport.offsetLeft),
                scale: viewport.scale,
              }
            : null,
          documentElement: {
            clientHeight: root.clientHeight,
            scrollHeight: root.scrollHeight,
            codexHeight: rootStyle.getPropertyValue("--codex-visual-viewport-height").trim(),
            codexBottomInset: rootStyle
              .getPropertyValue("--codex-visual-viewport-bottom-inset")
              .trim(),
          },
          body: {
            clientHeight: document.body?.clientHeight,
            scrollHeight: document.body?.scrollHeight,
          },
          rootChildren: Array.from(document.getElementById("root")?.children || []).map(
            (element) => ({
              tag: element.tagName,
              className: element.className || null,
            }),
          ),
          contentViewport: {
            found: Boolean(contentViewport),
            rect: formatRect(contentViewport),
            bottomInset: contentStyle?.getPropertyValue(bottomInsetProperty).trim() || null,
          },
          floatingComposer: {
            found: Boolean(floatingComposer),
            rect: formatRect(floatingComposer),
            className: floatingComposer?.className || null,
            position: floatingStyle?.position || null,
            bottom: floatingStyle?.bottom || null,
            transform: floatingStyle?.transform || null,
          },
          firstInput: {
            found: Boolean(input),
            rect: formatRect(input),
            tag: input?.tagName || null,
          },
        };
      }

      async function updateDebugOverlay() {
        if (!new URLSearchParams(location.search).has("ghostship-debug")) {
          return;
        }

        let overlay = document.getElementById("ghostship-mobile-debug");
        if (!overlay) {
          overlay = document.createElement("pre");
          overlay.id = "ghostship-mobile-debug";
          overlay.style.cssText = [
            "position:fixed",
            "z-index:2147483647",
            "left:8px",
            "right:8px",
            "top:8px",
            "max-height:48vh",
            "overflow:auto",
            "margin:0",
            "padding:10px",
            "font:11px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace",
            "white-space:pre-wrap",
            "color:#f8fafc",
            "background:rgba(2,6,23,.94)",
            "border:1px solid rgba(148,163,184,.6)",
            "border-radius:8px",
            "box-shadow:0 8px 30px rgba(0,0,0,.45)",
          ].join(";");
          document.documentElement.appendChild(overlay);
        }

        const state = await collectDebugState();
        overlay.textContent = "Ghostship mobile debug\n" + JSON.stringify(state, null, 2);
      }

      const scheduleViewportUpdate = () => {
        updateViewport();
        updateDebugOverlay();
        requestAnimationFrame(updateViewport);
        requestAnimationFrame(updateDebugOverlay);
      };

      scheduleViewportUpdate();
      [50, 150, 300, 750, 1500].forEach((delay) => {
        window.setTimeout(scheduleViewportUpdate, delay);
      });
      document.addEventListener("DOMContentLoaded", scheduleViewportUpdate, { once: true });
      window.addEventListener("load", scheduleViewportUpdate, { once: true });
      window.visualViewport?.addEventListener("resize", updateViewport);
      window.visualViewport?.addEventListener("scroll", updateViewport);
      window.addEventListener("resize", updateViewport);
      window.addEventListener("orientationchange", scheduleViewportUpdate);
      window.visualViewport?.addEventListener("resize", updateDebugOverlay);
      window.visualViewport?.addEventListener("scroll", updateDebugOverlay);
      window.addEventListener("resize", updateDebugOverlay);
      window.addEventListener("orientationchange", updateDebugOverlay);

      if ("serviceWorker" in navigator && window.isSecureContext) {
        navigator.serviceWorker
          .register("/service-worker.js", { scope: "/" })
          .finally(updateDebugOverlay)
          .catch(() => {});
      }

      [250, 1000, 2500, 5000].forEach((delay) => {
        window.setTimeout(updateDebugOverlay, delay);
      });
    })();
  '';

  codexServiceWorker = pkgs.writeText "codex-service-worker.js" ''
    self.addEventListener("install", (event) => {
      event.waitUntil(self.skipWaiting());
    });

    self.addEventListener("activate", (event) => {
      event.waitUntil(self.clients.claim());
    });

    self.addEventListener("fetch", (event) => {
      if (event.request.method !== "GET") {
        return;
      }

      event.respondWith(fetch(event.request));
    });
  '';

  codexCacheControlHook = pkgs.writeText "codex-cache-control-hook.js" ''
    const sockets = new Set();
      app.addHook("onSend", async (request, reply, payload) => {
        const path = new URL(request.url, "http://localhost").pathname;
        if (
          request.method === "GET" &&
          (path === "/" ||
            path === "/index.html" ||
            path === "/manifest.json" ||
            path === "/codex-mobile-viewport.css" ||
            path === "/codex-mobile-viewport.js" ||
            path === "/service-worker.js" ||
            !path.includes("."))
        ) {
          reply.header("Cache-Control", "no-store, max-age=0, must-revalidate");
          reply.header("Pragma", "no-cache");
          reply.header("Expires", "0");
          if (path === "/manifest.json") {
            reply.header("Content-Type", "application/manifest+json; charset=utf-8");
          }
        }
        return payload;
      });
  '';

  codexWeb =
    pkgs.runCommand "codex-web-mobile-viewport-${inputs.codex-web.shortRev or inputs.codex-web.rev}"
      {
        nativeBuildInputs = [
          pkgs.gnused
          pkgs.imagemagick
        ];
      }
      ''
                      cp -a ${codexWebUnpatched} "$out"
                      chmod -R u+w "$out"
                      substituteInPlace "$out/bin/codex-web" \
                        --replace-fail ${codexWebUnpatched} "$out"

                      webview="$out/lib/node_modules/codex-web/scratch/asar/webview"
                      substituteInPlace "$webview/index.html" \
                        --replace-fail 'content="width=device-width, initial-scale=1.0"' \
                        'content="width=device-width, initial-scale=1.0, viewport-fit=cover"'

                install -m0644 ${codexWebManifest} "$webview/manifest.json"
                magick "$webview/assets/pwa-icon-512.png" -resize 192x192 "$webview/assets/pwa-icon-192.png"
                install -m0644 ${codexMobileViewportStyle} "$webview/codex-mobile-viewport.css"
                install -m0644 ${codexMobileViewportScript} "$webview/codex-mobile-viewport.js"
                install -m0644 ${codexServiceWorker} "$webview/service-worker.js"

                server_main="$out/lib/node_modules/codex-web/src/server/main.js"
                substituteInPlace "$server_main" \
                  --replace-fail 'const sockets = new Set();' \
                  "$(cat ${codexCacheControlHook})"
            substituteInPlace "$server_main" \
              --replace-fail 'prefix: "/",' \
              'prefix: "/",
        cacheControl: false,
        setHeaders: (res) => {
          res.setHeader("Cache-Control", "no-store, max-age=0, must-revalidate");
          res.setHeader("Pragma", "no-cache");
          res.setHeader("Expires", "0");
        },'

                sed -i \
                        's|</head>|    <meta name="theme-color" content="#0d0d0d" />\n    <meta name="mobile-web-app-capable" content="yes" />\n    <meta name="apple-mobile-web-app-capable" content="yes" />\n    <meta name="apple-mobile-web-app-title" content="Codex" />\n    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />\n    <link rel="stylesheet" href="/codex-mobile-viewport.css" />\n    <script src="/codex-mobile-viewport.js"></script>\n  </head>|' \
                        "$webview/index.html"
                sed -i \
                        's|<link rel="manifest" href="/manifest.json" />|<link rel="manifest" href="/manifest.json" />\n    <link rel="icon" sizes="192x192" href="/assets/pwa-icon-192.png" />\n    <link rel="apple-touch-icon" href="/assets/pwa-icon-192.png" />|' \
                        "$webview/index.html"
                substituteInPlace "$server_main" \
                  --replace-fail 'if (request.method === "GET") {
            return reply.sendFile("index.html");
        }' 'if (
            request.method === "GET" &&
            request.headers.accept?.includes("text/html") &&
            !new URL(request.url, "http://localhost").pathname.split("/").pop()?.includes(".")
        ) {
            return reply.sendFile("index.html");
        }'
      '';

  codexPackages = with pkgs; [
    codexWeb
    codexWebCli
    nix
    docker
    ollama
    bitwarden-cli
    git
    gh
    openssh
    curl
    jq
    ripgrep
    fd
    direnv
    uv
    python3
    nodejs_24
    stdenv.cc
    gnumake
    pkg-config
    cmake
    binutils
    coreutils
    findutils
    gnugrep
    gnused
    gnutar
    gzip
    unzip
    iptables
    iproute2
    kmod
    su-exec
    which
    file
    bashInteractive
    cacert
  ];

  codexPath = lib.makeBinPath codexPackages;

  codexOllamaCloudProxy = pkgs.writeTextFile {
    name = "codex-ollama-cloud-proxy";
    destination = "/bin/codex-ollama-cloud-proxy";
    executable = true;
    text = ''
      #!${pkgs.nodejs_24}/bin/node
      const http = require("node:http");

      const listenHost = "127.0.0.1";
      const listenPort = Number(process.env.OLLAMA_PROXY_PORT || "11434");
      const upstream = new URL(process.env.OLLAMA_CLOUD_BASE_URL || "https://ollama.com");
      const ollamaPrefix = "ollama/";

      function normalizeRequestBody(body, headers) {
        if (body.length === 0) {
          return body;
        }
        const contentType = String(headers["content-type"] || "");
        if (!contentType.includes("application/json")) {
          return body;
        }

        try {
          const payload = JSON.parse(body.toString("utf8"));
          if (payload && typeof payload.model === "string" && payload.model.startsWith(ollamaPrefix)) {
            payload.model = payload.model.slice(ollamaPrefix.length);
            const normalized = Buffer.from(JSON.stringify(payload));
            headers["content-length"] = String(normalized.length);
            return normalized;
          }
        } catch {
          return body;
        }

        return body;
      }

      const server = http.createServer(async (request, response) => {
        try {
          const body = await new Promise((resolve, reject) => {
            const chunks = [];
            request.on("data", (chunk) => chunks.push(chunk));
            request.on("end", () => resolve(Buffer.concat(chunks)));
            request.on("error", reject);
          });

          const target = new URL(request.url || "/", upstream);
          const headers = { ...request.headers };
          headers.host = upstream.host;
          if (process.env.OLLAMA_API_KEY) {
            headers.authorization = `Bearer ''${process.env.OLLAMA_API_KEY}`;
          }
          const upstreamBody = normalizeRequestBody(body, headers);

          const upstreamResponse = await fetch(target, {
            method: request.method,
            headers,
            body: ["GET", "HEAD"].includes(request.method || "GET") ? undefined : upstreamBody,
          });

          response.writeHead(upstreamResponse.status, Object.fromEntries(upstreamResponse.headers));
          if (upstreamResponse.body) {
            for await (const chunk of upstreamResponse.body) {
              response.write(chunk);
            }
          }
          response.end();
        } catch (error) {
          response.writeHead(502, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: String(error?.message || error) }));
        }
      });

      server.listen(listenPort, listenHost, () => {
        console.error(`Ollama cloud proxy listening on http://''${listenHost}:''${listenPort}`);
      });
    '';
  };

  codexAppServerProxy = pkgs.writeTextFile {
    name = "codex-app-server-proxy";
    destination = "/bin/codex-app-server-proxy";
    executable = true;
    text = ''
      #!${pkgs.nodejs_24}/bin/node
      const { spawn } = require("node:child_process");
      const readline = require("node:readline");

      const realCodex = process.env.CODEX_REAL_CLI_PATH || "${codexWebCli}/bin/codex";
      const args = process.argv.slice(2);
      const isAppServer = args[0] === "app-server";

      if (!isAppServer) {
        const child = spawn(realCodex, args, { stdio: "inherit", env: process.env });
        child.on("exit", (code, signal) => {
          if (signal) {
            process.kill(process.pid, signal);
          }
          process.exit(code ?? 1);
        });
        process.on("SIGTERM", () => child.kill("SIGTERM"));
        process.on("SIGINT", () => child.kill("SIGINT"));
      } else {
        const child = spawn(realCodex, args, {
          stdio: ["pipe", "pipe", "pipe"],
          env: process.env,
        });

        const requestMethods = new Map();
        const ollamaPrefix = "ollama/";
        const fallbackOllamaModels = ${
          builtins.toJSON [
            "glm-5"
            "qwen3-next:80b"
            "kimi-k2.5"
            "kimi-k2.6"
            "kimi-k2-thinking"
            "gemini-3-flash-preview"
            "minimax-m2"
            "glm-4.7"
            "deepseek-v4-flash"
            "qwen3-vl:235b-instruct"
            "glm-5.1"
            "gpt-oss:120b"
            "qwen3-vl:235b"
            "gemma4:31b"
            "nemotron-3-super"
            "deepseek-v4-pro"
            "nemotron-3-nano:30b"
            "gpt-oss:20b"
            "minimax-m2.5"
            "deepseek-v3.2"
            "minimax-m2.7"
            "qwen3.5:397b"
          ]
        };

        function routeOllamaSelection(message) {
          if (!message || typeof message !== "object" || !message.params || typeof message.params !== "object") {
            return message;
          }
          const params = message.params;
          if (typeof params.model !== "string" || !params.model.startsWith(ollamaPrefix)) {
            return message;
          }

          params.model = params.model.slice(ollamaPrefix.length);
          if (["thread/start", "thread/fork", "thread/resume"].includes(message.method)) {
            params.modelProvider = "ollama";
            params.serviceTier = null;
          }
          return message;
        }

        function effortTemplate(models) {
          for (const model of models) {
            if (Array.isArray(model.supportedReasoningEfforts) && model.supportedReasoningEfforts.length > 0) {
              return model.supportedReasoningEfforts;
            }
          }
          return ["low", "medium", "high"];
        }

        async function fetchOllamaModelNames() {
          try {
            const headers = {};
            if (process.env.OLLAMA_API_KEY) {
              headers.authorization = `Bearer ''${process.env.OLLAMA_API_KEY}`;
            }
            const [tagsResponse, searchResponse] = await Promise.all([
              fetch("https://ollama.com/api/tags", { headers }),
              fetch("https://ollama.com/search?c=tools&c=thinking&c=cloud", { headers }),
            ]);
            if (!tagsResponse.ok) {
              throw new Error(`ollama.com/api/tags returned ''${tagsResponse.status}`);
            }
            if (!searchResponse.ok) {
              throw new Error(`ollama.com/search returned ''${searchResponse.status}`);
            }
            const payload = await tagsResponse.json();
            const searchHtml = await searchResponse.text();
            const taggedFamilies = new Set(
              Array.from(searchHtml.matchAll(/href="\/library\/([^"?#/]+)/g), (match) => match[1])
            );
            const names = Array.isArray(payload.models) ?
              payload.models
                .map((model) => model.model || model.name)
                .filter(Boolean)
                .filter((name) => taggedFamilies.has(name) || taggedFamilies.has(name.split(":", 1)[0])) :
              [];
            return names.length > 0 ? names : fallbackOllamaModels;
          } catch (error) {
            console.error(`failed to fetch ollama.com model list: ''${error?.message || error}`);
            return fallbackOllamaModels;
          }
        }

        async function decorateOllamaModels(openaiModels) {
          const supportedReasoningEfforts = effortTemplate(openaiModels);
          const modelNames = await fetchOllamaModelNames();
          return modelNames.map((modelName) => ({
            upgrade: null,
            upgradeInfo: null,
            availabilityNux: null,
            hidden: false,
            supportedReasoningEfforts,
            defaultReasoningEffort: "medium",
            inputModalities: ["text"],
            supportsPersonality: true,
            additionalSpeedTiers: [],
            serviceTiers: [],
            isDefault: false,
            id: `ollama/''${modelName}`,
            model: `ollama/''${modelName}`,
            displayName: `Ollama / ''${modelName}`,
            description: "Ollama cloud model reached through ollama.com using the projected API key.",
          }));
        }

        async function appendOllamaModels(message) {
          const method = requestMethods.get(message?.id);
          if (method !== "model/list" || !Array.isArray(message?.result?.data)) {
            return message;
          }

          const data = message.result.data;
          const existing = new Set(data.map((model) => model.id || model.model));
          const injected = (await decorateOllamaModels(data)).filter((model) => !existing.has(model.id));
          message.result = {
            ...message.result,
            data: data.concat(injected),
          };
          return message;
        }

        const input = readline.createInterface({ input: process.stdin });
        input.on("line", (line) => {
          if (line.trim() === "") {
            child.stdin.write("\n");
            return;
          }
          try {
            const message = JSON.parse(line);
            if (message.id !== undefined && typeof message.method === "string") {
              requestMethods.set(message.id, message.method);
            }
            child.stdin.write(JSON.stringify(routeOllamaSelection(message)) + "\n");
          } catch {
            child.stdin.write(line + "\n");
          }
        });
        input.on("close", () => child.stdin.end());

        const output = readline.createInterface({ input: child.stdout });
        output.on("line", async (line) => {
          try {
            process.stdout.write(JSON.stringify(await appendOllamaModels(JSON.parse(line))) + "\n");
          } catch {
            process.stdout.write(line + "\n");
          }
        });

        child.stderr.pipe(process.stderr);
        child.on("exit", (code) => process.exit(code ?? 1));
        process.on("SIGTERM", () => child.kill("SIGTERM"));
        process.on("SIGINT", () => child.kill("SIGINT"));
      }
    '';
  };

  codexEntrypoint = pkgs.writeShellScriptBin "codex-web-entrypoint" ''
    set -eu

    export HOME=/home/codex
    export USER=codex
    export PATH=${codexPath}:$PATH
    export DOCKER_HOST=unix:///var/run/docker.sock
    export NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    export SSL_CERT_FILE=$NIX_SSL_CERT_FILE
    export NIX_CONFIG="experimental-features = nix-command flakes"
    export CODEX_REAL_CLI_PATH=${codexWebCli}/bin/codex
    export CODEX_CLI_PATH=${codexAppServerProxy}/bin/codex-app-server-proxy
    export OLLAMA_HOST=http://127.0.0.1:11434
    export OLLAMA_MODELS=$HOME/.ollama/models
    export OLLAMA_CLOUD_BASE_URL=https://ollama.com
    web_pid=""
    ollama_proxy_pid=""

    mkdir -p "$HOME/.ollama/models" "$HOME/.codex" /workspace /mnt/share /var/lib/docker /var/run /tmp
    chown -R codex:codex "$HOME" /workspace

    rm -f /var/run/docker.pid
    dockerd \
      --host=unix:///var/run/docker.sock \
      --data-root=/var/lib/docker \
      --storage-driver=vfs \
      --iptables=false \
      --ip-masq=false \
      --bridge=none &
    docker_pid=$!
    trap 'kill "$docker_pid" 2>/dev/null || true' EXIT

    for _ in $(seq 1 30); do
      if docker info >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    chmod 0666 /var/run/docker.sock || true

    su-exec codex:codex env \
      HOME="$HOME" \
      USER="$USER" \
      PATH="$PATH" \
      OLLAMA_HOST="$OLLAMA_HOST" \
      OLLAMA_MODELS="$OLLAMA_MODELS" \
      OLLAMA_CLOUD_BASE_URL="$OLLAMA_CLOUD_BASE_URL" \
      OLLAMA_API_KEY="''${OLLAMA_API_KEY:-}" \
      NIX_SSL_CERT_FILE="$NIX_SSL_CERT_FILE" \
      SSL_CERT_FILE="$SSL_CERT_FILE" \
      ${codexOllamaCloudProxy}/bin/codex-ollama-cloud-proxy &
    ollama_proxy_pid=$!
    trap 'kill "$docker_pid" "''${ollama_proxy_pid:-}" "''${web_pid:-}" 2>/dev/null || true' EXIT

    cd /workspace

    su-exec codex:codex env \
      HOME="$HOME" \
      USER="$USER" \
      PATH="$PATH" \
      DOCKER_HOST="$DOCKER_HOST" \
      NIX_SSL_CERT_FILE="$NIX_SSL_CERT_FILE" \
      SSL_CERT_FILE="$SSL_CERT_FILE" \
      NIX_CONFIG="$NIX_CONFIG" \
      CODEX_REAL_CLI_PATH="$CODEX_REAL_CLI_PATH" \
      CODEX_CLI_PATH="$CODEX_CLI_PATH" \
      OLLAMA_HOST="$OLLAMA_HOST" \
      OLLAMA_MODELS="$OLLAMA_MODELS" \
      OLLAMA_CLOUD_BASE_URL="$OLLAMA_CLOUD_BASE_URL" \
      OLLAMA_API_KEY="''${OLLAMA_API_KEY:-}" \
      ${codexWeb}/bin/codex-web --host 0.0.0.0 --port 8214 &
    web_pid=$!
    wait "$web_pid"
  '';

  codexImage = pkgs.dockerTools.buildLayeredImage {
    name = imageName;
    tag = imageTag;
    contents = codexPackages ++ [
      codexEntrypoint
      codexOllamaCloudProxy
      codexAppServerProxy
      pkgs.dockerTools.binSh
      pkgs.dockerTools.usrBinEnv
      pkgs.dockerTools.caCertificates
    ];
    extraCommands = ''
      mkdir -p etc/nix tmp workspace home/codex
      mkdir -p mnt/share var/lib/docker var/run
      chmod 1777 tmp
      cat > etc/passwd <<'EOF'
      root:x:0:0:root:/root:/bin/sh
      codex:x:3000:3000:Codex:/home/codex:/bin/sh
      EOF
      cat > etc/group <<'EOF'
      root:x:0:
      codex:x:3000:
      EOF
      cat > etc/nix/nix.conf <<'EOF'
      experimental-features = nix-command flakes
      sandbox = false
      EOF
    '';
    config = {
      Cmd = [ "${codexEntrypoint}/bin/codex-web-entrypoint" ];
      Env = [
        "HOME=/home/codex"
        "USER=codex"
        "DOCKER_HOST=unix:///var/run/docker.sock"
        "PATH=${codexPath}"
        "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "NIX_CONFIG=experimental-features = nix-command flakes"
        "CODEX_REAL_CLI_PATH=${codexWebCli}/bin/codex"
        "CODEX_CLI_PATH=${codexAppServerProxy}/bin/codex-app-server-proxy"
        "OLLAMA_HOST=http://127.0.0.1:11434"
        "OLLAMA_MODELS=/home/codex/.ollama/models"
        "OLLAMA_CLOUD_BASE_URL=https://ollama.com"
      ];
      WorkingDir = "/workspace";
      ExposedPorts = {
        "8214/tcp" = { };
      };
    };
  };
in
{
  virtualisation.oci-containers.containers."codex" = {
    image = "${imageName}:${imageTag}";
    imageFile = codexImage;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "disabled";
    };
    ports = [ ];
    environmentFiles = [ codexSecrets ];
    extraOptions = [
      "--privileged"
      "--network=ghostship_net"
      "--health-cmd=curl -fsS http://127.0.0.1:8214/ >/dev/null || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "${codexNix}:/nix:rw"
      "${codexDocker}:/var/lib/docker:rw"
      "${codexWorkspace}:/workspace:rw"
      "${codexHome}:/home/codex:rw"
      "/mnt/share:/mnt/share:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/codex 0755 root root -"
    "d ${codexDocker} 0755 root root -"
    "d ${codexHome} 0755 3000 3000 -"
    "d ${codexWorkspace} 0755 3000 3000 -"
  ];

  systemd.services.podman-codex = {
    after = [ "init-ghostship-net.service" ];
    wants = [ "init-ghostship-net.service" ];
    preStart = lib.mkAfter ''
      set -eu

      install -d -m0755 -o root -g root /srv/apps/codex
      install -d -m0755 -o root -g root ${codexDocker}
      install -d -m0755 -o 3000 -g 3000 ${codexHome}
      install -d -m0755 -o 3000 -g 3000 ${codexWorkspace}

      if [ ! -e ${codexNix}/.ghostship-seeded-image ] || [ "$(<${codexNix}/.ghostship-seeded-image)" != "${codexImage}" ]; then
        ${pkgs.podman}/bin/podman load -i ${codexImage}

        seed_container="codex-nix-seed-$$"
        seed_tmp="${codexNix}.seed.$$"
        rm -rf "$seed_tmp"
        mkdir -p "$seed_tmp"

        ${pkgs.podman}/bin/podman rm -f "$seed_container" >/dev/null 2>&1 || true
        ${pkgs.podman}/bin/podman create --pull=never --name "$seed_container" "${imageName}:${imageTag}" >/dev/null
        ${pkgs.podman}/bin/podman cp "$seed_container:/nix/." "$seed_tmp/"
        ${pkgs.podman}/bin/podman rm -f "$seed_container" >/dev/null

        if [ -e ${codexNix} ]; then
          cp -a "$seed_tmp"/. ${codexNix}/
          rm -rf "$seed_tmp"
        else
          mv "$seed_tmp" ${codexNix}
        fi
        printf '%s\n' "${codexImage}" > ${codexNix}/.ghostship-seeded-image
        chown -R 3000:3000 ${codexNix}
      fi
    '';
  };
}
