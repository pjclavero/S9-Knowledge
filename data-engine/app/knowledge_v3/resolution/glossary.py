# -*- coding: utf-8 -*-
"""Fuente de glosario para la cascada de resolucion.

El glosario del sistema actual (`glossary/*`, 1044 terminos en `leyenda`)
conoce las formas habladas y las formas ERRONEAS de cada termino: es la unica
pieza que sabe que `"Daiqui"` es como el ASR escribe `"Daiki"`. Aprovecharlo es
lo que separa una resolucion util de una que solo compara cadenas.

Este modulo NO importa `glossary.*`: define la interfaz minima que la cascada
necesita (`lookup`) y una implementacion en memoria. El puente con el
`GlossaryStore` real (SQLite, `state/glossary.db`) queda como enganche
declarado, por dos motivos: ese store esta fuera del repo (gitignored) y no se
puede ejercitar aqui, y V3 no debe acoplarse a un almacen de V1/V2 sin medirlo
antes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .normalization import normalize_surface

#: Como se llego del termino del glosario a la superficie observada.
#: `canonical` y `alias` son formas ESCRITAS deliberadamente; `spoken_form` y
#: `error_form` son formas degradadas (ASR/OCR) y por eso puntuan menos.
GLOSSARY_KINDS: tuple[str, ...] = ("canonical", "alias", "spoken_form", "error_form")

#: Formas degradadas: la cascada les aplica `glossary_variant_score`.
DEGRADED_KINDS: frozenset[str] = frozenset({"spoken_form", "error_form"})


@dataclass(frozen=True)
class GlossaryHit:
    """Termino de glosario que explica una superficie observada."""

    canonical_term: str
    kind: str
    term_type: str | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in GLOSSARY_KINDS:
            raise ValueError(f"kind desconocido: {self.kind!r}")

    @property
    def normalized_term(self) -> str:
        return normalize_surface(self.canonical_term)

    @property
    def degraded(self) -> bool:
        return self.kind in DEGRADED_KINDS


class GlossarySource(ABC):
    """Consulta de SOLO LECTURA del glosario, por workspace."""

    @abstractmethod
    def lookup(self, workspace: str, normalized_surface: str) -> Sequence[GlossaryHit]:
        """Terminos cuya forma canonica, alias, forma hablada o forma erronea
        coincide con la superficie normalizada. Orden estable."""


class NullGlossarySource(GlossarySource):
    """Glosario vacio. Es el defecto y la ablacion "sin glosario"."""

    def lookup(self, workspace: str, normalized_surface: str) -> Sequence[GlossaryHit]:
        return ()


class InMemoryGlossarySource(GlossarySource):
    """Glosario en memoria construido desde terminos sueltos.

    Acepta dicts o cualquier objeto con los atributos de `GlossaryTerm`
    (`canonical_term`, `term_type`, `aliases`, `spoken_forms`, `error_forms`,
    `confidence`, `workspace`) — duck typing deliberado para poder alimentarlo
    con el glosario real sin importarlo ni acoplarse a el.
    """

    def __init__(self, terms: Iterable[Any] = ()) -> None:
        self._index: dict[tuple[str, str], list[GlossaryHit]] = {}
        for term in terms:
            self.add(term)

    @staticmethod
    def _field(term: Any, name: str, default: Any) -> Any:
        if isinstance(term, dict):
            value = term.get(name, default)
        else:
            value = getattr(term, name, default)
        return default if value is None else value

    def add(self, term: Any) -> "InMemoryGlossarySource":
        workspace = str(self._field(term, "workspace", ""))
        canonical = str(self._field(term, "canonical_term", ""))
        if not workspace or not canonical:
            raise ValueError("el termino de glosario necesita workspace y canonical_term")
        term_type = self._field(term, "term_type", None)
        confidence = float(self._field(term, "confidence", 1.0))
        enabled = bool(self._field(term, "enabled", True))
        if not enabled:
            return self

        forms: list[tuple[str, str]] = [(canonical, "canonical")]
        for attr, kind in (
            ("aliases", "alias"),
            ("spoken_forms", "spoken_form"),
            ("error_forms", "error_form"),
        ):
            for form in self._field(term, attr, ()) or ():
                forms.append((str(form), kind))

        for surface, kind in forms:
            key = (workspace, normalize_surface(surface))
            if not key[1]:
                continue
            hit = GlossaryHit(
                canonical_term=canonical,
                kind=kind,
                term_type=term_type if term_type in _KNOWN_TYPES else None,
                confidence=confidence,
            )
            bucket = self._index.setdefault(key, [])
            if hit not in bucket:
                bucket.append(hit)
        return self

    def lookup(self, workspace: str, normalized_surface: str) -> Sequence[GlossaryHit]:
        hits = self._index.get((workspace, normalized_surface), [])
        # Orden estable: primero las formas escritas, luego las degradadas, y
        # dentro de cada grupo por termino canonico.
        return tuple(
            sorted(hits, key=lambda h: (GLOSSARY_KINDS.index(h.kind), h.canonical_term))
        )


class GlossaryStoreSource(GlossarySource):  # pragma: no cover - enganche
    """ENGANCHE: puente hacia `glossary.glossary_store.GlossaryStore` (V1/V2).

    Deliberadamente sin implementar. El store real vive en un SQLite fuera del
    repositorio (`state/glossary.db`, gitignored) y ya causo una divergencia de
    medicion documentada (`docs/v3/00-audit-current-system.md`). Acoplar V3 a el
    sin poder ejecutarlo aqui seria escribir codigo que nadie ha visto correr.

    Quien lo implemente: `GlossaryStore.search_terms(workspace=...)` es de solo
    lectura; basta con mapear cada `GlossaryTerm` a `InMemoryGlossarySource.add`
    y cachear por workspace.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def lookup(self, workspace: str, normalized_surface: str) -> Sequence[GlossaryHit]:
        raise NotImplementedError(
            "GlossaryStoreSource es un enganche declarado: lo completa el bloque "
            "de integracion, que si puede ejecutar el store real."
        )


_KNOWN_TYPES = frozenset({"Character", "Location", "Faction", "Object", "Event", "Concept"})

__all__ = [
    "GlossaryHit",
    "GlossarySource",
    "NullGlossarySource",
    "InMemoryGlossarySource",
    "GlossaryStoreSource",
    "GLOSSARY_KINDS",
    "DEGRADED_KINDS",
]
