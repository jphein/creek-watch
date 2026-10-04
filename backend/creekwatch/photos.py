"""Photo hygiene: decode, auto-rotate, strip ALL metadata (EXIF/GPS/XMP/ICC), downscale, re-encode JPEG."""

from __future__ import annotations

import io
import threading
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

try:  # HEIC/HEIF from iPhones. Optional: if the wheel is missing we reject HEIC clearly.
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIC_SUPPORTED = True
except Exception:  # pragma: no cover - depends on platform wheels
    HEIC_SUPPORTED = False

# Pixel cap. Default phone photos are 12 MP (iPhone, incl. 48 MP sensors) or 12-50 MP
# (Android). A 40 MP RGB decode measured ~160 MB extra RSS; a 59.9 MP RGBA PNG measured
# ~520 MB, which is why the old 60 MP cap was too loose. Opt-in "48 MP HEIF Max" (iPhone
# Pro, 8064x6048 = 48.8 MP) and 108/200 MP Android modes are rejected with a clear message.
# ProRAW is DNG, which is never accepted.
MAX_PIXELS = 40_000_000
# Pillow's own bomb check (in Image.open) stays as a backstop at 2x, so our header-size check
# below is what normally rejects, with a message that says how big the photo was.
Image.MAX_IMAGE_PIXELS = 2 * MAX_PIXELS
# At most this many photos are decoded at once, process-wide, so concurrent uploads can't
# multiply RSS. The API gates and queues uploads in the event loop (main.py) and runs the
# decode on its own 2-thread limiter; this threading semaphore is the inner backstop for any
# other caller. MAX_QUEUE bounds how many uploads may wait (each holds up to 10 MB of raw bytes).
DECODE_SLOTS = 2
MAX_QUEUE = 8
DECODE_WAIT_S = 30.0
_decode_slots = threading.BoundedSemaphore(DECODE_SLOTS)
ALLOWED_FORMATS = {"JPEG", "PNG", "MPO"} | ({"HEIF", "HEIC"} if HEIC_SUPPORTED else set())


class PhotoError(ValueError):
    pass


class PhotoBusy(PhotoError):
    """All decode slots are taken; the client should retry later (HTTP 503)."""


def _too_big(w: int, h: int) -> PhotoError:
    return PhotoError(f"That photo is {w * h / 1e6:.1f} megapixels; the limit is {MAX_PIXELS // 1_000_000}. "
                      "Use your phone's normal photo size (12 MP) or send a screenshot of it.")


def process_photo(raw: bytes, max_px: int = 1600, quality: int = 85) -> bytes:
    """Return clean JPEG bytes, or raise PhotoError with a user-facing message.

    At most DECODE_SLOTS decodes run at once; a request waits up to DECODE_WAIT_S for a slot.
    """
    if not _decode_slots.acquire(timeout=DECODE_WAIT_S):
        raise PhotoBusy("The server is busy processing other photos; please try again in a minute.")
    try:
        return _process_photo(raw, max_px, quality)
    finally:
        _decode_slots.release()


def _process_photo(raw: bytes, max_px: int, quality: int) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(raw))
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                if fmt in {"HEIF", "HEIC"}:
                    raise PhotoError("HEIC photos aren't supported on this server; please send a JPEG or PNG.")
                raise PhotoError("Photo must be a JPEG, PNG or HEIC image.")
            w, h = img.size  # header only: nothing decoded yet
            if w * h > MAX_PIXELS:
                raise _too_big(w, h)
            img.load()
    except PhotoError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        raise PhotoError(f"That photo is too large; the limit is {MAX_PIXELS // 1_000_000} megapixels.") from e
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise PhotoError(f"Couldn't read that photo ({type(e).__name__}).") from e

    # Apply the camera's orientation tag BEFORE we drop it, or phone photos come out sideways.
    img = ImageOps.exif_transpose(img)
    # Shrink BEFORE flattening transparency: flattening a full-size RGBA image made several
    # full-size copies (~520 MB at 60 MP). Palette/other modes go to RGBA first so the resize
    # filters properly; RGB and L are shrunk as they are.
    if img.mode not in ("RGB", "L", "RGBA"):
        img = img.convert("RGBA")
    img.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))
        img = bg

    # Rebuild from raw pixels: the new image has an empty .info, so no EXIF/GPS/XMP/ICC can ride along.
    clean = Image.frombytes(img.mode, img.size, img.tobytes())
    out = io.BytesIO()
    clean.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()
