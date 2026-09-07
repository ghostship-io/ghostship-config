# Run only through ghostship-backup so the repository and maintenance lock are set.
set -euo pipefail
umask 077
scratch=$(mktemp -d /var/lib/ghostship-backup/restore-check.XXXXXX)
container=ghostship-restore-$(basename "$scratch" | tr '[:upper:].' '[:lower:]-')
cleanup_restore() {
    status=$?
    trap - EXIT
    podman rm -f --volumes "$container" >/dev/null 2>&1 || true
    # Keep failed restores for inspection; successful probes contain no durable state.
    if [ "$status" -eq 0 ]; then
        rm -rf -- "$scratch"
    else
        echo "Restore failed; isolated files retained in $scratch" >&2
    fi
    exit "$status"
}
trap cleanup_restore EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

restic restore latest --host chill-penguin --tag ghostship --target "$scratch" \
    --include /var/lib/ghostship-backup/exports \
    --include /var/lib/ghostship-backup/snapshot/apps/ntfy \
    --include /var/lib/ghostship-backup/snapshot/apps/uptime-kuma \
    --include /var/lib/ghostship-backup/snapshot/apps/seerr \
    --include /var/lib/ghostship-backup/snapshot/srv/apps/ntfy \
    --include /var/lib/ghostship-backup/snapshot/srv/apps/uptime-kuma \
    --include /var/lib/ghostship-backup/snapshot/srv/apps/seerr

# Work only on restored SQLite files. Opening read/write allows WAL recovery.
python - "$scratch" <<'PY'
import pathlib
import sqlite3
import sys

root = pathlib.Path(sys.argv[1])
for path in root.rglob('*'):
    if not path.is_file() or path.is_symlink():
        continue
    with path.open('rb') as handle:
        header = handle.read(16)
    if header != b'SQLite format 3\x00':
        continue
    with sqlite3.connect(str(path)) as database:
        result = database.execute('PRAGMA integrity_check').fetchall()
        if result != [('ok',)]:
            raise RuntimeError(f'SQLite integrity check failed: {path.name}')
    print(f'SQLite restore verified: {path.name}')
PY

# Import each logical dump into its own disposable engine. No network, live
# volumes, production credentials, or production container names are used.
image=docker.io/library/mariadb@sha256:2439dcd7d14010ecd1ff7a4e1c5abe8e208c34fe35290744deeeaac3569043c3
for database in romm grimmory; do
    dump=$scratch/var/lib/ghostship-backup/exports/$database.sql
    test -s "$dump"
    data_dir=$scratch/mariadb-$database
    mkdir -m0700 "$data_dir"
    # First boot must initialize grants normally. Passing skip-grant-tables to
    # an empty datadir prevents the entrypoint's CREATE/ALTER USER statements.
    for mode in initialize import; do
        args=(--skip-networking)
        if [ "$mode" = import ]; then args+=(--skip-grant-tables); fi
        podman run -d --name "$container" --network none \
            -v "$data_dir:/var/lib/mysql" \
            -e MARIADB_ALLOW_EMPTY_ROOT_PASSWORD=1 "$image" "${args[@]}" >/dev/null
        ready=false
        for _ in $(seq 1 90); do
            if podman exec "$container" sh -c 'test "$(cat /proc/1/comm)" = mariadbd' 2>/dev/null && \
                podman exec "$container" mariadb-admin ping --silent >/dev/null 2>&1; then
                ready=true
                break
            fi
            sleep 2
        done
        "$ready" || { echo "Disposable database $mode did not become ready" >&2; exit 1; }
        if [ "$mode" = initialize ]; then
            podman stop --time 30 "$container" >/dev/null
            podman rm --volumes "$container" >/dev/null
        fi
    done
    podman exec -i "$container" mariadb --user=root < "$dump"
    podman exec "$container" mariadb-check --user=root --all-databases --check >/dev/null
    podman rm -f --volumes "$container" >/dev/null
    echo "MariaDB restore verified: $database"
done
date +%s > /var/lib/ghostship-backup/last-restore-success
