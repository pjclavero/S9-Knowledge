"""Búsqueda de términos en el glosario con múltiples estrategias.

Orden de búsqueda:
1. Exacta: canonical_term normalizado == query normalizado
2. Por alias: algún alias normalizado == query normalizado
3. Por error_form: alguna forma errónea normalizada == query normalizado
4. Fuzzy: difflib SequenceMatcher sobre normalized_term y aliases/error_forms

Las búsquedas 1-3 son O(n) sobre la lista en memoria (se carga una vez del
store). La fuzzy es también O(n) con umbral configurable.
"""
from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass

from glossary.glossary_models import GlossaryTerm
from glossary.glossary_store import GlossaryStore, normalize_term

log = logging.getLogger("glossary.matcher")


@dataclass
class MatchResult:
    term: GlossaryTerm
    match_type: str        # "exact" | "alias" | "error_form" | "fuzzy"
    matched_value: str     # el valor que hizo match
    score: float           # 1.0 para exact/alias/error_form, ratio para fuzzy


class GlossaryMatcher:
    """Busca términos usando estrategias en cascada.

    Instanciar una vez y llamar a search() repetidamente; la lista de términos
    se cachea en memoria y se puede refrescar con reload().
    """

    def __init__(self, store: GlossaryStore, workspace: str, fuzzy_threshold: float = 0.72):
        self.store = store
        self.workspace = workspace
        self.fuzzy_threshold = fuzzy_threshold
        self._terms: list[GlossaryTerm] = []
        self.reload()

    def reload(self) -> None:
        """Recarga todos los términos del workspace desde el store."""
        self._terms = self.store.list_terms(self.workspace, enabled_only=True)
        log.debug("GlossaryMatcher: %d términos cargados para workspace=%s", len(self._terms), self.workspace)

    def search(self, query: str, limit: int = 10) -> list[MatchResult]:
        """Busca query usando exact → alias → error_form → fuzzy.

        Devuelve resultados únicos (sin duplicar el mismo canonical_term),
        ordenados por score desc, luego priority desc.
        """
        nq = normalize_term(query)
        if not nq:
            return []

        results: list[MatchResult] = []
        seen_ids: set[int | None] = set()

        def _add(term: GlossaryTerm, mtype: str, mval: str, score: float) -> None:
            tid = term.id if term.id is not None else id(term)
            if tid not in seen_ids:
                seen_ids.add(tid)
                results.append(MatchResult(term=term, match_type=mtype, matched_value=mval, score=score))

        # 1. Exacta sobre canonical_term normalizado
        for t in self._terms:
            if t.normalized_term == nq:
                _add(t, "exact", t.canonical_term, 1.0)

        # 2. Alias normalizado
        for t in self._terms:
            for alias in t.aliases:
                if normalize_term(alias) == nq:
                    _add(t, "alias", alias, 1.0)
                    break

        # 3. Error form normalizado
        for t in self._terms:
            for ef in t.error_forms:
                if normalize_term(ef) == nq:
                    _add(t, "error_form", ef, 1.0)
                    break

        # 4. Fuzzy si no hay resultados exactos/alias/error
        if not results:
            fuzzy: list[MatchResult] = []
            for t in self._terms:
                candidates = [t.normalized_term] + [normalize_term(a) for a in t.aliases] + [normalize_term(ef) for ef in t.error_forms]
                best_ratio = 0.0
                best_val = t.canonical_term
                for cand in candidates:
                    ratio = difflib.SequenceMatcher(None, nq, cand).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_val = cand
                if best_ratio >= self.fuzzy_threshold:
                    fuzzy.append(MatchResult(term=t, match_type="fuzzy", matched_value=best_val, score=round(best_ratio, 3)))
            # Ordenar fuzzy por score desc, luego por priority
            fuzzy.sort(key=lambda r: (-r.score, -r.term.priority))
            # Deduplicar
            for mr in fuzzy:
                tid = mr.term.id if mr.term.id is not None else id(mr.term)
                if tid not in seen_ids:
                    seen_ids.add(tid)
                    results.append(mr)

        # Ordenar final: score desc, priority desc
        results.sort(key=lambda r: (-r.score, -r.term.priority))
        return results[:limit]
