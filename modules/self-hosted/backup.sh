set -euo pipefail
umask 077
exec 9>/run/ghostship-maintenance.lock
flock -w 300 9
findmnt -rn -t nfs,nfs4 --mountpoint /mnt/share >/dev/null || {
    echo 'Backup refused: NAS is not mounted' >&2
    exit 1
}
export RESTIC_REPOSITORY=/mnt/share/Backups/ghostship/chill-penguin
export RESTIC_CACHE_DIR=/var/cache/ghostship-backup
# The runtime projection is shell quoted; never log its contents.
set -a
. /run/ghostship-secrets/backup.env
set +a
: "${RESTIC_PASSWORD:?Missing backup password}"

case "${1:-backup}" in
    check) exec restic check ;;
    sample) exec restic check --read-data-subset=10% ;;
    prune) exec restic prune ;;
    restore-check) source @restoreCheck@; exit ;;
    backup) ;;
    *) echo 'Usage: ghostship-backup [backup|check|sample|prune|restore-check]' >&2; exit 2 ;;
esac

state=/var/lib/ghostship-backup
snapshot=$state/snapshot
install -d -m0700 "$state/exports" "$state/recovery" \
    /var/lib/ghostship-cloudflare /var/lib/ghostship-dashboards
# The live host has a dedicated /srv subvolume; a fresh declared layout may
# keep /srv in @. Snapshot the containing root only in that verified case.
if btrfs subvolume show /srv >/dev/null 2>&1; then
    snapshot_source=/srv
    app_snapshot=$snapshot/apps
elif [ "$(findmnt -nr -o TARGET --target /srv)" = / ] && btrfs subvolume show / >/dev/null 2>&1; then
    snapshot_source=/
    app_snapshot=$snapshot/srv/apps
else
    echo 'Backup refused: /srv is not on a supported Btrfs subvolume layout' >&2
    exit 1
fi
quiesced=()
declare -A health_intervals health_actions
resume_writer() {
    local app=$1
    if [ "$(podman inspect "$app" --format '{{.State.Paused}}')" = true ]; then
        podman unpause "$app" || return 1
    fi
    podman update --health-interval="${health_intervals[$app]}ns" \
        --health-on-failure="${health_actions[$app]}" "$app" >/dev/null
}
cleanup() {
    status=$?
    trap - EXIT
    for app in "${quiesced[@]}"; do
        resume_writer "$app" || status=1
    done
    if btrfs subvolume show "$snapshot" >/dev/null 2>&1; then
        btrfs subvolume delete "$snapshot" || status=1
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# Record the generation and exact image IDs before quiescing anything.
podman ps --no-trunc --format '{{.Names}} {{.Image}} {{.ImageID}}' > "$state/recovery/containers.txt"
readlink /run/current-system > "$state/recovery/system-generation.txt"
podman images --no-trunc --format '{{.ID}} {{.Repository}}:{{.Tag}} {{.Digest}}' > "$state/recovery/images.txt"

# Pause and resume the same containers: restarting a pull=always unit could
# upgrade the writer before this backup succeeds. Disable health recovery
# during the bounded pause so the frozen process cannot be killed by its probe.
for app in romm grimmory; do
    if [ "$(podman inspect "$app" --format '{{.State.Running}}')" = true ]; then
        if [ "$(podman inspect "$app" --format '{{.State.Paused}}')" = true ]; then
            echo "Backup refused: $app is already paused" >&2
            exit 1
        fi
        health_intervals[$app]=$(podman inspect "$app" --format '{{json .Config.Healthcheck.Interval}}')
        health_actions[$app]=$(podman inspect "$app" --format '{{.Config.HealthcheckOnFailureAction}}')
        quiesced+=("$app")
        podman update --health-on-failure=none --health-interval=disable "$app" >/dev/null
        podman pause "$app" >/dev/null
    fi
done
# SQLite applications recover their atomically captured DB + WAL together.
timeout 120 podman exec romm-db mariadb-dump --user=root --single-transaction --routines --events --all-databases > "$state/exports/romm.sql"
# Expand the database password inside its container, never in the host shell.
# shellcheck disable=SC2016
timeout 120 podman exec grimmory-db sh -c 'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mariadb-dump --user=root --single-transaction --routines --events --all-databases' > "$state/exports/grimmory.sql"
test -s "$state/exports/romm.sql"
test -s "$state/exports/grimmory.sql"
if btrfs subvolume show "$snapshot" >/dev/null 2>&1; then
    btrfs subvolume delete "$snapshot"
fi
btrfs subvolume snapshot -r "$snapshot_source" "$snapshot"
for app in "${quiesced[@]}"; do resume_writer "$app"; done
quiesced=()

if [ ! -e "$RESTIC_REPOSITORY/config" ]; then
    restic init
fi
restic backup --host chill-penguin --tag ghostship \
    --exclude "$app_snapshot/codex" \
    --exclude "$app_snapshot/chatgpt/docker" \
    --exclude "$app_snapshot/chatgpt/nix-root" \
    --exclude "$app_snapshot/romm-db" \
    --exclude "$app_snapshot/grimmory-db" \
    --exclude "$app_snapshot/openchamber/docker" \
    --exclude "$app_snapshot/openchamber/nix-root" \
    --exclude '**/node_modules' --exclude '**/.cache' \
    "$app_snapshot" "$state/exports" "$state/recovery" /etc/ssh /boot/asahi \
    /var/lib/ghostship-cloudflare /var/lib/ghostship-dashboards
restic forget --host chill-penguin --tag ghostship --keep-daily 7 --keep-weekly 5 --keep-monthly 12
date +%s > "$state/last-success.new"
mv "$state/last-success.new" "$state/last-success"
