# -*- coding: utf-8 -*-
"""Lectura de las decisiones HUMANAS de revision, desde su UNICA autoridad.

EL HUECO QUE ESTE MODULO CIERRA
-------------------------------
Hasta aqui el lazo de revision V3 era de un solo sentido::

    motor --export_review_package--> proposals/ --> visor --> decision humana
                                                                    |
                                            nada la leia de vuelta <-+

El operador pulsaba "Aprobar", el visor la guardaba de verdad, la pantalla
confirmaba, y el motor **seguia proponiendo exactamente la misma reclamacion
para siempre**. Era un falso exito de producto: la decision existia y no
cambiaba nada.

LA AUTORIDAD, Y POR QUE ES ESTA
-------------------------------
La autoridad de una decision humana sobre una propuesta V3 es la tabla
``human_decisions`` del almacen SQLite del visor. No es una eleccion de gusto:

  * El motor **no tenia almacen propio** para esta decision. ``decisiones.json``
    (``pipeline/entity_decisions.py``) son decisiones de IDENTIDAD de entidad,
    otro objeto; ``output/reviews/<ws>/<src>/approved_payload.json`` es la
    salida del auto-decisor v2, una decision de MAQUINA. Ninguno de los dos
    expresa "un humano aprobo esta propuesta".
  * Dentro del visor la autoridad YA estaba declarada y es unica: la cola
    (``ReviewService.queue``) filtra por ``_active_decisions`` leido de SQLite,
    y ``decisions.jsonl`` esta degradado en el propio codigo a exportacion de
    auditoria ("JSONL remains a compatibility/audit export, never the
    authority").

Por eso el motor se convierte en LECTOR de esa autoridad. No se crea almacen
nuevo, no se sincroniza nada y no se copia ninguna decision de un fichero a
otro.

LO QUE ESTE MODULO NO HACE — Y ES DELIBERADO
--------------------------------------------
**NO lee ``decisions.jsonl``.** Leerlo "por compatibilidad" crearia una segunda
autoridad capaz de contradecir a la primera, que es justo el defecto que este
carril cierra. Tampoco escribe: aqui no se persiste ni se corrige nada. Y no
importa el visor (``app.services.*``): motor y visor publican dos paquetes
``app`` distintos, asi que el unico acoplamiento admisible es el fichero.

SEMANTICA DE "DECISION ACTIVA"
------------------------------
Es la del contrato del visor, sin inventar ninguna variante:

  * la ultima decision por ``proposal_id`` gana;
  * una decision **supersedida** por otra (``supersedes_decision_id``) no
    cuenta;
  * una decision de ``undo`` (``correction.undo``) devuelve la propuesta a
    PENDIENTE: no es una decision activa.

``undo`` entra aqui porque es el MISMO modelo de decision (``record()`` con
``supersedes_decision_id``), no una funcionalidad aparte: leer las activas sin
respetarlo haria que deshacer no deshiciera nada para el motor.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

#: Decisiones humanas que RESUELVEN una propuesta: el motor deja de pedirla.
#: ``CORRECT`` no aparece: una correccion sigue siendo material de revision, y
#: ademas es el vehiculo de ``undo``.
RESOLVING_DECISIONS = frozenset({"APPROVE", "REJECT"})

#: Nombre del fichero de auditoria que este modulo NO lee, declarado para que
#: la prohibicion sea comprobable por enumeracion y no una promesa en prosa.
NON_AUTHORITATIVE_EXPORT = "decisions.jsonl"


class ReviewDecisionsError(RuntimeError):
    """El almacen autoritativo existe pero no se puede leer.

    FALLA CERRADO a proposito: si no se puede saber que decidio el humano, el
    motor NO puede seguir como si nadie hubiera decidido nada. Un almacen
    ilegible no es un almacen vacio.
    """


@dataclass(frozen=True)
class HumanDecision:
    """Una decision humana activa sobre una propuesta."""

    proposal_id: str
    workspace: str
    decision_id: str
    human_decision: str
    reviewer: str
    timestamp: str
    rationale: str = ""

    @property
    def resolves(self) -> bool:
        return self.human_decision in RESOLVING_DECISIONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "workspace": self.workspace,
            "decision_id": self.decision_id,
            "human_decision": self.human_decision,
            "reviewer": self.reviewer,
            "timestamp": self.timestamp,
            "rationale": self.rationale,
        }


def default_decisions_db() -> Optional[Path]:
    """El MISMO contrato de ruta que usa el visor. Un solo camino de lectura.

    Se respeta el orden de precedencia del visor
    (``app/services/v3_review.py``): variable explicita de la base, si no la
    carpeta que declare ``S9K_V3_REVIEW_DECISIONS_PATH``, si no la ubicacion
    por defecto del repositorio. Devuelve ``None`` cuando no hay visor montado.
    """
    configured = os.environ.get("S9K_V3_REVIEW_DATABASE_PATH")
    if configured:
        return Path(configured)
    decisions = os.environ.get("S9K_V3_REVIEW_DECISIONS_PATH")
    if decisions:
        return Path(decisions).with_name("review.sqlite3")
    guess = (
        Path(__file__).resolve().parents[3]
        / "viewer" / "output" / "reviews-v3" / "review.sqlite3"
    )
    return guess if guess.exists() else None


def _records(db_path: Path) -> list[dict[str, Any]]:
    """Las decisiones crudas, en el orden en que el visor las escribio."""
    uri = f"file:{db_path}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:  # almacen presente pero inabordable
        raise ReviewDecisionsError(
            "no se pudo abrir el almacen autoritativo de decisiones"
        ) from exc
    try:
        rows = connection.execute(
            "SELECT record_json FROM human_decisions ORDER BY created_at, decision_id"
        ).fetchall()
    except sqlite3.Error as exc:
        raise ReviewDecisionsError(
            "el almacen autoritativo de decisiones no tiene la forma esperada"
        ) from exc
    finally:
        connection.close()
    out: list[dict[str, Any]] = []
    for (blob,) in rows:
        try:
            record = json.loads(blob)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReviewDecisionsError(
                "una decision del almacen autoritativo no es JSON valido"
            ) from exc
        if isinstance(record, dict):
            out.append(record)
    return out


def _proposal_id_of(record: Mapping[str, Any]) -> str:
    proposal = record.get("proposal")
    if isinstance(proposal, Mapping):
        identifier = proposal.get("proposal_id")
        if identifier:
            return str(identifier)
    return str(record.get("proposal_id") or "")


def active_decisions(records: Iterable[Mapping[str, Any]]) -> dict[str, HumanDecision]:
    """`proposal_id -> decision activa`, con la semantica del contrato del visor."""
    latest: dict[str, Mapping[str, Any]] = {}
    superseded: set[str] = set()
    for record in records:
        supersedes = record.get("supersedes_decision_id")
        if supersedes:
            superseded.add(str(supersedes))
        identifier = _proposal_id_of(record)
        if identifier:
            latest[identifier] = record
    active: dict[str, HumanDecision] = {}
    for identifier, record in latest.items():
        if str(record.get("decision_id") or "") in superseded:
            continue
        correction = record.get("correction") or {}
        if isinstance(correction, Mapping) and correction.get("undo"):
            # Deshacer devuelve la propuesta a PENDIENTE para el motor tambien.
            continue
        active[identifier] = HumanDecision(
            proposal_id=identifier,
            workspace=str(record.get("workspace") or ""),
            decision_id=str(record.get("decision_id") or ""),
            human_decision=str(record.get("human_decision") or ""),
            reviewer=str(record.get("reviewer") or ""),
            timestamp=str(record.get("timestamp") or ""),
            rationale=str(record.get("rationale") or ""),
        )
    return active


def read_active_decisions(
    db_path: "Path | None" = None,
    *,
    workspace: str | None = None,
) -> dict[str, HumanDecision]:
    """Las decisiones humanas activas. EL UNICO camino de lectura del motor.

    Sin almacen no hay decisiones: se devuelve vacio y el motor se comporta
    como siempre. Con almacen ilegible se levanta ``ReviewDecisionsError``: eso
    es un fallo, no un silencio.
    """
    path = db_path if db_path is not None else default_decisions_db()
    if path is None or not Path(path).exists():
        return {}
    active = active_decisions(_records(Path(path)))
    if workspace is None:
        return active
    return {
        identifier: decision
        for identifier, decision in active.items()
        if decision.workspace == workspace
    }


def resolved_proposal_ids(
    db_path: "Path | None" = None,
    *,
    workspace: str | None = None,
) -> dict[str, HumanDecision]:
    """Solo las que RESUELVEN (``APPROVE``/``REJECT``)."""
    return {
        identifier: decision
        for identifier, decision in read_active_decisions(db_path, workspace=workspace).items()
        if decision.resolves
    }


__all__ = [
    "RESOLVING_DECISIONS",
    "NON_AUTHORITATIVE_EXPORT",
    "ReviewDecisionsError",
    "HumanDecision",
    "default_decisions_db",
    "active_decisions",
    "read_active_decisions",
    "resolved_proposal_ids",
]
