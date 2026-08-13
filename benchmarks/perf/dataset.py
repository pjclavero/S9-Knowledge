"""Generador de datasets SINTÉTICOS para el laboratorio de rendimiento (v2).

Determinista: los mismos parámetros producen siempre el mismo grafo, así una
medición es reproducible y comparable entre commits.

NO contiene material real de ninguna fuente: todos los nombres, descripciones y
documentos son cadenas generadas. Nunca se conecta a producción.

Forma de salida: idéntica a ``viewer/examples/sample_graph.json``
(``{"workspace", "nodes", "edges"}``), para que ``MockGraphProvider`` la cargue
sin cambios.

NOVEDAD v2 — HUELLA (fingerprint)
---------------------------------
``huella()`` resume en un hash TODO lo que puede cambiar el grafo generado:

  * el código fuente de ESTE fichero (si cambia el generador, cambia la huella),
  * los parámetros de generación (n, semilla, grado, hubs),
  * el vocabulario de visibilidad que el generador emite.

La caché (``cache.py``) guarda la huella junto al fichero. Una caché sin huella
es una máquina de resucitar defectos: en v1, el generador emitía un nivel de
visibilidad fuera de vocabulario y el 25 % de los nodos era invisible; al
corregir el generador, los ficheros ya cacheados seguían conteniendo el grafo
malo y las mediciones seguían siendo falsas sin que nada avisara.

NOVEDAD v2 — HUBS
-----------------
``generate(..., hubs=k, grado_hub=d)`` fuerza ``k`` nodos de grado muy alto.
Es donde revientan las consultas por-elemento: la ficha de entidad hace una
consulta por relación, así que su coste no depende del tamaño del grafo sino
del GRADO del nodo pedido.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

WORKSPACE = "perflab"

# Versión del FORMATO de salida. Súbela a mano si cambia la forma del JSON de
# manera que un fichero antiguo ya no sea equivalente. Entra en la huella.
FORMATO_VERSION = 2

ENTITY_TYPES = [
    "Character", "Location", "Organization", "Item", "Event",
    "Concept", "Creature", "Deity",
]
REVIEW_STATUSES = ["auto_extracted", "reviewed", "approved", "rejected"]
# Sólo niveles del vocabulario cerrado del motor (`policies.models`). No es un
# detalle cosmético: un valor fuera de vocabulario —"public", por ejemplo— hace
# que la política descarte el nodo y se mediría un grafo parcialmente invisible.
VISIBILITIES = ["player", "narrator", "secret", "reference"]
KNOWLEDGE_LAYERS = ["book", "campaign", "session"]
SOURCE_KINDS = ["pdf", "video", "audio", "manuscript"]
RELATION_TYPES = [
    "RELATED_TO", "MEMBER_OF", "LOCATED_IN", "ALLY_OF",
    "ENEMY_OF", "OWNS", "PARENT_OF",
]

EDGES_PER_NODE = 3
NODES_PER_SOURCE = 25
SEMILLA = 20260809


@dataclass(frozen=True)
class Parametros:
    """Todo lo que determina el grafo generado."""
    n_entities: int
    seed: int = SEMILLA
    workspace: str = WORKSPACE
    edges_per_node: int = EDGES_PER_NODE
    hubs: int = 0
    grado_hub: int = 0

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


def _texto(rng: random.Random, palabras: int) -> str:
    vocab = (
        "alfa bravo charlie delta eco foxtrot golf hotel india julieta kilo "
        "lima mike noviembre oscar papa quebec romeo sierra tango uniforme "
        "victor whisky xray yanqui zulu"
    ).split()
    return " ".join(rng.choice(vocab) for _ in range(palabras))


# ---------------------------------------------------------------------------
# HUELLA
# ---------------------------------------------------------------------------

def _fuente_del_generador() -> str:
    """El texto de este mismo fichero. Si cambia el generador, cambia la huella."""
    return Path(__file__).read_text(encoding="utf-8")


def huella(p: Parametros) -> str:
    """Hash estable de (código del generador + parámetros + vocabulario)."""
    material = json.dumps(
        {
            "formato": FORMATO_VERSION,
            "parametros": p.como_dict(),
            "visibilities": VISIBILITIES,
            "entity_types": ENTITY_TYPES,
            "relation_types": RELATION_TYPES,
            "fuente_sha256": hashlib.sha256(
                _fuente_del_generador().encode("utf-8")
            ).hexdigest(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# GENERACIÓN
# ---------------------------------------------------------------------------

def generate(
    n_entities: int,
    *,
    seed: int = SEMILLA,
    workspace: str = WORKSPACE,
    edges_per_node: int = EDGES_PER_NODE,
    hubs: int = 0,
    grado_hub: int = 0,
) -> dict[str, Any]:
    """Grafo sintético con ``n_entities`` nodos.

    Con ``hubs>0`` los ``hubs`` primeros nodos reciben ``grado_hub`` relaciones
    salientes adicionales cada uno.
    """
    rng = random.Random(seed ^ n_entities ^ (hubs * 1_000_003) ^ (grado_hub * 7919))
    n_sources = max(4, n_entities // NODES_PER_SOURCE)
    sources = [f"doc_sintetico_{i:04d}.pdf" for i in range(n_sources)]

    nodes: list[dict[str, Any]] = []
    for i in range(n_entities):
        etype = ENTITY_TYPES[i % len(ENTITY_TYPES)]
        nodes.append(
            {
                "id": f"p_{i:07d}",
                "label": f"{etype} sintetico {i:07d}",
                "canonical_name": f"{etype} sintetico {i:07d}",
                "type": etype,
                "entity_type": etype,
                "description": _texto(rng, 40),
                "aliases": [f"alias_{i:07d}_{k}" for k in range(rng.randint(0, 2))],
                "workspace": workspace,
                "scope": "juego",
                "source_document": sources[i % n_sources],
                "source_pages": [rng.randint(1, 400)],
                "source_kind": SOURCE_KINDS[i % len(SOURCE_KINDS)],
                "confidence": round(rng.uniform(0.3, 0.99), 2),
                "visibility": VISIBILITIES[i % len(VISIBILITIES)],
                "knowledge_layer": KNOWLEDGE_LAYERS[i % len(KNOWLEDGE_LAYERS)],
                "review_status": REVIEW_STATUSES[i % len(REVIEW_STATUSES)],
                "manual_review_required": (i % 7 == 0),
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "extractor_version": "perf-synth-2",
                "prompt_version": "perf-synth-2",
                "source_hash": f"{i:064x}",
            }
        )

    edges: list[dict[str, Any]] = []

    def _arista(j: int, a: int, b: int) -> dict[str, Any]:
        rtype = RELATION_TYPES[j % len(RELATION_TYPES)]
        return {
            "id": f"pe_{j:07d}",
            "from": f"p_{a:07d}",
            "to": f"p_{b:07d}",
            "type": rtype,
            "label": rtype.lower().replace("_", " "),
            "description": _texto(rng, 15),
            "workspace": workspace,
            "scope": "juego",
            "confidence": round(rng.uniform(0.3, 0.99), 2),
            "visibility": VISIBILITIES[j % len(VISIBILITIES)],
            "review_status": REVIEW_STATUSES[j % len(REVIEW_STATUSES)],
            "source_document": sources[j % n_sources],
            "source_pages": [rng.randint(1, 400)],
        }

    j = 0
    for _ in range(n_entities * edges_per_node):
        a = rng.randrange(n_entities)
        b = rng.randrange(n_entities)
        if a == b:
            b = (b + 1) % n_entities
        edges.append(_arista(j, a, b))
        j += 1

    # Hubs: nodos de grado muy alto, que es donde revientan las consultas
    # por-elemento.
    for h in range(min(hubs, n_entities)):
        for _ in range(grado_hub):
            b = rng.randrange(n_entities)
            if b == h:
                b = (b + 1) % n_entities
            edges.append(_arista(j, h, b))
            j += 1

    return {"workspace": workspace, "nodes": nodes, "edges": edges}


def ids_hub(p: Parametros) -> list[str]:
    return [f"p_{i:07d}" for i in range(min(p.hubs, p.n_entities))]


def verificar_visibilidad_valida() -> None:
    """Falla si el generador emite un nivel que el motor no reconoce.

    Se comprueba contra el vocabulario REAL del visor, no contra una copia.
    """
    try:
        from app.policies.models import ALL_STORED_LEVELS
    except ImportError:  # ejecución suelta, sin el visor en sys.path
        return
    invalidos = sorted(set(VISIBILITIES) - set(ALL_STORED_LEVELS))
    if invalidos:
        raise ValueError(
            f"Niveles de visibilidad fuera del vocabulario del motor: {invalidos}. "
            "El dataset mediría un grafo parcialmente invisible."
        )


def escribir(p: Parametros, destino: Path) -> Path:
    verificar_visibilidad_valida()
    destino.parent.mkdir(parents=True, exist_ok=True)
    data = generate(
        p.n_entities,
        seed=p.seed,
        workspace=p.workspace,
        edges_per_node=p.edges_per_node,
        hubs=p.hubs,
        grado_hub=p.grado_hub,
    )
    destino.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return destino


if __name__ == "__main__":  # pragma: no cover - utilidad de línea de órdenes
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"/tmp/perf_{n}.json")
    par = Parametros(n_entities=n)
    print(escribir(par, out), huella(par))
