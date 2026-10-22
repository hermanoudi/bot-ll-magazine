import pytest

from productbot.config import FieldSpec
from productbot.fields import (FieldError, build_payload, compute_discount, parse_price,
                               parse_text_value, sanitize_ai_value)


@pytest.mark.parametrize("raw,exp", [
    ("179,90", "179,90"), ("179.9", "179,90"), ("R$ 179,90", "179,90"),
    ("1.234,50", "1234,50"), ("1.234", "1234,00"), ("50", "50,00"),
])
def test_price(raw, exp):
    assert parse_price(raw) == exp


@pytest.mark.parametrize("raw", ["abc", "0", "R$"])
def test_price_invalid(raw):
    with pytest.raises(FieldError):
        parse_price(raw)


def test_discount():
    assert compute_discount("200,00", "150,00") == 25
    assert compute_discount("100,00", "150,00") is None
    assert compute_discount(None, "10,00") is None


def test_colors_strict_and_ai(site):
    spec = next(f for f in site.fields if f.key == "colors")
    assert parse_text_value(spec, "Preto, azul marinho e Rosa", site.color_map) == ["preto", "azul marinho", "rosa"]
    with pytest.raises(FieldError):
        parse_text_value(spec, "xyzcor", site.color_map)
    assert sanitize_ai_value(spec, ["preto", "xyzcor"], site.color_map) == ["preto"]


def test_choice_and_multichoice():
    c = FieldSpec(key="c", type="choice")
    assert parse_text_value(c, "FEMININO", choices=["feminino", "masculino"]) == "feminino"
    m = FieldSpec(key="s", type="multichoice", options=["P", "M", "G"])
    assert parse_text_value(m, "p, g") == ["P", "G"]
    with pytest.raises(FieldError):
        parse_text_value(m, "XL")


def test_ai_invalid_choice_discarded():
    c = FieldSpec(key="c", type="choice")
    assert sanitize_ai_value(c, "outra", choices=["a", "b"]) is None


def test_payload(site):
    values = {"name": "Vestido", "category": "feminino", "price": "99,90", "description": "d",
              "colors": ["preto"], "image": "assets/x.jpg", "originalPrice": None}
    p = build_payload(site.fields, values, site.color_map)
    assert p["colors"] == ["#000000"]
    assert p["inStock"] == 1 and p["featured"] == 0
    assert p["sizes"] == ["PP", "P", "M", "G", "GG"]
    assert "originalPrice" not in p
