"""Valida a imagem contra ImageRules do site e, quando permitido, corrige (converte/comprime)."""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import ImageRules

_EXT = {"jpeg": "jpg", "png": "png", "webp": "webp", "gif": "gif", "avif": "avif"}
_MIME = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif", "avif": "image/avif"}


class ImageRejected(Exception):
    """Imagem fora do padrão e sem correção possível; a mensagem é mostrada ao usuário."""


@dataclass
class ValidatedImage:
    data: bytes
    filename: str
    content_type: str
    format: str
    width: int
    height: int
    notes: list[str] = field(default_factory=list)


def _norm_format(fmt: str | None) -> str:
    f = (fmt or "").lower()
    return "jpeg" if f == "jpg" else f


def _encode(img: Image.Image, fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    if fmt == "jpeg":
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.getchannel("A"))
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, "JPEG", quality=quality, optimize=True)
    else:
        img.save(buf, fmt.upper(), quality=quality)
    return buf.getvalue()


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f}MB"


def validate_image(data: bytes, filename: str, rules: ImageRules) -> ValidatedImage:
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise ImageRejected("Não consegui abrir o arquivo como imagem. Envie uma foto JPG, PNG ou WEBP.") from None

    fmt = _norm_format(img.format)
    img = ImageOps.exif_transpose(img)
    w, h = img.size
    notes: list[str] = []
    allowed = [_norm_format(f) for f in rules.allowed_formats]

    if w < rules.min_width or h < rules.min_height:
        raise ImageRejected(
            f"Imagem muito pequena ({w}x{h}). O mínimo é {rules.min_width}x{rules.min_height}px."
        )

    out = data
    if fmt not in allowed:
        target = _norm_format(rules.auto_convert_to)
        if not target or target not in allowed:
            raise ImageRejected(
                f"Formato {fmt.upper() or 'desconhecido'} não aceito. Formatos aceitos: "
                f"{', '.join(f.upper() for f in allowed)}."
            )
        out = _encode(img, target, 90)
        notes.append(f"convertida de {fmt.upper()} para {target.upper()}")
        fmt = target

    if len(out) > rules.max_bytes:
        if not rules.auto_compress:
            raise ImageRejected(
                f"Imagem com {_mb(len(out))}; o máximo é {_mb(rules.max_bytes)}. Envie uma menor."
            )
        target = next((f for f in ("jpeg", "webp") if f in allowed), None)
        if not target:
            raise ImageRejected(f"Imagem com {_mb(len(out))}; o máximo é {_mb(rules.max_bytes)}.")
        original_size = len(out)
        work = img
        done = False
        while not done:
            for q in (88, 78, 68, 58):
                out = _encode(work, target, q)
                if len(out) <= rules.max_bytes:
                    done = True
                    break
            if done:
                break
            nw, nh = int(work.width * 0.85), int(work.height * 0.85)
            if nw < rules.min_width or nh < rules.min_height:
                raise ImageRejected(
                    f"Não consegui reduzir a imagem para {_mb(rules.max_bytes)} sem ficar abaixo "
                    f"de {rules.min_width}x{rules.min_height}px."
                )
            work = work.resize((nw, nh), Image.LANCZOS)
        fmt = target
        w, h = work.size
        notes.append(f"comprimida de {_mb(original_size)} para {_mb(len(out))}")

    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return ValidatedImage(
        data=out,
        filename=f"{stem or 'produto'}.{_EXT.get(fmt, fmt)}",
        content_type=_MIME.get(fmt, "application/octet-stream"),
        format=fmt,
        width=w,
        height=h,
        notes=notes,
    )
