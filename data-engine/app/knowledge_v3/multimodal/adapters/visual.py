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
from ..quality import (
    LOW_CONFIDENCE_THRESHOLD,
    LOW_PROVIDER_CONFIDENCE,
    check_provider_confidence,
    pending_quality,
    quality,
    text_quality,
)

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
class VisualTextSpan:
    """Literal OCR/HTR anchored both in result text and image coordinates."""

    text: str
    start: int
    end: int
    bbox: dict
    confidence: float


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
    spans: tuple[VisualTextSpan, ...] = ()
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


def _pending_episode(
    mode: str,
    region: VisualRegion,
    *,
    pending_reason: str = "NO_VISUAL_PROVIDER",
    metadata: Optional[dict[str, Any]] = None,
) -> EpisodeDraft:
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
            "pending_reason": pending_reason,
            "requested_mode": mode,
            "would_produce_modality": modality,
            "would_produce_media_type": media_type,
            "region_id": region.region_id,
            **(metadata or {}),
        },
    )


def _source_labels(source: SourceInput) -> dict[str, str]:
    payload = dict(source.payload or {})
    labels = {
        "source_file": source.original_name,
        "ingested_by": str(payload.get("ingested_by") or ""),
    }
    for key in ("author_hint", "perspective_hint", "session_id", "in_game_date"):
        value = payload.get(key)
        if value not in (None, ""):
            labels[key] = str(value)
    return labels


def _valid_bbox(bbox: Any) -> bool:
    if not isinstance(bbox, dict):
        return False
    try:
        x = float(bbox["x"])
        y = float(bbox["y"])
        width = float(bbox["width"])
        height = float(bbox["height"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        0.0 <= x <= 1.0
        and 0.0 <= y <= 1.0
        and 0.0 < width <= 1.0
        and 0.0 < height <= 1.0
        and x + width <= 1.0 + 1e-9
        and y + height <= 1.0 + 1e-9
    )


def _literal_fragments(
    result: VisualResult,
    region: VisualRegion,
    content: str,
    media_type: str,
) -> list[FragmentDraft]:
    if not result.spans:
        return [
            FragmentDraft(
                literal_text=content,
                start=0,
                end=len(content),
                media_type=media_type,
                confidence=result.confidence,
                bbox=region.bbox,
                page=region.page,
                frame_id=region.frame_id,
                produced_by=STEP_VISION,
            )
        ]
    fragments: list[FragmentDraft] = []
    previous_end = 0
    for index, span in enumerate(result.spans):
        if (
            span.start < previous_end
            or span.end <= span.start
            or span.end > len(content)
            or content[span.start:span.end] != span.text
        ):
            raise errors.NormalizationError(
                errors.ANCHOR_MISMATCH,
                f"span OCR {index} no coincide con los offsets del texto reconocido",
            )
        if not _valid_bbox(span.bbox):
            raise errors.NormalizationError(
                errors.ANCHOR_MISMATCH,
                f"span OCR {index} con bbox fuera de los limites de la imagen",
            )
        confidence = check_provider_confidence(
            span.confidence,
            where=f"span OCR {index} de {result.name!r}",
        )
        fragments.append(
            FragmentDraft(
                literal_text=span.text,
                start=span.start,
                end=span.end,
                media_type=media_type,
                confidence=confidence,
                bbox=dict(span.bbox),
                page=region.page,
                frame_id=region.frame_id,
                produced_by=STEP_VISION,
                metadata={"anchor": "text+bbox", "region_id": region.region_id},
            )
        )
        previous_end = span.end
    return fragments


def _transcription_fragments(
    result: VisualResult,
    content: str,
    media_type: str,
    region: VisualRegion,
) -> list[FragmentDraft]:
    """Proyecta offsets textuales de HTR sin inventar cajas de imagen."""
    records = result.metadata.get("transcription_spans")
    if not isinstance(records, list):
        return _literal_fragments(result, region, content, media_type)
    fragments: list[FragmentDraft] = []
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            raise errors.NormalizationError(
                errors.ANCHOR_MISMATCH,
                f"tramo de transcripcion {index} no es un objeto",
            )
        start, end = item.get("start"), item.get("end")
        literal = item.get("text")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not isinstance(literal, str)
            or start < 0
            or end <= start
            or content[start:end] != literal
        ):
            raise errors.NormalizationError(
                errors.ANCHOR_MISMATCH,
                f"tramo de transcripcion {index} no coincide con sus offsets",
            )
        fragments.append(
            FragmentDraft(
                literal_text=literal,
                start=start,
                end=end,
                media_type=media_type,
                confidence=check_provider_confidence(
                    item.get("confidence", result.confidence),
                    where=f"tramo de transcripcion {index}",
                ),
                bbox=None,
                page=region.page,
                frame_id=region.frame_id,
                produced_by=STEP_VISION,
                metadata={
                    "anchor": "transcription_offsets",
                    "lane": "TRANSCRIBED_TEXT",
                    "review_required": bool(item.get("review_required")),
                    "reason_codes": list(item.get("reason_codes") or []),
                    "line": item.get("line"),
                    "region_id": region.region_id,
                },
            )
        )
    return fragments


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
    confidence = check_provider_confidence(
        result.confidence, where=f"resultado visual {result.mode} de {result.name!r}"
    )
    content = (result.text if literal else result.description) or ""
    if not content.strip():
        return _pending_episode(
            result.mode,
            region,
            pending_reason=str(result.metadata.get("diagnostic") or "NO_CONTENT_DETECTED"),
            metadata=dict(result.metadata),
        )
    low = confidence < LOW_CONFIDENCE_THRESHOLD

    if literal:
        # OCR/HTR: el texto ES el contenido del episodio, y los offsets son
        # offsets de texto de verdad.
        fragments = (
            _transcription_fragments(result, content, media_type, region)
            if result.mode == MODE_HTR
            else _literal_fragments(result, region, content, media_type)
        )
        episode_quality = text_quality(content)
        episode_quality["score"] = min(episode_quality["score"], confidence)
        if low:
            episode_quality["flags"] = sorted(
                set(episode_quality["flags"]) | {LOW_PROVIDER_CONFIDENCE}
            )
        return EpisodeDraft(
            modality=modality,
            text=content,
            page=region.page,
            bbox=region.bbox,
            quality=episode_quality,
            fragments=fragments,
            produced_by=STEP_VISION,
            metadata={"region_id": region.region_id, **dict(result.metadata)},
        )

    # Interpretacion visual: el texto describe, no cita. Va a metadata y el
    # episodio NO se declara textual (`text=None`).
    #
    # Convencion de offsets (documentada en docs/v3/02-multimodal.md): el
    # contrato exige `start` y `end`, no admite omitirlos. En un fragmento
    # anclado por BBOX no existe texto de episodio contra el que medir, asi que
    # ambos valen 0 — un tramo vacio — y `metadata.anchor = "bbox"` dice cual es
    # el anclaje real. Poner `end = len(descripcion)` habria fabricado offsets
    # que parecen de texto y no recortan nada de ningun sitio.
    fragment = FragmentDraft(
        literal_text=content,
        start=0,
        end=0,
        media_type=media_type,
        confidence=confidence,
        bbox=region.bbox,
        page=region.page,
        frame_id=region.frame_id,
        produced_by=STEP_VISION,
        metadata={"anchor": "bbox", "region_id": region.region_id},
    )
    return EpisodeDraft(
        modality=modality,
        text=None,
        page=region.page,
        bbox=region.bbox,
        quality=quality(confidence, [LOW_PROVIDER_CONFIDENCE] if low else []),
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

    def _check_external_allowed(self, provider_kind: str, options: IngestOptions) -> None:
        """`processing_policy.allow_external_providers` se APLICA, no se declara.

        El contrato dice que si la politica es `false`, ningun `provider_trace`
        de la cadena derivada puede llevar `provider='external'`. Sin esta
        comprobacion, inyectar un proveedor remoto producia un asset que se
        contradecia a si mismo: politica `false` y traza `external` en el mismo
        documento, ambos validos por separado.
        """
        if provider_kind == "external" and not options.allow_external_providers:
            raise errors.NormalizationError(
                errors.EXTERNAL_PROVIDER_NOT_ALLOWED,
                "proveedor visual externo con allow_external_providers=false: "
                "la politica del asset prohibe exponer este material a un "
                "proveedor remoto, y la traza no puede decir lo contrario",
            )

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
        # La politica debe validarse antes de invocar al proveedor. Hacerlo solo
        # en `assemble()` detectaria la incoherencia, pero ya habria expuesto la
        # imagen privada.
        options.processing_policy()
        # Comprobacion PREVIA: si el proveedor declara su clase por adelantado
        # (`provider_kind`) y la politica no la admite, no se le llega a mandar
        # el material. Rechazar solo el resultado ya habria expuesto los bytes.
        self._check_external_allowed(
            str(getattr(self.provider, "provider_kind", "") or ""), options
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
                    pending_episode = _pending_episode(mode, region)
                    if mode == MODE_HTR:
                        pending_episode.metadata = {
                            **(pending_episode.metadata or {}),
                            **_source_labels(source),
                        }
                    episodes.append(pending_episode)
                    pending += 1
                    continue
                if result.mode != mode:
                    raise errors.NormalizationError(
                        errors.MISSING_PAYLOAD,
                        f"el proveedor respondio en modo {result.mode!r} a una "
                        f"peticion {mode!r}",
                    )
                # Comprobacion POSTERIOR: el proveedor puede no haber declarado
                # su clase por adelantado, pero el resultado siempre la lleva.
                self._check_external_allowed(result.provider, options)
                results.append(result)
                episode = _episode_from_result(result, region)
                if mode == MODE_HTR:
                    episode.metadata = {
                        **(episode.metadata or {}),
                        **_source_labels(source),
                    }
                episodes.append(episode)
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
                **(
                    {
                        "transcription_metrics": self.provider.metrics.snapshot()
                    }
                    if hasattr(self.provider, "metrics")
                    else {}
                ),
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
