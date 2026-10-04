# Creek Watch: one process serving /api/*, /uploads/* and the static PWA (web/) at /.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
# git: only to install realm-sigil from GitHub at build time.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY . .

ARG GIT_SHA=""
ARG GIT_BRANCH=""
ARG BUILT=""
ENV CREEKWATCH_GIT_SHA=$GIT_SHA \
    CREEKWATCH_GIT_BRANCH=$GIT_BRANCH \
    CREEKWATCH_BUILT=$BUILT \
    CREEKWATCH_DATA_DIR=/srv/creekwatch \
    PYTHONPATH=/app/backend:/app \
    PYTHONUNBUFFERED=1

# DB at /srv/creekwatch/creekwatch.db, photos at /srv/creekwatch/uploads/. Must match deploy/redeploy.sh
# (CW_APP_PORT, CW_VAR): the live volume creekwatch-data is mounted there. Guarded by test_deploy_contract.py.
RUN useradd --system --uid 10001 creekwatch && mkdir -p /srv/creekwatch/uploads && chown -R creekwatch /srv/creekwatch
USER creekwatch
VOLUME /srv/creekwatch
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2).status==200 else 1)"
# Client IP comes from CF-Connecting-IP / X-Forwarded-For only when the peer is in CREEKWATCH_TRUSTED_PROXIES
# (see main.make_client_ip), so uvicorn's own --proxy-headers is off.
CMD ["uvicorn", "creekwatch.asgi:app", "--host", "0.0.0.0", "--port", "8080", "--no-proxy-headers"]
