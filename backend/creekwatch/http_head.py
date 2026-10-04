"""HEAD for every GET route (RFC 9110 §9.3.2: a server SHOULD answer HEAD as it would GET, minus the body).

FastAPI's @app.get routes don't accept HEAD, so `HEAD /healthz` fell through to the "/" StaticFiles mount
and returned 404, which uptime bots and link checkers read as "down". This runs a HEAD as a GET and drops
the body; the status and headers (Content-Length included) are the GET's. Pure ASGI, so streamed and file
responses work too. Only HEAD is rewritten; a route that refuses GET (POST-only) still refuses HEAD.
"""

from __future__ import annotations


class HeadAsGetMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "HEAD":
            return await self.app(scope, receive, send)

        done = False

        async def send_no_body(message):
            nonlocal done
            if message["type"] == "http.response.body":
                if done or message.get("more_body", False):
                    return
                done = True
                message = {"type": "http.response.body", "body": b"", "more_body": False}
            await send(message)

        await self.app({**scope, "method": "GET"}, receive, send_no_body)
