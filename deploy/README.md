# Deploy: creekwatch.realm.watch

Creek Watch runs as one Docker container on **ubox0**, which is always on. It has no runtime dependency on familiar or katana.

```
phone ─► Cloudflare edge (proxied CNAME, TLS) ─► cloudflared tunnel on ubox0
      ─► Caddy :443 (SNI creekwatch.realm.watch, LE cert via DNS-01, 12 MB body cap)
      ─► 127.0.0.1:8442 ─► container `creekwatch` :8080 (volume `creekwatch-data` at /srv/creekwatch)
```

## Day-to-day

| Do | Command (from any host with `ssh ubox0`) |
|---|---|
| Deploy the latest `main` | nothing: a timer polls `main` every 2 min and redeploys on change |
| Deploy now / a branch or sha | `deploy/redeploy.sh` · `deploy/redeploy.sh <ref>` |
| See what's live | `deploy/redeploy.sh --status` |
| Undo the last deploy | `deploy/redeploy.sh --rollback` |
| Emergency rollback, without waiting for a running backup | `CW_SWAP_LOCK_WAIT=0 deploy/redeploy.sh --rollback` skips the backup-lock wait (up to 300 s) and rolls back at once. An in-flight backup may then fail for that hour (exit 1), and the next hourly run backs up normally. |
| Timer logs | `ssh ubox0 journalctl -u creekwatch-redeploy -n 50` |
| App logs | `ssh ubox0 docker logs --tail 100 creekwatch` |
| Back up now / list backups | `deploy/backup.sh` · `deploy/backup.sh --list` (an hourly timer also runs it) |

`redeploy.sh` does the following:
1. It fetches the ref and builds `creekwatch:<sha>` on ubox0.
2. It boots that image on a **staging port** (8443) against the same volume. If staging fails `/healthz`, it stops there and the live site is untouched.
3. It swaps: the old container is stopped and kept as `creekwatch-prev`, and the new one goes live.
4. It health-checks again, both directly and through Caddy. On failure it rolls back to `creekwatch-prev` automatically.

The container's port and data path come from the image's own `EXPOSE` and `VOLUME`. Whichever path that is, the **same named volume `creekwatch-data`** is mounted there, so an app-side contract change (for example 8080 with /srv/creekwatch → 8000 with /app/var) can't strand deploys or orphan the reports.

The container runs with `--memory 1536m --memory-swap 1536m --pids-limit 256 --security-opt no-new-privileges --cap-drop ALL`, overridable with `CW_MEMORY` and `CW_PIDS`. Idle is about 60 MB; one worst-case image decode measured about 600 MB; and an OOM kills only the container, which then restarts. `git fetch` is bounded (90 s, plus ssh keepalives). A stall once hung the timer for 12 minutes, and a network failure is never recorded as a bad sha.

A sha that fails is written to `~/creekwatch/failed.shas`, and the timer won't retry it. A new merge, or a manual run, will. Measured swap gap: one probe miss at a 0.5 s interval, so about 1 s.

## Backups

`creekwatch-backup.timer` runs **hourly** and copies to **disks** at `/mnt/raid/backups/ubox0/creekwatch/`, which borg snapshots nightly at 03:00:
- `db/creekwatch-<UTC>.db`: a consistent snapshot taken with SQLite's online-backup API inside the container. It needs no downtime, is checked with `integrity_check`, and is kept for 14 days.
- `uploads/`: a mirror of the photos, capped at 5 GB (`CW_BACKUP_MAX_UPLOADS_BYTES`). Above the cap the photo mirror is skipped with a warning, and the DB is still backed up. Everything leaving the container is treated as untrusted. It's streamed out as tar through a hard byte cap (`head -c`: 2 GB for the DB, 5 GB for photos), and host free space is checked first. It's extracted with a filter that keeps only regular files and directories, which drops links and devices and aborts on absolute or `..` paths. The snapshot is converted to `journal_mode=DELETE` inside the container, so it's one self-contained file. The host refuses anything that isn't a rollback-journal SQLite file and opens it read-only with `trusted_schema=OFF`. A photo deleted for moderation is deleted here as well, and borg keeps the history.
- `LATEST`: the stamp and report count of the newest snapshot.

**Restore** (drilled 2026-10-03: the report and its photo came back from disks into a fresh container):
```
ssh ubox0
rsync disks:/mnt/raid/backups/ubox0/creekwatch/db/<snap>.db ~/r/creekwatch.db
rsync -a disks:/mnt/raid/backups/ubox0/creekwatch/uploads/ ~/r/uploads/
docker stop creekwatch
docker run --rm -v creekwatch-data:/to -v ~/r:/from:ro alpine sh -c 'cp -a /from/. /to/ && chown -R 10001 /to'
docker start creekwatch
```

## Files

- `redeploy.sh`: build, stage, swap, verify and roll back. It re-execs itself on ubox0 and forwards `CW_*` overrides.
- `install.sh`: idempotent. It copies `redeploy.sh` to `~/creekwatch/bin/` on ubox0 and installs and enables `creekwatch-redeploy.{service,timer}`. The installed copy is **never** self-updated from `main`: it runs on the host as a docker-group user, so a merge may only change what runs inside the container. Re-run `install.sh` to adopt a changed `redeploy.sh`.
- `Caddyfile.snippet`: the site block in `/etc/caddy/Caddyfile` on ubox0. Besides the proxy it sets two things:
  - Tunnel traffic gets `X-Forwarded-For` from `CF-Connecting-IP`, so per-IP rate limiting sees real phones and not cloudflared. Only requests from cloudflared on localhost are trusted for `CF-Connecting-IP`. Anything that reaches Caddy directly has that header stripped and XFF set to its real peer, so another VLAN can't forge its IP.
  - `Cache-Control` keeps the Cloudflare edge from caching: photos are marked `private`, so deletion is effective, and everything else is `private, no-cache`, so a redeploy reaches phones at once. Without `private`, the zone's Browser Cache TTL rewrote `no-cache` to `max-age=14400` on JS and CSS, and the token can't change zone settings. `web/sw.js` also revalidates with `cache: 'no-cache'`. Every response is `no-transform`, which stops Cloudflare injecting its Web Analytics beacon; the About page promises no trackers.
- `cloudflared-ingress.yml`: the rule in `/etc/cloudflared/config.yml`, placed above the catch-all 404. It shares the tunnel with `list.techempower.org`.
- `backup.sh` plus `creekwatch-backup.{service,timer}`: the hourly off-host backup described above.
- `placeholder/`: the "coming soon" nginx page. It's the rollback target of last resort.

## One-time setup already done (2026-10-03)

- **DNS:** a proxied CNAME `creekwatch.realm.watch` → `<tunnel-id>.cfargotunnel.com` in the realm.watch zone, created with Caddy's DNS token. The LAN has **no** dnsmasq override and resolves to Cloudflare like cellular does. jp-main briefly added one at 17:31, then removed it, because a LAN A record combined with CF's HTTPS/SVCB record (ECH plus ipv4hint) breaks TLS in Chrome. Don't add one.
- **Repo access:** a read-only deploy key on ubox0 (`~/.ssh/creekwatch_deploy`, ssh alias `github-creekwatch`). Once the repo is public this is optional.
- **Monitoring:** `status.realm.watch` checks `/healthz` and `/api/version` (jphein/status.realm.watch#14).
- **Backups** sit next to each edited file on ubox0, as `*.bak-pre-creekwatch-*`.

## Teardown

1. `docker rm -f creekwatch creekwatch-prev`, and `systemctl disable --now creekwatch-redeploy.timer`.
2. Remove the Caddy block and the cloudflared rule.
3. Delete the DNS record.
4. Remove the deploy key.

`docker volume rm creekwatch-data` destroys every report and photo, so export them first.
