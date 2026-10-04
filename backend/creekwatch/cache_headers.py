"""Cache-Control set by the app, for hosts with no header-setting proxy in front (AWS: kamal-proxy can't add
headers). It mirrors the homelab Caddy policy (deploy/Caddyfile.snippet) exactly:

- /uploads/*      private, max-age=86400, no-transform   (photos: browser-cached, never at a shared edge)
- everything else private, no-cache, no-transform        (revalidate, so a redeploy never pins a stale app.js)

A response that already carries Cache-Control (e.g. the alert feeds' "public, max-age=120") keeps its own.
Pure ASGI (not BaseHTTPMiddleware), so streamed and file responses pass through untouched.

Off by default (CREEKWATCH_CACHE_CONTROL=1 turns it on): behind homelab Caddy, `header` without `defer`
does not replace an upstream header but adds a second one, so turning it on there would duplicate
the header on every response.
"""

from __future__ import annotations

UPLOADS = b"private, max-age=86400, no-transform"
DEFAULT = b"private, no-cache, no-transform"


class CacheControlMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        value = UPLOADS if scope["path"].startswith("/uploads/") else DEFAULT

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(k.lower() == b"cache-control" for k, _ in headers):
                    headers.append((b"cache-control", value))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
