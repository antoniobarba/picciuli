#!/usr/bin/env bash
# Back up every user database and the Zitadel database. Run as root, e.g. from
# /etc/cron.d/picciuli-backup (installed by bootstrap-vm.sh).
#
#   BACKUP_DIR   where archives are written   (default /var/backups/picciuli)
#   KEEP_DAYS    local retention in days       (default 14)
#   RESTIC_REPOSITORY, RESTIC_PASSWORD, ...    optional off-site copy with restic
set -euo pipefail
cd "$(dirname "$0")"

backup_dir=${BACKUP_DIR:-/var/backups/picciuli}
keep_days=${KEEP_DAYS:-14}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
work="$backup_dir/$stamp"
mkdir -p "$work/users"
chmod 700 "$backup_dir"

# sqlite3 .backup takes a consistent snapshot even while the API is writing.
shopt -s nullglob
for db in data/picciuli/users/*.db; do
    sqlite3 "$db" ".backup '$work/users/$(basename "$db")'"
done

docker compose exec -T postgres pg_dump -U postgres --format=custom zitadel \
    >"$work/zitadel.dump"

tar -C "$backup_dir" -czf "$backup_dir/$stamp.tar.gz" "$stamp"
rm -rf "$work"
find "$backup_dir" -maxdepth 1 -name '*.tar.gz' -mtime +"$keep_days" -delete

if [[ -n ${RESTIC_REPOSITORY:-} ]]; then
    restic backup --tag picciuli "$backup_dir/$stamp.tar.gz"
    restic forget --tag picciuli --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
fi
echo "backup written to $backup_dir/$stamp.tar.gz"
