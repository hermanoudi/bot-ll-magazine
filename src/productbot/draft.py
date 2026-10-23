"""Estado de um cadastro em andamento. Lógica pura (sem Telegram) para ser testável."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import FieldSpec, SiteConfig
from .fields import build_payload, compute_discount, format_value, sanitize_ai_value
from .image_validator import ValidatedImage


@dataclass
class Draft:
    site_key: str
    site: SiteConfig
    values: dict[str, Any] = field(default_factory=dict)
    image: ValidatedImage | None = None
    uploaded_path: str | None = None  # reaproveitado se o cadastro falhar depois do upload
    options: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # choice dinâmico
    queue: list[str] = field(default_factory=list)
    current: str | None = None
    editing: bool = False
    multi: list[str] = field(default_factory=list)  # seleção em andamento de um multichoice
    pending_photo: tuple[str, str, str | None] | None = None  # (file_id, filename, caption)
    ai_filled: set[str] = field(default_factory=set)
    share_post: str | None = None  # post da prévia; é exatamente o que vai ao grupo

    def spec(self, key: str) -> FieldSpec:
        return next(s for s in self.site.fields if s.key == key)

    def choices(self, spec: FieldSpec) -> list[str]:
        if spec.key in self.options:
            return [v for v, _ in self.options[spec.key]]
        return spec.options

    def labels(self, spec: FieldSpec) -> dict[str, str]:
        return dict(self.options.get(spec.key, []))

    def apply_ai(self, suggestion: dict[str, Any]) -> None:
        for key, raw in suggestion.items():
            spec = next((s for s in self.site.fields if s.key == key), None)
            if spec is None:
                continue
            value = sanitize_ai_value(spec, raw, self.site.color_map, self.choices(spec))
            if value is not None:
                self.values[key] = value
                self.ai_filled.add(key)

    def build_queue(self) -> None:
        """Pergunta: obrigatórios faltando e opcionais sem valor nem default. Calculados, nunca."""
        self.queue = [
            s.key
            for s in self.site.fields
            if not s.discount_from
            and s.key not in self.values
            and (s.required or s.default is None)
        ]

    def refresh_computed(self) -> None:
        for s in self.site.fields:
            if s.discount_from:
                orig, price = (self.values.get(k) for k in s.discount_from)
                d = compute_discount(orig, price)
                if d is None:
                    self.values.pop(s.key, None)
                else:
                    self.values[s.key] = d

    def effective(self, spec: FieldSpec) -> Any:
        v = self.values.get(spec.key)
        return spec.default if v is None else v

    def editable_specs(self) -> list[FieldSpec]:
        return [s for s in self.site.fields if not s.discount_from]

    def summary(self) -> str:
        self.refresh_computed()
        lines = ["📦 Confira o cadastro:", ""]
        for s in self.site.fields:
            v = self.effective(s)
            if v is None and not s.required:
                continue
            mark = " ✨" if s.key in self.ai_filled else ""
            lines.append(f"• {s.title}: {format_value(s, v, self.labels(s))}{mark}")
        if self.ai_filled:
            lines += ["", "✨ = sugerido pela IA, confira antes de cadastrar."]
        return "\n".join(lines)

    def missing_required(self) -> list[FieldSpec]:
        return [s for s in self.site.fields if s.required and self.effective(s) is None]

    def payload(self) -> dict[str, Any]:
        self.refresh_computed()
        payload = build_payload(self.site.fields, self.values, self.site.color_map)
        if self.uploaded_path:
            payload[self.site.image_field] = self.uploaded_path
        return payload
