# -*- coding: utf-8 -*-
"""Nucleo del normalizador multimodal: entrada, opciones, borradores y ensamblado.

Division de responsabilidades, deliberada:

* Los **adaptadores** solo saben de su formato. Producen *borradores*
  (`EpisodeDraft`, `FragmentDraft`) con texto, offsets, bbox y timecodes.
* El **ensamblador** de este modulo es el unico que construye documentos
  `v3-internal-v1`: identificadores, `sequence`, encadenado `previous/next`,
  hashes, envelope y `provider_trace`. Un adaptador no puede equivocarse en
  algo que no escribe.

Invariante duro que se comprueba SIEMPRE (`_check_anchor`): si el episodio tiene
texto, `episode.text[fragment.start:fragment.end] == fragment.literal_text`. Un
fragmento cuyo offset no recorta su propio literal es evidencia falsa, y una
evidencia falsa es peor que ninguna: apunta a un sitio que parece verificado.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from ..contracts import (
    CONTRACT_VERSION,
    EvidenceFragment,
    Provider,
    SourceAsset,
    SourceEpisode,
    provider_step,
    sha256_hash,
)
from . import errors, ids
from .quality import normalize_text

#: Version del normalizador. Entra en `provider_trace`: si cambia el algoritmo
#: de segmentacion, la traza lo dice.
NORMALIZER_VERSION = "1.0.0"

#: Nombres canonicos de los pasos de `provider_trace` que emite este subsistema.
STEP_INGEST = "ingest"
STEP_EXTRACT = "extract"
STEP_ANCHOR = "anchor"

#: Modalidades que el validador obliga a llevar texto no vacio.
TEXT_MODALITIES = frozenset({"TEXT", "OCR_TEXT", "HTR_TEXT", "ASR_TEXT"})


# ──────────────────────────────────────────────────────────────────────────────
# Entrada y opciones
# ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SourceInput:
    """Fuente a normalizar.

    `data` son los bytes REALES de la fuente: el `content_hash` del asset es su
    sha256 y nada mas. Cuando la fuente no es un fichero local (YouTube), el
    adaptador correspondiente documenta que bytes hashea y por que.

    `payload` transporta lo que no son bytes del fichero: la transcripcion ya
    producida por `media/`, `audio/` o `youtube/`, o las regiones declaradas de
    una imagen. El normalizador NO transcribe ni ejecuta OCR: envuelve.
    """

    data: bytes
    original_name: str
    original_location: str
    mime_type: Optional[str] = None
    source_kind: Optional[str] = None
    payload: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class IngestOptions:
    """Politica y metadatos de la ingesta.

    `ingested_at` y `created_at` son DATOS, no se generan aqui: el nucleo nunca
    llama al reloj. Si lo hiciera, dos normalizaciones del mismo fichero
    dejarian de ser identicas y el determinismo seria una promesa vacia.
    """

    workspace: str
    collection_id: str
    ingested_at: str
    created_at: Optional[str] = None
    game_profile: str = "generic"
    language_hint: Optional[str] = None
    privacy_class: str = "INTERNAL"
    copyright_class: str = "UNKNOWN"
    allow_external_providers: bool = False
    allow_media_persistence: bool = False
    retention_days: Optional[int] = None

    def processing_policy(self) -> dict[str, Any]:
        """Bloque `processing_policy` del asset, ya validado contra la clase de privacidad."""
        if self.privacy_class in ("PERSONAL_DATA", "RESTRICTED") and self.allow_external_providers:
            raise errors.NormalizationError(
                errors.INCONSISTENT_POLICY,
                f"privacy_class={self.privacy_class} no admite allow_external_providers=true; "
                "el contrato lo prohibe y degradarlo en silencio ocultaria la intencion",
            )
        return {
            "allow_external_providers": bool(self.allow_external_providers),
            "allow_media_persistence": bool(self.allow_media_persistence),
            "retention_days": self.retention_days,
        }

    def effective_created_at(self) -> str:
        return self.created_at or self.ingested_at


# ──────────────────────────────────────────────────────────────────────────────
# Borradores que produce un adaptador
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class FragmentDraft:
    """Anclaje literal propuesto por un adaptador, aun sin identidad ni envelope."""

    literal_text: str
    start: int
    end: int
    media_type: str
    confidence: float = 1.0
    bbox: Optional[dict] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    frame_id: Optional[str] = None
    page: Optional[int] = None
    produced_by: str = STEP_EXTRACT
    metadata: Optional[dict] = None


@dataclass
class EpisodeDraft:
    """Trozo direccionable propuesto por un adaptador."""

    modality: str
    text: Optional[str] = None
    page: Optional[int] = None
    bbox: Optional[dict] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    speaker: Optional[dict] = None
    turn: Optional[int] = None
    table: Optional[dict] = None
    quality: dict = field(default_factory=lambda: {"score": 1.0, "flags": []})
    fragments: list[FragmentDraft] = field(default_factory=list)
    produced_by: str = STEP_EXTRACT
    metadata: Optional[dict] = None


@dataclass
class AdapterOutput:
    """Lo que devuelve un adaptador: episodios, pasos de traza y su informe."""

    source_kind: str
    mime_type: str
    episodes: list[EpisodeDraft]
    trace_steps: list[dict] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Interfaz de adaptador
# ──────────────────────────────────────────────────────────────────────────────
class SourceAdapter(abc.ABC):
    """Contrato que cumple todo adaptador de fuente.

    Un adaptador declara que `source_kind` cubre, que MIME y extensiones
    reconoce, y sabe convertir bytes (+ payload) en borradores de episodio. No
    conoce los contratos V3 ni construye identificadores.
    """

    #: Nombre estable del adaptador; aparece en `provider_trace.name`.
    name: str = ""
    #: Version del adaptador; aparece en `provider_trace.version`.
    version: str = NORMALIZER_VERSION
    #: `source_kind` del contrato que produce este adaptador.
    source_kinds: tuple[str, ...] = ()
    #: MIME que reconoce en la deteccion automatica.
    mime_types: tuple[str, ...] = ()
    #: Extensiones (con punto, en minusculas) que reconoce.
    extensions: tuple[str, ...] = ()
    #: True si el adaptador esta DECLARADO pero su ejecucion real corresponde al
    #: subsistema de proveedores (OCR, HTR, vision). Se expone tal cual: un
    #: adaptador stub que se anuncie como real es una mentira en el inventario.
    is_stub: bool = False

    @abc.abstractmethod
    def extract(self, source: SourceInput, options: IngestOptions) -> AdapterOutput:
        """Convierte la fuente en borradores de episodio."""

    def content_bytes(self, source: SourceInput) -> bytes:
        """Bytes que definen el CONTENIDO del asset y de los que sale su sha256.

        Por defecto, los bytes del fichero. Un adaptador solo lo sobrescribe si
        la fuente no es un fichero local (YouTube), y entonces debe documentar
        exactamente que hashea: un `content_hash` cuyo origen no esta escrito no
        es procedencia, es un numero.
        """
        return source.data

    def default_mime(self) -> str:
        return self.mime_types[0] if self.mime_types else "application/octet-stream"

    def local_step(self, produced: Sequence[str], step: str = STEP_EXTRACT) -> dict:
        """Paso `local` de traza con el nombre y la version de este adaptador."""
        return provider_step(
            step, Provider.LOCAL, self.name, self.version, list(produced)
        )


# ──────────────────────────────────────────────────────────────────────────────
# Ensamblado a documentos v3-internal-v1
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class NormalizationResult:
    """Salida del normalizador: un asset, sus episodios y su evidencia."""

    asset: SourceAsset
    episodes: list[SourceEpisode]
    fragments: list[EvidenceFragment]
    report: dict[str, Any]

    def validate(self) -> "NormalizationResult":
        """Valida los tres tipos de documento contra los contratos congelados."""
        self.asset.validate()
        for episode in self.episodes:
            episode.validate()
        for fragment in self.fragments:
            fragment.validate()
        return self

    def fragments_of(self, episode_id: str) -> list[EvidenceFragment]:
        return [f for f in self.fragments if f.episode_id == episode_id]

    def to_dict(self) -> dict[str, Any]:
        """Serializacion completa y determinista del resultado."""
        return {
            "asset": self.asset.to_dict(),
            "episodes": [e.to_dict() for e in self.episodes],
            "fragments": [f.to_dict() for f in self.fragments],
            "report": self.report,
        }


def _ingest_step() -> dict:
    return provider_step(
        STEP_INGEST,
        Provider.LOCAL,
        "knowledge_v3.multimodal.normalizer",
        NORMALIZER_VERSION,
        ["content_hash", "byte_size", "mime_type", "source_kind"],
    )


def _anchor_step() -> dict:
    """Paso local que fija offsets, bbox y timecodes.

    Existe siempre y es SIEMPRE `local`, incluso cuando el texto lo produjo un
    proveedor: el contrato dice que los anclajes los pone o los verifica el
    sistema local, nunca el proveedor.
    """
    return provider_step(
        STEP_ANCHOR,
        Provider.LOCAL,
        "knowledge_v3.multimodal.anchor",
        NORMALIZER_VERSION,
        ["start", "end", "bbox", "time_start", "time_end", "normalized_text"],
    )


def _check_anchor(episode_text: Optional[str], draft: FragmentDraft, episode_id: str) -> None:
    if draft.start > draft.end:
        raise errors.NormalizationError(
            errors.ANCHOR_MISMATCH,
            f"fragmento de {episode_id} con start {draft.start} > end {draft.end}",
        )
    if episode_text is None:
        return
    sliced = episode_text[draft.start : draft.end]
    if sliced != draft.literal_text:
        raise errors.NormalizationError(
            errors.ANCHOR_MISMATCH,
            f"offsets [{draft.start}:{draft.end}] de {episode_id} recortan "
            f"{sliced!r}, no el literal {draft.literal_text!r}: la evidencia "
            "apuntaria a un sitio que no dice lo que dice",
        )


def _check_unique(values: list[str], label: str) -> None:
    seen: set[str] = set()
    duplicated: set[str] = set()
    for value in values:
        if value in seen:
            duplicated.add(value)
        seen.add(value)
    if duplicated:
        raise errors.NormalizationError(
            errors.ANCHOR_MISMATCH,
            f"{label} duplicado: {sorted(duplicated)}; con identificadores repetidos la "
            "procedencia deja de ser una funcion",
        )


def _episode_content_payload(draft: EpisodeDraft) -> dict[str, Any]:
    """Cuerpo que define el contenido del episodio, para su `content_hash`.

    No incluye identificadores ni encadenado: el hash es del CONTENIDO. Si
    incluyera `previous_episode_id`, insertar un episodio delante cambiaria el
    hash de uno cuyo contenido no ha cambiado.
    """
    return {
        "modality": draft.modality,
        "text": draft.text,
        "page": draft.page,
        "bbox": draft.bbox,
        "time_start": draft.time_start,
        "time_end": draft.time_end,
        "speaker": draft.speaker,
        "turn": draft.turn,
        "table": draft.table,
    }


def assemble(
    source: SourceInput,
    options: IngestOptions,
    output: AdapterOutput,
    content_hash_hex: str,
    byte_size: int,
) -> NormalizationResult:
    """Convierte los borradores de un adaptador en documentos `v3-internal-v1`.

    Es la UNICA funcion que escribe envelope, identidad y hashes. Valida todo lo
    que produce antes de devolverlo: el normalizador no emite documentos que no
    pasen su propio contrato.
    """
    policy = options.processing_policy()
    content_hash = ids.hash_field(content_hash_hex)
    asset_id = ids.asset_id_for(options.workspace, options.collection_id, content_hash_hex)

    asset = SourceAsset(
        contract_version=CONTRACT_VERSION,
        workspace=options.workspace,
        source_asset_id=asset_id,
        source_hash=content_hash,
        provider_trace=[_ingest_step()],
        produced_by_step=STEP_INGEST,
        asset_id=asset_id,
        collection_id=options.collection_id,
        game_profile=options.game_profile,
        source_kind=output.source_kind,
        mime_type=source.mime_type or output.mime_type,
        content_hash=content_hash,
        byte_size=byte_size,
        original_name=source.original_name,
        original_location=source.original_location,
        created_at=options.effective_created_at(),
        ingested_at=options.ingested_at,
        language_hint=options.language_hint,
        privacy_class=options.privacy_class,
        copyright_class=options.copyright_class,
        processing_policy=policy,
    )

    episode_trace = [_ingest_step(), *output.trace_steps]
    fragment_trace = [*episode_trace, _anchor_step()]

    # Primera pasada: identidad de cada episodio (necesaria para encadenar).
    prepared: list[tuple[EpisodeDraft, str, dict]] = []
    for sequence, draft in enumerate(output.episodes):
        episode_hash = sha256_hash(_episode_content_payload(draft))
        episode_id = ids.episode_id_for(asset_id, sequence, episode_hash["value"])
        prepared.append((draft, episode_id, episode_hash))

    episodes: list[SourceEpisode] = []
    fragments: list[EvidenceFragment] = []
    for index, (draft, episode_id, episode_hash) in enumerate(prepared):
        if draft.modality in TEXT_MODALITIES and not (draft.text or "").strip():
            raise errors.NormalizationError(
                errors.NO_CONTENT_EXTRACTED,
                f"episodio {index} con modality={draft.modality} y texto vacio: "
                "una modalidad textual sin texto no es un episodio, es un hueco",
            )
        episodes.append(
            SourceEpisode(
                contract_version=CONTRACT_VERSION,
                workspace=options.workspace,
                source_asset_id=asset_id,
                source_hash=content_hash,
                provider_trace=episode_trace,
                produced_by_step=draft.produced_by,
                episode_id=episode_id,
                asset_id=asset_id,
                sequence=index,
                modality=draft.modality,
                text=draft.text,
                page=draft.page,
                bbox=draft.bbox,
                time_start=draft.time_start,
                time_end=draft.time_end,
                previous_episode_id=prepared[index - 1][1] if index > 0 else None,
                next_episode_id=prepared[index + 1][1] if index + 1 < len(prepared) else None,
                speaker=draft.speaker,
                turn=draft.turn,
                table=draft.table,
                quality=draft.quality,
                content_hash=episode_hash,
                metadata=draft.metadata,
            )
        )
        for fragment_draft in draft.fragments:
            _check_anchor(draft.text, fragment_draft, episode_id)
            if not fragment_draft.literal_text:
                raise errors.NormalizationError(
                    errors.ANCHOR_MISMATCH,
                    f"fragmento vacio en {episode_id}: un literal vacio no ancla nada",
                )
            fragments.append(
                EvidenceFragment(
                    contract_version=CONTRACT_VERSION,
                    workspace=options.workspace,
                    source_asset_id=asset_id,
                    source_hash=content_hash,
                    provider_trace=fragment_trace,
                    produced_by_step=fragment_draft.produced_by,
                    fragment_id=ids.fragment_id_for(
                        episode_id,
                        fragment_draft.start,
                        fragment_draft.end,
                        fragment_draft.media_type,
                        fragment_draft.literal_text,
                    ),
                    episode_id=episode_id,
                    literal_text=fragment_draft.literal_text,
                    normalized_text=normalize_text(fragment_draft.literal_text),
                    start=fragment_draft.start,
                    end=fragment_draft.end,
                    bbox=fragment_draft.bbox,
                    time_start=fragment_draft.time_start,
                    time_end=fragment_draft.time_end,
                    frame_id=fragment_draft.frame_id,
                    page=fragment_draft.page if fragment_draft.page is not None else draft.page,
                    media_type=fragment_draft.media_type,
                    confidence=fragment_draft.confidence,
                    metadata=fragment_draft.metadata,
                )
            )

    # Unicidad: dos episodios o dos fragmentos con el mismo id hacen que la
    # procedencia deje de ser una funcion (una cita apuntaria a dos sitios).
    _check_unique([e.episode_id for e in episodes], "episode_id")
    _check_unique([f.fragment_id for f in fragments], "fragment_id")

    report = {
        "normalizer_version": NORMALIZER_VERSION,
        "source_kind": output.source_kind,
        "mime_type": asset.mime_type,
        "byte_size": asset.byte_size,
        "episode_count": len(episodes),
        "fragment_count": len(fragments),
        "modalities": sorted({e.modality for e in episodes}),
        "media_types": sorted({f.media_type for f in fragments}),
        "pending_provider_episodes": sum(
            1
            for e in episodes
            if "UNPROCESSED_PENDING_PROVIDER" in (e.quality.get("flags") or [])
        ),
        **output.report,
    }
    return NormalizationResult(
        asset=asset, episodes=episodes, fragments=fragments, report=report
    ).validate()
