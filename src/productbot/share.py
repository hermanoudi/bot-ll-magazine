"""Post de divulgação para o grupo do WhatsApp. Lógica pura (sem Telegram) para ser testável."""

from __future__ import annotations

import random
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import quote_plus, urlencode

from .config import ShareConfig
from .draft import Draft
from .fields import format_value, price_to_decimal


def installment_text(price: str, n: int) -> str | None:
    """'180,00', 3 -> '3x de R$ 60,00 sem juros'. None sem parcelamento."""
    if n <= 1:
        return None
    part = (price_to_decimal(price) / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{n}x de R$ {str(part).replace('.', ',')} sem juros"


def whatsapp_link(phone: str, text: str) -> str:
    query = urlencode(
        {"phone": phone, "text": text, "type": "phone_number", "app_absent": 0}, quote_via=quote_plus
    )
    return f"https://api.whatsapp.com/send/?{query}"


def _value(d: Draft, key: str | None) -> str | None:
    """Valor do campo já formatado para leitura (rótulo em choice); None se vazio ou inexistente."""
    spec = next((s for s in d.site.fields if s.key == key), None) if key else None
    if spec is None:
        return None
    v = d.effective(spec)
    return None if v is None else format_value(spec, v, d.labels(spec))


def inquiry_text(d: Draft, cfg: ShareConfig) -> str:
    """Mensagem pronta que o cliente envia à loja ao tocar no link."""
    d.refresh_computed()
    price = d.values.get(cfg.price_field)
    lines = [cfg.inquiry_intro.format(store_name=cfg.store_name), "", f"*{_value(d, cfg.name_field) or 'Produto'}*"]
    if price:
        line = f"Preço: R$ {price}"
        if inst := installment_text(price, cfg.installments):
            line += f" (ou {inst})"
        lines.append(line)
    if cfg.inquiry_details:
        if category := _value(d, cfg.category_field):
            lines.append(f"Categoria: {category}")
        if description := _value(d, cfg.description_field):
            lines += ["", f"Descrição: {description}"]
    return "\n".join(lines)


def build_post(d: Draft, cfg: ShareConfig, headline: str) -> str:
    d.refresh_computed()
    price = d.values.get(cfg.price_field)
    original = d.values.get(cfg.original_price_field) if cfg.original_price_field else None

    lines = [headline, "", f"*{_value(d, cfg.name_field) or 'Produto'}*", cfg.store_name, ""]
    if price:
        if original and price_to_decimal(original) > price_to_decimal(price):
            lines.append(f"~de R$ {original}~")
        lines.append(f"🔥por: *R$ {price}*")
        if inst := installment_text(price, cfg.installments):
            lines.append(f"(ou {inst})")
        lines.append("")
    lines += [f"Link: {whatsapp_link(cfg.whatsapp_phone, inquiry_text(d, cfg))}", "", cfg.footer]
    return "\n".join(lines)


def fallback_headline(cfg: ShareConfig) -> str:
    return random.choice(cfg.fallback_headlines)
