# -*- coding: utf-8 -*-
"""Catalogo de entidades EXISTENTES: entrada del resolutor, nunca salida.

El resolutor no escribe en Neo4j ni en ninguna otra parte. El grafo entra por
esta interfaz y sale, como mucho, una `EntityResolution` que otro subsistema
decidira aplicar. Por eso el catalogo solo tiene metodos de LECTURA: no hay
`create`, no hay `merge`, no hay `save`.

`InMemoryEntityCatalog` es la implementacion real y probada.
`Neo4jEntityCatalog` es un ENGANCHE declarado: la firma y el aislamiento por
workspace estan fijados aqui, pero la consulta la implementa el bloque de
integracion. Devolver datos inventados desde este modulo seria peor que no
tenerlo.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .normalization import normalize_surface

#: Tipos canonicos de `_common-v3.schema.json#/$defs/entity_type`. No se amplia
#: aqui: si el contrato congelado no lo lista, no existe.
ENTITY_TYPES: frozenset[str] = frozenset(
    {"Character", "Location", "Faction", "Object", "Event", "Concept"}
)


@dataclass(frozen=True)
class CatalogEntity:
    """Entidad ya existente en el grafo (o provisional ya asignada).

    `normalized_name` y `normalized_aliases` se derivan SIEMPRE aqui con la
    misma funcion que usa la cascada: si el catalogo trajera su propia
    normalizacion, dos entidades identicas dejarian de parecerlo.
    """

    entity_id: str
    workspace: str
    entity_type: str | None
    canonical_name: str
    aliases: tuple[str, ...] = ()
    description: str | None = None
    #: `True` para entidades creadas como provisionales y aun no canonizadas.
    provisional: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    normalized_name: str = field(init=False, repr=False)
    normalized_aliases: frozenset[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("entity_id vacio")
        if not self.workspace:
            raise ValueError("workspace vacio")
        if self.entity_type is not None and self.entity_type not in ENTITY_TYPES:
            raise ValueError(
                f"entity_type {self.entity_type!r} fuera del catalogo congelado"
            )
        object.__setattr__(self, "aliases", tuple(self.aliases))
        object.__setattr__(self, "normalized_name", normalize_surface(self.canonical_name))
        object.__setattr__(
            self,
            "normalized_aliases",
            frozenset(n for n in (normalize_surface(a) for a in self.aliases) if n),
        )

    def all_normalized_forms(self) -> frozenset[str]:
        """Nombre canonico + alias, todos normalizados."""
        forms = set(self.normalized_aliases)
        if self.normalized_name:
            forms.add(self.normalized_name)
        return frozenset(forms)


class EntityCatalog(ABC):
    """Vista de SOLO LECTURA del catalogo de entidades, por workspace."""

    @abstractmethod
    def entities(self, workspace: str) -> Sequence[CatalogEntity]:
        """Entidades del workspace, en orden estable.

        Contrato de la interfaz: la implementacion NO debe devolver entidades de
        otro workspace. El resolutor vuelve a filtrar de todos modos (defensa en
        profundidad): un catalogo con un bug no puede filtrar identidades entre
        boveda y boveda.
        """

    def get(self, workspace: str, entity_id: str) -> CatalogEntity | None:
        """Entidad concreta del workspace, o `None`."""
        for entity in self.entities(workspace):
            if entity.entity_id == entity_id:
                return entity
        return None

    def locate(self, entity_id: str) -> str | None:
        """Workspace propietario de un identificador, o `None` si no consta.

        Sirve para CONTRASTAR identidades que llegan por caminos que no pasan
        por `entities()` — hoy, el historial de sesion. Distingue tres
        respuestas y las tres importan:

        - un workspace: el catalogo sabe de quien es; si no coincide con el que
          se esta resolviendo, la identidad se descarta;
        - `None`: el catalogo NO lo sabe. No es una contradiccion y no debe
          tratarse como tal: una entidad provisional recien creada por el propio
          resolutor no esta en el catalogo y es perfectamente legitima.

        Por defecto devuelve `None` (implementacion honesta: "no me consta"). Las
        implementaciones que puedan responder deben sobreescribirlo.
        """
        return None


class InMemoryEntityCatalog(EntityCatalog):
    """Catalogo en memoria. Implementacion de referencia y base de los tests."""

    def __init__(self, entities: Iterable[CatalogEntity] = ()) -> None:
        self._by_workspace: dict[str, dict[str, CatalogEntity]] = {}
        for entity in entities:
            self.add(entity)

    def add(self, entity: CatalogEntity) -> "InMemoryEntityCatalog":
        bucket = self._by_workspace.setdefault(entity.workspace, {})
        if entity.entity_id in bucket:
            raise ValueError(
                f"entity_id duplicado en {entity.workspace}: {entity.entity_id}"
            )
        bucket[entity.entity_id] = entity
        return self

    def entities(self, workspace: str) -> Sequence[CatalogEntity]:
        bucket = self._by_workspace.get(workspace, {})
        # Orden por entity_id: el determinismo del desempate final depende de
        # que la entrada no dependa del orden de insercion.
        return tuple(bucket[k] for k in sorted(bucket))

    def get(self, workspace: str, entity_id: str) -> CatalogEntity | None:
        return self._by_workspace.get(workspace, {}).get(entity_id)

    def locate(self, entity_id: str) -> str | None:
        for workspace in sorted(self._by_workspace):
            if entity_id in self._by_workspace[workspace]:
                return workspace
        return None

    def workspaces(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_workspace))


class Neo4jEntityCatalog(EntityCatalog):
    """ENGANCHE de integracion: catalogo respaldado por Neo4j, SOLO LECTURA.

    No esta implementado a proposito. Este editor no tiene acceso a un Neo4j con
    datos reales, y una implementacion no ejecutada nunca es una implementacion
    no verificada: se declara la frontera (constructor, firma, aislamiento por
    workspace y prohibicion de escritura) y se deja la consulta al bloque de
    integracion, que si puede medirla.

    Requisitos que la implementacion debe cumplir:

    1. Toda consulta lleva `workspace` en el `WHERE`; nunca se filtra en Python
       lo que se pudo haber filtrado en la consulta.
    2. Solo sentencias de lectura (`MATCH` / `RETURN`). Ni `CREATE`, ni `MERGE`,
       ni `SET`, ni `DELETE`.
    3. Si el driver no responde, se propaga el error: degradar en silencio a
       "no hay candidatos" convertiria una caida de Neo4j en una avalancha de
       entidades nuevas.
    4. `locate()` deberia implementarse (una consulta por `entity_id` que
       devuelva su workspace): es la segunda cerradura que impide que una
       entidad de otra boveda entre por el historial. Si no se implementa, la
       version por defecto responde "no me consta" y la cerradura se apoya solo
       en el workspace declarado por la entrada — correcto, pero mas debil.
    """

    def __init__(self, driver: Any, *, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    def entities(self, workspace: str) -> Sequence[CatalogEntity]:  # pragma: no cover
        raise NotImplementedError(
            "Neo4jEntityCatalog es un enganche declarado, no una implementacion: "
            "lo completa el bloque de integracion con Neo4j real (solo lectura)."
        )


__all__ = [
    "ENTITY_TYPES",
    "CatalogEntity",
    "EntityCatalog",
    "InMemoryEntityCatalog",
    "Neo4jEntityCatalog",
]
