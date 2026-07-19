"""Contrato interno común para extracción multimedia (ASR / OCR / visión).

Este módulo define `MultimediaArtifact`, el contrato interno común
`multimedia-artifact/internal-v1` que unifica los resultados de:

- **Texto embebido** (extraído directamente del PDF/documento, sin OCR).
- **ASR** (transcripción de audio; compatible con
  `media.transcriber` / `media.models.TranscriptResult`, NO lo duplica).
- **OCR** (texto reconocido ópticamente sobre una región de imagen).
- **Comprensión visual** (descripción semántica de una imagen por un modelo
  visual: mapas, diagramas, retratos, escenas...).

IMPORTANTE — separación OCR vs comprensión visual:
    `OCR_TEXT` es *texto reconocido* carácter a carácter sobre la imagen.
    `IMAGE_DESCRIPTION` es *interpretación semántica* de lo que muestra la
    imagen. Son tipos DISTINTOS y NO se mezclan: una misma región puede
    generar ambos artefactos, pero cada uno es un `MultimediaArtifact`
    independiente con su propio `media_type`.

Solo stdlib (dataclasses + enum). No descarga modelos, no ejecuta OCR real,
no importa dependencias de visión. Este contrato solo describe y valida datos.

Compatibilidad con el pipeline ASR existente:
    `MultimediaArtifact.from_transcript_result()` proyecta un
    `media.models.TranscriptResult` (producido por `media.transcriber`) a un
    artefacto `ASR_TEXT`, sin reimplementar la transcripción.

Sistema de coordenadas del bounding box:
    Coordenadas NORMALIZADAS en el rango [0, 1] relativas a la página/imagen.
    Origen (0, 0) en la ESQUINA SUPERIOR IZQUIERDA; x crece hacia la derecha,
    y crece hacia abajo. Un `BoundingBox(x, y, width, height)` describe el
    rectángulo [x, x+width] x [y, y+height]. Ver `BoundingBox`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

# ── Versión del contrato ──────────────────────────────────────────────────────
CONTRACT_ID = "multimedia-artifact/internal-v1"

# Orientaciones válidas (grados de rotación de la región respecto a la página).
VALID_ORIENTATIONS = frozenset({0, 90, 180, 270})

# Umbral por defecto por debajo del cual se recomienda revisión humana.
LOW_CONFIDENCE_THRESHOLD = 0.50


class MediaType(str, Enum):
    """Tipo de artefacto multimedia extraído.

    OCR_TEXT (texto reconocido) e IMAGE_DESCRIPTION (comprensión visual) son
    tipos deliberadamente separados: NO deben mezclarse en un mismo artefacto.
    """

    EMBEDDED_TEXT = "EMBEDDED_TEXT"          # texto nativo del documento (sin OCR)
    ASR_TEXT = "ASR_TEXT"                    # transcripción de audio (faster-whisper/stub)
    OCR_TEXT = "OCR_TEXT"                    # texto reconocido ópticamente sobre imagen
    IMAGE_DESCRIPTION = "IMAGE_DESCRIPTION"  # comprensión visual (descripción semántica)
    TABLE = "TABLE"                          # tabla estructurada (structured_data)
    MAP = "MAP"                              # mapa (subtipo de comprensión visual)
    DIAGRAM = "DIAGRAM"                      # diagrama/esquema
    CHARACTER_SHEET = "CHARACTER_SHEET"      # hoja de personaje (ficha estructurada)
    CAPTION = "CAPTION"                      # pie de figura / leyenda
    UNKNOWN_VISUAL = "UNKNOWN_VISUAL"        # visual no clasificado (fallback)


# Tipos que EXIGEN el campo `text` no vacío.
_TEXT_REQUIRED = frozenset({MediaType.EMBEDDED_TEXT, MediaType.OCR_TEXT})
# Tipos que EXIGEN el campo `description`.
_DESCRIPTION_REQUIRED = frozenset({MediaType.IMAGE_DESCRIPTION})
# Tipos que EXIGEN `structured_data`.
_STRUCTURED_REQUIRED = frozenset({MediaType.TABLE})


class ContractValidationError(ValueError):
    """Error de validación del contrato multimedia."""


@dataclass(frozen=True)
class BoundingBox:
    """Rectángulo NORMALIZADO en [0, 1] sobre la página/imagen.

    Sistema de coordenadas:
        - Origen (0, 0) en la esquina SUPERIOR IZQUIERDA.
        - x crece hacia la derecha; y crece hacia abajo.
        - Todos los valores son fracciones del ancho/alto de la página.
        - El rectángulo cubre [x, x+width] en horizontal y [y, y+height]
          en vertical.

    Reglas de validez (ver `validate`):
        width > 0, height > 0,
        0 <= x, 0 <= y,
        x + width <= 1, y + height <= 1.
    """

    x: float
    y: float
    width: float
    height: float

    def validate(self) -> list[str]:
        """Devuelve lista de errores (vacía si la caja es válida)."""
        errors: list[str] = []
        for name, value in (
            ("x", self.x), ("y", self.y),
            ("width", self.width), ("height", self.height),
        ):
            if not isinstance(value, (int, float)):
                errors.append(f"bounding_box.{name} no es numérico: {value!r}")
        if errors:
            return errors
        if self.width <= 0:
            errors.append(f"bounding_box.width debe ser > 0 (es {self.width})")
        if self.height <= 0:
            errors.append(f"bounding_box.height debe ser > 0 (es {self.height})")
        if self.x < 0:
            errors.append(f"bounding_box.x debe ser >= 0 (es {self.x})")
        if self.y < 0:
            errors.append(f"bounding_box.y debe ser >= 0 (es {self.y})")
        if self.x + self.width > 1 + 1e-9:
            errors.append(
                f"bounding_box fuera de página: x+width={self.x + self.width} > 1"
            )
        if self.y + self.height > 1 + 1e-9:
            errors.append(
                f"bounding_box fuera de página: y+height={self.y + self.height} > 1"
            )
        return errors

    def is_valid(self) -> bool:
        return not self.validate()

    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def intersection_area(self, other: "BoundingBox") -> float:
        """Área de solape con otra caja (0 si no se solapan)."""
        ix = max(self.x, other.x)
        iy = max(self.y, other.y)
        ix2 = min(self.x + self.width, other.x + other.width)
        iy2 = min(self.y + self.height, other.y + other.height)
        if ix2 <= ix or iy2 <= iy:
            return 0.0
        return (ix2 - ix) * (iy2 - iy)

    def overlaps(self, other: "BoundingBox", min_iou: float = 0.0) -> bool:
        """True si hay solape. Con `min_iou`>0, exige IoU por encima del umbral."""
        inter = self.intersection_area(other)
        if inter <= 0:
            return False
        if min_iou <= 0:
            return True
        union = self.area() + other.area() - inter
        if union <= 0:
            return False
        return (inter / union) >= min_iou

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BoundingBox":
        return cls(
            x=data["x"], y=data["y"],
            width=data["width"], height=data["height"],
        )


@dataclass
class MultimediaArtifact:
    """Artefacto interno común `multimedia-artifact/internal-v1`.

    Un artefacto describe UNA unidad de contenido extraído (una región de
    página, un segmento de audio, una imagen) de forma revisable, antes de
    cualquier ingesta en el grafo.

    Campos:
        source_id: ID estable de la fuente (p. ej. media/documento).
        file_hash: hash del contenido de la fuente (procedencia).
        page: número de página (1-based) o None si no aplica (audio).
        region_id: ID de la región dentro de la página/fuente.
        bounding_box: caja normalizada [0,1] (None para audio/documento entero).
        media_type: uno de MediaType.
        extraction_method: cómo se obtuvo (p. ej. "pdf_text", "faster-whisper",
            "ocr:stub", "vision:stub"). Cadena libre trazable.
        model: identificador del modelo usado (o "" / "n/a").
        confidence: confianza en [0, 1] o None si no aplica.
        language: código ISO 639-1 (p. ej. "es") o "".
        orientation: rotación de la región en {0, 90, 180, 270}.
        text: texto reconocido/embebido/transcrito (según tipo).
        description: descripción semántica (comprensión visual).
        structured_data: datos estructurados (tablas, fichas).
        parent_region: region_id del padre (jerarquía de regiones).
        provenance: metadatos mínimos de procedencia (ver validate()).
        warnings: avisos no bloqueantes (solapes, baja confianza...).
    """

    source_id: str
    file_hash: str
    media_type: MediaType
    extraction_method: str = ""
    model: str = ""
    page: int | None = None
    region_id: str = ""
    bounding_box: BoundingBox | None = None
    confidence: float | None = None
    language: str = ""
    orientation: int = 0
    text: str = ""
    description: str = ""
    structured_data: dict | None = None
    parent_region: str | None = None
    provenance: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    contract: str = CONTRACT_ID

    # ── Validación ────────────────────────────────────────────────────────────
    def validate(self, *, strict: bool = True) -> list[str]:
        """Valida el artefacto.

        Devuelve la lista de errores encontrados. Los avisos no bloqueantes
        (baja confianza, solape) se acumulan en `self.warnings`, NO en errores.

        Args:
            strict: si True (por defecto), un `media_type` no perteneciente a
                MediaType es un error. Si False, se degrada a UNKNOWN_VISUAL
                (política documentada de fallback).
        """
        errors: list[str] = []

        # media_type conocido
        mt = self.media_type
        if not isinstance(mt, MediaType):
            try:
                mt = MediaType(mt)
                self.media_type = mt
            except ValueError:
                if strict:
                    errors.append(f"media_type desconocido: {self.media_type!r}")
                else:
                    self.media_type = MediaType.UNKNOWN_VISUAL
                    self.warnings.append(
                        f"media_type desconocido {self.media_type!r} degradado a UNKNOWN_VISUAL"
                    )
                    mt = MediaType.UNKNOWN_VISUAL

        # provenance mínima: source_id y file_hash
        if not self.source_id:
            errors.append("provenance: source_id ausente")
        if not self.file_hash:
            errors.append("provenance: file_hash ausente")
        prov = self.provenance if isinstance(self.provenance, dict) else {}
        for key in ("source_id", "file_hash"):
            expected = getattr(self, key)
            if key in prov and expected and prov[key] != expected:
                errors.append(
                    f"provenance.{key} ({prov[key]!r}) no coincide con {key} ({expected!r})"
                )

        # bounding_box válida y dentro de página (si existe)
        if self.bounding_box is not None:
            if not isinstance(self.bounding_box, BoundingBox):
                errors.append("bounding_box no es BoundingBox")
            else:
                errors.extend(self.bounding_box.validate())

        # confidence en [0, 1]
        if self.confidence is not None:
            if not isinstance(self.confidence, (int, float)):
                errors.append(f"confidence no numérica: {self.confidence!r}")
            elif not (0.0 <= self.confidence <= 1.0):
                errors.append(f"confidence fuera de [0,1]: {self.confidence}")

        # orientation en {0, 90, 180, 270}
        if self.orientation not in VALID_ORIENTATIONS:
            errors.append(
                f"orientation inválida: {self.orientation} (permitidas {sorted(VALID_ORIENTATIONS)})"
            )

        # Requisitos por tipo
        if isinstance(mt, MediaType):
            if mt in _TEXT_REQUIRED and not (self.text or "").strip():
                errors.append(f"{mt.value} exige 'text' no vacío")
            if mt in _DESCRIPTION_REQUIRED and not (self.description or "").strip():
                errors.append(f"{mt.value} exige 'description' no vacía")
            if mt in _STRUCTURED_REQUIRED and not self.structured_data:
                errors.append(f"{mt.value} exige 'structured_data'")

        # page coherente
        if self.page is not None and (not isinstance(self.page, int) or self.page < 1):
            errors.append(f"page debe ser entero >= 1 o None (es {self.page!r})")

        # Aviso no bloqueante: baja confianza -> revisión humana
        if (
            self.confidence is not None
            and isinstance(self.confidence, (int, float))
            and 0.0 <= self.confidence < LOW_CONFIDENCE_THRESHOLD
        ):
            self._add_warning(
                f"confianza baja ({self.confidence:.2f} < {LOW_CONFIDENCE_THRESHOLD}): "
                f"requiere revisión humana"
            )

        return errors

    def is_valid(self, *, strict: bool = True) -> bool:
        return not self.validate(strict=strict)

    def requires_human_review(self) -> bool:
        """True si la confianza es baja (por debajo del umbral)."""
        return (
            self.confidence is not None
            and isinstance(self.confidence, (int, float))
            and self.confidence < LOW_CONFIDENCE_THRESHOLD
        )

    def _add_warning(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    # ── Serialización ──────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        d = asdict(self)
        d["media_type"] = self.media_type.value if isinstance(self.media_type, MediaType) else self.media_type
        d["bounding_box"] = self.bounding_box.to_dict() if self.bounding_box else None
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "MultimediaArtifact":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        bb = known.get("bounding_box")
        if isinstance(bb, dict):
            known["bounding_box"] = BoundingBox.from_dict(bb)
        mt = known.get("media_type")
        if isinstance(mt, str):
            try:
                known["media_type"] = MediaType(mt)
            except ValueError:
                known["media_type"] = MediaType.UNKNOWN_VISUAL
        return cls(**known)

    # ── Compatibilidad con el pipeline ASR existente ───────────────────────────
    @classmethod
    def from_transcript_result(
        cls,
        result,  # media.models.TranscriptResult (no se importa para no acoplar)
        *,
        source_id: str,
        file_hash: str,
        region_id: str = "audio",
    ) -> "MultimediaArtifact":
        """Proyecta un `media.models.TranscriptResult` (ASR) a un artefacto.

        NO reimplementa la transcripción: consume el resultado ya producido por
        `media.transcriber` y lo expone como `ASR_TEXT` en el contrato común.
        """
        return cls(
            source_id=source_id,
            file_hash=file_hash,
            media_type=MediaType.ASR_TEXT,
            extraction_method=f"asr:{getattr(result, 'engine', '')}",
            model=getattr(result, "model", "") or "",
            language=getattr(result, "language", "") or "",
            text=getattr(result, "text", "") or "",
            structured_data={
                "segments": [
                    {"start": s.start, "end": s.end, "text": s.text}
                    for s in getattr(result, "segments", []) or []
                ],
                "duration_seconds": getattr(result, "duration_seconds", None),
            },
            provenance={"source_id": source_id, "file_hash": file_hash},
        )


# ── Validación de colecciones (deduplicación / solapes) ───────────────────────
def content_dedup_key(artifact: MultimediaArtifact) -> tuple:
    """Clave de deduplicación por contenido idéntico.

    Dos artefactos con la misma clave (misma fuente, página, tipo y contenido)
    se consideran duplicados (p. ej. regiones idénticas por hash).
    """
    return (
        artifact.source_id,
        artifact.page,
        artifact.media_type.value if isinstance(artifact.media_type, MediaType) else artifact.media_type,
        (artifact.text or "").strip(),
        (artifact.description or "").strip(),
    )


def deduplicate(artifacts: list[MultimediaArtifact]) -> list[MultimediaArtifact]:
    """Elimina artefactos duplicados por contenido, conservando el primero."""
    seen: set = set()
    out: list[MultimediaArtifact] = []
    for art in artifacts:
        key = content_dedup_key(art)
        if key in seen:
            continue
        seen.add(key)
        out.append(art)
    return out


def annotate_overlaps(
    artifacts: list[MultimediaArtifact], *, min_iou: float = 0.10
) -> list[MultimediaArtifact]:
    """Añade un warning a los artefactos de la MISMA página cuyas cajas se solapan.

    No es bloqueante: el solape es un aviso para revisión, no un error. Los
    artefactos con `parent_region` apuntando al otro (jerarquía) NO se marcan.
    """
    by_page: dict = {}
    for art in artifacts:
        if art.bounding_box is None:
            continue
        by_page.setdefault(art.page, []).append(art)

    for page, arts in by_page.items():
        for i in range(len(arts)):
            for j in range(i + 1, len(arts)):
                a, b = arts[i], arts[j]
                # jerarquía explícita: no es un solape "sospechoso"
                if a.region_id and b.parent_region == a.region_id:
                    continue
                if b.region_id and a.parent_region == b.region_id:
                    continue
                if a.bounding_box.overlaps(b.bounding_box, min_iou=min_iou):
                    a._add_warning(
                        f"solape con región '{b.region_id or '?'}' en página {page}"
                    )
                    b._add_warning(
                        f"solape con región '{a.region_id or '?'}' en página {page}"
                    )
    return artifacts
