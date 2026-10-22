import pytest
from conftest import make_image

from productbot.config import ImageRules
from productbot.image_validator import ImageRejected, validate_image

RULES = ImageRules(allowed_formats=["jpeg", "png"], max_bytes=200_000, min_width=300, min_height=300,
                   auto_convert_to="jpeg", auto_compress=True)


def test_valid_png_untouched():
    data = make_image((320, 320), "PNG")
    rules = RULES.model_copy(update={"max_bytes": 10_000_000})
    r = validate_image(data, "foto.png", rules)
    assert r.format == "png" and r.data == data and r.filename == "foto.png" and not r.notes


def test_too_small_rejected():
    with pytest.raises(ImageRejected, match="pequena"):
        validate_image(make_image((100, 100)), "x.png", RULES)


def test_not_an_image_rejected():
    with pytest.raises(ImageRejected, match="imagem"):
        validate_image(b"isto nao e imagem", "x.jpg", RULES)


def test_unsupported_format_converted():
    r = validate_image(make_image((400, 400), "BMP"), "x.bmp", RULES.model_copy(update={"max_bytes": 10_000_000}))
    assert r.format == "jpeg" and r.filename == "x.jpg" and r.content_type == "image/jpeg"


def test_unsupported_without_convert_rejected():
    rules = RULES.model_copy(update={"auto_convert_to": None})
    with pytest.raises(ImageRejected, match="não aceito"):
        validate_image(make_image((400, 400), "BMP"), "x.bmp", rules)


def test_oversize_compressed():
    data = make_image((1600, 1600), "PNG")
    assert len(data) > RULES.max_bytes
    r = validate_image(data, "big.png", RULES)
    assert len(r.data) <= RULES.max_bytes and r.format == "jpeg" and r.filename == "big.jpg"


def test_oversize_without_compress_rejected():
    rules = RULES.model_copy(update={"auto_compress": False})
    with pytest.raises(ImageRejected, match="máximo"):
        validate_image(make_image((1600, 1600), "PNG"), "big.png", rules)
