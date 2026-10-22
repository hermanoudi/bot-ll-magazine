"""Fluxo completo (foto -> IA -> perguntas -> revisão -> cadastro) com Telegram simulado e HTTP mockado."""

import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from conftest import make_image
from telegram.ext import ConversationHandler

from productbot import conversation as conv
from productbot.api_client import SiteApiClient

B = "https://shop.test"
UID = 123456789


def message(text=None, photo=False):
    m = MagicMock()
    m.text, m.caption, m.document = text, None, None
    m.photo = [NS(file_id="F1")] if photo else []
    m.reply_text, m.reply_photo = AsyncMock(), AsyncMock()
    return m


def update(msg=None, data=None):
    q = None
    if data is not None:
        q = MagicMock()
        q.data = data
        q.answer, q.edit_message_reply_markup, q.edit_message_text = AsyncMock(), AsyncMock(), AsyncMock()
        msg = message()
        q.message = msg
    return NS(effective_user=NS(id=UID), effective_message=msg, callback_query=q)


@pytest.fixture
def ctx(app_config, monkeypatch):
    bot = MagicMock()
    tg_file = MagicMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(make_image((600, 600), "PNG")))
    bot.get_file = AsyncMock(return_value=tg_file)
    app = NS(bot_data={"config": app_config, "clients": {}})
    monkeypatch.setattr(conv.ai_suggester, "suggest", AsyncMock(return_value={
        "name": "Vestido floral", "category": "feminino", "description": "Vestido leve", "colors": ["rosa"]}))
    return NS(bot=bot, application=app, user_data={})


@respx.mock
async def test_full_flow(ctx):
    respx.post(f"{B}/api/auth.php").respond(json={"token": "T"})
    respx.get(f"{B}/api/products.php").respond(json=[{"id": "all", "name": "Todos"}, {"id": "feminino", "name": "Feminino"}])
    up = respx.post(f"{B}/api/admin/upload.php").respond(json={"success": True, "path": "assets/images/products/v.jpg"})
    create = respx.post(f"{B}/api/admin/products.php").respond(json={"success": True, "product_id": 42})

    # foto solta inicia o fluxo; IA preenche tudo menos o preço
    u = update(message(photo=True))
    assert await conv.start(u, ctx) == conv.ASK
    assert ctx.user_data["draft"].current == "price"

    # preço inválido -> avisa e continua; válido -> próxima pergunta (originalPrice, opcional)
    assert await conv.on_answer_text(update(message("abc")), ctx) == conv.ASK
    assert await conv.on_answer_text(update(message("R$ 150,00")), ctx) == conv.ASK
    assert ctx.user_data["draft"].current == "originalPrice"
    assert await conv.on_answer_text(update(message("200")), ctx) == conv.REVIEW

    d = ctx.user_data["draft"]
    assert d.summary().count("✨") >= 3 and "Desconto: 25%" in d.summary()

    assert await conv.on_review(update(data="ok"), ctx) == ConversationHandler.END
    assert up.call_count == 1 and create.call_count == 1
    body = json.loads(create.calls[0].request.content)
    assert body == {
        "name": "Vestido floral", "category": "feminino", "price": "150,00", "originalPrice": "200,00",
        "discount": 25, "description": "Vestido leve", "colors": ["#FF69B4"],
        "sizes": ["PP", "P", "M", "G", "GG"], "inStock": 1, "featured": 0,
        "image": "assets/images/products/v.jpg",
    }
    assert "draft" not in ctx.user_data


@respx.mock
async def test_create_failure_keeps_upload_and_retries(ctx):
    respx.post(f"{B}/api/auth.php").respond(json={"token": "T"})
    respx.get(f"{B}/api/products.php").respond(json=[{"id": "feminino", "name": "Feminino"}])
    up = respx.post(f"{B}/api/admin/upload.php").respond(json={"success": True, "path": "p.jpg"})
    respx.post(f"{B}/api/admin/products.php").mock(side_effect=[
        httpx.Response(500, json={"error": "Failed to create product"}),
        httpx.Response(200, json={"success": True, "product_id": 1})])

    await conv.start(update(message(photo=True)), ctx)
    await conv.on_answer_text(update(message("99,90")), ctx)
    await conv.on_answer_cb(update(data="skip"), ctx)  # pula originalPrice
    assert await conv.on_review(update(data="ok"), ctx) == conv.REVIEW  # falha
    assert ctx.user_data["draft"].uploaded_path == "p.jpg"
    assert await conv.on_review(update(data="ok"), ctx) == ConversationHandler.END
    assert up.call_count == 1  # upload reaproveitado


async def test_unauthorized_user(ctx):
    u = update(message("/novo"))
    u.effective_user = NS(id=999)
    assert await conv.start(u, ctx) == ConversationHandler.END
    u.effective_message.reply_text.assert_awaited_once()
    assert "draft" not in ctx.user_data


async def test_small_image_rejected(ctx):
    ctx.bot.get_file.return_value.download_as_bytearray = AsyncMock(return_value=bytearray(make_image((50, 50))))
    assert await conv.start(update(message(photo=True)), ctx) == conv.PHOTO
