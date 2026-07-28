# -*- coding: utf-8 -*-
"""Lexico de superficies conocidas: glosario V1 + alias del `GameProfile`.

El extractor determinista NO adivina entidades: reconoce las que alguien ya
declaro. Las fuentes son dos, ambas de solo lectura:

- **glosario V1** (`glossary/`, tabla `glossary_terms`): terminos canonicos con
  alias, formas habladas y formas erroneas. Se consume a traves de un puente
  (`from_glossary_terms` / `from_glossary_store`) que copia lo que necesita a
  estructuras propias: V3 no muta el glosario ni depende de su esquema interno
  mas alla de los campos que lee;
- **GameProfile v3** (`aliases`, `factions`, `titles`): ontologia por juego.

El lexico es inmutable y no toca la red ni Neo4j.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from .text import normalize, phrase_tokens

#: Traduccion de `term_type` del glosario V1 al catalogo canonico de tipos V3.
#: Lo que no esta en el mapa NO se traduce: es preferible una mencion sin tipo a
#: una mencion con el tipo equivocado (el contrato admite `type_candidates: []`).
GLOSSARY_TYPE_MAP = {
    "character": "Character",
    "personaje": "Character",
    "npc": "Character",
    "pj": "Character",
    "pnj": "Character",
    "person": "Character",
    "persona": "Character",
    "location": "Location",
    "lugar": "Location",
    "place": "Location",
    "ubicacion": "Location",
    "region": "Location",
    "ciudad": "Location",
    "faction": "Faction",
    "faccion": "Faction",
    "organizacion": "Faction",
    "organization": "Faction",
    "casa": "Faction",
    "clan": "Faction",
    "object": "Object",
    "objeto": "Object",
    "item": "Object",
    "artefacto": "Object",
    "event": "Event",
    "evento": "Event",
    "suceso": "Event",
    "concept": "Concept",
    "concepto": "Concept",
    "regla": "Concept",
}


def map_term_type(term_type: Optional[str]) -> Optional[str]:
    """`term_type` de V1 -> tipo canonico V3, o None si no se sabe."""
    if not term_type:
        return None
    return GLOSSARY_TYPE_MAP.get(normalize(term_type))


@dataclass(frozen=True)
class LexiconEntry:
    """Una entidad conocida y todas sus superficies."""

    canonical: str
    entity_type: Optional[str] = None
    variants: tuple[str, ...] = ()
    confidence: float = 0.5
    origin: str = "manual"

    @property
    def normalized(self) -> str:
        return normalize(self.canonical)

    def surfaces(self) -> tuple[str, ...]:
        return (self.canonical, *self.variants)


@dataclass(frozen=True)
class LexiconMatch:
    """Superficie del lexico localizada en un texto concreto."""

    entry: LexiconEntry
    surface: str
    start: int
    end: int
    first_token: int
    last_token: int
    is_canonical: bool

    @property
    def confidence(self) -> float:
        """Un alias vale menos que la forma canonica. No es lo mismo."""
        return self.entry.confidence if self.is_canonical else self.entry.confidence * 0.85


class Lexicon:
    """Coleccion de entradas indexada por secuencia de tokens normalizados.

    El emparejamiento es por TOKENS (ver `text.find_phrase`): 'Elara' no casa
    dentro de 'Elaramir', y los offsets devueltos son del texto original.
    Se prefiere siempre la coincidencia mas LARGA: 'Reino de Val' antes que
    'Val'.
    """

    def __init__(self, entries: Iterable[LexiconEntry] = ()) -> None:
        self._entries: tuple[LexiconEntry, ...] = tuple(entries)
        self._index: dict[tuple[str, ...], list[tuple[LexiconEntry, str, bool]]] = {}
        for entry in self._entries:
            canonical_key = phrase_tokens(entry.canonical)
            for surface in entry.surfaces():
                key = phrase_tokens(surface)
                if not key:
                    continue
                self._index.setdefault(key, []).append(
                    (entry, surface, key == canonical_key)
                )
        self._max_len = max((len(k) for k in self._index), default=0)

    @property
    def entries(self) -> tuple[LexiconEntry, ...]:
        return self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def lookup(self, key: Sequence[str]) -> Optional[tuple[LexiconEntry, str, bool]]:
        hits = self._index.get(tuple(key))
        if not hits:
            return None
        # Desempate determinista: por termino canonico.
        return sorted(hits, key=lambda h: (h[0].canonical, h[1]))[0]

    def find_all(self, tokens: Sequence) -> list[LexiconMatch]:
        """Todas las superficies del lexico presentes en `tokens`, sin solapes.

        Se recogen TODAS las coincidencias posibles y despues se resuelven los
        solapes por longitud descendente. Un barrido izquierda-derecha ingenuo
        no vale: en "la Orden del Alba", el alias "la Orden" empieza antes y se
        llevaria por delante a la forma canonica, que es mas larga y mas
        especifica.
        """
        candidates: list[tuple[int, int, LexiconMatch]] = []
        n = len(tokens)
        for i in range(n):
            for size in range(min(self._max_len, n - i), 0, -1):
                key = tuple(tokens[i + k].norm for k in range(size))
                hit = self.lookup(key)
                if hit is None:
                    continue
                entry, surface, is_canonical = hit
                first, last = tokens[i], tokens[i + size - 1]
                candidates.append(
                    (
                        i,
                        size,
                        LexiconMatch(
                            entry=entry,
                            surface=surface,
                            start=first.start,
                            end=last.end,
                            first_token=first.index,
                            last_token=last.index,
                            is_canonical=is_canonical,
                        ),
                    )
                )
        chosen: list[LexiconMatch] = []
        used: set[int] = set()
        for start, size, match in sorted(
            candidates, key=lambda c: (-c[1], c[0], c[2].entry.canonical)
        ):
            span = set(range(start, start + size))
            if span & used:
                continue
            used |= span
            chosen.append(match)
        return sorted(chosen, key=lambda m: m.start)

    # -- Puentes de solo lectura -----------------------------------------
    @classmethod
    def from_entries(cls, entries: Iterable[LexiconEntry]) -> "Lexicon":
        return cls(entries)

    @classmethod
    def from_glossary_terms(cls, terms: Iterable[Any]) -> "Lexicon":
        """Puente con el glosario V1 (`GlossaryTerm` o cualquier objeto igual).

        Se leen `canonical_term`, `term_type`, `aliases`, `spoken_forms` y
        `confidence`. Las `error_forms` se EXCLUYEN a proposito: son errores
        conocidos de transcripcion, utiles para corregir ASR, pero aceptarlas
        como superficie de entidad meteria falsos positivos en un extractor
        cuyo objetivo declarado es la precision.
        """
        entries: list[LexiconEntry] = []
        for term in terms:
            if getattr(term, "enabled", True) is False:
                continue
            canonical = getattr(term, "canonical_term", None)
            if not canonical:
                continue
            variants = tuple(
                dict.fromkeys(
                    [*(getattr(term, "aliases", ()) or ()), *(getattr(term, "spoken_forms", ()) or ())]
                )
            )
            entries.append(
                LexiconEntry(
                    canonical=canonical,
                    entity_type=map_term_type(getattr(term, "term_type", None)),
                    variants=variants,
                    confidence=float(getattr(term, "confidence", 0.5) or 0.5),
                    origin="glossary",
                )
            )
        return cls(entries)

    @classmethod
    def from_glossary_store(cls, store: Any, workspace: str, *, limit: int = 5000) -> "Lexicon":
        """Lee el glosario del workspace. SOLO lectura: `list_terms`, nada mas."""
        terms = store.list_terms(workspace, enabled_only=True, limit=limit)
        return cls.from_glossary_terms(terms)

    @classmethod
    def from_profile(cls, profile: Any) -> "Lexicon":
        """Alias, facciones y titulos declarados en el `GameProfile`.

        Los titulos NO son entidades: entran como entradas de tipo `Concept`
        solo si el perfil los declara, y con confianza baja.
        """
        entries: list[LexiconEntry] = []
        for alias in getattr(profile, "aliases", ()) or ():
            entries.append(
                LexiconEntry(
                    canonical=alias["canonical"],
                    entity_type=None,
                    variants=tuple(alias.get("variants", ())),
                    confidence=0.8,
                    origin="profile",
                )
            )
        for faction in getattr(profile, "factions", ()) or ():
            entries.append(
                LexiconEntry(
                    canonical=faction,
                    entity_type="Faction",
                    confidence=0.8,
                    origin="profile",
                )
            )
        return cls(entries)

    def merged(self, other: "Lexicon") -> "Lexicon":
        """Union de lexicos. Ante superficie repetida gana la mas especifica.

        'Mas especifica' = la que trae tipo; a igualdad, la de mayor confianza.
        El desempate final es alfabetico para que el resultado no dependa del
        orden de union.
        """
        by_key: dict[str, LexiconEntry] = {}
        for entry in (*self._entries, *other._entries):
            key = entry.normalized
            prev = by_key.get(key)
            if prev is None:
                by_key[key] = entry
                continue
            better = sorted(
                [prev, entry],
                key=lambda e: (e.entity_type is None, -e.confidence, e.origin, e.canonical),
            )[0]
            merged_variants = tuple(dict.fromkeys([*prev.variants, *entry.variants]))
            by_key[key] = LexiconEntry(
                canonical=better.canonical,
                entity_type=better.entity_type,
                variants=merged_variants,
                confidence=max(prev.confidence, entry.confidence),
                origin=better.origin,
            )
        return Lexicon(sorted(by_key.values(), key=lambda e: e.canonical))


__all__ = [
    "GLOSSARY_TYPE_MAP",
    "Lexicon",
    "LexiconEntry",
    "LexiconMatch",
    "map_term_type",
]
