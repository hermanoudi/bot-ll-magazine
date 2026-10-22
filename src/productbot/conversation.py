"""Fluxo de conversa do Telegram: site -> foto -> (IA) -> perguntas -> revisão -> envio."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from . import ai_suggester
from .api_client import ApiError, SiteApiClient
from .config import AppConfig
from .draft import Draft
from .fields import FieldError, format_value, parse_text_value
from .image_validator import ImageRejected, validate_image

log = logging.getLogger(__name__)

SITE, PHOTO, ASK, REVIEW = range(4)
DRAFT = "draft"
IMAGE_FILTER = filters.PHOTO | filters.Document.IMAGE


def _cfg(ctx: ContextTypes.DEFAULT_TYPE) -> AppConfig:
    return ctx.application.bot_data["config"]


def _client(ctx: ContextTypes.DEFAULT_TYPE, site_key: str) -> SiteApiClient:
    clients: dict[str, SiteApiClient] = ctx.application.bot_data["clients"]
    if site_key not in clients:
        clients[site_key] = SiteApiClient(_cfg(ctx).sites[site_key])
    return clients[site_key]


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])


def _grid(items: list[tuple[str, str]], per_row: int = 2) -> list[list[tuple[str, str]]]:
    return [items[i : i + per_row] for i in range(0, len(items), per_row)]


async def _reply(update: Update, text: str, **kw: Any) -> Message:
    target = update.effective_message
    assert target is not None
    return await target.reply_text(text, **kw)


# ---------- entrada: /novo ou foto solta ----------

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    sites = _cfg(ctx).sites_for(user.id)
    if not sites:
        log.warning("Acesso negado ao usuário %s", user.id)
        await _reply(update, "Você não tem permissão para usar este bot.")
        return ConversationHandler.END

    msg = update.effective_message
    pending = None
    if msg and (msg.photo or msg.document):
        if msg.photo:
            pending = (msg.photo[-1].file_id, "produto.jpg", msg.caption)
        else:
            pending = (msg.document.file_id, msg.document.file_name or "produto", msg.caption)

    if len(sites) == 1:
        key, site = next(iter(sites.items()))
        ctx.user_data[DRAFT] = Draft(site_key=key, site=site, pending_photo=pending)
        return await _after_site(update, ctx)

    ctx.user_data[DRAFT] = Draft(site_key="", site=next(iter(sites.values())), pending_photo=pending)
    await _reply(update, "Em qual site quer cadastrar?",
                 reply_markup=_kb(_grid([(s.display_name, f"site:{k}") for k, s in sites.items()])))
    return SITE


async def on_site(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    key = q.data.split(":", 1)[1]
    sites = _cfg(ctx).sites_for(update.effective_user.id)
    if key not in sites:
        return ConversationHandler.END
    d: Draft = ctx.user_data[DRAFT]
    d.site_key, d.site = key, sites[key]
    await q.edit_message_text(f"Site: {d.site.display_name}")
    return await _after_site(update, ctx)


async def _after_site(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    d: Draft = ctx.user_data[DRAFT]
    if d.pending_photo:
        return await _process_photo(update, ctx, *d.pending_photo)
    r = d.site.image
    await _reply(update, "Envie a foto do produto 📷\n"
                         f"Formatos: {', '.join(f.upper() for f in r.allowed_formats)}"
                         + (f" • mínimo {r.min_width}x{r.min_height}px" if r.min_width else "")
                         + "\nDica: envie como arquivo para não perder qualidade.")
    return PHOTO


# ---------- foto ----------

async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    if msg.photo:
        return await _process_photo(update, ctx, msg.photo[-1].file_id, "produto.jpg", msg.caption)
    return await _process_photo(update, ctx, msg.document.file_id, msg.document.file_name or "produto", msg.caption)


async def _process_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE, file_id: str,
                         filename: str, caption: str | None) -> int:
    d: Draft = ctx.user_data[DRAFT]
    d.pending_photo = None
    tg_file = await ctx.bot.get_file(file_id)
    data = bytes(await tg_file.download_as_bytearray())
    try:
        d.image = validate_image(data, filename, d.site.image)
    except ImageRejected as e:
        await _reply(update, f"❌ {e}\nEnvie outra imagem.")
        return PHOTO
    d.uploaded_path = None
    if d.image.notes:
        await _reply(update, "ℹ️ Imagem ajustada: " + "; ".join(d.image.notes))

    try:
        client = _client(ctx, d.site_key)
        for s in d.site.fields:
            if s.options_from:
                d.options[s.key] = await client.fetch_options(s.options_from)
    except ApiError as e:
        await _reply(update, f"❌ {e}")
        ctx.user_data.pop(DRAFT, None)
        return ConversationHandler.END

    ai = _cfg(ctx).ai
    if ai.enabled and any(s.ai for s in d.site.fields):
        await _reply(update, "🔎 Analisando a foto…")
        suggestion = await ai_suggester.suggest(
            ai, d.image, d.site.fields,
            {k: [v for v, _ in opts] for k, opts in d.options.items()},
            sorted(d.site.color_map), caption,
        )
        d.apply_ai(suggestion)
        if not suggestion:
            await _reply(update, "Não consegui sugerir os dados pela foto; vou perguntar campo a campo.")

    d.build_queue()
    return await _ask_next(update, ctx)


# ---------- perguntas ----------

async def _ask_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    d: Draft = ctx.user_data[DRAFT]
    d.editing = False
    if not d.queue:
        return await _show_review(update, ctx)
    return await _ask(update, ctx, d.queue.pop(0))


async def _ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE, key: str) -> int:
    d: Draft = ctx.user_data[DRAFT]
    s = d.spec(key)
    d.current = key
    d.multi = list(d.values.get(key) or s.default or []) if s.type == "multichoice" else []
    text = s.question
    rows: list[list[tuple[str, str]]] = []
    if s.type == "choice":
        opts = d.options.get(key) or [(o, o) for o in s.options]
        rows = _grid([(label, f"c:{i}") for i, (_, label) in enumerate(opts)])
    elif s.type == "bool":
        rows = [[("Sim", "b:1"), ("Não", "b:0")]]
    elif s.type == "multichoice":
        rows = _multi_rows(d)
        text += "\nToque para marcar/desmarcar e confirme."
    elif s.type == "colors" and d.site.color_map:
        text += "\nCores aceitas: " + ", ".join(sorted(d.site.color_map))
    if not s.required and s.type != "multichoice":
        rows.append([("Pular ⏭", "skip")])
    await _reply(update, text, reply_markup=_kb(rows) if rows else None)
    return ASK


def _multi_rows(d: Draft) -> list[list[tuple[str, str]]]:
    s = d.spec(d.current)
    opts = d.choices(s)
    rows = _grid([(("✅ " if o in d.multi else "▫️ ") + o, f"m:{i}") for i, o in enumerate(opts)], 3)
    rows.append([("Pronto ✔", "m:done")])
    return rows


async def on_answer_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    d: Draft = ctx.user_data[DRAFT]
    s = d.spec(d.current)
    text = update.effective_message.text
    if s.type == "choice":  # aceita o rótulo (Feminino) além do valor (feminino)
        by_label = {lbl.lower(): v for v, lbl in d.options.get(s.key, [])}
        text = by_label.get(text.strip().lower(), text)
    try:
        value = parse_text_value(s, text, d.site.color_map, d.choices(s) or None)
    except FieldError as e:
        await _reply(update, f"⚠️ {e}")
        return ASK
    return await _store(update, ctx, value)


async def on_answer_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    d: Draft = ctx.user_data[DRAFT]
    s = d.spec(d.current)
    kind, _, arg = q.data.partition(":")
    if kind == "skip":
        d.values.pop(s.key, None)
        return await _finish_answer(update, ctx)
    if kind == "c":
        return await _store(update, ctx, d.choices(s)[int(arg)])
    if kind == "b":
        return await _store(update, ctx, arg == "1")
    if kind == "m":
        if arg == "done":
            if not d.multi:
                await q.answer("Escolha ao menos uma opção.", show_alert=True)
                return ASK
            return await _store(update, ctx, list(d.multi))
        opt = d.choices(s)[int(arg)]
        d.multi = [o for o in d.multi if o != opt] if opt in d.multi else d.multi + [opt]
        await q.edit_message_reply_markup(_kb(_multi_rows(d)))
    return ASK


async def _store(update: Update, ctx: ContextTypes.DEFAULT_TYPE, value: Any) -> int:
    d: Draft = ctx.user_data[DRAFT]
    d.values[d.current] = value
    d.ai_filled.discard(d.current)
    return await _finish_answer(update, ctx)


async def _finish_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    d: Draft = ctx.user_data[DRAFT]
    if d.editing:
        return await _show_review(update, ctx)
    return await _ask_next(update, ctx)


# ---------- revisão e envio ----------

async def _show_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    d: Draft = ctx.user_data[DRAFT]
    d.editing = False
    d.current = None
    markup = _kb([[("✅ Cadastrar", "ok")], [("✏️ Editar campo", "edit"), ("❌ Cancelar", "cancel")]])
    msg = update.effective_message
    await msg.reply_photo(d.image.data, caption=d.summary()[:1024], reply_markup=markup)
    return REVIEW


async def on_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    d: Draft = ctx.user_data[DRAFT]
    if q.data == "cancel":
        return await cancel(update, ctx)
    if q.data == "edit":
        rows = _grid([(s.title, f"e:{s.key}") for s in d.editable_specs()], 2)
        await _reply(update, "Qual campo quer editar?", reply_markup=_kb(rows))
        return REVIEW
    if q.data.startswith("e:"):
        d.editing = True
        await q.edit_message_reply_markup(None)
        return await _ask(update, ctx, q.data[2:])
    if q.data == "ok":
        return await _submit(update, ctx)
    return REVIEW


async def _submit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    d: Draft = ctx.user_data[DRAFT]
    missing = d.missing_required()
    if missing:
        await _reply(update, "Faltam campos obrigatórios: " + ", ".join(s.title for s in missing))
        return REVIEW
    lock: asyncio.Lock = ctx.user_data.setdefault("lock", asyncio.Lock())
    if lock.locked():  # clique duplo
        return REVIEW
    async with lock:
        await update.callback_query.edit_message_reply_markup(None)
        await _reply(update, "⏳ Cadastrando…")
        client = _client(ctx, d.site_key)
        try:
            if not d.uploaded_path:
                d.uploaded_path = await client.upload_image(d.image.data, d.image.filename, d.image.content_type)
            result = await client.create_product(d.payload())
        except ApiError as e:
            log.warning("Cadastro falhou (user=%s site=%s): %s", update.effective_user.id, d.site_key, e)
            await _reply(update, f"❌ {e}",
                         reply_markup=_kb([[("🔁 Tentar de novo", "ok"), ("❌ Cancelar", "cancel")]]))
            return REVIEW
    name = format_value(d.spec("name"), d.values.get("name")) if any(s.key == "name" for s in d.site.fields) else "Produto"
    ident = f" (ID {result.id})" if result.id else ""
    await _reply(update, f"✅ {name} cadastrado em {d.site.display_name}{ident}!\nEnvie /novo para cadastrar outro.")
    ctx.user_data.pop(DRAFT, None)
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.pop(DRAFT, None)
    await _reply(update, "Cadastro cancelado. Envie /novo para começar de novo.")
    return ConversationHandler.END


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    sites = _cfg(ctx).sites_for(update.effective_user.id)
    if not sites:
        await _reply(update, "Você não tem permissão para usar este bot.")
        return
    await _reply(update, "Envie /novo (ou direto uma foto) para cadastrar um produto.\n"
                         "/cancelar interrompe o cadastro.\nSites: " + ", ".join(s.display_name for s in sites.values()))


def build_handler() -> ConversationHandler:
    private = filters.ChatType.PRIVATE
    return ConversationHandler(
        entry_points=[
            CommandHandler("novo", start, filters=private),
            MessageHandler(private & IMAGE_FILTER, start),
        ],
        states={
            SITE: [CallbackQueryHandler(on_site, pattern=r"^site:")],
            PHOTO: [MessageHandler(private & IMAGE_FILTER, on_photo)],
            ASK: [
                MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_answer_text),
                CallbackQueryHandler(on_answer_cb, pattern=r"^(c|b|m|skip)(:|$)"),
            ],
            REVIEW: [CallbackQueryHandler(on_review, pattern=r"^(ok|edit|cancel|e:.+)$")],
        },
        fallbacks=[CommandHandler("cancelar", cancel), CommandHandler("novo", start, filters=private)],
        allow_reentry=True,
    )


def register(app: Application) -> None:
    app.add_handler(build_handler())
    app.add_handler(CommandHandler(["start", "ajuda", "help"], help_cmd))
