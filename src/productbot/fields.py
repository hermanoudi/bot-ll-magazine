"""Parse, validação, formatação e payload dos tipos de campo declarados no YAML."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .config import FieldSpec

_TRUE = {"sim", "s", "yes", "y", "true", "1", "verdadeiro"}
_FALSE = {"nao", "não", "n", "no", "false", "0", "falso"}


class FieldError(ValueError):
    """Mensagem pensada para ser mostrada ao usuário."""


def parse_price(text: str) -> str:
    """Normaliza '179.9', 'R$ 179,90', '1.234,50' para o formato BR '179,90'."""
    s = re.sub(r"[^\d.,]", "", text.replace("R$", ""))
    if not s:
        raise FieldError("Não entendi o preço. Exemplo: 179,90")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"\d+\.\d{3}", s):
        s = s.replace(".", "")  # 1.234 / 1.234.567 -> milhar
    try:
        value = Decimal(s)
    except InvalidOperation:
        raise FieldError("Não entendi o preço. Exemplo: 179,90") from None
    if value <= 0:
        raise FieldError("O preço precisa ser maior que zero.")
    return f"{value:.2f}".replace(".", ",")


def price_to_decimal(price: str) -> Decimal:
    return Decimal(price.replace(".", "").replace(",", "."))


def compute_discount(original: str | None, price: str | None) -> int | None:
    if not original or not price:
        return None
    o, p = price_to_decimal(original), price_to_decimal(price)
    if o <= p:
        return None
    return int(((o - p) / o * 100).to_integral_value())


def parse_bool(text: str) -> bool:
    t = text.strip().lower()
    if t in _TRUE:
        return True
    if t in _FALSE:
        return False
    raise FieldError("Responda sim ou não.")


def resolve_colors(names: list[str], color_map: dict[str, str], strict: bool) -> list[str]:
    """Normaliza nomes de cor (minúsculas, sem duplicar). Com strict, nome fora do mapa é erro."""
    out: list[str] = []
    unknown: list[str] = []
    for raw in names:
        name = raw.strip().lower()
        if not name:
            continue
        if color_map and not name.startswith("#") and name not in color_map:
            unknown.append(name)
            continue
        if name not in out:
            out.append(name)
    if unknown and strict:
        known = ", ".join(sorted(color_map))
        raise FieldError(f"Cor(es) desconhecida(s): {', '.join(unknown)}.\nCores aceitas: {known}")
    return out


def parse_text_value(
    spec: FieldSpec,
    text: str,
    color_map: dict[str, str] | None = None,
    choices: list[str] | None = None,
) -> Any:
    """Converte a resposta livre do usuário no valor interno do campo."""
    text = text.strip()
    t = spec.type
    if t == "text":
        if not text:
            raise FieldError("Resposta vazia.")
        if spec.max_len and len(text) > spec.max_len:
            raise FieldError(f"Máximo de {spec.max_len} caracteres (você enviou {len(text)}).")
        return text
    if t == "price":
        return parse_price(text)
    if t == "int":
        try:
            n = int(re.sub(r"[%\s]", "", text))
        except ValueError:
            raise FieldError("Envie um número inteiro.") from None
        if spec.min is not None and n < spec.min or spec.max is not None and n > spec.max:
            raise FieldError(f"O valor deve estar entre {spec.min} e {spec.max}.")
        return n
    if t == "bool":
        return parse_bool(text)
    if t == "colors":
        names = resolve_colors(re.split(r"[,;/]| e ", text), color_map or {}, strict=True)
        if not names:
            raise FieldError("Envie ao menos uma cor.")
        return names
    if t in ("choice", "multichoice"):
        valid = choices if choices is not None else spec.options
        by_lower = {v.lower(): v for v in valid}
        parts = [text] if t == "choice" else [p.strip() for p in re.split(r"[,;\s]+", text) if p.strip()]
        picked = []
        for p in parts:
            if p.lower() not in by_lower:
                raise FieldError(f"Opção inválida: {p}. Opções: {', '.join(valid)}")
            picked.append(by_lower[p.lower()])
        if not picked:
            raise FieldError("Escolha ao menos uma opção.")
        return picked[0] if t == "choice" else picked
    raise FieldError(f"Tipo de campo não suportado: {t}")


def sanitize_ai_value(
    spec: FieldSpec,
    value: Any,
    color_map: dict[str, str] | None = None,
    choices: list[str] | None = None,
) -> Any | None:
    """Valida o que a IA sugeriu com as mesmas regras do usuário; None se inválido (descarta)."""
    if value is None or value == "" or value == []:
        return None
    try:
        if spec.type == "colors":
            names = value if isinstance(value, list) else [str(value)]
            return resolve_colors([str(n) for n in names], color_map or {}, strict=False) or None
        if spec.type == "multichoice":
            value = ", ".join(value) if isinstance(value, list) else str(value)
        return parse_text_value(spec, str(value), color_map, choices)
    except FieldError:
        return None


def to_payload_value(spec: FieldSpec, value: Any, color_map: dict[str, str]) -> Any:
    if spec.type == "bool":
        return int(value) if spec.as_int else bool(value)
    if spec.type == "colors":
        if spec.output == "hex":
            return [n if n.startswith("#") else color_map.get(n, n) for n in value]
        return list(value)
    return value


def build_payload(
    specs: list[FieldSpec], values: dict[str, Any], color_map: dict[str, str]
) -> dict[str, Any]:
    """Monta o JSON de criação; campos sem valor (e sem default) são omitidos."""
    payload: dict[str, Any] = {}
    for spec in specs:
        v = values.get(spec.key)
        if v is None:
            v = spec.default
        if v is None or v == []:
            continue
        payload[spec.key] = to_payload_value(spec, v, color_map)
    return payload


def format_value(spec: FieldSpec, value: Any, labels: dict[str, str] | None = None) -> str:
    if value is None:
        return "—"
    if spec.type == "bool":
        return "sim" if value else "não"
    if spec.type in ("multichoice", "colors"):
        return ", ".join(value)
    if spec.type == "price":
        return f"R$ {value}"
    if spec.type == "int" and spec.discount_from:
        return f"{value}%"
    if spec.type == "choice" and labels:
        return labels.get(value, value)
    return str(value)
