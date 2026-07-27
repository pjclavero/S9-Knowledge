# -*- coding: utf-8 -*-
"""Adaptadores visuales: OCR, HTR, imagen y dibujo.

**Que es real aqui y que no.** El puerto (`VisualProvider`), las estructuras de
peticion y respuesta, el enrutado por region, la proyeccion a `SourceEpisode` /
`EvidenceFragment` con bbox y la separacion de tipos son codigo real y probado.
Lo que NO esta aqui es el reconocimiento en si: ejecutar OCR, HTR o un modelo
de vision corresponde al subsistema de proveedores. Sin proveedor inyectado,
estos adaptadores producen episodios **pendientes**
(`UNPROCESSED_PENDING_PROVIDER`, `score = 0.0`, sin texto y sin evidencia).

No hay ningun modo en que este modulo devuelva texto que no le haya dado un
proveedor. Un stub que devolviera texto plausible seria peor que no tener nada:
alimentaria el grafo con contenido inventado y trazado como si fuera leido.

Tres cosas distintas, tres tipos distintos (regla del dosier 7.6)
-----------------------------------------------------------------
========================  =====================  ===================
Que es                    `modality` (episodio)  `media_type` (evid.)
========================  =====================  ===================
Texto impreso reconocido  `OCR_TEXT`             `OCR_TEXT`
Manuscrito reconocido     `HTR_TEXT`             `HTR_TEXT`
Interpretacion visual     `IMAGE`                `IMAGE_DESCRIPTION`
Mapa interpretado         `MAP`                  `MAP`
Diagrama interpretado     `DIAGRAM`              `DIAGRAM`
========================  =====================  ===================

Una descripcion visual NUNCA se mezcla con OCR como si fuera texto literal: son
episodios distintos aunque cubran la misma region.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from .. import errors
from ..base import (
    STEP_EXTRACT,
    AdapterOutput,
    EpisodeDraft,
    FragmentDraft,
    IngestOptions,
    Provider,
    SourceAdapter,
    SourceInput,
    provider_step,
)
from ..quality import pending_quality, quality, text_quality

#: Paso de traza del proveedor de reconocimiento visual.
STEP_VISION = "vision"

#: Region por defecto: la imagen entera.
FULL_REGION_BBOX = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}

#: Modos de reconocimiento que puede pedir un adaptador visual.
MODE_OCR = "OCR"
MODE_HTR = "HTR"
MODE_DESCRIPTION = "DESCRIPTION"
MODE_MAP = "MAP"
MODE_DIAGRAM = "DIAGRAM"

#: Modo -> (modality del episodio, media_type de la evidencia).
MODE_TARGETS = {
    MODE_OCR: ("OCR_TEXT", "OCR_TEXT"),
    MODE_HTR: ("HTR_TEXT", "HTR_TEXT"),
    MODE_DESCRIPTION: ("IMAGE", "IMAGE_DESCRIPTION"),
    MODE_MAP: ("MAP", "MAP"),
    MODE_DIAGRAM: ("DIAGRAM", "DIAGRAM"),
}

#: Modos cuyo resultado es TEXTO LITERAL leido de la imagen. El resto son
#: interpretacion, y su texto va a `metadata.description`, nunca a `text` de un
#: episodio textual.
LITERAL_MODES = frozenset({MODE_OCR, MODE_HTR})


@dataclass(frozen=True)
class VisualRegion:
    """Region declarada de una imagen o pagina, en coordenadas normalizadas."""

    bbox: dict
    region_id: str = "full"
    page: Optional[int] = None
    frame_id: Optional[str] = None


@dataclass(frozen=True)
class VisualRequest:
    """Peticion de reconocimiento sobre una region concreta."""

    mode: str
    region: VisualRegion
    data: bytes
    mime_type: str
    language_hint: Optional[str] = None


@dataclass(frozen=True)
class VisualResult:
    """Respuesta de un proveedor visual.

    `text` solo se rellena en modos literales (OCR/HTR). `description` solo en
    modos de interpretacion. Un proveedor que rellene ambos esta mezclando
    lectura con interpretacion y el adaptador lo rechaza.
    """

    mode: str
    region_id: str
    confidence: float
    text: Optional[str] = None
    description: Optional[str] = None
    provider: str = "external"
    name: str = "unknown"
    version: str = "unknown"
    model: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VisualProvider(Protocol):
    """Puerto del subsistema de proveedores para reconocimiento visual.

    Contrato de la implementacion real:

    * devuelve un `VisualResult` por peticion, o `None` si no puede procesarla;
    * en modos literales rellena `text` y deja `description` a `None`;
    * en modos de interpretacion, al reves;
    * declara su `provider`/`name`/`version`/`model` reales: la traza los copia
      tal cual y de ahi sale la atribucion de procedencia.

    El adaptador NUNCA rellena estos huecos por su cuenta.
    """

    def recognize(self, request: VisualRequest) -> Optional[VisualResult]:
        ...


class NoVisualProvider:
    """Proveedor ausente: no reconoce nada y lo dice.

    Es el valor por defecto. Su existencia hace que la ruta "sin proveedor" sea
    un caso normal y probado, no una excepcion que revienta en produccion.
    """

    name = "none"
    version = "0"

    def recognize(self, request: VisualRequest) -> Optional[VisualResult]:
        return None


def _regions_from(source: SourceInput) -> list[VisualRegion]:
    payload = dict(source.payload or {})
    raw = payload.get("regions")
    if not raw:
        return [VisualRegion(bbox=dict(FULL_REGION_BBOX))]
    regions: list[VisualRegion] = []
    for index, item in enumerate(raw):
        bbox = item.get("bbox") if isinstance(item, dict) else None
        if not isinstance(bbox, dict):
            raise errors.NormalizationError(
                errors.MISSING_PAYLOAD,
                f"region {index} sin bbox: una region visual sin caja no esta anclada",
            )
        regions.append(
            VisualRegion(
                bbox=dict(bbox),
                region_id=str(item.get("region_id", f"r{index}")),
                page=item.get("page"),
                frame_id=item.get("frame_id"),
            )
        )
    return regions


def _pending_episode(mode: str, region: VisualRegion) -> EpisodeDraft:
    modality, media_type = MODE_TARGETS[mode]
    return EpisodeDraft(
        # Un episodio pendiente NO se declara con la modalidad textual que
        # tendria si se hubiera procesado: `OCR_TEXT` sin texto seria mentira
        # (y el contrato lo rechaza). Queda como IMAGE hasta que haya lectura.
        modality="IMAGE",
        text=None,
        page=region.page,
        bbox=region.bbox,
        quality=pending_quality(),
        metadata={
            "pending_reason": "NO_VISUAL_PROVIDER",
            "requested_mode": mode,
            "would_produce_modality": modality,
            "would_produce_media_type": media_type,
            "region_id": region.region_id,
        },
    )


def _episode_from_result(
    result: VisualResult, region: VisualRegion
) -> EpisodeDraft:
    modality, media_type = MODE_TARGETS[result.mode]
    literal = result.mode in LITERAL_MODES
    if literal and result.description:
        raise errors.NormalizationError(
            errors.MISSING_PAYLOAD,
            f"resultado {result.mode} con descripcion: OCR/HTR es lectura literal, "
            "no interpretacion; mezclarlos contamina la evidencia",
        )
    if not literal and result.text:
        raise errors.NormalizationError(
            errors.MISSING_PAYLOAD,
            f"resultado {result.mode} con texto literal: la interpretacion visual "
            "no produce texto literal de la imagen",
        )
    content = (result.text if literal else result.description) or ""
    if not content.strip():
        return _pending_episode(result.mode, region)

    confidence = max(0.0, min(1.0, float(result.confidence)))
    fragment = FragmentDraft(
        literal_text=content,
        start=0,
        end=len(content),
        media_type=media_type,
        confidence=confidence,
        bbox=region.bbox,
        page=region.page,
        frame_id=region.frame_id,
        produced_by=STEP_VISION,
    )
    if literal:
        episode_quality = text_quality(content)
        episode_quality["score"] = min(episode_quality["score"], confidence)
        return EpisodeDraft(
            modality=modality,
            text=content,
            page=region.page,
            bbox=region.bbox,
            quality=episode_quality,
            fragments=[fragment],
            produced_by=STEP_VISION,
            metadata={"region_id": region.region_id},
        )
    # Interpretacion visual: el texto describe, no cita. Va a metadata, y el
    # episodio NO se declara textual.
    return EpisodeDraft(
        modality=modality,
        text=None,
        page=region.page,
        bbox=region.bbox,
        quality=quality(confidence),
        fragments=[fragment],
        produced_by=STEP_VISION,
        metadata={"region_id": region.region_id, "description": content},
    )


class _BaseVisualAdapter(SourceAdapter):
    """Adaptador visual: declarado con interfaz real, stub sin proveedor."""

    #: Modos que pide este adaptador, en orden. OCR literal e interpretacion se
    #: piden por separado y producen episodios separados.
    modes: tuple[str, ...] = (MODE_OCR,)
    default_mime_type = "image/png"

    def __init__(self, provider: Optional[VisualProvider] = None) -> None:
        self.provider = provider or NoVisualProvider()

    def modes_for(self, source: SourceInput) -> tuple[str, ...]:
        """Modos a pedir para esta fuente concreta."""
        return self.modes

    @property
    def is_stub(self) -> bool:  # type: ignore[override]
        """True mientras no haya proveedor real detras. Se calcula, no se declara."""
        return isinstance(self.provider, NoVisualProvider)

    def _provider_step(self, results: Sequence[VisualResult]) -> dict:
        if not results:
            return provider_step(
                STEP_VISION,
                Provider.LOCAL,
                "visual_provider:none",
                "0",
                ["pending_regions"],
            )
        first = results[0]
        provider = {
            "local": Provider.LOCAL,
            "ollama": Provider.OLLAMA,
            "external": Provider.EXTERNAL,
        }.get(first.provider, Provider.EXTERNAL)
        return provider_step(
            STEP_VISION,
            provider,
            first.name,
            first.version,
            ["text", "description", "confidence"],
            model=first.model,
        )

    def extract(self, source: SourceInput, options: IngestOptions) -> AdapterOutput:
        if not source.data:
            raise errors.NormalizationError(
                errors.EMPTY_SOURCE, f"{source.original_name} sin contenido binario"
            )
        regions = _regions_from(source)
        mime = source.mime_type or self.default_mime_type
        modes = self.modes_for(source)
        episodes: list[EpisodeDraft] = []
        results: list[VisualResult] = []
        pending = 0
        for region in regions:
            for mode in modes:
                result = self.provider.recognize(
                    VisualRequest(
                        mode=mode,
                        region=region,
                        data=source.data,
                        mime_type=mime,
                        language_hint=options.language_hint,
                    )
                )
                if result is None:
                    episodes.append(_pending_episode(mode, region))
                    pending += 1
                    continue
                if result.mode != mode:
                    raise errors.NormalizationError(
                        errors.MISSING_PAYLOAD,
                        f"el proveedor respondio en modo {result.mode!r} a una "
                        f"peticion {mode!r}",
                    )
                results.append(result)
                episodes.append(_episode_from_result(result, region))
        return AdapterOutput(
            source_kind=source.source_kind
            if source.source_kind in self.source_kinds
            else self.source_kinds[0],
            mime_type=mime,
            episodes=episodes,
            trace_steps=[
                self._provider_step(results),
                self.local_step(["episodes", "bbox", "evidence_fragments"], step=STEP_EXTRACT),
            ],
            report={
                "visual_regions": len(regions),
                "visual_modes": list(modes),
                "visual_provider": type(self.provider).__name__,
                "visual_pending_requests": pending,
                "visual_implementation": "stub" if self.is_stub else "real",
            },
        )


class ImageAdapter(_BaseVisualAdapter):
    """`IMAGE` y `CHARACTER_SHEET`: OCR literal + interpretacion, por separado."""

    name = "knowledge_v3.multimodal.adapters.image"
    source_kinds = ("IMAGE", "CHARACTER_SHEET")
    mime_types = ("image/png", "image/jpeg", "image/webp", "image/tiff")
    extensions = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")
    modes = (MODE_OCR, MODE_DESCRIPTION)


class HandwritingAdapter(_BaseVisualAdapter):
    """`HANDWRITING`: HTR, que NO es OCR ni se mezcla con el."""

    name = "knowledge_v3.multimodal.adapters.handwriting"
    source_kinds = ("HANDWRITING",)
    mime_types = ()
    extensions = ()
    modes = (MODE_HTR,)


class DrawingAdapter(_BaseVisualAdapter):
    """`MAP` y `DIAGRAM`: dibujos interpretados, nunca leidos como texto.

    Los claims que salgan de aqui nacen `VISUAL_INFERRED` con
    `review_required = true` (dosier 7.6). Eso lo aplica el extractor sobre
    estos episodios; este adaptador se limita a no disfrazar interpretacion de
    lectura.
    """

    name = "knowledge_v3.multimodal.adapters.drawing"
    source_kinds = ("MAP", "DIAGRAM")
    mime_types = ("image/svg+xml",)
    extensions = (".svg",)
    modes = (MODE_DIAGRAM,)

    def modes_for(self, source: SourceInput) -> tuple[str, ...]:
        """Un mapa se interpreta como mapa, no como diagrama generico."""
        return (MODE_MAP,) if source.source_kind == "MAP" else self.modes
