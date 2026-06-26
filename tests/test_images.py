import io
import os

import imagehash
import pytest
from PIL import Image, UnidentifiedImageError

from pact.anticheat import phash_hex
from pact.images import (
    make_thumbnail,
    phash_of_bytes,
    save_proof_image,
    strip_exif,
)


def _jpeg_with_exif(
    size: tuple[int, int] = (300, 200),
    color: tuple[int, int, int] = (123, 45, 67),
) -> bytes:
    """A JPEG whose EXIF carries a PII-ish ImageDescription tag (270)."""
    img = Image.new("RGB", size, color)
    exif = img.getexif()
    exif[270] = "secret-gps-and-name"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _png(
    size: tuple[int, int] = (120, 90),
    color: tuple[int, int, int] = (10, 200, 30),
) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_input_image_actually_carries_exif():
    # Guards the test itself: prove the source bytes have the tag we strip.
    src = Image.open(io.BytesIO(_jpeg_with_exif()))
    assert src.getexif().get(270) == "secret-gps-and-name"


def test_strip_exif_drops_metadata_and_preserves_format():
    cleaned = strip_exif(_jpeg_with_exif())
    out = Image.open(io.BytesIO(cleaned))
    assert dict(out.getexif()) == {}
    assert out.format == "JPEG"
    assert out.size == (300, 200)


def test_strip_exif_preserves_png_format():
    cleaned = strip_exif(_png())
    out = Image.open(io.BytesIO(cleaned))
    assert out.format == "PNG"
    assert dict(out.getexif()) == {}


def test_strip_exif_rejects_non_image_bytes():
    with pytest.raises(ValueError):
        strip_exif(b"this is not an image")


def test_make_thumbnail_caps_longest_side_and_strips_exif():
    thumb_bytes = make_thumbnail(_jpeg_with_exif(size=(800, 400)), max_px=256)
    thumb = Image.open(io.BytesIO(thumb_bytes))
    assert max(thumb.size) <= 256
    # Aspect ratio preserved: 800x400 -> 256x128.
    assert thumb.size == (256, 128)
    assert dict(thumb.getexif()) == {}


def test_make_thumbnail_does_not_upscale_small_images():
    small = _png(size=(100, 80))
    thumb = Image.open(io.BytesIO(make_thumbnail(small, max_px=256)))
    assert thumb.size == (100, 80)


def test_make_thumbnail_rejects_non_image_bytes():
    with pytest.raises(ValueError):
        make_thumbnail(b"nope", max_px=256)


def test_save_proof_image_writes_both_files_under_pact_dir(tmp_path):
    data = _jpeg_with_exif()
    image_path, thumb_path = save_proof_image(
        str(tmp_path), "pact_abc123", "proof_def456", data
    )

    assert os.path.exists(image_path)
    assert os.path.exists(thumb_path)
    # Both live under artifacts_dir/<pact_id>/.
    pact_dir = os.path.join(str(tmp_path), "pact_abc123")
    assert os.path.commonpath([pact_dir, image_path]) == pact_dir
    assert os.path.commonpath([pact_dir, thumb_path]) == pact_dir
    assert image_path != thumb_path
    # Stored full image is EXIF-stripped.
    saved = Image.open(image_path)
    assert dict(saved.getexif()) == {}
    # Stored thumb is a real, smaller-or-equal image.
    saved_thumb = Image.open(thumb_path)
    assert max(saved_thumb.size) <= 256


def test_save_proof_image_creates_missing_dirs(tmp_path):
    nested = tmp_path / "does" / "not" / "exist"
    image_path, thumb_path = save_proof_image(
        str(nested), "pact_x", "proof_y", _png()
    )

    assert os.path.exists(image_path)
    assert os.path.exists(thumb_path)


def test_phash_of_bytes_is_deterministic():
    data = _jpeg_with_exif()
    assert phash_of_bytes(data) == phash_of_bytes(data)


def test_phash_of_bytes_matches_anticheat_for_same_content(tmp_path):
    data = _jpeg_with_exif()
    p = tmp_path / "same.jpg"
    p.write_bytes(data)
    assert phash_of_bytes(data) == phash_hex(str(p))


def test_phash_of_bytes_matches_imagehash_directly():
    data = _png()
    expected = str(imagehash.phash(Image.open(io.BytesIO(data))))
    assert phash_of_bytes(data) == expected


def test_phash_of_bytes_rejects_non_image_bytes():
    with pytest.raises(ValueError):
        phash_of_bytes(b"definitely not a png")
