# -*- coding: utf-8 -*-
"""Extractor VISUAL: interfaz + stub honesto.

**No hay extraccion visual en esta entrega.** No existe proveedor de vision
enganchado, asi que este modulo no produce ni una sola propuesta: emite el
diagnostico `VISION_PROVIDER_NOT_AVAILABLE` y devuelve vacio.

Lo que si deja hecho, para que el dia que llegue el proveedor no se cuele nada:

- el puerto `VisionPort` con la misma forma que el externo (una operacion,
  fail-closed, el transporte fuera);
- la regla de nacimiento de lo visual ya implementada y probada: cualquier claim
  inferido de una imagen, dibujo, mapa o diagrama nace con
  `epistemic_status_hint = VISUAL_INFERRED` y, por contrato, con
  `review_required = True` (dosier 7.6). Lo que se deduce de un dibujo no es lo
  mismo que lo que dice un texto, y el sistema no puede tratarlo igual;
- la separacion OCR / HTR / descripcion visual: si un dia el proveedor devuelve
  texto reconocido, eso NO es una inferencia visual y no debe pasar por aqui,
  sino por el extractor de texto sobre un episodio `OCR_TEXT`/`HTR_TEXT`.

Un stub que devolviese menciones plausibles seria mucho peor que uno vacio: el
benchmark las mediria como si fueran extraccion real.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from ..contracts import Provider, SourceEpisode
from .base import (
    Diagnostic,
    ExtractionContext,
    ExtractionOutput,
    Extractor,
    ExtractorInfo,
    emit,
)
from .external import ExternalExtractionRequest, ExternalExtractionResponse
from .payload import PayloadError, check_payload_shape, normalize_payload

VISUAL_STEP = "extract.visual"

#: Estatus epistemico obligatorio de todo lo inferido de una imagen.
VISUAL_EPISTEMIC_HINT = "VISUAL_INFERRED"

#: Confianza maxima de una inferencia visual. Muy baja a proposito: hoy no hay
#: nada que la respalde, y cuando lo haya sera el benchmark quien la mueva.
VISUAL_CONFIDENCE_CAP = 0.5

#: Modalidades que le tocarian a un extractor visual.
VISUAL_MODALITIES = ("IMAGE", "DIAGRAM", "MAP", "VIDEO_FRAME")


@runtime_checkable
class VisionPort(Protocol):
    """Puerto hacia un proveedor de vision. No implementado en esta entrega."""

    def describe(self, request: ExternalExtractionRequest) -> ExternalExtractionResponse:
        ...


class VisualExtractor(Extractor):
    """Interfaz completa; sin proveedor, salida vacia y diagnostico explicito."""

    info = ExtractorInfo(
        step=VISUAL_STEP,
        provider=Provider.LOCAL,
        name="s9k.extraction.visual",
    )

    def __init__(self, port: Optional[VisionPort] = None) -> None:
        self.port = port

    @property
    def bound(self) -> bool:
        return self.port is not None

    def supports(self, episode: SourceEpisode) -> bool:
        return episode.modality in VISUAL_MODALITIES

    def extract_episode(
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        prior: Optional[ExtractionOutput] = None,
    ) -> ExtractionOutput:
        out = ExtractionOutput()
        index = ctx.index_of(episode)
        if self.port is None:
            out.diagnostics.append(
                Diagnostic(
                    "VISION_PROVIDER_NOT_AVAILABLE", self.info.step, episode.episode_id,
                    "VISUAL_INFERRED queda pendiente de un proveedor de vision; "
                    "este extractor no inventa descripciones",
                )
            )
            return out
        info = ExtractorInfo(
            step=VISUAL_STEP,
            provider=Provider.EXTERNAL,
            name="s9k.extraction.visual.provider",
        )
        request = ExternalExtractionRequest.from_episode(ctx, episode, index)
        try:
            response = self.port.describe(request)
            check_payload_shape(response.payload)
        except PayloadError as exc:
            out.diagnostics.append(
                Diagnostic("VISION_PAYLOAD_MALFORMED", info.step, episode.episode_id, str(exc))
            )
            return out
        except Exception as exc:
            out.diagnostics.append(
                Diagnostic(
                    "VISION_PROVIDER_FAILED", info.step, episode.episode_id, type(exc).__name__
                )
            )
            return out
        return out.extend(
            normalize_payload(
                response.payload,
                ctx=ctx,
                episode=episode,
                info=info,
                confidence_cap=VISUAL_CONFIDENCE_CAP,
                force_review=True,
                # Lo inferido de una imagen NO puede declararse ASSERTED aunque
                # el proveedor lo diga: se fuerza aqui, no se pide por favor.
                epistemic_override=VISUAL_EPISTEMIC_HINT,
            )
        )


__all__ = [
    "VISUAL_CONFIDENCE_CAP",
    "VISUAL_EPISTEMIC_HINT",
    "VISUAL_MODALITIES",
    "VISUAL_STEP",
    "VisionPort",
    "VisualExtractor",
]
