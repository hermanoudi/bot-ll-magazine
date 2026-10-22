"""Rascunho do cadastro a partir da foto, via LangChain (independente de provedor).

O provedor/modelo vêm de ai.* no YAML; qualquer falha devolve {} e o bot segue só com perguntas.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any, Callable

from pydantic import BaseModel, Field, create_model

from .config import AIConfig, FieldSpec
from .image_validator import ValidatedImage

log = logging.getLogger(__name__)

_PY_TYPES: dict[str, Any] = {
    "text": str, "price": str, "int": int, "bool": bool,
    "choice": str, "multichoice": list[str], "colors": list[str],
}

SYSTEM_PROMPT = (
    "Você ajuda a cadastrar produtos de uma loja online brasileira a partir da foto do produto. "
    "Preencha apenas o que for possível inferir com segurança pela imagem (e pela legenda, se houver). "
    "Escreva em português do Brasil. Se não tiver certeza de um campo, deixe-o nulo. "
    "Nunca invente preço, marca ou medidas."
)


def build_draft_model(
    specs: list[FieldSpec], choices: dict[str, list[str]], color_names: list[str]
) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for s in specs:
        if not s.ai:
            continue
        desc = s.question
        opts = choices.get(s.key) or s.options
        if opts:
            desc += f" Opções válidas: {', '.join(opts)}."
        if s.type == "colors" and color_names:
            desc += f" Use apenas estes nomes: {', '.join(color_names)}."
        if s.max_len:
            desc += f" Máximo {s.max_len} caracteres."
        fields[s.key] = (_PY_TYPES[s.type] | None, Field(default=None, description=desc))
    return create_model("ProductDraft", **fields)


def default_llm_factory(ai: AIConfig) -> Any:
    from langchain.chat_models import init_chat_model

    kwargs: dict[str, Any] = {"model_provider": ai.provider, "temperature": ai.temperature}
    if ai.api_key_env:
        key = os.environ.get(ai.api_key_env)
        if key:
            kwargs["api_key"] = key
    return init_chat_model(ai.model, **kwargs)


async def suggest(
    ai: AIConfig,
    image: ValidatedImage,
    specs: list[FieldSpec],
    choices: dict[str, list[str]],
    color_names: list[str],
    caption: str | None = None,
    llm_factory: Callable[[AIConfig], Any] = default_llm_factory,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Devolve {campo: valor_sugerido} (valores ainda não validados). {} se desligada ou em erro."""
    if not ai.enabled or not any(s.ai for s in specs):
        return {}
    try:
        model = build_draft_model(specs, choices, color_names)
        llm = llm_factory(ai).with_structured_output(model)
        text = "Analise a foto e preencha os dados do produto."
        if caption:
            text += f"\nLegenda enviada pelo usuário: {caption}"
        b64 = base64.b64encode(image.data).decode()
        messages = [
            ("system", SYSTEM_PROMPT),
            ("human", [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:{image.content_type};base64,{b64}"}},
            ]),
        ]
        result = await asyncio.wait_for(llm.ainvoke(messages), timeout)
        data = result.model_dump() if isinstance(result, BaseModel) else dict(result)
        return {k: v for k, v in data.items() if v not in (None, "", [])}
    except Exception:  # cota, chave inválida, timeout, saída fora do schema…
        log.exception("Sugestão por IA falhou; seguindo sem sugestões")
        return {}
