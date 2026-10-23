"""Cliente da Evolution API (v2) para postar o anúncio no grupo do WhatsApp."""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from .config import WhatsAppConfig

log = logging.getLogger(__name__)

LIST_GROUPS_TIMEOUT = 180.0


class WhatsAppError(Exception):
    """Erro do gateway; a mensagem é segura para mostrar ao usuário."""


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict):
            msg = body.get("message") or body.get("error") or (body.get("response") or {}).get("message")
            if isinstance(msg, list):
                msg = "; ".join(str(m) for m in msg)
            if msg:
                return str(msg)
    except (ValueError, AttributeError):
        pass
    return f"HTTP {resp.status_code}"


class EvolutionClient:
    def __init__(self, cfg: WhatsAppConfig, http: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self._http = http or httpx.AsyncClient(timeout=cfg.timeout)
        self._owns_http = http is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _request(self, method: str, path: str, timeout: float | None = None, **kw: Any) -> Any:
        url = f"{self.cfg.base_url}/{path}/{self.cfg.instance}"
        try:  # sem retry: repetir um envio que talvez tenha chegado duplicaria o post no grupo
            resp = await self._http.request(method, url, headers={"apikey": self.cfg.api_key},
                                            timeout=timeout or httpx.USE_CLIENT_DEFAULT, **kw)
        except httpx.TimeoutException as e:  # instância sem QR code lido deixa a requisição pendurada
            log.warning("Timeout em %s %s: %s", method, url, e)
            raise WhatsAppError("O WhatsApp não respondeu a tempo. Confira se o número está conectado "
                                "(painel da Evolution API) e se o post já não chegou ao grupo.") from e
        except httpx.TransportError as e:
            log.warning("Falha de rede em %s %s: %s", method, url, e)
            raise WhatsAppError("Não consegui falar com o WhatsApp (gateway fora do ar?).") from e
        if resp.status_code not in (200, 201):
            raise WhatsAppError(f"WhatsApp: {_error_message(resp)}")
        try:
            return resp.json()
        except ValueError:
            return None

    async def send_image(self, group_id: str, data: bytes, mimetype: str, filename: str,
                         caption: str | None = None) -> None:
        body: dict[str, Any] = {
            "number": group_id, "mediatype": "image", "mimetype": mimetype, "fileName": filename,
            "media": base64.b64encode(data).decode(),
        }
        if caption:
            body["caption"] = caption
        await self._request("POST", "message/sendMedia", json=body)

    async def send_text(self, group_id: str, text: str) -> None:
        await self._request("POST", "message/sendText", json={"number": group_id, "text": text})

    async def list_groups(self) -> list[tuple[str, str]]:
        # número com muitos grupos (100+) leva ~40 s para listar: timeout maior que o dos envios
        groups = await self._request("GET", "group/fetchAllGroups", timeout=LIST_GROUPS_TIMEOUT,
                                     params={"getParticipants": "false"})
        return [(str(g["id"]), str(g.get("subject", ""))) for g in groups or [] if isinstance(g, dict) and "id" in g]
