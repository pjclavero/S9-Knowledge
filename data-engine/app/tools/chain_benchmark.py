# -*- coding: utf-8 -*-
"""Driver de la CADENA COMPLETA: extractor REAL de entidades -> motor de relaciones.

QUE MIDE ESTO Y POR QUE EXISTE
------------------------------
El arnes autoritativo de relaciones (`relations/benchmark/`) alimenta el pipeline
R8 con entidades DERIVADAS DEL GROUND TRUTH (`runner.derive_entities`): le regala
al motor las menciones perfectas, con su `id`, su `type` y sus offsets exactos.
Todas las cifras publicadas (B1, H1, H2) son, por tanto, una COTA OPTIMISTA: nadie
habia medido que ocurre cuando las entidades las produce el extractor real.

Este driver hace exactamente esa ablacion, sobre los MISMOS corpus y con las
MISMAS funciones de puntuacion:

    A) `gt_perfect`      -> entidades de `runner.derive_entities` (CONTROL, ya medido)
    B) `extractor_strict`-> entidades REALES del extractor, politica de ids ESTRICTA
    C) `extractor_lax`   -> entidades REALES del extractor, politica de ids LAXA

REGLAS DE CONSTRUCCION (lo que este fichero NO hace)
----------------------------------------------------
  * NO modifica `relations/benchmark/` ni ningun corpus ni ningun umbral.
  * NO reimplementa metricas: importa `benchmark.matching` y `benchmark.metrics`
    a traves de `benchmark.report.build_report`, que es el mismo ensamblador que
    usa la CLI autoritativa.
  * NO reimplementa el motor: llama a `relations.pipeline.run_pipeline`.
  * NO reimplementa el extractor: llama a `review.extractor.extract_from_segments`.
  * NO abre red: proveedores SIEMPRE deshabilitados (solo modos de `runner.MODES`).

DECISIONES METODOLOGICAS (todas sesgadas EN CONTRA de una cifra bonita, salvo
donde se dice explicitamente lo contrario)
-------------------------------------------------------------------------------
1. SEGMENTACION. Igual que el arnes: UN segmento por fuente, `segment_id ==
   source_id`, texto completo. Asi la unica variable que cambia entre A y B/C es
   la PROCEDENCIA DE LAS ENTIDADES. No se ejecutan el segmentador ni el
   clasificador reales: el segmento se construye ya clasificado con
   `should_extract=True`. Esto FAVORECE al extractor (no puede perder texto por
   una mala clasificacion).

2. OFFSETS. El extractor NO emite offsets de caracter: `review.models.Candidate`
   solo lleva `name`, `entity_type`, `confidence` y `evidence` (200 primeros
   caracteres del segmento). Se RECUPERAN localizando el `name` emitido en el
   texto de la fuente con `re.finditer(re.escape(name))`, sensible a mayusculas,
   y generando UNA MENCION POR OCURRENCIA. Es el analogo mas fiel del control,
   que tambien coloca varias menciones del mismo id en varias posiciones.
   SESGO: favorece al extractor (le regala la localizacion exacta de todas sus
   menciones, que en un sistema real habria que resolver).

3. DES-SOLAPAMIENTO. Un conjunto de menciones con spans solapados no es una
   entrada valida para `relations.pairs` (dos "entidades" distintas en la misma
   posicion producen pares espurios de distancia 0). El extractor SI produce
   nombres solapados (p.ej. "Clan Escorpion" por regex y "Clan Escorpión" por la
   tabla de clanes). Regla determinista: ante spans solapados se conserva el MAS
   LARGO; a igual longitud, el de nombre alfabeticamente menor. Los descartados
   se registran en `derivation_notes` con `reason="overlapping_span"`.

4. TIPOS. El extractor emite `Character | Location | Faction | Clan`.
   `Clan` NO pertenece a `relations.contracts.ALLOWED_ENTITY_TYPES` y el pipeline
   lo rechazaria, asi que se mapea `Clan -> Faction` (equivalencia semantica
   directa: los clanes del GT estan anotados como `Faction`). Cualquier otro tipo
   fuera del vocabulario permitido se pasa como `None` (el pipeline lo acepta) y
   se registra. SESGO: `Clan -> Faction` FAVORECE al extractor en
   `types_correct`; sin ese mapeo el pipeline fallaria el segmento entero.
   El extractor NUNCA produce `Object`, `Event` ni `Concept`: esos tipos del GT
   son inalcanzables por construccion.

5. GLOSARIO. `review.extractor._load_glossary` lee `state/glossary.db`, que es
   estado de ejecucion (gitignored) y NO existe en este entorno. El extractor
   corre por tanto SIN GLOSARIO, que es su modo mas conservador. SESGO: en contra
   del extractor respecto a una produccion con glosario poblado.

6. POLITICA DE IDS -- LA DECISION MAS DELICADA. El ground truth referencia
   entidades por `id` (`ysolde`, `clan-roble`). El extractor no produce ids: solo
   cadenas de texto. Sin una politica de emparejamiento, CERO predicciones
   podrian emparejar y el resultado seria trivialmente 0. Se miden DOS politicas
   que ACOTAN la verdad por abajo y por arriba:

     * ESTRICTA (`strict`): una mencion del extractor recibe el id de una mencion
       del GT si y solo si su span coincide EXACTAMENTE (`start` y `end`
       identicos). Es el limite inferior: exige que el extractor delimite la
       mencion con precision de caracter.
     * LAXA (`lax`): una mencion del extractor recibe el id de la mencion del GT
       con la que MAS caracteres solapa (cualquier solape > 0 basta). Es el
       limite superior: cualquier trozo de la mencion correcta vale.

   En AMBAS politicas, una mencion sin correspondencia recibe un id sintetico
   `xx::<slug>` que NUNCA puede emparejar con el GT: contribuye a falsos
   positivos, nunca a verdaderos positivos.

   ADVERTENCIA CAPITAL DE HONESTIDAD: las dos politicas usan el GROUND TRUTH para
   asignar ids. Es un ORACULO DE RESOLUCION DE ENTIDADES que el sistema real no
   tiene (`review/resolver.py` no interviene aqui). Por tanto B y C siguen siendo
   COTAS OPTIMISTAS: miden la degradacion que aporta la DETECCION de entidades,
   con el ENLAZADO regalado. La cadena completa real sera igual o peor.

AMPLIACION v2 -- MODOS `llm` / `hybrid` Y RESOLUCION REAL
---------------------------------------------------------
7. MODO DE EXTRACTOR (`--extractor`). Ademas del heuristico se soportan los
   otros dos modos REALES del pipeline (`review/pipeline.py:_run_extract_step`):

     * `llm`    -> SOLO `review.llm_extractor.extract_with_llm` (Ollama real).
     * `hybrid` -> heuristico + LLM combinados por `review.hybrid_filter.merge_hybrid`
                   con sus umbrales por defecto (0.70 / 0.85), exactamente igual
                   que el pipeline.

   No se reimplementa nada: se importan las mismas funciones. Como el pipeline
   real hace UNA sola llamada al LLM por segmento y despues decide el modo, este
   driver CACHEA la respuesta del LLM por (corrida, fuente) y deriva de ella
   tanto `llm` como `hybrid`. Es la misma entrada que veria el pipeline, con la
   mitad de llamadas.

   PROVEEDOR: en los modos `llm`/`hybrid` SI se abre red hacia Ollama (autorizado
   explicitamente y SOLO para medir). Nunca hacia NVIDIA. El motor de relaciones
   sigue corriendo con proveedores DESHABILITADOS (`runner.MODES`).

8. DETERMINISMO (`--runs N`). El LLM se llama con `temperature=0` (settings.yaml)
   y `seed=42` (misma semilla que `cli/extractor_benchmark.py`). Aun asi la
   reproducibilidad NO esta garantizada, asi que el driver repite la cadena
   completa N veces con la misma semilla y se reporta la varianza entre corridas.
   El modo `heuristic` es determinista por construccion (`--runs 1` basta).

9. RESOLUCION DE ENTIDADES (`--resolution`). La decision 6 asigna ids con el
   GROUND TRUTH como ORACULO DE ENLAZADO. El sistema real no tiene ese oraculo:

     * `oracle`  -> politica original (cota optimista).
     * `surface` -> agrupacion REALISTA: las menciones se agrupan por la clave que
                    el sistema real usa de verdad, es decir alias revisados del
                    workspace (`review.workspace_aliases`) seguidos de la
                    normalizacion de `review.resolver._normalize` (minusculas sin
                    tildes). Cada GRUPO recibe despues el id de GT MAYORITARIO
                    entre sus menciones (bautizo por mayoria).

   Que mide y que no mide `surface`: penaliza INTEGRAMENTE las FUSIONES (dos
   entidades distintas con la misma cadena normalizada colapsan en una, y la
   perdedora queda inalcanzable), pero REPARA las DIVISIONES (dos cadenas
   distintas de la misma entidad reciben, cada una por su lado, el mismo id de
   GT). Sigue siendo por tanto una COTA OPTIMISTA, mas ajustada que `oracle`.

     * `surface_bijective` -> COTA PESIMISTA de la misma agrupacion: un grupo solo
                    se identifica con una entidad del GT si la correspondencia es
                    BIYECTIVA (el grupo contiene un unico id y ese id no aparece en
                    ningun otro grupo). Si hay fusion o division, el grupo recibe un
                    id sintetico que jamas empareja. Es lo que ocurriria si el
                    sistema no tuviera forma alguna de desambiguar.

   Las tres politicas ACOTAN el resultado real: `oracle` >= `surface` >=
   `surface_bijective`. Las metricas B-cubed de `resolution_audit.py` cuantifican
   aparte cuantas fusiones y divisiones hay y de que tipo.

SALIDA
------
JSON con un informe `report.build_report` por (corpus, modo, selector, condicion),
mas el detalle de la derivacion de entidades. Sin Neo4j, sin ingesta, sin NVIDIA.

Uso:
    python data-engine/app/tools/chain_benchmark.py \
        --corpus B1 H1 H2 --selector v1 v2 --mode baseline1 \
        --out /ruta/chain.json
    python data-engine/app/tools/chain_benchmark.py \
        --corpus B1 H1 H2 --selector v2 --extractor hybrid --runs 3 \
        --condition extractor_strict extractor_lax \
        --llm-cache /ruta/cache.json --out /ruta/chain_hybrid.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Optional

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_REPO_ROOT = _APP_DIR.parents[1]

# --- Arnes autoritativo de relaciones (IMPORTADO, jamas modificado) ---------
from relations.benchmark import runner as _runner
from relations.benchmark import report as _report
from relations.benchmark import matching as _matching  # noqa: F401  (via build_report)
from relations.benchmark import metrics as _bench_metrics  # noqa: F401  (via build_report)
from relations.contracts import ALLOWED_ENTITY_TYPES
from relations.pipeline import run_pipeline as _run_pipeline

# --- Extractor REAL (IMPORTADO, jamas modificado) ---------------------------
from review import extractor as _extractor
from review import llm_extractor as _llm_extractor
from review.hybrid_filter import merge_hybrid as _merge_hybrid
from review.models import Candidate as _Candidate
from review.resolver import _normalize as _resolver_normalize
from review.workspace_aliases import load_workspace_aliases as _load_ws_aliases

# Corpus disponibles (los tres del programa).
CORPORA = {
    "B1": _APP_DIR / "tests" / "data" / "relation_benchmark",
    "H1": _APP_DIR / "tests" / "data" / "relation_heldout",
    "H2": _APP_DIR / "tests" / "data" / "relation_heldout_h2",
}

CONDITIONS = ("gt_perfect", "extractor_strict", "extractor_lax")

# Mapa de tipos del extractor -> vocabulario del motor. Ver decision 4.
# `Clan` es el unico tipo del heuristico fuera de `ALLOWED_ENTITY_TYPES`; el resto
# (incluidos los que solo emite el LLM: Object, Event, Concept) pasa tal cual.
EXTRACTOR_TYPE_MAP = {
    "Character": "Character",
    "Location": "Location",
    "Faction": "Faction",
    "Clan": "Faction",
    "Object": "Object",
    "Event": "Event",
    "Concept": "Concept",
}

# Prefijo de los ids sinteticos (menciones sin correspondencia en el GT).
UNMATCHED_PREFIX = "xx::"

# Modos de extractor soportados (los tres REALES de `review/pipeline.py`).
EXTRACTOR_MODES = ("heuristic", "llm", "hybrid")

# Semilla del LLM: la MISMA que usa `cli/extractor_benchmark.py` (_BENCHMARK_SEED).
LLM_SEED = 42

# Politicas de resolucion de entidades (decision 9).
RESOLUTIONS = ("oracle", "surface", "surface_bijective")


# ---------------------------------------------------------------------------
# Cache de respuestas del LLM (una llamada por (corrida, fuente))
# ---------------------------------------------------------------------------
class LLMCache:
    """Persiste los candidatos del LLM por (corrida, fuente).

    Motivo: el pipeline real llama UNA vez al LLM y despues decide si el modo es
    `llm` o `hybrid`. Cachear reproduce esa realidad y evita duplicar llamadas.
    Ademas hace la medicion reanudable (Ollama en CPU tarda ~70 s por fuente).
    """

    def __init__(self, path: Optional[Path]):
        self.path = path
        self.data: dict[str, list[dict]] = {}
        self.hits = 0
        self.misses = 0
        if path is not None and path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {}

    @staticmethod
    def key(corpus_key: str, source_id: str, run_index: int) -> str:
        return f"{corpus_key}|{source_id}|run{run_index}"

    def get(self, key: str) -> Optional[list]:
        raw = self.data.get(key)
        if raw is None:
            return None
        self.hits += 1
        return [_Candidate.from_dict(d) for d in raw]

    def put(self, key: str, candidates: list) -> None:
        self.misses += 1
        self.data[key] = [c.to_dict() for c in candidates]
        if self.path is not None:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)


# ---------------------------------------------------------------------------
# Extractor real -> menciones con offsets
# ---------------------------------------------------------------------------
    # Mapa de plegado que PRESERVA LA LONGITUD (imprescindible para no desplazar
    # offsets). NFKD no sirve aqui porque cambia el numero de caracteres.
_FOLD_MAP = str.maketrans(
    "ÁÀÄÂÃÅáàäâãåÉÈËÊéèëêÍÌÏÎíìïîÓÒÖÔÕóòöôõÚÙÜÛúùüûÑñÇç",
    "AAAAAAaaaaaaEEEEeeeeIIIIiiiiOOOOOoooooUUUUuuuuNnCc",
)


def _fold(text: str) -> str:
    """Minusculas sin tildes, CON LA MISMA LONGITUD que la entrada."""
    return text.translate(_FOLD_MAP).lower()


def _slug(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "vacio"


def build_classified_segment(source_id: str, text: str, workspace: str) -> dict:
    """Segmento YA CLASIFICADO equivalente al del arnes (uno por fuente).

    No se ejecutan `review.segmenter` ni `review.classifier`: se fija
    `should_extract=True` para que la comparacion aisle la extraccion de
    entidades y no la segmentacion. Esto FAVORECE al extractor.
    """
    return {
        "segment_id": source_id,
        "source_id": source_id,
        "source_kind": "text",
        "workspace": workspace,
        "timestamp_start": "",
        "timestamp_end": "",
        "text": text,
        "lines": text.splitlines(),
        "category": "lore",
        "should_extract": True,
        "category_scores": {},
    }


def extractor_candidates(source_id: str, text: str, workspace: str, *,
                         extractor_mode: str, cache: "LLMCache",
                         cache_key: str) -> tuple[list, dict]:
    """Devuelve los candidatos del EXTRACTOR REAL en el modo pedido.

    Reproduce `review/pipeline.py:_run_extract_step` sin reimplementarlo:
      * heuristic -> `extractor.extract_from_segments`
      * llm       -> `llm_extractor.extract_with_llm` (Ollama REAL, seed 42)
      * hybrid    -> `hybrid_filter.merge_hybrid(heuristicos, llm)`
    """
    seg = build_classified_segment(source_id, text, workspace)
    glossary = _extractor._load_glossary(_REPO_ROOT, workspace)
    stats: dict = {"extractor_mode": extractor_mode}

    heur: list = []
    if extractor_mode in ("heuristic", "hybrid"):
        heur = _extractor.extract_from_segments([seg], glossary)
        stats["n_heuristic_candidates"] = len(heur)
    if extractor_mode == "heuristic":
        return heur, stats

    llm_cands = cache.get(cache_key)
    if llm_cands is None:
        gloss_snap = _extractor._glossary_snapshot(_REPO_ROOT, workspace)
        if not _llm_extractor.is_ollama_available():
            raise RuntimeError(
                "Ollama NO responde: el modo %r no puede medirse sin proveedor. "
                "No se degrada a heuristico (falsearia la medicion)." % extractor_mode)
        llm_cands = _llm_extractor.extract_with_llm([seg], gloss_snap, workspace, seed=LLM_SEED)
        cache.put(cache_key, llm_cands)
    stats["n_llm_candidates"] = len(llm_cands)
    stats["n_llm_entities"] = sum(1 for c in llm_cands if c.kind == "entity")

    if extractor_mode == "llm":
        return llm_cands, stats

    merged, hybrid_stats = _merge_hybrid(heur, llm_cands)
    stats["hybrid_filter"] = {k: v for k, v in hybrid_stats.items() if k != "filtered"}
    return merged, stats


def extractor_mentions(source_id: str, text: str, workspace: str, *,
                       extractor_mode: str = "heuristic",
                       cache: Optional["LLMCache"] = None,
                       cache_key: str = "",
                       offset_recovery: str = "exact") -> tuple[list[dict], list[dict], dict]:
    """Llama al EXTRACTOR REAL y devuelve (menciones_con_offsets, notas, stats).

    Cada mencion es `{"name", "type", "start", "end"}` (sin `id`: lo asigna la
    politica de emparejamiento). Ver decisiones 2, 3, 4, 5 y 7 del docstring.
    """
    if cache is None:
        cache = LLMCache(None)
    candidates, stats = extractor_candidates(
        source_id, text, workspace, extractor_mode=extractor_mode,
        cache=cache, cache_key=cache_key)

    notes: list[dict] = []
    raw: list[dict] = []
    for cand in candidates:
        if cand.kind != "entity" or not cand.name:
            continue
        name = cand.name
        etype = EXTRACTOR_TYPE_MAP.get(cand.entity_type or "", None)
        if etype is None:
            notes.append({"source_id": source_id, "name": name,
                          "extractor_type": cand.entity_type,
                          "reason": "type_out_of_vocabulary",
                          "allowed": list(ALLOWED_ENTITY_TYPES)})
        spans = [m.span() for m in re.finditer(re.escape(name), text)]
        if not spans and offset_recovery == "relaxed":
            # Sensibilidad: el heuristico copia subcadenas literales del texto, pero
            # el LLM RE-ESCRIBE el nombre ("la reina Ysolde" -> "Reina Ysolde"). Con
            # la regla publicada (busqueda literal) esas menciones se pierden, lo
            # que penaliza al LLM por un detalle de mayusculas. Este modo repite la
            # busqueda plegando mayusculas y tildes SIN alterar longitudes.
            spans = [m.span() for m in re.finditer(re.escape(_fold(name)), _fold(text))]
            if spans:
                notes.append({"source_id": source_id, "name": name,
                              "reason": "found_only_with_relaxed_folding",
                              "n_spans": len(spans)})
        if not spans:
            # El extractor canonicalizo el nombre (tabla de clanes / glosario) y
            # la cadena resultante no aparece literalmente en el texto: no se
            # inventa posicion.
            notes.append({"source_id": source_id, "name": name,
                          "reason": "name_not_found_in_text"})
            continue
        for start, end in spans:
            raw.append({"name": name, "type": etype, "start": start, "end": end,
                        "confidence": cand.confidence})

    # Deduplicacion exacta (mismo nombre y mismo span).
    dedup: dict[tuple, dict] = {}
    for m in raw:
        dedup.setdefault((m["start"], m["end"], m["name"]), m)
    ordered = sorted(dedup.values(), key=lambda m: (m["start"], -(m["end"] - m["start"]), m["name"]))

    # Des-solapamiento determinista (decision 3): se conserva el span mas largo.
    kept: list[dict] = []
    for m in ordered:
        clash = next((k for k in kept if m["start"] < k["end"] and k["start"] < m["end"]), None)
        if clash is None:
            kept.append(m)
        else:
            notes.append({"source_id": source_id, "name": m["name"],
                          "start": m["start"], "end": m["end"],
                          "reason": "overlapping_span",
                          "kept_instead": clash["name"]})
    kept.sort(key=lambda m: (m["start"], m["end"], m["name"]))
    return kept, notes, stats


# ---------------------------------------------------------------------------
# Politicas de emparejamiento de ids (decision 6)
# ---------------------------------------------------------------------------
def assign_ids(mentions: list[dict], gt_entities: list[dict], policy: str) -> tuple[list[dict], list[dict]]:
    """Asigna un `id` a cada mencion del extractor segun la politica.

    `gt_entities` son las entidades del CONTROL (`runner.derive_entities`), que
    llevan el `id` real del ground truth y sus offsets.

    * `strict`: span EXACTAMENTE igual al de una mencion del GT.
    * `lax`   : maximo solape de caracteres con una mencion del GT (solape > 0).

    Sin correspondencia -> id sintetico `xx::<slug>`, que jamas empareja con el GT.
    Devuelve (entidades_para_el_pipeline, notas_de_emparejamiento).
    """
    if policy not in ("strict", "lax"):
        raise ValueError(f"politica de ids desconocida: {policy!r}")

    out: list[dict] = []
    notes: list[dict] = []
    for m in mentions:
        matched_id: Optional[str] = None
        if policy == "strict":
            exact = [g for g in gt_entities if g["start"] == m["start"] and g["end"] == m["end"]]
            if exact:
                matched_id = sorted(exact, key=lambda g: str(g["id"]))[0]["id"]
        else:
            best: Optional[tuple] = None
            for g in gt_entities:
                inter = min(m["end"], g["end"]) - max(m["start"], g["start"])
                if inter <= 0:
                    continue
                # Mayor solape; desempate determinista por span mas largo e id menor.
                rank = (-inter, -(g["end"] - g["start"]), str(g["id"]))
                if best is None or rank < best[0]:
                    best = (rank, g["id"])
            if best is not None:
                matched_id = best[1]

        if matched_id is None:
            matched_id = UNMATCHED_PREFIX + _slug(m["name"])
            notes.append({"name": m["name"], "start": m["start"], "end": m["end"],
                          "policy": policy, "reason": "no_gt_correspondence",
                          "assigned_id": matched_id})
        out.append({"id": matched_id, "text": m["name"], "type": m["type"],
                    "start": m["start"], "end": m["end"]})
    out.sort(key=lambda e: (e["start"], e["end"], e["id"], e["type"] or ""))
    return out, notes


def surface_key(name: str, alias_map: dict) -> str:
    """Clave de agrupacion que usa el SISTEMA REAL para una mencion.

    Cadena de canonicalizacion realmente implementada en el repo:
      1. alias revisados del workspace (`config/aliases/<workspace>.json`), que
         `review.relation_normalizer` aplica por coincidencia exacta de cadena;
      2. `review.resolver._normalize` (minusculas, sin tildes), que es la clave
         con la que `_search_neo4j` compara (`toLower(n.canonical_name)`).
    No interviene el glosario porque `state/glossary.db` no existe (decision 5),
    igual que en las mediciones previas.
    """
    return _resolver_normalize(alias_map.get(name, name))


def apply_surface_resolution(entities: list[dict], alias_map: dict,
                             bijective_only: bool = False) -> tuple[list[dict], list[dict]]:
    """Sustituye el ORACULO de enlazado del GT por la agrupacion REAL (decision 9).

    Las menciones se agrupan por `surface_key`; cada grupo recibe el id de GT
    MAYORITARIO entre sus miembros (desempate por id alfabeticamente menor). Si
    ningun miembro tenia id de GT, todo el grupo recibe el id sintetico menor
    (el sistema real tambien los fusionaria).

    Con `bijective_only=True` un grupo solo conserva el id del GT si la
    correspondencia grupo<->id es BIYECTIVA (ni fusiones ni divisiones); en caso
    contrario recibe un id sintetico que jamas empareja. Es la cota PESIMISTA.

    Devuelve (entidades_reenlazadas, notas de fusion/renombrado).
    """
    groups: dict[str, list[dict]] = {}
    for e in entities:
        groups.setdefault(surface_key(e["text"], alias_map), []).append(e)

    # Reparto inverso: en cuantos grupos distintos cae cada id del GT (divisiones).
    id_groups: dict[str, set] = {}
    for key, members in groups.items():
        for m in members:
            if not m["id"].startswith(UNMATCHED_PREFIX):
                id_groups.setdefault(m["id"], set()).add(key)

    out: list[dict] = []
    notes: list[dict] = []
    for key, members in sorted(groups.items()):
        counts: dict[str, int] = {}
        for m in members:
            if not m["id"].startswith(UNMATCHED_PREFIX):
                counts[m["id"]] = counts.get(m["id"], 0) + 1
        if counts and bijective_only and (
                len(counts) > 1 or any(len(id_groups[i]) > 1 for i in counts)):
            # Cota PESIMISTA: sin oraculo, un grupo solo puede identificarse con una
            # entidad del GT si la correspondencia es BIYECTIVA (ni fusion ni
            # division). Si no lo es, el sistema real no tiene forma de saber a
            # cual de las dos se refiere -> id sintetico, que nunca empareja.
            notes.append({"surface_key": key, "reason": "no_biyectivo",
                          "gt_ids": sorted(counts),
                          "grupos_por_id": {i: sorted(id_groups[i]) for i in counts}})
            counts = {}
        if counts:
            chosen = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        elif any(not m["id"].startswith(UNMATCHED_PREFIX) for m in members):
            chosen = UNMATCHED_PREFIX + _slug(key)
        else:
            chosen = sorted(m["id"] for m in members)[0]
        if len(counts) > 1:
            notes.append({"surface_key": key, "reason": "merge_of_distinct_gt_ids",
                          "gt_ids": sorted(counts), "kept": chosen,
                          "lost": sorted(i for i in counts if i != chosen)})
        for m in members:
            if m["id"] != chosen:
                notes.append({"surface_key": key, "text": m["text"],
                              "start": m["start"], "end": m["end"],
                              "reason": "regrouped_by_surface",
                              "from_id": m["id"], "to_id": chosen})
            out.append({**m, "id": chosen})
    out.sort(key=lambda e: (e["start"], e["end"], e["id"], e["type"] or ""))
    return out, notes


# ---------------------------------------------------------------------------
# Metricas de DETECCION de entidades sobre el corpus de relaciones (diagnostico)
# ---------------------------------------------------------------------------
def entity_detection_metrics(mentions: list[dict], gt_entities: list[dict]) -> dict:
    """P/R/F1 de DETECCION de menciones (diagnostico, no es el arnes de docs/34).

    * `span_exact` : una mencion del extractor es TP si su span coincide
      exactamente con el de una mencion del GT (1:1, avaricioso determinista).
    * `span_overlap`: TP si solapa (>0 caracteres) con una mencion del GT.
    El denominador de recall son las menciones del GT (las que el motor recibe
    en el control), no las entidades unicas.
    """
    def _prf(tp: int, fp: int, fn: int) -> dict:
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        f = (2 * p * r / (p + r)) if (p + r) else 0.0
        return {"tp": tp, "fp": fp, "fn": fn,
                "precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}

    out = {}
    for label, exact in (("span_exact", True), ("span_overlap", False)):
        used: set[int] = set()
        tp = 0
        for m in sorted(mentions, key=lambda x: (x["start"], x["end"], x["name"])):
            hit = None
            for i, g in enumerate(gt_entities):
                if i in used:
                    continue
                if exact:
                    ok = g["start"] == m["start"] and g["end"] == m["end"]
                else:
                    ok = min(m["end"], g["end"]) - max(m["start"], g["start"]) > 0
                if ok:
                    hit = i
                    break
            if hit is not None:
                used.add(hit)
                tp += 1
        out[label] = _prf(tp, len(mentions) - tp, len(gt_entities) - tp)
    return out


# ---------------------------------------------------------------------------
# Ejecucion de una fuente en una condicion
# ---------------------------------------------------------------------------
def reachable_relations(corpus, source_id: str, entities: list[dict]) -> dict:
    """Techo de RECALL impuesto por el extractor, con independencia del motor.

    Una relacion del ground truth es ALCANZABLE si ambos extremos (`subject_id`
    y `object_id`) estan presentes entre los ids asignados a las entidades de
    entrada. Si no lo estan, el motor NO PUEDE emparejarla por construccion: es
    un fallo imputable integramente al extractor (o a la politica de ids), no al
    motor. Es una cota SUPERIOR: estar presentes no garantiza que el generador de
    pares los junte (contexto de frase, distancia...).
    """
    ids = {e["id"] for e in entities}
    total = 0
    reach = 0
    for r in corpus.relations:
        if r["source_id"] != source_id:
            continue
        total += 1
        if str(r["subject_id"]) in ids and str(r["object_id"]) in ids:
            reach += 1
    return {"total": total, "reachable": reach}


def run_source_condition(corpus, source_id: str, condition: str, *, mode: str,
                         predicate_selector: Optional[str],
                         extractor_mode: str = "heuristic",
                         resolution: str = "oracle",
                         cache: Optional["LLMCache"] = None,
                         corpus_key: str = "", run_index: int = 1,
                         offset_recovery: str = "exact") -> tuple:
    """Ejecuta el pipeline REAL sobre una fuente en la condicion indicada.

    Devuelve (SourceRun, info_de_entidades). Para `gt_perfect` se delega
    integramente en `runner.run_source` (camino autoritativo, sin tocar nada).
    """
    text = corpus.sources[source_id]
    workspace = corpus.workspace_by_source[source_id]
    gt_entities, gt_notes = _runner.derive_entities(source_id, text, corpus.relations)

    if condition == "gt_perfect":
        sr = _runner.run_source(corpus, source_id, mode=mode,
                                predicate_selector=predicate_selector)
        info = {"condition": condition, "source_id": source_id,
                "n_entities_input": len(sr.entities),
                "n_gt_mentions": len(gt_entities),
                "extractor_notes": [], "id_notes": [],
                "entity_detection": None,
                "unmatched_mentions": 0, "matched_mentions": len(sr.entities),
                "distinct_gt_ids_recovered": len({e["id"] for e in sr.entities}),
                "distinct_gt_ids_total": len({e["id"] for e in gt_entities}),
                "reachable": reachable_relations(corpus, source_id, sr.entities)}
        return sr, info

    policy = "strict" if condition == "extractor_strict" else "lax"
    mentions, ext_notes, ext_stats = extractor_mentions(
        source_id, text, workspace, extractor_mode=extractor_mode,
        cache=cache, cache_key=LLMCache.key(corpus_key, source_id, run_index),
        offset_recovery=offset_recovery)
    entities, id_notes = assign_ids(mentions, gt_entities, policy)
    res_notes: list[dict] = []
    if resolution.startswith("surface"):
        entities, res_notes = apply_surface_resolution(
            entities, _load_ws_aliases(_REPO_ROOT, workspace),
            bijective_only=(resolution == "surface_bijective"))

    payload = _runner.build_payload(source_id, text, workspace, entities)
    config = _runner._config_for_mode(mode, predicate_selector=predicate_selector)
    t0 = time.perf_counter()
    output = _run_pipeline(payload, config=config)  # proveedores off: jamas red
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    if _runner.uses_ensemble(mode):
        preds = _runner.extract_predictions_ensemble(output)
    else:
        preds = _runner.extract_predictions(output)

    sr = _runner.SourceRun(
        source_id=source_id, workspace=workspace, output=output, predictions=preds,
        entities=entities, derivation_notes=list(gt_notes) + ext_notes, elapsed_ms=elapsed_ms,
    )
    matched = sum(1 for e in entities if not e["id"].startswith(UNMATCHED_PREFIX))
    info = {
        "condition": condition, "source_id": source_id,
        "n_entities_input": len(entities), "n_gt_mentions": len(gt_entities),
        "extractor_notes": ext_notes, "id_notes": id_notes,
        "extractor_mode": extractor_mode, "resolution": resolution,
        "extractor_stats": ext_stats, "resolution_notes": res_notes,
        "entity_detection": entity_detection_metrics(mentions, gt_entities),
        "unmatched_mentions": len(entities) - matched, "matched_mentions": matched,
        "distinct_gt_ids_recovered": len(
            {e["id"] for e in entities if not e["id"].startswith(UNMATCHED_PREFIX)}),
        "distinct_gt_ids_total": len({e["id"] for e in gt_entities}),
        "reachable": reachable_relations(corpus, source_id, entities),
    }
    return sr, info


def run_condition(corpus, condition: str, *, mode: str,
                  predicate_selector: Optional[str],
                  extractor_mode: str = "heuristic", resolution: str = "oracle",
                  cache: Optional["LLMCache"] = None,
                  corpus_key: str = "", run_index: int = 1,
                  offset_recovery: str = "exact") -> tuple:
    """Ejecuta TODAS las fuentes del corpus en una condicion y arma un BenchmarkRun."""
    source_runs = []
    infos = []
    versions: dict = {}
    for sid in sorted(corpus.sources):
        sr, info = run_source_condition(corpus, sid, condition, mode=mode,
                                        predicate_selector=predicate_selector,
                                        extractor_mode=extractor_mode,
                                        resolution=resolution, cache=cache,
                                        corpus_key=corpus_key, run_index=run_index,
                                        offset_recovery=offset_recovery)
        source_runs.append(sr)
        infos.append(info)
        if not versions:
            versions = dict(sr.output["versions"])
    run = _runner.BenchmarkRun(
        mode=mode,
        config=_runner._config_for_mode(mode, predicate_selector=predicate_selector).to_dict(),
        versions=versions,
        source_runs=source_runs,
        corpus_hashes=dict(corpus.corpus_hashes),
        code_sha=_runner._code_sha(),
        source_ids=sorted(corpus.sources),
        provider_status={},
        ensemble=_runner.uses_ensemble(mode),
    )
    return run, infos


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def prefill_llm_cache(corpus_keys: list, cache: "LLMCache", run_index: int,
                      workers: int = 4) -> None:
    """Rellena la cache llamando a Ollama en paralelo (unica etapa con red).

    Separar el llenado de la cache de la evaluacion tiene un motivo metodologico:
    la evaluacion de la cadena es asi 100 % determinista dada la cache, y toda la
    variabilidad observada entre corridas es atribuible al proveedor. La anchura
    de concurrencia se mantiene CONSTANTE en todas las corridas para no introducir
    una variable extra (Ollama agrupa peticiones concurrentes en lotes).
    """
    from concurrent.futures import ThreadPoolExecutor

    jobs = []
    for corpus_key in corpus_keys:
        corpus = _runner.load_corpus(CORPORA[corpus_key], verify=True)
        for sid in sorted(corpus.sources):
            key = LLMCache.key(corpus_key, sid, run_index)
            if key in cache.data:
                continue
            jobs.append((key, sid, corpus.sources[sid], corpus.workspace_by_source[sid]))
    if not jobs:
        print(f"[prefill run={run_index}] cache completa, nada que pedir", flush=True)
        return
    if not _llm_extractor.is_ollama_available():
        raise RuntimeError("Ollama NO responde: no se puede rellenar la cache")
    print(f"[prefill run={run_index}] {len(jobs)} llamadas a Ollama "
          f"({_llm_extractor.OLLAMA_MODEL} @ {_llm_extractor.OLLAMA_URL}), "
          f"workers={workers}", flush=True)

    def _one(job):
        key, sid, text, ws = job
        seg = build_classified_segment(sid, text, ws)
        snap = _extractor._glossary_snapshot(_REPO_ROOT, ws)
        t0 = time.perf_counter()
        cands = _llm_extractor.extract_with_llm([seg], snap, ws, seed=LLM_SEED)
        return key, cands, time.perf_counter() - t0

    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for key, cands, secs in ex.map(_one, jobs):
            cache.put(key, cands)  # serializado: ex.map devuelve en orden
            done += 1
            print(f"  [{done}/{len(jobs)}] {key} -> {len(cands)} cands ({secs:.0f}s)",
                  flush=True)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", nargs="+", default=["B1", "H1", "H2"], choices=sorted(CORPORA))
    ap.add_argument("--mode", nargs="+", default=["baseline1"], choices=sorted(_runner.MODES))
    ap.add_argument("--selector", nargs="+", default=["v1", "v2"], choices=["v1", "v2"])
    ap.add_argument("--condition", nargs="+", default=list(CONDITIONS), choices=CONDITIONS)
    ap.add_argument("--extractor", nargs="+", default=["heuristic"], choices=EXTRACTOR_MODES,
                    help="modo del extractor de entidades (llm/hybrid usan Ollama REAL)")
    ap.add_argument("--resolution", nargs="+", default=["oracle"], choices=RESOLUTIONS,
                    help="oracle = ids del GT; surface = agrupacion real del sistema")
    ap.add_argument("--runs", type=int, default=1,
                    help="repeticiones (varianza del LLM); el heuristico es determinista")
    ap.add_argument("--llm-cache", default=None, help="JSON de cache de respuestas del LLM")
    ap.add_argument("--prefill-only", action="store_true",
                    help="solo rellena la cache del LLM (unica etapa con red) y sale")
    ap.add_argument("--workers", type=int, default=4, help="concurrencia del prefill")
    ap.add_argument("--offset-recovery", default="exact", choices=("exact", "relaxed"),
                    help="exact = regla publicada (busqueda literal); relaxed = plegando "
                         "mayusculas y tildes (analisis de sensibilidad para el LLM)")
    ap.add_argument("--out", default=None, help="ruta del JSON de salida")
    args = ap.parse_args(argv)

    cache = LLMCache(Path(args.llm_cache) if args.llm_cache else None)
    needs_llm = any(e in ("llm", "hybrid") for e in args.extractor)

    if args.prefill_only:
        for run_index in range(1, args.runs + 1):
            prefill_llm_cache(args.corpus, cache, run_index, workers=args.workers)
        return 0

    results = []
    for corpus_key in args.corpus:
        corpus = _runner.load_corpus(CORPORA[corpus_key], verify=True)
        for mode in args.mode:
          for extractor_mode in args.extractor:
           for resolution in args.resolution:
            for run_index in range(1, (args.runs if extractor_mode != "heuristic" else 1) + 1):
             for selector in args.selector:
                for condition in args.condition:
                    if condition == "gt_perfect" and (
                            extractor_mode != args.extractor[0] or resolution != args.resolution[0]
                            or run_index > 1):
                        continue  # el control no depende del extractor ni de la resolucion
                    run, infos = run_condition(corpus, condition, mode=mode,
                                               predicate_selector=selector,
                                               extractor_mode=extractor_mode,
                                               resolution=resolution, cache=cache,
                                               corpus_key=corpus_key, run_index=run_index,
                                               offset_recovery=args.offset_recovery)
                    rep = _report.build_report(corpus, run, check_determinism=False)
                    results.append({
                        "corpus": corpus_key,
                        "corpus_dir": str(CORPORA[corpus_key]),
                        "mode": mode,
                        "predicate_selector": selector,
                        "condition": condition,
                        "extractor": extractor_mode,
                        "resolution": resolution,
                        "offset_recovery": args.offset_recovery,
                        "run_index": run_index,
                        "report": rep,
                        "entity_info": infos,
                    })
                    st = rep["metrics"]["structural_quality"]
                    ge = rep["metrics"]["global_existence"]
                    reach = sum(i["reachable"]["reachable"] for i in infos)
                    reach_tot = sum(i["reachable"]["total"] for i in infos)
                    print(
                        f"{corpus_key:3s} {mode:12s} sel={selector} "
                        f"ext={extractor_mode:9s} res={resolution:7s} r{run_index} {condition:17s} "
                        f"alcanz={reach}/{reach_tot}={reach / reach_tot if reach_tot else 0:.4f} "
                        f"pair_F1={ge['f1']:.4f} (TP={ge['tp']} FP={ge['fp']} FN={ge['fn']}) "
                        f"pred={st['predicate_correct']['rate']:.4f} "
                        f"dir={st['direction_correct']['rate']:.4f} "
                        f"tipos={st['types_correct']['rate']:.4f} "
                        f"strictF1={rep['metrics']['strict_predicate']['f1']:.4f}",
                        flush=True,
                    )

    payload = {
        "driver": "chain_benchmark-v2",
        "harness": "relations/benchmark (importado sin modificar)",
        "extractor": {
            "heuristic": "review.extractor.extract_from_segments",
            "llm": "review.llm_extractor.extract_with_llm (Ollama REAL)",
            "hybrid": "heuristico + LLM via review.hybrid_filter.merge_hybrid",
            "modes_ejecutados": args.extractor,
        },
        "resolution_policies": args.resolution,
        "runs": args.runs,
        "providers": {
            "motor_de_relaciones": "NOT_EXECUTED (runner.MODES: sin red)",
            "extractor_llm": (
                f"OLLAMA REAL {_llm_extractor.OLLAMA_MODEL} @ {_llm_extractor.OLLAMA_URL} "
                f"temperature={_llm_extractor._OLLAMA_TEMPERATURE} seed={LLM_SEED}"
                if needs_llm else "NOT_EXECUTED"),
            "nvidia": "NUNCA",
        },
        "llm_cache": {"path": args.llm_cache, "hits": cache.hits, "misses": cache.misses},
        "results": results,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\nJSON -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
