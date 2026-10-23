"""Conecta o número à instância da Evolution API com um QR code grande (PNG) ou código de pareamento.

Uso (na pasta do projeto, com a Evolution API no ar):
    uv run python scripts/whatsapp_qr.py            # abre o QR code ampliado
    uv run python scripts/whatsapp_qr.py --phone    # código de 8 caracteres, sem câmera
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image, ImageOps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", action="store_true",
                    help="gera o código de pareamento (WhatsApp > Aparelhos conectados > Conectar com número de telefone)")
    ap.add_argument("--scale", type=int, default=4, help="ampliação do QR code (padrão 4x)")
    args = ap.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    base = os.environ.get("EVOLUTION_URL", "http://localhost:8080").rstrip("/")
    instance, key = os.environ.get("EVOLUTION_INSTANCE"), os.environ.get("EVOLUTION_API_KEY")
    if not instance or not key:
        sys.exit("Defina EVOLUTION_INSTANCE e EVOLUTION_API_KEY no .env.")

    params = {}
    if args.phone:
        phone = os.environ.get("LLMAGAZINE_WHATSAPP", "")
        if not phone:
            sys.exit("Defina LLMAGAZINE_WHATSAPP (DDI+DDD+número) no .env.")
        params["number"] = phone
    resp = httpx.get(f"{base}/instance/connect/{instance}", params=params, headers={"apikey": key}, timeout=60)
    if resp.status_code != 200:
        sys.exit(f"Evolution API respondeu HTTP {resp.status_code}: {resp.text[:200]}")
    body = resp.json()

    if args.phone:
        code = body.get("pairingCode")
        if not code:
            sys.exit(f"Sem código de pareamento na resposta: {list(body)}")
        print(f"Código: {code}\nNo celular: WhatsApp > Aparelhos conectados > Conectar com número de telefone.")
        return

    b64 = body.get("base64")
    if not b64:
        sys.exit(f"Sem QR code na resposta (já conectado?): {body}")
    img = Image.open(io.BytesIO(base64.b64decode(b64.split(",", 1)[-1]))).convert("L")
    img = ImageOps.expand(img.resize((img.width * args.scale, img.height * args.scale), Image.NEAREST),
                          border=40 * args.scale // 2, fill=255)  # margem branca ("quiet zone")
    out = Path(tempfile.gettempdir()) / "whatsapp_qr.png"
    img.save(out)
    print(f"QR code salvo em {out} ({img.width}x{img.height}). Ele expira em ~1 minuto: escaneie logo.")
    try:
        subprocess.Popen(["xdg-open", str(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


if __name__ == "__main__":
    main()
