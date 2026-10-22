from productbot.draft import Draft


def make(site):
    d = Draft(site_key="llmagazine", site=site)
    d.options["category"] = [("feminino", "Feminino"), ("masculino", "Masculino")]
    return d


def test_ai_values_validated_and_queue(site):
    d = make(site)
    d.apply_ai({"name": "Vestido floral", "category": "inexistente", "description": "Leve", "colors": ["rosa", "zzz"]})
    assert d.values == {"name": "Vestido floral", "description": "Leve", "colors": ["rosa"]}
    d.build_queue()
    # categoria inválida e preço faltam (obrigatórios); originalPrice não tem default; discount é calculado
    assert d.queue == ["category", "price", "originalPrice"]


def test_discount_and_payload(site):
    d = make(site)
    d.values.update(name="V", category="feminino", description="d", price="150,00", originalPrice="200,00")
    d.uploaded_path = "assets/images/products/v.jpg"
    p = d.payload()
    assert p["discount"] == 25 and p["image"] == "assets/images/products/v.jpg"
    assert p["category"] == "feminino" and p["inStock"] == 1
    assert d.missing_required() == []
    assert "Desconto: 25%" in d.summary() and "Feminino" in d.summary()


def test_missing_required(site):
    d = make(site)
    assert {s.key for s in d.missing_required()} == {"name", "category", "price", "description"}
