{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:

let
  codexHome = "/srv/apps/codex/home";
  codexDocker = "/srv/apps/codex/docker";
  codexNixRoot = "/srv/apps/codex/nix-root";
  codexWorkspace = "/srv/apps/codex/workspace";
  codexSecrets = config.ghostship.selfHostedSecrets.projections.codex.path;
  codexSecretsFile = "/run/secrets/codex.env";
  imageName = "localhost/ghostship-codex";
  imageTag = "codex-${inputs.self.shortRev or inputs.self.rev or "dirty"}";
  repoVersion = lib.removeSuffix "\n" (builtins.readFile ../../VERSION);
  system = pkgs.stdenv.hostPlatform.system;

  codexWebFallback = inputs.codex-web.packages.${system}.default;
  codexCliFallback = inputs.codex-web.packages.${system}.codex;
  codexRemoteProxyFallback = inputs.codex-web.packages.${system}.codex_remote_proxy;
  codexToolFallback = pkgs.linkFarm "ghostship-codex-tools-fallback" [
    {
      name = "web";
      path = codexWebFallback;
    }
    {
      name = "codex";
      path = codexCliFallback;
    }
    {
      name = "proxy";
      path = codexRemoteProxyFallback;
    }
  ];

  codexPwaManifest = pkgs.writeText "codex-manifest.webmanifest" ''
    {
      "id": "/",
      "name": "Codex",
      "short_name": "Codex",
      "description": "Ghostship Codex",
      "start_url": "/",
      "scope": "/",
      "display": "standalone",
      "display_override": ["standalone"],
      "background_color": "#0d0d0d",
      "theme_color": "#0d0d0d",
      "categories": ["developer", "productivity", "tools"],
      "lang": "en",
      "prefer_related_applications": false,
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

  codexPwaRegister = pkgs.writeText "codex-pwa-register.js" ''
    (() => {
      if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
      window.addEventListener("load", () => {
        navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
      });
    })();
  '';

  codexServiceWorker = pkgs.writeText "codex-sw.js" ''
    self.addEventListener("install", (event) => {
      event.waitUntil(self.skipWaiting());
    });

    self.addEventListener("activate", (event) => {
      event.waitUntil(self.clients.claim());
    });

    self.addEventListener("fetch", (event) => {
      if (event.request.method === "GET") {
        event.respondWith(fetch(event.request));
      }
    });
  '';

  codexPwaPrepare = pkgs.writeShellScriptBin "codex-pwa-prepare" ''
    set -eu

    source_web="''${1:?usage: codex-pwa-prepare WEB_PACKAGE}"
    resolved_source="$(readlink -f "$source_web")"
    case "$resolved_source" in
      /nix/store/*) ;;
      *)
        printf 'error: Codex Web package is outside the Nix store: %s\n' "$resolved_source" >&2
        exit 1
        ;;
    esac

    target_root="$CODEX_TOOL_ROOT/pwa"
    target="$target_root/${repoVersion}-$(basename "$resolved_source")"
    marker="$target/.ghostship-pwa-source"
    if [ -x "$target/bin/codex-web" ] \
      && [ -f "$target/lib/node_modules/codex-web/scratch/asar/webview/manifest.webmanifest" ] \
      && [ -f "$target/lib/node_modules/codex-web/scratch/asar/webview/sw.js" ] \
      && [ "$(cat "$marker" 2>/dev/null || true)" = "$resolved_source" ]; then
      printf '%s\n' "$target"
      exit 0
    fi

    mkdir -p "$target_root"
    work_dir="$(mktemp -d "$target_root/.pwa.XXXXXX")"
    trap 'rm -rf "$work_dir"' EXIT
    cp -a "$resolved_source/." "$work_dir/"
    chmod -R u+w "$work_dir"

    launcher="$work_dir/bin/codex-web"
    webview="$work_dir/lib/node_modules/codex-web/scratch/asar/webview"
    index="$webview/index.html"
    [ -x "$launcher" ]
    [ -f "$index" ]
    [ -f "$webview/assets/pwa-icon-512.png" ]

    sed -i "s|$resolved_source|$target|g" "$launcher"
    sed -i \
      -e 's|href="/manifest.json"|href="/manifest.webmanifest"|g' \
      -e 's|</head>|    <meta name="theme-color" content="#0d0d0d" />\n    <meta name="mobile-web-app-capable" content="yes" />\n    <meta name="apple-mobile-web-app-capable" content="yes" />\n    <meta name="apple-mobile-web-app-title" content="Codex" />\n    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />\n    <link rel="apple-touch-icon" sizes="180x180" href="/assets/pwa-icon-180.png" />\n    <script src="/pwa-register.js"></script>\n  </head>|' \
      "$index"

    install -m 0644 ${codexPwaManifest} "$webview/manifest.webmanifest"
    install -m 0644 ${codexPwaRegister} "$webview/pwa-register.js"
    install -m 0644 ${codexServiceWorker} "$webview/sw.js"
    ${pkgs.imagemagick}/bin/magick "$webview/assets/pwa-icon-512.png" \
      -resize 192x192 "$webview/assets/pwa-icon-192.png"
    ${pkgs.imagemagick}/bin/magick "$webview/assets/pwa-icon-512.png" \
      -resize 180x180 "$webview/assets/pwa-icon-180.png"

    jq -e '
      (.name == "Codex")
      and (.start_url == "/")
      and (.display == "standalone")
      and (any(.icons[]; .sizes == "192x192"))
      and (any(.icons[]; .sizes == "512x512"))
    ' "$webview/manifest.webmanifest" >/dev/null
    ${pkgs.imagemagick}/bin/identify "$webview/assets/pwa-icon-192.png" \
      | grep -q '192x192'
    grep -q '/pwa-register.js' "$index"
    grep -q '/manifest.webmanifest' "$index"

    printf '%s\n' "$resolved_source" > "$work_dir/.ghostship-pwa-source"
    rm -rf "$target"
    mv "$work_dir" "$target"
    trap - EXIT
    printf '%s\n' "$target"
  '';

  codexPackages = with pkgs; [
    nix
    systemd
    dbus
    pam
    docker
    cloudflared
    sudo
    bitwarden-cli
    git
    git-lfs
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
    p7zip
    util-linux
    websocat
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
  codexRuntimeEnv = ''
    if [ -f ${codexSecretsFile} ]; then
      set -a
      # shellcheck disable=SC1091
      . ${codexSecretsFile}
      set +a
    fi
    export HOME=/home/codex
    export USER=codex
    export XDG_CONFIG_HOME="''${XDG_CONFIG_HOME:-$HOME/.config}"
    export XDG_STATE_HOME="''${XDG_STATE_HOME:-$HOME/.local/state}"
    export XDG_CACHE_HOME="''${XDG_CACHE_HOME:-$HOME/.cache}"
    export XDG_DATA_HOME="''${XDG_DATA_HOME:-$HOME/.local/share}"
    export CODEX_HOME="$HOME/.codex"
    export CODEX_TOOL_ROOT="$HOME/.local/share/codex-tools"
    export CODEX_TOOL_CURRENT="$CODEX_TOOL_ROOT/current"
    export CODEX_APP_SERVER_SOCKET=/run/codex-app-server/codex-app-server.sock
    export CODEX_UNIX_SOCKET="$CODEX_APP_SERVER_SOCKET"
    export CODEX_REMOTE_PROXY_PATH="$CODEX_TOOL_CURRENT/proxy/bin/codex_remote_proxy"
    export CODEX_OLLAMA_CATALOG="$HOME/.local/state/codex-ollama/catalog.json"
    export OLLAMA_HOST=http://127.0.0.1:11434
    hm_session_vars="$HOME/.nix-profile/etc/profile.d/hm-session-vars.sh"
    if [ -f "$hm_session_vars" ]; then
      # shellcheck disable=SC1090
      case "$-" in *u*) restore_nounset=1 ;; *) restore_nounset=0 ;; esac
      set +u
      . "$hm_session_vars"
      if [ "$restore_nounset" -eq 1 ]; then
        set -u
      fi
    fi
    export PATH=$HOME/.local/bin:$CODEX_TOOL_CURRENT/codex/bin:${codexPath}:/bin:/usr/bin:$PATH
    export DOCKER_HOST=unix:///var/run/docker.sock
    export XDG_RUNTIME_DIR=/run/user/3000
    export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
    export NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    export SSL_CERT_FILE=$NIX_SSL_CERT_FILE
    export NIX_CONFIG="experimental-features = nix-command flakes"
    export NIX_REMOTE=daemon
  '';

  codexAppServerAdapter = pkgs.writeTextFile {
    name = "codex-app-server-adapter";
    destination = "/bin/codex-app-server-adapter";
    executable = true;
    text = ''
      #!${pkgs.nodejs_24}/bin/node
      const fs = require("node:fs");
      const readline = require("node:readline");
      const { spawn } = require("node:child_process");

      const home = process.env.HOME || "/home/codex";
      const proxy = process.env.CODEX_REMOTE_PROXY_PATH ||
        home + "/.local/share/codex-tools/current/proxy/bin/codex_remote_proxy";
      const catalogPath = process.env.CODEX_OLLAMA_CATALOG ||
        home + "/.local/state/codex-ollama/catalog.json";
      const childEnv = {
        ...process.env,
        CODEX_UNIX_SOCKET: process.env.CODEX_UNIX_SOCKET ||
          process.env.CODEX_APP_SERVER_SOCKET ||
          "/run/codex-app-server/codex-app-server.sock",
      };
      const child = spawn(proxy, process.argv.slice(2), {
        env: childEnv,
        stdio: ["pipe", "pipe", "pipe"],
      });
      const requests = new Map();

      function readCatalog() {
        try {
          const parsed = JSON.parse(fs.readFileSync(catalogPath, "utf8"));
          return Array.isArray(parsed) ? parsed : [];
        } catch {
          return [];
        }
      }

      function reasoningOptions(capabilities) {
        if (!capabilities.includes("thinking")) return [];
        return ["low", "medium", "high"].map((reasoningEffort) => ({
          reasoningEffort,
          description: reasoningEffort + " reasoning effort",
        }));
      }

      function catalogModels() {
        return readCatalog().map((entry) => {
          const capabilities = Array.isArray(entry.capabilities) ? entry.capabilities : [];
          return {
            upgrade: null,
            upgradeInfo: null,
            availabilityNux: null,
            hidden: false,
            supportedReasoningEfforts: reasoningOptions(capabilities),
            defaultReasoningEffort: "medium",
            inputModalities: capabilities.includes("vision") ? ["text", "image"] : ["text"],
            supportsPersonality: false,
            additionalSpeedTiers: [],
            serviceTiers: [],
            defaultServiceTier: null,
            isDefault: false,
            id: "ollama/" + entry.name,
            model: "ollama/" + entry.name,
            displayName: "Ollama / " + entry.name,
            description: "Tool-capable Ollama.com cloud model",
          };
        });
      }

      function routeOllama(message) {
        if (!message || typeof message !== "object" || !message.params ||
            typeof message.params !== "object") return message;
        if (!["thread/start", "thread/resume", "thread/fork"].includes(message.method)) {
          return message;
        }
        if (typeof message.params.model !== "string" ||
            !message.params.model.startsWith("ollama/")) return message;
        const model = message.params.model.slice("ollama/".length);
        if (!readCatalog().some((entry) => entry.name === model)) {
          process.stderr.write("refusing unknown Ollama picker model: " + model + "\n");
          return message;
        }
        message.params.model = model;
        message.params.modelProvider = "ollama";
        message.params.serviceTier = null;
        return message;
      }

      function decorateModels(message) {
        const request = requests.get(message && message.id);
        if (!request || request.method !== "model/list" || !request.firstPage ||
            !message.result || !Array.isArray(message.result.data)) return message;
        const existing = new Set(message.result.data.map((model) => model.id || model.model));
        message.result.data = message.result.data.concat(
          catalogModels().filter((model) => !existing.has(model.id)),
        );
        return message;
      }

      readline.createInterface({ input: process.stdin }).on("line", (line) => {
        try {
          const message = routeOllama(JSON.parse(line));
          if (message.id !== undefined && typeof message.method === "string") {
            requests.set(message.id, {
              method: message.method,
              firstPage: message.method !== "model/list" || !message.params || !message.params.cursor,
            });
          }
          child.stdin.write(JSON.stringify(message) + "\n");
        } catch {
          child.stdin.write(line + "\n");
        }
      }).on("close", () => child.stdin.end());

      readline.createInterface({ input: child.stdout }).on("line", (line) => {
        try {
          const message = decorateModels(JSON.parse(line));
          process.stdout.write(JSON.stringify(message) + "\n");
          if (message.id !== undefined) requests.delete(message.id);
        } catch {
          process.stdout.write(line + "\n");
        }
      });

      child.stderr.pipe(process.stderr);
      child.stdin.on("error", (error) => {
        if (error.code !== "EPIPE") process.stderr.write(String(error) + "\n");
      });
      child.on("exit", (code, signal) => {
        if (signal) process.kill(process.pid, signal);
        process.exit(code === null ? 1 : code);
      });
      process.on("SIGTERM", () => child.kill("SIGTERM"));
      process.on("SIGINT", () => child.kill("SIGINT"));
    '';
  };

  codexAppServerStatus = pkgs.writeTextFile {
    name = "codex-app-server-status";
    destination = "/bin/codex-app-server-status";
    executable = true;
    text = ''
      #!${pkgs.nodejs_24}/bin/node
      const readline = require("node:readline");
      const { spawn } = require("node:child_process");

      const home = process.env.HOME || "/home/codex";
      const proxy = process.env.CODEX_REMOTE_PROXY_PATH ||
        home + "/.local/share/codex-tools/current/proxy/bin/codex_remote_proxy";
      const mode = process.argv.includes("--idle") ? "idle" : "health";
      const childEnv = {
        ...process.env,
        CODEX_UNIX_SOCKET: process.env.CODEX_UNIX_SOCKET ||
          process.env.CODEX_APP_SERVER_SOCKET ||
          "/run/codex-app-server/codex-app-server.sock",
      };
      const child = spawn(proxy, ["app-server"], { env: childEnv, stdio: ["pipe", "pipe", "pipe"] });
      const threads = [];
      let nextId = 2;
      let finished = false;
      let timer;

      function fail(message) {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        process.stderr.write(message + "\n");
        child.kill("SIGTERM");
        process.exit(1);
      }

      function sendList(cursor) {
        child.stdin.write(JSON.stringify({
          id: nextId++,
          method: "thread/list",
          params: { cursor, limit: 100, sourceKinds: [], useStateDbOnly: true },
        }) + "\n");
      }

      function succeed() {
        if (finished) return;
        const statuses = threads.map((thread) => thread && thread.status && thread.status.type);
        const idle = statuses.every((status) => status === "idle" || status === "notLoaded");
        const result = { idle, threadCount: threads.length, statuses };
        process.stdout.write(JSON.stringify(result) + "\n");
        finished = true;
        clearTimeout(timer);
        child.kill("SIGTERM");
        process.exit(mode === "health" || idle ? 0 : 1);
      }

      readline.createInterface({ input: child.stdout }).on("line", (line) => {
        let message;
        try { message = JSON.parse(line); } catch { return; }
        if (message.id === 1) {
          if (message.error) fail("app-server initialize failed");
          else if (mode === "health") succeed();
          else sendList(null);
          return;
        }
        if (message.id >= 2) {
          if (message.error || !message.result || !Array.isArray(message.result.data)) {
            fail("app-server thread/list failed");
            return;
          }
          threads.push(...message.result.data);
          if (message.result.nextCursor) sendList(message.result.nextCursor);
          else succeed();
        }
      });
      child.stderr.on("data", () => {});
      child.stdin.on("error", (error) => {
        if (error.code !== "EPIPE") fail(String(error));
      });
      child.on("error", (error) => fail(String(error)));
      child.on("exit", (code) => {
        if (!finished) fail("app-server proxy exited with " + code);
      });
      child.stdin.write(JSON.stringify({
        id: 1,
        method: "initialize",
        params: {
          clientInfo: { name: "ghostship-runtime-probe", version: "1.0.0" },
          capabilities: { experimentalApi: true },
        },
      }) + "\n");
      timer = setTimeout(() => fail("app-server probe timed out"), 15000);
    '';
  };

  codexOllamaProxy = pkgs.writeTextFile {
    name = "codex-ollama-cloud-proxy";
    destination = "/bin/codex-ollama-cloud-proxy";
    executable = true;
    text = ''
      #!${pkgs.nodejs_24}/bin/node
      const http = require("node:http");
      const https = require("node:https");

      const apiKey = process.env.OLLAMA_API_KEY || "";
      const maxBody = 64 * 1024 * 1024;
      const server = http.createServer((request, response) => {
        if (!apiKey) {
          response.writeHead(503, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: "Ollama API key is not configured" }));
          return;
        }

        const headers = { ...request.headers };
        delete headers.host;
        delete headers.connection;
        delete headers["proxy-connection"];
        delete headers["transfer-encoding"];
        headers.authorization = "Bearer " + apiKey;
        let size = 0;
        const upstreamRequest = https.request({
          hostname: "ollama.com",
          port: 443,
          method: request.method,
          path: request.url || "/",
          headers,
        }, (upstreamResponse) => {
          response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
          upstreamResponse.pipe(response);
        });
        upstreamRequest.on("error", (error) => {
          if (response.headersSent) {
            response.destroy(error);
            return;
          }
          response.writeHead(502, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: String(error && error.message || error) }));
        });
        request.on("data", (chunk) => {
          size += chunk.length;
          if (size > maxBody) {
            upstreamRequest.destroy(new Error("request body exceeds 64 MiB"));
            request.destroy();
            if (!response.headersSent) {
              response.writeHead(413, { "content-type": "application/json" });
              response.end(JSON.stringify({ error: "request body exceeds 64 MiB" }));
            }
            return;
          }
          upstreamRequest.write(chunk);
        });
        request.on("end", () => upstreamRequest.end());
        request.on("error", (error) => upstreamRequest.destroy(error));
      });
      server.listen(11434, "127.0.0.1", () => {
        process.stderr.write("Ollama cloud proxy listening on 127.0.0.1:11434\n");
      });
    '';
  };

  codexIdleCheck = ''
    is_codex_idle() {
      su-exec codex:codex ${codexAppServerStatus}/bin/codex-app-server-status --idle >/dev/null 2>&1
    }
  '';

  codexToolMaintenance = pkgs.writeShellScriptBin "codex-tool-maintenance" ''
    set -eu

    ${codexRuntimeEnv}

    metadata="$(nix flake metadata --refresh --json github:0xcaff/codex-web/main)"
    revision="$(printf '%s\n' "$metadata" | jq -r '.locked.rev')"
    case "$revision" in
      ""|null|*[!0-9a-f]*)
        printf 'error: failed to resolve codex-web main revision\n' >&2
        exit 1
        ;;
    esac

    generation="$CODEX_TOOL_ROOT/generations/$revision"
    if [ -x "$generation/codex/bin/codex" ] \
      && [ -x "$generation/web/bin/codex-web" ] \
      && [ -x "$generation/proxy/bin/codex_remote_proxy" ] \
      && [ -s "$generation/codex.version" ] \
      && [ -s "$generation/revision" ] \
      && [ -f "$generation/schema/v2/ModelListResponse.json" ]; then
      printf '%s\n' "$generation"
      exit 0
    fi

    reference="github:0xcaff/codex-web/$revision"
    web="$(nix build --no-link --print-out-paths "$reference#default")"
    cli="$(nix build --no-link --print-out-paths "$reference#codex")"
    proxy="$(nix build --no-link --print-out-paths "$reference#codex_remote_proxy")"

    rm -rf "$generation"
    mkdir -p "$generation"
    nix-store --add-root "$generation/web" --indirect -r "$web" >/dev/null
    nix-store --add-root "$generation/codex" --indirect -r "$cli" >/dev/null
    nix-store --add-root "$generation/proxy" --indirect -r "$proxy" >/dev/null

    schema_dir="$generation/schema"
    "$generation/codex/bin/codex" app-server generate-json-schema --experimental --out "$schema_dir" >/dev/null
    jq -e '
      .definitions.Model.properties
      | has("id") and has("model") and has("displayName")
        and has("supportedReasoningEfforts") and has("serviceTiers")
    ' "$schema_dir/v2/ModelListResponse.json" >/dev/null
    "$generation/codex/bin/codex" --version > "$generation/codex.version"
    printf '%s\n' "$revision" > "$generation/revision"
    printf '%s\n' "$generation"
  '';

  codexToolAutoUpdate = pkgs.writeShellScriptBin "codex-tool-auto-update" ''
    set -eu

    ${codexRuntimeEnv}
    state_dir="/run/codex-tool-update"
    pending_restart="$state_dir/restart.pending"
    install -d -m 0700 "$state_dir"

    exec 9>"$state_dir/tool-update.lock"
    ${pkgs.util-linux}/bin/flock 9

    log_info() {
      printf 'info: %s\n' "$1" >&2
    }

    generation="$(su-exec codex:codex ${codexToolMaintenance}/bin/codex-tool-maintenance)"
    current="$(readlink -f "$CODEX_TOOL_CURRENT" 2>/dev/null || true)"
    if [ "$current" = "$generation" ]; then
      log_info "codex-web revision is unchanged"
      exit 0
    fi

    pending_tmp="$pending_restart.tmp"
    {
      printf 'source=tool-update\n'
      printf 'generation=%s\n' "$generation"
      printf 'previous=%s\n' "$current"
      printf 'revision=%s\n' "$(cat "$generation/revision")"
      printf 'codex=%s\n' "$(cat "$generation/codex.version")"
    } > "$pending_tmp"
    mv "$pending_tmp" "$pending_restart"
    log_info "Codex tool generation downloaded; restart queued until all threads are idle"
  '';

  codexToolUpdateRestart = pkgs.writeShellScriptBin "codex-tool-update-restart" ''
    set -eu

    ${codexRuntimeEnv}

    state_dir="/run/codex-tool-update"
    pending_restart="$state_dir/restart.pending"

    log_info() {
      printf 'info: %s\n' "$1" >&2
    }

    ${codexIdleCheck}

    [ -f "$pending_restart" ] || exit 0

    exec 9>"$state_dir/tool-update.lock"
    if ! ${pkgs.util-linux}/bin/flock -n 9; then
      log_info "tool maintenance is still running; leaving restart queued"
      exit 0
    fi

    generation="$(sed -n 's/^generation=//p' "$pending_restart")"
    previous="$(sed -n 's/^previous=//p' "$pending_restart")"
    [ -d "$generation" ] || {
      log_info "queued generation is missing; leaving restart queued"
      exit 1
    }

    if ! is_codex_idle; then
      log_info "Codex reports active or unknown work; leaving restart queued"
      exit 0
    fi

    sleep 5

    if [ ! -f "$pending_restart" ]; then
      log_info "queued restart was already applied by another service start"
      exit 0
    fi

    if ! is_codex_idle; then
      log_info "Codex is no longer idle; leaving restart queued"
      exit 0
    fi

    log_info "Codex reports all work complete; activating queued generation"
    current_tmp="$CODEX_TOOL_ROOT/current.tmp"
    rm -f "$current_tmp"
    ln -s "$generation" "$current_tmp"
    mv -Tf "$current_tmp" "$CODEX_TOOL_CURRENT"
    systemctl restart codex-app-server.service
    systemctl restart codex-web.service

    healthy=0
    for _ in $(seq 1 90); do
      if su-exec codex:codex ${codexAppServerStatus}/bin/codex-app-server-status --health >/dev/null 2>&1 \
        && curl -fsS --max-time 5 http://127.0.0.1:8214/ >/dev/null; then
        healthy=1
        break
      fi
      sleep 1
    done
    if [ "$healthy" -eq 1 ]; then
      rm -f "$pending_restart"
      log_info "queued Codex generation is healthy"
      exit 0
    fi

    log_info "queued generation failed health checks; restoring last-good generation"
    if [ -n "$previous" ] && [ -d "$previous" ]; then
      rm -f "$current_tmp"
      ln -s "$previous" "$current_tmp"
      mv -Tf "$current_tmp" "$CODEX_TOOL_CURRENT"
      systemctl restart codex-app-server.service
      systemctl restart codex-web.service
    fi
    rm -f "$pending_restart"
    exit 1
  '';

  codexWebMonitor = pkgs.writeShellScriptBin "codex-web-monitor" ''
    set -eu

    ${codexRuntimeEnv}

    log_file="$HOME/.codex-container/logs/codex-web-monitor.log"
    mkdir -p "$(dirname "$log_file")"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$log_file"
    }

    if ! systemctl is-active --quiet codex-app-server.service; then
      log_info "codex-app-server.service is not active; restarting after process loss"
      systemctl reset-failed codex-app-server.service || true
      systemctl restart codex-app-server.service
    fi

    if ! systemctl is-active --quiet codex-web.service \
      || ! curl -fsS --max-time 5 http://127.0.0.1:8214/ >/dev/null; then
      log_info "Codex web bridge is unavailable; restarting bridge without interrupting app-server"
      systemctl reset-failed codex-web.service || true
      systemctl restart codex-web.service
      exit 0
    fi

    if ! su-exec codex:codex ${codexAppServerStatus}/bin/codex-app-server-status --health >/dev/null 2>&1; then
      log_info "app-server protocol is unavailable while its process is active; restart deferred"
      exit 0
    fi

    log_info "healthy"
  '';

  codexContainerHealth = pkgs.writeShellScriptBin "codex-container-health" ''
    set -eu

    ${codexIdleCheck}

    read -r uptime _ < /proc/uptime
    uptime_seconds="''${uptime%%.*}"
    if ! manager_started_usec="$(${pkgs.systemd}/bin/systemctl show -p UserspaceTimestampMonotonic --value)"; then
      exit 0
    fi
    case "$manager_started_usec" in
      ""|*[!0-9]*)
        container_age_seconds=1200
        ;;
      *)
        container_age_seconds=$((uptime_seconds - (manager_started_usec / 1000000)))
        if [ "$container_age_seconds" -lt 0 ]; then
          container_age_seconds=1200
        fi
        ;;
    esac
    if ! setup_state="$(${pkgs.systemd}/bin/systemctl show codex-container-setup.service -p ActiveState --value)"; then
      exit 0
    fi
    if ! bootstrap_state="$(${pkgs.systemd}/bin/systemctl show codex-bootstrap.service -p ActiveState --value)"; then
      exit 0
    fi
    if ! web_state="$(${pkgs.systemd}/bin/systemctl show codex-web.service -p ActiveState --value)"; then
      exit 0
    fi
    if ! app_state="$(${pkgs.systemd}/bin/systemctl show codex-app-server.service -p ActiveState --value)"; then
      exit 0
    fi

    if [ "$container_age_seconds" -lt 1200 ] \
      && { [ "$setup_state" = "activating" ] \
        || [ "$bootstrap_state" = "activating" ] \
        || [ "$web_state" = "activating" ] \
        || [ "$app_state" = "activating" ]; }; then
      exit 0
    fi

    if su-exec codex:codex ${codexAppServerStatus}/bin/codex-app-server-status --health >/dev/null 2>&1 \
      && ${pkgs.curl}/bin/curl -fsS --max-time 5 http://127.0.0.1:8214/ >/dev/null; then
      exit 0
    fi

    if ! ${pkgs.systemd}/bin/systemctl is-active --quiet codex-app-server.service; then
      exit 1
    fi

    printf 'warning: Codex health is degraded but activity is active or unknown; container kill deferred\n' >&2
    exit 0
  '';

  codexApplyConfig = pkgs.writeShellScriptBin "codex-apply-config" ''
    set -eu

    ${codexRuntimeEnv}

    recovery_dir="$HOME/.codex-container/recovery"
    last_good="$recovery_dir/last-good"
    log_file="$HOME/.codex-container/logs/codex-apply-config.log"
    systemctl_bin="${pkgs.systemd}/bin/systemctl"
    sudo_bin="/usr/bin/sudo"

    mkdir -p "$recovery_dir" "$(dirname "$log_file")"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" | tee -a "$log_file" >&2
    }

    log_error() {
      printf '%s error: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" | tee -a "$log_file" >&2
    }

    restore_config() {
      src="$1"
      if [ ! -d "$src" ]; then
        log_error "no last-good config snapshot exists at $src"
        return 1
      fi

      rm -f "$CODEX_HOME/config.toml" "$CODEX_HOME"/*.config.toml \
        "$CODEX_HOME/AGENTS.md" "$CODEX_HOME/AGENTS.override.md" \
        "$CODEX_HOME/hooks.json"
      rm -rf "$CODEX_HOME/agents"
      if [ -d "$src/config" ]; then
        tar -C "$src/config" -cf - . | tar -C "$CODEX_HOME" -xf -
      fi
    }

    validate_config() {
      command -v codex >/dev/null 2>&1 || {
        log_error "codex CLI is not installed"
        return 1
      }

      find "$CODEX_HOME" -maxdepth 1 -type f \
        \( -name 'config.toml' -o -name '*.config.toml' \) -print \
        | while IFS= read -r config_file; do
          python3 -c 'import pathlib, sys, tomllib; tomllib.loads(pathlib.Path(sys.argv[1]).read_text())' "$config_file"
        done
      if [ -f "$CODEX_HOME/hooks.json" ]; then
        jq -e . "$CODEX_HOME/hooks.json" >/dev/null
      fi
      codex doctor --json >/dev/null
    }

    restart_runtime() {
      "$sudo_bin" -n "$systemctl_bin" reset-failed codex-app-server.service
      "$sudo_bin" -n "$systemctl_bin" restart codex-app-server.service
      "$sudo_bin" -n "$systemctl_bin" reset-failed codex-web.service
      "$sudo_bin" -n "$systemctl_bin" restart codex-web.service
    }

    wait_healthy() {
      for _ in $(seq 1 90); do
        if ${codexAppServerStatus}/bin/codex-app-server-status --health >/dev/null 2>&1 \
          && curl -fsS --max-time 5 http://127.0.0.1:8214/ >/dev/null; then
          return 0
        fi
        sleep 1
      done
      return 1
    }

    apply_config() {
      log_info "validating Codex config"
      validate_config

      if [ ! -d "$last_good" ]; then
        log_error "no last-good config snapshot exists; wait for codex-app-server.service to start successfully once"
        exit 1
      fi

      if ! ${codexAppServerStatus}/bin/codex-app-server-status --idle >/dev/null 2>&1; then
        log_error "Codex has active or unknown work; config apply blocked"
        exit 1
      fi

      log_info "restarting Codex app-server and web bridge"
      restart_runtime

      if wait_healthy; then
        log_info "Codex runtime is healthy"
        exit 0
      fi

      log_error "Codex did not become healthy; restoring last-good config"
      restore_config "$last_good"
      validate_config
      restart_runtime

      if wait_healthy; then
        log_info "rollback restored a healthy Codex runtime"
        exit 1
      fi

      log_error "rollback did not restore a healthy Codex runtime"
      exit 1
    }

    case "''${1:-apply}" in
      apply) apply_config ;;
      *)
        printf 'usage: codex-apply-config [apply]\n' >&2
        exit 2
        ;;
    esac
  '';

  codexUserUnits = pkgs.writeShellScriptBin "codex-user-units" ''
    set -eu

    ${codexRuntimeEnv}

    usage() {
      cat >&2 <<EOF
    usage:
      codex-user-units reload
      codex-user-units enable-now <unit>...
      codex-user-units disable-now <unit>...
      codex-user-units restart <unit>...
      codex-user-units status <unit>...
      codex-user-units list-timers
    EOF
      exit 2
    }

    systemctl_user() {
      systemctl --user "$@"
    }

    [ "$#" -ge 1 ] || usage
    command="$1"
    shift

    case "$command" in
      reload)
        [ "$#" -eq 0 ] || usage
        systemctl_user daemon-reload
        ;;
      enable-now)
        [ "$#" -ge 1 ] || usage
        systemctl_user daemon-reload
        systemctl_user enable --now "$@"
        ;;
      disable-now)
        [ "$#" -ge 1 ] || usage
        systemctl_user disable --now "$@"
        systemctl_user daemon-reload
        ;;
      restart)
        [ "$#" -ge 1 ] || usage
        systemctl_user daemon-reload
        systemctl_user restart "$@"
        ;;
      status)
        [ "$#" -ge 1 ] || usage
        systemctl_user status --no-pager "$@"
        ;;
      list-timers)
        [ "$#" -eq 0 ] || usage
        systemctl_user list-timers --all --no-pager
        ;;
      *)
        usage
        ;;
    esac
  '';

  codexRunHooks = pkgs.writeShellScriptBin "codex-run-hooks" ''
    set -eu

    hook_set="''${1:-}"
    if [ -z "$hook_set" ]; then
      printf 'usage: codex-run-hooks <hook-set>\n' >&2
      exit 2
    fi

    ${codexRuntimeEnv}
    export CODEX_HOOK_SET="$hook_set"

    hook_dir="$HOME/.codex-container/hooks/$hook_set"
    log_file="$HOME/.codex-container/logs/codex-hooks.log"
    mkdir -p "$(dirname "$log_file")" "$hook_dir"

    log_info() {
      printf '%s %s: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$hook_set" "$1" >> "$log_file"
    }

    if [ ! -d "$hook_dir" ]; then
      log_info "missing hook directory; skipping"
      exit 0
    fi

    found=0
    for hook in "$hook_dir"/*; do
      if [ ! -f "$hook" ] || [ ! -x "$hook" ]; then
        continue
      fi

      found=1
      log_info "running $(basename "$hook")"
      if "$hook" >> "$log_file" 2>&1; then
        log_info "completed $(basename "$hook")"
      else
        hook_status="$?"
        log_info "failed $(basename "$hook") with status $hook_status; continuing"
      fi
    done

    if [ "$found" -eq 0 ]; then
      log_info "no executable hooks"
    fi
  '';

  codexDoctor = pkgs.writeShellScriptBin "codex-doctor" ''
    set -eu

    ${codexRuntimeEnv}

    codex doctor --json
    ${codexRunHooks}/bin/codex-run-hooks doctor.d
  '';

  codexBootstrap = pkgs.writeShellScriptBin "codex-bootstrap" ''
    set -eu

    ${codexRuntimeEnv}

    ${codexRunHooks}/bin/codex-run-hooks bootstrap.d
    ${codexRunHooks}/bin/codex-run-hooks before-codex.d
  '';

  codexSnapshotConfig = pkgs.writeShellScriptBin "codex-snapshot-config" ''
    set -eu

    ${codexRuntimeEnv}

    recovery_dir="$HOME/.codex-container/recovery"
    last_good="$recovery_dir/last-good"
    tmp="$recovery_dir/last-good.tmp"

    mkdir -p "$recovery_dir"
    rm -rf "$tmp"
    mkdir -p "$tmp"

    mkdir -p "$tmp/config"
    for config_file in config.toml AGENTS.md AGENTS.override.md hooks.json; do
      if [ -f "$CODEX_HOME/$config_file" ]; then
        cp -a "$CODEX_HOME/$config_file" "$tmp/config/"
      fi
    done
    find "$CODEX_HOME" -maxdepth 1 -type f -name '*.config.toml' -exec cp -a {} "$tmp/config/" \;
    if [ -d "$CODEX_HOME/agents" ]; then
      cp -a "$CODEX_HOME/agents" "$tmp/config/"
    fi

    rm -rf "$last_good"
    mv "$tmp" "$last_good"
  '';

  codexTunnel = pkgs.writeShellScriptBin "codex-tunnel" ''
    set -eu

    ${codexRuntimeEnv}

    tunnel_dir="$HOME/.codex-container/tunnels"
    unit_dir="$HOME/.config/systemd/user"
    log_dir="$HOME/.codex-container/logs/tunnels"

    usage() {
      cat >&2 <<EOF
    usage:
      codex-tunnel start <name> <port>
      codex-tunnel stop <name>
      codex-tunnel restart <name> <port>
      codex-tunnel status <name>
      codex-tunnel url <name>
      codex-tunnel list
      codex-tunnel remove <name>
    EOF
      exit 2
    }

    ensure_state() {
      mkdir -p "$tunnel_dir" "$unit_dir" "$log_dir"
    }

    validate_name() {
      name="$1"
      case "$name" in
        ""|"-"*|*"-"|*[!a-z0-9-]*)
          printf 'error: name must be a lowercase DNS label using a-z, 0-9, and hyphen\n' >&2
          exit 2
          ;;
      esac
      if [ "''${#name}" -gt 63 ]; then
        printf 'error: name must be 63 characters or fewer\n' >&2
        exit 2
      fi
    }

    validate_port() {
      case "$1" in
        ""|*[!0-9]*)
          printf 'error: port must be numeric\n' >&2
          exit 2
          ;;
      esac
      if [ "$1" -lt 1 ] || [ "$1" -gt 65535 ]; then
        printf 'error: port must be between 1 and 65535\n' >&2
        exit 2
      fi
    }

    unit_name() {
      printf 'codex-tunnel-%s.service' "$1"
    }

    unit_path() {
      printf '%s/%s' "$unit_dir" "$(unit_name "$1")"
    }

    log_path() {
      printf '%s/%s.log' "$log_dir" "$1"
    }

    write_unit() {
      name="$1"
      port="$2"
      ensure_state
      validate_name "$name"
      validate_port "$port"
      log_file="$(log_path "$name")"
      cat > "$(unit_path "$name")" <<EOF
    [Unit]
    Description=Codex quick tunnel: $name
    After=default.target

    [Service]
    Type=simple
    ExecStart=${pkgs.cloudflared}/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:$port
    Restart=always
    RestartSec=5
    StandardOutput=append:$log_file
    StandardError=append:$log_file

    [Install]
    WantedBy=default.target
    EOF
      printf '%s\t%s\n' "$name" "$port" > "$tunnel_dir/$name.tsv"
    }

    systemctl_user() {
      systemctl --user "$@"
    }

    start_tunnel() {
      [ "$#" -eq 2 ] || usage
      name="$1"
      port="$2"
      write_unit "$name" "$port"
      systemctl_user daemon-reload
      systemctl_user enable --now "$(unit_name "$name")"
      printf 'started %s for http://127.0.0.1:%s\n' "$name" "$port"
      printf 'logs: %s\n' "$(log_path "$name")"
    }

    stop_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      systemctl_user stop "$(unit_name "$name")" || true
    }

    restart_tunnel() {
      [ "$#" -eq 2 ] || usage
      stop_tunnel "$1"
      start_tunnel "$1" "$2"
    }

    status_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      systemctl_user status --no-pager "$(unit_name "$name")"
    }

    url_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      log_file="$(log_path "$name")"
      if [ ! -f "$log_file" ]; then
        printf 'error: no log file for tunnel %s\n' "$name" >&2
        exit 1
      fi
      url="$(grep -Eo 'https://[-a-zA-Z0-9.]+\\.trycloudflare\\.com' "$log_file" | tail -n 1 || true)"
      if [ -z "$url" ]; then
        printf 'error: no quick tunnel URL found yet for %s\n' "$name" >&2
        exit 1
      fi
      printf '%s\n' "$url"
    }

    list_tunnels() {
      [ "$#" -eq 0 ] || usage
      ensure_state
      found=0
      for entry in "$tunnel_dir"/*.tsv; do
        [ -f "$entry" ] || continue
        found=1
        IFS="$(printf '\t')" read -r name port < "$entry"
        state="$(systemctl_user is-active "$(unit_name "$name")" 2>/dev/null || true)"
        printf '%s\t%s\t%s' "$name" "$port" "$state"
        if url="$(codex-tunnel url "$name" 2>/dev/null)"; then
          printf '\t%s' "$url"
        fi
        printf '\n'
      done
      [ "$found" -eq 1 ] || true
    }

    remove_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      systemctl_user disable --now "$(unit_name "$name")" || true
      rm -f "$(unit_path "$name")" "$tunnel_dir/$name.tsv"
      systemctl_user daemon-reload
    }

    [ "$#" -ge 1 ] || usage
    command="$1"
    shift
    case "$command" in
      start) start_tunnel "$@" ;;
      stop) stop_tunnel "$@" ;;
      restart) restart_tunnel "$@" ;;
      status) status_tunnel "$@" ;;
      url) url_tunnel "$@" ;;
      list|ls) list_tunnels "$@" ;;
      remove|rm|delete) remove_tunnel "$@" ;;
      *) usage ;;
    esac
  '';

  codexOllamaCatalogRefresh = pkgs.writeShellScriptBin "codex-ollama-catalog-refresh" ''
    set -eu

    ${codexRuntimeEnv}

    if [ -z "''${OLLAMA_API_KEY:-}" ]; then
      printf 'error: OLLAMA_API_KEY is not configured\n' >&2
      exit 1
    fi

    catalog_dir="$(dirname "$CODEX_OLLAMA_CATALOG")"
    mkdir -p "$catalog_dir"
    work_dir="$(mktemp -d "$catalog_dir/.refresh.XXXXXX")"
    trap 'rm -rf "$work_dir"' EXIT

    auth_header_file="$work_dir/authorization.header"
    printf 'Authorization: Bearer %s\n' "$OLLAMA_API_KEY" > "$auth_header_file"
    chmod 0600 "$auth_header_file"
    curl -fsS --retry 3 --connect-timeout 15 --max-time 60 \
      -H "@$auth_header_file" https://ollama.com/api/tags > "$work_dir/tags.json"

    jq -r '.models[]? | .model // .name // empty' "$work_dir/tags.json" \
      | sort -u > "$work_dir/models"
    : > "$work_dir/catalog.jsonl"
    while IFS= read -r model; do
      [ -n "$model" ] || continue
      payload="$(jq -cn --arg model "$model" '{model: $model}')"
      if ! curl -fsS --retry 2 --connect-timeout 15 --max-time 60 \
        -H "@$auth_header_file" -H 'Content-Type: application/json' \
        --data "$payload" https://ollama.com/api/show > "$work_dir/show.json"; then
        printf 'warning: failed to inspect Ollama model %s\n' "$model" >&2
        continue
      fi
      jq -c --arg name "$model" '
        (.capabilities // []) as $capabilities
        | select($capabilities | index("tools"))
        | {name: $name, capabilities: $capabilities}
      ' "$work_dir/show.json" >> "$work_dir/catalog.jsonl"
    done < "$work_dir/models"

    jq -s 'sort_by(.name)' "$work_dir/catalog.jsonl" > "$work_dir/catalog.json"
    jq -e 'all(.[]; (.capabilities | index("tools")) != null)' "$work_dir/catalog.json" >/dev/null
    install -m 0600 "$work_dir/catalog.json" "$CODEX_OLLAMA_CATALOG.tmp"
    mv "$CODEX_OLLAMA_CATALOG.tmp" "$CODEX_OLLAMA_CATALOG"
  '';

  codexAppServerRun = pkgs.writeShellScriptBin "codex-app-server-run" ''
    set -eu

    ${codexRuntimeEnv}
    rm -f "$CODEX_APP_SERVER_SOCKET"
    cd /home/codex
    exec "$CODEX_TOOL_CURRENT/codex/bin/codex" app-server \
      --listen "unix://$CODEX_APP_SERVER_SOCKET"
  '';

  codexOllamaProxyRun = pkgs.writeShellScriptBin "codex-ollama-cloud-proxy-run" ''
    set -eu

    ${codexRuntimeEnv}
    exec ${codexOllamaProxy}/bin/codex-ollama-cloud-proxy
  '';

  codexWebRun = pkgs.writeShellScriptBin "codex-web-run" ''
    set -eu

    ${codexRuntimeEnv}
    export CODEX_UNIX_SOCKET="$CODEX_APP_SERVER_SOCKET"
    export CODEX_REMOTE_PROXY_PATH="$CODEX_TOOL_CURRENT/proxy/bin/codex_remote_proxy"
    export CODEX_CLI_PATH=${codexAppServerAdapter}/bin/codex-app-server-adapter

    for _ in $(seq 1 90); do
      if ${codexAppServerStatus}/bin/codex-app-server-status --health >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    cd /home/codex
    patched_web="$(${codexPwaPrepare}/bin/codex-pwa-prepare "$CODEX_TOOL_CURRENT/web")"
    exec "$patched_web/bin/codex-web" --host 0.0.0.0 --port 8214
  '';

  codexContainerSetup = pkgs.writeShellScriptBin "codex-container-setup" ''
    set -eu

    ${codexRuntimeEnv}

    mkdir -p \
      "$HOME/.local/bin" \
      "$CODEX_TOOL_ROOT/generations" \
      "$XDG_DATA_HOME" \
      "$XDG_STATE_HOME" \
      "$XDG_CACHE_HOME" \
      "$HOME/.codex" \
      "$HOME/.codex-container/logs/tunnels" \
      "$HOME/.codex-container/recovery" \
      "$HOME/.codex-container/tunnels" \
      "$HOME/.codex-container/hooks/bootstrap.d" \
      "$HOME/.codex-container/hooks/before-codex.d" \
      "$HOME/.codex-container/hooks/doctor.d" \
      "$HOME/.local/state/codex-ollama" \
      "$HOME/.config/systemd/user" \
      /workspace \
      /mnt/share \
      /var/lib/docker \
      /var/run \
      /tmp \
      /run/user/3000 \
      /run/codex-app-server
    chown -R codex:codex \
      "$HOME/.codex" \
      "$HOME/.codex-container" \
      "$HOME/.config/systemd" \
      "$HOME/.local" \
      /run/codex-app-server
    chown codex:codex /run/user/3000 /workspace
    chmod 0700 /run/user/3000
    if [ ! -e "$HOME/tools" ] && [ -d /workspace/ghostship-agent/tools ]; then
      ln -s /workspace/ghostship-agent/tools "$HOME/tools"
      chown -h codex:codex "$HOME/tools"
    fi
    if [ ! -L "$CODEX_TOOL_CURRENT" ]; then
      ln -s ${codexToolFallback} "$CODEX_TOOL_CURRENT"
      chown -h codex:codex "$CODEX_TOOL_CURRENT"
    fi
    cat > "$HOME/.local/bin/codex" <<'EOF'
    #!/bin/sh
    exec /home/codex/.local/share/codex-tools/current/codex/bin/codex "$@"
    EOF
    chown codex:codex "$HOME/.local/bin/codex"
    chmod 0755 "$HOME/.local/bin/codex"
    cat > "$HOME/.local/bin/codex-web-run" <<'EOF'
    #!/bin/sh
    exec ${codexWebRun}/bin/codex-web-run "$@"
    EOF
    chown codex:codex "$HOME/.local/bin/codex-web-run"
    chmod 0755 "$HOME/.local/bin/codex-web-run"
    cat > "$HOME/.local/bin/codex-tunnel" <<'EOF'
    #!/bin/sh
    exec ${codexTunnel}/bin/codex-tunnel "$@"
    EOF
    chown codex:codex "$HOME/.local/bin/codex-tunnel"
    chmod 0755 "$HOME/.local/bin/codex-tunnel"
    cat > "$HOME/.local/bin/codex-user-units" <<'EOF'
    #!/bin/sh
    exec ${codexUserUnits}/bin/codex-user-units "$@"
    EOF
    chown codex:codex "$HOME/.local/bin/codex-user-units"
    chmod 0755 "$HOME/.local/bin/codex-user-units"
    cat > "$HOME/.local/bin/codex-apply-config" <<'EOF'
    #!/bin/sh
    exec ${codexApplyConfig}/bin/codex-apply-config "$@"
    EOF
    chown codex:codex "$HOME/.local/bin/codex-apply-config"
    chmod 0755 "$HOME/.local/bin/codex-apply-config"
  '';

  codexDockerdRun = pkgs.writeShellScriptBin "codex-dockerd-run" ''
    set -eu

    ${codexRuntimeEnv}

    rm -f /var/run/docker.pid
    exec dockerd \
      --host=unix:///var/run/docker.sock \
      --group=codex \
      --data-root=/var/lib/docker \
      --storage-driver=vfs \
      --iptables=false \
      --ip-masq=false \
      --bridge=none
  '';

  codexEntrypoint = pkgs.writeShellScriptBin "codex-systemd-entrypoint" ''
    set -eu

    exec ${pkgs.systemd}/lib/systemd/systemd
  '';

  codexImageContents = codexPackages ++ [
    codexToolFallback
    codexEntrypoint
    codexContainerSetup
    codexDockerdRun
    codexAppServerRun
    codexAppServerAdapter
    codexAppServerStatus
    codexOllamaProxy
    codexOllamaProxyRun
    codexOllamaCatalogRefresh
    codexWebRun
    codexToolMaintenance
    codexToolAutoUpdate
    codexToolUpdateRestart
    codexWebMonitor
    codexContainerHealth
    codexRunHooks
    codexDoctor
    codexApplyConfig
    codexUserUnits
    codexBootstrap
    codexSnapshotConfig
    codexTunnel
    pkgs.dockerTools.binSh
    pkgs.dockerTools.usrBinEnv
    pkgs.dockerTools.caCertificates
  ];

  codexImage = pkgs.dockerTools.buildLayeredImageWithNixDb {
    name = imageName;
    tag = imageTag;
    contents = codexImageContents;
    extraCommands = ''
      mkdir -p etc/nix etc/pam.d etc/sudoers.d etc/systemd/system/multi-user.target.wants etc/systemd/user/sockets.target.wants usr/bin usr/share/systemd/user nix/store nix/var/log/nix nix/var/nix tmp workspace home/codex
      mkdir -p mnt/share run/user var/empty var/lib/docker var/log/journal var/run
      chmod 1777 tmp
      chmod 0555 var/empty
      cp ${pkgs.sudo}/bin/sudo usr/bin/sudo
      chmod 0755 usr/bin/sudo
      cat > etc/passwd <<'EOF'
      root:x:0:0:root:/root:/bin/sh
      codex:x:3000:3000:Codex:/home/codex:/bin/sh
      EOF
      cat > etc/group <<'EOF'
      root:x:0:
      codex:x:3000:
      EOF
      nixbld_members=""
      nixbld_index=1
      while [ "$nixbld_index" -le 32 ]; do
        printf 'nixbld%s:x:%s:30000:Nix build user %s:/var/empty:/bin/sh\n' \
          "$nixbld_index" "$((30000 + nixbld_index))" "$nixbld_index" >> etc/passwd
        if [ -n "$nixbld_members" ]; then
          nixbld_members="$nixbld_members,"
        fi
        nixbld_members="$nixbld_members""nixbld$nixbld_index"
        nixbld_index="$((nixbld_index + 1))"
      done
      printf 'nixbld:x:30000:%s\n' "$nixbld_members" >> etc/group
      cat > etc/nix/nix.conf <<'EOF'
      experimental-features = nix-command flakes
      sandbox = false
      allowed-users = root codex
      trusted-users = root
      build-users-group = nixbld
      EOF
      rm -f etc/sudoers etc/sudoers.d/codex-apply-config etc/pam.d/sudo
      cat > etc/sudoers <<'EOF'
      root ALL=(ALL:ALL) ALL
      #includedir /etc/sudoers.d
      EOF
      chmod 0440 etc/sudoers
      cat > etc/sudoers.d/codex-apply-config <<'EOF'
      codex ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl reset-failed codex-app-server.service
      codex ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl restart codex-app-server.service
      codex ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl reset-failed codex-web.service
      codex ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl restart codex-web.service
      EOF
      chmod 0440 etc/sudoers.d/codex-apply-config
      rm -f etc/pam.d/systemd-user
      cat > etc/pam.d/systemd-user <<'EOF'
      account required ${pkgs.pam}/lib/security/pam_permit.so
      session required ${pkgs.pam}/lib/security/pam_permit.so
      EOF
      cat > etc/pam.d/sudo <<'EOF'
      auth sufficient ${pkgs.pam}/lib/security/pam_permit.so
      account required ${pkgs.pam}/lib/security/pam_permit.so
      session required ${pkgs.pam}/lib/security/pam_permit.so
      EOF
      for system_unit in halt.target shutdown.target final.target systemd-halt.service umount.target; do
        cp -a "${pkgs.systemd}/example/systemd/system/$system_unit" etc/systemd/system/
      done
      cp -a ${pkgs.systemd}/example/systemd/user/. usr/share/systemd/user/
      rm -f etc/systemd/user/dbus.socket etc/systemd/user/dbus.service etc/systemd/user/sockets.target.wants/dbus.socket
      cat > etc/systemd/user/dbus.socket <<'EOF'
      [Unit]
      Description=D-Bus User Message Bus Socket

      [Socket]
      ListenStream=%t/bus
      ExecStartPost=-${pkgs.systemd}/bin/systemctl --user set-environment DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus

      [Install]
      WantedBy=sockets.target
      EOF
      cat > etc/systemd/user/dbus.service <<'EOF'
      [Unit]
      Description=D-Bus User Message Bus
      Documentation=man:dbus-daemon(1)
      Requires=dbus.socket

      [Service]
      Type=notify
      NotifyAccess=main
      ExecStart=${pkgs.dbus}/bin/dbus-daemon --session --address=systemd: --nofork --nopidfile --systemd-activation --syslog-only
      ExecReload=${pkgs.dbus}/bin/dbus-send --print-reply --session --type=method_call --dest=org.freedesktop.DBus / org.freedesktop.DBus.ReloadConfig
      Slice=session.slice
      EOF
      ln -s ../dbus.socket etc/systemd/user/sockets.target.wants/dbus.socket
      cat > etc/systemd/system/codex-container-setup.service <<'EOF'
      [Unit]
      Description=Prepare Codex container state
      DefaultDependencies=no
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      ExecStart=${codexContainerSetup}/bin/codex-container-setup
      RemainAfterExit=yes
      TimeoutStartSec=20m
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/nix-daemon.service <<'EOF'
      [Unit]
      Description=Nix package manager daemon
      DefaultDependencies=no
      After=codex-container-setup.service nix-daemon.socket
      Requires=codex-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=user@3000.service codex-app-server.service codex-bootstrap.service codex-web.service shutdown.target

      [Service]
      Type=simple
      ExecStart=@${pkgs.nix}/bin/nix-daemon nix-daemon --daemon
      KillMode=mixed
      LimitNOFILE=1048576
      Delegate=yes
      Restart=always
      RestartSec=5
      TimeoutStopSec=30s
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/nix-daemon.socket <<'EOF'
      [Unit]
      Description=Nix package manager daemon socket
      DefaultDependencies=no
      After=codex-container-setup.service
      Requires=codex-container-setup.service
      Conflicts=shutdown.target
      Before=nix-daemon.service user@3000.service codex-app-server.service codex-bootstrap.service codex-web.service shutdown.target

      [Socket]
      ListenStream=/nix/var/nix/daemon-socket/socket
      SocketMode=0666
      DirectoryMode=0755
      RemoveOnStop=true

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/user@.service <<'EOF'
      [Unit]
      Description=Codex user manager for UID %i
      Documentation=man:user@.service(5)
      DefaultDependencies=no
      After=codex-container-setup.service nix-daemon.socket
      Requires=codex-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=codex-app-server.service codex-bootstrap.service codex-web.service shutdown.target
      IgnoreOnIsolate=yes

      [Service]
      User=%i
      PAMName=systemd-user
      Type=notify-reload
      Environment=HOME=/home/codex
      Environment=USER=codex
      Environment=LOGNAME=codex
      Environment=XDG_RUNTIME_DIR=/run/user/%i
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%i/bus
      Environment=NIX_REMOTE=daemon
      ExecStart=${pkgs.systemd}/lib/systemd/systemd --user
      Slice=user-%i.slice
      ReloadSignal=RTMIN+25
      KillMode=mixed
      Delegate=pids memory cpu
      DelegateSubgroup=init.scope
      TasksMax=infinity
      TimeoutStopSec=10s
      KeyringMode=inherit
      OOMScoreAdjust=100
      MemoryPressureWatch=skip
      Restart=always
      RestartSec=5

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/dockerd.service <<'EOF'
      [Unit]
      Description=Codex Docker daemon
      DefaultDependencies=no
      After=codex-container-setup.service
      Requires=codex-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=simple
      ExecStart=${codexDockerdRun}/bin/codex-dockerd-run
      Restart=always
      RestartSec=5
      TimeoutStopSec=30s
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/codex-bootstrap.service <<'EOF'
      [Unit]
      Description=Run Codex bootstrap hooks
      DefaultDependencies=no
      After=codex-app-server.service codex-web.service
      Requires=codex-app-server.service codex-web.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      User=codex
      Group=codex
      Environment=HOME=/home/codex
      Environment=USER=codex
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=PATH=/home/codex/.local/bin:${codexPath}:/bin:/usr/bin
      ExecStart=${codexBootstrap}/bin/codex-bootstrap
      RemainAfterExit=yes
      TimeoutStartSec=20m
      StandardOutput=append:/home/codex/.codex-container/logs/codex-bootstrap.log
      StandardError=append:/home/codex/.codex-container/logs/codex-bootstrap.log
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/codex-ollama-cloud-proxy.service <<'EOF'
      [Unit]
      Description=Ollama.com API compatibility proxy
      DefaultDependencies=no
      After=codex-container-setup.service
      Requires=codex-container-setup.service
      Conflicts=shutdown.target
      Before=codex-app-server.service shutdown.target

      [Service]
      Type=simple
      User=codex
      Group=codex
      Environment=HOME=/home/codex
      Environment=USER=codex
      Environment=PATH=/home/codex/.local/bin:${codexPath}:/bin:/usr/bin
      ExecStart=${codexOllamaProxyRun}/bin/codex-ollama-cloud-proxy-run
      Restart=always
      RestartSec=5
      TimeoutStopSec=10s
      StandardOutput=append:/home/codex/.codex-container/logs/codex-ollama-cloud-proxy.log
      StandardError=append:/home/codex/.codex-container/logs/codex-ollama-cloud-proxy.log
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/codex-app-server.service <<'EOF'
      [Unit]
      Description=Persistent Codex app server
      DefaultDependencies=no
      After=codex-container-setup.service nix-daemon.socket user@3000.service dockerd.service codex-ollama-cloud-proxy.service
      Requires=codex-container-setup.service nix-daemon.socket user@3000.service dockerd.service codex-ollama-cloud-proxy.service
      Conflicts=shutdown.target
      Before=codex-web.service shutdown.target

      [Service]
      Type=simple
      User=codex
      Group=codex
      Environment=HOME=/home/codex
      Environment=USER=codex
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=PATH=/home/codex/.local/bin:${codexPath}:/bin:/usr/bin
      ExecStart=${codexAppServerRun}/bin/codex-app-server-run
      ExecStartPost=${codexSnapshotConfig}/bin/codex-snapshot-config
      Restart=always
      RestartSec=5
      TimeoutStartSec=20m
      TimeoutStopSec=30s
      SuccessExitStatus=0 143
      StandardOutput=append:/home/codex/.codex-container/logs/codex-app-server.service.log
      StandardError=append:/home/codex/.codex-container/logs/codex-app-server.service.log
      MemoryHigh=32G
      MemoryMax=40G
      OOMPolicy=continue
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/codex-web.service <<'EOF'
      [Unit]
      Description=Codex Web
      DefaultDependencies=no
      After=codex-app-server.service
      Requires=codex-app-server.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=simple
      User=codex
      Group=codex
      Environment=HOME=/home/codex
      Environment=USER=codex
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=PATH=/home/codex/.local/bin:${codexPath}:/bin:/usr/bin
      ExecStart=${codexWebRun}/bin/codex-web-run
      Restart=always
      RestartSec=5
      TimeoutStartSec=20m
      TimeoutStopSec=10s
      SuccessExitStatus=0 143
      StandardOutput=append:/home/codex/.codex-container/logs/codex-web.service.log
      StandardError=append:/home/codex/.codex-container/logs/codex-web.service.log
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/codex-ollama-catalog-refresh.service <<'EOF'
      [Unit]
      Description=Refresh tool-capable Ollama.com model catalog
      DefaultDependencies=no
      After=codex-container-setup.service
      Requires=codex-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      User=codex
      Group=codex
      Environment=HOME=/home/codex
      Environment=USER=codex
      Environment=PATH=/home/codex/.local/bin:${codexPath}:/bin:/usr/bin
      ExecStart=${codexOllamaCatalogRefresh}/bin/codex-ollama-catalog-refresh
      StandardOutput=append:/home/codex/.codex-container/logs/codex-ollama-catalog-refresh.log
      StandardError=append:/home/codex/.codex-container/logs/codex-ollama-catalog-refresh.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/codex-ollama-catalog-refresh.timer <<'EOF'
      [Unit]
      Description=Periodic Ollama.com model catalog refresh
      DefaultDependencies=no
      After=codex-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=30s
      OnUnitActiveSec=4h
      Persistent=true
      Unit=codex-ollama-catalog-refresh.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/codex-tool-auto-update.service <<'EOF'
      [Unit]
      Description=Stage Codex Web and CLI updates
      DefaultDependencies=no
      After=codex-bootstrap.service
      Requires=codex-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/codex/.local/bin:${codexPath}:/bin:/usr/bin
      ExecStart=${codexToolAutoUpdate}/bin/codex-tool-auto-update
      StandardOutput=append:/home/codex/.codex-container/logs/codex-tool-auto-update.log
      StandardError=append:/home/codex/.codex-container/logs/codex-tool-auto-update.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/codex-tool-auto-update.timer <<'EOF'
      [Unit]
      Description=Periodic Codex Web and CLI updates
      DefaultDependencies=no
      After=codex-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=10m
      OnUnitActiveSec=4h
      Persistent=true
      Unit=codex-tool-auto-update.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/codex-tool-update-restart.service <<'EOF'
      [Unit]
      Description=Restart Codex after queued maintenance becomes idle
      DefaultDependencies=no
      After=codex-bootstrap.service
      Requires=codex-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/codex/.local/bin:${codexPath}:/bin:/usr/bin
      ExecStart=${codexToolUpdateRestart}/bin/codex-tool-update-restart
      StandardOutput=append:/home/codex/.codex-container/logs/codex-tool-update-restart.log
      StandardError=append:/home/codex/.codex-container/logs/codex-tool-update-restart.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/codex-tool-update-restart.timer <<'EOF'
      [Unit]
      Description=Apply queued Codex maintenance when idle
      DefaultDependencies=no
      After=codex-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=codex-tool-update-restart.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/codex-web-monitor.service <<'EOF'
      [Unit]
      Description=Monitor Codex web and app server
      DefaultDependencies=no
      After=codex-web.service
      Wants=codex-web.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/codex/.local/bin:${codexPath}:/bin:/usr/bin
      ExecStart=${codexWebMonitor}/bin/codex-web-monitor
      StandardOutput=append:/home/codex/.codex-container/logs/codex-web-monitor.log
      StandardError=append:/home/codex/.codex-container/logs/codex-web-monitor.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/codex-web-monitor.timer <<'EOF'
      [Unit]
      Description=Periodic Codex web monitor
      DefaultDependencies=no
      After=codex-web.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=codex-web-monitor.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/multi-user.target <<'EOF'
      [Unit]
      Description=Codex Multi-User System
      DefaultDependencies=no
      Wants=codex-container-setup.service nix-daemon.socket nix-daemon.service user@3000.service dockerd.service codex-ollama-cloud-proxy.service codex-app-server.service codex-web.service codex-bootstrap.service codex-ollama-catalog-refresh.timer codex-tool-auto-update.timer codex-tool-update-restart.timer codex-web-monitor.timer
      After=codex-container-setup.service nix-daemon.socket user@3000.service dockerd.service
      AllowIsolate=yes
      EOF
      rm -f etc/systemd/system/docker.service \
        etc/systemd/system/docker.socket \
        etc/systemd/system/multi-user.target.wants/docker.service \
        etc/systemd/system/sockets.target.wants/docker.socket
      ln -s multi-user.target etc/systemd/system/default.target
      ln -s ../codex-container-setup.service etc/systemd/system/multi-user.target.wants/codex-container-setup.service
      ln -s ../nix-daemon.socket etc/systemd/system/multi-user.target.wants/nix-daemon.socket
      ln -s ../nix-daemon.service etc/systemd/system/multi-user.target.wants/nix-daemon.service
      ln -s ../user@.service etc/systemd/system/multi-user.target.wants/user@3000.service
      ln -s ../dockerd.service etc/systemd/system/multi-user.target.wants/dockerd.service
      ln -s ../codex-ollama-cloud-proxy.service etc/systemd/system/multi-user.target.wants/codex-ollama-cloud-proxy.service
      ln -s ../codex-app-server.service etc/systemd/system/multi-user.target.wants/codex-app-server.service
      ln -s ../codex-bootstrap.service etc/systemd/system/multi-user.target.wants/codex-bootstrap.service
      ln -s ../codex-web.service etc/systemd/system/multi-user.target.wants/codex-web.service
      ln -s ../codex-ollama-catalog-refresh.timer etc/systemd/system/multi-user.target.wants/codex-ollama-catalog-refresh.timer
      ln -s ../codex-tool-auto-update.timer etc/systemd/system/multi-user.target.wants/codex-tool-auto-update.timer
      ln -s ../codex-tool-update-restart.timer etc/systemd/system/multi-user.target.wants/codex-tool-update-restart.timer
      ln -s ../codex-web-monitor.timer etc/systemd/system/multi-user.target.wants/codex-web-monitor.timer
    '';
    fakeRootCommands = ''
      chown -R root:root nix/store nix/var/log/nix nix/var/nix
      chmod -R u+rwX,go+rX nix/store nix/var/log/nix nix/var/nix
      chown 0:0 usr/bin/sudo
      chmod 4755 usr/bin/sudo
    '';
    config = {
      Cmd = [ "${codexEntrypoint}/bin/codex-systemd-entrypoint" ];
      Env = [
        "HOME=/home/codex"
        "USER=codex"
        "DOCKER_HOST=unix:///var/run/docker.sock"
        "XDG_RUNTIME_DIR=/run/user/3000"
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus"
        "XDG_CONFIG_HOME=/home/codex/.config"
        "XDG_STATE_HOME=/home/codex/.local/state"
        "XDG_CACHE_HOME=/home/codex/.cache"
        "XDG_DATA_HOME=/home/codex/.local/share"
        "CODEX_HOME=/home/codex/.codex"
        "CODEX_TOOL_ROOT=/home/codex/.local/share/codex-tools"
        "CODEX_TOOL_CURRENT=/home/codex/.local/share/codex-tools/current"
        "CODEX_APP_SERVER_SOCKET=/run/codex-app-server/codex-app-server.sock"
        "CODEX_OLLAMA_CATALOG=/home/codex/.local/state/codex-ollama/catalog.json"
        "OLLAMA_HOST=http://127.0.0.1:11434"
        "PATH=/home/codex/.local/bin:/home/codex/.local/share/codex-tools/current/codex/bin:${codexPath}:/bin:/usr/bin"
        "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "NIX_CONFIG=experimental-features = nix-command flakes"
        "NIX_REMOTE=daemon"
      ];
      WorkingDir = "/home/codex";
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
    extraOptions = [
      "--privileged"
      "--systemd=always"
      "--pids-limit=-1"
      "--stop-timeout=180"
      "--network=ghostship_net"
      "--health-cmd=${codexContainerHealth}/bin/codex-container-health"
      "--health-interval=30s"
      "--health-timeout=15s"
      "--health-retries=5"
      "--health-start-period=5m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "${codexDocker}:/var/lib/docker:rw"
      "${codexWorkspace}:/workspace:rw"
      "${codexHome}:/home/codex:rw"
      "${codexNixRoot}/nix:/nix:rw"
      "${codexSecrets}:${codexSecretsFile}:ro"
      "/mnt/share:/mnt/share:rw"
    ];
    environmentFiles = [ codexSecrets ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/codex 0755 root root -"
    "d ${codexDocker} 0755 root root -"
    "d ${codexHome} 0755 3000 3000 -"
    "d ${codexNixRoot} 0755 root root -"
    "d ${codexNixRoot}/nix 0755 root root -"
    "d ${codexWorkspace} 0755 3000 3000 -"
  ];

  systemd.services.podman-codex = {
    after = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    wants = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    serviceConfig.TimeoutStopSec = lib.mkForce "210s";
    preStart = lib.mkAfter ''
      set -eu

      install -d -m0755 -o root -g root /srv/apps/codex
      install -d -m0755 -o root -g root ${codexDocker}
      install -d -m0755 -o 3000 -g 3000 ${codexHome}
      install -d -m0755 -o root -g root ${codexNixRoot}
      install -d -m0755 -o 3000 -g 3000 ${codexWorkspace}

      nix_store_uri='local?root=${codexNixRoot}'
      ${pkgs.nix}/bin/nix copy \
        --no-check-sigs \
        --to "$nix_store_uri" \
        ${lib.escapeShellArgs (map toString codexImageContents)}

      gcroot_dir=${codexNixRoot}/nix/var/nix/gcroots/ghostship-codex-image
      rm -rf "$gcroot_dir"
      install -d -m0755 -o root -g root "$gcroot_dir"
      for store_path in ${lib.escapeShellArgs (map toString codexImageContents)}; do
        ln -s "$store_path" "$gcroot_dir/$(basename "$store_path")"
      done

      rm -f ${codexNixRoot}/nix/var/nix/temproots/*
      rm -rf ${codexNixRoot}/nix/var/nix/builds/*
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.local/bin
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.local/share
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.local/state
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.cache
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.codex
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.codex-container/logs/tunnels
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.codex-container/recovery
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.codex-container/tunnels
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.codex-container/hooks/bootstrap.d
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.codex-container/hooks/before-codex.d
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.codex-container/hooks/doctor.d
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.local/share/codex-tools/generations
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.local/state/codex-ollama
      install -d -m0755 -o 3000 -g 3000 ${codexHome}/.config/systemd/user

      if [ -e ${codexHome}/.config/systemd/user/codex.service ] \
        && grep -q 'ExecStart=/home/codex/.local/bin/codex-web-run' ${codexHome}/.config/systemd/user/codex.service; then
        rm -f ${codexHome}/.config/systemd/user/codex.service
      fi
      if [ -e ${codexHome}/.config/systemd/user/default.target ] \
        && grep -q 'Codex User Default Target' ${codexHome}/.config/systemd/user/default.target; then
        rm -f ${codexHome}/.config/systemd/user/default.target
      fi
      rm -f ${codexHome}/.config/systemd/user/default.target.wants/codex.service
    '';
  };
}
