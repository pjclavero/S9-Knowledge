# -*- coding: utf-8 -*-
"""Extractor OLLAMA: propone menciones y claims; nunca decide nada.

Cadena completa: prompt con salida JSON estricta -> parseo tolerante SOLO a la
sintaxis -> normalizacion anti-alucinacion (`payload.normalize_payload`) ->
documentos validados.

Tres decisiones que conviene entender antes de tocar nada:

- **el modelo no ve identificadores como algo que pueda inventar**: se le
  entregan los `fragment_id` reales y se le pide que cite, pero su respuesta se
  verifica igual. Un `fragment_id` inexistente no invalida la propuesta por si
  solo: se intenta reanclar por el contenido de la cita, y solo si la cita
  tampoco existe se descarta. Asi se distingue "se equivoco de etiqueta" de "se
  lo invento";
- **JSON invalido no es un resultado**: se reintenta UNA vez con una instruccion
  correctiva y, si vuelve a fallar, se emite una ABSTENCION explicita. Nunca se
  devuelve una extraccion parcial adivinada del texto;
- **todo claim de Ollama nace `review_required=True`** y con la confianza
  limitada por `payload.DEFAULT_CONFIDENCE_CAP`.
"""
from __future__ import annotations

import json
import re
from typing import Optional, Sequence

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
from .ollama_client import OllamaClient, OllamaConfig, OllamaError
from .payload import DEFAULT_CONFIDENCE_CAP, PayloadError, check_payload_shape, normalize_payload
from .text import EvidenceIndex

OLLAMA_STEP = "extract.ollama"

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

SYSTEM_PROMPT = (
    "Eres un extractor de conocimiento. Respondes UNICAMENTE con un objeto JSON valido, "
    "sin texto antes ni despues, sin markdown y sin comentarios.\n"
    "Reglas inviolables:\n"
    "1. Solo puedes usar texto que aparezca LITERALMENTE en el fragmento indicado. "
    "Copia las superficies y las citas caracter a caracter.\n"
    "2. No inventes nombres, fechas ni identificadores de fragmento.\n"
    "3. Si no estas seguro, devuelve listas vacias. Omitir es correcto; inventar no.\n"
    "4. Tipos de entidad permitidos: Character, Location, Faction, Object, Event, Concept.\n"
    "5. epistemic permitido: ASSERTED, RUMORED, HYPOTHETICAL, INTENDED, UNKNOWN.\n"
    "6. 'confidence' es TU confianza real entre 0 y 1. No copies el numero del ejemplo."
)

OUTPUT_SCHEMA_HINT = (
    '{"mentions":[{"surface":"texto literal","type":"Character","confidence":0.0,'
    '"fragment_id":"id del fragmento","quote":"frase literal que la contiene"}],'
    '"claims":[{"subject":"superficie del sujeto","relation":"verbo o frase literal",'
    '"object":"superficie del objeto","predicate":"PREDICADO_EN_MAYUSCULAS",'
    '"negated":false,"epistemic":"ASSERTED","confidence":0.0,'
    '"fragment_id":"id del fragmento","quote":"frase literal que lo sostiene"}]}'
)

RETRY_INSTRUCTION = (
    "\n\nLa respuesta anterior NO era JSON valido. Devuelve exclusivamente el objeto JSON "
    "con las claves 'mentions' y 'claims'. Nada mas."
)


class OllamaJSONError(ValueError):
    """El modelo no devolvio un objeto JSON utilizable."""


def parse_strict_json(text: str) -> dict:
    """Parsea la respuesta del modelo. Repara SINTAXIS, jamas semantica.

    Se admiten dos reparaciones, ambas puramente textuales: quitar las vallas de
    markdown y recortar al primer objeto `{...}`. No se completan campos, no se
    adivinan valores y no se acepta nada que no sea un objeto JSON.
    """
    if not isinstance(text, str) or not text.strip():
        raise OllamaJSONError("respuesta vacia")
    candidates = [text.strip(), _FENCE_RE.sub("", text.strip())]
    stripped = text.strip()
    first, last = stripped.find("{"), stripped.rfind("}")
    if 0 <= first < last:
        candidates.append(stripped[first:last + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    raise OllamaJSONError("la respuesta no contiene un objeto JSON")


def build_prompt(episode: SourceEpisode, index: EvidenceIndex, *, max_chars: int = 6000) -> str:
    """Prompt del episodio con sus fragmentos REALES y sus identificadores."""
    fragments = []
    for frag in index.fragments:
        fragments.append(
            f'- fragment_id: "{frag.fragment_id}"\n  texto: "{frag.literal_text[:1500]}"'
        )
    text = (episode.text or "")[:max_chars]
    return (
        f"Episodio: {episode.episode_id}\n"
        f"Modalidad: {episode.modality}\n\n"
        f"TEXTO:\n{text}\n\n"
        f"FRAGMENTOS DISPONIBLES (usa SOLO estos identificadores):\n"
        + "\n".join(fragments)
        + "\n\nDevuelve exactamente esta forma JSON:\n"
        + OUTPUT_SCHEMA_HINT
    )


class OllamaExtractor(Extractor):
    """Extractor basado en el LLM local. Propone; el motor local decide."""

    def __init__(
        self,
        client: Optional[OllamaClient] = None,
        *,
        config: Optional[OllamaConfig] = None,
        max_json_retries: int = 1,
        confidence_cap: float = DEFAULT_CONFIDENCE_CAP,
        emit_abstention_on_failure: bool = True,
    ) -> None:
        self.client = client or OllamaClient(config=config)
        self.max_json_retries = max(0, int(max_json_retries))
        self.confidence_cap = confidence_cap
        self.emit_abstention_on_failure = emit_abstention_on_failure
        self.info = ExtractorInfo(
            step=OLLAMA_STEP,
            provider=Provider.OLLAMA,
            name="s9k.extraction.ollama",
            model=self.client.config.model,
        )

    def supports(self, episode: SourceEpisode) -> bool:
        return bool(episode.text)

    def _abstain(
        self, out: ExtractionOutput, episode: SourceEpisode, index: EvidenceIndex,
        code: str, detail: str,
    ) -> None:
        out.diagnostics.append(Diagnostic(code, self.info.step, episode.episode_id, detail[:300]))
        if not self.emit_abstention_on_failure or not index.fragment_ids:
            return
        claim = abstention_claim(
            info=self.info,
            episode=episode,
            evidence_fragment_ids=index.fragment_ids[:1],
            reason_codes=[code],
            metadata={"model": self.info.model, "detail": detail[:300]},
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
        prompt = build_prompt(episode, index)
        payload = None
        last_error = ""
        for attempt in range(self.max_json_retries + 1):
            try:
                response = self.client.generate(
                    prompt if attempt == 0 else prompt + RETRY_INSTRUCTION,
                    system=SYSTEM_PROMPT,
                )
            except OllamaError as exc:
                self._abstain(out, episode, index, "OLLAMA_UNAVAILABLE", str(exc))
                return out
            try:
                candidate = parse_strict_json(response.text)
                check_payload_shape(candidate)
            except (OllamaJSONError, PayloadError) as exc:
                last_error = str(exc)
                continue
            payload = candidate
            break
        if payload is None:
            self._abstain(out, episode, index, "OLLAMA_INVALID_JSON", last_error)
            return out
        return out.extend(
            normalize_payload(
                payload,
                ctx=ctx,
                episode=episode,
                info=self.info,
                confidence_cap=self.confidence_cap,
                force_review=True,
            )
        )


__all__ = [
    "OLLAMA_STEP",
    "OUTPUT_SCHEMA_HINT",
    "RETRY_INSTRUCTION",
    "SYSTEM_PROMPT",
    "OllamaExtractor",
    "OllamaJSONError",
    "build_prompt",
    "parse_strict_json",
]
