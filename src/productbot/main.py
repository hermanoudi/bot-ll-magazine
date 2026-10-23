"""Ponto de entrada: python -m productbot.main"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from telegram.ext import Application

from . import conversation
from .api_client import SiteApiClient
from .config import ConfigError, load_config

log = logging.getLogger("productbot")


async def _post_init(app: Application) -> None:
    app.bot_data["clients"] = {}


async def _post_shutdown(app: Application) -> None:
    clients: dict[str, SiteApiClient] = app.bot_data.get("clients", {})
    for c in clients.values():
        await c.aclose()
    if wa := app.bot_data.get("wa"):
        await wa.aclose()


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # a URL do bot contém o token

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("Defina TELEGRAM_BOT_TOKEN.")
    try:
        config = load_config(os.environ.get("SITES_CONFIG", "sites.yaml"))
    except ConfigError as e:
        sys.exit(str(e))

    app = Application.builder().token(token).post_init(_post_init).post_shutdown(_post_shutdown).build()
    app.bot_data["config"] = config
    conversation.register(app)
    log.info("Bot iniciado com %d site(s): %s", len(config.sites), ", ".join(config.sites))
    app.run_polling()


if __name__ == "__main__":
    main()
