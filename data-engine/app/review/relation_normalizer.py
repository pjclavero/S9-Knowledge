# -*- coding: utf-8 -*-
"""Normalizador determinista de extremos de relación (Prioridad 2.1).

El benchmark mostró relaciones con extremos en forma corta ("Hisao" en vez de
"Bayushi Hisao") y con la dirección invertida ("Clan Escorpión MEMBER_OF
Bayushi Hisao"). Este módulo, aplicado tras la extracción, resuelve `from`/`to`
a nombre canónico usando las entidades del propio source y el glosario del
workspace, corrige la dirección según el esquema de tipos, y marca los extremos
no resueltos o ambiguos (que el quality gate mantendrá en needs_review).

No consulta Neo4j (la resolución contra Neo4j sigue en resolver.py, solo lectura).
No inventa entidades: si un extremo no se resuelve, se conserva el texto original
y se marca `unresolved`.
"""
from __future__ import annotations
import unicodedata
from typing import Optional

# Tipos direccionales: origen esperado -> destino esperado (por familia de tipo).
# Usado para corregir inversiones evidentes.
_FROM_CHARACTER_TO_FACTION = {"MEMBER_OF", "WORKS_FOR", "SERVES", "BELONGS_TO"}
_FROM_CHARACTER_TO_LOCATION = {"FOUGHT_AT", "LOCATED_IN"}
_FROM_CHARACTER_TO_OBJECT = {"OWNS", "CREATED"}
_FROM_CHARACTER_TO_EVENT = {"PARTICIPATED_IN"}

_STOP_TOKENS = {"clan", "el", "la", "los", "las", "de", "del", "los", "the"}


def _fold(s: Optional[str]) -> str:
    """minúsculas + sin acentos + espacios colapsados."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def build_alias_map(entities: list[dict], glossary_aliases: Optional[dict] = None):
    """Construye {fold(alias) -> canonical} a partir de las entidades extraídas y
    el glosario. Devuelve (alias_map, type_map, ambiguous_folds)."""
    alias_map: dict[str, str] = {}
    type_map: dict[str, str] = {}
    token_owner: dict[str, set] = {}

    def _canon_name(e):
        return e.get("name") or ""

    for e in entities:
        name = _canon_name(e)
        if not name:
            continue
        f = _fold(name)
        alias_map.setdefault(f, name)
        type_map[f] = e.get("entity_type") or ""
        # tokens individuales significativos → posible alias corto
        for tok in f.split():
            if len(tok) < 3 or tok in _STOP_TOKENS:
                continue
            token_owner.setdefault(tok, set()).add(name)

    # tokens que apuntan a un único canónico → alias no ambiguo
    ambiguous: set[str] = set()
    for tok, owners in token_owner.items():
        if len(owners) == 1:
            canonical = next(iter(owners))
            alias_map.setdefault(tok, canonical)
        else:
            ambiguous.add(tok)

    # glosario del workspace (alias -> canonical), no sobreescribe entidades
    if glossary_aliases:
        for alias, canonical in glossary_aliases.items():
            fa = _fold(alias)
            if fa and fa not in alias_map:
                alias_map[fa] = canonical

    return alias_map, type_map, ambiguous


def resolve_endpoint(raw: str, alias_map: dict, ambiguous: set):
    """Devuelve (canonical, match_type). match_type ∈
    exact_match | canonical_match | alias_match | ambiguous_match | unresolved."""
    if not raw:
        return raw, "unresolved"
    f = _fold(raw)
    if f in ambiguous and f not in alias_map:
        return raw, "ambiguous_match"
    if f in alias_map:
        canonical = alias_map[f]
        if raw == canonical:
            return canonical, "exact_match"
        if _fold(canonical) == f:
            return canonical, "canonical_match"
        return canonical, "alias_match"
    return raw, "unresolved"


def _looks_like(tp: str, target: str) -> bool:
    return (tp or "").lower() == target.lower()


def _infer_type(name: str, type_map: dict) -> str:
    """Tipo de una entidad; infiere Faction para nombres 'Clan X' aunque no se
    hayan extraído como entidad."""
    t = type_map.get(_fold(name), "")
    if not t and _fold(name).startswith("clan "):
        return "Faction"
    return t


def normalize_relations(entities: list[dict], relations: list[dict],
                        glossary_aliases: Optional[dict] = None) -> list[dict]:
    """Resuelve extremos y corrige dirección. Muta y devuelve `relations`.

    Cada relación recibe:
      - from_entity/to_entity canónicos cuando se resuelven;
      - _from_match / _to_match (tipos de match);
      - status='needs_review' y confidence reducida si algún extremo queda
        `unresolved`/`ambiguous_match` (el quality gate ya evita autoaprobación).
    """
    alias_map, type_map, ambiguous = build_alias_map(entities, glossary_aliases)

    for r in relations:
        fc, fmt = resolve_endpoint(r.get("from_entity", ""), alias_map, ambiguous)
        tc, tmt = resolve_endpoint(r.get("to_entity", ""), alias_map, ambiguous)
        rtype = (r.get("relation_type") or "").upper()

        # Rescate: facciones "Clan X" no extraídas como entidad son válidas.
        if fmt == "unresolved" and _fold(fc).startswith("clan "):
            fmt = "canonical_match"
        if tmt == "unresolved" and _fold(tc).startswith("clan "):
            tmt = "canonical_match"

        # Corrección de dirección según el esquema, usando los tipos resueltos.
        ft = _infer_type(fc, type_map)
        tt = _infer_type(tc, type_map)
        swap = False
        if rtype in _FROM_CHARACTER_TO_FACTION:
            if _looks_like(ft, "Faction") and _looks_like(tt, "Character"):
                swap = True
        elif rtype in _FROM_CHARACTER_TO_LOCATION:
            if _looks_like(ft, "Location") and _looks_like(tt, "Character"):
                swap = True
        elif rtype in _FROM_CHARACTER_TO_OBJECT:
            if _looks_like(ft, "Object") and _looks_like(tt, "Character"):
                swap = True
        elif rtype in _FROM_CHARACTER_TO_EVENT:
            if _looks_like(ft, "Event") and _looks_like(tt, "Character"):
                swap = True
        if swap:
            fc, tc = tc, fc
            fmt, tmt = tmt, fmt

        r["from_entity"] = fc
        r["to_entity"] = tc
        r["_from_match"] = fmt
        r["_to_match"] = tmt

        if fmt in ("unresolved", "ambiguous_match") or tmt in ("unresolved", "ambiguous_match"):
            r["status"] = "needs_review"
            # penaliza confianza para que nunca alcance autoaprobación
            try:
                r["confidence"] = min(float(r.get("confidence", 0.5)), 0.55)
            except Exception:
                r["confidence"] = 0.5
    return relations
