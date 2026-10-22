"""Teste real contra a API de um site: login, categorias, upload, criação, leitura e remoção.

Uso (a senha vem do ambiente, nunca do arquivo):
    SMOKE_URL=https://llmagazine.com.br SMOKE_USER=admin SMOKE_PASS=... uv run python scripts/e2e_smoke.py

O produto é criado fora de estoque (não aparece na vitrine) e removido no final. O arquivo de imagem
enviado permanece no servidor, pois a API de remoção de produto não apaga imagens.
"""

import asyncio
import io
import os
from pathlib import Path

import yaml
from PIL import Image

from productbot.api_client import SiteApiClient
from productbot.config import AppConfig, interpolate_env
from productbot.draft import Draft
from productbot.image_validator import validate_image

ROOT = Path(__file__).resolve().parent.parent


async def main() -> None:
    env = {"LLMAGAZINE_URL": os.environ["SMOKE_URL"], "LLMAGAZINE_USER": os.environ["SMOKE_USER"],
           "LLMAGAZINE_PASS": os.environ["SMOKE_PASS"]}
    cfg = AppConfig.model_validate(interpolate_env(yaml.safe_load((ROOT / "sites.example.yaml").read_text()), env))
    site = cfg.sites["llmagazine"]
    client = SiteApiClient(site)
    try:
        opts = await client.fetch_options(next(f for f in site.fields if f.key == "category").options_from)
        print("categorias:", opts)

        buf = io.BytesIO()
        Image.new("RGB", (400, 400), (230, 120, 160)).save(buf, "PNG")
        img = validate_image(buf.getvalue(), "teste-bot.png", site.image)
        print("imagem:", img.filename, img.format, len(img.data), img.notes)

        d = Draft(site_key="llmagazine", site=site, image=img)
        d.options["category"] = opts
        d.values.update(name="TESTE BOT - pode apagar", category=opts[0][0], price="150,00",
                        originalPrice="200,00", description="Produto de teste criado pelo bot.",
                        colors=["rosa"], inStock=False)
        d.uploaded_path = await client.upload_image(img.data, img.filename, img.content_type)
        print("upload ->", d.uploaded_path)
        res = await client.create_product(d.payload())
        print("criado: id =", res.id)

        got = await client._authed("GET", f"/api/admin/products.php/{res.id}")
        print("GET:", got.status_code, got.text[:400])
        dele = await client._authed("DELETE", f"/api/admin/products.php/{res.id}")
        print("DELETE:", dele.status_code)
        print("GET após delete:", (await client._authed("GET", f"/api/admin/products.php/{res.id}")).status_code)
    finally:
        await client.aclose()


asyncio.run(main())
