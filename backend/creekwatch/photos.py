"""Photo hygiene: decode, auto-rotate, strip ALL metadata (EXIF/GPS/XMP/ICC), downscale, re-encode JPEG."""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

try:  # HEIC/HEIF from iPhones. Optional: if the wheel is missing we reject HEIC clearly.
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIC_SUPPORTED = True
except Exception:  # pragma: no cover - depends on platform wheels
    HEIC_SUPPORTED = False

# Decompression-bomb guard: ~60 MP is bigger than any phone camera.
Image.MAX_IMAGE_PIXELS = 60_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "MPO"} | ({"HEIF", "HEIC"} if HEIC_SUPPORTED else set())


class PhotoError(ValueError):
    pass


def process_photo(raw: bytes, max_px: int = 1600, quality: int = 85) -> bytes:
    """Return clean JPEG bytes, or raise PhotoError with a user-facing message."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(raw))
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                if fmt in {"HEIF", "HEIC"}:
                    raise PhotoError("HEIC photos aren't supported on this server; please send a JPEG or PNG.")
                raise PhotoError("Photo must be a JPEG, PNG or HEIC image.")
            img.load()
    except PhotoError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError) as e:
        raise PhotoError(f"Couldn't read that photo ({type(e).__name__}).") from e

    # Apply the camera's orientation tag BEFORE we drop it, or phone photos come out sideways.
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        img = bg
    img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)

    # Rebuild from raw pixels: the new image has an empty .info, so no EXIF/GPS/XMP/ICC can ride along.
    clean = Image.frombytes(img.mode, img.size, img.tobytes())
    out = io.BytesIO()
    clean.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()
