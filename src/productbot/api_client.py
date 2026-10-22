"""Cliente HTTP genérico para a API de admin de um site, guiado por SiteConfig."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import OptionsFrom, SiteConfig

log = logging.getLogger(__name__)


class ApiError(Exception):
    """Erro da API do site; a mensagem é segura para mostrar ao usuário."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class CreateResult:
    id: str | None
    raw: dict[str, Any]


def _dig(data: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict):
            msg = body.get("error") or body.get("message")
            if msg:
                return str(msg)
    except ValueError:
        pass
    return f"HTTP {resp.status_code}"


class SiteApiClient:
    def __init__(self, site: SiteConfig, http: httpx.AsyncClient | None = None):
        self.site = site
        self._http = http or httpx.AsyncClient(timeout=site.timeout)
        self._owns_http = http is None
        self._token: str | None = None
        self._login_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _url(self, endpoint: str) -> str:
        return self.site.base_url + (endpoint if endpoint.startswith("/") else "/" + endpoint)

    def _auth_header(self) -> dict[str, str]:
        name, _, tmpl = self.site.auth.header.partition(":")
        return {name.strip(): tmpl.strip().format(token=self._token)}

    async def _send(self, method: str, url: str, retries: int = 0, **kw: Any) -> httpx.Response:
        for attempt in range(retries + 1):
            try:
                return await self._http.request(method, url, **kw)
            except httpx.TransportError as e:
                if attempt == retries:
                    log.warning("Falha de rede em %s %s: %s", method, url, e)
                    raise ApiError("Não consegui falar com o site (erro de rede). Tente novamente.") from e
                await asyncio.sleep(0.5 * 2**attempt)
        raise AssertionError("unreachable")

    async def login(self) -> None:
        a = self.site.auth
        resp = await self._send("POST", self._url(a.endpoint), retries=2, json=a.body)
        if resp.status_code != 200:
            raise ApiError(f"Login no site falhou: {_error_message(resp)}", resp.status_code)
        try:
            token = _dig(resp.json(), a.token_field)
        except ValueError:
            token = None
        if not token:
            raise ApiError("Login no site não retornou token.")
        self._token = str(token)

    async def _authed(self, method: str, endpoint: str, retries: int = 0, **kw: Any) -> httpx.Response:
        async with self._login_lock:
            if not self._token:
                await self.login()
        for attempt in (1, 2):
            headers = {**kw.pop("headers", {}), **self._auth_header()}
            resp = await self._send(method, self._url(endpoint), retries=retries, headers=headers, **kw)
            if resp.status_code != 401 or attempt == 2:
                return resp
            async with self._login_lock:  # token expirou: novo login e uma repetição
                await self.login()
        raise AssertionError("unreachable")

    async def fetch_options(self, spec: OptionsFrom) -> list[tuple[str, str]]:
        resp = await self._authed("GET", spec.endpoint, retries=2)
        if resp.status_code != 200:
            raise ApiError(f"Não consegui carregar as opções: {_error_message(resp)}", resp.status_code)
        items = resp.json()
        if isinstance(items, dict):  # aceita {"data": [...]} etc.
            items = next((v for v in items.values() if isinstance(v, list)), [])
        out = []
        for it in items:
            value = str(it.get(spec.value))
            if value not in spec.exclude:
                out.append((value, str(it.get(spec.label, value))))
        return out

    async def upload_image(self, data: bytes, filename: str, content_type: str) -> str:
        up = self.site.upload
        resp = await self._authed(
            "POST", up.endpoint, files={up.file_field: (filename, data, content_type)}
        )
        if resp.status_code != 200:
            raise ApiError(f"Upload da imagem falhou: {_error_message(resp)}", resp.status_code)
        path = _dig(resp.json(), up.response_path_field)
        if not path:
            raise ApiError("O upload não retornou o caminho da imagem.")
        return str(path)

    async def create_product(self, payload: dict[str, Any]) -> CreateResult:
        c = self.site.create
        resp = await self._authed("POST", c.endpoint, json=payload)
        if resp.status_code not in (200, 201):
            raise ApiError(f"Cadastro falhou: {_error_message(resp)}", resp.status_code)
        body = resp.json()
        if c.success_field and not _dig(body, c.success_field):
            raise ApiError(f"Cadastro falhou: {_error_message(resp)}")
        pid = _dig(body, c.id_field) if c.id_field else None
        return CreateResult(id=None if pid is None else str(pid), raw=body)
