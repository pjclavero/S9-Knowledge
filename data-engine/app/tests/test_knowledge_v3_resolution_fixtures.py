# -*- coding: utf-8 -*-
"""Fixtures del subsistema de resolucion de identidad (V3, subsistema C).

Este modulo NO contiene tests: contiene el mundo sobre el que se prueban. Se
carga por RUTA desde los dos modulos de test (mismo patron que
`test_knowledge_v3_contracts.py` con `v3_fixtures.py`), para no depender del
orden en que pytest inserta directorios en `sys.path`.

El corpus es deliberadamente pequeno y a mano: cada entidad esta aqui porque
plantea un problema concreto (homonimo entre bovedas, tipo en conflicto,
variante de ASR, nombre casi identico). Un corpus grande y generico no probaria
mas: probaria lo mismo con mas ruido.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Sequence

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from knowledge_v3.contracts import (  # noqa: E402
    CONTRACT_VERSION,
    EntityMention,
    Provider,
    provider_step,
)
from knowledge_v3.resolution import (  # noqa: E402
    CatalogEntity,
    EntityCatalog,
    InMemoryEntityCatalog,
    InMemoryGlossarySource,
    ResolutionHistory,
    normalize_surface,
)

WORKSPACE = "leyenda"
OTHER_WORKSPACE = "tinieblas"
ASSET_ID = "asset:manual-001"
EPISODE_ID = "episode:manual-001:p12"
GAME_PROFILE = "generic"
#: Ambitos de partida (M2, docs/v3/49-multipartida-diseno.md) dentro del MISMO
#: workspace/juego `WORKSPACE`. `None` en el resto del fichero sigue
#: significando "capa juego": todo el corpus preexistente no declara partida.
PARTIDA_A = "partida:alpha"
PARTIDA_B = "partida:beta"


def h(seed: str) -> dict[str, str]:
    return {"algorithm": "sha256", "value": hashlib.sha256(seed.encode("utf-8")).hexdigest()}


SOURCE_HASH = h(ASSET_ID)


def mention(
    mention_id: str,
    surface: str,
    *,
    types: Sequence[tuple[str, float]] = (("Character", 0.92),),
    confidence: float = 0.92,
    workspace: str = WORKSPACE,
    asset_id: str = ASSET_ID,
    evidence: Sequence[str] = ("fragment:p12:0",),
    normalized: str | None = None,
    partida_id: str | None = None,
) -> EntityMention:
    """`EntityMention` valida y minima para alimentar al resolutor."""
    return EntityMention(
        contract_version=CONTRACT_VERSION,
        workspace=workspace,
        source_asset_id=asset_id,
        source_hash=SOURCE_HASH,
        provider_trace=[
            provider_step("ner.deterministic", Provider.LOCAL, "s9k.ner", "3.0.0", ["surface"])
        ],
        produced_by_step="ner.deterministic",
        mention_id=mention_id,
        episode_id=EPISODE_ID,
        surface=surface,
        normalized_surface=normalize_surface(surface) if normalized is None else normalized,
        start=0,
        end=max(1, len(surface)),
        bbox=None,
        time_start=None,
        time_end=None,
        type_candidates=[{"type": t, "confidence": c} for t, c in types],
        confidence=confidence,
        coreference_candidates=[],
        evidence_fragment_ids=list(evidence),
        partida_id=partida_id,
    )


# -- Catalogo ---------------------------------------------------------------
#: Cada entrada existe por un motivo, anotado al lado.
CATALOG_ENTITIES: tuple[CatalogEntity, ...] = (
    # Match exacto y por alias.
    CatalogEntity(
        entity_id="entity:daiki",
        workspace=WORKSPACE,
        entity_type="Character",
        canonical_name="Daiki",
        aliases=("El Magistrado", "Daiki-san"),
    ),
    # HOMONIMO en otra boveda: mismo nombre, entidad distinta.
    CatalogEntity(
        entity_id="entity:daiki-tinieblas",
        workspace=OTHER_WORKSPACE,
        entity_type="Character",
        canonical_name="Daiki",
    ),
    # Gemela en la OTRA boveda de una entidad que el glosario de `leyenda` sabe
    # escribir mal. Existe para que la fuga de glosario entre bovedas sea
    # DETECTABLE: sin ella, el filtro del catalogo taparia el del glosario.
    CatalogEntity(
        entity_id="entity:casa-ciervo-tinieblas",
        workspace=OTHER_WORKSPACE,
        entity_type="Faction",
        canonical_name="Casa del Ciervo",
    ),
    # Nombre casi identico a otro: fuente de ambiguedad legitima.
    CatalogEntity(
        entity_id="entity:casa-ciervo",
        workspace=WORKSPACE,
        entity_type="Faction",
        canonical_name="Casa del Ciervo",
    ),
    CatalogEntity(
        entity_id="entity:casa-cuervo",
        workspace=WORKSPACE,
        entity_type="Faction",
        canonical_name="Casa del Cuervo",
    ),
    # Colision de TIPOS: la superficie "Umbra" designa una faccion en el
    # catalogo, pero el extractor puede proponerla como Location.
    CatalogEntity(
        entity_id="entity:umbra-faccion",
        workspace=WORKSPACE,
        entity_type="Faction",
        canonical_name="Umbra",
    ),
    # Dos entidades DISTINTAS que comparten exactamente el mismo alias: el caso
    # que obliga a REVIEW por ambiguedad, no a elegir la primera.
    CatalogEntity(
        entity_id="entity:kaede-a",
        workspace=WORKSPACE,
        entity_type="Character",
        canonical_name="Kaede la Mayor",
        aliases=("Kaede",),
    ),
    CatalogEntity(
        entity_id="entity:kaede-b",
        workspace=WORKSPACE,
        entity_type="Character",
        canonical_name="Kaede la Menor",
        aliases=("Kaede",),
    ),
)


#: Entidades PRIVADAS de partida (M2), en el MISMO workspace/juego que
#: `CATALOG_ENTITIES`. Existen aparte porque son un corpus nuevo, no una
#: variante del anterior: `CATALOG_ENTITIES` sigue siendo integramente capa
#: juego (`partida_id=None`), asi que ningun test preexistente que la use
#: cambia de comportamiento.
PARTIDA_ENTITIES: tuple[CatalogEntity, ...] = (
    # Nacida en la partida alpha. Nunca debe ser candidata desde beta ni desde
    # la capa juego.
    CatalogEntity(
        entity_id="entity:aldric-alpha",
        workspace=WORKSPACE,
        entity_type="Character",
        canonical_name="Aldric",
        partida_id=PARTIDA_A,
    ),
    # HOMONIMO exacto en OTRA partida del MISMO juego: el caso que probaria un
    # cruce silencioso si el resolutor solo mirase el nombre.
    CatalogEntity(
        entity_id="entity:aldric-beta",
        workspace=WORKSPACE,
        entity_type="Character",
        canonical_name="Aldric",
        partida_id=PARTIDA_B,
    ),
)


def catalog_with_partidas() -> InMemoryEntityCatalog:
    """Catalogo con capa juego (`CATALOG_ENTITIES`) + partidas (`PARTIDA_ENTITIES`)."""
    return InMemoryEntityCatalog((*CATALOG_ENTITIES, *PARTIDA_ENTITIES))


#: Glosario: la unica pieza que sabe que "Daiqui" es como el ASR escribe "Daiki".
GLOSSARY_TERMS: tuple[dict[str, Any], ...] = (
    {
        "workspace": WORKSPACE,
        "canonical_term": "Daiki",
        "term_type": "Character",
        "aliases": ["Daiki-san"],
        "spoken_forms": ["daiki san"],
        "error_forms": ["Daiqui", "Dayki"],
        "confidence": 0.97,
    },
    {
        "workspace": WORKSPACE,
        "canonical_term": "Casa del Ciervo",
        "term_type": "Faction",
        "error_forms": ["Casa del Siervo"],
        "confidence": 0.9,
    },
    # Termino del OTRO workspace: nunca debe alcanzar a `leyenda`.
    {
        "workspace": OTHER_WORKSPACE,
        "canonical_term": "Daiki",
        "term_type": "Character",
        "error_forms": ["Daiqui"],
        "confidence": 0.99,
    },
)


def catalog() -> InMemoryEntityCatalog:
    return InMemoryEntityCatalog(CATALOG_ENTITIES)


def glossary() -> InMemoryGlossarySource:
    return InMemoryGlossarySource(GLOSSARY_TERMS)


class LeakyCatalog(EntityCatalog):
    """Catalogo DEFECTUOSO: ignora el workspace y lo devuelve todo.

    No es un capricho de test: modela el fallo realista (una consulta Cypher a
    la que se le olvido el `WHERE workspace = $ws`). El resolutor debe seguir
    sin filtrar identidades entre bovedas aunque su fuente de datos sea mala.
    """

    def __init__(self, entities: Sequence[CatalogEntity] = CATALOG_ENTITIES) -> None:
        self._entities = tuple(entities)

    def entities(
        self, workspace: str, *, partida_scope: str | None = None
    ) -> Sequence[CatalogEntity]:
        # Ignora tambien `partida_scope` a proposito: es el mismo bug de
        # workspace (Cypher sin WHERE), extendido al segundo eje de M2.
        return self._entities


class LeakyHistory(ResolutionHistory):
    """Historial DEFECTUOSO: ignora el workspace al consultar.

    Modela dos fallos realistas a la vez — una implementacion de `lookup` que
    se olvida del argumento, y una entrada cuyo `workspace` no coincide con su
    clave. El resolutor debe seguir sin enlazar entre bovedas: es la segunda
    cerradura (`history_entry_allowed`) la que lo impide, no el indice.
    """

    def lookup(self, workspace: str, surface: str, *, partida_scope: str | None = None):
        # Ignora tambien `partida_scope`: mismo bug de M2 gemelo al de workspace.
        found = super().lookup(workspace, surface, partida_scope=partida_scope)
        if found is not None:
            return found
        target = normalize_surface(surface)
        for entry in self.entries():
            if entry.normalized_surface == target:
                return entry
        return None


__all__ = [
    "WORKSPACE",
    "OTHER_WORKSPACE",
    "ASSET_ID",
    "EPISODE_ID",
    "GAME_PROFILE",
    "SOURCE_HASH",
    "CATALOG_ENTITIES",
    "GLOSSARY_TERMS",
    "PARTIDA_A",
    "PARTIDA_B",
    "PARTIDA_ENTITIES",
    "mention",
    "catalog",
    "catalog_with_partidas",
    "glossary",
    "LeakyCatalog",
    "LeakyHistory",
    "h",
]
