#!/usr/bin/env bash
# Isolated-service proof for the shared Basic Memory workspace (#1676).
#
# Runs the whole A-G evidence plan as one reviewed command. Nothing is deployed:
# every service container is on --network=none with scratch data under $BASE,
# the real /srv/apps/agent-memory volume is refused, and case G creates only the
# approved internal network with two transient probes.
#
# Each case is independent and prints exactly one line:
#
#   CASE <id> PASS|FAIL|UNKNOWN <reason>
#
# A precondition that cannot be established is UNKNOWN, never a product FAIL.
# The final exit code is 0 only when every case passed, 1 when any case failed,
# and 77 when some case is UNKNOWN (the release-window convention).
#
# Dry run prints every command without executing anything:
#
#   modules/self-hosted/agent-memory-evidence.sh --dry-run
#
# The sole host writer runs it as root and pastes the output:
#
#   modules/self-hosted/agent-memory-evidence.sh 2>&1 | tee /var/lib/agent-memory-evidence/run.log
#
# Usage: agent-memory-evidence.sh [--dry-run] [--cases C,D,E] [--repo DIR] [--base DIR] [--image REF]
# A (scratch setup and checkout checks) always runs; --cases selects the evidence cases.

set -uo pipefail

DRY_RUN=0
REPO=""
BASE="/var/lib/agent-memory-evidence"
IMAGE="localhost/agent-memory:evidence"
NETWORK="agent_memory_net"
SUBNET="10.89.23.0/24"
GATEWAY="10.89.23.1"
APP="agent-memory-evidence"
RESTORE="agent-memory-restore"
DNS_CLIENT="t3code-dns"
DNS_SERVER="agent-memory-dns"
PRODUCTION_DIR="/srv/apps/agent-memory"
PRODUCTION_CONTAINER="agent-memory"
PRODUCTION_UNIT="podman-agent-memory.service"

CASES="A B C D E F G"

FAILURES=0
PASSES=0
UNKNOWNS=0
CASE_ID=""

RECOVERY_NOTE="active/recovery.md"
KILL9_NOTE="active/kill9.md"
RECOVERY_BODY=$'---\ntitle: Recovery probe\nstatus: open\n---\n\nacked body\n'
KILL9_BODY=$'---\ntitle: Kill9 probe\nstatus: open\n---\n\nacked before kill\n'

# One MCP session: initialize, initialized, tools/list. Prints "TOOLS <n>".
# The image's python has no third-party dependency here.
HEALTH_PY='import json,urllib.request as u; h={"Content-Type":"application/json","Accept":"application/json, text/event-stream"}; r=u.urlopen(u.Request("http://127.0.0.1:8000/mcp",data=json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"evidence","version":"1"}}}).encode(),headers=h),timeout=5); s=r.headers["mcp-session-id"]; h["mcp-session-id"]=s; u.urlopen(u.Request("http://127.0.0.1:8000/mcp",data=b"{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}",headers=h),timeout=5).read(); r=u.urlopen(u.Request("http://127.0.0.1:8000/mcp",data=b"{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\",\"params\":{}}",headers=h),timeout=5); b=r.read().decode(); j=json.loads(b.split("data: ",1)[1]); print("TOOLS",len(j["result"]["tools"]))'
HEALTH_CMD="python -c '$HEALTH_PY'"

usage() {
  sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) DRY_RUN=1 ;;
      --cases)
        [ $# -ge 2 ] || { printf 'missing value for --cases\n' >&2; exit 2; }
        CASES=$(printf '%s' "$2" | tr ',' ' ')
        shift
        ;;
      --repo)
        [ $# -ge 2 ] || { printf 'missing value for --repo\n' >&2; exit 2; }
        REPO=$2
        shift
        ;;
      --base)
        [ $# -ge 2 ] || { printf 'missing value for --base\n' >&2; exit 2; }
        BASE=$2
        shift
        ;;
      --image)
        [ $# -ge 2 ] || { printf 'missing value for --image\n' >&2; exit 2; }
        IMAGE=$2
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        printf 'unknown argument: %s\n' "$1" >&2
        exit 2
        ;;
    esac
    shift
  done
}

selected() {
  case " $CASES " in
    *" $1 "*) return 0 ;;
  esac
  return 1
}

validate_cases() {
  local item
  for item in $CASES; do
    case "$item" in
      A|B|C|D|E|F|G) ;;
      *) printf 'unknown case in --cases: %s\n' "$item" >&2; exit 2 ;;
    esac
  done
}

resolve_repo() {
  local here
  here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  if [ -z "$REPO" ]; then
    REPO=$(cd "$here/../.." && pwd)
  fi
}

log() {
  printf '%s\n' "$*"
}

refuse() {
  printf 'REFUSED: %s\n' "$*" >&2
  exit 1
}

run() {
  if [ "$DRY_RUN" = 1 ]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

# --- Container and note helpers -------------------------------------------

execute() {
  local container=$1
  shift
  podman exec "$container" "$@"
}

podman_run_service() {
  local name=$1
  shift
  podman run -d --name "$name" --pull=never --network=none \
    --user 3000:3000 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m -e HOME=/tmp \
    -e BASIC_MEMORY_CONFIG_DIR=/data/config \
    -e BASIC_MEMORY_HOME=/data/projects/.main \
    -e BASIC_MEMORY_PROJECT_ROOT=/data/projects \
    -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache \
    -e BASIC_MEMORY_SQLITE_SYNCHRONOUS=FULL \
    -e BASIC_MEMORY_DEFAULT_SEARCH_TYPE=text \
    -v "$1:/data:rw" \
    --health-cmd "$HEALTH_CMD" --health-interval=1s \
    --health-start-period=1s --health-timeout=5s --health-retries=180 \
    "$IMAGE" \
    basic-memory mcp --transport streamable-http --host 127.0.0.1 --port 8000 --path /mcp
}

start_app() {
  podman_run_service "$APP" "$BASE/data"
}

wait_healthy() {
  timeout 300 podman wait --condition=healthy "$1" >/dev/null
}

# Bounded MCP readiness probe: health-cmd is only `basic-memory --version`, so
# the transport can still be starting after the container is healthy.
wait_mcp() {
  local container=$1
  local out=""
  local _i
  for _i in $(seq 1 60); do
    if out=$(podman exec "$container" sh -c "$HEALTH_CMD" 2>&1); then
      printf '%s\n' "$out"
      return 0
    fi
    sleep 1
  done
  printf '%s\n' "$out"
  return 1
}

project_add() {
  podman run --rm --pull=never --network=none --user 3000:3000 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m -e HOME=/tmp \
    -e BASIC_MEMORY_CONFIG_DIR=/data/config \
    -e BASIC_MEMORY_HOME=/data/projects/.main \
    -e BASIC_MEMORY_PROJECT_ROOT=/data/projects \
    -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache \
    -v "$BASE/data:/data:rw" "$IMAGE" \
    basic-memory project add "$1" "/data/projects/$1"
}

bm_write() {
  execute "$APP" basic-memory tool write --project agent-memory \
    --identifier "$1" --content "$2" --json
}

checksum_of() {
  python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("checksum") or "")' "$1"
}

# Host-side SQLite reads and the forced state used by the recovery case. They
# run on the bind mount, so a broken container exec cannot hide the row.
DB_ROW_PY='import sqlite3,sys
connection = sqlite3.connect(sys.argv[1])
row = connection.execute("select file_write_status, db_checksum from note_content where file_path=?", (sys.argv[2],)).fetchone()
print("- -" if row is None else "%s %s" % row)
connection.close()'

DB_FORCE_WRITING_PY='import sqlite3,sys
connection = sqlite3.connect(sys.argv[1])
cursor = connection.execute("update note_content set file_write_status=? where file_path=?", ("writing", sys.argv[2]))
connection.commit()
print(cursor.rowcount)
connection.close()'

db_row() {
  python3 -c "$DB_ROW_PY" "$1" "$2"
}

db_force_writing() {
  python3 -c "$DB_FORCE_WRITING_PY" "$1" "$2"
}

# Wait up to 30 s for an accepted row to reach synced. Prints the last row.
db_wait_synced() {
  local db=$1 note=$2 row=""
  local _i
  for _i in $(seq 1 120); do
    row=$(db_row "$db" "$note")
    case "$row" in
      synced*) printf '%s\n' "$row"; return 0 ;;
    esac
    sleep 0.25
  done
  printf '%s\n' "$row"
  return 1
}

case_start() {
  CASE_ID=$1
  log ""
  log "## case $CASE_ID"
}

case_dry_end() {
  printf 'CASE %s DRY-RUN not executed\n' "$CASE_ID"
}

dry_commands() {
  sed 's/^/+ /'
}

pass_case() {
  printf 'CASE %s PASS %s\n' "$CASE_ID" "$*"
  return 0
}

fail_case() {
  printf 'CASE %s FAIL %s\n' "$CASE_ID" "$*"
  return 1
}

unknown_case() {
  printf 'CASE %s UNKNOWN %s\n' "$CASE_ID" "$*"
  return 77
}

run_case() {
  local fn=$1 rc=0
  "$fn" || rc=$?
  case $rc in
    0) PASSES=$((PASSES + 1)) ;;
    1) FAILURES=$((FAILURES + 1)) ;;
    77) UNKNOWNS=$((UNKNOWNS + 1)) ;;
    *)
      FAILURES=$((FAILURES + 1))
      printf 'CASE %s FAIL unexpected exit %s\n' "$CASE_ID" "$rc"
      ;;
  esac
}

# --- Refusals and preconditions -------------------------------------------

preflight() {
  log "# agent-memory isolated-service proof"
  log "repo=$REPO"
  log "base=$BASE"
  log "image=$IMAGE"
  log "dry_run=$DRY_RUN"

  case "$BASE" in
    ""|"/"|"."|"..") refuse "unsafe --base '$BASE'" ;;
    /srv|/srv/*) refuse "--base must not be inside $PRODUCTION_DIR" ;;
  esac
  case "$(basename "$BASE")" in
    *-evidence|*-evidence-r[0-9]*) ;;
    *) refuse "--base must be a dedicated directory ending in -evidence or -evidence-r<N>" ;;
  esac

  if [ "$DRY_RUN" = 1 ]; then
    log ""
    log "## preflight (dry run)"
    # shellcheck disable=SC2016 # this line is a printed command, not an expansion
    printf '%s\n' '+ test "$(id -u)" -eq 0'
    printf '+ command -v podman git python3\n'
    printf '+ systemctl cat %s\n' "$PRODUCTION_UNIT"
    printf '+ systemctl is-enabled --quiet %s\n' "$PRODUCTION_UNIT"
    printf '+ podman container exists %s\n' "$PRODUCTION_CONTAINER"
    printf '+ test -e %s\n' "$PRODUCTION_DIR"
    printf '+ podman ps -a --format "{{.Names}} {{.Mounts}}" | grep -F %s\n' "$PRODUCTION_DIR"
    printf '+ podman network inspect %s --format "{{range .Containers}}{{.Name}}{{\"\\n\"}}{{end}}"\n' "$NETWORK"
    return 0
  fi

  [ "$(id -u)" -eq 0 ] || refuse "run as root: the proof needs /var/lib, chown and iptables reads"
  for tool in podman git python3; do
    command -v "$tool" >/dev/null 2>&1 || refuse "missing required tool: $tool"
  done

  if systemctl cat "$PRODUCTION_UNIT" >/dev/null 2>&1; then
    refuse "ghostship.agentMemory is enabled ($PRODUCTION_UNIT exists)"
  fi
  if systemctl is-enabled --quiet "$PRODUCTION_UNIT" 2>/dev/null; then
    refuse "ghostship.agentMemory is enabled ($PRODUCTION_UNIT)"
  fi
  if podman container exists "$PRODUCTION_CONTAINER" 2>/dev/null; then
    refuse "the production $PRODUCTION_CONTAINER container exists; this proof is isolated"
  fi
  if [ -e "$PRODUCTION_DIR" ]; then
    refuse "$PRODUCTION_DIR exists; the proof must not touch the production volume"
  fi
  if podman ps -a --format '{{.Names}} {{.Mounts}}' 2>/dev/null | grep -Fq -- "$PRODUCTION_DIR"; then
    refuse "a container mounts $PRODUCTION_DIR"
  fi

  local attached name
  attached=$(podman network inspect "$NETWORK" \
    --format '{{range .Containers}}{{.Name}}{{"\n"}}{{end}}' 2>/dev/null)
  for name in $attached; do
    case "$name" in
      "$APP"|"$RESTORE"|"$DNS_CLIENT"|"$DNS_SERVER") ;;
      *) refuse "network $NETWORK already carries $name; the workspace is attached" ;;
    esac
  done

  if [ -e "$BASE" ] && [ ! -d "$BASE" ]; then
    refuse "$BASE exists and is not a directory"
  fi
}

# --- Case A: checkout, tools, network, scratch ----------------------------

case_a() {
  case_start A
  if [ "$DRY_RUN" = 1 ]; then
    dry_commands <<CMDS
git -C $REPO rev-parse HEAD
git -C $REPO merge-base --is-ancestor 4898056a HEAD
git -C $REPO merge-base --is-ancestor 3cbd63b6 HEAD
git -C $REPO merge-base --is-ancestor 8b9b9eef HEAD
grep -q agent_memory_net $REPO/modules/self-hosted/agent-memory.nix
grep -q 'BASIC_MEMORY_SQLITE_SYNCHRONOUS = "FULL"' $REPO/modules/self-hosted/agent-memory.nix
grep -q AGENT_MEMORY_FILE_UTILS $REPO/modules/self-hosted/agent-memory.Containerfile
grep -q agent-memory-fsync-test.py $REPO/modules/self-hosted/agent-memory.Containerfile
podman info --format '{{.Store.GraphDriverName}}'
iptables -S nixos-fw | grep -F -- '-s $SUBNET -d $GATEWAY'
podman network inspect $NETWORK --format '{{json .}}'
podman rm -f $APP $RESTORE $DNS_CLIENT $DNS_SERVER
rm -rf $BASE
install -d -m0700 -o3000 -g3000 $BASE $BASE/data $BASE/restore
touch $BASE/.agent-memory-evidence
CMDS
    case_dry_end
    return 0
  fi

  local rev
  for rev in 4898056a 3cbd63b6 8b9b9eef; do
    if ! git -C "$REPO" cat-file -e "$rev^{commit}" 2>/dev/null; then
      log "ANCESTRY_UNVERIFIED $rev (object absent from this checkout)"
      continue
    fi
    git -C "$REPO" merge-base --is-ancestor "$rev" HEAD 2>/dev/null ||
      { fail_case "checkout $REPO does not contain required revision $rev"; return 1; }
  done

  grep -q 'agent_memory_net' "$REPO/modules/self-hosted/agent-memory.nix" 2>/dev/null ||
    { fail_case "agent-memory.nix is missing the private network"; return 1; }
  grep -q 'BASIC_MEMORY_SQLITE_SYNCHRONOUS = "FULL"' "$REPO/modules/self-hosted/agent-memory.nix" 2>/dev/null ||
    { fail_case "agent-memory.nix is missing synchronous=FULL"; return 1; }
  grep -q 'AGENT_MEMORY_FILE_UTILS' "$REPO/modules/self-hosted/agent-memory.Containerfile" 2>/dev/null ||
    { fail_case "Containerfile does not apply the durability patch"; return 1; }
  grep -q 'agent-memory-fsync-test.py' "$REPO/modules/self-hosted/agent-memory.Containerfile" 2>/dev/null ||
    { fail_case "Containerfile does not prove the durability patch at build time"; return 1; }

  log "HEAD $(git -C "$REPO" rev-parse HEAD)"
  log "graph driver $(podman info --format '{{.Store.GraphDriverName}}')"
  if iptables -S nixos-fw 2>/dev/null | grep -Fq -- "-s $SUBNET -d $GATEWAY"; then
    log "firewall rule present"
  else
    log "firewall rule absent (case G is UNKNOWN until the module's #737 rule is active)"
  fi
  if podman network inspect "$NETWORK" >/dev/null 2>&1; then
    local internal dns
    internal=$(podman network inspect "$NETWORK" --format '{{.Internal}}')
    dns=$(podman network inspect "$NETWORK" --format '{{.DNSEnabled}}')
    log "network $NETWORK internal=$internal dns=$dns"
    [ "$internal" = "true" ] || { fail_case "existing $NETWORK is not internal"; return 1; }
  else
    log "network $NETWORK absent (case G creates it)"
  fi

  podman rm -f "$APP" "$RESTORE" "$DNS_CLIENT" "$DNS_SERVER" >/dev/null 2>&1 || true
  rm -rf "$BASE"
  install -d -m0700 -o3000 -g3000 "$BASE" "$BASE/data" "$BASE/restore" ||
    { fail_case "could not create $BASE"; return 1; }
  : >"$BASE/.agent-memory-evidence"
  pass_case "checkout, containerfile, network and scratch are ready"
}

# --- Case B: image build --------------------------------------------------

case_b() {
  case_start B
  if [ "$DRY_RUN" = 1 ]; then
    dry_commands <<CMDS
podman build --no-cache -f $REPO/modules/self-hosted/agent-memory.Containerfile -t $IMAGE $REPO/modules/self-hosted
podman image inspect --format 'IMAGE_ID={{.Id}} SIZE_BYTES={{.Size}}' $IMAGE
podman build -f $REPO/modules/self-hosted/agent-memory.Containerfile -t $IMAGE $REPO/modules/self-hosted
podman run --rm --pull=never --network=none $IMAGE python -c 'import sys; print(sys.version)'
podman run --rm --pull=never --network=none $IMAGE sh -c 'ls -A /opt/agent-memory/fastembed_cache'
CMDS
    case_dry_end
    return 0
  fi

  local start clean_seconds cached_seconds size model
  start=$(date +%s)
  podman build --no-cache -f "$REPO/modules/self-hosted/agent-memory.Containerfile" \
    -t "$IMAGE" "$REPO/modules/self-hosted" ||
    { fail_case "clean image build failed"; return 1; }
  clean_seconds=$(($(date +%s) - start))
  log "CLEAN_BUILD_S=$clean_seconds"

  size=$(podman image inspect --format '{{.Id}} {{.Size}}' "$IMAGE") ||
    { fail_case "image missing after the clean build"; return 1; }
  log "IMAGE_ID_SIZE=$size"
  case "$size" in
    *" 0") fail_case "image size is zero"; return 1 ;;
  esac

  start=$(date +%s)
  podman build -f "$REPO/modules/self-hosted/agent-memory.Containerfile" \
    -t "$IMAGE" "$REPO/modules/self-hosted" ||
    { fail_case "cached image build failed"; return 1; }
  cached_seconds=$(($(date +%s) - start))
  log "CACHED_BUILD_S=$cached_seconds"

  podman run --rm --pull=never --network=none "$IMAGE" python -c 'import sys; print(sys.version)' ||
    { fail_case "image has no usable python"; return 1; }
  model=$(podman run --rm --pull=never --network=none "$IMAGE" \
    sh -c 'ls -A /opt/agent-memory/fastembed_cache') ||
    { fail_case "pre-baked embedding model directory is missing"; return 1; }
  [ -n "$model" ] || { fail_case "pre-baked embedding model directory is empty"; return 1; }
  log "MODEL_ENTRIES=$(printf '%s\n' "$model" | wc -l)"
  pass_case "clean ${clean_seconds}s cached ${cached_seconds}s and the model cache are present"
}

# --- Case C: cold start and restart to MCP ready ---------------------------

case_c() {
  case_start C
  if [ "$DRY_RUN" = 1 ]; then
    dry_commands <<CMDS
podman run --rm --pull=never --network=none --user 3000:3000 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m -e HOME=/tmp -e BASIC_MEMORY_CONFIG_DIR=/data/config -e BASIC_MEMORY_HOME=/data/projects/.main -e BASIC_MEMORY_PROJECT_ROOT=/data/projects -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache -v $BASE/data:/data:rw $IMAGE basic-memory project add agent-memory /data/projects/agent-memory
podman run --rm --pull=never --network=none --user 3000:3000 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m -e HOME=/tmp -e BASIC_MEMORY_CONFIG_DIR=/data/config -e BASIC_MEMORY_HOME=/data/projects/.main -e BASIC_MEMORY_PROJECT_ROOT=/data/projects -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache -v $BASE/data:/data:rw $IMAGE basic-memory project add agent-memory-test /data/projects/agent-memory-test
podman run -d --name $APP --pull=never --network=none --user 3000:3000 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m -e HOME=/tmp -e BASIC_MEMORY_CONFIG_DIR=/data/config -e BASIC_MEMORY_HOME=/data/projects/.main -e BASIC_MEMORY_PROJECT_ROOT=/data/projects -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache -e BASIC_MEMORY_SQLITE_SYNCHRONOUS=FULL -e BASIC_MEMORY_DEFAULT_SEARCH_TYPE=text -v $BASE/data:/data:rw --health-cmd "$HEALTH_CMD" --health-interval=1s --health-start-period=1s --health-timeout=5s --health-retries=180 $IMAGE basic-memory mcp --transport streamable-http --host 127.0.0.1 --port 8000 --path /mcp
podman wait --condition=healthy $APP
podman exec $APP sh -c "$HEALTH_CMD"
podman stop -t 30 $APP
podman start $APP
podman wait --condition=healthy $APP
podman exec $APP sh -c "$HEALTH_CMD"
CMDS
    case_dry_end
    return 0
  fi

  project_add agent-memory || { fail_case "project add agent-memory failed"; return 1; }
  project_add agent-memory-test || { fail_case "project add agent-memory-test failed"; return 1; }

  local start cold restart out
  start=$(date +%s)
  start_app >/dev/null || { fail_case "cold start failed"; return 1; }
  if ! wait_healthy "$APP"; then
    local state
    state=$(podman inspect --format '{{.State.Status}}' "$APP" 2>/dev/null)
    if [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
      fail_case "container exited before becoming healthy ($state)"
      return 1
    fi
    unknown_case "container did not become healthy on cold start"
    return 77
  fi
  out=$(wait_mcp "$APP") || {
    case "$out" in
      *"Transport endpoint is not connected"*) unknown_case "runtime exec failure on the cold-start probe"; return 77 ;;
      *) fail_case "MCP did not answer within 60s on cold start: ${out:0:200}"; return 1 ;;
    esac
  }
  cold=$(($(date +%s) - start))
  log "COLD_START_READY_S=$cold"
  log "$out"
  [ "$out" = "TOOLS 12" ] || { fail_case "cold start exposed '$out', not 12 tools"; return 1; }

  start=$(date +%s)
  podman stop -t 30 "$APP" >/dev/null || { unknown_case "clean stop failed"; return 77; }
  podman start "$APP" >/dev/null || { unknown_case "restart failed"; return 77; }
  wait_healthy "$APP" || { unknown_case "container did not become healthy after restart"; return 77; }
  out=$(wait_mcp "$APP") || {
    case "$out" in
      *"Transport endpoint is not connected"*) unknown_case "runtime exec failure on the restart probe"; return 77 ;;
      *) fail_case "MCP did not answer within 60s after restart: ${out:0:200}"; return 1 ;;
    esac
  }
  restart=$(($(date +%s) - start))
  log "RESTART_READY_S=$restart"
  log "$out"
  [ "$out" = "TOOLS 12" ] || { fail_case "restart exposed '$out', not 12 tools"; return 1; }

  pass_case "cold ${cold}s restart ${restart}s with 12 tools"
}

# --- Case D: recovery from a forced stuck materialization ------------------

case_recovery() {
  case_start D
  if [ "$DRY_RUN" = 1 ]; then
    dry_commands <<CMDS
podman run --rm --pull=never --network=none --user 3000:3000 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m -e HOME=/tmp -e BASIC_MEMORY_CONFIG_DIR=/data/config -e BASIC_MEMORY_HOME=/data/projects/.main -e BASIC_MEMORY_PROJECT_ROOT=/data/projects -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache -v $BASE/data:/data:rw $IMAGE basic-memory project add agent-memory /data/projects/agent-memory
podman run --rm --pull=never --network=none --user 3000:3000 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m -e HOME=/tmp -e BASIC_MEMORY_CONFIG_DIR=/data/config -e BASIC_MEMORY_HOME=/data/projects/.main -e BASIC_MEMORY_PROJECT_ROOT=/data/projects -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache -v $BASE/data:/data:rw $IMAGE basic-memory project add agent-memory-test /data/projects/agent-memory-test
podman run -d --name $APP --pull=never --network=none --user 3000:3000 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m -e HOME=/tmp -e BASIC_MEMORY_CONFIG_DIR=/data/config -e BASIC_MEMORY_HOME=/data/projects/.main -e BASIC_MEMORY_PROJECT_ROOT=/data/projects -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache -e BASIC_MEMORY_SQLITE_SYNCHRONOUS=FULL -e BASIC_MEMORY_DEFAULT_SEARCH_TYPE=text -v $BASE/data:/data:rw --health-cmd "$HEALTH_CMD" --health-interval=1s --health-start-period=1s --health-timeout=5s --health-retries=180 $IMAGE basic-memory mcp --transport streamable-http --host 127.0.0.1 --port 8000 --path /mcp
podman start $APP
podman wait --condition=healthy $APP
podman exec $APP basic-memory tool write --project agent-memory --identifier $RECOVERY_NOTE --content "$RECOVERY_BODY" --json
python3 -c "$DB_ROW_PY" $BASE/data/config/memory.db $RECOVERY_NOTE   # poll 120 x 0.25s until synced
podman stop -t 30 $APP
python3 -c "$DB_FORCE_WRITING_PY" $BASE/data/config/memory.db $RECOVERY_NOTE
rm -f $BASE/data/projects/agent-memory/$RECOVERY_NOTE
podman start $APP
podman wait --condition=healthy $APP
test -f $BASE/data/projects/agent-memory/$RECOVERY_NOTE
python3 -c "$DB_ROW_PY" $BASE/data/config/memory.db $RECOVERY_NOTE
CMDS
    case_dry_end
    return 0
  fi

  # A targeted --cases D,F run has no case C; create the same prerequisites.
  if ! podman container exists "$APP" 2>/dev/null; then
    project_add agent-memory || { fail_case "project add agent-memory failed"; return 1; }
    project_add agent-memory-test || { fail_case "project add agent-memory-test failed"; return 1; }
    start_app >/dev/null || { fail_case "could not start the evidence container"; return 1; }
  fi
  podman start "$APP" >/dev/null 2>&1 || true
  wait_healthy "$APP" || { unknown_case "container is not healthy before recovery"; return 77; }

  bm_write "$RECOVERY_NOTE" "$RECOVERY_BODY" >"$BASE/recovery-write.json" 2>"$BASE/recovery-write.err" ||
    { unknown_case "the acknowledged write did not return: $(head -c 200 "$BASE/recovery-write.err")"; return 77; }
  local expected
  expected=$(checksum_of "$BASE/recovery-write.json") || expected=""
  [ -n "$expected" ] || { unknown_case "the write returned no checksum"; return 77; }
  [ -f "$BASE/data/config/memory.db" ] ||
    { unknown_case "the workspace database was not created"; return 77; }

  # Corrected precondition: observe the accepted row before forcing the state.
  # The last run set no row because note_content was still empty.
  local row=""
  row=$(db_wait_synced "$BASE/data/config/memory.db" "$RECOVERY_NOTE") || {
    unknown_case "no synced note_content row within 30s: $row"
    return 77
  }
  log "RECOVERY_ROW $row"

  # Stop before forcing the state, so the materializer cannot race the test.
  podman stop -t 30 "$APP" >/dev/null || { unknown_case "clean stop failed"; return 77; }
  local rows
  rows=$(db_force_writing "$BASE/data/config/memory.db" "$RECOVERY_NOTE" 2>"$BASE/recovery-db.err") ||
    { unknown_case "host SQLite update failed: $(head -c 200 "$BASE/recovery-db.err")"; return 77; }
  log "UPDATE_ROWS $rows"
  [ "$rows" = "1" ] || { unknown_case "UPDATE_ROWS=$rows, the precondition was not established"; return 77; }

  # Prove the forced state exists while nothing can observe the file removal.
  row=$(db_row "$BASE/data/config/memory.db" "$RECOVERY_NOTE")
  log "FORCED_ROW $row"
  [ "${row%% *}" = "writing" ] ||
    { unknown_case "forced row is '${row%% *}', not writing; the precondition was not established"; return 77; }

  rm -f "$BASE/data/projects/agent-memory/$RECOVERY_NOTE"
  [ ! -f "$BASE/data/projects/agent-memory/$RECOVERY_NOTE" ] ||
    { unknown_case "the file could not be removed while the container was stopped"; return 77; }
  podman start "$APP" >/dev/null || { unknown_case "restart failed"; return 77; }
  wait_healthy "$APP" || { unknown_case "container did not become healthy after recovery restart"; return 77; }

  row=$(db_wait_synced "$BASE/data/config/memory.db" "$RECOVERY_NOTE") || {
    if [ "$row" = "- -" ]; then
      fail_case "the note was deleted rather than recovered: no note_content row after restart"
    else
      fail_case "the forced writing row did not return to synced within 30s: $row"
    fi
    return 1
  }
  [ -f "$BASE/data/projects/agent-memory/$RECOVERY_NOTE" ] ||
    { fail_case "file absent after a healthy restart with the precondition held"; return 1; }
  log "DB_STATUS $row"
  [ "${row##* }" = "$expected" ] ||
    { fail_case "recovered checksum ${row##* } does not match the acknowledged $expected"; return 1; }

  pass_case "acked write recovered after a forced writing row, checksum $expected"
}

# --- Case E: acknowledged write survives kill -9 ---------------------------

case_kill9() {
  case_start E
  if [ "$DRY_RUN" = 1 ]; then
    dry_commands <<CMDS
podman start $APP
podman wait --condition=healthy $APP
podman exec $APP basic-memory tool write --project agent-memory --identifier $KILL9_NOTE --content "$KILL9_BODY" --json
podman kill -9 $APP
podman start $APP
podman wait --condition=healthy $APP
python3 -c "$DB_ROW_PY" $BASE/data/config/memory.db $KILL9_NOTE   # poll 120 x 0.25s until synced
CMDS
    case_dry_end
    return 0
  fi

  podman start "$APP" >/dev/null 2>&1 || true
  wait_healthy "$APP" || { unknown_case "container is not healthy before kill -9"; return 77; }

  bm_write "$KILL9_NOTE" "$KILL9_BODY" >"$BASE/kill9-write.json" 2>"$BASE/kill9-write.err" ||
    { unknown_case "the acknowledged write did not return: $(head -c 200 "$BASE/kill9-write.err")"; return 77; }
  local expected
  expected=$(checksum_of "$BASE/kill9-write.json") || expected=""
  [ -n "$expected" ] || { unknown_case "the write returned no checksum"; return 77; }

  podman kill -9 "$APP" >/dev/null || { unknown_case "kill -9 failed"; return 77; }
  podman start "$APP" >/dev/null || { unknown_case "restart after kill -9 failed"; return 77; }
  wait_healthy "$APP" || { unknown_case "container did not become healthy after kill -9"; return 77; }

  local row
  row=$(db_wait_synced "$BASE/data/config/memory.db" "$KILL9_NOTE") ||
    { fail_case "the accepted note did not return to synced after kill -9: $row"; return 1; }
  log "DB_STATUS $row"
  [ "${row##* }" = "$expected" ] ||
    { fail_case "accepted checksum $expected did not survive kill -9 (db ${row##* })"; return 1; }

  pass_case "accepted checksum $expected survived kill -9"
}

# --- Case F: backup / restore --------------------------------------------

case_restore() {
  case_start F
  if [ "$DRY_RUN" = 1 ]; then
    dry_commands <<CMDS
python3 -c "$DB_ROW_PY" $BASE/data/config/memory.db $RECOVERY_NOTE
python3 -c "$DB_ROW_PY" $BASE/data/config/memory.db $KILL9_NOTE
podman stop -t 30 $APP
tar -C $BASE/data -cf $BASE/snapshot.tar .
rm -rf $BASE/restore
install -d -m0700 -o3000 -g3000 $BASE/restore
tar -C $BASE/restore -xf $BASE/snapshot.tar
podman run -d --name $RESTORE --pull=never --network=none --user 3000:3000 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m -e HOME=/tmp -e BASIC_MEMORY_CONFIG_DIR=/data/config -e BASIC_MEMORY_HOME=/data/projects/.main -e BASIC_MEMORY_PROJECT_ROOT=/data/projects -e FASTEMBED_CACHE_PATH=/opt/agent-memory/fastembed_cache -e BASIC_MEMORY_SQLITE_SYNCHRONOUS=FULL -e BASIC_MEMORY_DEFAULT_SEARCH_TYPE=text -v $BASE/restore:/data:rw --health-cmd "$HEALTH_CMD" --health-interval=1s --health-start-period=1s --health-timeout=5s --health-retries=180 $IMAGE basic-memory mcp --transport streamable-http --host 127.0.0.1 --port 8000 --path /mcp
podman wait --condition=healthy $RESTORE
podman exec $RESTORE sh -c "$HEALTH_CMD"
test -f $BASE/restore/projects/agent-memory/$RECOVERY_NOTE
python3 -c "$DB_ROW_PY" $BASE/restore/config/memory.db $RECOVERY_NOTE
CMDS
    case_dry_end
    return 0
  fi

  podman start "$APP" >/dev/null 2>&1 || true
  wait_healthy "$APP" || { unknown_case "container is not healthy before the backup"; return 77; }

  local note row notes="" db="$BASE/data/config/memory.db"
  local -A before=()
  for note in "$RECOVERY_NOTE" "$KILL9_NOTE"; do
    row=$(db_row "$db" "$note")
    [ "$row" != "- -" ] || continue
    [ "${row%% *}" = "synced" ] ||
      { unknown_case "note $note is ${row%% *}, not synced before the backup"; return 77; }
    [ -f "$BASE/data/projects/agent-memory/$note" ] ||
      { unknown_case "note $note has no materialized file before the backup"; return 77; }
    notes="$notes $note"
    before["$note"]=${row##* }
    log "BEFORE $note $row"
  done
  if [ -z "$notes" ]; then
    unknown_case "no acknowledged note to restore"
    return 77
  fi

  podman stop -t 30 "$APP" >/dev/null || { unknown_case "clean stop failed"; return 77; }
  rm -f "$BASE/snapshot.tar"
  tar -C "$BASE/data" -cf "$BASE/snapshot.tar" . ||
    { unknown_case "snapshot failed"; return 77; }
  rm -rf "$BASE/restore"
  install -d -m0700 -o3000 -g3000 "$BASE/restore" || { unknown_case "restore directory failed"; return 77; }
  tar -C "$BASE/restore" -xf "$BASE/snapshot.tar" ||
    { unknown_case "extract failed"; return 77; }

  podman_run_service "$RESTORE" "$BASE/restore" >/dev/null ||
    { unknown_case "the restored instance did not start"; return 77; }
  wait_healthy "$RESTORE" || { unknown_case "the restored instance did not become healthy"; return 77; }

  local out
  out=$(wait_mcp "$RESTORE") || {
    case "$out" in
      *"Transport endpoint is not connected"*) unknown_case "runtime exec failure on the restored probe"; return 77 ;;
      *) fail_case "restored MCP did not answer within 60s: ${out:0:200}"; return 1 ;;
    esac
  }
  log "RESTORED $out"
  [ "$out" = "TOOLS 12" ] || { fail_case "restored instance exposed '$out', not 12 tools"; return 1; }

  for note in $notes; do
    [ -f "$BASE/restore/projects/agent-memory/$note" ] ||
      { fail_case "restored file missing: $note"; return 1; }
    row=$(db_row "$BASE/restore/config/memory.db" "$note")
    log "AFTER $note $row"
    [ "${row%% *}" = "synced" ] || { fail_case "restored $note is ${row%% *}, not synced"; return 1; }
    [ "${row##* }" = "${before[$note]}" ] ||
      { fail_case "restored $note checksum ${row##* } does not match ${before[$note]}"; return 1; }
  done

  pass_case "restored instance is healthy with matching acknowledged notes"
}

# --- Case G: case 9, internal DNS on the approved private network ----------

case_dns() {
  case_start G
  if [ "$DRY_RUN" = 1 ]; then
    dry_commands <<CMDS
iptables -S nixos-fw | grep -F -- '-s $SUBNET -d $GATEWAY'
podman network inspect $NETWORK >/dev/null 2>&1 || podman network create --internal --subnet $SUBNET --gateway $GATEWAY $NETWORK
podman network inspect $NETWORK
podman run -d --name $DNS_CLIENT --pull=never --network=$NETWORK --user 3000:3000 --read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m $IMAGE sleep infinity
podman run -d --name $DNS_SERVER --pull=never --network=$NETWORK --user 3000:3000 --read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m $IMAGE sleep infinity
podman exec $DNS_CLIENT cat /etc/resolv.conf
podman exec $DNS_SERVER cat /etc/resolv.conf
podman exec $DNS_CLIENT python -c 'import socket; print("RESOLVE_NAME", socket.gethostbyname("$DNS_SERVER"))'
podman exec $DNS_SERVER python -c 'import socket; print("RESOLVE_NAME", socket.gethostbyname("$DNS_CLIENT"))'
timeout 5 podman exec $DNS_CLIENT python -c 'import socket; socket.gethostbyname("example.com")'
timeout 5 podman exec $DNS_SERVER python -c 'import socket; socket.gethostbyname("example.com")'
podman rm -f $DNS_CLIENT $DNS_SERVER
CMDS
    case_dry_end
    return 0
  fi

  podman network inspect "$NETWORK" >/dev/null 2>&1 ||
    podman network create --internal --subnet "$SUBNET" --gateway "$GATEWAY" "$NETWORK" >/dev/null ||
    { fail_case "could not create $NETWORK"; return 1; }

  local net_state internal dns servers
  net_state=$(podman network inspect "$NETWORK" |
    python3 -c 'import json,sys; d=json.load(sys.stdin)[0]; print(str(d.get("internal")).lower(), str(d.get("dns_enabled")).lower(), json.dumps(d.get("network_dns_servers") or []))') ||
    { unknown_case "could not inspect $NETWORK"; return 77; }
  read -r internal dns servers <<<"$net_state"
  log "INTERNAL $internal DNS_ENABLED $dns DNS_SERVERS $servers"
  if [ "$internal" != "true" ] || [ "$dns" != "true" ]; then
    fail_case "$NETWORK must be internal with DNS enabled"
    return 1
  fi
  case "$servers" in
    ""|"[]") ;;
    *) fail_case "$NETWORK carries explicit DNS servers: $servers"; return 1 ;;
  esac
  local subnets
  subnets=$(podman network inspect "$NETWORK" --format '{{range .Subnets}}{{.Subnet}} {{end}}')
  log "SUBNETS $subnets"
  case " $subnets " in
    *" $SUBNET "*) ;;
    *) fail_case "$NETWORK does not carry the approved subnet $SUBNET"; return 1 ;;
  esac

  podman rm -f "$DNS_CLIENT" "$DNS_SERVER" >/dev/null 2>&1 || true
  local name
  for name in "$DNS_CLIENT" "$DNS_SERVER"; do
    podman run -d --name "$name" --pull=never --network="$NETWORK" \
      --user 3000:3000 --read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=8m \
      "$IMAGE" sleep infinity >/dev/null || { fail_case "could not start $name"; return 1; }
  done

  podman exec "$DNS_CLIENT" cat /etc/resolv.conf
  podman exec "$DNS_SERVER" cat /etc/resolv.conf

  local client_resolves=1 server_resolves=1 public_resolves=0
  podman exec "$DNS_CLIENT" python -c "import socket; print('RESOLVE_NAME', socket.gethostbyname('$DNS_SERVER'))" ||
    client_resolves=0
  podman exec "$DNS_SERVER" python -c "import socket; print('RESOLVE_NAME', socket.gethostbyname('$DNS_CLIENT'))" ||
    server_resolves=0
  if timeout 5 podman exec "$DNS_CLIENT" python -c 'import socket; socket.gethostbyname("example.com")'; then
    public_resolves=1
  else
    log "PUBLIC_BLOCKED client"
  fi
  if timeout 5 podman exec "$DNS_SERVER" python -c 'import socket; socket.gethostbyname("example.com")'; then
    public_resolves=1
  else
    log "PUBLIC_BLOCKED server"
  fi

  podman rm -f "$DNS_CLIENT" "$DNS_SERVER" >/dev/null 2>&1 || true

  if [ "$public_resolves" = 1 ]; then
    fail_case "a public name resolved from the internal network; remove the egress before deploying"
    return 1
  fi
  if ! iptables -S nixos-fw 2>/dev/null | grep -Fq -- "-s $SUBNET -d $GATEWAY"; then
    unknown_case "firewall rule #737 is not active (the module is disabled); public no-egress passed"
    return 77
  fi
  if [ "$client_resolves" = 0 ] || [ "$server_resolves" = 0 ]; then
    unknown_case "with the rule present, peer name resolution still failed; capture resolv.conf and the aardvark-dns journal"
    return 77
  fi
  pass_case "internal names resolve and public names are blocked in one run"
}

cleanup() {
  [ "$DRY_RUN" = 1 ] && return 0
  podman rm -f "$APP" "$RESTORE" "$DNS_CLIENT" "$DNS_SERVER" >/dev/null 2>&1 || true
  log "containers removed; $BASE kept for the report"
}

main() {
  parse_args "$@"
  validate_cases
  resolve_repo
  preflight
  run_case case_a
  selected B && run_case case_b
  selected C && run_case case_c
  selected D && run_case case_recovery
  selected E && run_case case_kill9
  selected F && run_case case_restore
  selected G && run_case case_dns
  cleanup

  log ""
  if [ "$DRY_RUN" = 1 ]; then
    log "SUMMARY dry-run cases=$((PASSES + FAILURES + UNKNOWNS))"
    return 0
  fi
  log "SUMMARY pass=$PASSES fail=$FAILURES unknown=$UNKNOWNS"
  if [ "$FAILURES" -gt 0 ]; then
    return 1
  fi
  if [ "$UNKNOWNS" -gt 0 ]; then
    return 77
  fi
  return 0
}

main "$@"
