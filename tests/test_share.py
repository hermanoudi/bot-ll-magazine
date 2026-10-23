from urllib.parse import parse_qs, urlparse

from productbot.draft import Draft
from productbot.share import build_post, fallback_headline, inquiry_text, installment_text, whatsapp_link


def make_draft(site, **values):
    base = {"name": "Vestido infantil azul", "category": "infantil", "price": "180,00",
            "description": "Vestido azul com babados."}
    d = Draft(site_key="llmagazine", site=site, values={**base, **values})
    d.options["category"] = [("infantil", "Infantil")]
    return d


def test_whatsapp_link_encoding_matches_example():
    url = whatsapp_link("5534991738581", "Olá!\n*Vestido*: R$ 180,00")
    assert url.startswith("https://api.whatsapp.com/send/?phone=5534991738581&text=Ol%C3%A1%21%0A%2AVestido%2A")
    assert "R%24+180%2C00" in url
    assert url.endswith("&type=phone_number&app_absent=0")


def test_installment_text():
    assert installment_text("180,00", 3) == "3x de R$ 60,00 sem juros"
    assert installment_text("100,00", 3) == "3x de R$ 33,33 sem juros"
    assert installment_text("1.234,50", 2) == "2x de R$ 617,25 sem juros"
    assert installment_text("180,00", 1) is None
    assert installment_text("180,00", 0) is None


def test_inquiry_text_short_by_default(site):
    assert inquiry_text(make_draft(site), site.share) == (
        "Olá! Gostaria de saber mais sobre este produto da LL Magazine:\n\n"
        "*Vestido infantil azul*\n"
        "Preço: R$ 180,00 (ou 3x de R$ 60,00 sem juros)"
    )


def test_inquiry_text_with_details(site):
    site.share.inquiry_details = True
    text = inquiry_text(make_draft(site), site.share)
    assert text == (
        "Olá! Gostaria de saber mais sobre este produto da LL Magazine:\n\n"
        "*Vestido infantil azul*\n"
        "Preço: R$ 180,00 (ou 3x de R$ 60,00 sem juros)\n"
        "Categoria: Infantil\n\n"
        "Descrição: Vestido azul com babados."
    )


def test_build_post_full(site):
    d = make_draft(site, originalPrice="220,00")
    post = build_post(d, site.share, "ATÉ O VESTIDO GANHOU BABADOS!")
    lines = post.split("\n")
    assert lines[0] == "ATÉ O VESTIDO GANHOU BABADOS!"
    assert "*Vestido infantil azul*" in lines
    assert "LL Magazine" in lines
    assert "~de R$ 220,00~" in lines
    assert "🔥por: *R$ 180,00*" in lines
    assert "(ou 3x de R$ 60,00 sem juros)" in lines
    link = next(line for line in lines if line.startswith("Link: "))
    qs = parse_qs(urlparse(link[6:]).query)
    assert qs["phone"] == ["5534991738581"]
    assert qs["text"][0].startswith("Olá! Gostaria")
    assert lines[-1] == site.share.footer


def test_build_post_fits_photo_caption(site):
    d = make_draft(site, name="Chinelo Havaianas Brasil Branco", originalPrice="55,00", price="52,90",
                   description="Chinelo Havaianas modelo Brasil na cor branca com bandeira do Brasil nas tiras. " * 3)
    assert len(build_post(d, site.share, "HAVAIANAS BRANCA CLASSICA PARA O DIA A DIA")) <= 1024


def test_build_post_without_original_or_installments(site):
    site.share.installments = 0
    post = build_post(make_draft(site), site.share, "X")
    assert "~de" not in post and "(ou" not in post
    assert "🔥por: *R$ 180,00*" in post


def test_build_post_ignores_original_not_above_price(site):
    assert "~de" not in build_post(make_draft(site, originalPrice="150,00"), site.share, "X")


def test_build_post_without_optional_fields(site):
    site.share.inquiry_details = True
    d = make_draft(site)
    del d.values["category"], d.values["description"]
    text = inquiry_text(d, site.share)
    assert "Categoria" not in text and "Descrição" not in text
    assert "Link: " in build_post(d, site.share, "X")


def test_fallback_headline(site):
    site.share.fallback_headlines = ["A", "B"]
    assert {fallback_headline(site.share) for _ in range(50)} <= {"A", "B"}
