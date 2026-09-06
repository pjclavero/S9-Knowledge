# -*- coding: utf-8 -*-
"""Reversion de la PROCEDENCIA, con recuento de referencias vivas.

POR QUE EXISTE
--------------
El rollback sabia deshacer conocimiento (`V3Entity`, `V3Assertion` y sus
aristas) y no sabia que existiese la procedencia (`V3Source`, `V3Episode`,
`V3Evidence` y las cinco aristas de `provenance.py`). Resultado medido: tras
revertir un apply quedaban nodos de procedencia sin nada que apuntase a ellos
--con el texto literal de la fuente dentro-- y el documento afirmaba
`"unrecoverable": []`. Eso no es una carencia declarada: es evidencia falsa.

LAS DOS DIRECCIONES, QUE SON UNA SOLA REGLA
-------------------------------------------
Borrar la procedencia huerfana y conservar la compartida no son dos criterios:
son el mismo, **cero referencias vivas**, mirado desde los dos lados.

* Una `V3Evidence` se borra si, DESPUES de borrar la asercion revertida, no
  queda ninguna `(:V3Assertion)-[:SUPPORTED_BY]->` apuntandola.
* Si otra asercion viva sigue apuntandola, NO se borra --y se dice, porque es
  algo que ese apply creo y que este rollback no revierte.
* Igual hacia arriba: un `V3Episode` se borra si no le queda ningun
  `HAS_FRAGMENT`, y un `V3Source` si no le queda ningun `HAS_EPISODE`. Solo se
  consideran los ANTEPASADOS de los fragmentos purgados, leidos por el camino
  antes de borrar nada: un episodio ajeno no entra en la lista siquiera.

Por eso el orden importa y esta fijado: aristas y nodo de la asercion primero,
censo de antepasados ANTES de borrar (despues las aristas ya no estan) y la
cascada evidencia -> episodio -> fuente al final.

IDENTIDAD
---------
`(workspace, fragment_id)`, `(workspace, episode_id)` y
`(workspace, source_asset_id)`. Ni una sola consulta de este modulo menciona
`elementId`.

QUE NO ES ESTE MODULO
---------------------
No es un gate: no impide ninguna escritura. Mide DESPUES y hace que el
resultado diga la verdad.

FRONTERA CON EL BLOQUE DE AISLAMIENTO POR AMBITO
------------------------------------------------
El filtro de ambito de estas consultas es DELIBERADAMENTE estrecho y
fail-closed (`partida_id IS NULL` si el plan no declara partida; igualdad
exacta si la declara), de modo que nunca alcance otra partida. Desde la
integracion de la tanda 3 NO se define aqui: se llama a
`rollback.scope_clause`, que es la UNICA definicion del filtro en todo el
camino de recuperacion. La generacion
de Cypher de las consultas de borrado del conocimiento
(`rollback.rollback_query`) NO se toca aqui: `rollback_query_for` se limita a
encaminar las acciones nuevas y a delegar en ella todo lo demas.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from . import codes
from .cypher import LABEL_APPLIED_OPERATION, LABEL_ASSERTION
from .provenance import (
    IDENTITY_FIELD,
    LABEL_EPISODE,
    LABEL_EVIDENCE,
    LABEL_SOURCE,
    REL_HAS_EPISODE,
    REL_HAS_FRAGMENT,
    REL_SUPPORTED_BY,
)
from .rollback import (
    ACTION_FORGET_APPLIED,
    ACTION_PURGE_PROVENANCE,
    RollbackDocument,
    RollbackInstruction,
    RollbackNotReconstructible,
    SWEEP_OPERATION_ID,
    RollbackQuery,
    rollback_query,
    scope_clause,
)

#: Acciones que encamina este modulo. El resto va a `rollback.rollback_query`.
OWN_ACTIONS = (ACTION_PURGE_PROVENANCE, ACTION_FORGET_APPLIED)


# INTEGRACION tanda 3: el filtro de ambito del camino de recuperacion tiene UNA
# sola definicion, y vive en `rollback.scope_clause`. Este modulo tenia la suya
# (`_scope`), que decia lo mismo con otras palabras y otro nombre de parametro.
# Dos definiciones que deben coincidir sin nada que lo verifique acaban
# divergiendo, y la que diverge borra de mas. La de `rollback` cubre ademas un
# caso que esta no cubria: valida el ambito malformado (cadena vacia, tipo raro)
# en vez de dejarlo pasar como si fuese una partida. Los cuatro puntos de uso
# llaman ya directamente a `scope_clause`; no queda alias.


# --- Consultas -------------------------------------------------------------
def ancestors_query(
    workspace: str, fragment_ids: list[str], partida_id: Optional[str]
) -> RollbackQuery:
    """Antepasados de los fragmentos, POR EL CAMINO y en una sola consulta.

    Un `MATCH` suelto por etiqueta daria producto cartesiano (o cero filas) y
    pareceria medir. Aqui cada fila recorre `evidencia <- episodio <- fuente`
    encadenado, de modo que un episodio que no sostenga a ninguno de estos
    fragmentos no aparece.
    """
    params: dict[str, Any] = {"ws": workspace, "fragments": list(fragment_ids)}
    cond = scope_clause("ev", partida_id, params)
    return RollbackQuery(
        "UNWIND $fragments AS fid "
        f"MATCH (ev:{LABEL_EVIDENCE} {{fragment_id: fid, workspace: $ws}}) "
        f"WHERE {cond} "
        f"OPTIONAL MATCH (ep:{LABEL_EPISODE})-[:{REL_HAS_FRAGMENT}]->(ev) "
        f"OPTIONAL MATCH (src:{LABEL_SOURCE})-[:{REL_HAS_EPISODE}]->(ep) "
        "RETURN DISTINCT ev.fragment_id AS fragment_id, "
        "ep.episode_id AS episode_id, src.source_asset_id AS source_asset_id",
        params,
    )


def live_references_query(
    workspace: str, fragment_ids: list[str], partida_id: Optional[str]
) -> RollbackQuery:
    """Cuantas aserciones VIVAS sostiene cada fragmento, y cuales."""
    params: dict[str, Any] = {"ws": workspace, "fragments": list(fragment_ids)}
    cond = scope_clause("ev", partida_id, params)
    return RollbackQuery(
        "UNWIND $fragments AS fid "
        f"MATCH (ev:{LABEL_EVIDENCE} {{fragment_id: fid, workspace: $ws}}) "
        f"WHERE {cond} "
        f"OPTIONAL MATCH (a:{LABEL_ASSERTION})-[:{REL_SUPPORTED_BY}]->(ev) "
        "RETURN ev.fragment_id AS fragment_id, count(a) AS vivas, "
        "collect(a.assertion_id) AS referrers",
        params,
    )


def _delete_if_unreferenced(
    label: str,
    ids: list[str],
    workspace: str,
    partida_id: Optional[str],
    guard: str,
) -> RollbackQuery:
    field_name = IDENTITY_FIELD[label]
    params: dict[str, Any] = {"ws": workspace, "ids": list(ids)}
    cond = scope_clause("n", partida_id, params)
    return RollbackQuery(
        "UNWIND $ids AS wanted "
        f"MATCH (n:{label} {{{field_name}: wanted, workspace: $ws}}) "
        f"WHERE {cond} AND NOT {guard} "
        "DETACH DELETE n RETURN count(n) AS borrados",
        params,
    )


def delete_orphan_evidence_query(
    workspace: str, fragment_ids: list[str], partida_id: Optional[str]
) -> RollbackQuery:
    """Solo la evidencia SIN ninguna asercion viva detras."""
    return _delete_if_unreferenced(
        LABEL_EVIDENCE,
        fragment_ids,
        workspace,
        partida_id,
        f"EXISTS {{ MATCH (:{LABEL_ASSERTION})-[:{REL_SUPPORTED_BY}]->(n) }}",
    )


def delete_orphan_episode_query(
    workspace: str, episode_ids: list[str], partida_id: Optional[str]
) -> RollbackQuery:
    return _delete_if_unreferenced(
        LABEL_EPISODE,
        episode_ids,
        workspace,
        partida_id,
        f"EXISTS {{ MATCH (n)-[:{REL_HAS_FRAGMENT}]->(:{LABEL_EVIDENCE}) }}",
    )


def delete_orphan_source_query(
    workspace: str, source_ids: list[str], partida_id: Optional[str]
) -> RollbackQuery:
    return _delete_if_unreferenced(
        LABEL_SOURCE,
        source_ids,
        workspace,
        partida_id,
        f"EXISTS {{ MATCH (n)-[:{REL_HAS_EPISODE}]->(:{LABEL_EPISODE}) }}",
    )


def orphan_provenance_query(
    workspace: str, partida_id: Optional[str]
) -> RollbackQuery:
    """Procedencia HUERFANA en un ambito, la nombre el documento o no.

    POR QUE NO BASTA CON MIRAR LO QUE EL DOCUMENTO NOMBRA (defecto medido)
    ---------------------------------------------------------------------
    `residues` solo buscaba evidencia huerfana entre los `fragment_ids` que
    alguna instruccion `PURGE_PROVENANCE` citaba. Medido: ejecutando un
    documento al que le faltaba el barrido de procedencia quedaron evidencias y
    episodios huerfanos en el grafo Y el mando salio con
    `ROLLED_BACK` / rc=0 -- es decir, el desenlace limpio era una frase que el
    grafo desmentia. Lo que un documento NO nombra es justo lo que hay que
    poder ver.

    Tres ramas en `UNION ALL`, no tres patrones en la misma consulta: dos
    `MATCH` sueltos darian producto cartesiano y, con cualquiera de los tres
    conjuntos vacio, CERO filas -- un verde que no mide nada.

    Esto NO es una capa de proteccion: no impide ningun borrado. Es
    OBSERVACION, y es la unica de las tres que puede ver lo que el documento no
    menciona. La conservacion de lo compartido la siguen sosteniendo el censo y
    la guarda del propio `DELETE`, que no se tocan.
    """
    params: dict[str, Any] = {"ws": workspace}
    ev = scope_clause("ev", partida_id, params)
    ep = scope_clause("ep", partida_id, params)
    src = scope_clause("src", partida_id, params)
    return RollbackQuery(
        f"MATCH (ev:{LABEL_EVIDENCE} {{workspace: $ws}}) WHERE {ev} "
        f"OPTIONAL MATCH (:{LABEL_ASSERTION})-[sup:{REL_SUPPORTED_BY}]->(ev) "
        "WITH ev, count(sup) AS vivas WHERE vivas = 0 "
        f"RETURN '{LABEL_EVIDENCE}' AS clase, ev.fragment_id AS id "
        "UNION ALL "
        f"MATCH (ep:{LABEL_EPISODE} {{workspace: $ws}}) WHERE {ep} "
        f"OPTIONAL MATCH (ep)-[frg:{REL_HAS_FRAGMENT}]->(:{LABEL_EVIDENCE}) "
        "WITH ep, count(frg) AS vivas WHERE vivas = 0 "
        f"RETURN '{LABEL_EPISODE}' AS clase, ep.episode_id AS id "
        "UNION ALL "
        f"MATCH (src:{LABEL_SOURCE} {{workspace: $ws}}) WHERE {src} "
        f"OPTIONAL MATCH (src)-[epi:{REL_HAS_EPISODE}]->(:{LABEL_EPISODE}) "
        "WITH src, count(epi) AS vivas WHERE vivas = 0 "
        f"RETURN '{LABEL_SOURCE}' AS clase, src.source_asset_id AS id",
        params,
    )


def forget_applied_query(workspace: str, idempotency_key: str) -> RollbackQuery:
    """Retira la marca autoritativa de idempotencia de UNA operacion."""
    return RollbackQuery(
        f"MATCH (op:{LABEL_APPLIED_OPERATION} "
        "{workspace: $ws, idempotency_key: $key}) "
        "DELETE op RETURN count(op) AS borrados",
        {"ws": workspace, "key": idempotency_key},
    )


def key_evidence_query(workspace: str, idempotency_key: str) -> RollbackQuery:
    """Que queda en el grafo con esa `idempotency_key`: nodos, aristas y marca.

    Dos patrones en la MISMA consulta darian producto cartesiano, asi que van
    en ramas de un `UNION ALL` y cada una cuenta lo suyo.
    """
    return RollbackQuery(
        "MATCH (n {workspace: $ws, idempotency_key: $key}) "
        f"WHERE NOT n:{LABEL_APPLIED_OPERATION} "
        "RETURN 'nodo' AS clase, count(n) AS cuantos "
        "UNION ALL "
        "MATCH ()-[r {workspace: $ws, idempotency_key: $key}]->() "
        "RETURN 'arista' AS clase, count(r) AS cuantos "
        "UNION ALL "
        f"MATCH (op:{LABEL_APPLIED_OPERATION} "
        "{workspace: $ws, idempotency_key: $key}) "
        "RETURN 'marca' AS clase, count(op) AS cuantos",
        {"ws": workspace, "key": idempotency_key},
    )


def rollback_query_for(instruction: RollbackInstruction) -> RollbackQuery:
    """Encaminador. Delega en `rollback.rollback_query` todo lo que no es suyo.

    `PURGE_PROVENANCE` NO se traduce a una consulta unica: es una secuencia con
    censo intermedio (hay que leer los antepasados antes de borrar y contar las
    referencias vivas despues). Se ejecuta con `execute_purge`.
    """
    if instruction.action == ACTION_FORGET_APPLIED:
        detail = dict(instruction.detail)
        ws = detail.get("workspace")
        key = detail.get("idempotency_key") or instruction.target_id
        if not ws or not key:
            raise RollbackNotReconstructible(
                f"{instruction.operation_id}: {ACTION_FORGET_APPLIED} sin "
                "workspace o idempotency_key"
            )
        return forget_applied_query(ws, key)
    if instruction.action == ACTION_PURGE_PROVENANCE:
        raise RollbackNotReconstructible(
            f"{instruction.operation_id}: {ACTION_PURGE_PROVENANCE} es una "
            "secuencia con censo intermedio, no una consulta: usa execute_purge"
        )
    return rollback_query(instruction)


# --- Ejecucion -------------------------------------------------------------
def _rows(runner: Any, query: RollbackQuery) -> list[dict[str, Any]]:
    return [dict(r) for r in runner.run(query.cypher, query.params)]


def _existing(
    runner: Any, label: str, ids: list[str], workspace: str, partida_id: Optional[str]
) -> set[str]:
    """Que sigue EXISTIENDO de esa lista. Se mide, no se presume."""
    field_name = IDENTITY_FIELD[label]
    params: dict[str, Any] = {"ws": workspace, "ids": list(ids)}
    cond = scope_clause("n", partida_id, params)
    filas = _rows(
        runner,
        RollbackQuery(
            "UNWIND $ids AS wanted "
            f"MATCH (n:{label} {{{field_name}: wanted, workspace: $ws}}) "
            f"WHERE {cond} RETURN n.{field_name} AS id",
            params,
        ),
    )
    return {f["id"] for f in filas if f.get("id")}


@dataclass
class PurgeReport:
    """Lo que la purga hizo DE VERDAD, separado de lo que decidio no hacer."""

    deleted_evidence: list[str] = field(default_factory=list)
    deleted_episodes: list[str] = field(default_factory=list)
    deleted_sources: list[str] = field(default_factory=list)
    #: fragment_id -> aserciones vivas que lo sostienen. NO se borro por esto.
    retained_evidence: dict[str, list[str]] = field(default_factory=dict)
    #: episodios/fuentes conservados porque aun cuelga algo de ellos.
    retained_ancestors: dict[str, list[str]] = field(default_factory=dict)
    #: fragmentos que la instruccion nombraba y que ya no estaban en el grafo.
    absent: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deleted_evidence": list(self.deleted_evidence),
            "deleted_episodes": list(self.deleted_episodes),
            "deleted_sources": list(self.deleted_sources),
            "retained_evidence": {k: list(v) for k, v in self.retained_evidence.items()},
            "retained_ancestors": {k: list(v) for k, v in self.retained_ancestors.items()},
            "absent": list(self.absent),
        }


def execute_purge(runner: Any, instruction: RollbackInstruction) -> PurgeReport:
    """La secuencia completa de una instruccion `PURGE_PROVENANCE`.

    `runner` es cualquier cosa con `.run(cypher, params)`: una sesion o una
    transaccion. Este modulo no importa `neo4j` ni abre conexiones.
    """
    detail = dict(instruction.detail)
    ws = detail.get("workspace")
    fragments = [f for f in (detail.get("fragment_ids") or []) if f]
    partida = detail.get("partida_id")
    if not ws:
        raise RollbackNotReconstructible(
            f"{instruction.operation_id}: purga sin workspace"
        )
    report = PurgeReport()
    if not fragments:
        return report

    # 1. Antepasados ANTES de borrar: despues, las aristas ya no existen.
    ancestros = _rows(runner, ancestors_query(ws, fragments, partida))
    presentes = {r["fragment_id"] for r in ancestros if r.get("fragment_id")}
    report.absent = sorted(set(fragments) - presentes)
    episodios = sorted({r["episode_id"] for r in ancestros if r.get("episode_id")})
    fuentes = sorted({r["source_asset_id"] for r in ancestros if r.get("source_asset_id")})

    # 2. Censo de referencias vivas: quien se queda, y por que.
    huerfanos: list[str] = []
    for fila in _rows(runner, live_references_query(ws, fragments, partida)):
        fid = fila["fragment_id"]
        referrers = sorted({a for a in (fila.get("referrers") or []) if a})
        if int(fila.get("vivas") or 0) > 0:
            report.retained_evidence[fid] = referrers
        else:
            huerfanos.append(fid)

    # 3. Cascada, de abajo arriba. La condicion de borrado vuelve a comprobar la
    #    ausencia de referencias: el censo informa, pero no decide (entre censo y
    #    borrado el grafo puede cambiar). Y lo borrado se MIDE preguntando que
    #    sigue existiendo, no dando por hecho lo que se pidio.
    if huerfanos:
        _rows(runner, delete_orphan_evidence_query(ws, huerfanos, partida))
        siguen = _existing(runner, LABEL_EVIDENCE, huerfanos, ws, partida)
        report.deleted_evidence = sorted(set(huerfanos) - siguen)
        for fid in sorted(siguen):
            report.retained_evidence.setdefault(fid, [])
    if episodios:
        _rows(runner, delete_orphan_episode_query(ws, episodios, partida))
        siguen = _existing(runner, LABEL_EPISODE, episodios, ws, partida)
        report.deleted_episodes = sorted(set(episodios) - siguen)
        if siguen:
            report.retained_ancestors[LABEL_EPISODE] = sorted(siguen)
    if fuentes:
        _rows(runner, delete_orphan_source_query(ws, fuentes, partida))
        siguen = _existing(runner, LABEL_SOURCE, fuentes, ws, partida)
        report.deleted_sources = sorted(set(fuentes) - siguen)
        if siguen:
            report.retained_ancestors[LABEL_SOURCE] = sorted(siguen)
    return report


@dataclass
class RollbackReport:
    """Desenlace de ejecutar un documento entero, con lo que NO se revirtio."""

    executed: list[dict[str, Any]] = field(default_factory=list)
    purges: list[dict[str, Any]] = field(default_factory=list)
    residues: list[dict[str, Any]] = field(default_factory=list)
    unrecoverable: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.residues

    def to_dict(self) -> dict[str, Any]:
        return {
            "executed": [dict(e) for e in self.executed],
            "purges": [dict(p) for p in self.purges],
            "residues": [dict(r) for r in self.residues],
            "unrecoverable": list(self.unrecoverable),
            "clean": self.clean,
        }


def execute_rollback(
    runner: Any, doc: RollbackDocument, *, annotate: bool = True
) -> RollbackReport:
    """Ejecuta el documento EN ORDEN y devuelve lo que no pudo revertir.

    Con `annotate`, lo no revertido se escribe en `doc.unrecoverable`: el
    documento que un operador lee despues dice la verdad, no `[]`.
    """
    report = RollbackReport()
    for instruction in doc.instructions:
        if instruction.action == ACTION_PURGE_PROVENANCE:
            purga = execute_purge(runner, instruction)
            report.purges.append(
                {"operation_id": instruction.operation_id, **purga.to_dict()}
            )
            for fid, referrers in sorted(purga.retained_evidence.items()):
                report.unrecoverable.append(
                    f"{codes.ROLLBACK_RETAINED_SHARED} {instruction.operation_id}: "
                    f"la evidencia {fid} NO se borro porque la sostienen "
                    f"aserciones vivas {referrers}"
                )
            continue
        try:
            query = rollback_query_for(instruction)
        except RollbackNotReconstructible as exc:
            report.unrecoverable.append(str(exc))
            continue
        filas = _rows(runner, query)
        report.executed.append(
            {
                "operation_id": instruction.operation_id,
                "action": instruction.action,
                "result": filas,
            }
        )

    report.residues = residues(runner, doc)
    for residuo in report.residues:
        report.unrecoverable.append(
            f"{codes.ROLLBACK_RESIDUE} {residuo['operation_id']}: "
            f"{residuo['what']} ({residuo['detail']})"
        )
    if annotate:
        for linea in report.unrecoverable:
            if linea not in doc.unrecoverable:
                doc.unrecoverable.append(linea)
    return report


def residues(runner: Any, doc: RollbackDocument) -> list[dict[str, Any]]:
    """Lo que queda de ESA operacion despues de haberla deshecho.

    Dos familias, medidas por separado:

    * cualquier nodo, arista o marca que aun lleve una `idempotency_key` del
      documento;
    * evidencia que la purga nombraba, sigue en el grafo y NO tiene ninguna
      asercion viva detras: procedencia huerfana, que es exactamente el defecto
      que este bloque cierra.
    """
    fuera: list[dict[str, Any]] = []
    vistas: set[tuple[str, str]] = set()
    ambitos: set[tuple[str, Any]] = set()
    for instruction in doc.instructions:
        detalle = dict(instruction.detail)
        if instruction.action == ACTION_PURGE_PROVENANCE:
            ambitos.add(
                (detalle.get("workspace") or doc.workspace, detalle.get("partida_id"))
            )
        detail = dict(instruction.detail)
        ws = detail.get("workspace") or doc.workspace
        key = detail.get("idempotency_key")
        if key and (ws, key) not in vistas:
            vistas.add((ws, key))
            for fila in _rows(runner, key_evidence_query(ws, key)):
                if int(fila.get("cuantos") or 0) > 0:
                    fuera.append(
                        {
                            "operation_id": instruction.operation_id,
                            "what": f"queda {fila['clase']} con la idempotency_key",
                            "detail": {
                                "idempotency_key": key,
                                "cuantos": fila["cuantos"],
                            },
                        }
                    )
        if instruction.action != ACTION_PURGE_PROVENANCE:
            continue
        fragments = [f for f in (detail.get("fragment_ids") or []) if f]
        if not fragments:
            continue
        for fila in _rows(
            runner, live_references_query(ws, fragments, detail.get("partida_id"))
        ):
            if int(fila.get("vivas") or 0) == 0:
                fuera.append(
                    {
                        "operation_id": instruction.operation_id,
                        "what": "evidencia HUERFANA: sigue en el grafo y ninguna "
                        "asercion viva la sostiene",
                        "detail": {"fragment_id": fila["fragment_id"]},
                    }
                )

    # Barrido por AMBITO: lo que el documento NO nombra. Sin esto, un documento
    # incompleto producia un desenlace limpio sobre un grafo con procedencia
    # huerfana dentro -- medido.
    ya_dicho = {
        (r["what"], json.dumps(r["detail"], sort_keys=True, default=str))
        for r in fuera
    }
    for ws, partida in sorted(ambitos, key=lambda x: (x[0], str(x[1]))):
        try:
            consulta = orphan_provenance_query(ws, partida)
        except RollbackNotReconstructible:
            continue  # ambito malformado: ya se denuncio al intentar ejecutarlo
        for fila in _rows(runner, consulta):
            if not fila.get("id"):
                continue
            que = (
                f"procedencia HUERFANA en el grafo ({fila['clase']}): nada vivo "
                "la sostiene y el documento no la nombraba"
            )
            detalle = {"clase": fila["clase"], "id": fila["id"], "workspace": ws}
            firma = (que, json.dumps(detalle, sort_keys=True, default=str))
            if firma in ya_dicho:
                continue
            ya_dicho.add(firma)
            fuera.append(
                {"operation_id": SWEEP_OPERATION_ID, "what": que, "detail": detalle}
            )
    return fuera


__all__ = [
    "OWN_ACTIONS",
    "PurgeReport",
    "RollbackReport",
    "ancestors_query",
    "delete_orphan_episode_query",
    "delete_orphan_evidence_query",
    "delete_orphan_source_query",
    "execute_purge",
    "execute_rollback",
    "forget_applied_query",
    "key_evidence_query",
    "live_references_query",
    "orphan_provenance_query",
    "residues",
    "rollback_query_for",
]
