# -*- coding: utf-8 -*-
"""Extractor EXTERNO: SOLO el punto de enganche. Aqui no hay transporte.

El subsistema de proveedores (rama `feat/v3-provider-routing`) es quien habla
con NVIDIA o con quien sea: enrutado, cuotas, coste, reintentos, redaccion de
credenciales y politica de privacidad. Este modulo define la frontera y nada
mas:

    proveedor externo -> `ExternalProposalPort.propose()` -> payload
    payload -> `payload.normalize_payload()` -> propuestas ancladas y validadas

Por que el transporte no esta aqui: si el extractor supiera hablar con el
proveedor, la politica de coste y de privacidad acabaria duplicada en dos
sitios, y una de las dos copias se quedaria vieja. La frontera es una funcion.

Garantias que este modulo SI da, y que sus tests fijan:

- las propuestas externas llevan `provider: "external"` en la traza y en
  `produced_by_step`. Nunca se disfrazan de locales;
- pasan por el MISMO filtro anti-alucinacion que Ollama: una cita que no existe
  en un fragmento real no entra, venga de donde venga;
- sin puerto enganchado, el extractor no falla ni finge: emite un diagnostico
  `EXTERNAL_PROVIDER_NOT_BOUND` y devuelve vacio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from ..contracts import Provider, SourceEpisode
from .base import (
    Diagnostic,
    ExtractionContext,
    ExtractionOutput,
    Extractor,
    ExtractorInfo,
    abstention_claim,
    emit,
)
from .payload import DEFAULT_CONFIDENCE_CAP, PayloadError, check_payload_shape, normalize_payload
from .text import EvidenceIndex

EXTERNAL_STEP = "extract.external"

#: Tope de confianza de una propuesta externa: por debajo del de Ollama a
#: proposito. Un proveedor remoto no ha visto el corpus, no esta calibrado
#: contra el, y ademas su salida no se puede reproducir localmente.
EXTERNAL_CONFIDENCE_CAP = 0.6


@dataclass(frozen=True)
class ExternalExtractionRequest:
    """Lo que el subsistema de proveedores necesita para pedir una extraccion.

    Lleva los fragmentos con su texto literal porque el proveedor tiene que
    poder CITAR. No lleva credenciales, ni rutas locales, ni nada del workspace
    que no sea su nombre.
    """

    workspace: str
    episode_id: str
    modality: str
    text: Optional[str]
    fragments: tuple[tuple[str, str], ...]  # (fragment_id, literal_text)
    predicates: tuple[str, ...] = ()
    entity_types: tuple[str, ...] = ()
    language_hint: Optional[str] = None

    @classmethod
    def from_episode(
        cls, ctx: ExtractionContext, episode: SourceEpisode, index: EvidenceIndex
    ) -> "ExternalExtractionRequest":
        return cls(
            workspace=episode.workspace,
            episode_id=episode.episode_id,
            modality=episode.modality,
            text=episode.text,
            fragments=tuple((f.fragment_id, f.literal_text) for f in index.fragments),
            predicates=tuple(sorted(ctx.profile_predicates())),
        )


@dataclass(frozen=True)
class ExternalExtractionResponse:
    """Lo que el proveedor devuelve: un payload y su identidad declarada."""

    payload: Any
    provider_name: str
    provider_version: str
    model: Optional[str] = None
    reason_codes: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class ExternalProposalPort(Protocol):
    """Puerto hacia el subsistema de proveedores. Una sola operacion.

    La implementacion vive FUERA de `extraction/`. Debe ser fail-closed: ante
    error, lanza; no devuelve un payload a medias.
    """

    def propose(self, request: ExternalExtractionRequest) -> ExternalExtractionResponse:
        ...


class ExternalExtractor(Extractor):
    """Punto de enganche. Sin puerto, no hay propuestas (y se dice claramente)."""

    def __init__(
        self,
        port: Optional[ExternalProposalPort] = None,
        *,
        confidence_cap: float = EXTERNAL_CONFIDENCE_CAP,
        emit_abstention_on_failure: bool = True,
    ) -> None:
        self.port = port
        self.confidence_cap = min(confidence_cap, DEFAULT_CONFIDENCE_CAP)
        self.emit_abstention_on_failure = emit_abstention_on_failure
        self.info = ExtractorInfo(
            step=EXTERNAL_STEP,
            provider=Provider.EXTERNAL,
            name="s9k.extraction.external",
        )

    @property
    def bound(self) -> bool:
        return self.port is not None

    def _info_for(self, response: ExternalExtractionResponse) -> ExtractorInfo:
        """Traza VERAZ: el nombre y el modelo son los que declara el proveedor."""
        return ExtractorInfo(
            step=EXTERNAL_STEP,
            provider=Provider.EXTERNAL,
            name=response.provider_name or self.info.name,
            version=response.provider_version or self.info.version,
            model=response.model,
        )

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
                    "EXTERNAL_PROVIDER_NOT_BOUND", self.info.step, episode.episode_id,
                    "no hay puerto de proveedores enganchado: el transporte vive fuera "
                    "de extraction/ (subsistema de proveedores)",
                )
            )
            return out
        request = ExternalExtractionRequest.from_episode(ctx, episode, index)
        try:
            response = self.port.propose(request)
        except Exception as exc:  # el puerto es fail-closed; aqui solo se registra
            out.diagnostics.append(
                Diagnostic(
                    "EXTERNAL_PROVIDER_FAILED", self.info.step, episode.episode_id,
                    f"{type(exc).__name__}",
                )
            )
            return out
        info = self._info_for(response)
        try:
            check_payload_shape(response.payload)
        except PayloadError as exc:
            out.diagnostics.append(
                Diagnostic(
                    "EXTERNAL_PAYLOAD_MALFORMED", info.step, episode.episode_id, str(exc)
                )
            )
            if self.emit_abstention_on_failure and index.fragment_ids:
                emit(
                    abstention_claim(
                        info=info,
                        episode=episode,
                        evidence_fragment_ids=index.fragment_ids[:1],
                        reason_codes=["EXTERNAL_PAYLOAD_MALFORMED"],
                        metadata={"provider": info.name},
                    ),
                    out,
                    info,
                    episode.episode_id,
                )
            return out
        return out.extend(
            normalize_payload(
                response.payload,
                ctx=ctx,
                episode=episode,
                info=info,
                confidence_cap=self.confidence_cap,
                force_review=True,
            )
        )


__all__ = [
    "EXTERNAL_CONFIDENCE_CAP",
    "EXTERNAL_STEP",
    "ExternalExtractionRequest",
    "ExternalExtractionResponse",
    "ExternalExtractor",
    "ExternalProposalPort",
]
