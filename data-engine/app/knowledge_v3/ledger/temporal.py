# -*- coding: utf-8 -*-
"""Consultas bitemporales: los dos ejes de tiempo, separados.

- **Tiempo de transaccion** (`recorded_at`): cuando el SISTEMA supo algo.
  `LedgerView.as_of(T)` responde «que sabia el sistema el dia T».
- **Tiempo de validez** (`valid_from`/`valid_to`): cuando el hecho era cierto en
  el MUNDO. `valid_at(t)` responde «que era cierto el dia t».
- **Tiempo del evento** (`event_time`): cuando ocurrio el hecho narrado. Es un
  tercer dato, no un sinonimo del anterior: un juramento ocurre en un instante
  (`event_time`) y su efecto dura anos (`valid_from`..`valid_to`).

Los dos primeros ejes son ortogonales y se combinan: `valid_at(t, as_of=T)`
responde «que creia el sistema el dia T sobre lo que era cierto el dia t». Ese
cruce es lo que permite reconstruir una decision pasada sin que el conocimiento
posterior la contamine.

Nada de este modulo escribe ni consulta un reloj: una vista es una funcion pura
de las entradas del ledger.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .entries import LedgerEntry
from .supersession import chain_from, is_live
from .timeline import in_validity_interval, time_key


@dataclass(frozen=True)
class AssertionVersion:
    """Revision materializada de una afirmacion en un punto del ledger."""

    assertion_id: str
    revision: int
    document: dict
    entry_seq: int
    recorded_at: str
    operation: str

    @property
    def status(self) -> str:
        return str(self.document["status"])

    @property
    def is_live(self) -> bool:
        return is_live(self.status)


class LedgerView:
    """Estado materializado del ledger hasta un instante de transaccion.

    Se construye plegando las entradas en orden de `seq` y quedandose con la
    ULTIMA revision de cada `assertion_id`. Las revisiones anteriores no
    desaparecen: siguen en el ledger, y `history()` las devuelve.
    """

    def __init__(self, entries: Iterable[LedgerEntry], *, as_of: Optional[str] = None) -> None:
        self.as_of = as_of
        self._entries: List[LedgerEntry] = list(entries)
        self._records: Dict[str, AssertionVersion] = {}
        for entry in self._entries:
            self._records[entry.assertion_id] = AssertionVersion(
                assertion_id=entry.assertion_id,
                revision=entry.revision,
                document=deepcopy(entry.assertion),
                entry_seq=entry.seq,
                recorded_at=entry.recorded_at,
                operation=entry.operation,
            )

    # -- Acceso basico -----------------------------------------------------
    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, assertion_id: object) -> bool:
        return assertion_id in self._records

    @property
    def entries(self) -> Tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def get(self, assertion_id: str) -> Optional[AssertionVersion]:
        return self._records.get(assertion_id)

    def document(self, assertion_id: str) -> dict:
        rec = self._records.get(assertion_id)
        if rec is None:
            raise KeyError(f"afirmacion desconocida en esta vista: {assertion_id}")
        return deepcopy(rec.document)

    def records(self) -> List[AssertionVersion]:
        """Todas las afirmaciones materializadas, en orden de `assertion_id`."""
        return [self._records[k] for k in sorted(self._records)]

    def live(self) -> List[AssertionVersion]:
        """Afirmaciones vigentes: ni SUPERSEDED ni RETRACTED.

        `CONTRADICTED` SI aparece: una contradiccion sin resolver es
        conocimiento que el motor debe ver, no un hecho borrado.
        """
        return [r for r in self.records() if r.is_live]

    def conflicted(self) -> List[AssertionVersion]:
        return [r for r in self.records() if r.document["status"] == "CONTRADICTED"]

    def history(self, assertion_id: str) -> List[AssertionVersion]:
        """Todas las revisiones de una afirmacion, de la 1 a la actual."""
        return [
            AssertionVersion(
                assertion_id=e.assertion_id,
                revision=e.revision,
                document=deepcopy(e.assertion),
                entry_seq=e.seq,
                recorded_at=e.recorded_at,
                operation=e.operation,
            )
            for e in self._entries
            if e.assertion_id == assertion_id
        ]

    def supersession_chain(self, assertion_id: str) -> List[str]:
        """Cadena de custodia hacia adelante: version original -> ... -> vigente."""
        return chain_from({k: v.document for k, v in self._records.items()}, assertion_id)

    # -- Eje de tiempo de validez -----------------------------------------
    def valid_at(
        self,
        world_time: str,
        *,
        include_unknown_start: bool = False,
        include_non_live: bool = False,
    ) -> List[AssertionVersion]:
        """Que era cierto en el MUNDO en `world_time`, segun esta vista.

        Intervalo semiabierto `[valid_from, valid_to)`. Por defecto solo
        afirmaciones vigentes en el ledger; `include_non_live=True` incluye las
        superadas y retractadas, que es justo lo que hace falta para auditar por
        que se creyo algo.
        """
        pool = self.records() if include_non_live else self.live()
        return [
            r
            for r in pool
            if in_validity_interval(
                world_time,
                r.document.get("valid_from"),
                r.document.get("valid_to"),
                include_unknown_start=include_unknown_start,
            )
        ]

    def by_event_time(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        *,
        include_non_live: bool = False,
    ) -> List[AssertionVersion]:
        """Hechos cuyo `event_time` cae en `[start, end]` (limites inclusivos).

        Ventana CERRADA, al reves que la de vigencia: aqui se pregunta por
        eventos puntuales, y excluir el extremo dejaria fuera precisamente el
        evento que ocurre en la fecha buscada.
        """
        pool = self.records() if include_non_live else self.live()
        out = []
        for r in pool:
            et = r.document.get("event_time")
            if et is None:
                continue
            k = time_key(et)
            if start is not None and k < time_key(start):
                continue
            if end is not None and k > time_key(end):
                continue
            out.append(r)
        return out


__all__ = ["AssertionVersion", "LedgerView"]
