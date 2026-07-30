# -*- coding: utf-8 -*-
"""Extractor SEMANTICO episodico: ontologia cerrada, candidatos y abstencion.

Corrige, punto por punto, lo que el benchmark midio del camino anterior:

    medido en dev                          que se hace aqui
    -------------------------------------  -------------------------------------
    prompt generico sin ontologia          el `GameProfile` COMPILADO va en el
                                           prompt (definicion, dominio, rango,
                                           simetria, inverso, confundibles)
    el modelo inventa el predicado y        el modelo ELIGE entre predicados
    despues se tira la propuesta con        cerrados; lo que no encaja se
    PREDICATE_NOT_IN_PROFILE (llamada        abstiene, no se descarta pagando la
    pagada para descartarla)                llamada entera
    un solo predicado, un solo candidato    `predicate_candidates` multiples y
                                           ordenados: el motor ya sabe desempatar
    SUBJECT_TO_OBJECT cableado              direccion pedida al modelo, con
                                           UNRESOLVED admitido (= sin candidatos)
    todo `review_required=True` a ciegas    sigue pidiendo revision, pero por una
                                           razon declarada y medible
    una llamada temporal para todos         escalonado: lo explicito se resuelve
                                           localmente y gratis

Lo que NO cambia, porque no debe: el modelo aporta CITAS, nunca offsets ni
identificadores; toda superficie se ancla al texto real o se descarta
(`HALLUCINATED_MENTION`); toda cita se comprueba en contexto y, si el texto
niega o no es factivo, la propuesta se abstiene; la confianza del modelo se
acota y no se lee como probabilidad; y ninguna salida de aqui aprueba nada.

El extractor es AGNOSTICO del proveedor: recibe un `ProviderPort` (Ollama,
NVIDIA o mock) y no sabe cual es. Ese es el experimento del bloque: mismo
prompt, mismo esquema, mismos limites, misma validacion; solo cambia el modelo.
"""
from __future__ import annotations

import time
import hashlib
import json
from collections import deque
from dataclasses import asdict
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from ..contracts import Provider, SourceEpisode
from .base import (
    Diagnostic,
    ExtractionContext,
    ExtractionOutput,
    Extractor,
    ExtractorInfo,
    abstention_claim,
    emit,
    entity_types_of,
)
from .external import EXTERNAL_CONFIDENCE_CAP
from .ontology_prompt import (
    SYSTEM_PROMPT,
    TEMPORAL_SYSTEM_PROMPT,
    OntologySpec,
    compile_ontology,
    render_prompt,
    render_temporal_prompt,
)
from .payload import (
    DEFAULT_CONFIDENCE_CAP,
    PayloadError,
    check_semantic_shape,
    normalize_semantic_payload,
)
from .provider_port import (
    ProviderPort,
    ProviderPortError,
    ProviderRequest,
    ProviderUnavailable,
)
from .temporal import (
    TEMPORAL_AMBIGUOUS,
    TEMPORAL_NONE,
    TEMPORAL_RESOLVED,
    resolve_locally,
    validate_model_expressions,
)
from .text import Anchor, EvidenceIndex

SEMANTIC_STEP = "extract.semantic"

#: Nombre del paso cuando el puerto es LOCAL (Ollama o mock). Vive dentro del
#: espacio reservado `s9k.extraction.*`, que es el de lo local.
SEMANTIC_NAME = "s9k.extraction.semantic"

#: Nombre del paso cuando el puerto es EXTERNO. NO puede vivir en el espacio
#: reservado: un informe que leyese `s9k.extraction.semantic` con
#: `provider: external` no podria distinguir una propuesta local de una remota,
#: y esa distincion es justo la que la traza existe para conservar.
EXTERNAL_SEMANTIC_NAME = "external.semantic"

#: Tope de tokens de la respuesta. La forma conjunta es mas larga que la del
#: camino anterior: con 1024 el modelo se quedaba a medias y el JSON llegaba
#: truncado, que en el informe aparece como "JSON invalido" y no lo es.
DEFAULT_MAX_TOKENS = 3072


@dataclass
class EpisodeRun:
    """Coste REAL de un episodio. Se registra siempre, salga bien o mal."""

    episode_id: str
    ok: bool
    latency_ms: int = 0
    calls: int = 0
    json_retries: int = 0
    temporal_calls: int = 0
    error: str = ""
    model: str = ""
    mentions: int = 0
    claims: int = 0
    abstentions: int = 0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class SemanticEpisodeExtractor(Extractor):
    """Extractor semantico sobre un `ProviderPort`. Propone; no decide."""

    def __init__(
        self,
        port: ProviderPort,
        *,
        confidence_cap: float = DEFAULT_CONFIDENCE_CAP,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temporal_second_pass: bool = True,
        emit_abstention_on_failure: bool = True,
        max_chars: int = 6000,
        max_recorded_runs: int = 256,
    ) -> None:
        self.port = port
        provider = getattr(port, "provider", Provider.LOCAL)
        # El tope NUNCA sube por parametro (misma regla que el camino Ollama):
        # un LLM sin calibrar no puede firmar un 0.99. Y si el puerto es EXTERNO
        # baja otro escalon (0.6): un proveedor remoto no ha visto el corpus, no
        # esta calibrado contra el y su salida no se puede reproducir en local.
        cap = min(float(confidence_cap), DEFAULT_CONFIDENCE_CAP)
        if provider is Provider.EXTERNAL:
            cap = min(cap, EXTERNAL_CONFIDENCE_CAP)
        self.confidence_cap = cap
        self.max_tokens = int(max_tokens)
        self.temporal_second_pass = bool(temporal_second_pass)
        self.emit_abstention_on_failure = bool(emit_abstention_on_failure)
        self.max_chars = int(max_chars)
        if int(max_recorded_runs) <= 0:
            raise ValueError("max_recorded_runs debe ser mayor que cero")
        self.runs: deque[EpisodeRun] = deque(maxlen=int(max_recorded_runs))
        self._ontology_cache: dict[str, OntologySpec] = {}
        self.info = ExtractorInfo(
            step=SEMANTIC_STEP,
            provider=provider,
            name=EXTERNAL_SEMANTIC_NAME if provider is Provider.EXTERNAL else SEMANTIC_NAME,
            model=getattr(port, "model", None),
        )

    # -- ontologia --------------------------------------------------------
    def ontology_for(self, ctx: ExtractionContext) -> OntologySpec:
        """Compila (y cachea) la ontologia del contexto. Sin perfil, no hay."""
        profile = ctx.profile.to_dict() if ctx.profile is not None else None
        lexicon = [
            asdict(entry) for entry in getattr(ctx.lexicon, "entries", ())
        ]
        content = {
            "profile": profile,
            "lexicon": lexicon,
            "entity_types": entity_types_of(ctx.profile),
        }
        clave = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        cached = self._ontology_cache.get(clave)
        if cached is None:
            # El extractor trabaja con un perfil activo: al cambiar su contenido
            # se invalida la entrada anterior en vez de acumular perfiles viejos.
            self._ontology_cache.clear()
            cached = compile_ontology(
                ctx.profile,
                lexicon=ctx.lexicon,
                entity_types=entity_types_of(ctx.profile),
            )
            self._ontology_cache[clave] = cached
        return cached

    def export_and_clear_runs(self) -> list[dict]:
        """Exporta una instantanea cronologica de telemetria y vacia el buffer."""
        exported = [run.to_dict() for run in self.runs]
        self.runs.clear()
        return exported

    def supports(self, episode: SourceEpisode) -> bool:
        return bool(episode.text) or bool(getattr(episode, "table", None))

    def prompt_for(self, ctx: ExtractionContext, episode: SourceEpisode) -> str:
        """Prompt REAL del episodio. Publico a proposito: hay que poder leerlo."""
        return render_prompt(
            self.ontology_for(ctx),
            episode,
            ctx.index_of(episode),
            max_chars=self.max_chars,
        )

    # -- temporalidad escalonada -----------------------------------------
    def _temporal_hook(
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        run: EpisodeRun,
    ):
        calendars = ctx.calendars()

        def hook(
            index: EvidenceIndex,
            anchor: Optional[Anchor],
            raw_expressions: Sequence[Any],
            model_flag: bool,
        ) -> tuple[list[dict], list[str], bool]:
            lo = anchor.start if anchor is not None else None
            hi = anchor.end if anchor is not None else None
            # (a) lo explicito, en local y gratis
            local = resolve_locally(index, lo=lo, hi=hi, calendars=calendars)
            expresiones = local.to_contract()
            codigos = list(local.reason_codes) + list(local.cues)
            # (c) lo que diga el modelo se valida contra el texto real
            del_modelo, codigos_modelo = validate_model_expressions(
                raw_expressions, index, calendars=calendars
            )
            codigos.extend(codigos_modelo)
            vistas = {(e["text"], e["kind"]) for e in expresiones}
            for e in del_modelo:
                if (e["text"], e["kind"]) not in vistas:
                    vistas.add((e["text"], e["kind"]))
                    expresiones.append(e)

            if local.status == TEMPORAL_RESOLVED:
                return expresiones, sorted(dict.fromkeys(codigos)), False
            if local.status == TEMPORAL_NONE and not expresiones:
                return expresiones, sorted(dict.fromkeys(codigos)), bool(model_flag)
            if local.status != TEMPORAL_AMBIGUOUS or not self.temporal_second_pass:
                return expresiones, sorted(dict.fromkeys(codigos)), True

            # (b) SOLO lo que quedo ambiguo llega al modelo
            contexto = ""
            if anchor is not None:
                frag = index.get(anchor.fragment_id)
                contexto = frag.literal_text if frag is not None else ""
            cita = (index.text or "")[lo:hi] if lo is not None and hi is not None else ""
            try:
                reply = self.port.complete_json(
                    ProviderRequest(
                        system=TEMPORAL_SYSTEM_PROMPT,
                        prompt=render_temporal_prompt(
                            cita, [e["text"] for e in expresiones], contexto or (index.text or "")
                        ),
                        max_tokens=512,
                        purpose="temporal",
                    )
                )
            except ProviderPortError as exc:
                codigos.append("TEMPORAL_SECOND_PASS_FAILED")
                run.error = run.error or f"temporal: {type(exc).__name__}"
                return expresiones, sorted(dict.fromkeys(codigos)), True
            run.temporal_calls += 1
            run.calls += 1
            run.latency_ms += reply.latency_ms
            # (c) y (d): se valida, y si sigue ambigua se dice; no se rellena
            nuevas, codigos_nuevos = validate_model_expressions(
                reply.payload.get("temporal_expressions") or [], index, calendars=calendars
            )
            codigos.extend(codigos_nuevos)
            for e in nuevas:
                if (e["text"], e["kind"]) not in vistas:
                    vistas.add((e["text"], e["kind"]))
                    expresiones.append(e)
            pendiente = bool(reply.payload.get("still_ambiguous", True)) or not nuevas
            if pendiente:
                codigos.append("TEMPORAL_STILL_AMBIGUOUS")
            return expresiones, sorted(dict.fromkeys(codigos)), pendiente

        return hook

    # -- ejecucion --------------------------------------------------------
    def _abstain(
        self,
        out: ExtractionOutput,
        episode: SourceEpisode,
        index: EvidenceIndex,
        code: str,
        detail: str,
    ) -> None:
        out.diagnostics.append(Diagnostic(code, self.info.step, episode.episode_id, detail[:300]))
        if not self.emit_abstention_on_failure or not index.fragment_ids:
            return
        claim = abstention_claim(
            info=self.info,
            episode=episode,
            evidence_fragment_ids=index.fragment_ids[:1],
            reason_codes=[code],
            metadata={
                "model": self.info.model,
                "detail": detail[:300],
                "metadata_block_version": "1",
                "untrusted_origin": True,
            },
        )
        emit(claim, out, self.info, episode.episode_id)

    def extract_episode(
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        prior: Optional[ExtractionOutput] = None,
    ) -> ExtractionOutput:
        out = ExtractionOutput()
        index = ctx.index_of(episode)
        run = EpisodeRun(episode_id=episode.episode_id, ok=False, model=self.info.model or "")
        started = time.monotonic()
        try:
            ontology = self.ontology_for(ctx)
        except ValueError as exc:
            run.error = "NO_ONTOLOGY"
            self.runs.append(run)
            self._abstain(out, episode, index, "SEMANTIC_WITHOUT_ONTOLOGY", str(exc))
            return out

        try:
            reply = self.port.complete_json(
                ProviderRequest(
                    system=SYSTEM_PROMPT,
                    prompt=render_prompt(ontology, episode, index, max_chars=self.max_chars),
                    max_tokens=self.max_tokens,
                    purpose="extraction",
                )
            )
        except ProviderUnavailable as exc:
            run.error = f"UNAVAILABLE: {exc}"
            run.latency_ms = int((time.monotonic() - started) * 1000)
            run.calls += 1
            self.runs.append(run)
            self._abstain(out, episode, index, "PROVIDER_UNAVAILABLE", str(exc))
            return out
        except ProviderPortError as exc:
            run.error = f"BAD_JSON: {exc}"
            run.latency_ms = int((time.monotonic() - started) * 1000)
            run.calls += 1
            self.runs.append(run)
            self._abstain(out, episode, index, "PROVIDER_INVALID_JSON", str(exc))
            return out

        run.calls += 1
        run.json_retries = reply.json_retries
        run.latency_ms = reply.latency_ms
        run.model = reply.model or run.model
        try:
            check_semantic_shape(reply.payload)
        except PayloadError as exc:
            self.runs.append(run)
            self._abstain(out, episode, index, "MODEL_PAYLOAD_MALFORMED", str(exc))
            return out

        if not reply.payload.get("claims") and not reply.payload.get("abstentions"):
            out.diagnostics.append(
                Diagnostic(
                    "EMPTY_PROVIDER_PAYLOAD",
                    self.info.step,
                    episode.episode_id,
                    "el proveedor no devolvio claims ni abstenciones explicitas",
                )
            )

        try:
            out.extend(
                normalize_semantic_payload(
                    reply.payload,
                    ctx=ctx,
                    episode=episode,
                    info=self.info,
                    ontology=ontology,
                    confidence_cap=self.confidence_cap,
                    force_review=True,
                    temporal_hook=self._temporal_hook(ctx, episode, run),
                )
            )
        except (ValueError, TypeError) as exc:
            # Un payload con tipos imposibles se lleva por delante SU episodio,
            # nunca el lote: los demas episodios estaban bien.
            self.runs.append(run)
            self._abstain(
                out, episode, index, "MODEL_PAYLOAD_MALFORMED", f"{type(exc).__name__}: {exc}"
            )
            return out

        run.ok = True
        run.mentions = len(out.mentions)
        run.claims = len([c for c in out.claims if not c.abstained])
        run.abstentions = len([c for c in out.claims if c.abstained])
        self.runs.append(run)
        return out

    # -- medicion ---------------------------------------------------------
    def performance(self) -> dict:
        """Rendimiento agregado. Se REGISTRA, no se maquilla."""
        if not self.runs:
            return {"status": "not_evaluated", "reason": "no se ejecuto ningun episodio"}
        latencias = sorted(r.latency_ms for r in self.runs)
        ok = [r for r in self.runs if r.ok]
        return {
            "status": "measured",
            "provider": self.info.provider.value,
            "model": self.info.model,
            "episodes": len(self.runs),
            "episodes_ok": len(ok),
            "valid_json_rate": round(len(ok) / len(self.runs), 4),
            "provider_calls": sum(r.calls for r in self.runs),
            "temporal_second_pass_calls": sum(r.temporal_calls for r in self.runs),
            "json_retries": sum(r.json_retries for r in self.runs),
            "latency_ms_total": sum(latencias),
            "latency_ms_mean": round(sum(latencias) / len(latencias), 1),
            "latency_ms_median": latencias[len(latencias) // 2],
            "latency_ms_max": latencias[-1],
            "errors": sorted({r.error for r in self.runs if r.error}),
            "per_episode": [r.to_dict() for r in self.runs],
        }


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "EXTERNAL_SEMANTIC_NAME",
    "SEMANTIC_NAME",
    "SEMANTIC_STEP",
    "EpisodeRun",
    "SemanticEpisodeExtractor",
]
