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

    assert await conv.on_review(update(data="ok"), ctx) == conv.SHARE
    assert up.call_count == 1 and create.call_count == 1
    body = json.loads(create.calls[0].request.content)
    assert body == {
        "name": "Vestido floral", "category": "feminino", "price": "150,00", "originalPrice": "200,00",
        "discount": 25, "description": "Vestido leve", "colors": ["#FF69B4"],
        "sizes": ["PP", "P", "M", "G", "GG"], "inStock": 1, "featured": 0,
        "image": "assets/images/products/v.jpg",
    }
    assert await conv.on_share(update(data="sh:no"), ctx) == ConversationHandler.END
    assert "draft" not in ctx.user_data


@respx.mock
async def test_full_flow_without_share_ends_after_create(ctx):
    ctx.application.bot_data["config"].sites["llmagazine"].share = None
    respx.post(f"{B}/api/auth.php").respond(json={"token": "T"})
    respx.get(f"{B}/api/products.php").respond(json=[{"id": "feminino", "name": "Feminino"}])
    respx.post(f"{B}/api/admin/upload.php").respond(json={"success": True, "path": "p.jpg"})
    respx.post(f"{B}/api/admin/products.php").respond(json={"success": True, "product_id": 1})

    await conv.start(update(message(photo=True)), ctx)
    await conv.on_answer_text(update(message("99,90")), ctx)
    await conv.on_answer_cb(update(data="skip"), ctx)
    assert await conv.on_review(update(data="ok"), ctx) == ConversationHandler.END
    assert "draft" not in ctx.user_data


@respx.mock
async def test_share_flow(ctx, monkeypatch):
    headline = AsyncMock(side_effect=["PRIMEIRA CHAMADA", None, None])
    monkeypatch.setattr(conv.ai_suggester, "suggest_headline", headline)
    respx.post(f"{B}/api/auth.php").respond(json={"token": "T"})
    respx.get(f"{B}/api/products.php").respond(json=[{"id": "feminino", "name": "Feminino"}])
    respx.post(f"{B}/api/admin/upload.php").respond(json={"success": True, "path": "p.jpg"})
    respx.post(f"{B}/api/admin/products.php").respond(json={"success": True, "product_id": 1})

    await conv.start(update(message(photo=True)), ctx)
    await conv.on_answer_text(update(message("99,90")), ctx)
    await conv.on_answer_cb(update(data="skip"), ctx)
    assert await conv.on_review(update(data="ok"), ctx) == conv.SHARE

    # post curto cabe na legenda da foto
    u = update(data="sh:yes")
    assert await conv.on_share(u, ctx) == conv.SHARE
    u.callback_query.edit_message_reply_markup.assert_awaited_once_with(None)
    kw = u.effective_message.reply_photo.await_args.kwargs
    assert kw["caption"].startswith("PRIMEIRA CHAMADA\n") and "api.whatsapp.com/send" in kw["caption"]
    assert kw["reply_markup"] is not None

    # outra chamada: a IA não respondeu -> frase padrão do YAML
    u = update(data="sh:again")
    assert await conv.on_share(u, ctx) == conv.SHARE
    assert u.effective_message.reply_photo.await_args.kwargs["caption"].startswith("OLHA O ACHADINHO QUE CHEGOU!")

    # post longo estoura a legenda: foto sem legenda + texto com os botões
    ctx.user_data["draft"].values["name"] = "Vestido leve e confortável. " * 20
    u = update(data="sh:again")
    assert await conv.on_share(u, ctx) == conv.SHARE
    assert "caption" not in u.effective_message.reply_photo.await_args.kwargs
    sent = u.effective_message.reply_text.await_args_list[-1]
    assert "api.whatsapp.com/send" in sent.args[0] and sent.kwargs["reply_markup"] is not None

    assert await conv.on_share(update(data="sh:done"), ctx) == ConversationHandler.END
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
    assert await conv.on_review(update(data="ok"), ctx) == conv.SHARE
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


# ---------- envio ao grupo do WhatsApp ----------

def buttons(call):
    return [b.callback_data for row in call.kwargs["reply_markup"].inline_keyboard for b in row]


async def to_share(ctx, monkeypatch, wa=None):
    """Cadastra um produto (HTTP mockado) e deixa o fluxo na prévia de divulgação."""
    monkeypatch.setattr(conv.ai_suggester, "suggest_headline", AsyncMock(return_value="CHAMADA"))
    if wa is not None:
        ctx.application.bot_data["wa"] = wa
    respx.post(f"{B}/api/auth.php").respond(json={"token": "T"})
    respx.get(f"{B}/api/products.php").respond(json=[{"id": "feminino", "name": "Feminino"}])
    respx.post(f"{B}/api/admin/upload.php").respond(json={"success": True, "path": "p.jpg"})
    respx.post(f"{B}/api/admin/products.php").respond(json={"success": True, "product_id": 1})
    await conv.start(update(message(photo=True)), ctx)
    await conv.on_answer_text(update(message("99,90")), ctx)
    await conv.on_answer_cb(update(data="skip"), ctx)
    assert await conv.on_review(update(data="ok"), ctx) == conv.SHARE
    u = update(data="sh:yes")
    assert await conv.on_share(u, ctx) == conv.SHARE
    return u


@respx.mock
async def test_send_to_group_posts_exact_preview(ctx, monkeypatch):
    wa = MagicMock(send_image=AsyncMock(), send_text=AsyncMock())
    u = await to_share(ctx, monkeypatch, wa)
    call = u.effective_message.reply_photo.await_args
    assert buttons(call) == ["sh:send", "sh:again", "sh:done"]

    s = update(data="sh:send")
    assert await conv.on_share(s, ctx) == ConversationHandler.END
    group, data, mime, name, caption = wa.send_image.await_args.args
    assert group == "120363111@g.us" and mime == "image/png" and caption == call.kwargs["caption"]
    wa.send_text.assert_not_awaited()
    assert "draft" not in ctx.user_data


@respx.mock
async def test_send_failure_allows_retry(ctx, monkeypatch):
    wa = MagicMock(send_image=AsyncMock(side_effect=[conv.WhatsAppError("WhatsApp: fora do ar"), None]),
                   send_text=AsyncMock())
    await to_share(ctx, monkeypatch, wa)

    s = update(data="sh:send")
    assert await conv.on_share(s, ctx) == conv.SHARE
    err = s.effective_message.reply_text.await_args_list[-1]
    assert "fora do ar" in err.args[0] and buttons(err) == ["sh:send", "sh:done"]
    assert ctx.user_data["draft"].share_post  # post preservado

    assert await conv.on_share(update(data="sh:send"), ctx) == ConversationHandler.END
    assert wa.send_image.await_count == 2


@respx.mock
async def test_send_long_post_sends_image_then_text(ctx, monkeypatch):
    wa = MagicMock(send_image=AsyncMock(), send_text=AsyncMock())
    await to_share(ctx, monkeypatch, wa)
    d = ctx.user_data["draft"]
    d.share_post = "x" * 1500

    assert await conv.on_share(update(data="sh:send"), ctx) == ConversationHandler.END
    assert wa.send_image.await_args.args[4] is None
    wa.send_text.assert_awaited_once_with("120363111@g.us", "x" * 1500)


@respx.mock
async def test_no_send_button_without_gateway_or_group(ctx, monkeypatch, app_config):
    app_config.whatsapp = None
    u = await to_share(ctx, monkeypatch)
    assert buttons(u.effective_message.reply_photo.await_args) == ["sh:again", "sh:done"]

    app_config.sites["llmagazine"].share.group_id = None
    ctx.user_data.pop("draft")
    u = await to_share(ctx, monkeypatch)
    assert "sh:send" not in buttons(u.effective_message.reply_photo.await_args)


async def test_groups_cmd(ctx):
    u = update(message("/grupos"))
    ctx.args = []
    ctx.application.bot_data["wa"] = MagicMock(list_groups=AsyncMock(return_value=[("1@g.us", "Clientes")]))
    await conv.groups_cmd(u, ctx)
    text = u.effective_message.reply_text.await_args.args[0]
    assert "Clientes" in text and "1@g.us" in text


async def test_groups_cmd_filters_by_name_and_caps_list(ctx):
    groups = [(f"{i}@g.us", f"Grupo {i:02d}") for i in range(30)] + [("t@g.us", "Teste Loja")]
    ctx.application.bot_data["wa"] = MagicMock(list_groups=AsyncMock(return_value=groups))

    ctx.args = ["teste"]
    u = update(message("/grupos teste"))
    await conv.groups_cmd(u, ctx)
    text = u.effective_message.reply_text.await_args.args[0]
    assert "Teste Loja" in text and "t@g.us" in text and "Grupo 00" not in text

    ctx.args = []
    u = update(message("/grupos"))
    await conv.groups_cmd(u, ctx)
    text = u.effective_message.reply_text.await_args.args[0]
    assert "Mostrando 20 de 31" in text and "/grupos nome" in text and text.count("@g.us") == 20

    ctx.args = ["inexistente"]
    u = update(message("/grupos inexistente"))
    await conv.groups_cmd(u, ctx)
    assert "Nenhum grupo com" in u.effective_message.reply_text.await_args.args[0]


async def test_groups_cmd_denied_and_unconfigured(ctx, app_config):
    ctx.args = []
    u = update(message("/grupos"))
    u.effective_user = NS(id=999)
    await conv.groups_cmd(u, ctx)
    assert "permissão" in u.effective_message.reply_text.await_args.args[0]

    app_config.whatsapp = None
    u = update(message("/grupos"))
    await conv.groups_cmd(u, ctx)
    assert "não está configurado" in u.effective_message.reply_text.await_args.args[0]
