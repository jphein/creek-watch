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
| Timer logs | `ssh ubox0 journalctl -u creekwatch-redeploy -n 50` |
| App logs | `ssh ubox0 docker logs --tail 100 creekwatch` |

`redeploy.sh` does the following:
1. It fetches the ref and builds `creekwatch:<sha>` on ubox0.
2. It boots that image on a **staging port** (8443) against the same volume. If staging fails `/healthz`, it stops there and the live site is untouched.
3. It swaps: the old container is stopped and kept as `creekwatch-prev`, and the new one goes live.
4. It health-checks again, both directly and through Caddy. On failure it rolls back to `creekwatch-prev` automatically.

A sha that fails is written to `~/creekwatch/failed.shas`, and the timer won't retry it. A new merge, or a manual run, will. Measured swap gap: one probe miss at a 0.5 s interval, so about 1 s.

## Files

- `redeploy.sh`: build, stage, swap, verify and roll back. It re-execs itself on ubox0 and forwards `CW_*` overrides.
- `install.sh`: idempotent. It copies `redeploy.sh` to `~/creekwatch/bin/` on ubox0 and installs and enables `creekwatch-redeploy.{service,timer}`. After each successful deploy, the installed copy self-updates from `main`.
- `Caddyfile.snippet`: the site block in `/etc/caddy/Caddyfile` on ubox0. Besides the proxy it sets two things:
  - `X-Forwarded-For` comes from `CF-Connecting-IP`, so per-IP rate limiting sees real phones and not cloudflared.
  - `Cache-Control` keeps the Cloudflare edge from caching: photos are marked `private`, so deletion is effective, and everything else is `no-cache`, so a redeploy reaches phones at once.
- `cloudflared-ingress.yml`: the rule in `/etc/cloudflared/config.yml`, placed above the catch-all 404. It shares the tunnel with `list.techempower.org`.
- `placeholder/`: the "coming soon" nginx page. It's the rollback target of last resort.

## One-time setup already done (2026-10-03)

- **DNS:** a proxied CNAME `creekwatch.realm.watch` → `<tunnel-id>.cfargotunnel.com` in the realm.watch zone, created with Caddy's DNS token. There's deliberately no LAN dnsmasq override, so LAN clients take the same path as phones.
- **Repo access:** a read-only deploy key on ubox0 (`~/.ssh/creekwatch_deploy`, ssh alias `github-creekwatch`). Once the repo is public this is optional.
- **Monitoring:** `status.realm.watch` checks `/healthz` and `/api/version` (jphein/status.realm.watch#14).
- **Backups** sit next to each edited file on ubox0, as `*.bak-pre-creekwatch-*`.

## Teardown

1. `docker rm -f creekwatch creekwatch-prev`, and `systemctl disable --now creekwatch-redeploy.timer`.
2. Remove the Caddy block and the cloudflared rule.
3. Delete the DNS record.
4. Remove the deploy key.

`docker volume rm creekwatch-data` destroys every report and photo, so export them first.
