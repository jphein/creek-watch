#!/usr/bin/env bash
# Creek Watch backup: consistent SQLite snapshot + photo mirror, copied OFF ubox0 to disks
# (whose /mnt/raid is borg-snapshotted nightly at 03:00, giving history beyond our own retention).
#
#   deploy/backup.sh            # run from any host; re-execs on ubox0 (timer runs it hourly)
#   deploy/backup.sh --list     # show what's on disks
#
# On disks:  /mnt/raid/backups/ubox0/creekwatch/
#   db/creekwatch-<UTC stamp>.db   hourly snapshots, pruned after ${KEEP_DAYS} days
#   uploads/                        mirror of the photo dir (deleted/moderated photos are removed here too)
#   LATEST                          stamp + report count of the newest snapshot
# Restore: stop the container, copy a snapshot to <datadir>/creekwatch.db and uploads/ into the volume
#          (docker cp), start the container. See deploy/README.md.
set -euo pipefail

DEPLOY_HOST="${CW_DEPLOY_HOST:-ubox0}"
if [ "$(hostname -s)" != "$DEPLOY_HOST" ]; then
  exec ssh "$DEPLOY_HOST" "bash -s -- $(printf '%q ' "$@")" < "${BASH_SOURCE[0]}"
fi

# Everything below runs inside main(): bash parses the whole function before running it, and
# stdin is then detached, so when this script arrives as `ssh host bash -s < script`, an inner
# ssh/docker/git that reads stdin can't swallow the rest of the script.
main() {
exec </dev/null
NAME=creekwatch
VOLUME="${CW_VOLUME:-creekwatch-data}"
DEST_HOST="${CW_BACKUP_HOST:-disks}"
DEST="${CW_BACKUP_DIR:-/mnt/raid/backups/ubox0/creekwatch}"
STAGE="$HOME/creekwatch/backup-stage"
KEEP_DAYS="${CW_BACKUP_KEEP_DAYS:-14}"
log() { printf '%s backup: %s\n' "$(date '+%F %T %Z')" "$*"; }

if [ "${1:-}" = --list ]; then
  exec ssh -n "$DEST_HOST" "cat $DEST/LATEST; ls -1 $DEST/db | tail -5; echo photos: \$(ls $DEST/uploads | wc -l); du -sh $DEST"
fi

# Where the volume is mounted in the running container (follows the app's contract: /srv/creekwatch or /app/var).
DATADIR=$(docker inspect -f "{{range .Mounts}}{{if eq .Name \"$VOLUME\"}}{{.Destination}}{{end}}{{end}}" "$NAME")
[ -n "$DATADIR" ] || { log "FAIL: $NAME has no $VOLUME mount"; exit 1; }

STAMP=$(date -u +%Y%m%dT%H%MZ)
mkdir -p "$STAGE"
rm -rf "${STAGE:?}/uploads" "$STAGE"/snap.db

# 1) Consistent DB copy via SQLite's online backup API, inside the container (WAL-safe, no app downtime).
docker exec -i "$NAME" python - "$DATADIR" <<'PY'
import sqlite3, sys
d = sys.argv[1]
src = sqlite3.connect(f"{d}/creekwatch.db")
dst = sqlite3.connect("/tmp/creekwatch-snap.db")
src.backup(dst); dst.close(); src.close()
PY
docker cp -q "$NAME:/tmp/creekwatch-snap.db" "$STAGE/snap.db"
docker exec "$NAME" rm -f /tmp/creekwatch-snap.db
python3 - "$STAGE/snap.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
assert c.execute("pragma integrity_check").fetchone()[0] == "ok", "integrity_check failed"
PY
COUNT=$(python3 -c "import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute('select count(*) from reports').fetchone()[0])" "$STAGE/snap.db")

# 2) Photos.
docker cp -q "$NAME:$DATADIR/uploads" "$STAGE/uploads"

# 3) Ship off-host.
ssh "$DEST_HOST" "mkdir -p $DEST/db $DEST/uploads"
rsync -a "$STAGE/snap.db" "$DEST_HOST:$DEST/db/creekwatch-$STAMP.db"
rsync -a --delete "$STAGE/uploads/" "$DEST_HOST:$DEST/uploads/"
ssh "$DEST_HOST" "echo '$STAMP reports=$COUNT' > $DEST/LATEST; find $DEST/db -name 'creekwatch-*.db' -mtime +$KEEP_DAYS -delete"
rm -rf "${STAGE:?}/uploads" "$STAGE"/snap.db
log "OK $STAMP reports=$COUNT photos=$(ssh "$DEST_HOST" "ls $DEST/uploads | wc -l") -> $DEST_HOST:$DEST"
}
main "$@"
