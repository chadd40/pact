from PIL import Image

from pact.anticheat import find_duplicate, phash_hex


def _make_image(path, color, size=(64, 64)):
    img = Image.new("RGB", size, color)
    img.save(path)
    return str(path)


def _make_checker(path, size=(64, 64)):
    """Create a checkerboard pattern (8x8 tiles) — produces a distinct perceptual hash."""
    img = Image.new("RGB", size)
    for x in range(size[0]):
        for y in range(size[1]):
            color = (255, 255, 255) if (x // 8 + y // 8) % 2 == 0 else (0, 0, 0)
            img.putpixel((x, y), color)
    img.save(path)
    return str(path)


def _make_hstripes(path, size=(64, 64)):
    """Create horizontal stripes pattern — perceptually distinct from checkerboard."""
    img = Image.new("RGB", size)
    for y in range(size[1]):
        color = (255, 255, 255) if (y // 8) % 2 == 0 else (0, 0, 0)
        for x in range(size[0]):
            img.putpixel((x, y), color)
    img.save(path)
    return str(path)


def test_phash_hex_returns_stable_hex_string(tmp_path):
    p = _make_image(tmp_path / "a.png", (10, 120, 200))
    h1 = phash_hex(p)
    h2 = phash_hex(p)
    assert isinstance(h1, str)
    assert h1 == h2
    # hex string: only hexadecimal characters
    assert all(c in "0123456789abcdef" for c in h1)


def test_identical_image_is_duplicate_distance_zero(tmp_path):
    a = _make_image(tmp_path / "a.png", (200, 30, 30))
    b = _make_image(tmp_path / "b.png", (200, 30, 30))
    ha = phash_hex(a)
    hb = phash_hex(b)
    assert ha == hb
    assert find_duplicate(hb, [ha]) == 0


def test_clearly_different_images_are_not_duplicates(tmp_path):
    # A checkerboard vs horizontal stripes produce very different perceptual hashes
    # (Hamming distance ~20, well above the default threshold of 6).
    checker = _make_checker(tmp_path / "checker.png")
    stripes = _make_hstripes(tmp_path / "stripes.png")

    h_checker = phash_hex(checker)
    h_stripes = phash_hex(stripes)
    assert h_checker != h_stripes
    assert find_duplicate(h_checker, [h_stripes]) is None


def test_find_duplicate_returns_first_match_index(tmp_path):
    # Use a checker pattern as the query image.
    checker = _make_checker(tmp_path / "checker.png")
    checker_copy = _make_checker(tmp_path / "checker_copy.png")
    stripes = _make_hstripes(tmp_path / "stripes.png")

    h = phash_hex(checker)
    h_copy = phash_hex(checker_copy)
    h_other = phash_hex(stripes)

    # existing[0] is clearly different; existing[1] and [2] are identical to query.
    # find_duplicate should return index 1 (first match), not 0.
    existing = [h_other, h_copy, h_copy]
    assert find_duplicate(h, existing) == 1


def test_find_duplicate_empty_existing_is_none(tmp_path):
    h = phash_hex(_make_image(tmp_path / "a.png", (7, 7, 7)))
    assert find_duplicate(h, []) is None
