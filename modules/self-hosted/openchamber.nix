{
  config,
  lib,
  pkgs,
  ...
}:

let
  openchamberHome = "/srv/apps/openchamber/home";
  openchamberDocker = "/srv/apps/openchamber/docker";
  openchamberNixRoot = "/srv/apps/openchamber/nix-root";
  openchamberToolControl = "/srv/apps/openchamber/tool-update-control";
  openchamberWorkspace = "/srv/apps/openchamber/workspace";
  openchamberSecrets = config.ghostship.selfHostedSecrets.projections.openchamber.path;
  openchamberSecretsFile = "/run/secrets/openchamber.env";
  openchamberDeploymentState = "/var/lib/ghostship/openchamber-deployment";
  externalOpenCode = config.ghostship.openchamber.externalOpenCode.enable;
  nativeResponses = config.ghostship.openchamber.nativeResponses.enable;
  imageName = "localhost/ghostship-openchamber";
  imageTag = "openchamber-runtime";
  # Bump whenever injected runtime safety hooks or wrappers change so an
  # unchanged npm pair is restaged with the new harness contract.
  openchamberHarnessRevision = "2026-09-08.5";
  openchamberGenerationRevision = "${openchamberHarnessRevision}-goal-${toString config.ghostship.openchamber.goalMaxAutoTurns}";

  openchamberPackages = with pkgs; [
    nix
    systemd
    dbus
    pam
    docker
    cloudflared
    sudo
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
    ruff
    basedpyright
    nodejs_24
    typescript-language-server
    prettier
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
    iptables
    iproute2
    kmod
    su-exec
    which
    file
    nil
    nixfmt
    shellcheck
    shfmt
    yq-go
    buildkit
    bubblewrap
    fuse-overlayfs
    bashInteractive
    cacert
  ];

  openchamberPath = lib.makeBinPath openchamberPackages;
  openchamberExternalOpenCodeReady = ''
    opencode_ready() {
      systemctl is-active --quiet opencode.service \
        && curl -fsS --max-time 5 http://127.0.0.1:4096/global/health \
          | jq -e '.healthy == true' >/dev/null 2>&1
    }
  '';
  openchamberRuntimeEnv = ''
    if [ "''${OPENCHAMBER_SKIP_RUNTIME_SECRETS:-0}" != 1 ] \
      && [ -f ${openchamberSecretsFile} ]; then
      set -a
      # shellcheck disable=SC1091
      . ${openchamberSecretsFile}
      set +a
    fi
    export HOME=/home/openchamber
    export USER=openchamber
    export XDG_CONFIG_HOME="''${XDG_CONFIG_HOME:-$HOME/.config}"
    export XDG_STATE_HOME="''${XDG_STATE_HOME:-$HOME/.local/state}"
    export XDG_CACHE_HOME="''${XDG_CACHE_HOME:-$HOME/.cache}"
    export XDG_DATA_HOME="''${XDG_DATA_HOME:-$HOME/.local/share}"
    export NPM_CONFIG_PREFIX="$HOME/.local/share/openchamber-tools/active"
    export npm_config_prefix="$NPM_CONFIG_PREFIX"
    export OPENCODE_AUTOMATION_DIR="$HOME/.automation"
    export OPENCHAMBER_MAINTENANCE_GATE="/var/lib/openchamber-tool-update/admission.lock"
    # ghostship-agent owns the complete on-disk behavior config; runtime overlays
    # are deliberately disabled so timeout and compaction keys have one owner.
    unset OPENCODE_CONFIG_CONTENT
    ${lib.optionalString nativeResponses "export OPENCODE_EXPERIMENTAL_NATIVE_LLM=1"}
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
    export PATH=$HOME/.local/bin:$NPM_CONFIG_PREFIX/bin:${openchamberPath}:/bin:/usr/bin:$PATH
    export DOCKER_HOST=unix:///var/run/docker.sock
    export XDG_RUNTIME_DIR=/run/user/3000
    export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
    export NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    export SSL_CERT_FILE=$NIX_SSL_CERT_FILE
    export NIX_CONFIG="experimental-features = nix-command flakes"
    export NIX_REMOTE=daemon
  '';

  sourceHmSessionVarsIfPresent = ''
    hm_session_vars="\$HOME/.nix-profile/etc/profile.d/hm-session-vars.sh"
    if [ -f "\$hm_session_vars" ]; then
      # shellcheck disable=SC1090
      case "\$-" in *u*) restore_nounset=1 ;; *) restore_nounset=0 ;; esac
      set +u
      . "\$hm_session_vars"
      if [ "\$restore_nounset" -eq 1 ]; then
        set -u
      fi
    fi
  '';

  openchamberIdleCheck = ''
    is_openchamber_idle() {
      if ! activity="$(${pkgs.curl}/bin/curl -fsS --max-time 5 http://127.0.0.1:3000/api/session-activity)"; then
        return 1
      fi

      printf '%s\n' "$activity" | ${pkgs.jq}/bin/jq -e '
        if type != "object" then
          false
        else
          all(.[]; type == "object" and .type == "idle")
        end
      ' >/dev/null 2>&1
    }
  '';

  openchamberManagedOpenCodeIdleBody = ''
    set -eu

    if systemctl is-active --quiet opencode.service 2>/dev/null; then
      opencode_pid="$(systemctl show opencode.service -p MainPID --value)"
      case "$opencode_pid" in
        ""|0|*[!0-9]*) exit 1 ;;
      esac
      tr "\0" "\n" < "/proc/$opencode_pid/cmdline" 2>/dev/null \
        | grep -Eq "(^|/)opencode$" || exit 1
      tr "\0" "\n" < "/proc/$opencode_pid/cmdline" 2>/dev/null \
        | grep -qx serve || exit 1
    else
      web_cgroup="$(systemctl show openchamber-web.service -p ControlGroup --value)"
      [ -n "$web_cgroup" ] || exit 1
      opencode_pid=
      matches=0
      for cmdline in /proc/[0-9]*/cmdline; do
        pid="$(basename "$(dirname "$cmdline")")"
        if tr "\0" "\n" < "$cmdline" 2>/dev/null | grep -Eq "(^|/)opencode$" \
          && tr "\0" "\n" < "$cmdline" 2>/dev/null | grep -qx serve \
          && grep -Fq "$web_cgroup" "/proc/$pid/cgroup" 2>/dev/null; then
          opencode_pid="$pid"
          matches=$((matches + 1))
        fi
      done
      [ "$matches" -eq 1 ] || exit 1
    fi
    [ -n "$opencode_pid" ] || exit 1
    port=
    expect_port=0
    while IFS= read -r argument; do
      if [ "$expect_port" -eq 1 ]; then
        port="$argument"
        break
      fi
      if [ "$argument" = --port ]; then
        expect_port=1
      else
        case "$argument" in
          --port=*) port="$(printf '%s\n' "$argument" | cut -d= -f2)"; break ;;
        esac
      fi
    done < <(tr "\0" "\n" < "/proc/$opencode_pid/cmdline")
    case "$port" in
      ""|*[!0-9]*) exit 1 ;;
    esac
    if [ "''${1:-}" = --print-port ]; then
      printf '%s\n' "$port"
      exit 0
    fi
    if [ "''${1:-}" = --connections-drained ]; then
      if ss -Hnt state established \
        "( sport = :$port or dport = :$port )" | grep -q .; then
        exit 1
      fi
      exit 0
    fi
    # The standalone canary can outlive the web observer. OpenCode exposes
    # status per directory, with no authoritative aggregate idle endpoint.
    # Never infer that the whole process is idle from its default directory.
    if systemctl is-active --quiet opencode.service 2>/dev/null; then
      printf 'standalone OpenCode requires an operator-controlled maintenance stop\n' >&2
      exit 1
    fi
    username=opencode
    password=
    while IFS= read -r entry; do
      case "$entry" in
        OPENCODE_SERVER_USERNAME=*) username="$(printf '%s\n' "$entry" | cut -d= -f2-)" ;;
        OPENCODE_SERVER_PASSWORD=*) password="$(printf '%s\n' "$entry" | cut -d= -f2-)" ;;
      esac
    done < <(tr "\0" "\n" < "/proc/$opencode_pid/environ")
    if [ -n "$password" ]; then
      status="$(printf 'user = \"%s:%s\"\n' "$username" "$password" \
        | curl --config - -fsS --max-time 5 "http://127.0.0.1:$port/session/status")"
    else
      status="$(curl -fsS --max-time 5 "http://127.0.0.1:$port/session/status")"
    fi
    printf '%s\n' "$status" \
      | jq -e 'type == "object" and all(.[]; type == "object" and .type == "idle")' >/dev/null
  '';
  openchamberManagedOpenCodeIdlePortable = pkgs.writeText "openchamber-managed-opencode-idle-portable" ''
    #!/usr/bin/env bash
    ${openchamberManagedOpenCodeIdleBody}
  '';
  openchamberManagedOpenCodePresentPortable = pkgs.writeText "openchamber-managed-opencode-present-portable" ''
    #!/usr/bin/env bash
    set -eu

    if systemctl is-active --quiet opencode.service 2>/dev/null; then
      exit 0
    fi
    for cmdline in /proc/[0-9]*/cmdline; do
      if tr "\0" "\n" < "$cmdline" 2>/dev/null | grep -Eq "(^|/)opencode$" \
        && tr "\0" "\n" < "$cmdline" 2>/dev/null | grep -qx serve; then
        exit 0
      fi
    done
    exit 1
  '';
  openchamberManagedOpenCodeIdle = pkgs.writeShellScriptBin "openchamber-managed-opencode-idle" openchamberManagedOpenCodeIdleBody;

  openchamberToolMaintenance = pkgs.writeShellScriptBin "openchamber-tool-maintenance" ''
    set -eu

    if [ "''${OPENCHAMBER_TOOL_ENV_SANITIZED:-0}" != 1 ]; then
      exec ${pkgs.coreutils}/bin/env -i \
        OPENCHAMBER_TOOL_ENV_SANITIZED=1 \
        OPENCHAMBER_SKIP_RUNTIME_SECRETS=1 \
        HOME="$HOME" \
        USER=openchamber \
        XDG_CONFIG_HOME="''${XDG_CONFIG_HOME:-$HOME/.config}" \
        XDG_STATE_HOME="''${XDG_STATE_HOME:-$HOME/.local/state}" \
        XDG_CACHE_HOME="''${XDG_CACHE_HOME:-$HOME/.cache}" \
        XDG_DATA_HOME="''${XDG_DATA_HOME:-$HOME/.local/share}" \
        PATH=${openchamberPath}:/bin:/usr/bin \
        "$0" "$@"
    fi
    export OPENCHAMBER_SKIP_RUNTIME_SECRETS=1
    ${openchamberRuntimeEnv}
    export NODE_NO_WARNINGS=1

    tools_root="$XDG_DATA_HOME/openchamber-tools"
    generations_dir="$tools_root/generations"
    update_state="$XDG_STATE_HOME/openchamber-tool-update"
    control_dir="/var/lib/openchamber-tool-update"
    candidate_file="$update_state/candidate.tsv"
    failed_file="$control_dir/failed-release"
    report_dir="$HOME/.config/openchamber/run"
    report="$report_dir/update-check.json"
    staging=""

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >&2
    }

    cleanup() {
      [ -z "$staging" ] || rm -rf "$staging"
    }
    trap cleanup EXIT INT TERM

    package_version() {
      package_json="$1"
      [ -f "$package_json" ] || return 1
      jq -er '.version | strings | select(length > 0)' "$package_json"
    }

    active_version() {
      package="$1"
      package_version "$tools_root/active/lib/node_modules/$package/package.json" 2>/dev/null || true
    }

    opencode_platform_package() {
      case "$(uname -m)" in
        aarch64|arm64) printf '%s\n' opencode-linux-arm64 ;;
        x86_64|amd64) printf '%s\n' opencode-linux-x64 ;;
        *) return 1 ;;
      esac
    }

    harden_generation() {
      prefix="$1"
      python3 - "$prefix" <<'PY'
    import pathlib
    import sys

    prefix = pathlib.Path(sys.argv[1])
    candidate_root = prefix.resolve(strict=True)
    web = prefix / "lib/node_modules/@openchamber/web"

    for entry in prefix.rglob("*"):
        if not entry.is_symlink():
            continue
        try:
            entry.resolve(strict=True).relative_to(candidate_root)
        except (FileNotFoundError, ValueError):
            raise SystemExit(f"candidate symlink escapes or dangles: {entry}")

    def replace(relative, old, new):
        path = web / relative
        if path.is_symlink():
            raise SystemExit(f"required OpenChamber safety hook is a symlink: {relative}")
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(candidate_root)
        except (FileNotFoundError, ValueError):
            raise SystemExit(f"required OpenChamber safety hook escapes the candidate: {relative}")
        source = resolved.read_text()
        if old not in source:
            raise SystemExit(f"required OpenChamber safety hook is missing: {relative}")
        resolved.write_text(source.replace(old, new, 1))

    replace(
        "server/lib/session-goal/runtime.js",
        "const MAX_AUTO_TURNS = 20;",
        "const MAX_AUTO_TURNS = ${toString config.ghostship.openchamber.goalMaxAutoTurns};",
    )
    # Goal audits and delayed continuations are work even while model sessions
    # briefly report idle. Keep observers running until that work settles.
    replace(
        "server/lib/session-goal/runtime.js",
        "  return { processPayload, stop };",
        "  return { processPayload, stop, getMaintenanceWorkCount: () => timers.size + inflight.size };",
    )

    replace(
        "server/index.js",
        "  app.set('trust proxy', true);",
        """  app.set('trust proxy', true);
      const maintenanceGatePath = process.env.OPENCHAMBER_MAINTENANCE_GATE;
      let maintenanceActiveMutations = 0;
      let maintenanceObserverPaused = false;
      let maintenanceObserverResumePromise = null;
      let maintenanceSchedulerPaused = Boolean(maintenanceGatePath && fs.existsSync(maintenanceGatePath));
      app.use((req, res, next) => {
        if (req.method === 'GET' && req.path === '/api/openchamber/maintenance-drain') {
          const activeTerminalSessions = terminalRuntime?.getActiveSessionCount?.() ?? 0;
          const activeOpenCodeSessions = getActiveSessionCount();
          const scheduledTaskStatus = scheduledTasksRuntime?.getStatus?.() ?? {};
          const maintenanceGateActive = maintenanceGatePath && fs.existsSync(maintenanceGatePath);
          if (maintenanceGateActive && !maintenanceSchedulerPaused) {
            scheduledTasksRuntime.pauseForMaintenance();
            maintenanceSchedulerPaused = true;
          }
          const activeGoalWork = sessionGoalRuntime.getMaintenanceWorkCount?.() ?? 1;
          const activeScheduledTasks = scheduledTaskStatus.runningScheduledTasksCount ?? 0;
          const queuedScheduledTasks = scheduledTaskStatus.queuedScheduledTasksCount ?? 0;
          if (maintenanceGateActive
            && maintenanceActiveMutations === 0 && activeTerminalSessions === 0
            && activeOpenCodeSessions === 0 && activeScheduledTasks === 0 && activeGoalWork === 0) {
            if (!maintenanceObserverPaused) {
              openCodeWatcherRuntime.stop();
              globalMessageStreamHub.stop();
              globalWatcherStartPromise = null;
              maintenanceObserverPaused = true;
            }
          }
          return res.json({
            inFlightMutations: maintenanceActiveMutations,
            activeTerminalSessions,
            activeOpenCodeSessions,
            activeGoalWork,
            activeScheduledTasks,
            queuedScheduledTasks,
            observerPaused: maintenanceObserverPaused,
            schedulerPaused: maintenanceSchedulerPaused,
          });
        }
        const mutating = !['GET', 'HEAD', 'OPTIONS'].includes(req.method);
        if (maintenanceGatePath && mutating && fs.existsSync(maintenanceGatePath)) {
          return res.status(503).json({ error: 'OpenChamber maintenance is draining active sessions; retry shortly.' });
        }
        if (mutating) {
          maintenanceActiveMutations += 1;
          let settled = false;
          const settle = () => {
            if (settled) return;
            settled = true;
            maintenanceActiveMutations = Math.max(0, maintenanceActiveMutations - 1);
          };
          res.once('finish', settle);
          // A disconnected socket does not cancel its asynchronous handler.
          // Unknown unfinished mutations must continue to block maintenance.
        }
        next();
      });""",
    )
    replace(
        "server/index.js",
        "  server = http.createServer(app);",
        """  server = http.createServer(app);
      server.prependListener('upgrade', (_req, socket) => {
        if (maintenanceGatePath && fs.existsSync(maintenanceGatePath)) {
          socket.write('HTTP/1.1 503 Service Unavailable\\r\\nConnection: close\\r\\n\\r\\n');
          socket.destroy();
          return;
        }
      });
      setInterval(() => {
        if (maintenanceGatePath && fs.existsSync(maintenanceGatePath)) return;
        if (maintenanceSchedulerPaused) {
          scheduledTasksRuntime.resumeAfterMaintenance();
          maintenanceSchedulerPaused = false;
        }
        if (maintenanceObserverPaused && !maintenanceObserverResumePromise) {
          maintenanceObserverResumePromise = ensureGlobalWatcherStarted()
            .then(() => {
              if (maintenanceGatePath && fs.existsSync(maintenanceGatePath)) {
                openCodeWatcherRuntime.stop();
                globalMessageStreamHub.stop();
                globalWatcherStartPromise = null;
                return;
              }
              maintenanceObserverPaused = false;
            })
            .catch((error) => {
              console.warn('Global event watcher maintenance resume failed:', error?.message || error);
            })
            .finally(() => { maintenanceObserverResumePromise = null; });
        }
      }, 100).unref();""",
    )
    replace(
        "server/lib/terminal/runtime.js",
        "  return { shutdown };",
        "  return { shutdown, getActiveSessionCount: () => pendingSessionCreates.size + [...sessions.values()].filter((session) => session.status === 'running').length };",
    )
    replace(
        "server/lib/opencode/openchamber-routes.js",
        "  app.post('/api/openchamber/update-install', async (_req, res) => {",
        "  app.post('/api/openchamber/update-install', async (_req, res) => { return res.status(403).json({ error: 'Updates are managed by the idle-gated generation updater.' });",
    )
    replace(
        "bin/lib/commands-update.js",
        "return async function updateCommand(options = {}) {",
        "return async function updateCommand(options = {}) { process.stderr.write('error: updates are managed by the idle-gated generation updater.\\n'); process.exitCode = 1; return;",
    )
    replace(
        "server/lib/opencode/routes.js",
        "  app.post('/api/opencode/upgrade', async (req, res) => {",
        "  app.post('/api/opencode/upgrade', async (req, res) => { return res.status(403).json({ error: 'Updates are managed by the idle-gated generation updater.' });",
    )
    replace(
        "server/lib/opencode/proxy.js",
        "  app.use('/api', (_req, _res, next) => {",
        "  app.use('/api', (req, res, next) => { if (req.method === 'POST' && req.path === '/global/upgrade') return res.status(403).json({ error: 'Updates are managed by the idle-gated generation updater.' });",
    )
    replace(
        "server/lib/scheduled-tasks/runtime.js",
        "import { createOpencodeClient }",
        "import fs from 'node:fs';\nimport { createOpencodeClient }",
    )
    replace(
        "server/lib/scheduled-tasks/runtime.js",
        "  let started = false;\n  const tasksByProject = new Map();",
        "  let started = false;\n  let maintenancePaused = Boolean(process.env.OPENCHAMBER_MAINTENANCE_GATE && fs.existsSync(process.env.OPENCHAMBER_MAINTENANCE_GATE));\n  const tasksByProject = new Map();",
    )
    replace(
        "server/lib/scheduled-tasks/runtime.js",
        "  const syncTaskSchedule = async (projectID, task) => {\n    if (!task) {\n      return;\n    }\n    const nextRunAt = computeNextRunAt(task, Date.now());",
        """  const syncTaskSchedule = async (projectID, task) => {
        if (!task) {
          return;
        }
        const now = Date.now();
        const persistedNextRunAt = task.state?.nextRunAt;
        const lastScheduledFor = task.state?.lastScheduledFor;
        if (task.enabled && Number.isFinite(persistedNextRunAt) && persistedNextRunAt <= now
          && (!Number.isFinite(lastScheduledFor)
            || Math.abs(lastScheduledFor - persistedNextRunAt) > TASK_DUE_SLACK_MS)) {
          scheduleTask(projectID, task.id, persistedNextRunAt);
          return;
        }
        const nextRunAt = computeNextRunAt(task, now);""",
    )
    replace(
        "server/lib/scheduled-tasks/runtime.js",
        "      clearTimerForKey(taskKey);\n      const taskMap = tasksByProject.get(projectID);",
        """      clearTimerForKey(taskKey);
          if (maintenancePaused) {
            const retryTimer = setTimeout(() => {
              clearTimerForKey(taskKey);
              scheduleTask(projectID, taskID, nextRunAt);
            }, 1000);
            timersByTaskKey.set(taskKey, retryTimer);
            return;
          }
          const taskMap = tasksByProject.get(projectID);""",
    )
    replace(
        "server/lib/scheduled-tasks/runtime.js",
        "  const pumpQueue = () => {\n    if (!started) {\n      return;\n    }",
        """  const pumpQueue = () => {
        if (!started || maintenancePaused) {
          return;
        }""",
    )
    replace(
        "server/lib/scheduled-tasks/runtime.js",
        "      runningScheduledTasksCount: runningCount,",
        "      runningScheduledTasksCount: runningCount,\n      queuedScheduledTasksCount: queuedTaskKeys.size,",
    )
    replace(
        "server/lib/scheduled-tasks/runtime.js",
        "    runNow,\n    getStatus,",
        """    runNow,
        getStatus,
        pauseForMaintenance() { maintenancePaused = true; },
        resumeAfterMaintenance() { maintenancePaused = false; pumpQueue(); },""",
    )
    PY
    }

    install_wrappers() {
      prefix="$1"
      platform_package="$2"
      [ -x "$prefix/bin/openchamber" ] || return 1
      [ -x "$prefix/lib/node_modules/$platform_package/bin/opencode" ] || return 1
      mv "$prefix/bin/openchamber" "$prefix/bin/openchamber.upstream"

      cat > "$prefix/bin/openchamber" <<EOF
    #!/usr/bin/env sh
    set -eu
    script_dir="\$(CDPATH= cd -- "\$(dirname -- "\$0")" && pwd)"
    if [ "\''${1:-}" = update ]; then
      printf 'error: updates are staged automatically and promoted only while idle\n' >&2
      exit 1
    fi
    exec "\$script_dir/openchamber.upstream" "\$@"
    EOF
      cat > "$prefix/bin/opencode" <<EOF
    #!/usr/bin/env sh
    set -eu
    ${sourceHmSessionVarsIfPresent}
    script_dir="\$(CDPATH= cd -- "\$(dirname -- "\$0")" && pwd)"
    skip_next=0
    for argument in "\$@"; do
      if [ "\$skip_next" -eq 1 ]; then
        skip_next=0
        continue
      fi
      case "\$argument" in
        --log-level|--port|--hostname|--mdns-domain|--cors|-m|--model|-s|--session|--prompt|--agent|--replay-limit)
          skip_next=1
          ;;
        --log-level=*|--port=*|--hostname=*|--mdns-domain=*|--cors=*|--model=*|--session=*|--prompt=*|--agent=*|--replay-limit=*|-h|--help|-v|--version|--print-logs|--pure|--mdns|-c|--continue|--fork|--auto|--mini|--no-replay)
          ;;
        --) break ;;
        upgrade)
          printf 'error: updates are staged automatically and promoted only while idle\n' >&2
          exit 1
          ;;
        -*) ;;
        *) break ;;
      esac
    done
    upstream="\$script_dir/../lib/node_modules/$platform_package/bin/opencode"
    loader='${pkgs.stdenv.cc.bintools.dynamicLinker}'
    library_path='${pkgs.glibc}/lib'
    if [ -x "\$loader" ]; then
      exec "\$loader" --library-path "\$library_path" "\$upstream" "\$@"
    fi
    exec "\$upstream" "\$@"
    EOF
      chmod 0755 "$prefix/bin/openchamber" "$prefix/bin/opencode"
    }

    sandbox_install() {
      prefix="$1"
      openchamber_version="$2"
      opencode_version="$3"
      platform_package="$4"
      ${pkgs.coreutils}/bin/timeout --signal=TERM --kill-after=30s 20m \
        ${pkgs.bubblewrap}/bin/bwrap \
        --unshare-all \
        --share-net \
        --die-with-parent \
        --new-session \
        --ro-bind /nix/store /nix/store \
        --ro-bind /bin /bin \
        --dir /usr \
        --ro-bind /usr/bin /usr/bin \
        --dir /etc \
        --ro-bind /etc/resolv.conf /etc/resolv.conf \
        --ro-bind /etc/hosts /etc/hosts \
        --proc /proc \
        --dev /dev \
        --tmpfs /tmp \
        --dir /home \
        --dir /home/openchamber \
        --bind "$prefix" /candidate \
        --setenv HOME /home/openchamber \
        --setenv USER openchamber \
        --setenv PATH ${openchamberPath}:/bin:/usr/bin \
        --setenv NIX_SSL_CERT_FILE ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt \
        --setenv SSL_CERT_FILE ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt \
        --chdir /home/openchamber \
        -- ${pkgs.nodejs_24}/bin/npm install -g --prefix /candidate \
          --no-fund --no-audit --ignore-scripts \
          "@openchamber/web@$openchamber_version" \
          "$platform_package@$opencode_version"
    }

    sandbox_run_lifecycle() {
      prefix="$1"
      ${pkgs.coreutils}/bin/timeout --signal=TERM --kill-after=30s 5m \
        ${pkgs.bubblewrap}/bin/bwrap \
        --unshare-all \
        --die-with-parent \
        --new-session \
        --ro-bind /nix/store /nix/store \
        --ro-bind /bin /bin \
        --dir /usr \
        --ro-bind /usr/bin /usr/bin \
        --proc /proc \
        --dev /dev \
        --tmpfs /tmp \
        --dir /home \
        --dir /home/openchamber \
        --bind "$prefix" /candidate \
        --setenv HOME /home/openchamber \
        --setenv USER openchamber \
        --setenv PATH ${openchamberPath}:/bin:/usr/bin \
        --setenv npm_config_offline true \
        --chdir /home/openchamber \
        -- ${pkgs.nodejs_24}/bin/npm rebuild -g --prefix /candidate --offline
    }

    sandbox_validate_clis() {
      prefix="$1"
      ${pkgs.bubblewrap}/bin/bwrap \
        --unshare-all \
        --die-with-parent \
        --new-session \
        --ro-bind /nix/store /nix/store \
        --ro-bind /bin /bin \
        --dir /usr \
        --ro-bind /usr/bin /usr/bin \
        --proc /proc \
        --dev /dev \
        --tmpfs /tmp \
        --dir /home \
        --dir /home/openchamber \
        --ro-bind "$prefix" /candidate \
        --setenv HOME /home/openchamber \
        --setenv USER openchamber \
        --setenv PATH /candidate/bin:${openchamberPath}:/bin:/usr/bin \
        --setenv XDG_CONFIG_HOME /home/openchamber/.config \
        --setenv XDG_STATE_HOME /home/openchamber/.local/state \
        --setenv XDG_CACHE_HOME /home/openchamber/.cache \
        --setenv XDG_DATA_HOME /home/openchamber/.local/share \
        --chdir /home/openchamber \
        -- ${pkgs.bash}/bin/bash -c \
          'openchamber --version >/dev/null && opencode --version >/dev/null && opencode debug config >/dev/null'
    }

    sandbox_validate_server() {
      prefix="$1"
      ${pkgs.coreutils}/bin/timeout --signal=TERM --kill-after=30s 3m \
        ${pkgs.bubblewrap}/bin/bwrap \
        --unshare-all \
        --uid 0 \
        --gid 0 \
        --cap-add CAP_NET_ADMIN \
        --die-with-parent \
        --new-session \
        --ro-bind /nix/store /nix/store \
        --ro-bind /bin /bin \
        --dir /usr \
        --ro-bind /usr/bin /usr/bin \
        --proc /proc \
        --dev /dev \
        --tmpfs /tmp \
        --tmpfs /run \
        --dir /home \
        --dir /home/openchamber \
        --ro-bind "$prefix" /candidate \
        --setenv HOME /home/openchamber \
        --setenv USER openchamber \
        --setenv PATH /candidate/bin:${openchamberPath}:/bin:/usr/bin \
        --setenv XDG_CONFIG_HOME /home/openchamber/.config \
        --setenv XDG_STATE_HOME /home/openchamber/.local/state \
        --setenv XDG_CACHE_HOME /home/openchamber/.cache \
        --setenv XDG_DATA_HOME /home/openchamber/.local/share \
        --setenv OPENCHAMBER_ALLOW_UNAUTHENTICATED_LAN true \
        --setenv OPENCHAMBER_MAINTENANCE_GATE /tmp/openchamber-maintenance.lock \
        --setenv NODE_NO_WARNINGS 1 \
        --chdir /home/openchamber \
        -- ${pkgs.bash}/bin/bash -c '
          set -eu
          ip link set lo up
          openchamber serve --host 127.0.0.1 --port 33119 --foreground >/tmp/openchamber-smoke.log 2>&1 &
          server_pid=$!
          cleanup_server() {
            kill "$server_pid" 2>/dev/null || true
            wait "$server_pid" 2>/dev/null || true
          }
          trap cleanup_server EXIT INT TERM
          for _ in $(seq 1 120); do
            if activity=$(curl -fsS --max-time 2 http://127.0.0.1:33119/api/session-activity 2>/dev/null) \
              && printf "%s\n" "$activity" | jq -e "type == \"object\" and all(.[]; type == \"object\" and .type == \"idle\")" >/dev/null \
              && curl -fsS --max-time 2 http://127.0.0.1:33119/api/opencode/health \
                | jq -e ".healthy == true" >/dev/null \
              && curl -fsS --max-time 2 http://127.0.0.1:33119/api/openchamber/maintenance-drain \
                | jq -e ".inFlightMutations == 0 and .activeTerminalSessions == 0 and .activeOpenCodeSessions == 0 and .activeScheduledTasks == 0 and .activeGoalWork == 0" >/dev/null; then
              touch /tmp/openchamber-maintenance.lock
              curl -fsS --max-time 2 http://127.0.0.1:33119/api/openchamber/maintenance-drain \
                | jq -e ".inFlightMutations == 0 and .activeTerminalSessions == 0 and .activeOpenCodeSessions == 0 and .activeScheduledTasks == 0 and .activeGoalWork == 0 and .observerPaused == true and .schedulerPaused == true" >/dev/null
              mutation_status=$(curl -sS --max-time 2 -o /dev/null -w "%{http_code}" \
                -X POST http://127.0.0.1:33119/api/openchamber/maintenance-probe)
              websocket_status=$(curl --http1.1 -sS --max-time 2 -o /dev/null -w "%{http_code}" \
                -H "Connection: Upgrade" -H "Upgrade: websocket" \
                http://127.0.0.1:33119/api/session-activity)
              rm -f /tmp/openchamber-maintenance.lock
              [ "$mutation_status" = 503 ] && [ "$websocket_status" = 503 ] || exit 1
              observer_resumed=0
              for _ in $(seq 1 20); do
                if curl -fsS --max-time 2 http://127.0.0.1:33119/api/openchamber/maintenance-drain \
                  | jq -e ".observerPaused == false and .schedulerPaused == false" >/dev/null; then
                  observer_resumed=1
                  break
                fi
                sleep 0.1
              done
              [ "$observer_resumed" -eq 1 ] || exit 1
              exit 0
            fi
            if ! kill -0 "$server_pid" 2>/dev/null; then
              cat /tmp/openchamber-smoke.log >&2
              exit 1
            fi
            sleep 1
          done
          cat /tmp/openchamber-smoke.log >&2
          exit 1
        '
    }

    sandbox_validate_scheduler() {
      prefix="$1"
      ${pkgs.coreutils}/bin/timeout --signal=TERM --kill-after=5s 30s \
        ${pkgs.bubblewrap}/bin/bwrap \
        --unshare-all \
        --die-with-parent \
        --new-session \
        --ro-bind /nix/store /nix/store \
        --ro-bind /bin /bin \
        --dir /usr \
        --ro-bind /usr/bin /usr/bin \
        --proc /proc \
        --dev /dev \
        --tmpfs /tmp \
        --dir /home \
        --dir /home/openchamber \
        --ro-bind "$prefix" /candidate \
        --setenv HOME /home/openchamber \
        --setenv USER openchamber \
        --setenv PATH /candidate/bin:${openchamberPath}:/bin:/usr/bin \
        --chdir /home/openchamber \
        -- ${pkgs.nodejs_24}/bin/node --input-type=module <<'NODE'
    import { mkdir, writeFile, unlink } from 'node:fs/promises';
    import { createScheduledTasksRuntime } from '/candidate/lib/node_modules/@openchamber/web/server/lib/scheduled-tasks/runtime.js';

    Math.random = () => 0;
    const projectID = 'maintenance-project';
    const projectPath = '/tmp/maintenance-project';
    await mkdir(projectPath + '/.agents/loops', { recursive: true });
    const now = Date.now();
    const makeTask = (id) => ({
      id,
      name: id,
      enabled: true,
      schedule: { kind: 'once', date: '2000-01-01', time: '00:00', timezone: 'UTC' },
      execution: {
        prompt: 'maintenance scheduler probe',
        providerID: 'openai',
        modelID: 'probe',
        permissionAutoAccept: false,
        goalEnabled: false,
      },
      state: { nextRunAt: now - 1000 },
    });
    const tasks = new Map([
      ['task-a', makeTask('task-a')],
      ['task-b', makeTask('task-b')],
    ]);
    const mergeState = (task, patch) => ({
      ...task,
      state: { ...(task.state || {}), ...patch },
    });
    const claimed = [];
    const releases = [];
    const projectConfigRuntime = {
      async reconcileLoopTasks() { return [...tasks.values()]; },
      async listScheduledTasks() { return [...tasks.values()]; },
      async updateScheduledTaskState(project, id, patch) {
        if (project !== projectID || !tasks.has(id)) return { task: null };
        const next = mergeState(tasks.get(id), patch);
        tasks.set(id, next);
        return { task: next };
      },
      async updateScheduledTaskStateIf(project, id, predicate, patch) {
        const current = tasks.get(id);
        if (project !== projectID || !current || !predicate(current)) {
          return { task: current || null, updated: false };
        }
        claimed.push(id);
        const next = mergeState(current, patch);
        tasks.set(id, next);
        return { task: next, updated: true };
      },
      async upsertScheduledTask(project, task) {
        if (project !== projectID) return { task: null };
        tasks.set(task.id, task);
        return { task };
      },
    };
    process.env.OPENCHAMBER_MAINTENANCE_GATE = '/tmp/persisted-maintenance.lock';
    await writeFile(process.env.OPENCHAMBER_MAINTENANCE_GATE, 'probe');
    const runtime = createScheduledTasksRuntime({
      projectConfigRuntime,
      listProjects: async () => [{ id: projectID, path: projectPath }],
      buildOpenCodeUrl: () => 'http://127.0.0.1:9',
      getOpenCodeAuthHeaders: () => ({}),
      waitForOpenCodeReady: () => new Promise((resolve) => releases.push(resolve)),
      logger: { warn() {}, error() {}, info() {} },
      maxGlobalConcurrency: 1,
      maxProjectConcurrency: 1,
      maxRunDurationMs: 1000,
    });
    const waitFor = async (predicate, message, timeoutMs = 5000) => {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        if (predicate()) return;
        await new Promise((resolve) => setTimeout(resolve, 20));
      }
      throw new Error(message);
    };

    await runtime.start();
    await new Promise((resolve) => setTimeout(resolve, 1200));
    let status = runtime.getStatus();
    if (claimed.length !== 0 || status.runningScheduledTasksCount !== 0
      || status.queuedScheduledTasksCount !== 0) {
      throw new Error('paused scheduler dispatched overdue work');
    }

    await unlink(process.env.OPENCHAMBER_MAINTENANCE_GATE);
    runtime.resumeAfterMaintenance();
    await waitFor(() => {
      const snapshot = runtime.getStatus();
      return claimed.length === 1
        && snapshot.runningScheduledTasksCount === 1
        && snapshot.queuedScheduledTasksCount === 1;
    }, 'overdue tasks did not preserve concurrency and queue accounting');

    runtime.pauseForMaintenance();
    releases.shift()?.();
    await waitFor(() => {
      const snapshot = runtime.getStatus();
      return snapshot.runningScheduledTasksCount === 0
        && snapshot.queuedScheduledTasksCount === 1;
    }, 'paused scheduler did not preserve queued work');

    runtime.resumeAfterMaintenance();
    await waitFor(() => claimed.length === 2 && runtime.getStatus().runningScheduledTasksCount === 1,
      'resume did not synchronously pump queued work');
    releases.shift()?.();
    await waitFor(() => {
      const snapshot = runtime.getStatus();
      return snapshot.runningScheduledTasksCount === 0
        && snapshot.queuedScheduledTasksCount === 0;
    }, 'scheduler did not settle after resumed work');

    if (new Set(claimed).size !== 2 || claimed.length !== 2) {
      throw new Error('persisted overdue occurrences were duplicated or lost');
    }
    runtime.stop();

    const { createSessionGoalRuntime } = await import('/candidate/lib/node_modules/@openchamber/web/server/lib/session-goal/runtime.js');
    let releaseGoalProbe;
    globalThis.fetch = () => new Promise((resolve) => {
      releaseGoalProbe = () => resolve({ ok: true, json: async () => ({}) });
    });
    const goals = createSessionGoalRuntime({
      buildOpenCodeUrl: (route) => 'http://127.0.0.1:1' + route,
      getOpenCodeAuthHeaders: () => ({}),
      isEnabled: () => true,
      idleQuietMs: 20,
    });
    goals.processPayload({ type: 'session.status', properties: { sessionID: 'maintenance-goal', status: { type: 'idle' } } });
    if (goals.getMaintenanceWorkCount() !== 1) throw new Error('pending goal continuation appears idle');
    await waitFor(() => typeof releaseGoalProbe === 'function', 'goal audit did not start');
    if (goals.getMaintenanceWorkCount() !== 1) throw new Error('in-flight goal audit appears idle');
    releaseGoalProbe();
    await waitFor(() => goals.getMaintenanceWorkCount() === 0, 'settled goal audit still blocks maintenance');
    goals.stop();
    process.exit(0);
    NODE
    }

    validate_generation() {
      prefix="$1"
      expected_openchamber="$2"
      expected_opencode="$3"
      platform_package="$4"
      [ "$(package_version "$prefix/lib/node_modules/@openchamber/web/package.json")" = "$expected_openchamber" ]
      [ "$(package_version "$prefix/lib/node_modules/$platform_package/package.json")" = "$expected_opencode" ]
      [ "$(cat "$prefix/.openchamber-harness-revision" 2>/dev/null || true)" = "${openchamberGenerationRevision}" ]
      for javascript in \
        "$prefix/lib/node_modules/@openchamber/web/server/index.js" \
        "$prefix/lib/node_modules/@openchamber/web/server/lib/opencode/openchamber-routes.js" \
        "$prefix/lib/node_modules/@openchamber/web/server/lib/opencode/routes.js" \
        "$prefix/lib/node_modules/@openchamber/web/server/lib/opencode/proxy.js" \
        "$prefix/lib/node_modules/@openchamber/web/server/lib/session-goal/runtime.js" \
        "$prefix/lib/node_modules/@openchamber/web/server/lib/scheduled-tasks/runtime.js" \
        "$prefix/lib/node_modules/@openchamber/web/server/lib/terminal/runtime.js" \
        "$prefix/lib/node_modules/@openchamber/web/bin/lib/commands-update.js"; do
        node --check "$javascript" >/dev/null
      done
      sandbox_validate_clis "$prefix"
      sandbox_validate_server "$prefix"
      sandbox_validate_scheduler "$prefix"
    }

    install_user_shims() {
      for name in openchamber opencode; do
        shim="$HOME/.local/bin/.$name.next.$$"
        cat > "$shim" <<EOF
    #!/usr/bin/env sh
    set -eu
    exec '$tools_root/active/bin/$name' "\$@"
    EOF
        chmod 0755 "$shim"
        mv -f "$shim" "$HOME/.local/bin/$name"
      done
    }

    active_clis_are_usable() {
      [ -x "$tools_root/active/bin/openchamber" ] \
        && [ -x "$tools_root/active/bin/opencode" ] \
        && "$tools_root/active/bin/openchamber" --version >/dev/null \
        && "$tools_root/active/bin/opencode" --version >/dev/null \
        && "$tools_root/active/bin/opencode" debug config >/dev/null
    }

    active_is_usable() {
      active_clis_are_usable \
        && [ "$(cat "$tools_root/active/.openchamber-harness-revision" 2>/dev/null || true)" = "${openchamberGenerationRevision}" ]
    }

    platform_package="$(opencode_platform_package)" || {
      printf 'error: unsupported OpenCode architecture: %s\n' "$(uname -m)" >&2
      exit 1
    }

    if [ "''${1:-}" = validate-candidate ]; then
      [ "$#" -eq 4 ] || {
        printf 'usage: openchamber-tool-maintenance validate-candidate <path> <openchamber-version> <opencode-version>\n' >&2
        exit 2
      }
      validate_generation "$2" "$3" "$4" "$platform_package"
      exit 0
    fi

    install -d -m 0755 "$HOME/.local/bin" "$HOME/.local/libexec" "$generations_dir" "$report_dir"
    install -d -m 0700 "$update_state"
    install -m 0755 ${openchamberManagedOpenCodeIdlePortable} \
      "$HOME/.local/libexec/openchamber-managed-opencode-idle"
    exec 9<"$control_dir/tool-update.lock"
    ${pkgs.util-linux}/bin/flock 9

    if [ "''${1:-}" = bootstrap-candidate ]; then
      [ -f "$candidate_file" ] || {
        printf 'error: no prestaged candidate is available for offline bootstrap\n' >&2
        exit 1
      }
      IFS="$(printf '\t')" read -r candidate candidate_openchamber candidate_opencode candidate_release < "$candidate_file"
      case "$candidate" in
        "$generations_dir/"*) ;;
        *)
          printf 'error: prestaged candidate is outside the managed generations directory\n' >&2
          exit 1
          ;;
      esac
      [ "$(basename "$candidate")" = "$candidate_release" ]
      validate_generation "$candidate" "$candidate_openchamber" "$candidate_opencode" "$platform_package"
      ln -sfn "$candidate" "$tools_root/active.next"
      mv -Tf "$tools_root/active.next" "$tools_root/active"
      install_user_shims
      rm -f "$candidate_file"
      log_info "activated prestaged $candidate_release without registry access"
      exit 0
    fi

    if [ "''${1:-}" = bootstrap ] && active_is_usable; then
      install_user_shims
      log_info "using the validated active generation; latest check remains asynchronous"
      exit 0
    fi

    latest_openchamber="$(npm view @openchamber/web@latest version 2>/dev/null || true)"
    latest_opencode="$(npm view opencode-ai@latest version 2>/dev/null || true)"
    if [ -z "$latest_openchamber" ] || [ -z "$latest_opencode" ]; then
      printf 'error: failed to resolve latest OpenChamber or OpenCode release\n' >&2
      exit 1
    fi
    current_openchamber="$(active_version @openchamber/web)"
    current_opencode="$(active_version "$platform_package")"
    release_id="openchamber-$latest_openchamber--opencode-$latest_opencode--harness-${openchamberGenerationRevision}"
    generation="$generations_dir/$release_id"
    checked_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

    jq -n \
      --arg checked_at "$checked_at" \
      --arg current_openchamber "$current_openchamber" \
      --arg latest_openchamber "$latest_openchamber" \
      --arg current_opencode "$current_opencode" \
      --arg latest_opencode "$latest_opencode" \
      --arg harness_revision "${openchamberGenerationRevision}" \
      '{
        checked_at: $checked_at,
        current: {openchamber: $current_openchamber, opencode: $current_opencode},
        latest: {openchamber: $latest_openchamber, opencode: $latest_opencode},
        harness_revision: $harness_revision,
        promotion: "staged-then-promoted-after-30-seconds-continuous-idle"
      }' > "$report.tmp"
    mv "$report.tmp" "$report"

    if [ "$current_openchamber" = "$latest_openchamber" ] \
      && [ "$current_opencode" = "$latest_opencode" ]; then
      if active_is_usable; then
        rm -f "$candidate_file"
        log_info "OpenChamber and OpenCode already match npm latest"
        exit 0
      fi
      if active_clis_are_usable; then
        log_info "npm versions match latest but harness ${openchamberGenerationRevision} must be staged"
      elif [ "''${1:-}" != bootstrap ]; then
        printf 'error: active latest generation failed validation; bootstrap recovery is required\n' >&2
        exit 1
      else
        log_info "active latest generation failed validation; rebuilding it"
        rm -f "$tools_root/active"
        chmod -R u+w "$generation" 2>/dev/null || true
        rm -rf "$generation"
      fi
    fi

    if [ "''${1:-}" != bootstrap ] \
      && [ -f "$failed_file" ] \
      && [ "$(cat "$failed_file")" = "$release_id" ]; then
      log_info "release $release_id previously failed promotion; waiting for a newer latest release"
      exit 0
    fi

    if [ -d "$generation" ] \
      && ! validate_generation "$generation" "$latest_openchamber" "$latest_opencode" "$platform_package"; then
      log_info "cached generation $release_id failed validation; restaging it"
      chmod -R u+w "$generation" 2>/dev/null || true
      rm -rf "$generation"
    fi

    if [ ! -d "$generation" ]; then
      staging="$generations_dir/.staging-$release_id-$$"
      rm -rf "$staging"
      install -d -m 0755 "$staging"
      log_info "staging npm latest: OpenChamber $latest_openchamber and OpenCode $latest_opencode"
      sandbox_install "$staging" "$latest_openchamber" "$latest_opencode" "$platform_package"
      sandbox_run_lifecycle "$staging"
      harden_generation "$staging"
      install_wrappers "$staging" "$platform_package"
      printf '%s\n' "${openchamberGenerationRevision}" > "$staging/.openchamber-harness-revision"
      validate_generation "$staging" "$latest_openchamber" "$latest_opencode" "$platform_package"
      chmod -R a-w "$staging"
      mv "$staging" "$generation"
      staging=""
    fi

    printf '%s\t%s\t%s\t%s\n' \
      "$generation" "$latest_openchamber" "$latest_opencode" "$release_id" > "$candidate_file.tmp"
    mv "$candidate_file.tmp" "$candidate_file"

    if [ "''${1:-}" = bootstrap ]; then
      ln -sfn "$generation" "$tools_root/active.next"
      mv -Tf "$tools_root/active.next" "$tools_root/active"
      install_user_shims
      rm -f "$candidate_file"
      log_info "bootstrapped $release_id before service startup"
    else
      log_info "staged $release_id; promotion is queued behind the continuous-idle gate"
    fi
  '';

  openchamberToolAutoUpdate = pkgs.writeShellScriptBin "openchamber-tool-auto-update" ''
    set -eu

    ${openchamberRuntimeEnv}
    export PATH=${openchamberPath}:/bin:/usr/bin
    ${pkgs.su-exec}/bin/su-exec openchamber:openchamber ${openchamberToolMaintenance}/bin/openchamber-tool-maintenance
  '';

  openchamberCacheCleanup = pkgs.writeShellScriptBin "openchamber-cache-cleanup" ''
    set -eu

    ${openchamberRuntimeEnv}
    export PATH=${openchamberPath}:/bin:/usr/bin

    for cache_dir in \
      "$HOME/.cache/npm" \
      "$HOME/.cache/uv" \
      "$HOME/.cache/go-build" \
      "$HOME/.cache/bun" \
      "$HOME/.npm/_cacache"; do
      [ -d "$cache_dir" ] || continue
      find "$cache_dir" -xdev -type f -mtime +30 -delete
    done
  '';

  openchamberToolUpdateRestart = pkgs.writeShellScriptBin "openchamber-tool-update-restart" ''
    set -eu

    ${openchamberRuntimeEnv}
    export PATH=${openchamberPath}:/bin:/usr/bin

    tools_root="$XDG_DATA_HOME/openchamber-tools"
    state_dir="$XDG_STATE_HOME/openchamber-tool-update"
    control_dir="/var/lib/openchamber-tool-update"
    candidate_file="$state_dir/candidate.tsv"
    health_restart_file="$control_dir/health-restart.pending"
    failed_file="$control_dir/failed-release"
    transaction_file="$control_dir/promotion.tsv"
    gate_file="$control_dir/admission.lock"
    previous_link="$tools_root/previous"
    audit_log="$HOME/.config/openchamber/logs/restart-audit.log"
    gate_armed=0
    opencode_gate_armed=0
    generations_locked=0
    generations_mode=""
    mkdir -p "$(dirname "$audit_log")"

    clear_opencode_network_gate() {
      if [ "$opencode_gate_armed" -ne 1 ] && [ "''${1:-}" != force ]; then
        return 0
      fi
      ${pkgs.iptables}/bin/iptables -D OUTPUT -j OPENCHAMBER_OPENCODE_GATE 2>/dev/null || true
      ${pkgs.iptables}/bin/iptables -F OPENCHAMBER_OPENCODE_GATE 2>/dev/null || true
      ${pkgs.iptables}/bin/iptables -X OPENCHAMBER_OPENCODE_GATE 2>/dev/null || true
      opencode_gate_armed=0
    }

    disarm_gate() {
      if [ "$generations_locked" -eq 1 ]; then
        chmod "$generations_mode" "$tools_root/generations"
        generations_locked=0
      fi
      if [ -f "$transaction_file" ]; then
        return 0
      fi
      clear_opencode_network_gate
      if [ "$gate_armed" -eq 1 ] && [ ! -f "$transaction_file" ]; then
        rm -f "$gate_file"
      fi
    }
    trap disarm_gate EXIT INT TERM

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >&2
    }

    audit_restart() {
      action="$1"
      release="$2"
      printf '%s source=tool-auto-update action=%s release=%s\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$action" "$release" \
        | ${pkgs.su-exec}/bin/su-exec openchamber:openchamber tee -a "$audit_log" >/dev/null
    }

    ${openchamberIdleCheck}
    ${lib.optionalString externalOpenCode openchamberExternalOpenCodeReady}

    has_opencode_serve() {
      web_cgroup="$(systemctl show openchamber-web.service -p ControlGroup --value)"
      [ -n "$web_cgroup" ] || return 1
      for cmdline in /proc/[0-9]*/cmdline; do
        pid_dir="$(dirname "$cmdline")"
        if tr '\0' ' ' < "$cmdline" 2>/dev/null | grep -q 'opencode serve' \
          && grep -Fq "$web_cgroup" "$pid_dir/cgroup" 2>/dev/null; then
          return 0
        fi
      done
      return 1
    }

    runtime_healthy() {
      is_openchamber_idle || return 1
      curl -fsS --max-time 5 http://127.0.0.1:3000/api/opencode/health \
        | jq -e '.healthy == true' >/dev/null 2>&1 \
        || return 1
      ${if externalOpenCode then "opencode_ready" else "has_opencode_serve"}
    }

    maintenance_drained() {
      curl -fsS --max-time 5 http://127.0.0.1:3000/api/openchamber/maintenance-drain \
        | jq -e '
          .inFlightMutations == 0
          and .activeTerminalSessions == 0
          and .activeOpenCodeSessions == 0
          and .activeScheduledTasks == 0 and .activeGoalWork == 0
          and .observerPaused == true
          and .schedulerPaused == true
        ' >/dev/null 2>&1
    }

    managed_opencode_idle() {
      ${openchamberManagedOpenCodeIdle}/bin/openchamber-managed-opencode-idle
    }

    managed_opencode_connections_drained() {
      ${openchamberManagedOpenCodeIdle}/bin/openchamber-managed-opencode-idle \
        --connections-drained
    }

    opencode_process_present() {
      ${
        if externalOpenCode then "systemctl is-active --quiet opencode.service" else "has_opencode_serve"
      }
    }

    managed_opencode_quiesced_or_absent() {
      if ! opencode_process_present; then
        return 0
      fi
      managed_opencode_connections_drained && managed_opencode_idle
    }

    arm_opencode_network_gate() {
      opencode_port="$(${openchamberManagedOpenCodeIdle}/bin/openchamber-managed-opencode-idle --print-port)" \
        || {
          if [ "''${1:-}" = allow-absent ] && ! opencode_process_present; then
            opencode_port=4096
          else
            return 1
          fi
        }
      case "$opencode_port" in
        ""|*[!0-9]*) return 1 ;;
      esac
      opencode_gate_armed=1
      ${pkgs.iptables}/bin/iptables -N OPENCHAMBER_OPENCODE_GATE 2>/dev/null || true
      ${pkgs.iptables}/bin/iptables -C OPENCHAMBER_OPENCODE_GATE \
        -p tcp --syn --dport "$opencode_port" -m conntrack --ctstate NEW \
        -m owner '!' --uid-owner 0 -j REJECT 2>/dev/null \
        || ${pkgs.iptables}/bin/iptables -A OPENCHAMBER_OPENCODE_GATE \
          -p tcp --syn --dport "$opencode_port" -m conntrack --ctstate NEW \
          -m owner '!' --uid-owner 0 -j REJECT \
        || return 1
      ${pkgs.iptables}/bin/iptables -C OUTPUT \
        -j OPENCHAMBER_OPENCODE_GATE 2>/dev/null \
        || ${pkgs.iptables}/bin/iptables -I OUTPUT 1 \
          -j OPENCHAMBER_OPENCODE_GATE \
        || return 1
    }

    wait_runtime_healthy() {
      for _ in $(seq 1 60); do
        if runtime_healthy; then
          return 0
        fi
        sleep 2
      done
      runtime_healthy
    }

    prune_generations() {
      active_generation="$(readlink -f "$tools_root/active")"
      previous_generation="$(readlink -f "$previous_link" 2>/dev/null || true)"
      for generation_dir in "$tools_root/generations"/* "$tools_root/generations"/.staging-*; do
        [ -e "$generation_dir" ] || continue
        [ "$generation_dir" = "$active_generation" ] && continue
        [ "$generation_dir" = "$previous_generation" ] && continue
        chmod -R u+w "$generation_dir" 2>/dev/null || true
        rm -rf -- "$generation_dir"
      done
    }

    lock_candidate_tree() {
      candidate="$1"
      generations_mode="$(${pkgs.coreutils}/bin/stat -c '%a' "$tools_root/generations")"
      chmod a-w "$tools_root/generations"
      generations_locked=1
      chown -R root:root "$candidate"
      chmod -R a-w "$candidate"
    }

    unlock_generations() {
      [ "$generations_locked" -eq 1 ] || return 0
      chmod "$generations_mode" "$tools_root/generations"
      generations_locked=0
    }

    exec 9<>"$control_dir/tool-update.lock"
    if ! ${pkgs.util-linux}/bin/flock -n 9; then
      log_info "tool maintenance is still running; leaving restart queued"
      exit 0
    fi
    if [ ! -f "$transaction_file" ]; then
      clear_opencode_network_gate force
    fi

    if [ -f "$transaction_file" ]; then
      IFS="$(printf '\t')" read -r interrupted_old interrupted_candidate interrupted_release < "$transaction_file"
      if systemctl is-active --quiet openchamber-web.service \
        || ${lib.optionalString externalOpenCode "systemctl is-active --quiet opencode.service ||"} false; then
        gate_armed=1
        if ! arm_opencode_network_gate allow-absent; then
          log_info "could not gate OpenCode while recovering $interrupted_release"
          exit 1
        fi
        sleep 30
        recovery_quiesced=1
        if systemctl is-active --quiet openchamber-web.service \
          && { ! maintenance_drained || ! is_openchamber_idle; }; then
          recovery_quiesced=0
        fi
        if ! managed_opencode_quiesced_or_absent; then
          recovery_quiesced=0
        fi
        if [ "$recovery_quiesced" -ne 1 ]; then
          log_info "runtime is active or unknown while recovering $interrupted_release"
          exit 1
        fi
      fi
      log_info "recovering interrupted promotion $interrupted_release"
      ${pkgs.su-exec}/bin/su-exec openchamber:openchamber ln -sfn "$interrupted_old" "$tools_root/active.next"
      ${pkgs.su-exec}/bin/su-exec openchamber:openchamber mv -Tf "$tools_root/active.next" "$tools_root/active"
      recovery_ok=1
      ${lib.optionalString externalOpenCode "systemctl restart opencode.service || recovery_ok=0"}
      if [ "$recovery_ok" -eq 1 ]; then
        systemctl restart openchamber-web.service || recovery_ok=0
      fi
      clear_opencode_network_gate
      if [ "$recovery_ok" -eq 1 ] && wait_runtime_healthy; then
        printf '%s\n' "$interrupted_release" > "$failed_file.tmp"
        mv "$failed_file.tmp" "$failed_file"
        rm -f "$candidate_file" "$transaction_file" "$gate_file"
        clear_opencode_network_gate
        audit_restart recover-interrupted "$interrupted_release"
        exit 1
      fi
      log_info "previous generation is not healthy yet; preserving promotion recovery state"
      audit_restart recover-pending "$interrupted_release"
      exit 1
    fi

    if [ ! -f "$candidate_file" ] && [ ! -f "$health_restart_file" ]; then
      rm -f "$gate_file"
      exit 0
    fi

    if ! systemctl is-active --quiet openchamber-web.service; then
      if [ -f "$health_restart_file" ]; then
        log_info "OpenChamber is stopped; attempting queued health recovery"
        if ! arm_opencode_network_gate allow-absent; then
          log_info "could not gate OpenCode before stopped-web health recovery"
          exit 0
        fi
        sleep 30
        if ! managed_opencode_quiesced_or_absent; then
          log_info "OpenCode is active or unknown before stopped-web health recovery"
          exit 0
        fi
        recovery_ok=1
        ${lib.optionalString externalOpenCode "systemctl restart opencode.service || recovery_ok=0"}
        if [ "$recovery_ok" -eq 1 ]; then
          systemctl restart openchamber-web.service || recovery_ok=0
        fi
        clear_opencode_network_gate
        if [ "$recovery_ok" -eq 1 ] && wait_runtime_healthy; then
          rm -f "$health_restart_file" "$gate_file"
          audit_restart health-recover-stopped current
          exit 0
        fi
        log_info "queued health recovery did not restore the stopped runtime"
        exit 1
      fi
      log_info "openchamber-web.service is stopped; leaving candidate queued"
      exit 0
    fi

    if ! is_openchamber_idle; then
      log_info "OpenChamber reports active or unknown work; leaving restart queued"
      exit 0
    fi

    printf '%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$gate_file.tmp"
    mv "$gate_file.tmp" "$gate_file"
    gate_armed=1
    sleep 1
    if ! maintenance_drained || ! is_openchamber_idle || ! managed_opencode_quiesced_or_absent; then
      log_info "admissions are still draining or activity began while the gate was closing; leaving candidate queued"
      exit 0
    fi

    if ! arm_opencode_network_gate allow-absent; then
      log_info "failed to gate direct OpenCode admissions; leaving restart queued"
      exit 0
    fi
    log_info "OpenChamber and new OpenCode admissions are gated; requiring 30 seconds of continuous idle before restart"
    sleep 30

    if ! maintenance_drained || ! is_openchamber_idle \
      || ! managed_opencode_quiesced_or_absent; then
      log_info "OpenChamber is no longer fully drained and idle; leaving restart queued"
      exit 0
    fi

    if [ -f "$health_restart_file" ] && [ ! -f "$candidate_file" ]; then
      log_info "runtime is fully drained; performing queued health recovery"
      restart_ok=1
      ${lib.optionalString externalOpenCode "systemctl restart opencode.service || restart_ok=0"}
      if [ "$restart_ok" -eq 1 ]; then
        systemctl restart openchamber-web.service || restart_ok=0
      fi
      clear_opencode_network_gate
      if [ "$restart_ok" -eq 1 ]; then
        wait_runtime_healthy || restart_ok=0
      fi
      if [ "$restart_ok" -eq 1 ]; then
        rm -f "$health_restart_file" "$gate_file"
        gate_armed=0
        audit_restart health-recover current
        exit 0
      fi
      log_info "queued health recovery failed; request remains pending"
      audit_restart health-recover-pending current
      exit 1
    fi

    if [ ! -f "$candidate_file" ]; then
      log_info "candidate was already promoted"
      exit 0
    fi

    IFS="$(printf '\t')" read -r candidate openchamber_version opencode_version release_id < "$candidate_file"
    case "$candidate" in
      "$tools_root/generations/"*) ;;
      *)
        log_info "candidate path is outside the managed generations directory; latching failure"
        printf '%s\n' "$release_id" > "$failed_file.tmp"
        mv "$failed_file.tmp" "$failed_file"
        rm -f "$candidate_file"
        exit 1
        ;;
    esac
    candidate_real="$(${pkgs.coreutils}/bin/readlink -f "$candidate" 2>/dev/null || true)"
    if [ "$candidate_real" != "$candidate" ] \
      || [ "$(basename "$candidate")" != "$release_id" ]; then
      log_info "candidate $release_id does not resolve to its declared immutable generation; latching failure"
      printf '%s\n' "$release_id" > "$failed_file.tmp"
      mv "$failed_file.tmp" "$failed_file"
      rm -f "$candidate_file"
      exit 1
    fi
    lock_candidate_tree "$candidate"
    if ! ${openchamberToolMaintenance}/bin/openchamber-tool-maintenance \
      validate-candidate "$candidate" "$openchamber_version" "$opencode_version"; then
      log_info "candidate $release_id failed locked pre-promotion validation; latching failure"
      printf '%s\n' "$release_id" > "$failed_file.tmp"
      mv "$failed_file.tmp" "$failed_file"
      rm -f "$candidate_file"
      unlock_generations
      exit 1
    fi

    old_generation="$(readlink -f "$tools_root/active")"
    printf '%s\t%s\t%s\n' "$old_generation" "$candidate" "$release_id" > "$transaction_file.tmp"
    mv "$transaction_file.tmp" "$transaction_file"
    ${pkgs.su-exec}/bin/su-exec openchamber:openchamber ln -sfn "$old_generation" "$previous_link"
    ${pkgs.su-exec}/bin/su-exec openchamber:openchamber ln -sfn "$candidate" "$tools_root/active.next"
    ${pkgs.su-exec}/bin/su-exec openchamber:openchamber mv -Tf "$tools_root/active.next" "$tools_root/active"
    unlock_generations
    audit_restart promote "$release_id"

    restart_ok=1
    ${lib.optionalString externalOpenCode ''
      systemctl restart opencode.service || restart_ok=0
      if [ "$restart_ok" -eq 1 ]; then
        for _ in $(seq 1 30); do
          if opencode_ready; then break; fi
          sleep 2
        done
        opencode_ready || restart_ok=0
      fi
    ''}
    if [ "$restart_ok" -eq 1 ]; then
      systemctl restart openchamber-web.service || restart_ok=0
    fi
    clear_opencode_network_gate
    if [ "$restart_ok" -eq 1 ]; then
      wait_runtime_healthy || restart_ok=0
    fi

    if [ "$restart_ok" -eq 1 ]; then
      rm -f "$candidate_file" "$failed_file" "$transaction_file" "$health_restart_file"
      rm -f "$gate_file"
      gate_armed=0
      prune_generations
      log_info "promoted $release_id after sustained idle"
      exit 0
    fi

    log_info "promotion $release_id failed health checks; restoring previous generation"
    if ! arm_opencode_network_gate allow-absent; then
      log_info "failed to gate OpenCode before rollback; preserving promotion recovery state"
      audit_restart rollback-deferred "$release_id"
      exit 1
    fi
    sleep 30
    if ! maintenance_drained || ! is_openchamber_idle \
      || ! managed_opencode_quiesced_or_absent; then
      log_info "runtime is active or unknown before rollback; preserving promotion recovery state"
      audit_restart rollback-deferred "$release_id"
      exit 1
    fi
    ${pkgs.su-exec}/bin/su-exec openchamber:openchamber ln -sfn "$old_generation" "$tools_root/active.next"
    ${pkgs.su-exec}/bin/su-exec openchamber:openchamber mv -Tf "$tools_root/active.next" "$tools_root/active"
    rollback_ok=1
    ${lib.optionalString externalOpenCode "systemctl restart opencode.service || rollback_ok=0"}
    if [ "$rollback_ok" -eq 1 ]; then
      systemctl restart openchamber-web.service || rollback_ok=0
    fi
    clear_opencode_network_gate
    if [ "$rollback_ok" -ne 1 ] || ! wait_runtime_healthy; then
      log_info "previous generation is not healthy yet; preserving promotion recovery state"
      audit_restart rollback-pending "$release_id"
      exit 1
    fi
    printf '%s\n' "$release_id" > "$failed_file.tmp"
    mv "$failed_file.tmp" "$failed_file"
    rm -f "$candidate_file" "$transaction_file" "$health_restart_file"
    rm -f "$gate_file"
    gate_armed=0
    clear_opencode_network_gate
    audit_restart rollback "$release_id"
    exit 1
  '';

  openchamberRetryGuard = pkgs.writeShellScriptBin "openchamber-retry-guard" ''
    set -eu

    ${openchamberRuntimeEnv}

    state_dir="/run/openchamber-retry-guard"
    state_file="$state_dir/state.json"
    log_file="$HOME/.config/openchamber/logs/openchamber-retry-guard.log"
    install -d -m 0700 "$state_dir"
    mkdir -p "$(dirname "$log_file")"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$log_file"
    }

    if ! snapshot="$(curl -fsS --max-time 10 http://127.0.0.1:3000/api/sessions/status)"; then
      log_info "session status unavailable; retry guard deferred"
      exit 0
    fi

    previous='{}'
    if [ -f "$state_file" ] && jq -e 'type == "object"' "$state_file" >/dev/null 2>&1; then
      previous="$(cat "$state_file")"
    fi

    now_ms="$(($(date -u '+%s') * 1000))"
    next_state="$(
      printf '%s\n' "$snapshot" | jq -c \
        --argjson now "$now_ms" \
        --argjson previous "$previous" '
          reduce (
            .sessions
            | to_entries[]
            | select(.value.status == "retry")
          ) as $item (
            {};
            .[$item.key] = {
              firstSeen: ($previous[$item.key].firstSeen // $now),
              attempt: ($item.value.metadata.attempt // 0),
              message: ($item.value.metadata.message // "provider retry")
            }
          )
        '
    )"

    printf '%s\n' "$next_state" > "$state_file.tmp"
    mv "$state_file.tmp" "$state_file"

    printf '%s\n' "$next_state" | jq -r 'to_entries[] | @base64' |
      while IFS= read -r encoded; do
        entry="$(printf '%s' "$encoded" | base64 -d)"
        session_id="$(printf '%s' "$entry" | jq -r '.key')"
        first_seen="$(printf '%s' "$entry" | jq -r '.value.firstSeen')"
        attempt="$(printf '%s' "$entry" | jq -r '.value.attempt')"
        message="$(printf '%s' "$entry" | jq -r '.value.message')"
        age_ms="$((now_ms - first_seen))"

        if [ "$attempt" -lt 10 ] && [ "$age_ms" -lt 600000 ]; then
          continue
        fi

        # Provider rate limits and outages must not cancel autonomous goals.
        log_info "session=$session_id action=observe-provider-retry attempt=$attempt age_ms=$age_ms reason=$message"
      done
  '';

  openchamberReconcileInterruptedTools = pkgs.writeShellScriptBin "openchamber-reconcile-interrupted-tools" ''
    set -eu

    ${openchamberRuntimeEnv}

    web_is_running=0
    if curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null 2>&1; then
      web_is_running=1
    else
      for cmdline in /proc/[0-9]*/cmdline; do
        if tr '\0' ' ' < "$cmdline" 2>/dev/null |
          grep -Eq '(/| )openchamber serve|opencode serve'; then
          web_is_running=1
          break
        fi
      done
    fi

    if [ "$web_is_running" -eq 1 ]; then
      printf 'info: OpenChamber runtime is active; orphan reconciliation skipped\n'
      exit 0
    fi

    count_query="$(cat <<'SQL'
    SELECT count(*) AS count
    FROM part
    WHERE json_extract(data, '$.type') = 'tool'
      AND json_extract(data, '$.state.status') IN ('running', 'pending');
    SQL
    )"
    count="$(
      opencode db --format json "$count_query" |
        jq -r '.[0].count // 0'
    )"

    case "$count" in
      0) exit 0 ;;
      ""|*[!0-9]*)
        printf 'warning: could not count orphaned OpenCode tools\n' >&2
        exit 0
        ;;
    esac

    update_query="$(cat <<'SQL'
    UPDATE part
    SET data = json_set(
      data,
      '$.state.status', 'error',
      '$.state.error', 'Interrupted by an OpenChamber service restart',
      '$.state.time.end', CAST(strftime('%s', 'now') AS INTEGER) * 1000
    )
    WHERE json_extract(data, '$.type') = 'tool'
      AND json_extract(data, '$.state.status') IN ('running', 'pending');
    SQL
    )"
    opencode db "$update_query" >/dev/null
    printf 'info: reconciled %s orphaned OpenCode tool records\n' "$count"
  '';

  openchamberWebMonitor = pkgs.writeShellScriptBin "openchamber-web-monitor" ''
    set -eu

    ${openchamberRuntimeEnv}

    log_file="$HOME/.config/openchamber/logs/openchamber-web-monitor.log"
    state_dir="/run/openchamber-web-monitor"
    state_file="$state_dir/failure-state"
    mkdir -p "$(dirname "$log_file")"
    install -d -m 0700 "$state_dir"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$log_file"
    }

    ${openchamberIdleCheck}
    ${lib.optionalString externalOpenCode openchamberExternalOpenCodeReady}

    unhealthy_reason=""
    web_was_active=1

    if ! systemctl is-active --quiet openchamber-web.service; then
      unhealthy_reason="openchamber-web.service is not active"
      web_was_active=0
    ${lib.optionalString externalOpenCode ''
      elif ! opencode_ready; then
        unhealthy_reason="external OpenCode endpoint is not ready"
    ''}
    elif ! curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null; then
      unhealthy_reason="OpenChamber root endpoint is not responding"
    fi

    if [ -z "$unhealthy_reason" ]; then
      found_opencode=0
      for cmdline in /proc/[0-9]*/cmdline; do
        if tr '\0' ' ' < "$cmdline" 2>/dev/null | grep -q 'opencode serve'; then
          found_opencode=1
          break
        fi
      done

      if [ "$found_opencode" -ne 1 ]; then
        unhealthy_reason="managed OpenCode server process is missing"
      fi
    fi

    if [ -z "$unhealthy_reason" ]; then
      rm -f "$state_file"
      log_info "healthy"
      exit 0
    fi

    previous_reason=""
    previous_count=0
    if [ -f "$state_file" ]; then
      IFS="$(printf '\t')" read -r previous_count previous_reason < "$state_file" || true
    fi
    if [ "$previous_reason" = "$unhealthy_reason" ]; then
      failure_count="$((previous_count + 1))"
    else
      failure_count=1
    fi
    printf '%s\t%s\n' "$failure_count" "$unhealthy_reason" > "$state_file.tmp"
    mv "$state_file.tmp" "$state_file"

    if [ "$failure_count" -lt 3 ]; then
      log_info "unhealthy: $unhealthy_reason; consecutive failure $failure_count/3; restart deferred"
      exit 0
    fi

    update_control_dir="/var/lib/openchamber-tool-update"
    exec 9<>"$update_control_dir/tool-update.lock"
    if ! ${pkgs.util-linux}/bin/flock -n 9; then
      log_info "unhealthy: $unhealthy_reason; tool maintenance or restart is in progress; restart deferred"
      exit 0
    fi
    if [ -f "$update_control_dir/promotion.tsv" ]; then
      log_info "unhealthy: $unhealthy_reason; tool promotion recovery owns the restart gates; restart deferred"
      exit 0
    fi

    printf '%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      > "$update_control_dir/health-restart.pending.tmp"
    mv "$update_control_dir/health-restart.pending.tmp" \
      "$update_control_dir/health-restart.pending"
    log_info "unhealthy: $unhealthy_reason; queued coordinated idle-gated recovery"
    printf '%s source=health-monitor action=queue-restart reason=%s failures=%s\n' \
      "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$unhealthy_reason" "$failure_count" \
      >> "$HOME/.config/openchamber/logs/restart-audit.log"
    systemctl start --no-block openchamber-tool-update-restart.service || true
    rm -f "$state_file"
  '';

  openchamberContainerHealth = pkgs.writeShellScriptBin "openchamber-container-health" ''
    set -eu

    ${openchamberIdleCheck}
    ${lib.optionalString externalOpenCode openchamberExternalOpenCodeReady}

    if [ -f /var/lib/openchamber-tool-update/promotion.tsv ]; then
      printf 'warning: tool promotion recovery owns the restart gates; container kill deferred\n' >&2
      exit 0
    fi

    read -r uptime _ < /proc/uptime
    uptime_seconds="''${uptime%%.*}"
    if ! manager_started_usec="$(${pkgs.systemd}/bin/systemctl show -p UserspaceTimestampMonotonic --value)"; then
      exit 0
    fi
    case "$manager_started_usec" in
      ""|*[!0-9]*)
        container_age_seconds=3600
        ;;
      *)
        container_age_seconds=$((uptime_seconds - (manager_started_usec / 1000000)))
        if [ "$container_age_seconds" -lt 0 ]; then
          container_age_seconds=3600
        fi
        ;;
    esac
    if ! setup_state="$(${pkgs.systemd}/bin/systemctl show openchamber-container-setup.service -p ActiveState --value)"; then
      exit 0
    fi
    if ! bootstrap_state="$(${pkgs.systemd}/bin/systemctl show openchamber-bootstrap.service -p ActiveState --value)"; then
      exit 0
    fi
    if ! web_state="$(${pkgs.systemd}/bin/systemctl show openchamber-web.service -p ActiveState --value)"; then
      exit 0
    fi

    if [ "$container_age_seconds" -lt 3600 ] \
      && { [ "$setup_state" = "activating" ] \
        || [ "$bootstrap_state" = "activating" ] \
        || [ "$web_state" = "activating" ]; }; then
      exit 0
    fi

    if ${pkgs.curl}/bin/curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null \
      && ${if externalOpenCode then "opencode_ready" else "true"}; then
      exit 0
    fi

    if ! ${pkgs.systemd}/bin/systemctl is-active --quiet openchamber-web.service; then
      ${lib.optionalString externalOpenCode ''
        if ${pkgs.systemd}/bin/systemctl is-active --quiet opencode.service; then
          health_restart=/var/lib/openchamber-tool-update/health-restart.pending
          if [ ! -f "$health_restart" ]; then
            printf '%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$health_restart.tmp"
            mv "$health_restart.tmp" "$health_restart"
          fi
          ${pkgs.systemd}/bin/systemctl start --no-block \
            openchamber-tool-update-restart.service || true
          printf 'warning: OpenChamber web is stopped while external OpenCode is active; coordinated recovery owns its admission gate and container kill is deferred\n' >&2
          exit 0
        fi
      ''}
      exit 1
    fi

    printf 'warning: OpenChamber health is degraded while its service is active; coordinated monitor recovery owns admission gating and container kill is deferred\n' >&2
    exit 0
  '';

  openchamberApplyConfig = pkgs.writeShellScriptBin "openchamber-apply-config" ''
    set -eu

    ${openchamberRuntimeEnv}

    recovery_dir="$HOME/.config/openchamber/recovery"
    last_good="$recovery_dir/last-good"
    log_file="$HOME/.config/openchamber/logs/openchamber-apply-config.log"
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

      mkdir -p "$HOME/.config/openchamber"
      find "$HOME/.config/openchamber" -mindepth 1 -maxdepth 1 \
        ! -name logs \
        ! -name run \
        ! -name recovery \
        -exec rm -rf {} +

      if [ -d "$src/openchamber" ]; then
        tar -C "$src" -cf - openchamber | tar -C "$HOME/.config" -xf -
      fi

      rm -rf "$HOME/.config/opencode"
      if [ -d "$src/opencode" ]; then
        tar -C "$src" -cf - opencode | tar -C "$HOME/.config" -xf -
      else
        mkdir -p "$HOME/.config/opencode"
      fi

      rm -rf "$HOME/.openchamber"
      if [ -d "$src/.openchamber" ]; then
        tar -C "$src" -cf - .openchamber | tar -C "$HOME" -xf -
      else
        mkdir -p "$HOME/.openchamber/hooks/bootstrap.d" \
          "$HOME/.openchamber/hooks/before-openchamber.d" \
          "$HOME/.openchamber/hooks/doctor.d"
      fi
    }

    validate_json_tree() {
      dir="$1"
      [ -d "$dir" ] || return 0
      find "$dir" -type f -name '*.json' \
        ! -path "$HOME/.config/openchamber/logs/*" \
        ! -path "$HOME/.config/openchamber/run/*" \
        ! -path "$HOME/.config/openchamber/recovery/*" \
        -print | while IFS= read -r file; do
          if ! jq -e . "$file" >/dev/null; then
            log_error "invalid JSON: $file"
            exit 1
          fi
        done
    }

    validate_config() {
      command -v openchamber >/dev/null 2>&1 || {
        log_error "openchamber CLI is not installed"
        return 1
      }
      command -v opencode >/dev/null 2>&1 || {
        log_error "opencode CLI is not installed"
        return 1
      }

      validate_json_tree "$HOME/.config/openchamber"
      validate_json_tree "$HOME/.openchamber"
      opencode debug config >/dev/null
    }

    restart_web() {
      ${lib.optionalString externalOpenCode ''
        "$sudo_bin" -n "$systemctl_bin" reset-failed opencode.service
        "$sudo_bin" -n "$systemctl_bin" restart opencode.service
      ''}
      "$sudo_bin" -n "$systemctl_bin" reset-failed openchamber-web.service
      "$sudo_bin" -n "$systemctl_bin" restart openchamber-web.service
    }

    has_opencode_serve() {
      for cmdline in /proc/[0-9]*/cmdline; do
        if tr '\0' ' ' < "$cmdline" 2>/dev/null | grep -q 'opencode serve'; then
          return 0
        fi
      done
      return 1
    }

    opencode_healthy() {
      ${
        if externalOpenCode then
          ''
            curl -fsS --max-time 5 http://127.0.0.1:4096/global/health \
              | jq -e '.healthy == true' >/dev/null 2>&1
          ''
        else
          "has_opencode_serve"
      }
    }

    wait_healthy() {
      for _ in $(seq 1 90); do
        if curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null && opencode_healthy; then
          return 0
        fi
        sleep 1
      done
      return 1
    }

    apply_config() {
      log_info "validating OpenChamber and OpenCode config"
      validate_config

      if [ ! -d "$last_good" ]; then
        log_error "no last-good config snapshot exists; wait for openchamber-web.service to start successfully once"
        exit 1
      fi

      log_info "restarting openchamber-web.service"
      restart_web

      if wait_healthy; then
        log_info "OpenChamber and OpenCode are healthy"
        exit 0
      fi

      log_error "OpenChamber or OpenCode did not become healthy; restoring last-good config"
      restore_config "$last_good"
      validate_config
      restart_web

      if wait_healthy; then
        log_info "rollback restored a healthy OpenChamber runtime"
        exit 1
      fi

      log_error "rollback did not restore a healthy OpenChamber runtime"
      exit 1
    }

    case "''${1:-apply}" in
      apply) apply_config ;;
      *)
        printf 'usage: openchamber-apply-config [apply]\n' >&2
        exit 2
        ;;
    esac
  '';

  openchamberUserUnits = pkgs.writeShellScriptBin "openchamber-user-units" ''
    set -eu

    ${openchamberRuntimeEnv}

    usage() {
      cat >&2 <<EOF
    usage:
      openchamber-user-units reload
      openchamber-user-units enable-now <unit>...
      openchamber-user-units disable-now <unit>...
      openchamber-user-units restart <unit>...
      openchamber-user-units status <unit>...
      openchamber-user-units list-timers
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

  openchamberRunHooks = pkgs.writeShellScriptBin "openchamber-run-hooks" ''
    set -eu

    hook_set="''${1:-}"
    if [ -z "$hook_set" ]; then
      printf 'usage: openchamber-run-hooks <hook-set>\n' >&2
      exit 2
    fi

    ${openchamberRuntimeEnv}
    export OPENCHAMBER_HOOK_SET="$hook_set"

    hook_dir="$HOME/.openchamber/hooks/$hook_set"
    log_file="$HOME/.config/openchamber/logs/openchamber-hooks.log"
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

  openchamberDoctor = pkgs.writeShellScriptBin "openchamber-doctor" ''
    set -eu

    ${openchamberRuntimeEnv}

    ${pkgs.su-exec}/bin/su-exec openchamber:openchamber ${openchamberToolMaintenance}/bin/openchamber-tool-maintenance
    ${openchamberRunHooks}/bin/openchamber-run-hooks doctor.d
  '';

  openchamberBootstrap = pkgs.writeShellScriptBin "openchamber-bootstrap" ''
    set -eu

    ${openchamberRuntimeEnv}

    ${openchamberReconcileInterruptedTools}/bin/openchamber-reconcile-interrupted-tools
    ${openchamberRunHooks}/bin/openchamber-run-hooks bootstrap.d
    ${openchamberRunHooks}/bin/openchamber-run-hooks before-openchamber.d
  '';

  openchamberSnapshotConfig = pkgs.writeShellScriptBin "openchamber-snapshot-config" ''
    set -eu

    ${openchamberRuntimeEnv}

    recovery_dir="$HOME/.config/openchamber/recovery"
    last_good="$recovery_dir/last-good"
    tmp="$recovery_dir/last-good.tmp"

    mkdir -p "$recovery_dir"
    rm -rf "$tmp"
    mkdir -p "$tmp"

    if [ -d "$HOME/.config/openchamber" ]; then
      tar -C "$HOME/.config" \
        --exclude='openchamber/logs' \
        --exclude='openchamber/run' \
        --exclude='openchamber/recovery' \
        -cf - openchamber | tar -C "$tmp" -xf -
    fi

    if [ -d "$HOME/.config/opencode" ]; then
      tar -C "$HOME/.config" -cf - opencode | tar -C "$tmp" -xf -
    fi

    if [ -d "$HOME/.openchamber" ]; then
      tar -C "$HOME" -cf - .openchamber | tar -C "$tmp" -xf -
    fi

    rm -rf "$last_good"
    mv "$tmp" "$last_good"
  '';

  openchamberRuntimeMetadata = pkgs.writeShellScriptBin "openchamber-runtime-metadata" ''
    set -eu

    ${openchamberRuntimeEnv}

    config_file="$HOME/.config/opencode/opencode.json"
    run_dir="$HOME/.config/openchamber/run"
    effective_raw="$run_dir/effective-opencode-config.raw.$$"
    redacted="$run_dir/effective-opencode-config.redacted.json"
    fingerprint="$run_dir/effective-opencode-config.sha256"
    metadata="$run_dir/runtime-metadata.json"
    install -d -m 0755 "$run_dir"

    if [ ! -f "$config_file" ]; then
      printf 'error: managed OpenCode config is missing: %s\n' "$config_file" >&2
      exit 1
    fi
    umask 077
    trap 'rm -f "$effective_raw"' EXIT INT TERM
    opencode debug config > "$effective_raw"
    jq '
      walk(
        if type == "object" then
          with_entries(
            if (.key | test("api.?key|token|secret|password|credential|authorization|cookie"; "i"))
            then .value = "[REDACTED]"
            else .
            end
          )
        else . end
      )
    ' "$effective_raw" > "$redacted.tmp"
    mv "$redacted.tmp" "$redacted"
    rm -f "$effective_raw"
    trap - EXIT INT TERM
    jq -S -c . "$redacted" | sha256sum | cut -d ' ' -f 1 > "$fingerprint.tmp"
    mv "$fingerprint.tmp" "$fingerprint"
    sdk_package="$(find "$NPM_CONFIG_PREFIX/lib/node_modules" -path '*/@opencode-ai/sdk/package.json' -print -quit 2>/dev/null || true)"
    sdk_version=""
    [ -z "$sdk_package" ] || sdk_version="$(jq -r '.version // empty' "$sdk_package")"

    jq -n \
      --arg openchamber "$(openchamber --version | sed -n '1p')" \
      --arg opencode "$(opencode --version | sed -n '1p')" \
      --arg sdk "$sdk_version" \
      --arg model "$(jq -r '.model // empty' "$config_file")" \
      --argjson native_responses ${lib.boolToString nativeResponses} \
      --argjson external_opencode ${lib.boolToString externalOpenCode} \
      --arg config_sha256 "$(cat "$fingerprint")" \
      '{
        openchamber: $openchamber,
        opencode: $opencode,
        opencode_sdk: $sdk,
        model_id: $model,
        config_sha256: $config_sha256,
        feature_gates: {
          native_responses: $native_responses,
          external_opencode: $external_opencode
        }
      }' > "$metadata.tmp"
    mv "$metadata.tmp" "$metadata"
  '';

  openchamberTunnel = pkgs.writeShellScriptBin "openchamber-tunnel" ''
    set -eu

    ${openchamberRuntimeEnv}

    tunnel_dir="$HOME/.config/openchamber/tunnels"
    unit_dir="$HOME/.config/systemd/user"
    log_dir="$HOME/.config/openchamber/logs/tunnels"

    usage() {
      cat >&2 <<EOF
    usage:
      openchamber-tunnel start <name> <port>
      openchamber-tunnel stop <name>
      openchamber-tunnel restart <name> <port>
      openchamber-tunnel status <name>
      openchamber-tunnel url <name>
      openchamber-tunnel list
      openchamber-tunnel remove <name>
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
      printf 'openchamber-tunnel-%s.service' "$1"
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
    Description=OpenChamber quick tunnel: $name
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
        if url="$(openchamber-tunnel url "$name" 2>/dev/null)"; then
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

  openchamberWebRun = pkgs.writeShellScriptBin "openchamber-web-run" ''
    set -eu

    ${openchamberRuntimeEnv}
    export XDG_RUNTIME_DIR=/run/user/3000
    unset OPENCHAMBER_UI_PASSWORD UI_PASSWORD
    export OPENCHAMBER_ALLOW_UNAUTHENTICATED_LAN=true
    export OPENCODE_PORT=4096
    ${lib.optionalString externalOpenCode ''
      export OPENCODE_HOST=http://127.0.0.1:4096
      export OPENCODE_SKIP_START=true
    ''}

    ${openchamberRuntimeMetadata}/bin/openchamber-runtime-metadata

    for _ in $(seq 1 30); do
      if docker info >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    cd /home/openchamber
    rm -f \
      "$HOME/.config/openchamber/run/openchamber-3000.json" \
      "$HOME/.config/openchamber/run/openchamber-3000.pid"

    exec openchamber serve --host 0.0.0.0 --port 3000 --foreground
  '';

  openchamberOpenCodeRun = pkgs.writeShellScriptBin "openchamber-opencode-run" ''
    set -eu

    ${openchamberRuntimeEnv}
    export XDG_RUNTIME_DIR=/run/user/3000
    cd /home/openchamber
    exec opencode serve --hostname 127.0.0.1 --port 4096
  '';

  openchamberHardenActiveGeneration = pkgs.writeShellScriptBin "openchamber-harden-active-generation" ''
    set -eu

    tools_root=/home/openchamber/.local/share/openchamber-tools
    active_generation="$(${pkgs.coreutils}/bin/readlink -f "$tools_root/active" 2>/dev/null || true)"
    case "$active_generation" in
      "$tools_root/generations/"*) ;;
      *)
        printf 'error: active OpenChamber generation is outside the managed tree\n' >&2
        exit 1
        ;;
    esac
    chown -R root:root "$active_generation"
    chmod -R a-w "$active_generation"
  '';

  openchamberContainerSetup = pkgs.writeShellScriptBin "openchamber-container-setup" ''
    set -eu

    ${openchamberRuntimeEnv}

    mkdir -p \
      "$HOME/.local/bin" \
      "$XDG_DATA_HOME/openchamber-tools/generations" \
      "$XDG_STATE_HOME/openchamber-tool-update" \
      "$XDG_DATA_HOME" \
      "$XDG_STATE_HOME" \
      "$XDG_CACHE_HOME" \
      "$HOME/.config/openchamber/logs" \
      "$HOME/.config/openchamber/recovery" \
      "$HOME/.config/openchamber/run" \
      "$HOME/.config/openchamber/tunnels" \
      "$HOME/.config/openchamber/logs/tunnels" \
      "$HOME/.config/opencode" \
      "$HOME/.automation" \
      "$HOME/.config/systemd/user" \
      "$HOME/.openchamber/hooks/bootstrap.d" \
      "$HOME/.openchamber/hooks/before-openchamber.d" \
      "$HOME/.openchamber/hooks/doctor.d" \
      /workspace \
      /mnt/share \
      /var/lib/docker \
      /var/run \
      /tmp \
      /run/user/3000
    install -d -m 0755 -o root -g root /var/lib/openchamber-tool-update
    touch /var/lib/openchamber-tool-update/tool-update.lock
    chown root:root /var/lib/openchamber-tool-update/tool-update.lock
    chmod 0644 /var/lib/openchamber-tool-update/tool-update.lock
    chown -R openchamber:openchamber "$HOME/.openchamber" "$HOME/.config/systemd"
    chown -R openchamber:openchamber "$HOME/.config/openchamber/logs" "$HOME/.config/openchamber/recovery" "$HOME/.config/openchamber/run" "$HOME/.config/openchamber/tunnels"
    chown openchamber:openchamber /run/user/3000
    chmod 0700 /run/user/3000
    managed_opencode_root=/workspace/ghostship-agent/config/opencode
    if [ ! -f "$HOME/.config/opencode/opencode.json" ]; then
      if [ ! -f "$managed_opencode_root/opencode.json" ] \
        || [ ! -f "$managed_opencode_root/AGENTS.md" ] \
        || [ ! -d "$managed_opencode_root/agent" ]; then
        printf 'error: managed OpenCode config is missing from %s\n' "$managed_opencode_root" >&2
        exit 1
      fi
      install -Dm0644 "$managed_opencode_root/opencode.json" "$HOME/.config/opencode/opencode.json"
      install -Dm0644 "$managed_opencode_root/AGENTS.md" "$HOME/.config/opencode/AGENTS.md"
      install -d -m0755 "$HOME/.config/opencode/agent"
      for agent_prompt in "$managed_opencode_root/agent"/*.md; do
        install -m0644 "$agent_prompt" "$HOME/.config/opencode/agent/"
      done
      chown -R openchamber:openchamber "$HOME/.config/opencode"
    fi
    if [ ! -e "$HOME/tools" ] && [ -d /workspace/ghostship-agent/tools ]; then
      ln -s /workspace/ghostship-agent/tools "$HOME/tools"
      chown -h openchamber:openchamber "$HOME/tools"
    fi
    rm -rf \
      "$HOME/.codex" \
      "$HOME/.gemini" \
      "$HOME/.local/state/codex" \
      "$HOME/.local/bin/codex" \
      "$HOME/.local/bin/gemini" \
      "$HOME/.local/bin/gemini-cli"
    chown openchamber:openchamber \
      "$XDG_DATA_HOME/openchamber-tools" \
      "$XDG_DATA_HOME/openchamber-tools/generations"
    chown -R openchamber:openchamber "$XDG_STATE_HOME/openchamber-tool-update"
    transaction_file=/var/lib/openchamber-tool-update/promotion.tsv
    recovery_pending=0
    if [ -f "$transaction_file" ]; then
      IFS="$(printf '\t')" read -r interrupted_old interrupted_candidate interrupted_release < "$transaction_file"
      case "$interrupted_old" in
        "$XDG_DATA_HOME/openchamber-tools/generations/"*) ;;
        *)
          printf 'error: interrupted promotion has an invalid previous generation path\n' >&2
          exit 1
          ;;
      esac
      if [ ! -x "$interrupted_old/bin/openchamber" ] || [ ! -x "$interrupted_old/bin/opencode" ]; then
        printf 'error: interrupted promotion previous generation is incomplete\n' >&2
        exit 1
      fi
      ${pkgs.su-exec}/bin/su-exec openchamber:openchamber ln -sfn "$interrupted_old" "$XDG_DATA_HOME/openchamber-tools/active.next"
      ${pkgs.su-exec}/bin/su-exec openchamber:openchamber mv -Tf \
        "$XDG_DATA_HOME/openchamber-tools/active.next" \
        "$XDG_DATA_HOME/openchamber-tools/active"
      recovery_pending=1
    fi
    if [ "$recovery_pending" -eq 0 ]; then
      rm -f "$OPENCHAMBER_MAINTENANCE_GATE"
      if [ ! -L "$XDG_DATA_HOME/openchamber-tools/active" ] \
        && [ -f "$XDG_STATE_HOME/openchamber-tool-update/candidate.tsv" ]; then
        # The host already validated this immutable generation while the old
        # container was live. Activate it without returning to the registry.
        ${pkgs.su-exec}/bin/su-exec openchamber:openchamber \
          ${openchamberToolMaintenance}/bin/openchamber-tool-maintenance bootstrap-candidate
      else
        # Resolve and validate npm latest. Initial startup promotes before any
        # service can own a session; later candidates remain queued until idle.
        ${pkgs.su-exec}/bin/su-exec openchamber:openchamber \
          ${openchamberToolMaintenance}/bin/openchamber-tool-maintenance bootstrap
      fi
    else
      # Keep the transaction and admission gate intact. The restart worker
      # clears them only after the restored runtime is healthy.
      printf 'interrupted tool promotion recovery remains pending after startup\n' >&2
    fi
    cat > "$HOME/.local/bin/openchamber-web-run" <<'EOF'
    #!/bin/sh
    exec ${openchamberWebRun}/bin/openchamber-web-run "$@"
    EOF
    chown openchamber:openchamber "$HOME/.local/bin/openchamber-web-run"
    chmod 0755 "$HOME/.local/bin/openchamber-web-run"
    cat > "$HOME/.local/bin/openchamber-tunnel" <<'EOF'
    #!/bin/sh
    exec ${openchamberTunnel}/bin/openchamber-tunnel "$@"
    EOF
    chown openchamber:openchamber "$HOME/.local/bin/openchamber-tunnel"
    chmod 0755 "$HOME/.local/bin/openchamber-tunnel"
    cat > "$HOME/.local/bin/openchamber-user-units" <<'EOF'
    #!/bin/sh
    exec ${openchamberUserUnits}/bin/openchamber-user-units "$@"
    EOF
    chown openchamber:openchamber "$HOME/.local/bin/openchamber-user-units"
    chmod 0755 "$HOME/.local/bin/openchamber-user-units"
    cat > "$HOME/.local/bin/openchamber-apply-config" <<'EOF'
    #!/bin/sh
    exec ${openchamberApplyConfig}/bin/openchamber-apply-config "$@"
    EOF
    chown openchamber:openchamber "$HOME/.local/bin/openchamber-apply-config"
    chmod 0755 "$HOME/.local/bin/openchamber-apply-config"
    rm -f "$HOME/.local/bin/openchamber-proxy"

  '';

  openchamberDockerdRun = pkgs.writeShellScriptBin "openchamber-dockerd-run" ''
    set -eu

    ${openchamberRuntimeEnv}

    rm -f /var/run/docker.pid
    exec dockerd \
      --host=unix:///var/run/docker.sock \
      --group=openchamber \
      --data-root=/var/lib/docker \
      --storage-driver=vfs \
      --iptables=false \
      --ip-masq=false \
      --bridge=none
  '';

  openchamberEntrypoint = pkgs.writeShellScriptBin "openchamber-systemd-entrypoint" ''
    set -eu

    exec ${pkgs.systemd}/lib/systemd/systemd
  '';

  openchamberImageContents = openchamberPackages ++ [
    openchamberEntrypoint
    openchamberContainerSetup
    openchamberDockerdRun
    openchamberWebRun
    openchamberOpenCodeRun
    openchamberHardenActiveGeneration
    openchamberToolMaintenance
    openchamberToolAutoUpdate
    openchamberCacheCleanup
    openchamberToolUpdateRestart
    openchamberRetryGuard
    openchamberReconcileInterruptedTools
    openchamberWebMonitor
    openchamberContainerHealth
    openchamberRunHooks
    openchamberDoctor
    openchamberApplyConfig
    openchamberUserUnits
    openchamberBootstrap
    openchamberSnapshotConfig
    openchamberRuntimeMetadata
    openchamberTunnel
    pkgs.dockerTools.binSh
    pkgs.dockerTools.usrBinEnv
    pkgs.dockerTools.caCertificates
  ];

  openchamberImage = pkgs.dockerTools.buildLayeredImageWithNixDb {
    name = imageName;
    tag = imageTag;
    contents = openchamberImageContents;
    extraCommands = ''
      mkdir -p etc/nix etc/pam.d etc/sudoers.d etc/systemd/system/multi-user.target.wants etc/systemd/user/sockets.target.wants usr/bin usr/share/systemd/user nix/store nix/var/log/nix nix/var/nix tmp workspace home/openchamber
      mkdir -p mnt/share run/user var/empty var/lib/docker var/log/journal var/run
      chmod 1777 tmp
      chmod 0555 var/empty
      cp ${pkgs.sudo}/bin/sudo usr/bin/sudo
      chmod 0755 usr/bin/sudo
      cat > etc/passwd <<'EOF'
      root:x:0:0:root:/root:/bin/sh
      openchamber:x:3000:3000:OpenChamber:/home/openchamber:/bin/sh
      EOF
      cat > etc/group <<'EOF'
      root:x:0:
      openchamber:x:3000:
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
      allowed-users = root openchamber
      trusted-users = root
      build-users-group = nixbld
      EOF
      rm -f etc/sudoers etc/sudoers.d/openchamber-apply-config etc/pam.d/sudo
      cat > etc/sudoers <<'EOF'
      root ALL=(ALL:ALL) ALL
      #includedir /etc/sudoers.d
      EOF
      chmod 0440 etc/sudoers
      cat > etc/sudoers.d/openchamber-apply-config <<'EOF'
      openchamber ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl reset-failed openchamber-web.service
      openchamber ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl restart openchamber-web.service
      ${lib.optionalString externalOpenCode "openchamber ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl reset-failed opencode.service"}
      ${lib.optionalString externalOpenCode "openchamber ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl restart opencode.service"}
      EOF
      chmod 0440 etc/sudoers.d/openchamber-apply-config
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
      cat > etc/systemd/system/openchamber-container-setup.service <<'EOF'
      [Unit]
      Description=Prepare OpenChamber container state
      DefaultDependencies=no
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      ExecStart=${openchamberContainerSetup}/bin/openchamber-container-setup
      RemainAfterExit=yes
      TimeoutStartSec=30m
      MemoryHigh=2G
      MemoryMax=4G
      OOMPolicy=kill
      TasksMax=512

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/nix-daemon.service <<'EOF'
      [Unit]
      Description=Nix package manager daemon
      DefaultDependencies=no
      After=openchamber-container-setup.service nix-daemon.socket
      Requires=openchamber-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=user@3000.service openchamber-bootstrap.service openchamber-web.service shutdown.target

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
      After=openchamber-container-setup.service
      Requires=openchamber-container-setup.service
      Conflicts=shutdown.target
      Before=nix-daemon.service user@3000.service openchamber-bootstrap.service openchamber-web.service shutdown.target

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
      Description=OpenChamber user manager for UID %i
      Documentation=man:user@.service(5)
      DefaultDependencies=no
      After=openchamber-container-setup.service nix-daemon.socket
      Requires=openchamber-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=openchamber-bootstrap.service openchamber-web.service shutdown.target
      IgnoreOnIsolate=yes

      [Service]
      User=%i
      PAMName=systemd-user
      Type=notify-reload
      Environment=HOME=/home/openchamber
      Environment=USER=openchamber
      Environment=LOGNAME=openchamber
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
      Description=OpenChamber Docker daemon
      DefaultDependencies=no
      After=openchamber-container-setup.service
      Requires=openchamber-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=simple
      ExecStart=${openchamberDockerdRun}/bin/openchamber-dockerd-run
      Restart=always
      RestartSec=5
      TimeoutStopSec=30s
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-bootstrap.service <<'EOF'
      [Unit]
      Description=Run OpenChamber bootstrap hooks
      DefaultDependencies=no
      After=openchamber-container-setup.service nix-daemon.socket user@3000.service dockerd.service
      Requires=openchamber-container-setup.service nix-daemon.socket user@3000.service dockerd.service
      Conflicts=shutdown.target
      Before=${lib.optionalString externalOpenCode "opencode.service "}openchamber-web.service shutdown.target

      [Service]
      Type=oneshot
      User=openchamber
      Group=openchamber
      Environment=HOME=/home/openchamber
      Environment=USER=openchamber
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=OPENCODE_AUTOMATION_DIR=/home/openchamber/.automation
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/active/bin:${openchamberPath}:/bin:/usr/bin
      ExecCondition=+${pkgs.runtimeShell} -c 'state="$(${pkgs.systemd}/bin/systemctl show openchamber-web.service -p ActiveState --value)" && { [ "$state" = inactive ] || [ "$state" = failed ]; }'
      ExecStart=${openchamberBootstrap}/bin/openchamber-bootstrap
      ExecStartPost=+${openchamberHardenActiveGeneration}/bin/openchamber-harden-active-generation
      RemainAfterExit=yes
      TimeoutStartSec=20m
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-bootstrap.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-bootstrap.log
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      ${lib.optionalString externalOpenCode ''
        cat > etc/systemd/system/openchamber-runtime.slice <<'EOF'
        [Unit]
        Description=OpenChamber runtime aggregate resource boundary
        DefaultDependencies=no
        Conflicts=shutdown.target
        Before=shutdown.target

        [Slice]
        MemoryHigh=32G
        MemoryMax=40G
        EOF
        cat > etc/systemd/system/opencode.service <<'EOF'
        [Unit]
        Description=OpenCode server for OpenChamber
        DefaultDependencies=no
        After=openchamber-bootstrap.service
        Requires=openchamber-bootstrap.service
        Conflicts=shutdown.target
        Before=openchamber-web.service shutdown.target

        [Service]
        Slice=openchamber-runtime.slice
        Type=simple
        User=openchamber
        Group=openchamber
        Environment=HOME=/home/openchamber
        Environment=USER=openchamber
        Environment=XDG_RUNTIME_DIR=/run/user/3000
        Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
        Environment=OPENCODE_AUTOMATION_DIR=/home/openchamber/.automation
        Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/active/bin:${openchamberPath}:/bin:/usr/bin
        ExecStart=${openchamberOpenCodeRun}/bin/openchamber-opencode-run
        Restart=always
        RestartSec=5
        TimeoutStartSec=2m
        TimeoutStopSec=30s
        SuccessExitStatus=0 143
        StandardOutput=append:/home/openchamber/.config/openchamber/logs/opencode.service.log
        StandardError=append:/home/openchamber/.config/openchamber/logs/opencode.service.log
        MemoryHigh=24G
        MemoryMax=32G
        OOMPolicy=continue
        TasksMax=infinity

        [Install]
        WantedBy=multi-user.target
        EOF
      ''}
      cat > etc/systemd/system/openchamber-web.service <<'EOF'
      [Unit]
      Description=OpenChamber Web
      DefaultDependencies=no
      After=openchamber-bootstrap.service${lib.optionalString externalOpenCode " opencode.service"}
      Requires=openchamber-bootstrap.service${lib.optionalString externalOpenCode " opencode.service"}
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      ${lib.optionalString externalOpenCode "Slice=openchamber-runtime.slice"}
      Type=simple
      User=openchamber
      Group=openchamber
      Environment=HOME=/home/openchamber
      Environment=USER=openchamber
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=OPENCODE_AUTOMATION_DIR=/home/openchamber/.automation
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/active/bin:${openchamberPath}:/bin:/usr/bin
      ExecStart=${openchamberWebRun}/bin/openchamber-web-run
      ExecStartPost=${openchamberSnapshotConfig}/bin/openchamber-snapshot-config
      Restart=always
      RestartSec=5
      TimeoutStartSec=20m
      TimeoutStopSec=30s
      SuccessExitStatus=0 143
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-web.service.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-web.service.log
      MemoryHigh=32G
      MemoryMax=40G
      OOMPolicy=continue
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-tool-auto-update.service <<'EOF'
      [Unit]
      Description=Update OpenChamber and OpenCode tools
      DefaultDependencies=no
      After=openchamber-bootstrap.service
      Requires=openchamber-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/active/bin:${openchamberPath}:/bin:/usr/bin
      ExecStart=${openchamberToolAutoUpdate}/bin/openchamber-tool-auto-update
      TimeoutStartSec=30m
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-tool-auto-update.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-tool-auto-update.log
      MemoryHigh=2G
      MemoryMax=4G
      OOMPolicy=kill
      TasksMax=512
      EOF
      cat > etc/systemd/system/openchamber-tool-auto-update.timer <<'EOF'
      [Unit]
      Description=Periodic OpenChamber and OpenCode tool updates
      DefaultDependencies=no
      After=openchamber-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=10m
      OnUnitActiveSec=4h
      Persistent=true
      Unit=openchamber-tool-auto-update.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-cache-cleanup.service <<'EOF'
      [Unit]
      Description=Prune stale OpenChamber tool cache files
      DefaultDependencies=no
      After=openchamber-bootstrap.service
      Requires=openchamber-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      User=openchamber
      Group=openchamber
      Environment=HOME=/home/openchamber
      Environment=USER=openchamber
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/active/bin:${openchamberPath}:/bin:/usr/bin
      ExecStart=${openchamberCacheCleanup}/bin/openchamber-cache-cleanup
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-cache-cleanup.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-cache-cleanup.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/openchamber-cache-cleanup.timer <<'EOF'
      [Unit]
      Description=Daily bounded OpenChamber tool cache cleanup
      DefaultDependencies=no
      After=openchamber-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=15m
      OnUnitActiveSec=1d
      Persistent=true
      Unit=openchamber-cache-cleanup.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-tool-update-restart.service <<'EOF'
      [Unit]
      Description=Restart OpenChamber after queued maintenance becomes idle
      DefaultDependencies=no
      After=openchamber-bootstrap.service
      Requires=openchamber-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/active/bin:${openchamberPath}:/bin:/usr/bin
      ExecStart=${openchamberToolUpdateRestart}/bin/openchamber-tool-update-restart
      TimeoutStartSec=20m
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-tool-update-restart.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-tool-update-restart.log
      MemoryHigh=2G
      MemoryMax=4G
      OOMPolicy=kill
      TasksMax=512
      EOF
      cat > etc/systemd/system/openchamber-tool-update-restart.timer <<'EOF'
      [Unit]
      Description=Apply queued OpenChamber maintenance when idle
      DefaultDependencies=no
      After=openchamber-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=openchamber-tool-update-restart.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-retry-guard.service <<'EOF'
      [Unit]
      Description=Bound repeated OpenCode provider retries
      DefaultDependencies=no
      After=openchamber-web.service
      Wants=openchamber-web.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/active/bin:${openchamberPath}:/bin:/usr/bin
      ExecStart=${openchamberRetryGuard}/bin/openchamber-retry-guard
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-retry-guard.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-retry-guard.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/openchamber-retry-guard.timer <<'EOF'
      [Unit]
      Description=Periodic OpenCode provider retry guard
      DefaultDependencies=no
      After=openchamber-web.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=openchamber-retry-guard.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-web-monitor.service <<'EOF'
      [Unit]
      Description=Monitor OpenChamber web and managed OpenCode
      DefaultDependencies=no
      After=openchamber-web.service
      Wants=openchamber-web.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/active/bin:${openchamberPath}:/bin:/usr/bin
      ExecStart=${openchamberWebMonitor}/bin/openchamber-web-monitor
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-web-monitor.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-web-monitor.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/openchamber-web-monitor.timer <<'EOF'
      [Unit]
      Description=Periodic OpenChamber web monitor
      DefaultDependencies=no
      After=openchamber-web.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=openchamber-web-monitor.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/multi-user.target <<'EOF'
      [Unit]
      Description=OpenChamber Multi-User System
      DefaultDependencies=no
      Wants=openchamber-container-setup.service nix-daemon.socket nix-daemon.service user@3000.service dockerd.service openchamber-bootstrap.service${lib.optionalString externalOpenCode " opencode.service"} openchamber-web.service openchamber-tool-auto-update.timer openchamber-cache-cleanup.timer openchamber-tool-update-restart.timer openchamber-retry-guard.timer openchamber-web-monitor.timer
      After=openchamber-container-setup.service nix-daemon.socket user@3000.service dockerd.service
      AllowIsolate=yes
      EOF
      rm -f etc/systemd/system/docker.service \
        etc/systemd/system/docker.socket \
        etc/systemd/system/multi-user.target.wants/docker.service \
        etc/systemd/system/sockets.target.wants/docker.socket
      ln -s multi-user.target etc/systemd/system/default.target
      ln -s ../openchamber-container-setup.service etc/systemd/system/multi-user.target.wants/openchamber-container-setup.service
      ln -s ../nix-daemon.socket etc/systemd/system/multi-user.target.wants/nix-daemon.socket
      ln -s ../nix-daemon.service etc/systemd/system/multi-user.target.wants/nix-daemon.service
      ln -s ../user@.service etc/systemd/system/multi-user.target.wants/user@3000.service
      ln -s ../dockerd.service etc/systemd/system/multi-user.target.wants/dockerd.service
      ln -s ../openchamber-bootstrap.service etc/systemd/system/multi-user.target.wants/openchamber-bootstrap.service
      ${lib.optionalString externalOpenCode "ln -s ../opencode.service etc/systemd/system/multi-user.target.wants/opencode.service"}
      ln -s ../openchamber-web.service etc/systemd/system/multi-user.target.wants/openchamber-web.service
      ln -s ../openchamber-tool-auto-update.timer etc/systemd/system/multi-user.target.wants/openchamber-tool-auto-update.timer
      ln -s ../openchamber-cache-cleanup.timer etc/systemd/system/multi-user.target.wants/openchamber-cache-cleanup.timer
      ln -s ../openchamber-tool-update-restart.timer etc/systemd/system/multi-user.target.wants/openchamber-tool-update-restart.timer
      ln -s ../openchamber-retry-guard.timer etc/systemd/system/multi-user.target.wants/openchamber-retry-guard.timer
      ln -s ../openchamber-web-monitor.timer etc/systemd/system/multi-user.target.wants/openchamber-web-monitor.timer
    '';
    fakeRootCommands = ''
      chown -R root:root nix/store nix/var/log/nix nix/var/nix
      chmod -R u+rwX,go+rX nix/store nix/var/log/nix nix/var/nix
      chown 0:0 usr/bin/sudo
      chmod 4755 usr/bin/sudo
    '';
    config = {
      Cmd = [ "${openchamberEntrypoint}/bin/openchamber-systemd-entrypoint" ];
      Env = [
        "HOME=/home/openchamber"
        "USER=openchamber"
        "DOCKER_HOST=unix:///var/run/docker.sock"
        "XDG_RUNTIME_DIR=/run/user/3000"
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus"
        "XDG_CONFIG_HOME=/home/openchamber/.config"
        "XDG_STATE_HOME=/home/openchamber/.local/state"
        "XDG_CACHE_HOME=/home/openchamber/.cache"
        "XDG_DATA_HOME=/home/openchamber/.local/share"
        "NPM_CONFIG_PREFIX=/home/openchamber/.local/share/openchamber-tools/active"
        "npm_config_prefix=/home/openchamber/.local/share/openchamber-tools/active"
        "OPENCODE_AUTOMATION_DIR=/home/openchamber/.automation"
        "PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/active/bin:${openchamberPath}:/bin:/usr/bin"
        "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "NIX_CONFIG=experimental-features = nix-command flakes"
        "NIX_REMOTE=daemon"
        "OPENCHAMBER_ALLOW_UNAUTHENTICATED_LAN=true"
      ];
      WorkingDir = "/home/openchamber";
      ExposedPorts = {
        "3000/tcp" = { };
      };
    };
  };

  openchamberDeploymentId = builtins.hashString "sha256" (toString openchamberImage);
  openchamberDeployWhenIdle = pkgs.writeShellScriptBin "openchamber-deploy-when-idle" ''
    set -eu

    state_dir=${openchamberDeploymentState}
    desired_file="$state_dir/desired"
    applied_file="$state_dir/applied"
    applying_file="$state_dir/applying"
    failed_file="$state_dir/failed"
    rollback_image_file="$state_dir/rollback-image"
    rollback_desired_file="$state_dir/rollback-desired"
    gate_file=${openchamberToolControl}/admission.lock
    promotion_file=${openchamberToolControl}/promotion.tsv
    rollback_override_dir=/run/systemd/system/podman-openchamber.service.d
    rollback_override="$rollback_override_dir/rollback-image.conf"
    audit_log=${openchamberHome}/.config/openchamber/logs/restart-audit.log
    host_gate_armed=0
    host_opencode_gate_armed=0
    container_was_active=0
    previous_image=""

    install -d -m 0755 "$state_dir"
    install -d -m 0755 -o 3000 -g 3000 "$(dirname "$audit_log")"
    [ -f "$desired_file" ] || exit 0

    desired="$(cat "$desired_file")"
    applied=""
    failed=""
    [ ! -f "$applied_file" ] || applied="$(cat "$applied_file")"
    [ ! -f "$failed_file" ] || failed="$(cat "$failed_file")"
    log_info() {
      message="$1"
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$message"
      printf '%s source=host-deployment %s\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$message" >> "$audit_log"
    }

    clear_rollback_override() {
      [ -f "$rollback_override" ] || return 0
      rm -f "$rollback_override"
      rmdir "$rollback_override_dir" 2>/dev/null || true
      ${pkgs.systemd}/bin/systemctl daemon-reload
    }

    clear_rollback_state() {
      rm -f "$rollback_image_file" "$rollback_desired_file"
    }

    persist_rollback_state() {
      printf '%s\n' "$previous_image" > "$rollback_image_file.tmp"
      mv "$rollback_image_file.tmp" "$rollback_image_file"
      printf '%s\n' "$desired" > "$rollback_desired_file.tmp"
      mv "$rollback_desired_file.tmp" "$rollback_desired_file"
    }

    rollback_container_healthy() {
      [ "$(${pkgs.podman}/bin/podman inspect openchamber \
        --format '{{.Image}}' 2>/dev/null || true)" = "$previous_image" ] \
        && [ "$(${pkgs.podman}/bin/podman inspect openchamber \
          --format '{{.State.Health.Status}}' 2>/dev/null || true)" = "healthy" ] \
        && ${pkgs.podman}/bin/podman exec openchamber \
          systemctl is-active --quiet openchamber-web.service \
        && ${pkgs.podman}/bin/podman exec openchamber \
          curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null 2>&1
    }

    clear_host_opencode_network_gate() {
      if [ "$host_opencode_gate_armed" -ne 1 ] && [ "''${1:-}" != force ]; then
        return 0
      fi
      ${pkgs.podman}/bin/podman exec openchamber \
        iptables -D OUTPUT -j OPENCHAMBER_OPENCODE_GATE 2>/dev/null || true
      ${pkgs.podman}/bin/podman exec openchamber \
        iptables -F OPENCHAMBER_OPENCODE_GATE 2>/dev/null || true
      ${pkgs.podman}/bin/podman exec openchamber \
        iptables -X OPENCHAMBER_OPENCODE_GATE 2>/dev/null || true
      host_opencode_gate_armed=0
    }

    disarm_host_gate() {
      clear_host_opencode_network_gate
      if [ "$host_gate_armed" -eq 1 ]; then
        rm -f "$gate_file"
        host_gate_armed=0
      fi
    }
    trap disarm_host_gate EXIT INT TERM

    maintenance_snapshot() {
      ${pkgs.podman}/bin/podman exec openchamber \
        curl -fsS --max-time 5 \
          http://127.0.0.1:3000/api/openchamber/maintenance-drain
    }

    maintenance_supported() {
      maintenance_snapshot | ${pkgs.jq}/bin/jq -e '
        (.inFlightMutations | type) == "number"
        and (.activeTerminalSessions | type) == "number"
        and (.activeOpenCodeSessions | type) == "number"
        and (.activeScheduledTasks | type) == "number"
        and (.activeGoalWork | type) == "number"
        and (.observerPaused | type) == "boolean"
        and (.schedulerPaused | type) == "boolean"
      ' >/dev/null 2>&1
    }

    maintenance_drained() {
      maintenance_snapshot | ${pkgs.jq}/bin/jq -e '
        .inFlightMutations == 0
        and .activeTerminalSessions == 0
        and .activeOpenCodeSessions == 0
        and .activeScheduledTasks == 0 and .activeGoalWork == 0
        and .observerPaused == true
        and .schedulerPaused == true
      ' >/dev/null 2>&1
    }

    is_live_idle() {
      if ! activity="$(${pkgs.podman}/bin/podman exec openchamber \
        curl -fsS --max-time 5 http://127.0.0.1:3000/api/session-activity 2>/dev/null)"; then
        return 1
      fi
      printf '%s\n' "$activity" | ${pkgs.jq}/bin/jq -e '
        type == "object"
        and all(.[]; type == "object" and .type == "idle")
      ' >/dev/null 2>&1
    }

    mark_failed() {
      printf '%s\n' "$desired" > "$failed_file.tmp"
      mv "$failed_file.tmp" "$failed_file"
      rm -f "$applying_file"
    }

    managed_opencode_probe() {
      ${pkgs.podman}/bin/podman exec -i --user 3000:3000 \
        --env PATH=/bin:/usr/bin openchamber \
        /bin/bash -s -- "$@" < ${openchamberManagedOpenCodeIdlePortable}
    }

    managed_opencode_root_probe() {
      ${pkgs.podman}/bin/podman exec -i \
        --env PATH=/bin:/usr/bin openchamber \
        /bin/bash -s -- "$@" < ${openchamberManagedOpenCodeIdlePortable}
    }

    managed_opencode_process_present() {
      ${pkgs.podman}/bin/podman exec -i \
        --env PATH=/bin:/usr/bin openchamber \
        /bin/bash -s < ${openchamberManagedOpenCodePresentPortable}
    }

    managed_opencode_quiesced_or_absent() {
      if ! managed_opencode_process_present; then
        return 0
      fi
      managed_opencode_probe --connections-drained \
        && managed_opencode_root_probe
    }

    arm_host_opencode_network_gate() {
      opencode_port="$(managed_opencode_probe --print-port)" \
        || {
          if [ "''${1:-}" = allow-absent ] \
            && ! managed_opencode_process_present; then
            opencode_port=4096
          else
            return 1
          fi
        }
      case "$opencode_port" in
        ""|*[!0-9]*) return 1 ;;
      esac
      host_opencode_gate_armed=1
      ${pkgs.podman}/bin/podman exec openchamber \
        iptables -N OPENCHAMBER_OPENCODE_GATE 2>/dev/null || true
      ${pkgs.podman}/bin/podman exec openchamber \
        iptables -C OPENCHAMBER_OPENCODE_GATE \
          -p tcp --syn --dport "$opencode_port" -m conntrack --ctstate NEW \
          -m owner '!' --uid-owner 0 -j REJECT 2>/dev/null \
        || ${pkgs.podman}/bin/podman exec openchamber \
          iptables -A OPENCHAMBER_OPENCODE_GATE \
            -p tcp --syn --dport "$opencode_port" -m conntrack --ctstate NEW \
            -m owner '!' --uid-owner 0 -j REJECT \
        || return 1
      ${pkgs.podman}/bin/podman exec openchamber \
        iptables -C OUTPUT -j OPENCHAMBER_OPENCODE_GATE 2>/dev/null \
        || ${pkgs.podman}/bin/podman exec openchamber \
          iptables -I OUTPUT 1 -j OPENCHAMBER_OPENCODE_GATE \
        || return 1
    }

    quiesce_active_container() {
      exec 9<>${openchamberToolControl}/tool-update.lock
      if ! ${pkgs.util-linux}/bin/flock -n 9; then
        log_info "action=defer desired=$desired reason=tool-update-in-progress"
        return 1
      fi
      if [ -f "$promotion_file" ]; then
        log_info "action=defer desired=$desired reason=tool-promotion-recovery"
        return 1
      fi
      clear_host_opencode_network_gate force
      if ! is_live_idle; then
        log_info "action=defer desired=$desired reason=active-or-unknown"
        return 1
      fi
      if ! maintenance_supported; then
        log_info "action=defer desired=$desired reason=legacy-runtime-needs-controlled-stop"
        return 1
      fi
      printf '%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$gate_file.tmp"
      mv "$gate_file.tmp" "$gate_file"
      host_gate_armed=1
      sleep 1
      if ! maintenance_drained || ! is_live_idle; then
        log_info "action=defer desired=$desired reason=admissions-still-draining"
        return 1
      fi
      if ! managed_opencode_probe; then
        log_info "action=defer desired=$desired reason=managed-opencode-active-or-unknown"
        return 1
      fi
      if ! arm_host_opencode_network_gate; then
        log_info "action=defer desired=$desired reason=direct-opencode-gate-failed"
        return 1
      fi
      log_info "action=admissions-gated desired=$desired wait_seconds=30"
      sleep 30
      if ! maintenance_drained || ! is_live_idle; then
        log_info "action=defer desired=$desired reason=activity-resumed-or-drain-incomplete"
        return 1
      fi
      if ! managed_opencode_probe --connections-drained; then
        log_info "action=defer desired=$desired reason=direct-opencode-connections-remain"
        return 1
      fi
      if ! managed_opencode_root_probe; then
        log_info "action=defer desired=$desired reason=managed-opencode-resumed-or-unknown"
        return 1
      fi
    }

    quiesce_failed_replacement() {
      exec 9<>${openchamberToolControl}/tool-update.lock
      if ! ${pkgs.util-linux}/bin/flock -n 9; then
        log_info "action=defer desired=$desired reason=tool-update-in-progress"
        return 1
      fi
      if [ -f "$promotion_file" ]; then
        log_info "action=defer desired=$desired reason=tool-promotion-recovery"
        return 1
      fi
      clear_host_opencode_network_gate force
      printf '%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$gate_file.tmp"
      mv "$gate_file.tmp" "$gate_file"
      host_gate_armed=1
      if ! arm_host_opencode_network_gate allow-absent; then
        log_info "action=defer desired=$desired reason=failed-replacement-opencode-gate-failed"
        return 1
      fi
      log_info "action=failed-replacement-gated desired=$desired wait_seconds=30"
      sleep 30
      if ! managed_opencode_quiesced_or_absent; then
        log_info "action=defer desired=$desired reason=failed-replacement-opencode-active-or-unknown"
        return 1
      fi
    }

    stop_quiesced_container() {
      [ "$container_was_active" -eq 1 ] || return 0
      previous_image="$(${pkgs.podman}/bin/podman inspect openchamber \
        --format '{{.Image}}' 2>/dev/null || true)"
      if [ -z "$previous_image" ] \
        || ! ${pkgs.podman}/bin/podman image exists "$previous_image"; then
        log_info "action=defer desired=$desired reason=previous-container-image-unknown"
        return 1
      fi
      persist_rollback_state
      log_info "action=stop-quiesced-container desired=$desired"
      if ! ${pkgs.systemd}/bin/systemctl stop podman-openchamber.service; then
        clear_rollback_state
        log_info "action=deployment-failed desired=$desired reason=container-stop"
        return 1
      fi
      host_gate_armed=0
      host_opencode_gate_armed=0
      ${pkgs.util-linux}/bin/flock -u 9
    }

    start_replacement_container() {
      log_info "action=start-container desired=$desired"
      if ! ${pkgs.systemd}/bin/systemctl start podman-openchamber.service; then
        log_info "action=deployment-failed desired=$desired reason=container-start"
        return 1
      fi
    }

    restore_previous_container() {
      [ -n "$previous_image" ] || return 1
      log_info "action=restore-previous-container desired=$desired image=$previous_image"
      ${pkgs.systemd}/bin/systemctl stop podman-openchamber.service || return 1
      # Bootstrap takes the same lock; release it only after the old writer stops.
      host_gate_armed=0
      host_opencode_gate_armed=0
      ${pkgs.util-linux}/bin/flock -u 9 2>/dev/null || true
      ${pkgs.podman}/bin/podman tag "$previous_image" ${imageName}:${imageTag} \
        || return 1
      install -d -m 0755 "$rollback_override_dir"
      {
        printf '%s\n' '[Service]'
        printf '%s\n' 'ExecStartPre='
        printf '%s\n' 'ExecStartPre=-${pkgs.podman}/bin/podman rm -f openchamber'
        printf '%s\n' 'ExecStartPre=${pkgs.coreutils}/bin/rm -f /run/openchamber/ctr-id'
      } > "$rollback_override.tmp"
      mv "$rollback_override.tmp" "$rollback_override"
      ${pkgs.systemd}/bin/systemctl daemon-reload
      ${pkgs.systemd}/bin/systemctl start podman-openchamber.service \
        || return 1
      for _ in $(seq 1 150); do
        if [ "$(${pkgs.podman}/bin/podman inspect openchamber \
          --format '{{.State.Health.Status}}' 2>/dev/null || true)" = "healthy" ] \
          && ${pkgs.podman}/bin/podman exec openchamber \
            systemctl is-active --quiet openchamber-web.service \
          && ${pkgs.podman}/bin/podman exec openchamber \
            curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null 2>&1; then
          log_info "action=restore-complete desired=$desired image=$previous_image"
          return 0
        fi
        sleep 2
      done
      log_info "action=restore-failed desired=$desired image=$previous_image"
      return 1
    }

    restore_previous_when_safe() {
      if ${pkgs.systemd}/bin/systemctl is-active --quiet podman-openchamber.service; then
        container_was_active=1
        web_state="$(${pkgs.podman}/bin/podman exec openchamber \
          systemctl show openchamber-web.service -p ActiveState --value \
          2>/dev/null || true)"
        case "$web_state" in
          active)
            quiesce_active_container || return 1
            ;;
          inactive|failed)
            quiesce_failed_replacement || return 1
            ;;
          *)
            log_info "action=defer desired=$desired reason=failed-replacement-web-state-$web_state"
            return 1
            ;;
        esac
      fi
      restore_previous_container
    }

    ensure_first_generation() {
      active_link=${openchamberHome}/.local/share/openchamber-tools/active
      if [ -L "$active_link" ] \
        || ! ${pkgs.systemd}/bin/systemctl is-active --quiet podman-openchamber.service; then
        return 0
      fi

      log_info "action=prestage-first-generation reason=migrate-running-runtime"
      install -d -m 0755 -o 3000 -g 3000 \
        ${openchamberHome}/.local/share/openchamber-tools/generations \
        ${openchamberHome}/.local/state/openchamber-tool-update
      install -d -m 0755 -o root -g root ${openchamberToolControl}
      touch ${openchamberToolControl}/tool-update.lock
      chown root:root ${openchamberToolControl}/tool-update.lock
      chmod 0644 ${openchamberToolControl}/tool-update.lock
      ${pkgs.podman}/bin/podman load --input ${openchamberImage} >/dev/null
      ${pkgs.podman}/bin/podman run --rm \
        --user 3000:3000 \
        --security-opt="unmask=/proc/*" \
        --memory=4g \
        --memory-reservation=2g \
        --pids-limit=512 \
        --network ghostship_net \
        --volume ${openchamberHome}:/home/openchamber:rw \
        --volume ${openchamberToolControl}:/var/lib/openchamber-tool-update:rw \
        --env HOME=/home/openchamber \
        --env USER=openchamber \
        --workdir /home/openchamber \
        --entrypoint ${openchamberToolMaintenance}/bin/openchamber-tool-maintenance \
        ${imageName}:${imageTag}
      candidate_file=${openchamberHome}/.local/state/openchamber-tool-update/candidate.tsv
      [ -f "$candidate_file" ] || return 1
      IFS="$(printf '\t')" read -r candidate _ < "$candidate_file"
      case "$candidate" in
        /home/openchamber/*) ;;
        *) return 1 ;;
      esac
      candidate_relative="$(printf '%s\n' "$candidate" \
        | ${pkgs.gnused}/bin/sed 's#^/home/openchamber/##')"
      host_candidate="$(${pkgs.coreutils}/bin/readlink -f \
        ${openchamberHome}/"$candidate_relative")"
      case "$host_candidate" in
        ${openchamberHome}/.local/share/openchamber-tools/generations/*) ;;
        *) return 1 ;;
      esac
      [ -x "$host_candidate/bin/openchamber" ] \
        && [ -x "$host_candidate/bin/opencode" ]
    }

    if [ -f "$rollback_image_file" ] && [ -f "$rollback_desired_file" ]; then
      rollback_desired="$(cat "$rollback_desired_file")"
      previous_image="$(cat "$rollback_image_file")"
      if rollback_container_healthy || restore_previous_when_safe; then
        if [ "$rollback_desired" = "$desired" ]; then
          mark_failed
          log_info "action=rollback-latched desired=$desired image=$previous_image"
        else
          clear_rollback_state
          clear_rollback_override
          rm -f "$applying_file"
          log_info "action=rollback-complete superseded=$rollback_desired desired=$desired image=$previous_image"
        fi
      else
        log_info "action=rollback-pending desired=$desired image=$previous_image"
      fi
      exit 1
    fi

    if [ "$desired" = "$applied" ]; then
      clear_rollback_override
      rm -f "$applying_file" "$failed_file"
      exit 0
    fi

    if ! ${pkgs.systemd}/bin/systemctl show podman-openchamber.service --property=Environment --value \
      | ${pkgs.gnugrep}/bin/grep -Fq "GHOSTSHIP_OPENCHAMBER_DEPLOYMENT_ID=$desired"; then
      log_info "action=defer desired=$desired reason=unit-not-reloaded"
      exit 0
    fi

    if ! ensure_first_generation; then
      log_info "action=defer desired=$desired reason=first-generation-prestage-failed"
      exit 1
    fi

    [ "$desired" != "$failed" ] || exit 0

    if ${pkgs.systemd}/bin/systemctl is-active --quiet podman-openchamber.service; then
      container_was_active=1
      if ! quiesce_active_container; then
        exit 0
      fi
    fi

    printf '%s\n' "$desired" > "$applying_file.tmp"
    mv "$applying_file.tmp" "$applying_file"
    if ! stop_quiesced_container; then
      exit 1
    fi
    if ! start_replacement_container; then
      if restore_previous_when_safe; then
        mark_failed
      else
        log_info "action=rollback-pending desired=$desired image=$previous_image"
      fi
      exit 1
    fi

    healthy=0
    for _ in $(seq 1 360); do
      if [ "$(${pkgs.podman}/bin/podman inspect openchamber \
        --format '{{.State.Health.Status}}' 2>/dev/null || true)" = "healthy" ] \
        && ${pkgs.podman}/bin/podman exec openchamber \
          systemctl is-active --quiet openchamber-web.service \
        && ${
          if externalOpenCode then
            ''
              ${pkgs.podman}/bin/podman exec openchamber ${pkgs.runtimeShell} -c \
                '${pkgs.systemd}/bin/systemctl is-active --quiet opencode.service \
                  && ${pkgs.curl}/bin/curl -fsS --max-time 5 http://127.0.0.1:4096/global/health \
                    | ${pkgs.jq}/bin/jq -e ".healthy == true" >/dev/null 2>&1'
            ''
          else
            "true"
        } \
        && ${pkgs.podman}/bin/podman exec openchamber \
          curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null 2>&1; then
        healthy=1
        break
      fi
      sleep 10
    done

    running="$(${pkgs.podman}/bin/podman inspect openchamber \
      --format '{{index .Config.Labels "io.ghostship.openchamber.deployment"}}' 2>/dev/null || true)"
    if [ "$healthy" -ne 1 ] || [ "$running" != "$desired" ]; then
      log_info "action=deployment-failed desired=$desired reason=health-timeout"
      if restore_previous_when_safe; then
        mark_failed
      else
        log_info "action=rollback-pending desired=$desired image=$previous_image"
      fi
      exit 1
    fi

    printf '%s\n' "$desired" > "$applied_file.tmp"
    mv "$applied_file.tmp" "$applied_file"
    rm -f "$applying_file" "$failed_file"
    clear_rollback_state
    clear_rollback_override
    log_info "action=deployment-complete desired=$desired"
  '';

in
{
  ghostship.apps.openchamber = {
    name = "OpenChamber";
    group = "Services";
    description = "OpenChamber Web";
    icon = "mdi-code-braces-#111827";
    order = 100;
    hostname = "openchamber.ghostship.io";
    origin = "http://openchamber:3000";
    muximux = {
      icon = "muximux-code";
      color = "#111827";
      dropdown = false;
    };
  };

  virtualisation.oci-containers.containers."openchamber" = {
    image = "${imageName}:${imageTag}";
    imageFile = openchamberImage;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "disabled";
      "io.ghostship.openchamber.deployment" = openchamberDeploymentId;
    };
    ports = [ ];
    extraOptions = [
      "--privileged"
      "--systemd=always"
      "--pids-limit=-1"
      "--stop-timeout=180"
      "--network=ghostship_net"
      "--health-cmd=${openchamberContainerHealth}/bin/openchamber-container-health"
      "--health-interval=30s"
      "--health-timeout=15s"
      "--health-retries=5"
      "--health-start-period=5m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "${openchamberDocker}:/var/lib/docker:rw"
      "${openchamberToolControl}:/var/lib/openchamber-tool-update:rw"
      "${openchamberWorkspace}:/workspace:rw"
      "${openchamberHome}:/home/openchamber:rw"
      "${openchamberNixRoot}/nix:/nix:rw"
      "${openchamberSecrets}:${openchamberSecretsFile}:ro"
      "/mnt/share:/mnt/share:rw"
    ];
    environmentFiles = [ config.ghostship.selfHostedSecrets.projections.openchamber.containerPath ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/openchamber 0755 root root -"
    "d ${openchamberDocker} 0755 root root -"
    "d ${openchamberToolControl} 0755 root root -"
    "d ${openchamberHome} 0755 3000 3000 -"
    "d ${openchamberNixRoot} 0755 root root -"
    "d ${openchamberNixRoot}/nix 0755 root root -"
    "d ${openchamberWorkspace} 0755 3000 3000 -"
  ];

  system.activationScripts.openchamber-deployment = {
    text = ''
      state_dir=${openchamberDeploymentState}
      desired=${lib.escapeShellArg openchamberDeploymentId}
      rollback_image_file="$state_dir/rollback-image"
      rollback_desired_file="$state_dir/rollback-desired"
      rollback_override_dir=/run/systemd/system/podman-openchamber.service.d
      rollback_override="$rollback_override_dir/rollback-image.conf"
      install -d -m 0755 "$state_dir"
      printf '%s\n' "$desired" > "$state_dir/desired.tmp"
      mv "$state_dir/desired.tmp" "$state_dir/desired"

      applied=""
      [ ! -f "$state_dir/applied" ] || applied="$(cat "$state_dir/applied")"
      if [ -f "$rollback_image_file" ] && [ -f "$rollback_desired_file" ]; then
        rollback_image="$(cat "$rollback_image_file")"
        if ${pkgs.podman}/bin/podman image exists "$rollback_image"; then
          ${pkgs.podman}/bin/podman tag "$rollback_image" ${imageName}:${imageTag}
          install -d -m 0755 "$rollback_override_dir"
          {
            printf '%s\n' '[Service]'
            printf '%s\n' 'ExecStartPre='
            printf '%s\n' 'ExecStartPre=-${pkgs.podman}/bin/podman rm -f openchamber'
            printf '%s\n' 'ExecStartPre=${pkgs.coreutils}/bin/rm -f /run/openchamber/ctr-id'
          } > "$rollback_override"
        fi
      elif [ "$applied" = "$desired" ]; then
        rm -f "$rollback_override"
        rmdir "$rollback_override_dir" 2>/dev/null || true
      elif [ -f "$rollback_desired_file" ]; then
        rm -f "$rollback_image_file" "$rollback_desired_file" "$rollback_override"
        rmdir "$rollback_override_dir" 2>/dev/null || true
      fi
    '';
    supportsDryActivation = false;
  };

  systemd.services.openchamber-deploy-when-idle = {
    description = "Deploy a changed OpenChamber image after sustained idle";
    after = [ "podman.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${openchamberDeployWhenIdle}/bin/openchamber-deploy-when-idle";
      TimeoutStartSec = "70m";
    };
  };

  systemd.timers.openchamber-deploy-when-idle = {
    description = "Check for a queued OpenChamber image deployment";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "2m";
      OnUnitActiveSec = "1m";
      Persistent = true;
      Unit = "openchamber-deploy-when-idle.service";
    };
  };

  systemd.services.podman-openchamber = {
    restartIfChanged = false;
    stopIfChanged = false;
    after = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    wants = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    serviceConfig = {
      Environment = lib.mkForce [
        "PODMAN_SYSTEMD_UNIT=%n"
        "GHOSTSHIP_OPENCHAMBER_DEPLOYMENT_ID=${openchamberDeploymentId}"
      ];
      TimeoutStopSec = lib.mkForce "210s";
      SuccessExitStatus = [
        0
        130
      ];
    };
    preStart = lib.mkAfter ''
      set -eu

      install -d -m0755 -o root -g root /srv/apps/openchamber
      install -d -m0755 -o root -g root ${openchamberDocker}
      install -d -m0755 -o root -g root ${openchamberToolControl}
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}
      install -d -m0755 -o root -g root ${openchamberNixRoot}
      install -d -m0755 -o 3000 -g 3000 ${openchamberWorkspace}

      nix_store_uri='local?root=${openchamberNixRoot}'
      ${pkgs.nix}/bin/nix copy \
        --no-check-sigs \
        --to "$nix_store_uri" \
        ${lib.escapeShellArgs (map toString openchamberImageContents)}

      gcroot_dir=${openchamberNixRoot}/nix/var/nix/gcroots/ghostship-openchamber-image
      rm -rf "$gcroot_dir"
      install -d -m0755 -o root -g root "$gcroot_dir"
      for store_path in ${lib.escapeShellArgs (map toString openchamberImageContents)}; do
        ln -s "$store_path" "$gcroot_dir/$(basename "$store_path")"
      done

      rm -f ${openchamberNixRoot}/nix/var/nix/temproots/*
      rm -rf ${openchamberNixRoot}/nix/var/nix/builds/*
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/bin
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/share
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/state
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.cache
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.config/openchamber
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.config/opencode
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.automation
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.config/systemd/user
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.openchamber/hooks/bootstrap.d
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.openchamber/hooks/before-openchamber.d
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.openchamber/hooks/doctor.d

      if [ -e ${openchamberHome}/.config/systemd/user/openchamber.service ] \
        && grep -q 'ExecStart=/home/openchamber/.local/bin/openchamber-web-run' ${openchamberHome}/.config/systemd/user/openchamber.service; then
        rm -f ${openchamberHome}/.config/systemd/user/openchamber.service
      fi
      if [ -e ${openchamberHome}/.config/systemd/user/default.target ] \
        && grep -q 'OpenChamber User Default Target' ${openchamberHome}/.config/systemd/user/default.target; then
        rm -f ${openchamberHome}/.config/systemd/user/default.target
      fi
      rm -f ${openchamberHome}/.config/systemd/user/default.target.wants/openchamber.service
    '';
  };
}
