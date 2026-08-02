# -*- coding: utf-8 -*-
"""Renderiza imagenes SINTETICAS de bench a partir de texto gold conocido.

Bloque B1 (puerta 4): la fuente `ambar-escaneo` del split `negation` declara
`source_kind=IMAGE` pero sus episodios (`modality=OCR_TEXT`) ya traen el texto
gold, con ruido de OCR simulado a mano (`rniembro`, `e1`, `1as`...). El gold NO
guarda bytes de imagen real (`benchmarks.loader` nunca los tuvo: solo el
`SourceAsset` con `byte_size`/`content_hash`), asi que reconstruir la fuente
como bytes de imagen de verdad exige FABRICAR una imagen -- y la unica manera
de hacerlo sin inventar contenido es dibujar el texto que el propio gold ya
declara.

Esto es legitimo (y distinto de "inventar evidencia"): la imagen se genera a
partir del texto conocido, y el carril OCR tiene que RECUPERAR ese mismo texto
leyendo la imagen. Si el OCR devuelve algo distinto, la medicion lo dice: no
hay ningun atajo que copie el texto de un lado a otro sin pasar por el
reconocimiento real.

Cada episodio ocupa una banda horizontal propia, y su `bbox` (normalizado a la
imagen entera) es exactamente esa banda: es lo que permite que
`multimodal.adapters.visual._BaseVisualAdapter` recorte la region correcta
antes de mandarla al proveedor, igual que haria con una imagen real de varias
paginas o parrafos.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

#: Modalidades de episodio que este renderizador sabe dibujar como texto
#: literal. Cualquier otra (interpretacion visual, mapas...) no tiene un
#: "texto conocido" del que partir y queda fuera, a proposito.
RENDERABLE_MODALITIES = ("OCR_TEXT", "HTR_TEXT")

#: modalidad de episodio -> modo de reconocimiento que le correspondería.
_MODE_OF_MODALITY = {"OCR_TEXT": "OCR", "HTR_TEXT": "HTR"}

_BAND_HEIGHT_PX = 96
_MARGIN_PX = 16
_WIDTH_PX = 1700
_FONT_SIZE = 34


@dataclass(frozen=True)
class RenderedBand:
    """Una banda de la imagen compuesta, con su bbox normalizado."""

    region_id: str
    bbox: dict
    mode: str
    page: "int | None"


def _font() -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", _FONT_SIZE)
    except OSError:  # pragma: no cover - depende de fuentes del sistema
        return ImageFont.load_default(size=_FONT_SIZE)


def renderable(episodes: Sequence[dict]) -> bool:
    """True si TODOS los episodios traen texto y una modalidad dibujable.

    Todo o nada: una fuente con episodios mixtos (algunos con texto conocido,
    otros de interpretacion visual) no es el caso que este bloque ataca, y
    forzarla a medias produciria una imagen que no representa la fuente.
    """
    return bool(episodes) and all(
        (e.get("text") or "").strip() and e.get("modality") in RENDERABLE_MODALITIES
        for e in episodes
    )


def render_source_image(
    episodes: Sequence[dict],
) -> tuple[bytes, list[dict]]:
    """PNG (una banda horizontal por episodio) + las regiones que lo describen.

    Las regiones devueltas tienen la misma forma que las que ya consume
    `reconstruct_bytes`/`multimodal.adapters.visual._regions_from`
    (`region_id`, `bbox`, `mode`, `page`), asi que el llamante no necesita
    saber si la imagen es sintetica o reconstruida a la vieja usanza.
    """
    if not renderable(episodes):
        raise ValueError(
            "render_source_image exige que TODOS los episodios tengan texto y "
            f"modalidad en {RENDERABLE_MODALITIES}"
        )
    height = _BAND_HEIGHT_PX * len(episodes)
    image = Image.new("L", (_WIDTH_PX, height), 255)
    draw = ImageDraw.Draw(image)
    font = _font()
    regions: list[dict] = []
    for index, episode in enumerate(episodes):
        top = index * _BAND_HEIGHT_PX
        draw.text(
            (_MARGIN_PX, top + _MARGIN_PX),
            str(episode["text"]),
            font=font,
            fill=0,
        )
        mode = _MODE_OF_MODALITY[episode["modality"]]
        regions.append(
            {
                "region_id": str(episode.get("episode_id", f"r{index}")),
                "bbox": {
                    "x": 0.0,
                    "y": index / len(episodes),
                    "width": 1.0,
                    "height": 1.0 / len(episodes),
                },
                "mode": mode,
                "page": episode.get("page"),
            }
        )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), regions


__all__ = ["RENDERABLE_MODALITIES", "render_source_image", "renderable"]
