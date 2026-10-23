import io
from pathlib import Path

import pytest
import yaml
from PIL import Image

from productbot.config import AppConfig, interpolate_env

EXAMPLE = Path(__file__).parent.parent / "sites.example.yaml"


@pytest.fixture
def app_config() -> AppConfig:
    env = {"LLMAGAZINE_URL": "https://shop.test", "LLMAGAZINE_USER": "bot", "LLMAGAZINE_PASS": "pw",
           "LLMAGAZINE_WHATSAPP": "5534991738581", "LLMAGAZINE_WHATSAPP_GROUP": "120363111@g.us",
           "EVOLUTION_URL": "https://evo.test/", "EVOLUTION_INSTANCE": "loja", "EVOLUTION_API_KEY": "K"}
    raw = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    return AppConfig.model_validate(interpolate_env(raw, env))


@pytest.fixture
def site(app_config):
    return app_config.sites["llmagazine"]


def make_image(size=(600, 600), fmt="PNG", mode="RGB") -> bytes:
    import random

    img = Image.effect_noise(size, 80).convert(mode) if mode == "RGB" else Image.new(mode, size, (200, 10, 10, 128))
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()
