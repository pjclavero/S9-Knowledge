# -*- coding: utf-8 -*-
"""Historial de resoluciones de la sesion/corpus.

Para que serve: una vez decidido que `"Ilya"` es `entity:X`, las siguientes
menciones de `"Ilya"` en el mismo corpus deben ir a `entity:X` sin volver a
recorrer glosario ni similitud. Es a la vez COHERENCIA (dos menciones iguales
en el mismo corpus no pueden acabar en entidades distintas por un empate que se
rompio de otra manera) y COSTE (la senal mas barata de la cascada).

Lo que NO es: memoria persistente. El historial vive en un proceso y se
invalida entero con `clear()`. Persistirlo significaria arrastrar decisiones
sin revisar de una ingesta a la siguiente, que es exactamente el fallo que
`CREATE_PROVISIONAL` intenta evitar.

Aislamiento por workspace: la clave del indice EMPIEZA por el workspace. No es
un filtro posterior que se pueda olvidar, es parte de la clave.

Aislamiento por partida (M2, docs/v3/49-multipartida-diseno.md, INVARIANTE 1):
la clave incluye TAMBIEN `partida_id` (`None` para la capa juego). Sin esto,
"Ilya" resuelta en la partida Y compartiria entrada de indice con "Ilya" de la
partida Z del mismo juego, y la segunda mencion de la partida Z heredaria
silenciosamente la identidad de una partida ajena — precisamente lo que el
Invariante 1 prohibe. `lookup()` combina dos claves (la propia del ambito que
pregunta, y la de la capa juego) porque la capa juego SI es visible desde una
partida; la partida NO es visible desde la capa juego (ver `lookup`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Sequence

from .normalization import normalize_surface

#: Acciones que FIJAN una identidad y por tanto son memorizables. `SPLIT` y
#: `REVIEW` no fijan nada: memorizarlas seria memorizar una duda.
BINDING_ACTIONS: frozenset[str] = frozenset(
    {"LINK_EXISTING", "CREATE_NEW", "CREATE_PROVISIONAL"}
)


def _key(workspace: str, partida_id: str | None, normalized_surface: str) -> tuple[str, str, str]:
    """Clave del indice. `partida_id=None` se representa como `""`.

    `""` esta fuera del alfabeto valido de `partida_id` (el patron del schema
    exige `minLength: 1`), asi que no puede colisionar con un valor real, y
    ordena antes que cualquiera de ellos — mantiene `sorted()` totalmente
    determinista sin mezclar `None` y `str` en la comparacion de tuplas (lo que
    lanzaria `TypeError` en cuanto dos entradas de la misma superficie
    difiriesen en partida).
    """
    return (workspace, partida_id or "", normalized_surface)


@dataclass(frozen=True)
class HistoryEntry:
    """Identidad ya fijada para una superficie dentro de un workspace."""

    workspace: str
    normalized_surface: str
    entity_id: str
    entity_type: str | None
    action: str
    confidence: float
    resolution_id: str
    #: Ambito de partida de la decision que fijo esta entrada (M2). `None` =
    #: capa juego compartida.
    partida_id: str | None = None

    @property
    def provisional(self) -> bool:
        return self.action == "CREATE_PROVISIONAL"


class ResolutionHistory:
    """Indice `(workspace, superficie) -> identidad fijada`.

    La sobrescritura NO es silenciosa por defecto: si una superficie ya estaba
    ligada a otra entidad, `record` conserva la entrada de MAYOR confianza y, en
    empate, la primera. Dejar que la ultima gane haria que el resultado
    dependiese del orden de recorrido del corpus.
    """

    def __init__(self, *, entries: Sequence[HistoryEntry] = ()) -> None:
        self._entries: dict[tuple[str, str, str], HistoryEntry] = {}
        for entry in entries:
            self._put(entry)

    # -- Escritura ---------------------------------------------------------
    def _put(self, entry: HistoryEntry) -> bool:
        key = _key(entry.workspace, entry.partida_id, entry.normalized_surface)
        current = self._entries.get(key)
        if current is not None:
            if entry.entity_id == current.entity_id:
                return False
            if entry.confidence <= current.confidence:
                return False
        self._entries[key] = entry
        return True

    def record(
        self,
        *,
        workspace: str,
        surfaces: Sequence[str],
        entity_id: str,
        entity_type: str | None,
        action: str,
        confidence: float,
        resolution_id: str,
        min_confidence: float = 0.0,
        partida_id: str | None = None,
    ) -> int:
        """Memoriza una identidad para todas las superficies del grupo.

        Devuelve cuantas superficies se han indexado. Ignora acciones que no
        fijan identidad y confianzas por debajo del minimo: recordar una
        decision debil convertiria una duda en un precedente.

        `partida_id` (M2) entra en la CLAVE del indice, no solo en el valor: una
        entrada de la partida Y y una de la partida Z para la misma superficie
        del mismo workspace son entradas DISTINTAS, nunca la misma ranura.
        """
        if action not in BINDING_ACTIONS or not entity_id:
            return 0
        if confidence < min_confidence:
            return 0
        written = 0
        for surface in surfaces:
            norm = normalize_surface(surface)
            if not norm:
                continue
            entry = HistoryEntry(
                workspace=workspace,
                normalized_surface=norm,
                entity_id=entity_id,
                entity_type=entity_type,
                action=action,
                confidence=float(confidence),
                resolution_id=resolution_id,
                partida_id=partida_id,
            )
            if self._put(entry):
                written += 1
        return written

    # -- Lectura -----------------------------------------------------------
    def lookup(
        self, workspace: str, surface: str, *, partida_scope: str | None = None
    ) -> HistoryEntry | None:
        """Identidad memorizada para esa superficie, VISIBLE desde `partida_scope`.

        No se comprueba aqui la compatibilidad de tipos a proposito: el
        historial informa, el paso de tipos decide. Si "Umbra" quedo ligada a
        una `Faction` y ahora aparece como `Location`, queremos ver el conflicto
        y mandarlo a `REVIEW`, no que el historial lo oculte devolviendo `None`.

        Direccion UNICA (M2, INVARIANTE 1): desde una partida se ve tambien la
        entrada de la capa juego para esa superficie (si no hay una propia mas
        especifica); desde la capa juego (`partida_scope=None`) NUNCA se
        consulta una entrada de partida — el lore no puede "capturar" una
        identidad fijada dentro de una mesa concreta.
        """
        norm = normalize_surface(surface)
        own = self._entries.get(_key(workspace, partida_scope, norm))
        if own is not None:
            return own
        if partida_scope is None:
            return None
        return self._entries.get(_key(workspace, None, norm))

    def entries(self) -> tuple[HistoryEntry, ...]:
        """Entradas en orden estable (workspace, partida_id, superficie)."""
        return tuple(self._entries[k] for k in sorted(self._entries))

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[HistoryEntry]:
        return iter(self.entries())

    # -- Invalidacion ------------------------------------------------------
    def invalidate_surface(
        self, workspace: str, surface: str, *, partida_id: str | None = None
    ) -> int:
        """Olvida una superficie concreta de un ambito. Devuelve cuantas cayeron."""
        key = _key(workspace, partida_id, normalize_surface(surface))
        return 1 if self._entries.pop(key, None) else 0

    def invalidate_entity(self, workspace: str, entity_id: str) -> int:
        """Olvida TODAS las superficies ligadas a una entidad.

        Es la invalidacion que importa cuando un humano rechaza una fusion o
        canoniza una provisional: si solo se olvidase una superficie, el resto
        seguiria apuntando a una identidad que ya no vale.
        """
        doomed = [
            k for k, v in self._entries.items() if k[0] == workspace and v.entity_id == entity_id
        ]
        for key in doomed:
            del self._entries[key]
        return len(doomed)

    def invalidate_resolution(self, resolution_id: str) -> int:
        """Olvida lo aportado por una resolucion concreta (rollback puntual)."""
        doomed = [k for k, v in self._entries.items() if v.resolution_id == resolution_id]
        for key in doomed:
            del self._entries[key]
        return len(doomed)

    def invalidate_workspace(self, workspace: str) -> int:
        doomed = [k for k in self._entries if k[0] == workspace]
        for key in doomed:
            del self._entries[key]
        return len(doomed)

    def clear(self) -> int:
        count = len(self._entries)
        self._entries.clear()
        return count


__all__ = ["HistoryEntry", "ResolutionHistory", "BINDING_ACTIONS"]
