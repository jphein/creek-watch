"""Photo storage behind one interface: local disk (default; homelab) or Cloudflare R2 (S3 API).

The Cloudflare build serves /uploads/* straight from the R2 binding in the Worker, so the container
only ever WRITES photos there. Credentials come from env only (never repr'd or logged)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

log = logging.getLogger("creekwatch.uploads")


class UploadError(RuntimeError):
    pass


class UploadStore(Protocol):
    def put(self, name: str, data: bytes) -> None: ...


class LocalUploads:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def put(self, name: str, data: bytes) -> None:
        (self.directory / name).write_bytes(data)


class R2Uploads:
    """Writes to R2 via its S3-compatible API (and keeps a local copy as a cache)."""

    def __init__(self, bucket: str, endpoint: str, key_id: str, secret: str, cache_dir: Path, client=None):
        self.bucket, self.cache = bucket, LocalUploads(cache_dir)
        if client is None:
            import boto3  # optional dependency: the `cf` extra
            from botocore.config import Config

            client = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=key_id,
                                  aws_secret_access_key=secret, region_name="auto",
                                  config=Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 3}))
        self.client = client

    def __repr__(self) -> str:
        return f"R2Uploads(bucket={self.bucket!r})"

    def put(self, name: str, data: bytes) -> None:
        try:
            self.client.put_object(Bucket=self.bucket, Key=f"uploads/{name}", Body=data,
                                   ContentType="image/jpeg", CacheControl="public, max-age=31536000, immutable")
        except Exception as e:  # never echo credentials; the class name is enough
            log.error("R2 photo upload failed: %s", type(e).__name__)
            raise UploadError("photo storage unavailable") from e
        self.cache.put(name, data)


def make_upload_store(s) -> UploadStore:
    if s.uploads_backend == "r2":
        missing = [k for k in ("r2_endpoint", "r2_bucket", "r2_access_key_id", "r2_secret_access_key") if not getattr(s, k)]
        if missing:
            raise RuntimeError(f"CREEKWATCH_UPLOADS_BACKEND=r2 but missing: {', '.join(missing)}")
        return R2Uploads(s.r2_bucket, s.r2_endpoint, s.r2_access_key_id, s.r2_secret_access_key, s.uploads_dir)
    return LocalUploads(s.uploads_dir)
