# -*- coding: utf-8 -*-
"""Capa 2 de la puerta 6: el invariante fail-closed contra el EXTRACTOR REAL.

Por que existe este modulo
--------------------------
`gate6_harness.py` mide una capa: `extraction.cues.analyze_raw_text` (el
CLASIFICADOR de factividad). Esa medida contesta "¿la politica lee bien la
frase?", que es una pregunta necesaria pero NO es la pregunta de la puerta.
La pregunta de la puerta es "¿el sistema escribiria esto como un hecho del
mundo?", y quien decide eso es el extractor de produccion.

El bloque B2 demostro que las dos preguntas podian tener respuestas distintas:
`analyze_raw_text("El heraldo dijo que Elara lidera la Orden")` devolvia RUMOR
mientras `DeterministicExtractor` emitia el mismo texto como ASSERTED con
`review_required=False`, porque el extractor solo consultaba del `verdict` las
dos acciones de ABORTO y nunca `EMIT_EPISTEMIC_PROPOSAL`. Una medicion de la
capa de clasificador no podia ver ese fallo: medir la capa que no escribe y
concluir sobre la que escribe es exactamente el error que la puerta 4 evito
publicando sus numeros POR CAPA.

Este modulo publica la segunda capa, `deterministic_extractor`, con la misma
disciplina: mismos corpus, mismo gold, ninguna cifra mezclada con las de la
capa 1.

Que se mide exactamente
-----------------------
Para cada caso se construye un episodio de un solo fragmento con su texto y se
corre `DeterministicExtractor`. Se cuenta VIOLACION cuando un caso cuyo gold
exige abstenerse (dev: `expected` distinto de WRITE_POSITIVE/WRITE_NEGATIVE;
generalizacion: `expected_class == "NON_FACTIVE"`) produce al menos un claim
NO abstenido con `epistemic_status_hint == "ASSERTED"`. Se publican dos
recuentos, del mas grave al mas laxo:

* `violations_written_without_review`: ademas, `review_required is False`.
  El sistema escribiria el hecho sin que ningun humano lo mire. Es el fallo
  que el programa de la puerta 6 existe para impedir.
* `violations_asserted`: el hint sale ASSERTED aunque la revision este
  marcada. Sigue siendo una lectura factual de algo que el gold no autoriza a
  leer asi, y se publica aparte en vez de esconderse en el numero anterior.

Cobertura y su honestidad
-------------------------
El extractor determinista solo ancla menciones que estan en el LEXICO
(`extraction/lexicon.py`); no hay NER. Los dos corpus de la puerta 6 son
frases sueltas sin lexico asociado, asi que este modulo construye uno POR
CASO con un reconocedor de nombres propios de superficie
(`proper_name_candidates`): secuencias de palabras capitalizadas unidas por
preposiciones/articulos, sin el determinante inicial. Es andamiaje de
MEDICION, no parte del extractor, y se declara como tal:

* no adivina tipos de entidad (`entity_type=None`), asi que ninguna regla se
  filtra por tipo y el extractor tiene MAS oportunidades de emitir, no menos:
  el sesgo del andamiaje va en contra del sistema medido, no a su favor;
* la cobertura real (cuantos casos llegan a producir algun claim) se publica
  en `coverage`, porque un "0 violaciones" sobre 3 casos cubiertos no
  significa lo mismo que sobre 80. Sin ese numero al lado, la cifra de
  violaciones de esta capa no es interpretable.

Determinista: sin red, sin fecha del sistema, sin aleatoriedad.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Optional

from ..contracts import CONTRACT_VERSION, EvidenceFragment, SourceEpisode
from ..extraction import DeterministicExtractor, ExtractionContext, Lexicon, LexiconEntry
from .gate6_dev_corpus import load_dev_cases
from .gate6_generalization_corpus import load_generalization

WORKSPACE = "gate6-eval"
ASSET_ID = "asset:gate6-eval"

#: Palabras funcionales que pueden ir capitalizadas por ir al principio de la
#: frase o dentro de un nombre propio, pero que nunca son, ellas solas, una
#: entidad. Clase cerrada del espanol (determinantes, preposiciones y
#: conjunciones frecuentes); no es vocabulario de ningun corpus.
_FUNCTION_WORDS = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas", "lo", "al", "del",
    "de", "en", "y", "e", "o", "u", "que", "si", "no", "se", "su", "sus",
    "por", "para", "con", "sin", "sobre", "tras", "desde", "hasta", "segun",
    "es", "fue", "era", "ni", "pero", "aunque", "mientras", "cuando", "donde",
    "como", "quien", "cual", "esa", "ese", "esta", "este", "aquel", "aquella",
    "nadie", "nada", "todo", "toda", "todos", "todas", "mas", "menos", "ya",
})

_CAPITALIZED = r"[A-ZÁÉÍÓÚÑÜ][\wáéíóúñü]*"
_LINKER = r"(?:de|del|de\s+la|de\s+los|de\s+las|la|los|las|y)"
_NAME_RE = re.compile(
    rf"{_CAPITALIZED}(?:\s+(?:{_LINKER}\s+)?{_CAPITALIZED})*"
)


def proper_name_candidates(text: str) -> list[str]:
    """Nombres propios de superficie del texto (andamiaje de medicion).

    Reconocedor deliberadamente simple y declarado: secuencias capitalizadas
    con enlaces ("Orden del Alba", "Casa Verrant"), sin el determinante
    inicial y sin las palabras funcionales sueltas. No pretende ser un NER;
    su unico trabajo es dar al extractor menciones que anclar para que la
    medicion de esta capa tenga cobertura distinta de cero.
    """
    out: list[str] = []
    for match in _NAME_RE.finditer(text or ""):
        span = match.group(0).strip()
        palabras = span.split()
        # se cae el determinante/preposicion inicial ("El Foso Humeante")
        while palabras and palabras[0].lower() in _FUNCTION_WORDS:
            palabras = palabras[1:]
        # y las palabras funcionales de cola ("Kaspar Nune a la" -> "Kaspar Nune")
        while palabras and palabras[-1].lower() in _FUNCTION_WORDS:
            palabras = palabras[:-1]
        if not palabras:
            continue
        candidato = " ".join(palabras)
        if candidato not in out:
            out.append(candidato)
    return out


def _hash(seed: str) -> dict[str, str]:
    return {
        "algorithm": "sha256",
        "value": hashlib.sha256(seed.encode("utf-8")).hexdigest(),
    }


def _trace(step: str, produced: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "step": step,
            "provider": "local",
            "name": "s9k.eval.gate6",
            "version": "3.0.0",
            "model": None,
            "produced": list(produced),
        }
    ]


def build_context(
    case_id: str, text: str, *, extra_entities: Iterable[str] = ()
) -> ExtractionContext:
    """Contexto de extraccion de UN caso: un episodio, un fragmento, un lexico."""
    episode = SourceEpisode(
        contract_version=CONTRACT_VERSION,
        workspace=WORKSPACE,
        source_asset_id=ASSET_ID,
        source_hash=_hash(ASSET_ID),
        provider_trace=_trace("normalize", ("text",)),
        produced_by_step="normalize",
        episode_id=f"ep:{case_id}",
        asset_id=ASSET_ID,
        sequence=0,
        modality="TEXT",
        text=text,
        page=None,
        bbox=None,
        time_start=None,
        time_end=None,
        previous_episode_id=None,
        next_episode_id=None,
        speaker=None,
        turn=None,
        table=None,
        quality={"score": 0.95, "flags": []},
        content_hash=_hash(case_id + text),
    )
    episode.validate()
    fragment = EvidenceFragment(
        contract_version=CONTRACT_VERSION,
        workspace=WORKSPACE,
        source_asset_id=ASSET_ID,
        source_hash=_hash(ASSET_ID),
        provider_trace=_trace("fragment", ("literal_text",)),
        produced_by_step="fragment",
        fragment_id=f"frag:{case_id}:0",
        episode_id=episode.episode_id,
        literal_text=text,
        normalized_text=text.lower(),
        start=0,
        end=len(text),
        bbox=None,
        time_start=None,
        time_end=None,
        frame_id=None,
        page=None,
        media_type="EMBEDDED_TEXT",
        confidence=0.99,
    )
    fragment.validate()

    superficies: list[str] = []
    for surface in (*extra_entities, *proper_name_candidates(text)):
        if surface and surface not in superficies:
            superficies.append(surface)
    lexicon = Lexicon(
        [LexiconEntry(s, None, (), 0.9, "gate6-eval") for s in superficies]
    )
    return ExtractionContext(
        workspace=WORKSPACE,
        episodes=[episode],
        fragments=[fragment],
        profile=None,
        lexicon=lexicon,
    )


def _run_case(
    case_id: str, text: str, *, extra_entities: Iterable[str] = ()
) -> dict[str, Any]:
    """Salida del extractor REAL sobre un caso, resumida para el informe."""
    ctx = build_context(case_id, text, extra_entities=extra_entities)
    out = DeterministicExtractor().extract(ctx)
    claims = [c for c in out.claims if not c.abstained]
    hints = sorted({c.epistemic_status_hint for c in claims})
    asserted_sin_revision = [
        c
        for c in claims
        if c.epistemic_status_hint == "ASSERTED" and c.review_required is False
    ]
    asserted_total = [c for c in claims if c.epistemic_status_hint == "ASSERTED"]
    return {
        "case_id": case_id,
        "claims_emitted": len(claims),
        "abstentions": len(out.claims) - len(claims),
        "epistemic_hints": hints,
        "asserted_claims": len(asserted_total),
        "asserted_without_review": len(asserted_sin_revision),
    }


def _summarize(rows: list[dict[str, Any]], gold_forbids: dict[str, bool]) -> dict[str, Any]:
    cubiertos = [r for r in rows if r["claims_emitted"] > 0]
    prohibidos = [r for r in rows if gold_forbids[r["case_id"]]]
    prohibidos_cubiertos = [r for r in prohibidos if r["claims_emitted"] > 0]
    sin_revision = [r for r in prohibidos if r["asserted_without_review"] > 0]
    asertados = [r for r in prohibidos if r["asserted_claims"] > 0]
    return {
        "cases": len(rows),
        "coverage": {
            "cases_with_claims": len(cubiertos),
            "cases_total": len(rows),
            "gold_forbids_cases": len(prohibidos),
            "gold_forbids_cases_with_claims": len(prohibidos_cubiertos),
        },
        "violations_written_without_review": sorted(
            r["case_id"] for r in sin_revision
        ),
        "violations_asserted": sorted(r["case_id"] for r in asertados),
        "rows": rows,
    }


def measure_dev_extractor() -> dict[str, Any]:
    corpus = load_dev_cases(verify=True)
    rows = [_run_case(c["case_id"], c["text"]) for c in corpus["cases"]]
    gold_forbids = {
        c["case_id"]: c["expected"] not in ("WRITE_POSITIVE", "WRITE_NEGATIVE")
        for c in corpus["cases"]
    }
    summary = _summarize(rows, gold_forbids)
    summary.update({
        "split": corpus["split"],
        "provenance": corpus["provenance"],
        "layer": "deterministic_extractor",
    })
    return summary


def measure_generalization_extractor() -> dict[str, Any]:
    items = load_generalization(verify=True)
    rows = [
        _run_case(i.case_id, i.text, extra_entities=(i.subject, i.object))
        for i in items
    ]
    gold_forbids = {i.case_id: i.expected_class == "NON_FACTIVE" for i in items}
    summary = _summarize(rows, gold_forbids)
    summary.update({
        "split": "gate6-generalization-compositional",
        "layer": "deterministic_extractor",
    })
    return summary


def measure_extractor_layer() -> dict[str, Any]:
    """Invariante fail-closed medido contra la salida real del extractor."""
    dev = measure_dev_extractor()
    gen = measure_generalization_extractor()
    sin_revision = [
        {"corpus": "dev", "case_id": cid}
        for cid in dev["violations_written_without_review"]
    ] + [
        {"corpus": "generalization", "case_id": cid}
        for cid in gen["violations_written_without_review"]
    ]
    asertados = [
        {"corpus": "dev", "case_id": cid} for cid in dev["violations_asserted"]
    ] + [
        {"corpus": "generalization", "case_id": cid}
        for cid in gen["violations_asserted"]
    ]
    return {
        "layer": "deterministic_extractor",
        "description": (
            "invariante fail-closed medido contra la salida REAL de "
            "DeterministicExtractor (no contra el clasificador): ningun caso "
            "cuyo gold exige abstenerse debe producir un claim no abstenido "
            "con epistemic_status_hint=ASSERTED"
        ),
        "corpora": {"dev": dev, "generalization": gen},
        "violations_written_without_review": sin_revision,
        "violations_asserted": asertados,
        "status": "CONFORME" if not asertados else "NO CONFORME",
        "caveats": [
            "las menciones se anclan con un lexico construido por caso a partir "
            "de nombres propios de superficie (`proper_name_candidates`): es "
            "andamiaje de medicion, no parte del extractor",
            "la cobertura (`coverage`) se publica al lado de las violaciones: "
            "un cero sobre pocos casos cubiertos no es la misma evidencia que "
            "un cero sobre muchos",
        ],
    }


__all__ = [
    "build_context",
    "measure_dev_extractor",
    "measure_extractor_layer",
    "measure_generalization_extractor",
    "proper_name_candidates",
]
