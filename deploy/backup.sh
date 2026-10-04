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
rm -rf "${STAGE:?}/uploads" "$STAGE"/snap.db "$STAGE"/snap.db-wal "$STAGE"/snap.db-shm "$STAGE"/*.tar

MAX_DB="${CW_BACKUP_MAX_DB_BYTES:-2000000000}"
MAX_UP="${CW_BACKUP_MAX_UPLOADS_BYTES:-5000000000}"
rm -f "$STAGE"/snap.db-wal "$STAGE"/snap.db-shm "$STAGE"/*.tar

# Everything that comes out of the container is container-controlled (a compromised app could lie
# about sizes, plant symlinks, or craft the DB). So: stream out as tar through a hard byte cap, check
# host free space first, extract only regular files/dirs, and open the DB read-only with
# trusted_schema=OFF.
need=$(( MAX_DB + MAX_UP + 1000000000 ))
free=$(df -B1 --output=avail "$STAGE" | tail -1 | tr -d ' ')
[ "$free" -gt "$need" ] || { log "FAIL: only $free bytes free on ubox0 for staging (need > $need)"; exit 1; }

# capped_cp <container path> <tar out> <cap>: docker cp streamed through head -c; returns 3 if capped.
capped_cp() {
  docker cp "$NAME:$1" - | head -c "$(( $3 + 1 ))" > "$2" || true
  [ "$(stat -c %s "$2")" -le "$3" ] || { rm -f "$2"; return 3; }
}
# safe_extract <tar> <dest dir>: regular files and directories only; nothing absolute, nothing via "..".
safe_extract() {
  python3 - "$1" "$2" <<'PY'
import sys, tarfile
def only_plain(m, path):
    if not (m.isreg() or m.isdir()):
        print(f"skipping non-regular member {m.name!r}", file=sys.stderr)   # links, devices, fifos
        return None
    return tarfile.data_filter(m, path)   # rejects absolute paths and "..": raises, which aborts the run
with tarfile.open(sys.argv[1]) as t:
    t.extractall(sys.argv[2], filter=only_plain)
PY
}

# 1) Consistent DB copy via SQLite's online backup API, inside the container (WAL-safe, no app downtime),
#    switched to rollback journal so the copy is one self-contained file (no -wal/-shm on the host).
docker exec -i "$NAME" python - "$DATADIR" <<'PY'
import sqlite3, sys
d = sys.argv[1]
src = sqlite3.connect(f"{d}/creekwatch.db")
dst = sqlite3.connect("/tmp/creekwatch-snap.db")
src.backup(dst)
dst.execute("PRAGMA journal_mode=DELETE")
dst.close(); src.close()
PY
capped_cp /tmp/creekwatch-snap.db "$STAGE/snap.tar" "$MAX_DB" || { docker exec "$NAME" rm -f /tmp/creekwatch-snap.db; log "FAIL: DB snapshot exceeds cap $MAX_DB"; exit 1; }
docker exec "$NAME" rm -f /tmp/creekwatch-snap.db
mkdir -p "$STAGE/db.x"
safe_extract "$STAGE/snap.tar" "$STAGE/db.x" || { log "FAIL: unsafe or unreadable DB archive"; exit 1; }
rm -f "$STAGE/snap.tar"
[ -f "$STAGE/db.x/creekwatch-snap.db" ] || { log "FAIL: snapshot missing or not a regular file"; exit 1; }
mv "$STAGE/db.x/creekwatch-snap.db" "$STAGE/snap.db"; rm -rf "${STAGE:?}/db.x"
# Header bytes 18/19 are 1/1 for a rollback-journal DB (2/2 = WAL): anything else, refuse to open.
[ "$(od -An -tu1 -j18 -N2 "$STAGE/snap.db" | tr -s ' ')" = " 1 1" ] || { log "FAIL: snapshot is not a rollback-journal SQLite file"; exit 1; }
COUNT=$(python3 - "$STAGE/snap.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
c.execute("pragma trusted_schema=OFF")
assert c.execute("pragma integrity_check").fetchone()[0] == "ok", "integrity_check failed"
print(c.execute("select count(*) from reports").fetchone()[0])
PY
)
rm -f "$STAGE"/snap.db-wal "$STAGE"/snap.db-shm

# 2) Photos, through the same hard cap. Over the cap -> skip the mirror this run (DB still saved).
SKIP_UPLOADS=0
if capped_cp "$DATADIR/uploads" "$STAGE/uploads.tar" "$MAX_UP"; then
  mkdir -p "$STAGE/up.x"
  safe_extract "$STAGE/uploads.tar" "$STAGE/up.x" || { rm -rf "${STAGE:?}/up.x"; log "FAIL: unsafe or unreadable uploads archive"; exit 1; }
  rm -f "$STAGE/uploads.tar"
  [ -d "$STAGE/up.x/uploads" ] || { log "FAIL: uploads missing from the container archive"; exit 1; }
  mv "$STAGE/up.x/uploads" "$STAGE/uploads"; rm -rf "${STAGE:?}/up.x"
else
  log "WARN: uploads exceed cap $MAX_UP bytes: photo mirror SKIPPED this run, DB still backed up"
  SKIP_UPLOADS=1
fi

# 3) Ship off-host.
ssh "$DEST_HOST" "mkdir -p $DEST/db $DEST/uploads"
rsync -a --no-links --no-devices --no-specials "$STAGE/snap.db" "$DEST_HOST:$DEST/db/creekwatch-$STAMP.db"
[ "$SKIP_UPLOADS" = 1 ] || rsync -a --no-links --no-devices --no-specials --delete "$STAGE/uploads/" "$DEST_HOST:$DEST/uploads/"
ssh "$DEST_HOST" "echo '$STAMP reports=$COUNT' > $DEST/LATEST; find $DEST/db -name 'creekwatch-*.db' -mtime +$KEEP_DAYS -delete"
rm -rf "${STAGE:?}/uploads" "$STAGE"/snap.db "$STAGE"/snap.db-wal "$STAGE"/snap.db-shm "$STAGE"/*.tar
log "OK $STAMP reports=$COUNT photos=$(ssh "$DEST_HOST" "ls $DEST/uploads | wc -l") -> $DEST_HOST:$DEST"
}
main "$@"
