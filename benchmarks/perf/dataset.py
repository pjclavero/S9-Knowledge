"""Generador de datasets SINTÉTICOS para el laboratorio de rendimiento.

Determinista (semilla fija): el mismo tamaño produce siempre el mismo grafo,
así una medición es reproducible y comparable entre commits.

NO contiene material real de ninguna fuente: todos los nombres, descripciones
y documentos son cadenas generadas. Nunca se conecta a producción.

Forma de salida: idéntica a ``viewer/examples/sample_graph.json``
(``{"workspace", "nodes", "edges"}``), para que ``MockGraphProvider`` la cargue
sin cambios.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

WORKSPACE = "perflab"

ENTITY_TYPES = [
    "Character", "Location", "Organization", "Item", "Event",
    "Concept", "Creature", "Deity",
]
REVIEW_STATUSES = ["auto_extracted", "reviewed", "approved", "rejected"]
# Sólo niveles del vocabulario cerrado del motor (`policies.models.ALL_LEVELS`).
# No es un detalle cosmético: un valor fuera de vocabulario —"public", por
# ejemplo— hace que `can_view` devuelva `visibility_invalid` y el nodo
# desaparezca ANTES incluso del bypass de administrador. La primera versión de
# este generador usaba "public" y medía un grafo con la cuarta parte de los
# nodos invisible, sin que nada avisara. `verificar_visibilidad_valida` congela
# el acuerdo.
VISIBILITIES = ["player", "narrator", "secret", "reference"]
KNOWLEDGE_LAYERS = ["book", "campaign", "session"]
SOURCE_KINDS = ["pdf", "video", "audio", "manuscript"]
RELATION_TYPES = [
    "RELATED_TO", "MEMBER_OF", "LOCATED_IN", "ALLY_OF",
    "ENEMY_OF", "OWNS", "PARENT_OF",
]

# Relaciones por entidad. 3 es un grado medio plausible para un grafo de lore
# y mantiene la proporción al escalar (el encargo pide relaciones escaladas).
EDGES_PER_NODE = 3
# Nº de documentos fuente distintos, ~1 por cada 25 entidades (mínimo 4).
NODES_PER_SOURCE = 25


def _texto(rng: random.Random, palabras: int) -> str:
    vocab = (
        "alfa bravo charlie delta eco foxtrot golf hotel india julieta kilo "
        "lima mike noviembre oscar papa quebec romeo sierra tango uniforme "
        "victor whisky xray yanqui zulu"
    ).split()
    return " ".join(rng.choice(vocab) for _ in range(palabras))


def generate(n_entities: int, *, seed: int = 20260809, workspace: str = WORKSPACE) -> dict[str, Any]:
    """Devuelve un grafo sintético con ``n_entities`` nodos y ~3N relaciones."""
    rng = random.Random(seed ^ n_entities)
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
                # ~40 palabras: descripción realista de entidad extraída.
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
                "extractor_version": "perf-synth-1",
                "prompt_version": "perf-synth-1",
                "source_hash": f"{i:064x}",
            }
        )

    edges: list[dict[str, Any]] = []
    n_edges = n_entities * EDGES_PER_NODE
    for j in range(n_edges):
        a = rng.randrange(n_entities)
        b = rng.randrange(n_entities)
        if a == b:
            b = (b + 1) % n_entities
        rtype = RELATION_TYPES[j % len(RELATION_TYPES)]
        edges.append(
            {
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
        )

    return {"workspace": workspace, "nodes": nodes, "edges": edges}


def verificar_visibilidad_valida() -> None:
    """Falla si el generador emite un nivel que el motor no reconoce.

    Se comprueba contra el vocabulario REAL (`app.policies.models`), no contra
    una copia. Si el visor amplía o recorta el vocabulario, esta comprobación
    lo detecta antes de que una medición mienta.
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


def write(n_entities: int, destino: Path, *, seed: int = 20260809) -> Path:
    verificar_visibilidad_valida()
    destino.parent.mkdir(parents=True, exist_ok=True)
    data = generate(n_entities, seed=seed)
    destino.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return destino


if __name__ == "__main__":  # pragma: no cover - utilidad de línea de órdenes
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"/tmp/perf_{n}.json")
    print(write(n, out))
