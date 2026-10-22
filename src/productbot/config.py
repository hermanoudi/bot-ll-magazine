"""Carrega e valida sites.yaml. Nada específico de um site fica no código."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    pass


def interpolate_env(value: Any, env: dict[str, str] | None = None) -> Any:
    """Substitui ${VAR} em strings, recursivamente. Variável ausente é erro."""
    env = os.environ if env is None else env
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            name = m.group(1)
            if name not in env:
                raise ConfigError(f"Variável de ambiente não definida: {name}")
            return env[name]

        return _ENV_RE.sub(repl, value)
    if isinstance(value, list):
        return [interpolate_env(v, env) for v in value]
    if isinstance(value, dict):
        return {k: interpolate_env(v, env) for k, v in value.items()}
    return value


class AIConfig(BaseModel):
    enabled: bool = False
    provider: str = "google_genai"
    model: str = "gemini-3.5-flash-lite"
    api_key_env: str | None = None
    temperature: float = 0.2


class AuthConfig(BaseModel):
    endpoint: str
    body: dict[str, Any]
    token_field: str = "token"
    header: str = "Authorization: Bearer {token}"


class UploadConfig(BaseModel):
    endpoint: str
    file_field: str = "image"
    response_path_field: str = "path"


class CreateConfig(BaseModel):
    endpoint: str
    success_field: str | None = "success"
    id_field: str | None = None


class ImageRules(BaseModel):
    allowed_formats: list[str] = Field(default_factory=lambda: ["jpeg", "png", "webp"])
    max_bytes: int = 5 * 1024 * 1024
    min_width: int = 0
    min_height: int = 0
    auto_convert_to: str | None = None
    auto_compress: bool = False


class OptionsFrom(BaseModel):
    endpoint: str
    value: str = "id"
    label: str = "name"
    exclude: list[str] = Field(default_factory=list)


FieldType = Literal["text", "price", "int", "bool", "choice", "multichoice", "colors"]


class FieldSpec(BaseModel):
    key: str
    type: FieldType = "text"
    label: str | None = None
    prompt: str | None = None
    required: bool = False
    ai: bool = False
    default: Any = None
    max_len: int | None = None
    min: int | None = None
    max: int | None = None
    options: list[str] = Field(default_factory=list)
    options_from: OptionsFrom | None = None
    as_int: bool = False  # bool enviado como 0/1
    output: Literal["names", "hex"] = "names"  # colors
    discount_from: list[str] | None = None  # [preço_original, preço_atual] -> % calculada

    @property
    def title(self) -> str:
        return self.label or self.key

    @property
    def question(self) -> str:
        return self.prompt or f"{self.title}?"


class SiteConfig(BaseModel):
    display_name: str
    base_url: str
    allowed_user_ids: list[int]
    auth: AuthConfig
    upload: UploadConfig
    create: CreateConfig
    image_field: str = "image"
    image: ImageRules = Field(default_factory=ImageRules)
    fields: list[FieldSpec]
    color_map: dict[str, str] = Field(default_factory=dict)
    timeout: float = 30.0

    @model_validator(mode="after")
    def _check(self) -> "SiteConfig":
        keys = [f.key for f in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("Chaves de campo duplicadas")
        self.base_url = self.base_url.rstrip("/")
        return self


class AppConfig(BaseModel):
    ai: AIConfig = Field(default_factory=AIConfig)
    sites: dict[str, SiteConfig]

    def sites_for(self, user_id: int) -> dict[str, SiteConfig]:
        return {k: s for k, s in self.sites.items() if user_id in s.allowed_user_ids}


def load_config(path: str | Path, env: dict[str, str] | None = None) -> AppConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Arquivo de configuração não encontrado: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(interpolate_env(raw, env))
