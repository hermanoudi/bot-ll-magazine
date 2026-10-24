import pytest
from conftest import make_image

from productbot.ai_suggester import build_draft_model, suggest, suggest_headline
from productbot.config import AIConfig
from productbot.image_validator import ValidatedImage


class FakeLLM:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.messages = result, exc, None

    def with_structured_output(self, model):
        self.model = model
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        if self.exc:
            raise self.exc
        return self.model(**self.result)


@pytest.fixture
def img():
    return ValidatedImage(make_image((300, 300)), "a.png", "image/png", "png", 300, 300)


def test_model_only_ai_fields(site):
    m = build_draft_model(site.fields, {"category": ["feminino"]}, ["preto"])
    assert set(m.model_fields) == {"name", "category", "description", "colors", "sizes"}
    assert "feminino" in m.model_fields["category"].description


def test_sizes_hint_in_description(site):
    desc = build_draft_model(site.fields, {}, []).model_fields["sizes"].description
    for expected in ("calçados", "33 a 44", "infantil", "somente U", "PP"):
        assert expected in desc


def test_sizes_sanitized(site):
    from productbot.fields import sanitize_ai_value
    spec = next(s for s in site.fields if s.key == "sizes")
    assert sanitize_ai_value(spec, ["36", "38"]) == ["36", "38"]
    assert sanitize_ai_value(spec, ["U"]) == ["U"]
    assert sanitize_ai_value(spec, ["50"]) is None


async def test_suggest_ok(site, img):
    llm = FakeLLM({"name": "Vestido", "category": "feminino"})
    out = await suggest(AIConfig(enabled=True), img, site.fields, {"category": ["feminino"]}, ["preto"],
                        caption="vestido novo", llm_factory=lambda ai: llm)
    assert out == {"name": "Vestido", "category": "feminino"}
    assert "vestido novo" in llm.messages[1][1][0]["text"]
    assert llm.messages[1][1][1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_suggest_failure_returns_empty(site, img):
    out = await suggest(AIConfig(enabled=True), img, site.fields, {}, [], llm_factory=lambda ai: FakeLLM(exc=RuntimeError("quota")))
    assert out == {}


class HeadlineLLM:
    def __init__(self, content=None, exc=None):
        self.content, self.exc, self.messages = content, exc, None

    async def ainvoke(self, messages):
        self.messages = messages
        if self.exc:
            raise self.exc
        return type("Msg", (), {"content": self.content})()


async def test_suggest_headline_normalizes(img):
    llm = HeadlineLLM('  "até o controle\nganhou roupa de gala!"  ')
    seen = []
    out = await suggest_headline(AIConfig(enabled=True), img, "Controle", "Azul",
                                 llm_factory=lambda ai: seen.append(ai) or llm)
    assert out == "ATÉ O CONTROLE GANHOU ROUPA DE GALA!"
    assert seen[0].temperature == 0.9
    assert "Controle" in llm.messages[1][1][0]["text"]


async def test_suggest_headline_content_parts(img):
    llm = HeadlineLLM([{"type": "text", "text": "olha o achado"}])
    assert await suggest_headline(AIConfig(enabled=True), img, "X", llm_factory=lambda ai: llm) == "OLHA O ACHADO"


async def test_suggest_headline_failure_or_empty_returns_none(img):
    assert await suggest_headline(AIConfig(enabled=True), img, "X",
                                  llm_factory=lambda ai: HeadlineLLM(exc=RuntimeError("quota"))) is None
    assert await suggest_headline(AIConfig(enabled=True), img, "X",
                                  llm_factory=lambda ai: HeadlineLLM("  ")) is None


async def test_suggest_headline_disabled(img):
    def boom(ai):
        raise AssertionError("não deveria chamar a IA")
    assert await suggest_headline(AIConfig(enabled=False), img, "X", llm_factory=boom) is None


async def test_suggest_disabled(site, img):
    def boom(ai):
        raise AssertionError("não deveria chamar a IA")
    assert await suggest(AIConfig(enabled=False), img, site.fields, {}, [], llm_factory=boom) == {}
