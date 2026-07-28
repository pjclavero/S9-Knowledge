# -*- coding: utf-8 -*-
"""Extractor de TABLAS: claims desde un episodio `TABLE` estructurado.

Una tabla aplanada a texto pierde justamente lo que la hace una tabla: la
relacion fila-columna. Por eso el contrato `source-episode` lleva `table` con
`header` y `rows`, y por eso este extractor lee la estructura y no el texto.

Como funciona: la primera columna (o la que el encabezado identifique como
sujeto) es el sujeto de la fila; cada columna cuyo encabezado esta MAPEADO a un
predicado produce un claim `sujeto -> predicado -> valor de la celda`.

Precision antes que cobertura, igual que el determinista:

- encabezado no mapeado = ningun claim (diagnostico, no invencion);
- celda con varios valores ("Elara, Kael") = ABSTENCION: no se sabe si la fila
  afirma una relacion o varias;
- celda cuyo texto no aparece en ningun fragmento real = nada. Tambien en una
  tabla la evidencia tiene que existir.

Offsets: un episodio TABLE no suele tener `text`, asi que los offsets de las
menciones son RELATIVOS al texto literal del fragmento que las ancla y se
declara en `metadata.offset_basis`. Un offset sin base declarada no es
reproducible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from ..contracts import Provider, SourceEpisode
from .base import (
    Diagnostic,
    ExtractionContext,
    ExtractionOutput,
    Extractor,
    ExtractorInfo,
    abstention_claim,
    build_claim,
    build_mention,
    clamp,
    emit,
    low_quality,
)
from .text import EvidenceIndex, normalize

TABLE_STEP = "extract.table"

TABLE_INFO = ExtractorInfo(
    step=TABLE_STEP,
    provider=Provider.LOCAL,
    name="s9k.extraction.table",
)

#: Confianza base de un claim tabular. Mas alta que la del texto libre porque la
#: estructura ya resuelve la ambiguedad sintactica, pero NO es 1: el mapeo del
#: encabezado a predicado sigue siendo una interpretacion.
TABLE_BASE_CONFIDENCE = 0.8

#: Encabezados que identifican la columna SUJETO.
SUBJECT_HEADERS: frozenset = frozenset(
    {"nombre", "personaje", "entidad", "name", "sujeto", "pj", "npc", "titulo del pj"}
)


@dataclass(frozen=True)
class ColumnRule:
    """Encabezado de columna -> predicado, direccion y tipo ESPERADO del objeto.

    `expected_object_type` es una EXPECTATIVA con la que contrastar, nunca un
    tipo que se le pueda colgar a la celda. Que una columna se llame "Ubicacion"
    no convierte su contenido en un `Location`: si en esa celda hay un nombre de
    persona, tiparlo como lugar es inventar un dato y ademas hace pasar el
    control de dominio/rango del perfil.
    """

    predicate: str
    headers: tuple[str, ...]
    direction: str = "SUBJECT_TO_OBJECT"
    expected_object_type: Optional[str] = None


#: Mapeo curado de encabezados. Corto a proposito: cada entrada es una apuesta
#: de precision. La direccion es EXPLICITA porque una columna "lider" dice que el
#: objeto lidera al sujeto, no al reves, y confundirlo invierte el grafo entero.
COLUMN_RULES: tuple[ColumnRule, ...] = (
    ColumnRule("MEMBER_OF", ("faccion", "casa", "clan", "organizacion", "gremio", "orden"),
               expected_object_type="Faction"),
    ColumnRule("LOCATED_IN", ("ubicacion", "lugar", "region", "ciudad", "residencia"),
               expected_object_type="Location"),
    ColumnRule("CHILD_OF", ("padre", "madre", "progenitor"), expected_object_type="Character"),
    ColumnRule("LEADS", ("lider", "jefe", "capitan"), direction="OBJECT_TO_SUBJECT",
               expected_object_type="Character"),
    ColumnRule("ALLY_OF", ("aliado", "aliados", "alianza"),),
    ColumnRule("ENEMY_OF", ("enemigo", "enemigos", "rival"),),
    ColumnRule("OWNS", ("objeto", "arma", "artefacto"), expected_object_type="Object"),
)

#: Separadores que delatan una celda multivalor.
_MULTIVALUE_RE = re.compile(r",|;|\s+y\s+|/|\|")


def _column_rule(header: str) -> Optional[ColumnRule]:
    key = normalize(header)
    for rule in COLUMN_RULES:
        if key in rule.headers:
            return rule
    return None


def _confirmed_type(ctx: ExtractionContext, surface: str) -> Optional[str]:
    """Tipo de una superficie SOLO si el lexico lo confirma. Nunca deducido."""
    lexicon = ctx.lexicon
    if lexicon is None:
        return None
    key = normalize(surface)
    for entry in lexicon.entries:
        if entry.normalized == key or key in {normalize(v) for v in entry.variants}:
            return entry.entity_type
    return None


def _subject_column(header: Sequence[str]) -> int:
    for i, name in enumerate(header):
        if normalize(name) in SUBJECT_HEADERS:
            return i
    return 0


class TableExtractor(Extractor):
    """Claims desde la estructura fila-columna de un episodio `TABLE`."""

    info = TABLE_INFO

    def __init__(
        self,
        *,
        rules: Sequence[ColumnRule] = COLUMN_RULES,
        emit_abstentions: bool = True,
    ) -> None:
        self.rules = tuple(rules)
        self.emit_abstentions = emit_abstentions

    def supports(self, episode: SourceEpisode) -> bool:
        return episode.modality == "TABLE" and bool(episode.table)

    # -- anclaje ----------------------------------------------------------
    def _anchor_cell(self, index: EvidenceIndex, row_i: int, cell: str):
        """Ancla el texto de una celda a un fragmento real.

        Si hay al menos tantos fragmentos como filas se prueba PRIMERO el
        fragmento de esa fila: en una tabla con valores repetidos ("Valdor" en
        cuatro filas), anclar siempre a la primera aparicion colapsaria cuatro
        menciones distintas en una sola.
        """
        frags = index.fragments
        if row_i < len(frags) and index.contains_quote(frags[row_i].fragment_id, cell):
            return index.anchor_quote(cell, frags[row_i].fragment_id)
        return index.anchor_quote(cell)

    def _mention_for(
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        index: EvidenceIndex,
        out: ExtractionOutput,
        cache: dict,
        row_i: int,
        cell: str,
        column: str,
    ) -> Optional[str]:
        """Mencion de una celda. El tipo se CONFIRMA con el lexico o no se pone.

        No se acepta el tipo esperado por la columna: seria el propio extractor
        rellenando el dato que despues usa para validarse contra el perfil.
        """
        key = (row_i, cell, column)
        if key in cache:
            return cache[key]
        entity_type = _confirmed_type(ctx, cell)
        anchor = self._anchor_cell(index, row_i, cell)
        if anchor is None:
            out.diagnostics.append(
                Diagnostic(
                    "TABLE_CELL_WITHOUT_EVIDENCE", self.info.step, episode.episode_id,
                    f"fila {row_i}, columna {column!r}: {cell!r} no aparece en ningun fragmento",
                )
            )
            cache[key] = None
            return None
        types = [{"type": entity_type, "confidence": 0.7}] if entity_type else []
        # Nota: `types` vacio es una salida legitima. La celda queda sin tipar y
        # el claim que la use tendra que pedir revision o abstenerse.
        mention = build_mention(
            info=self.info,
            episode=episode,
            surface=cell,
            start=anchor.start,
            end=anchor.end,
            evidence_fragment_ids=[anchor.fragment_id],
            type_candidates=types,
            confidence=0.75,
            basis=anchor.basis,
            metadata={"table_row": row_i, "table_column": column},
        )
        # Dos filas con el mismo valor y el mismo anclaje son la MISMA mencion
        # (mismo id determinista): se reutiliza en vez de emitirla dos veces.
        if any(m.mention_id == mention.mention_id for m in out.mentions):
            cache[key] = mention.mention_id
            return cache[key]
        cache[key] = mention.mention_id if emit(mention, out, self.info, episode.episode_id) else None
        return cache[key]

    # -- interfaz ---------------------------------------------------------
    def extract_episode(  # noqa: C901 - un bucle por fila y una guarda por regla
        self,
        ctx: ExtractionContext,
        episode: SourceEpisode,
        prior: Optional[ExtractionOutput] = None,
    ) -> ExtractionOutput:
        out = ExtractionOutput()
        index = ctx.index_of(episode)
        table = episode.table or {}
        header = [str(h) for h in table.get("header", [])]
        rows = table.get("rows", [])
        if not header:
            out.diagnostics.append(
                Diagnostic(
                    "TABLE_WITHOUT_HEADER", self.info.step, episode.episode_id,
                    "sin encabezado no se sabe que afirma cada columna",
                )
            )
            return out
        subject_col = _subject_column(header)
        profile_predicates = ctx.profile_predicates()
        mapped = {i: _column_rule(h) for i, h in enumerate(header) if i != subject_col}
        for i, rule in mapped.items():
            if rule is None:
                out.diagnostics.append(
                    Diagnostic(
                        "TABLE_COLUMN_NOT_MAPPED", self.info.step, episode.episode_id,
                        f"columna {header[i]!r} sin predicado conocido",
                    )
                )
        cache: dict = {}
        for row_i, row in enumerate(rows):
            if subject_col >= len(row) or not str(row[subject_col] or "").strip():
                continue
            subject_cell = str(row[subject_col]).strip()
            subject_id = self._mention_for(
                ctx, episode, index, out, cache, row_i, subject_cell, header[subject_col]
            )
            if subject_id is None:
                continue
            for col_i, rule in mapped.items():
                if rule is None or col_i >= len(row):
                    continue
                cell = str(row[col_i] or "").strip()
                if not cell:
                    continue
                frag_hint = index.fragment_ids[min(row_i, len(index.fragment_ids) - 1):][:1]
                if _MULTIVALUE_RE.search(cell):
                    if self.emit_abstentions:
                        emit(
                            abstention_claim(
                                info=self.info,
                                episode=episode,
                                evidence_fragment_ids=frag_hint,
                                reason_codes=["TABLE_MULTIVALUE_CELL"],
                                relation_phrase=header[col_i],
                                subject_mentions=[subject_id],
                                metadata={"table_row": row_i, "raw_cell": cell[:512]},
                            ),
                            out, self.info, episode.episode_id,
                        )
                    else:
                        out.diagnostics.append(
                            Diagnostic(
                                "TABLE_MULTIVALUE_CELL", self.info.step, episode.episode_id,
                                cell[:120],
                            )
                        )
                    continue
                object_id = self._mention_for(
                    ctx, episode, index, out, cache, row_i, cell, header[col_i]
                )
                if object_id is None or object_id == subject_id:
                    continue
                # Tipos CONFIRMADOS por el lexico (nunca los esperados por la
                # columna) y contraste con el dominio/rango del perfil.
                subject_type = _confirmed_type(ctx, subject_cell)
                object_type = _confirmed_type(ctx, cell)
                reasons: list[str] = []
                if profile_predicates and rule.predicate not in profile_predicates:
                    reasons.append("PREDICATE_NOT_IN_PROFILE")
                if (
                    rule.expected_object_type
                    and object_type
                    and object_type != rule.expected_object_type
                ):
                    # La columna esperaba un tipo y el lexico dice otro: la
                    # tabla no dice lo que el encabezado promete.
                    reasons.append("OBJECT_TYPE_MISMATCH")
                if ctx.profile is not None and rule.predicate in profile_predicates:
                    if subject_type and object_type:
                        if not ctx.profile.allows(rule.predicate, subject_type, object_type):
                            reasons.append("TYPE_INCOMPATIBLE_WITH_PROFILE")
                    else:
                        # Con perfil cargado, un claim cuyos tipos no se pueden
                        # confirmar NO se puede validar contra dominio/rango.
                        # Antes salia afirmado con un tipo inventado por la
                        # columna, que es la peor de las dos opciones.
                        reasons.append("TYPES_NOT_CONFIRMABLE")
                if reasons:
                    if self.emit_abstentions:
                        emit(
                            abstention_claim(
                                info=self.info,
                                episode=episode,
                                evidence_fragment_ids=frag_hint,
                                reason_codes=reasons,
                                relation_phrase=header[col_i],
                                subject_mentions=[subject_id],
                                object_mentions=[object_id],
                                metadata={"table_row": row_i},
                            ),
                            out, self.info, episode.episode_id,
                        )
                    continue
                confidence = clamp(TABLE_BASE_CONFIDENCE * float(episode.quality.get("score", 1.0)))
                claim = build_claim(
                    info=self.info,
                    episode=episode,
                    evidence_fragment_ids=frag_hint,
                    subject_mentions=[subject_id],
                    object_mentions=[object_id],
                    relation_phrase=header[col_i],
                    predicate_candidates=[{"predicate": rule.predicate, "confidence": confidence}],
                    direction_candidates=[{"direction": rule.direction, "confidence": confidence}],
                    epistemic_status_hint="ASSERTED",  # sin perfil: ver review_required
                    confidence=confidence,
                    abstained=False,
                    # Sin tipos confirmados no hay forma de comprobar el
                    # dominio/rango: el claim sale, pero pidiendo revision.
                    review_required=bool(
                        low_quality(episode)
                        or confidence < 0.6
                        or not (subject_type and object_type)
                    ),
                    metadata={
                        "table_row": row_i,
                        "table_column": header[col_i],
                        "structured_source": True,
                        "subject_type_confirmed": subject_type,
                        "object_type_confirmed": object_type,
                    },
                )
                emit(claim, out, self.info, episode.episode_id)
        return out


__all__ = [
    "COLUMN_RULES",
    "SUBJECT_HEADERS",
    "TABLE_BASE_CONFIDENCE",
    "TABLE_INFO",
    "TABLE_STEP",
    "ColumnRule",
    "TableExtractor",
]
