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
# Everything docker cp hands us is container-controlled: a compromised app could plant symlinks so host-side
# tools (sqlite, rsync with a trailing slash) follow them into ubox0's own files. Accept only plain files/dirs.
[ -f "$STAGE/snap.db" ] && [ ! -L "$STAGE/snap.db" ] || { log "FAIL: snapshot is not a regular file"; exit 1; }
# The snapshot is container-controlled too: open it read-only with trusted_schema=OFF so a planted
# trigger/view can't call functions from host-side sqlite.
COUNT=$(python3 - "$STAGE/snap.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
c.execute("pragma trusted_schema=OFF")
assert c.execute("pragma integrity_check").fetchone()[0] == "ok", "integrity_check failed"
print(c.execute("select count(*) from reports").fetchone()[0])
PY
)

# 2) Photos. Size-capped: a flood of uploads must not fill ubox0's disk (staging) or disks' RAID.
MAX_UP="${CW_BACKUP_MAX_UPLOADS_BYTES:-5000000000}"
claimed=$(docker exec "$NAME" du -sb "$DATADIR/uploads" | cut -f1)
case "$claimed" in ''|*[!0-9]*) log "FAIL: can't size uploads"; exit 1 ;; esac
if [ "$claimed" -gt "$MAX_UP" ]; then
  log "WARN: uploads are $claimed bytes (> cap $MAX_UP): photo mirror SKIPPED this run, DB still backed up"
  SKIP_UPLOADS=1
else
  SKIP_UPLOADS=0
  docker cp -q "$NAME:$DATADIR/uploads" "$STAGE/uploads"
fi
if [ "$SKIP_UPLOADS" = 0 ]; then
  [ -d "$STAGE/uploads" ] && [ ! -L "$STAGE/uploads" ] || { log "FAIL: uploads is not a plain directory"; exit 1; }
  # du inside the container is container-reported; re-measure what actually landed on the host.
  actual=$(du -sb "$STAGE/uploads" | cut -f1)
  [ "$actual" -le "$MAX_UP" ] || { log "FAIL: staged uploads $actual bytes exceed cap $MAX_UP"; rm -rf "${STAGE:?}/uploads"; exit 1; }
  links=$(find "$STAGE/uploads" ! -type f ! -type d | wc -l)
  [ "$links" = 0 ] || log "WARN: skipping $links non-regular entries (symlinks/devices) in uploads"
fi

# 3) Ship off-host.
ssh "$DEST_HOST" "mkdir -p $DEST/db $DEST/uploads"
rsync -a --no-links --no-devices --no-specials "$STAGE/snap.db" "$DEST_HOST:$DEST/db/creekwatch-$STAMP.db"
[ "$SKIP_UPLOADS" = 1 ] || rsync -a --no-links --no-devices --no-specials --delete "$STAGE/uploads/" "$DEST_HOST:$DEST/uploads/"
ssh "$DEST_HOST" "echo '$STAMP reports=$COUNT' > $DEST/LATEST; find $DEST/db -name 'creekwatch-*.db' -mtime +$KEEP_DAYS -delete"
rm -rf "${STAGE:?}/uploads" "$STAGE"/snap.db
log "OK $STAMP reports=$COUNT photos=$(ssh "$DEST_HOST" "ls $DEST/uploads | wc -l") -> $DEST_HOST:$DEST"
}
main "$@"
