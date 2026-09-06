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
    #: Ambito de partida (M2, docs/v3/49-multipartida-diseno.md). `None` =
    #: capa juego compartida (lore); un valor = nacida dentro de esa partida.
    #: Ortogonal a `workspace`, igual que en los contratos de M0.
    partida_id: str | None = None

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
        if self.partida_id is not None and not self.partida_id:
            raise ValueError("partida_id vacio: usa None para la capa juego, no ''")
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
    def entities(
        self, workspace: str, *, partida_scope: str | None = None
    ) -> Sequence[CatalogEntity]:
        """Entidades VISIBLES del workspace, en orden estable.

        Contrato de la interfaz: la implementacion NO debe devolver entidades de
        otro workspace. El resolutor vuelve a filtrar de todos modos (defensa en
        profundidad): un catalogo con un bug no puede filtrar identidades entre
        boveda y boveda.

        `partida_scope` (M2, docs/v3/49-multipartida-diseno.md, INVARIANTE 1):
        ademas del workspace, solo son visibles las entidades cuyo
        `partida_id` sea `None` (capa juego compartida) o coincida exactamente
        con `partida_scope`. `partida_scope=None` (por defecto, resolucion de
        la capa juego) deja ver SOLO la capa juego — la capa juego jamas
        "captura" una entidad nacida en una partida. Todo el material existente
        tiene `partida_id=None`, asi que el comportamiento por defecto es
        identico al de antes de M2.
        """

    def get(
        self, workspace: str, entity_id: str, *, partida_scope: str | None = None
    ) -> CatalogEntity | None:
        """Entidad concreta del workspace VISIBLE en `partida_scope`, o `None`."""
        for entity in self.entities(workspace, partida_scope=partida_scope):
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

    def entities(
        self, workspace: str, *, partida_scope: str | None = None
    ) -> Sequence[CatalogEntity]:
        bucket = self._by_workspace.get(workspace, {})
        # Orden por entity_id: el determinismo del desempate final depende de
        # que la entrada no dependa del orden de insercion.
        visible = (
            bucket[k] for k in sorted(bucket)
            if bucket[k].partida_id is None or bucket[k].partida_id == partida_scope
        )
        return tuple(visible)

    def get(
        self, workspace: str, entity_id: str, *, partida_scope: str | None = None
    ) -> CatalogEntity | None:
        """Busqueda DIRECTA por id, sin filtrar por `partida_scope`.

        Deliberado: esta se usa para comprobaciones de PROPIEDAD/integridad
        (p.ej. `history_entry_allowed`), donde hace falta saber la verdad
        completa de a quien pertenece un `entity_id` ya conocido, no la vista
        recortada que ve la cascada. `partida_scope` se acepta por
        compatibilidad de firma con la clase base y se ignora aqui a proposito.
        """
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

    IMPLEMENTADO por el carril B contra un Neo4j real y efimero. La frontera
    (constructor, firma, aislamiento por workspace, prohibicion de escritura)
    la habia dejado declarada el bloque anterior, que no tenia grafo con el
    que medirla; aqui si lo hay, y la consulta se ejecuta de verdad antes de
    afirmar que funciona.

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
    5. `partida_scope` (M2) debe filtrarse TAMBIEN en la consulta Cypher
       (`WHERE n.partida_id IS NULL OR n.partida_id = $partida_scope`), nunca
       en Python: es la misma regla del punto 1, aplicada al segundo eje de
       aislamiento.
    """

    IMPLEMENTADO_POR = "carril B, medido contra un Neo4j real y efimero"

    def __init__(self, driver: Any, *, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    def entities(
        self, workspace: str, *, partida_scope: str | None = None
    ) -> Sequence[CatalogEntity]:
        """Las entidades que el grafo TIENE, no las que un fichero declara.

        Los cinco requisitos del enganche, cumplidos donde se pueden observar:

        1 y 5. `workspace` y `partida_scope` van en el `WHERE` de
        `cypher.list_entities_query`, no en un filtro de Python posterior.
        2. La consulta es `MATCH` + `RETURN`.
        3. Un fallo del driver se propaga (`reads.list_entities` no lo captura).
        4. `locate()` esta implementado justo debajo.

        `entity_type` sale de la propiedad del nodo, no de sus etiquetas: la
        etiqueta la elige el writer desde el mismo campo, y leer la propiedad
        evita tener que adivinar cual de las etiquetas es el tipo.
        """
        from ..writer.reads import list_entities

        filas = list_entities(self._driver, workspace, partida_scope)
        return tuple(
            CatalogEntity(
                entity_id=fila.entity_id,
                workspace=workspace,
                entity_type=fila.entity_type,
                # Sin `name` no hay superficie que comparar. Se cae al
                # `entity_id` en vez de inventar un nombre: el resolutor vera
                # una superficie que no casa con nada, que es la verdad.
                canonical_name=fila.name or fila.entity_id,
                aliases=(),
                provisional=False,
                metadata={
                    "graph_version": fila.version,
                    "graph_state_hash": fila.state_hash,
                    "graph_status": fila.status,
                    "graph_labels": list(fila.labels),
                },
                partida_id=fila.partida_id,
            )
            for fila in filas
        )

    def locate(self, entity_id: str) -> str | None:
        """La segunda cerradura: de que boveda es este `entity_id`.

        Devuelve `None` tanto si no consta como si consta en MAS de un
        workspace. Lo segundo no es un empate que se pueda desempatar aqui:
        es una violacion del aislamiento, y responder con uno de los dos
        seria elegir a ciegas cual de las dos bovedas gana.
        """
        from ..writer.reads import locate_entity

        encontrados = locate_entity(self._driver, entity_id)
        return encontrados[0] if len(encontrados) == 1 else None


__all__ = [
    "ENTITY_TYPES",
    "CatalogEntity",
    "EntityCatalog",
    "InMemoryEntityCatalog",
    "Neo4jEntityCatalog",
]
