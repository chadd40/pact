from __future__ import annotations

import io
import os

import imagehash
from PIL import Image, UnidentifiedImageError

_DEFAULT_FORMAT = "PNG"


def _load(data: bytes) -> Image.Image:
    """Open image bytes, normalizing any decode failure to ValueError.

    Pillow raises UnidentifiedImageError (an OSError subclass) for junk bytes;
    the contract requires ValueError, so we translate here. `.load()` forces the
    decode eagerly so truncated/corrupt payloads fail now, not later.
    """
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(f"not a decodable image: {exc}") from exc


def _reencode(img: Image.Image) -> bytes:
    """Re-encode an image into a fresh same-mode canvas, dropping all metadata.

    Pasting into a new Image() and saving without an exif= kwarg strips EXIF and
    other metadata while preserving the original format (default PNG).
    """
    fmt = img.format or _DEFAULT_FORMAT
    clean = Image.new(img.mode, img.size)
    clean.paste(img)
    out = io.BytesIO()
    clean.save(out, format=fmt)
    return out.getvalue()


def strip_exif(data: bytes) -> bytes:
    """Return EXIF/metadata-free image bytes, preserving the source format.

    Raises ValueError on non-image bytes.
    """
    return _reencode(_load(data))


def make_thumbnail(data: bytes, max_px: int = 256) -> bytes:
    """Return a downscaled, EXIF-stripped copy whose longest side <= max_px.

    Never upscales (Image.thumbnail only shrinks). Raises ValueError on non-image
    bytes.
    """
    img = _load(data)
    fmt = img.format or _DEFAULT_FORMAT
    clean = Image.new(img.mode, img.size)
    clean.paste(img)
    clean.thumbnail((max_px, max_px))
    out = io.BytesIO()
    clean.save(out, format=fmt)
    return out.getvalue()


def save_proof_image(
    artifacts_dir: str, pact_id: str, proof_id: str, data: bytes
) -> tuple[str, str]:
    """Persist an EXIF-stripped full image + a thumbnail under
    artifacts_dir/<pact_id>/, creating directories as needed.

    Returns (image_path, thumb_path). Raises ValueError on non-image bytes.
    """
    clean_full = strip_exif(data)
    thumb = make_thumbnail(data)

    ext = (Image.open(io.BytesIO(clean_full)).format or _DEFAULT_FORMAT).lower()
    if ext == "jpeg":
        ext = "jpg"

    pact_dir = os.path.join(artifacts_dir, pact_id)
    os.makedirs(pact_dir, exist_ok=True)

    image_path = os.path.join(pact_dir, f"{proof_id}.{ext}")
    thumb_path = os.path.join(pact_dir, f"{proof_id}_thumb.{ext}")
    with open(image_path, "wb") as f:
        f.write(clean_full)
    with open(thumb_path, "wb") as f:
        f.write(thumb)
    return image_path, thumb_path


def phash_of_bytes(data: bytes) -> str:
    """Perceptual hash computed directly from image bytes.

    Complements anticheat.phash_hex (which takes a path); identical pixel content
    yields an identical hash. Raises ValueError on non-image bytes.
    """
    return str(imagehash.phash(_load(data)))
