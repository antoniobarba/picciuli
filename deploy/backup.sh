#!/usr/bin/env bash
# Back up every user database and the Zitadel database. Run as root, e.g. from
# picciuli-backup.timer (installed by bootstrap-vm.sh).
#
#   ./backup.sh           write a new archive
#   ./backup.sh --check   exit 1 with a warning if the newest archive is missing
#                         or older than MAX_AGE_HOURS
#
#   BACKUP_DIR     where archives are written   (default /var/backups/picciuli)
#   KEEP_DAYS      local retention in days       (default 14)
#   MAX_AGE_HOURS  staleness limit of --check    (default 26)
#   RESTIC_REPOSITORY, RESTIC_PASSWORD, ...      optional off-site copy with restic
set -euo pipefail
cd "$(dirname "$0")"
# Archives contain every book and the Zitadel dump: readable by root only.
umask 077

backup_dir=${BACKUP_DIR:-/var/backups/picciuli}
keep_days=${KEEP_DAYS:-14}

if [[ ${1:-} == --check ]]; then
    max_age=${MAX_AGE_HOURS:-26}
    latest=$(find "$backup_dir" -maxdepth 1 -name '*.tar.gz' -printf '%T@ %p\n' 2>/dev/null |
        sort -n | tail -n 1 | cut -d' ' -f2-)
    if [[ -z $latest ]]; then
        echo "WARNING: no backup archive in $backup_dir" >&2
        exit 1
    fi
    age_hours=$((($(date +%s) - $(stat -c %Y "$latest")) / 3600))
    if ((age_hours >= max_age)); then
        echo "WARNING: latest backup $latest is ${age_hours}h old (limit ${max_age}h)" >&2
        exit 1
    fi
    echo "latest backup $latest is ${age_hours}h old"
    exit 0
fi

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
