# -*- coding: utf-8 -*-
"""Medicion en SOMBRA de la precision del subconjunto-acuerdo determinista∧NVIDIA.

Pregunta del bloque (encargo del operador): sobre el MISMO gold congelado de la
puerta 4 (split `negation`, 57 claims / 56 casos evaluables), si el carril
DETERMINISTA (ablacion `local_only`, la cadena E2E real -- normalizador,
`extraction/cues.py`, motor, resolutor, writer en DRY-RUN -- la misma que mide
el 0.607 de B2) y el carril NVIDIA (ablacion `external_only`) llegan
INDEPENDIENTEMENTE al MISMO claim (mismo sujeto/objeto, predicado compatible,
evidencia anclada), ¿que tan fiable es ese subconjunto de acuerdo? Y que
fraccion del gold cubre.

Este script es SOMBRA PURA: el writer de `pipeline.runner.run_one` va siempre
en DRY-RUN (sin bandera que lo cambie), no decide ninguna politica y no toca
el gold (`load_dev_gold(verify=True)` lo verifica por hash antes de leerlo).

## Hallazgo de diseno que dicta como esta escrito este script

La primera version de este script uso `benchmarks.harness.score_extractor`
(via `pipeline.bundle.to_bundle`) para emparejar los claims predichos con el
gold, igual que hace `measure_b3.py`. Con la cadena E2E real (`local_only`,
`entry="raw"`) esa via da **cobertura estructuralmente cero**: el normalizador
acuna sus propios `episode_id` (`ep-<hash>`) a partir de los BYTES de entrada,
y `score_extractor` exige coincidencia EXACTA de `episode_id` para emparejar
menciones (`benchmarks.matching.match_spans`, `span_mode="exact"`). El
runner E2E CONGELADO que mide el 0.607 real de B2 (`artifacts/v3-final-
validation/gate4_negation_measure.py`) NO tiene este problema porque **nunca
usa `score_extractor`**: implementa su PROPIO alineamiento en tres fases
(`episode_alignment` por texto literal, `mention_alignment` por span + fallback
de superficie, `claim_alignment` por menciones-gold traducidas) precisamente
para resolver este desajuste estructural. Reimplementarlo hubiera sido
duplicar ~150 lineas ya escritas, revisadas y con tests propios; en su lugar,
este script IMPORTA esas tres funciones (mas `build_rows`, que arma una fila
por claim gold evaluable con la decision REAL del motor: `ACCEPT` / `REVIEW`
/ `REJECT` / sin cobertura) desde el runner congelado, vía
`knowledge_v3.eval._frozen_runner.load()` -- el MISMO cargador-por-ruta que ya
usan `dev_corpus.py` y `harness.py` para no fijar el nombre del split a mano.
Nunca se importa el runner como paquete ni se copia una linea de su codigo;
se usa por ruta, de solo lectura, exactamente como el resto del repo ya hace.

Consecuencia importante para la lectura de esta medicion: la fila de cada
carril trae `predicted_decision` -- el veredicto REAL del motor
(`engine/decision.py`), que YA incorpora la conexion de la puerta 6
(`review_required` + `epistemic_status_hint` degradado -> nunca `ACCEPT`,
ver docs/v3/46 P0) y la verificacion de evidencia literal
(`EVIDENCE_LITERAL_VERIFIED`). Por eso el criterio de ACUERDO de este bloque
usa `predicted_decision == "ACCEPT"` en AMBOS carriles como el filtro de
factividad+evidencia-anclada: es la MISMA puerta que ya usa produccion para
decidir si un claim se escribiria, no una reimplementacion paralela de esa
regla.

## Lo que se REUTILIZA (nada de esto es nuevo aqui)

* `knowledge_v3.eval.dev_corpus.load_dev_gold` -- el gold congelado (split
  `negation`), verificado por hash.
* `knowledge_v3.pipeline.runner.run_one` -- la via DESIGNADA en B3-gate4
  (docs/v3/40) para correr la cadena COMPLETA con un proveedor externo sobre
  el MISMO split, demostrada por `test_gate4_b3_adversarial.py`. Se invoca
  dos veces: `ablation="local_only"` (determinista real) y
  `ablation="external_only"` (NVIDIA), ambas `entry="raw"`, MISMO workspace
  que usa el runner congelado (`bench-negation`).
* `scripts.gate4.measure_b3.make_b3_port` -- retry/metering/cache del carril
  NVIDIA (backoff exponencial, timeout duro, cache en disco por hash de
  peticion). Reutilizado TAL CUAL: este script no reimplementa transporte.
* El runner E2E congelado (via `_frozen_runner.load()`, de solo lectura):
  `episode_alignment`, `mention_alignment`, `claim_alignment`, `build_rows`
  -- el alineamiento de tres fases y la fila-por-claim con la decision real
  del motor, exactamente como los usa `analyse()` para medir B0-B2.

## Lo que este script SI anade

* El criterio PRINCIPAL de este bloque es el **acuerdo a nivel de
  CONTENIDO**: mismo claim gold, predicado compatible, misma polaridad --
  SIN exigir que ningun motor de decision (`ACCEPT`/`REVIEW`/`ABSTAIN`)
  coincida. El par de decisiones de cada caso (`ACCEPT/ACCEPT`,
  `REVIEW/REVIEW`, `ACCEPT/REVIEW`, `ABSTAIN/x`, ...) se publica como
  ATRIBUTO (`decision_pair`) y se desglosa aparte: es esa tabla, no un
  agregado, la que responde la pregunta del operador. El criterio ORIGINAL
  de este bloque (exigir `ACCEPT` real en AMBOS carriles) se conserva como
  vista SECUNDARIA (`acuerdo_con_accept`), **declarada tautologica por el
  dictamen del revisor**: multiplica dos eventos ya raros del motor (la
  puerta 4 mide un recall de autoaprobacion bajo), asi que su interseccion
  tiende a vaciarse por construccion del filtro, no por la hipotesis medida.
* Dentro de `discrepancia`, la separacion entre `polaridades_opuestas_
  activas` (ambos carriles predicen algo activo, ninguno abstiene, y la
  polaridad difiere -- la discrepancia semantica "dura") y `abstain_vs_
  afirma` (un carril abstiene, el otro no): `ABSTAIN` da `negated=False`
  por CONVENCION del programa (no una polaridad comprobada), asi que
  mezclarlo con una discrepancia activa exagera el desacuerdo real.
* Precision y recall del conjunto `acuerdo_contenido` contra el gold, con
  el desglose completo por par de decisiones y el listado de casos de cada
  conjunto.
* Cache PROPIA del bloque (`artifacts/agreement/cache/` por defecto, NUNCA
  compartida con `artifacts/gate4-program/b3-cache/` de B3): una corrida
  `--mock` de este script y una de `measure_b3.py` escriben con la MISMA
  clave (hash de `system+prompt+purpose`) si el prompt coincide, asi que
  compartir directorio de cache entre bloques deja huella cruzada de
  cualquiera de los dos -- la causa real de una contaminacion detectada por
  el revisor en una version anterior de este artefacto (ver docs/v3/47).

Uso (desde la raiz del repo):

    export S9K_NVIDIA_ENABLED=true
    export S9K_NVIDIA_API_KEY=...   # nunca en la linea de comandos ni commiteada
    PYTHONPATH=data-engine/app python3 scripts/agreement/measure_agreement.py \
        --out-dir artifacts/agreement --out-name agreement-shadow \
        --cache artifacts/agreement/cache --concurrency 2

`--mock` sustituye NVIDIA por un puerto guionizado (sin red, sin key): sirve
para probar el script y para los tests unitarios. Los tests SIEMPRE apuntan
`--cache` a un directorio temporal propio, nunca al de la corrida real, por
la misma razon de arriba.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Optional

_APP = Path(__file__).resolve().parents[2] / "data-engine" / "app"
_GATE4_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "gate4"
for _p in (_APP, _GATE4_SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import measure_b3 as b3  # noqa: E402 -- reutiliza make_b3_port y _percentile

from knowledge_v3.benchmarks.matching import MatchConfig  # noqa: E402
from knowledge_v3.eval import _frozen_runner as _fr  # noqa: E402
from knowledge_v3.eval.dev_corpus import load_dev_gold  # noqa: E402
from knowledge_v3.pipeline.runner import run_one  # noqa: E402

#: Split y workspace, leidos del runner congelado (nunca escritos aqui a
#: mano -- misma disciplina que `measure_b3.py` y `dev_corpus.py`).
_FROZEN = _fr.load()
SPLIT = str(_FROZEN.SPLIT)
_WORKSPACE = str(_FROZEN.WORKSPACE)

#: Configuracion de emparejamiento: LA MISMA que usa `analyse()` en el runner
#: congelado (span en modo overlap, sin componentes extra en la clave del
#: claim). Copiar los VALORES, no el objeto: `MatchConfig` es inmutable y
#: publico, y construir uno propio con los mismos parametros no es indirectar
#: sobre estado interno del runner, es declarar el mismo contrato.
def _match_config(gold) -> MatchConfig:
    return MatchConfig(
        span_mode="overlap",
        overlap_threshold=0.5,
        claim_key_extra=(),
        symmetric_predicates=gold.symmetric_predicates,
    )


# --------------------------------------------------------------------------
# Vista por carril: gold_claim_id -> fila real del motor (via runner congelado)
# --------------------------------------------------------------------------
def _lane_rows(gold, result, config: MatchConfig) -> dict[str, dict[str, Any]]:
    """Filas por claim gold, alineadas y puntuadas con las funciones REALES
    del runner congelado (`episode_alignment` / `mention_alignment` /
    `claim_alignment` / `build_rows`), aplicadas al `PipelineResult` de ESTE
    carril. Ver el docstring del modulo: es la unica via que no tropieza con
    el desajuste de `episode_id` entre el normalizador y el gold.
    """
    episodes = _FROZEN.episode_alignment(gold, result)
    mentions, mention_match, fallback = _FROZEN.mention_alignment(gold, result, episodes, config)
    pairs, _claim_match = _FROZEN.claim_alignment(gold, result, mentions)
    rows = _FROZEN.build_rows(gold, result, pairs)
    by_id = {r["gold_claim_id"]: r for r in rows}
    diag = {
        "episodes_aligned": len(episodes),
        "episodes_predicted": len(result.episodes),
        "mentions_span_tp": mention_match.tp,
        "mentions_span_fp": mention_match.fp,
        "mentions_span_fn": mention_match.fn,
        "mentions_surface_fallback": fallback,
        "claims_matched": len(pairs),
        "rows": len(rows),
        "covered_rows": sum(1 for r in rows if r["covered"]),
    }
    return by_id, diag


def _predicate_compatible(det: dict[str, Any], nvidia: dict[str, Any]) -> bool:
    """Predicado top-1 de cada carril (post-motor: `predicted_predicate`).

    Si alguno de los dos carriles no cubrio el caso con predicado resuelto
    (`None`), se declara compatible-por-omision: la incompatibilidad solo se
    puede afirmar cuando AMBOS carriles se comprometen a un predicado y
    difieren -- limitacion explicita, no un acierto fabricado (docs/v3/47).
    """
    dp, np_ = det.get("predicted_predicate"), nvidia.get("predicted_predicate")
    if dp is None or np_ is None:
        return True
    return dp == np_


#: `predicted_decision` que NO es una asercion activa: `build_rows` (runner
#: congelado) da `negated=False` por CONVENCION cuando el motor abstiene
#: (`decision.negated` no se establece de verdad para `ABSTAIN`), no porque el
#: carril haya comprobado la polaridad. Tratar ese `False` como si fuera una
#: prediccion de polaridad falsearia tanto las precisiones de `solo_det`/
#: `solo_nvidia` como el criterio de "misma polaridad" del acuerdo -- de ahi
#: que este modulo etiquete cada caso con `is_abstain` y lo declare en las
#: notas en vez de dejarlo mezclado en silencio.
_ABSTAIN = "ABSTAIN"


# --------------------------------------------------------------------------
# Los conjuntos del bloque: acuerdo A NIVEL DE CONTENIDO (mismo claim +
# predicado compatible + misma polaridad, SIN exigir ACCEPT de ambos motores)
# como vista PRINCIPAL, con el par de decisiones (ACCEPT/ACCEPT, REVIEW/
# REVIEW, ACCEPT/REVIEW, ABSTAIN/x...) publicado como ATRIBUTO de cada caso y
# desglosado aparte. `acuerdo_con_accept` (el criterio original) se conserva
# como vista SECUNDARIA, documentada como tautologica: exigir `ACCEPT` real
# en ambos carriles multiplica dos eventos ya raros del motor (la puerta 4
# mide un recall de autoaprobacion bajo), asi que su interseccion tiende a
# vaciarse por construccion del filtro, no por la hipotesis del bloque.
# --------------------------------------------------------------------------
def compute_agreement(det_rows: dict[str, Any], nvidia_rows: dict[str, Any]) -> dict[str, Any]:
    gold_ids = sorted(det_rows.keys())
    assert gold_ids == sorted(nvidia_rows.keys()), (
        "los dos carriles corren sobre el MISMO gold: el conjunto de "
        "claim_id evaluables no puede diferir entre carriles"
    )

    acuerdo_contenido: list[dict[str, Any]] = []
    solo_det: list[dict[str, Any]] = []
    solo_nvidia: list[dict[str, Any]] = []
    polaridades_opuestas_activas: list[dict[str, Any]] = []
    abstain_vs_afirma: list[dict[str, Any]] = []
    predicado_incompatible: list[dict[str, Any]] = []
    sin_cubrir: list[str] = []

    for gid in gold_ids:
        d, n = det_rows[gid], nvidia_rows[gid]
        gold_negated = d["expected_negated"]  # identico en ambas filas: mismo gold

        if not d["covered"] and not n["covered"]:
            sin_cubrir.append(gid)
            continue
        if d["covered"] and not n["covered"]:
            solo_det.append({
                "claim_id": gid,
                "negated": d["predicted_negated"],
                "decision": d["predicted_decision"],
                "is_abstain": d["predicted_decision"] == _ABSTAIN,
                "correct": d["predicted_negated"] == gold_negated,
            })
            continue
        if n["covered"] and not d["covered"]:
            solo_nvidia.append({
                "claim_id": gid,
                "negated": n["predicted_negated"],
                "decision": n["predicted_decision"],
                "is_abstain": n["predicted_decision"] == _ABSTAIN,
                "correct": n["predicted_negated"] == gold_negated,
            })
            continue

        # Ambos carriles cubren el mismo claim gold.
        det_abstain = d["predicted_decision"] == _ABSTAIN
        nvidia_abstain = n["predicted_decision"] == _ABSTAIN
        same_polarity = d["predicted_negated"] == n["predicted_negated"]
        pred_ok = _predicate_compatible(d, n)
        decision_pair = f"{d['predicted_decision']}/{n['predicted_decision']}"

        case = {
            "claim_id": gid,
            "det_negated": d["predicted_negated"],
            "nvidia_negated": n["predicted_negated"],
            "det_decision": d["predicted_decision"],
            "nvidia_decision": n["predicted_decision"],
            "decision_pair": decision_pair,
            "det_predicate": d["predicted_predicate"],
            "nvidia_predicate": n["predicted_predicate"],
            "gold_negated": gold_negated,
        }

        if not pred_ok:
            case["reason"] = "predicado_incompatible"
            predicado_incompatible.append(case)
        elif same_polarity:
            # ACUERDO A NIVEL DE CONTENIDO: mismo claim, predicado compatible,
            # misma polaridad -- SIN exigir que ambos motores acepten. El par
            # de decisiones queda publicado en `decision_pair` para que el
            # desglose por celda (ACCEPT/ACCEPT, REVIEW/REVIEW, ABSTAIN/
            # ABSTAIN, ...) sea la vista que responde la pregunta del
            # operador, no un agregado que la esconde.
            case["correct"] = d["predicted_negated"] == gold_negated
            case["es_acuerdo_con_accept"] = decision_pair == "ACCEPT/ACCEPT"
            case["ambos_abstienen"] = det_abstain and nvidia_abstain
            acuerdo_contenido.append(case)
        elif det_abstain != nvidia_abstain:
            # Uno de los dos NO predice nada activo (ABSTAIN): la polaridad
            # discrepante es, en parte, un artefacto del `negated=False` por
            # convencion del lado que abstiene, no una discrepancia semantica
            # real entre dos afirmaciones activas.
            case["reason"] = "abstain_vs_afirma"
            abstain_vs_afirma.append(case)
        else:
            # Ninguno de los dos abstiene: polaridad realmente opuesta entre
            # dos predicciones ACTIVAS -- la unica discrepancia "dura" del
            # bloque.
            case["reason"] = "polaridad_opuesta_activa"
            polaridades_opuestas_activas.append(case)

    def _set_stats(cases: list[dict[str, Any]]) -> dict[str, Any]:
        tp = sum(1 for c in cases if c.get("correct"))
        fp = sum(1 for c in cases if c.get("correct") is False)
        n_cases = len(cases)
        return {"n": n_cases, "tp": tp, "fp": fp, "precision": round(tp / n_cases, 4) if n_cases else None}

    def _breakdown_by_decision_pair(cases: list[dict[str, Any]]) -> dict[str, Any]:
        pairs = sorted({c["decision_pair"] for c in cases})
        return {
            pair: _set_stats([c for c in cases if c["decision_pair"] == pair])
            for pair in pairs
        }

    evaluable_total = len(gold_ids)
    acuerdo_con_accept = [c for c in acuerdo_contenido if c["es_acuerdo_con_accept"]]
    discrepancia_activa_total = len(polaridades_opuestas_activas)
    discrepancia_total = discrepancia_activa_total + len(abstain_vs_afirma) + len(predicado_incompatible)

    return {
        "evaluable_total": evaluable_total,
        "acuerdo_contenido": {
            **_set_stats(acuerdo_contenido), "cases": acuerdo_contenido,
            "recall_sobre_gold": round(len(acuerdo_contenido) / evaluable_total, 4) if evaluable_total else None,
            "desglose_por_par_de_decisiones": _breakdown_by_decision_pair(acuerdo_contenido),
            "nota": (
                "vista PRINCIPAL del bloque: mismo claim gold + predicado "
                "compatible + misma polaridad, SIN exigir ACCEPT de ningun "
                "motor. El par de decisiones (det/nvidia) de cada caso vive "
                "en `decision_pair`; el desglose por celda es la respuesta a "
                "la pregunta del operador, no el agregado. Los pares "
                "ABSTAIN/ABSTAIN coinciden en polaridad por CONVENCION "
                "(negated=False por defecto en ambos lados, no una "
                "comprobacion real) -- ver `ambos_abstienen` en cada caso."
            ),
        },
        "acuerdo_con_accept": {
            **_set_stats(acuerdo_con_accept), "cases": acuerdo_con_accept,
            "recall_sobre_gold": round(len(acuerdo_con_accept) / evaluable_total, 4) if evaluable_total else None,
            "nota": (
                "vista SECUNDARIA (criterio original de este bloque, "
                "conservado por trazabilidad): subconjunto de "
                "`acuerdo_contenido` donde AMBOS motores dan ACCEPT real. "
                "DECLARADO TAUTOLOGICO por el dictamen del revisor: exigir "
                "ACCEPT en los dos carriles multiplica dos eventos ya raros "
                "del motor (la puerta 4 mide un recall de autoaprobacion "
                "bajo), asi que la interseccion tiende a vaciarse por "
                "construccion del filtro, no por la hipotesis medida. No "
                "usar esta vista para leer 'el acuerdo no sirve': para eso "
                "esta `acuerdo_contenido`."
            ),
        },
        "solo_det": {
            **_set_stats(solo_det), "cases": solo_det,
            "nota_abstain": (
                "las filas con `is_abstain=True` cuentan con `negated=False` "
                "por convencion del programa (build_rows del runner "
                "congelado), no porque el carril haya afirmado una polaridad "
                "activa: su `correct` no debe leerse como precision de "
                "aserciones activas."
            ),
        },
        "solo_nvidia": {
            **_set_stats(solo_nvidia), "cases": solo_nvidia,
            "nota_abstain": (
                "misma convencion que `solo_det`: `is_abstain=True` implica "
                "`negated=False` por defecto, no una polaridad comprobada."
            ),
        },
        "discrepancia": {
            "n": discrepancia_total,
            "polaridades_opuestas_activas": {
                **_set_stats(polaridades_opuestas_activas), "cases": polaridades_opuestas_activas,
                "nota": "ambos carriles predicen algo ACTIVO (ninguno abstiene) y la polaridad difiere: la unica discrepancia semantica 'dura' del bloque.",
            },
            "abstain_vs_afirma": {
                "n": len(abstain_vs_afirma), "cases": abstain_vs_afirma,
                "nota": "un carril abstiene (ABSTAIN, negated=False por convencion) y el otro predice algo activo con polaridad distinta: discrepancia parcialmente artefactual, no dos afirmaciones opuestas.",
            },
            "predicado_incompatible": {
                "n": len(predicado_incompatible), "cases": predicado_incompatible,
                "nota": "mismo claim gold, pero el predicado top-1 de cada carril difiere (ambos lo declaran).",
            },
        },
        "sin_cubrir": {"n": len(sin_cubrir), "claim_ids": sin_cubrir},
    }


# --------------------------------------------------------------------------
# Ejecucion de punta a punta
# --------------------------------------------------------------------------
def build_report(
    *,
    cache_dir: Optional[Path],
    mock: bool,
    timeout_seconds: int,
    concurrency: int,
    price_per_million_tokens_usd: Optional[float],
) -> dict[str, Any]:
    gold = load_dev_gold(verify=True)
    match_config = _match_config(gold)

    # --- carril determinista: cadena E2E real (misma via que mide 0.607) ---
    started_det = time.monotonic()
    _report_det, result_det = run_one(
        gold, "local_only", workspace=_WORKSPACE, entry="raw", run_id=f"agreement-{SPLIT}-local"
    )
    wall_det = int((time.monotonic() - started_det) * 1000)
    det_rows, det_diag = _lane_rows(gold, result_det, match_config)

    # --- carril NVIDIA: mismo puerto instrumentado que B3 --------------------
    port, metering = b3.make_b3_port(cache_dir=cache_dir, mock=mock, timeout_seconds=timeout_seconds)
    started_nvidia = time.monotonic()
    _report_nvidia, result_nvidia = run_one(
        gold, "external_only", workspace=_WORKSPACE, entry="raw",
        run_id=f"agreement-{SPLIT}-external", external_port=port,
    )
    wall_nvidia = int((time.monotonic() - started_nvidia) * 1000)
    nvidia_rows, nvidia_diag = _lane_rows(gold, result_nvidia, match_config)

    agreement = compute_agreement(det_rows, nvidia_rows)

    # --- coste/latencia/cache de la pasada NVIDIA (mismo vocabulario que B3) -
    calls = metering.calls
    real_calls = [c for c in calls if c["ok"]]
    tanda = list(getattr(port, "_data", {}).values()) or real_calls
    latencies = sorted(int(c.get("latency_ms", 0)) for c in tanda) if tanda else []

    def _usage(entry: dict, key: str) -> int:
        usage = entry.get("usage")
        if isinstance(usage, dict):
            return int(usage.get(key, 0) or 0)
        return int(entry.get(key, 0) or 0)

    prompt_tokens = sum(_usage(c, "prompt_tokens") for c in tanda)
    completion_tokens = sum(_usage(c, "completion_tokens") for c in tanda)
    total_tokens = sum(_usage(c, "total_tokens") for c in tanda) or (prompt_tokens + completion_tokens)
    estimated_cost_usd = (
        round(total_tokens / 1_000_000 * price_per_million_tokens_usd, 4)
        if price_per_million_tokens_usd is not None
        else None
    )
    incidents = sorted(set(c.get("error") for c in calls if not c["ok"]))

    report = {
        "titulo": "Precision del subconjunto-acuerdo determinista ∧ NVIDIA (medicion en SOMBRA)",
        "generado_por": "scripts/agreement/measure_agreement.py",
        "split": SPLIT,
        "workspace": _WORKSPACE,
        "mock": mock,
        "gold": {"episodes": len(gold.episodes), "claims": len(gold.claims_for("extractor"))},
        "carriles": {
            "determinista": {
                "ablation": "local_only",
                "nota": "cadena E2E real (normalizador + cues.py + motor + resolutor + writer DRY-RUN), la MISMA via que mide el 0.607 de B2.",
                "wall_ms": wall_det,
                "alineamiento": det_diag,
            },
            "nvidia": {
                "ablation": "external_only",
                "nota": "carril NVIDIA en SOMBRA (nunca escribe, nunca decide), por la MISMA cadena E2E (motor, negacion, evidencia).",
                "wall_ms": wall_nvidia,
                "alineamiento": nvidia_diag,
            },
        },
        "diseno": {
            "criterio_acuerdo_contenido": (
                "VISTA PRINCIPAL. mismo claim_id del gold (alineado via "
                "episode_alignment + mention_alignment + claim_alignment del "
                "runner congelado, reutilizados por ruta), predicado top-1 "
                "compatible (o ausente en algun carril), MISMA polaridad. "
                "NO exige ningun veredicto concreto del motor: el par de "
                "decisiones (ACCEPT/ACCEPT, REVIEW/REVIEW, ACCEPT/REVIEW, "
                "ABSTAIN/x...) se publica como atributo `decision_pair` de "
                "cada caso y se desglosa aparte -- esa tabla es la que "
                "responde la pregunta del operador."
            ),
            "criterio_acuerdo_con_accept": (
                "VISTA SECUNDARIA (criterio original del bloque, conservado "
                "por trazabilidad): subconjunto de acuerdo_contenido donde "
                "AMBOS carriles reciben predicted_decision=='ACCEPT' real del "
                "motor. DECLARADO TAUTOLOGICO por el dictamen del revisor: "
                "exigir ACCEPT de ambos multiplica dos eventos ya raros del "
                "motor (la puerta 4 mide un recall de autoaprobacion bajo), "
                "asi que la interseccion tiende a vaciarse por construccion "
                "del filtro, no por la hipotesis medida."
            ),
            "factividad": (
                "la puerta 6 (review_required + hint epistemico degradado "
                "nunca ACCEPT) sigue actuando dentro del motor real que "
                "produce cada `predicted_decision`; este bloque no la "
                "reimplementa. Lo que cambia respecto de la primera version "
                "es que 'acuerdo' ya NO exige ACCEPT de ambos carriles para "
                "existir: ese filtro se mueve a `acuerdo_con_accept`, la "
                "vista secundaria."
            ),
            "denominador": "56 casos evaluables (convencion B0-B3: se excluye el unico ABSTAIN puro del gold, sin polaridad declarada).",
            "alineamiento_reutilizado": (
                "episode_alignment/mention_alignment/claim_alignment/build_rows "
                "del runner E2E congelado (artifacts/v3-final-validation/"
                "gate4_negation_measure.py), cargado por ruta via "
                "knowledge_v3.eval._frozen_runner.load() -- nunca copiado ni "
                "modificado. Necesario porque score_extractor (benchmarks."
                "harness) exige episode_id identico y la cadena real acuna "
                "ids propios a partir de los bytes de entrada; ver docstring "
                "del modulo."
            ),
        },
        "agreement": agreement,
        "latency": {
            "unit": "ms",
            "measured_calls": len(tanda),
            "real_calls_this_run": len(real_calls),
            "mean": round(statistics.mean(latencies), 1) if latencies else None,
            "p95": round(b3._percentile(latencies, 0.95), 1) if latencies else None,
            "max": latencies[-1] if latencies else None,
        },
        "tokens": {
            "prompt_tokens_total": prompt_tokens,
            "completion_tokens_total": completion_tokens,
            "total_tokens": total_tokens,
            "price_per_million_tokens_usd": price_per_million_tokens_usd,
            "estimated_cost_usd_this_run": estimated_cost_usd,
        },
        "cache": {
            "path": str(cache_dir) if cache_dir else None,
            "calls_real": len(real_calls),
            "calls_failed": len(calls) - len(real_calls),
            "calls_served_from_cache": getattr(port, "hits", 0),
            "calls_missed_cache": getattr(port, "misses", 0),
        },
        "incidencias_api": {
            "transport_retries_used": getattr(metering.inner, "retries_used", 0)
            if hasattr(metering.inner, "retries_used") else 0,
            "hard_timeouts": getattr(metering.inner, "timeouts", 0)
            if hasattr(metering.inner, "timeouts") else 0,
            "failed_calls": len(calls) - len(real_calls),
            "distinct_errors": incidents,
        },
        "lectura_para_la_decision_del_operador": {
            "precision_acuerdo_contenido": agreement["acuerdo_contenido"]["precision"],
            "n_acuerdo_contenido": agreement["acuerdo_contenido"]["n"],
            "recall_acuerdo_contenido_sobre_gold": agreement["acuerdo_contenido"]["recall_sobre_gold"],
            "desglose_acuerdo_contenido_por_par_de_decisiones": agreement["acuerdo_contenido"]["desglose_por_par_de_decisiones"],
            "precision_acuerdo_con_accept_tautologico": agreement["acuerdo_con_accept"]["precision"],
            "n_acuerdo_con_accept_tautologico": agreement["acuerdo_con_accept"]["n"],
            "precision_solo_det": agreement["solo_det"]["precision"],
            "n_solo_det": agreement["solo_det"]["n"],
            "precision_solo_nvidia": agreement["solo_nvidia"]["precision"],
            "n_solo_nvidia": agreement["solo_nvidia"]["n"],
            "n_polaridades_opuestas_activas": agreement["discrepancia"]["polaridades_opuestas_activas"]["n"],
            "n_abstain_vs_afirma": agreement["discrepancia"]["abstain_vs_afirma"]["n"],
            "n_predicado_incompatible": agreement["discrepancia"]["predicado_incompatible"]["n"],
            "n_sin_cubrir": agreement["sin_cubrir"]["n"],
            "evaluable_total": agreement["evaluable_total"],
            "nota": (
                "cifras desnudas, sin recomendacion de politica: esa decision "
                "es del operador. n=56 evaluables es el mismo techo pequeno que "
                "ya declaro el programa de la puerta 4 (dev==test): cualquier "
                "precision de un subconjunto de este tamano tiene un intervalo "
                "ancho, no se trata como una cifra poblacional. La cifra "
                "'estrella' de este bloque es `precision_acuerdo_contenido`, "
                "junto con su desglose por par de decisiones -- NO "
                "`precision_acuerdo_con_accept_tautologico`, conservada solo "
                "por trazabilidad con la primera version del bloque."
            ),
        },
    }
    return report


def to_markdown(report: dict[str, Any]) -> str:
    ag = report["agreement"]
    lect = report["lectura_para_la_decision_del_operador"]
    lineas = [
        "# Medicion en sombra: precision del subconjunto-acuerdo determinista ∧ NVIDIA",
        "",
        f"Split: `{report['split']}` (workspace `{report['workspace']}`) -- "
        f"{report['gold']['claims']} claims / {report['gold']['episodes']} episodios "
        "(gold congelado, verificado por hash). "
        f"Denominador evaluable: {ag['evaluable_total']} (convencion B0-B3).",
        "",
        "Generado por `scripts/agreement/measure_agreement.py`. Ninguna cifra de este",
        "documento se escribe a mano. Modo SOMBRA pura: ningun carril escribe en Neo4j",
        "ni decide politica; esto SOLO mide.",
        "",
        "## Vista PRINCIPAL: acuerdo a nivel de CONTENIDO, desglosado por par de decisiones",
        "",
        f"Mismo claim gold + predicado compatible + misma polaridad, SIN exigir ACCEPT de",
        f"ningun motor. n={ag['acuerdo_contenido']['n']}, "
        f"precision global={ag['acuerdo_contenido']['precision']}, "
        f"recall sobre el gold={ag['acuerdo_contenido']['recall_sobre_gold']} "
        f"({ag['acuerdo_contenido']['n']}/{ag['evaluable_total']}).",
        "",
        "| par de decisiones (det/nvidia) | n | tp | fp | precision |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for pair, stats in ag["acuerdo_contenido"]["desglose_por_par_de_decisiones"].items():
        lineas.append(f"| {pair} | {stats['n']} | {stats['tp']} | {stats['fp']} | {stats['precision']} |")
    lineas += [
        "",
        f"nota: {ag['acuerdo_contenido']['nota']}",
        "",
        "## Vista SECUNDARIA (tautologica, conservada por trazabilidad): acuerdo_con_accept",
        "",
        f"n={ag['acuerdo_con_accept']['n']}, precision={ag['acuerdo_con_accept']['precision']}, "
        f"recall sobre el gold={ag['acuerdo_con_accept']['recall_sobre_gold']}.",
        "",
        f"nota: {ag['acuerdo_con_accept']['nota']}",
        "",
        "## Otros conjuntos",
        "",
        "| conjunto | n | tp | fp | precision |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| solo-det | {ag['solo_det']['n']} | {ag['solo_det']['tp']} | {ag['solo_det']['fp']} | {ag['solo_det']['precision']} |",
        f"| solo-nvidia | {ag['solo_nvidia']['n']} | {ag['solo_nvidia']['tp']} | {ag['solo_nvidia']['fp']} | {ag['solo_nvidia']['precision']} |",
        f"| discrepancia: polaridades opuestas ACTIVAS | {ag['discrepancia']['polaridades_opuestas_activas']['n']} | {ag['discrepancia']['polaridades_opuestas_activas']['tp']} | {ag['discrepancia']['polaridades_opuestas_activas']['fp']} | {ag['discrepancia']['polaridades_opuestas_activas']['precision']} |",
        f"| discrepancia: abstain vs afirma | {ag['discrepancia']['abstain_vs_afirma']['n']} | -- | -- | -- |",
        f"| discrepancia: predicado incompatible | {ag['discrepancia']['predicado_incompatible']['n']} | -- | -- | -- |",
        f"| sin_cubrir (ningun carril propuso nada emparejable) | {ag['sin_cubrir']['n']} | -- | -- | -- |",
        "",
        f"- nota solo-det: {ag['solo_det']['nota_abstain']}",
        f"- nota solo-nvidia: {ag['solo_nvidia']['nota_abstain']}",
        "",
        "## Diseno",
        "",
        f"- criterio de acuerdo (vista principal): {report['diseno']['criterio_acuerdo_contenido']}",
        f"- criterio de acuerdo_con_accept (vista secundaria, tautologica): {report['diseno']['criterio_acuerdo_con_accept']}",
        f"- factividad (puerta 6): {report['diseno']['factividad']}",
        f"- alineamiento reutilizado: {report['diseno']['alineamiento_reutilizado']}",
        "",
        "## Casos: polaridades opuestas ACTIVAS (discrepancia semantica dura)",
        "",
        "| claim_id | det negated | nvidia negated | gold negated |",
        "| --- | --- | --- | --- |",
    ]
    for c in ag["discrepancia"]["polaridades_opuestas_activas"]["cases"]:
        lineas.append(f"| {c['claim_id']} | {c['det_negated']} | {c['nvidia_negated']} | {c['gold_negated']} |")
    lineas += [
        "",
        "## Casos: abstain vs afirma (un carril abstiene, el otro predice algo activo)",
        "",
        "| claim_id | det decision | nvidia decision | det negated | nvidia negated | gold negated |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for c in ag["discrepancia"]["abstain_vs_afirma"]["cases"]:
        lineas.append(
            f"| {c['claim_id']} | {c['det_decision']} | {c['nvidia_decision']} | "
            f"{c['det_negated']} | {c['nvidia_negated']} | {c['gold_negated']} |"
        )
    lineas += [
        "",
        "## Coste / latencia / cache de la pasada NVIDIA",
        "",
        f"- llamadas medidas (tanda completa): {report['latency']['measured_calls']}",
        f"- reales en esta corrida: {report['latency']['real_calls_this_run']}",
        f"- latencia media: {report['latency']['mean']} ms, p95: {report['latency']['p95']} ms",
        f"- tokens totales: {report['tokens']['total_tokens']}",
        f"- servidas desde cache: {report['cache']['calls_served_from_cache']}",
        f"- llamadas reales (miss de cache): {report['cache']['calls_missed_cache']}",
        f"- llamadas fallidas: {report['cache']['calls_failed']}",
        f"- reintentos de transporte: {report['incidencias_api']['transport_retries_used']}",
        f"- timeouts duros: {report['incidencias_api']['hard_timeouts']}",
        f"- errores distintos: {report['incidencias_api']['distinct_errors'] or 'ninguno'}",
        "",
        "## Lectura para la decision del operador (cifras desnudas, sin recomendacion)",
        "",
        f"- precision del acuerdo de CONTENIDO (vista principal): {lect['precision_acuerdo_contenido']} (n={lect['n_acuerdo_contenido']})",
        f"- recall del acuerdo de contenido sobre el gold: {lect['recall_acuerdo_contenido_sobre_gold']} ({lect['n_acuerdo_contenido']}/{lect['evaluable_total']})",
        f"- precision del acuerdo_con_accept (vista secundaria, tautologica): {lect['precision_acuerdo_con_accept_tautologico']} (n={lect['n_acuerdo_con_accept_tautologico']})",
        f"- precision solo-det: {lect['precision_solo_det']} (n={lect['n_solo_det']})",
        f"- precision solo-nvidia: {lect['precision_solo_nvidia']} (n={lect['n_solo_nvidia']})",
        f"- polaridades opuestas activas (discrepancia dura): {lect['n_polaridades_opuestas_activas']}",
        f"- abstain vs afirma: {lect['n_abstain_vs_afirma']}",
        f"- predicado incompatible: {lect['n_predicado_incompatible']}",
        f"- sin cubrir por ningun carril: {lect['n_sin_cubrir']}",
        f"- nota: {lect['nota']}",
    ]
    return "\n".join(lineas) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Medicion en sombra del subconjunto-acuerdo determinista+NVIDIA.")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--out-name", default="agreement-shadow")
    parser.add_argument("--cache", default="artifacts/agreement/cache", help="dir de cache JSON PROPIO de este bloque (nunca compartido con artifacts/gate4-program/b3-cache/ de B3: ver docstring del modulo)")
    parser.add_argument("--mock", action="store_true", help="puerto guionizado (sin red, sin key)")
    parser.add_argument("--timeout-seconds", type=int, default=b3.EPISODE_TIMEOUT_SECONDS)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--price-per-million-tokens-usd", type=float, default=None)
    args = parser.parse_args(argv)

    if args.concurrency > 2:
        parser.error("--concurrency no puede superar 2 (para no gatillar rate limits de NVIDIA)")

    if not args.mock and os.environ.get("S9K_NVIDIA_API_KEY", "").strip() == "":
        print("ERROR: S9K_NVIDIA_API_KEY ausente en el entorno; usa --mock para probar sin red.", file=sys.stderr)
        return 2

    cache_dir = Path(args.cache) if args.cache else None
    if cache_dir:
        cache_dir = cache_dir / "responses.json" if cache_dir.is_dir() or not cache_dir.suffix else cache_dir

    report = build_report(
        cache_dir=cache_dir,
        mock=args.mock,
        timeout_seconds=args.timeout_seconds,
        concurrency=args.concurrency,
        price_per_million_tokens_usd=args.price_per_million_tokens_usd,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.out_name}.json").write_text(payload, encoding="utf-8")
        (out / f"{args.out_name}.md").write_text(to_markdown(report), encoding="utf-8")
        print(f"escrito en {out}/{args.out_name}.{{json,md}}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
