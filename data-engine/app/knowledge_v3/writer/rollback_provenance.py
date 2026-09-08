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
from .apply_identity import APPLY_ID_FIELD, is_apply_id
from .ownership_identity import OWNERSHIP_ID_FIELD, is_ownership_id
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


# --- Propiedad del apply ---------------------------------------------------
#: Campo del grafo por el que se filtra segun la clase de marca recibida.
#: La marca DICE de que campo es: los prefijos (`own:` / `apply:`) son
#: disjuntos y las dos formas se validan estrictamente, asi que no hay que
#: adivinar ni pasar un parametro extra por los cuatro puntos de uso.
_CAMPO_DE_MARCA = (
    (is_ownership_id, OWNERSHIP_ID_FIELD, "ownership_id"),
    (is_apply_id, APPLY_ID_FIELD, "apply_id"),
)


def campo_de_marca(marca: str) -> tuple[str, str]:
    """`(campo_del_grafo, nombre_de_parametro)` de una marca de propiedad.

    INTEGRACION tanda 8. Excepcion si la marca no es de ninguna clase
    conocida: filtrar por una marca malformada es peor que no filtrar, porque
    pareceria acotado.
    """
    for reconoce, campo, param in _CAMPO_DE_MARCA:
        if reconoce(marca):
            return campo, param
    raise RollbackNotReconstructible(
        f"marca de propiedad {marca!r} sin forma admisible "
        f"({OWNERSHIP_ID_FIELD} ni {APPLY_ID_FIELD})"
    )


class Propiedad:
    """Las marcas con las que un documento reclama los efectos de SU apply.

    INTEGRACION tanda 8 -- POR QUE SON DOS Y NO UNA
    -----------------------------------------------
    8B dejo declarado que la clasificacion seguia consumiendo `apply_id`, que
    es identidad de INTENTO: deriva de `plan_hash`, que cubre el reloj, asi
    que el mismo apply LOGICO replanificado tras un restore trae otro
    `apply_id` y la clasificacion deja de reconocer lo que ella misma creo.
    Esa es la migracion, y la marca durable es `ownership_id`.

    Pero quedarse SOLO con la durable seria fail-OPEN sobre un grafo escrito
    antes de que existiera: esos nodos llevan `apply_id` y no llevan
    `ownership_id`, asi que un residuo real dejaria de verse y el mando diria
    `clean` de algo que no lo esta. MEDIDO: con el filtro solo por la durable,
    `test_algo_creado_por_X_no_compartido_y_presente_sale_INCOMPLETE` pasa de
    `UNEXPECTED_RESIDUE` a `ROLLED_BACK`.

    Por eso el predicado es la DISYUNCION de las marcas presentes. No amplia
    la propiedad a nada ajeno: `apply_id` deriva del `plan_hash` de ESTE plan,
    de modo que solo lo llevan los nodos que escribio este mismo intento --que
    son, por definicion, del mismo apply logico. Lo que la disyuncion compra
    es que la propiedad se reconozca por CUALQUIERA de las dos marcas:

        misma base, mismo intento -> casan las dos
        base restaurada / replan  -> casa `ownership_id` (`apply_id` no existe alli)
        grafo anterior a 8B       -> casa `apply_id` (no hay `ownership_id`)

    La propiedad sigue solo ESTRECHANDO el conjunto candidato; nunca lo
    amplia mas alla de este apply logico.
    """

    __slots__ = ("marcas",)

    def __init__(self, marcas: tuple[str, ...]):
        self.marcas = marcas

    def __bool__(self) -> bool:
        return bool(self.marcas)

    @property
    def durable(self) -> Optional[str]:
        for m in self.marcas:
            if is_ownership_id(m):
                return m
        return None

    @property
    def principal(self) -> Optional[str]:
        """La marca con la que se ROTULA un informe: la durable si la hay."""
        return self.durable or (self.marcas[0] if self.marcas else None)

    def _pares(self, params: dict[str, Any]) -> list[tuple[str, str]]:
        fuera = []
        for marca in self.marcas:
            campo, param = campo_de_marca(marca)
            params[param] = marca
            fuera.append((campo, param))
        return fuera

    def propio(self, alias: str, params: dict[str, Any]) -> str:
        """«Este nodo es de este apply». `NULL` cuenta como NO propio.

        `coalesce` es lo que hace el predicado seguro con nulos: en Cypher
        `NULL = $x` es `NULL`, y un `NULL` en un `OR` se propaga de formas que
        no se leen a simple vista. Aqui se decide explicitamente: sin marca,
        no es de este apply.
        """
        pares = self._pares(params)
        if not pares:
            return "true"
        return "(" + " OR ".join(
            f"coalesce({alias}.{campo} = ${param}, false)" for campo, param in pares
        ) + ")"

    def ajeno(self, alias: str, params: dict[str, Any]) -> str:
        """«Este vecino NO es de este apply». Marca ausente cuenta como AJENO.

        Es la negacion EXACTA de `propio` sobre el mismo material: si las dos
        se escribieran por separado acabarian divergiendo, y la que divergiese
        haria que un vecino contase a la vez como propio y como ajeno.
        """
        pares = self._pares(params)
        if not pares:
            return "false"
        return "NOT (" + " OR ".join(
            f"coalesce({alias}.{campo} = ${param}, false)" for campo, param in pares
        ) + ")"


def propiedad_de(marca: Any) -> Propiedad:
    """`Propiedad` a partir de lo que reciba un punto de uso.

    Admite `None` (sin propiedad: radio antiguo `run`), una marca suelta --que
    es como llaman los documentos y las pruebas anteriores a esta tanda-- o
    una `Propiedad` ya compuesta.
    """
    if isinstance(marca, Propiedad):
        return marca
    if marca is None:
        return Propiedad(())
    return Propiedad((marca,))


def ownership_clause(
    alias: str, marca: Any, params: dict[str, Any], *, contexto: str
) -> str:
    """UNICA definicion del predicado de PROPIEDAD del camino de reversion.

    Igual que `rollback.scope_clause` es la unica definicion del ambito, esta
    es la unica de la propiedad. Dos definiciones que deben coincidir sin nada
    que lo verifique acaban divergiendo, y la que diverge borra de mas.

    Fail-closed en las dos direcciones:

    * sin propiedad (`None`) -> predicado SIEMPRE CIERTO, que es el radio
      antiguo `run`. NO se disfraza: quien pasa `None` esta pidiendo
      explicitamente el radio sin propiedad, y el ejecutor lo declara en el
      informe.
    * marca con forma no admisible -> excepcion. Una marca malformada
      filtraria por una propiedad que no distingue nada, que es peor que no
      filtrar: pareceria acotado.
    """
    prop = propiedad_de(marca)
    if not prop:
        return "true"
    try:
        return prop.propio(alias, params)
    except RollbackNotReconstructible as exc:
        raise RollbackNotReconstructible(
            f"{contexto}: {exc}; sin propiedad declarada no se borra"
        ) from exc


def marca_de_detalle(detail: dict[str, Any]) -> Propiedad:
    """La propiedad que declara una instruccion: LAS DOS marcas si estan.

    INTEGRACION tanda 8. `ownership_id` va primero porque es la que rotula el
    informe y la que sobrevive al restore; `apply_id` se conserva para que un
    grafo escrito antes de que la durable existiera siga siendo clasificable.
    """
    marcas = tuple(
        m for m in (detail.get(OWNERSHIP_ID_FIELD), detail.get(APPLY_ID_FIELD)) if m
    )
    return Propiedad(marcas)


def owned_by_apply_query(
    workspace: str, apply_id: str, partida_id: Optional[str], label: str = LABEL_EVIDENCE
) -> RollbackQuery:
    """Que nodos de esa etiqueta CREO ese apply. El conjunto PX, medido.

    El conjunto candidato no se lee de una lista del documento --que es lo que
    fijaba el radio en la corrida entera-- sino del propio grafo, preguntando
    por la marca de creacion. Un nodo que este apply REUTILIZO lleva el
    `apply_id` de quien lo creo y por tanto NO sale de aqui: P-noX es
    inalcanzable por construccion, no por una comprobacion posterior.
    """
    field_name = IDENTITY_FIELD[label]
    params: dict[str, Any] = {"ws": workspace}
    scope = scope_clause("n", partida_id, params, contexto="owned_by_apply")
    own = ownership_clause("n", apply_id, params, contexto="owned_by_apply")
    return RollbackQuery(
        f"MATCH (n:{label} {{workspace: $ws}}) "
        f"WHERE {scope} AND {own} "
        f"RETURN DISTINCT n.{field_name} AS id",
        params,
    )


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
    apply_id: Optional[str] = None,
) -> RollbackQuery:
    """El borrado. Las TRES condiciones van DENTRO del mismo `DELETE`.

    Ambito, propiedad y cero-referencias-vivas se evaluan en la misma
    operacion atomica que borra. Contar fuera y borrar despues seria TOCTOU:
    entre el censo y el `DELETE` otra transaccion puede crear la referencia
    que hacia inseguro el borrado. El censo de `execute_purge` INFORMA; esta
    consulta DECIDE. Ese diseno ya existia para la guarda de referencias y se
    conserva; la propiedad se anade en el mismo sitio, no en un paso previo.
    """
    field_name = IDENTITY_FIELD[label]
    params: dict[str, Any] = {"ws": workspace, "ids": list(ids)}
    cond = scope_clause("n", partida_id, params)
    own = ownership_clause("n", apply_id, params, contexto=f"purge:{label}")
    return RollbackQuery(
        "UNWIND $ids AS wanted "
        f"MATCH (n:{label} {{{field_name}: wanted, workspace: $ws}}) "
        f"WHERE {cond} AND {own} AND NOT {guard} "
        "DETACH DELETE n RETURN count(n) AS borrados",
        params,
    )


def delete_orphan_evidence_query(
    workspace: str, fragment_ids: list[str], partida_id: Optional[str],
    apply_id: Optional[str] = None,
) -> RollbackQuery:
    """Solo la evidencia SIN ninguna asercion viva detras."""
    return _delete_if_unreferenced(
        LABEL_EVIDENCE,
        fragment_ids,
        workspace,
        partida_id,
        f"EXISTS {{ MATCH (:{LABEL_ASSERTION})-[:{REL_SUPPORTED_BY}]->(n) }}",
        apply_id,
    )


def delete_orphan_episode_query(
    workspace: str, episode_ids: list[str], partida_id: Optional[str],
    apply_id: Optional[str] = None,
) -> RollbackQuery:
    return _delete_if_unreferenced(
        LABEL_EPISODE,
        episode_ids,
        workspace,
        partida_id,
        f"EXISTS {{ MATCH (n)-[:{REL_HAS_FRAGMENT}]->(:{LABEL_EVIDENCE}) }}",
        apply_id,
    )


def delete_orphan_source_query(
    workspace: str, source_ids: list[str], partida_id: Optional[str],
    apply_id: Optional[str] = None,
) -> RollbackQuery:
    return _delete_if_unreferenced(
        LABEL_SOURCE,
        source_ids,
        workspace,
        partida_id,
        f"EXISTS {{ MATCH (n)-[:{REL_HAS_EPISODE}]->(:{LABEL_EPISODE}) }}",
        apply_id,
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

    POR QUE ESTE BARRIDO NO SE ACOTA POR `apply_id` (INTEGRACION tanda 5)
    --------------------------------------------------------------------
    5B declaro un residuo: en su demo el desenlace salio `INCOMPLETE` con 3
    residuos porque este barrido es de AMBITO, no de apply, y su siembra
    sintetica no crea aserciones. Con `apply_id` ya disponible cabia acotarlo
    tambien por apply. SE EVALUO Y SE DECIDE QUE NO, porque acotarlo destruiria
    la propiedad por la que este barrido existe:

    es el unico que ve LO QUE EL DOCUMENTO NO NOMBRA. Un `apply_id` en el
    filtro solo dejaria pasar procedencia que el apply revertido creo --que es,
    por definicion, la que el documento SI nombra--, y la huerfana dejada por
    otro apply del mismo ambito volveria a ser invisible. Ese es el defecto
    exacto que este bloque cerro: un `ROLLED_BACK` con rc=0 sobre un grafo que
    lo desmiente. Acotar aqui es reabrirlo.

    Lo que SI faltaba no era alcance sino ATRIBUCION: el operador no podia
    distinguir «esto lo he dejado yo» de «esto ya estaba ahi». Por eso la
    consulta devuelve ademas el `apply_id` del nodo huerfano y `residues` lo
    publica en el detalle. El alcance NO cambia --mismo recall sobre todo el
    ambito--, y el `INCOMPLETE` pasa a ser accionable en vez de un numero sin
    duenno.
    """
    params: dict[str, Any] = {"ws": workspace}
    ev = scope_clause("ev", partida_id, params)
    ep = scope_clause("ep", partida_id, params)
    src = scope_clause("src", partida_id, params)
    return RollbackQuery(
        f"MATCH (ev:{LABEL_EVIDENCE} {{workspace: $ws}}) WHERE {ev} "
        f"OPTIONAL MATCH (:{LABEL_ASSERTION})-[sup:{REL_SUPPORTED_BY}]->(ev) "
        "WITH ev, count(sup) AS vivas WHERE vivas = 0 "
        f"RETURN '{LABEL_EVIDENCE}' AS clase, ev.fragment_id AS id, "
        "ev.apply_id AS apply_id, ev.ownership_id AS ownership_id "
        "UNION ALL "
        f"MATCH (ep:{LABEL_EPISODE} {{workspace: $ws}}) WHERE {ep} "
        f"OPTIONAL MATCH (ep)-[frg:{REL_HAS_FRAGMENT}]->(:{LABEL_EVIDENCE}) "
        "WITH ep, count(frg) AS vivas WHERE vivas = 0 "
        f"RETURN '{LABEL_EPISODE}' AS clase, ep.episode_id AS id, "
        "ep.apply_id AS apply_id, ep.ownership_id AS ownership_id "
        "UNION ALL "
        f"MATCH (src:{LABEL_SOURCE} {{workspace: $ws}}) WHERE {src} "
        f"OPTIONAL MATCH (src)-[epi:{REL_HAS_EPISODE}]->(:{LABEL_EPISODE}) "
        "WITH src, count(epi) AS vivas WHERE vivas = 0 "
        f"RETURN '{LABEL_SOURCE}' AS clase, src.source_asset_id AS id, "
        "src.apply_id AS apply_id, src.ownership_id AS ownership_id",
        params,
    )


# --- CLASIFICACION DEL RESULTADO: PX / SHARED / RESIDUE --------------------
#: Predicado de «este vecino NO es de X». Marca ausente cuenta como AJENO
#: a proposito: un nodo sin marca lo dejo un apply anterior a la propiedad, asi
#: que no es de X, y tratarlo como propio seria reclamar lo que no se creo.
#: La consecuencia se declara: sobre un grafo sin `apply_id` poblado, esta
#: clasificacion no denuncia residuo -- y es correcta, porque sin marca de
#: creacion NO hay conjunto PX que medir. Quien quiera ver esos nodos los tiene
#: en `observations`, que sigue barriendo todo el ambito.
def _ajeno(alias: str, prop: "Propiedad", params: dict[str, Any]) -> str:
    # INTEGRACION tanda 8: el vecino se juzga con LA MISMA propiedad que el
    # nodo. Si esta funcion mirase una marca distinta de la del filtro de PX,
    # un mismo vecino podria contar a la vez como propio y como ajeno.
    return prop.ajeno(alias, params)


def owned_residue_query(
    workspace: str, apply_id: str, partida_id: Optional[str], label: str
) -> RollbackQuery:
    """RESIDUE del apply X para UNA etiqueta. La definicion del operador, literal.

        PX       = elementos propiedad del apply X
        SHARED   = elementos de PX que siguen sostenidos por estado VIVO
        RESIDUE  = PX presentes que DEBERIAN haber desaparecido

        rollback limpio  <=>  RESIDUE == vacio

    POR QUE EXISTE (defecto D3, medido)
    -----------------------------------
    `orphan_provenance_query` barre el AMBITO entero y llama huerfano a todo lo
    que no tenga una asercion viva detras. Medido: un rollback EXACTO --diff
    vacio contra el estado previo, byte a byte-- salio `UNEXPECTED_RESIDUE`,
    `clean: false`, `rc=1`, denunciando 6 evidencias de OTRA fuente con la
    frase «procedencia HUERFANA ... nada vivo la sostiene». Era falso: las 7
    eran alcanzables desde su `V3Source` por `HAS_EPISODE`/`HAS_FRAGMENT`. El
    barrido denunciaba justo la procedencia que `docs/v3/58 §3` presume
    conservar, de modo que en CUALQUIER grafo con una fuente navegable todo
    rollback correcto salia `rc=1` y un runner no podia distinguirlo de uno
    sucio.

    La regla NO es «veo nodos de procedencia -> esta sucio». Una `V3Source` o
    una `V3Evidence` compartida PUEDE y DEBE sobrevivir. Y al reves: algo
    creado por X, no compartido y todavia presente es `INCOMPLETE`.

    QUE CUENTA COMO SOSTENIDO POR ESTADO VIVO, POR ETIQUETA
    -------------------------------------------------------
    * `V3Evidence`  -- la sostiene cualquier `V3Assertion -[SUPPORTED_BY]->`
      viva, o un `V3Episode` que X no creo (borrarla dejaria coja una fuente
      ajena).
    * `V3Episode`   -- lo sostiene un `V3Source` ajeno que lo cuelga, o una
      `V3Evidence` ajena que cuelga de el.
    * `V3Source`    -- la sostiene cualquier `V3Episode` ajeno que cuelgue de
      ella.

    Una fuente cuyos episodios son TODOS de X no esta sostenida por nada vivo:
    si sigue presente despues del rollback, es RESIDUE, y eso es exactamente el
    `INCOMPLETE` que se quiere poder ver.

    UNA CONSULTA POR ETIQUETA, no tres patrones en una. Dos `MATCH` sueltos
    darian producto cartesiano y, con cualquier conjunto vacio, CERO filas: un
    verde que no mide nada. Los vecinos se cuentan con subpatrones `COUNT {}`
    sobre la MISMA fila del nodo, que no multiplican.

    Esto OBSERVA; no borra. La condicion de borrado sigue siendo la de siempre
    y sigue viviendo DENTRO del `DELETE` (`_delete_if_unreferenced`): separar
    censo y borrado seria TOCTOU. Aqui se clasifica el RESULTADO, no se decide
    ningun borrado.
    """
    if label not in IDENTITY_FIELD:
        raise RollbackNotReconstructible(
            f"owned_residue_query: etiqueta {label!r} sin identidad durable"
        )
    field_name = IDENTITY_FIELD[label]
    params: dict[str, Any] = {"ws": workspace}
    if not propiedad_de(apply_id):
        raise RollbackNotReconstructible(
            "owned_residue_query: sin marca de propiedad no hay conjunto PX "
            "que medir"
        )
    scope = scope_clause("n", partida_id, params, contexto="owned_residue")
    # La MISMA propiedad para el nodo y para sus vecinos (`_ajeno`).
    prop = propiedad_de(apply_id)
    own = ownership_clause("n", prop, params, contexto="owned_residue")

    if label == LABEL_EVIDENCE:
        sostenes = (
            f"  COUNT {{ MATCH (:{LABEL_ASSERTION})-[:{REL_SUPPORTED_BY}]->(n) }} "
            "AS vivas, "
            f"  COUNT {{ MATCH (ep:{LABEL_EPISODE})-[:{REL_HAS_FRAGMENT}]->(n) "
            f"           WHERE {_ajeno('ep', prop, params)} }} AS ajenos"
        )
    elif label == LABEL_EPISODE:
        sostenes = (
            f"  COUNT {{ MATCH (src:{LABEL_SOURCE})-[:{REL_HAS_EPISODE}]->(n) "
            f"           WHERE {_ajeno('src', prop, params)} }} AS vivas, "
            f"  COUNT {{ MATCH (n)-[:{REL_HAS_FRAGMENT}]->(ev:{LABEL_EVIDENCE}) "
            f"           WHERE {_ajeno('ev', prop, params)} }} AS ajenos"
        )
    else:  # LABEL_SOURCE
        sostenes = (
            f"  COUNT {{ MATCH (n)-[:{REL_HAS_EPISODE}]->(ep:{LABEL_EPISODE}) "
            f"           WHERE {_ajeno('ep', prop, params)} }} AS vivas, "
            "  0 AS ajenos"
        )

    return RollbackQuery(
        f"MATCH (n:{label} {{workspace: $ws}}) "
        f"WHERE {scope} AND {own} "
        f"WITH n, {sostenes} "
        "WHERE vivas = 0 AND ajenos = 0 "
        f"RETURN '{label}' AS clase, n.{field_name} AS id, "
        # La fila declara las DOS marcas del nodo. Anunciar un residuo bajo la
        # clave `apply_id` cuando se acoto por `ownership_id` diria que
        # pertenece a un intento concreto, que es justo lo que dejo de ser.
        f"n.{OWNERSHIP_ID_FIELD} AS {OWNERSHIP_ID_FIELD}, "
        f"n.{APPLY_ID_FIELD} AS {APPLY_ID_FIELD}",
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


def dangling_applied_marks_query(
    workspace: str, partida_id: Optional[str] = None
) -> RollbackQuery:
    """Marcas `V3AppliedOperation` que afirman un conocimiento que ya no existe.

    POR QUE (tercer defecto medido)
    -------------------------------
    Tras un rollback declarado limpio --``ROLLED_BACK``, «No queda nada de esa
    operacion en el grafo», ``residues: []``-- un censo independiente encontro
    UNA `V3AppliedOperation` superviviente: el `S0` real era 1 nodo, no 0. Y no
    era inofensiva: la marca sigue diciendo «esto ya esta aplicado», asi que la
    relacion no se puede reescribir y el grafo queda atascado.

    `residues` no la veia porque solo preguntaba por las `idempotency_key` que
    el DOCUMENTO nombra, y esta no estaba nombrada. Lo que el documento no
    menciona es justo lo que hay que poder ver: el mismo problema de censo
    incompleto que ya se cerro para la procedencia huerfana, ahora para las
    marcas.

    QUE CUENTA COMO COLGANTE, Y QUE NO
    ----------------------------------
    NO se denuncia toda marca ajena: una marca de OTRO apply cuyo conocimiento
    sigue vivo es legitima, y denunciarla convertiria el censo en ruido que
    nadie leeria. Se denuncia la marca **colgante**: la que no tiene ni un solo
    nodo ni arista viva con su `idempotency_key`. Esa es, por definicion, una
    afirmacion que el grafo desmiente.

    AMBITO (INTEGRACION tanda 5): la carencia que 5B declaro aqui --«el ambito
    es el `workspace`, no la partida, porque `V3AppliedOperation` no lleva
    `partida_id`»-- SE CIERRA AL INTEGRAR: 5A hace que el writer estampe
    `op.partida_id` en la marca (`cypher.claim_applied_operation`), asi que el
    campo por el que acotar ya existe y esta poblado. La consulta se acota por
    ambito con la MISMA definicion unica que el resto del modulo
    (`rollback.scope_clause`): `partida_id=None` exige capa juego
    (`IS NULL`), un ambito declarado exige igualdad exacta.

    Sigue siendo fail-closed hacia el lado seguro: acotar ESTRECHA lo que se
    denuncia, nunca lo amplia, y este barrido OBSERVA -- no borra --, de modo
    que el peor caso de un ambito mal derivado es un censo que no menciona una
    marca ajena, jamas un borrado de mas.

    Los subpatrones `COUNT {}` NO se acotan por partida a proposito: lo que se
    pregunta ahi es «¿queda ALGO vivo con esta `idempotency_key`?». Un nodo
    superviviente de otra partida sigue siendo conocimiento vivo que sostiene
    la marca, y filtrarlo la declararia colgante cuando no lo esta: seria
    denunciar de mas, que es justo lo contrario de lo que se busca.

    Dos `MATCH` sueltos darian producto cartesiano; aqui la cuenta va en un
    subpatron `COUNT {}` sobre la MISMA fila de la marca.
    """
    params: dict[str, Any] = {"ws": workspace}
    cond = scope_clause("op", partida_id, params, contexto="dangling_applied_marks")
    return RollbackQuery(
        f"MATCH (op:{LABEL_APPLIED_OPERATION} {{workspace: $ws}}) "
        f"WHERE {cond} "
        "WITH op, "
        "  COUNT { MATCH (n {workspace: op.workspace, "
        f"           idempotency_key: op.idempotency_key}}) "
        f"          WHERE NOT n:{LABEL_APPLIED_OPERATION} }} AS nodos, "
        "  COUNT { MATCH ()-[r {workspace: op.workspace, "
        "           idempotency_key: op.idempotency_key}]->() } AS aristas "
        "WHERE nodos = 0 AND aristas = 0 "
        "RETURN op.idempotency_key AS idempotency_key, "
        "op.plan_hash AS plan_hash",
        params,
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
    #: Radio de esta purga, DECLARADO: "apply" (acotada a lo que ese apply
    #: creo) o "run" (radio antiguo, la corrida entera). Un informe que no
    #: dice su radio deja al lector suponiendolo, y el radio es exactamente lo
    #: que estaba mal.
    scope: str = "run"
    #: Marca de INTENTO del documento, si la hubo. Se conserva para auditoria.
    apply_id: Optional[str] = None
    #: Marca DURABLE de propiedad. INTEGRACION tanda 8: es la que acota de
    #: verdad cuando esta; `apply_id` solo queda como radio de los documentos
    #: emitidos antes de que existiera.
    ownership_id: Optional[str] = None
    #: Nodos que este apply NO creo y que por eso quedaron fuera del conjunto
    #: candidato. Es la mitad positiva de la propiedad: no basta con no
    #: borrarlos, hay que poder ENSENAR que se supo distinguirlos.
    not_owned: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "apply_id": self.apply_id,
            "ownership_id": self.ownership_id,
            "not_owned": {k: list(v) for k, v in self.not_owned.items()},
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
    partida = detail.get("partida_id")
    if not ws:
        raise RollbackNotReconstructible(
            f"{instruction.operation_id}: purga sin workspace"
        )
    # INTEGRACION tanda 8: la propiedad se toma de la marca DURABLE
    # (`ownership_id`) y solo se cae a `apply_id` cuando el documento es
    # anterior a ella. `apply_id` identifica el INTENTO: el mismo apply
    # logico replanificado tras un restore trae otro, y con el la purga
    # dejaba de reconocer lo que ella misma creo.
    apply_id = marca_de_detalle(detail)
    declarado = str(detail.get("scope") or ("apply" if apply_id else "run"))
    if declarado == "apply" and not apply_id:
        # Un documento que dice estar acotado por propiedad y no trae la marca
        # borraria con radio de corrida creyendose acotado. Fail-closed.
        raise RollbackNotReconstructible(
            f"{instruction.operation_id}: scope 'apply' sin "
            f"{OWNERSHIP_ID_FIELD} ni {APPLY_ID_FIELD}; sin propiedad "
            "declarada no se borra"
        )
    for _m in apply_id.marcas:
        # Forma admisible de la clase que sea; malformada, no se borra nada.
        campo_de_marca(_m)

    report = PurgeReport(
        scope=declarado,
        apply_id=detail.get(APPLY_ID_FIELD),
        ownership_id=detail.get(OWNERSHIP_ID_FIELD),
    )

    if apply_id:
        # RADIO POR PROPIEDAD. El conjunto candidato se DESCUBRE en el grafo
        # --que nodos llevan esta marca de creacion--, no se lee de una lista
        # del documento. Esa lista era el radio "run" y es justo lo que barria
        # lo que el apply no habia creado.
        fragments = sorted(
            {
                r["id"]
                for r in _rows(
                    runner, owned_by_apply_query(ws, apply_id, partida, LABEL_EVIDENCE)
                )
                if r.get("id")
            }
        )
    else:
        fragments = [f for f in (detail.get("fragment_ids") or []) if f]
    if not fragments:
        return report

    # 1. Antepasados ANTES de borrar: despues, las aristas ya no existen.
    ancestros = _rows(runner, ancestors_query(ws, fragments, partida))
    presentes = {r["fragment_id"] for r in ancestros if r.get("fragment_id")}
    report.absent = sorted(set(fragments) - presentes)
    episodios = sorted({r["episode_id"] for r in ancestros if r.get("episode_id")})
    fuentes = sorted({r["source_asset_id"] for r in ancestros if r.get("source_asset_id")})

    if apply_id:
        # Los antepasados salen por el CAMINO, asi que pueden ser de otro
        # apply: un episodio creado por el apply 1 es antepasado legitimo de un
        # fragmento del apply 2. Se recortan a los que ESTE apply creo, y los
        # que quedan fuera se DECLARAN en vez de desaparecer del informe.
        # (Aunque no se recortaran aqui, el `DELETE` los rechazaria: la
        # propiedad viaja tambien dentro de la consulta de borrado. Se hace en
        # los dos sitios a proposito -- lo que se declara y lo que se ejecuta
        # tienen que salir del mismo criterio.)
        for label, lista in ((LABEL_EPISODE, episodios), (LABEL_SOURCE, fuentes)):
            propios = {
                r["id"]
                for r in _rows(runner, owned_by_apply_query(ws, apply_id, partida, label))
                if r.get("id")
            }
            ajenos = sorted(set(lista) - propios)
            if ajenos:
                report.not_owned[label] = ajenos
            lista[:] = sorted(set(lista) & propios)

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
        _rows(runner, delete_orphan_evidence_query(ws, huerfanos, partida, apply_id))
        siguen = _existing(runner, LABEL_EVIDENCE, huerfanos, ws, partida)
        report.deleted_evidence = sorted(set(huerfanos) - siguen)
        for fid in sorted(siguen):
            report.retained_evidence.setdefault(fid, [])
    if episodios:
        _rows(runner, delete_orphan_episode_query(ws, episodios, partida, apply_id))
        siguen = _existing(runner, LABEL_EPISODE, episodios, ws, partida)
        report.deleted_episodes = sorted(set(episodios) - siguen)
        if siguen:
            report.retained_ancestors[LABEL_EPISODE] = sorted(siguen)
    if fuentes:
        _rows(runner, delete_orphan_source_query(ws, fuentes, partida, apply_id))
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
    #: Rarezas del AMBITO que este apply NO creo. Se publican para que el
    #: operador las vea y NO entran en `clean`: el desenlace de esta reversion
    #: no puede depender de lo que otro apply dejo. Ver `observations`.
    observations: list[dict[str, Any]] = field(default_factory=list)
    #: SHARED: elementos de PX que siguen sostenidos por estado VIVO y por eso
    #: NO se borraron. Se declaran --el operador tiene que poder verlos-- y NO
    #: entran en `clean`, porque la definicion es explicita: una `V3Source` o
    #: una `V3Evidence` compartida PUEDE y DEBE sobrevivir. RESIDUE es lo que
    #: deberia haber desaparecido; esto es justo lo contrario.
    retained: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """LIMPIO = ni residuos NI puntos no revertidos. Una sola definicion.

        CUARTO DEFECTO MEDIDO: `clean` solo miraba `residues`, mientras el
        mando decidia el desenlace con `report.clean and not
        report.unrecoverable`. Resultado: un mismo documento con
        ``"human": "...NO es una reversion limpia..."`` y ``"clean": true``
        dentro. No era una redaccion desafortunada: eran DOS definiciones de
        «limpio», y por eso podian contradecirse.

        Ahora hay una. La frase humana, el `code`, el `ok` y el `rc` cuelgan
        todos de esta propiedad, asi que no existe forma de imprimir
        «revertido» sobre un informe que no lo esta.

        LO QUE `clean` NO MIRA, Y POR QUE (arreglo del defecto D3)
        ---------------------------------------------------------
        * `observations` -- rarezas del ambito que este apply NO creo. El
          desenlace de ESTA reversion no puede depender de lo que otro dejo.
        * `retained`     -- SHARED: elementos de PX sostenidos por estado vivo,
          que por definicion del operador PUEDEN y DEBEN sobrevivir.

        `unrecoverable` SI cuenta, porque ahi queda lo que no se pudo revertir
        de verdad: instrucciones no reconstruibles y la prosa de los residuos.
        """
        return not self.residues and not self.unrecoverable

    def to_dict(self) -> dict[str, Any]:
        return {
            "executed": [dict(e) for e in self.executed],
            "purges": [dict(p) for p in self.purges],
            "residues": [dict(r) for r in self.residues],
            "unrecoverable": list(self.unrecoverable),
            "observations": [dict(o) for o in self.observations],
            "retained": list(self.retained),
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
                # SHARED, no RESIDUE. Va a `retained`, que se publica y NO
                # ensucia el desenlace: conservar lo que sigue sostenido por
                # estado vivo es el comportamiento CORRECTO, no una carencia.
                report.retained.append(
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
    # Canal SEPARADO, a proposito: lo que otro apply dejo se VE pero no decide
    # si esta reversion fue limpia. Mezclarlos era el defecto D3.
    report.observations = observations(runner, doc)
    for residuo in report.residues:
        report.unrecoverable.append(
            f"{codes.ROLLBACK_RESIDUE} {residuo['operation_id']}: "
            f"{residuo['what']} ({residuo['detail']})"
        )
    if annotate:
        # El documento que un operador RELEE debe decir la verdad de todo lo
        # que no se borro, tambien de lo conservado por compartido. Que no
        # ensucie el desenlace no significa que se calle.
        for linea in list(report.unrecoverable) + list(report.retained):
            if linea not in doc.unrecoverable:
                doc.unrecoverable.append(linea)
    return report


def _ambitos_de(doc: RollbackDocument) -> dict[tuple[str, Any], "Propiedad"]:
    """Los ambitos que este documento revirtio, y el `apply_id` de cada uno.

    El ambito NO se inventa: sale del documento y de sus instrucciones, igual
    que el `workspace`. Un documento sin ninguna instruccion con ambito
    revirtio la capa juego, que es `None` -- ausencia de campo y `None` no son
    lo mismo, y aqui se distingue.

    `apply_id` es lo que hace medible el conjunto PX. Viene del detalle de las
    instrucciones (`add_provenance_sweep` con `scope: "apply"` lo estampa). Si
    ninguna lo declara, el valor es `None` y quien pregunte sabe que sobre ese
    ambito NO hay propiedad que medir -- no se adivina una.
    """
    fuera: dict[tuple[str, Any], Propiedad] = {}
    for i in doc.instructions:
        ws = i.detail.get("workspace") or doc.workspace
        if not ws:
            continue
        clave = (ws, i.detail.get("partida_id"))
        declarado = marca_de_detalle(i.detail)
        if clave not in fuera or (not fuera[clave] and declarado):
            fuera[clave] = declarado or fuera.get(clave, Propiedad(()))
    if not fuera and doc.workspace:
        fuera[(doc.workspace, None)] = Propiedad(())
    return fuera


def residues(runner: Any, doc: RollbackDocument) -> list[dict[str, Any]]:
    """RESIDUE: lo de X que DEBERIA haber desaparecido y sigue presente.

    LA DEFINICION, TAL CUAL LA DA EL OPERADOR
    -----------------------------------------
        PX       = elementos propiedad del apply X
        SHARED   = elementos de PX que siguen sostenidos por estado vivo
        RESIDUE  = elementos de PX que DEBERIAN haber desaparecido
                   y siguen presentes

        rollback limpio  <=>  RESIDUE == vacio

    Lo que esta funcion ya NO hace, y es el arreglo (defecto D3, medido): NO
    llama residuo a toda procedencia del ambito que no tenga una asercion
    detras. Un rollback EXACTO --diff vacio contra el estado previo-- salia
    `UNEXPECTED_RESIDUE` / `clean: false` / `rc=1` denunciando 6 evidencias de
    OTRA fuente con la frase «procedencia HUERFANA ... nada vivo la sostiene»,
    siendo que las 7 eran alcanzables desde su `V3Source` por
    `HAS_EPISODE`/`HAS_FRAGMENT`. Consecuencia: en cualquier grafo con una
    fuente navegable TODO rollback correcto salia `rc=1`, y un runner no podia
    distinguirlo de uno sucio.

    Ese barrido de ambito NO desaparece: sigue corriendo, con el MISMO alcance,
    en `observations`. Cambia de canal, no de recall. Lo que deja de hacer es
    decidir si el desenlace es limpio.

    TRES FAMILIAS, MEDIDAS POR SEPARADO, UNA CONSULTA POR COSA CONTADA
    ------------------------------------------------------------------
    1. Cualquier nodo, arista o MARCA que aun lleve una `idempotency_key` del
       documento. Es de X por construccion: la clave la puso este apply.
    2. Procedencia de PX presente y no compartida (`owned_residue_query`),
       cuando el documento declara `apply_id`. Sin `apply_id` no hay PX que
       medir por propiedad y se cae al radio que el documento NOMBRA, que es
       la mejor aproximacion observable de PX y sigue siendo de X.
    3. Marcas `V3AppliedOperation` COLGANTES de ESTE apply. Se distinguen por
       `plan_hash`, que es lo que la marca guarda y lo que el documento trae.
       Cierra el caso medido de `residues: []` con una marca viva que el
       documento no nombraba: era de X, luego era residuo. Las colgantes de
       OTROS applies siguen viendose, en `observations`.
    """
    fuera: list[dict[str, Any]] = []
    vistas: set[tuple[str, str]] = set()

    # --- Familia 1: lo que aun lleva una clave de este documento -----------
    for instruction in doc.instructions:
        detail = dict(instruction.detail)
        ws = detail.get("workspace") or doc.workspace
        key = detail.get("idempotency_key")
        if not key or (ws, key) in vistas:
            continue
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

    ambitos = _ambitos_de(doc)

    # --- Familia 2: PX de procedencia presente y NO compartido -------------
    ya_dicho: set[tuple[str, str]] = set()
    for (ws, partida), apply_id in sorted(
        ambitos.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))
    ):
        if apply_id:
            for label in (LABEL_EVIDENCE, LABEL_EPISODE, LABEL_SOURCE):
                try:
                    consulta = owned_residue_query(ws, apply_id, partida, label)
                except RollbackNotReconstructible:
                    continue  # ambito o propiedad malformados: ya se denuncio
                for fila in _rows(runner, consulta):
                    if not fila.get("id"):
                        continue
                    detalle = {
                        "clase": fila["clase"],
                        "id": fila["id"],
                        "workspace": ws,
                        campo_de_marca(apply_id.principal)[0]: apply_id.principal,
                    }
                    que = (
                        f"RESIDUO de este apply ({fila['clase']}): lo creo esta "
                        "operacion, sigue en el grafo y NINGUN estado vivo "
                        "ajeno lo sostiene"
                    )
                    firma = (que, json.dumps(detalle, sort_keys=True, default=str))
                    if firma in ya_dicho:
                        continue
                    ya_dicho.add(firma)
                    fuera.append(
                        {
                            "operation_id": SWEEP_OPERATION_ID,
                            "what": que,
                            "detail": detalle,
                        }
                    )
            continue
        # Sin `apply_id`: PX se aproxima por lo que el documento NOMBRA. Se
        # denuncia la evidencia nombrada que sigue viva sin ninguna asercion
        # detras. Es el radio antiguo, restringido a lo nombrado: nunca alcanza
        # procedencia de otro apply que el documento no cite.
        for instruction in doc.instructions:
            if instruction.action != ACTION_PURGE_PROVENANCE:
                continue
            detail = dict(instruction.detail)
            if (detail.get("workspace") or doc.workspace) != ws:
                continue
            if detail.get("partida_id") != partida:
                continue
            fragments = [f for f in (detail.get("fragment_ids") or []) if f]
            if not fragments:
                continue
            for fila in _rows(
                runner, live_references_query(ws, fragments, partida)
            ):
                if int(fila.get("vivas") or 0) == 0:
                    fuera.append(
                        {
                            "operation_id": instruction.operation_id,
                            "what": "evidencia NOMBRADA por el documento que "
                            "sigue en el grafo y ninguna asercion viva la "
                            "sostiene",
                            "detail": {"fragment_id": fila["fragment_id"]},
                        }
                    )

    # --- Familia 3: marcas colgantes de ESTE apply -------------------------
    for (ws, partida), _apply_id in sorted(
        ambitos.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))
    ):
        try:
            consulta_marcas = dangling_applied_marks_query(ws, partida)
        except RollbackNotReconstructible:
            continue
        for fila in _rows(runner, consulta_marcas):
            clave = fila.get("idempotency_key")
            if not clave:
                continue
            # Propiedad de la marca. El comentario que habia aqui decia que
            # `V3AppliedOperation` NO lleva `apply_id`; dejo de ser cierto
            # cuando `cypher.claim_applied_operation` empezo a estamparlo, y la
            # marca lleva hoy ademas `ownership_id` (equipo 8B). Se corrige la
            # prosa, no la comparacion: se sigue comparando `plan_hash` porque
            # es lo que ESTE camino tiene garantizado en el documento, y una
            # comparacion se hace contra lo que se ha comprobado que llega, no
            # contra el campo mas nuevo que exista en el grafo.
            if not doc.plan_hash or fila.get("plan_hash") != doc.plan_hash:
                continue
            detalle_marca = {
                "idempotency_key": clave,
                "workspace": ws,
                "plan_hash": doc.plan_hash,
            }
            firma_marca = (
                "marca V3AppliedOperation COLGANTE de este apply: afirma una "
                "operacion aplicada de la que no queda nada en el grafo"
            )
            if any(
                r["what"] == firma_marca and r["detail"] == detalle_marca
                for r in fuera
            ):
                continue
            fuera.append(
                {
                    "operation_id": SWEEP_OPERATION_ID,
                    "what": firma_marca,
                    "detail": detalle_marca,
                }
            )
    return fuera


def observations(runner: Any, doc: RollbackDocument) -> list[dict[str, Any]]:
    """Cosas RARAS del ambito que este rollback no creo. NO deciden el desenlace.

    Es el barrido global de siempre --`orphan_provenance_query` y las marcas
    colgantes--, con el MISMO alcance: sigue viendo lo que el documento no
    nombra, que es la propiedad por la que existe. Lo unico que cambia es que
    ya no etiqueta como RESIDUO cualquier procedencia alcanzable, porque eso
    hacia que todo rollback correcto sobre un grafo con una fuente navegable
    saliese `rc=1` (defecto D3).

    Un dato aqui NO afecta a `clean` ni al `rc`: es de OTRO apply, y el
    desenlace de ESTA reversion no puede depender de lo que otro dejo. Se
    publica igualmente para que el operador lo vea y pueda actuar.
    """
    fuera: list[dict[str, Any]] = []
    ya_dicho: set[tuple[str, str]] = set()
    ambitos = _ambitos_de(doc)
    for (ws, partida), apply_id in sorted(
        ambitos.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))
    ):
        try:
            consulta = orphan_provenance_query(ws, partida)
        except RollbackNotReconstructible:
            continue
        for fila in _rows(runner, consulta):
            if not fila.get("id"):
                continue
            # Lo de X no es una observacion ajena: es residuo, y lo denuncia
            # `residues`. Aqui se publica lo que NO es de este apply.
            # INTEGRACION tanda 8: se compara por el campo de la MARCA en
            # uso. Comparando siempre `apply_id` mientras la propiedad va por
            # `ownership_id`, lo que X SI creo dejaria de reconocerse y se
            # publicaria aqui como «que este apply NO creo» -- ademas de
            # denunciarse, correctamente, en `residues`.
            if apply_id and any(
                fila.get(campo_de_marca(m)[0]) == m for m in apply_id.marcas
            ):
                continue
            detalle = {
                "clase": fila["clase"],
                "id": fila["id"],
                "workspace": ws,
                "apply_id": fila.get("apply_id"),
                OWNERSHIP_ID_FIELD: fila.get(OWNERSHIP_ID_FIELD),
            }
            que = (
                f"procedencia sin asercion viva detras ({fila['clase']}) que "
                "este apply NO creo: puede ser legitima (una fuente navegable "
                "lo es) o resto de otra operacion"
            )
            firma = (que, json.dumps(detalle, sort_keys=True, default=str))
            if firma in ya_dicho:
                continue
            ya_dicho.add(firma)
            fuera.append(
                {"operation_id": SWEEP_OPERATION_ID, "what": que, "detail": detalle}
            )
        try:
            consulta_marcas = dangling_applied_marks_query(ws, partida)
        except RollbackNotReconstructible:
            continue
        for fila in _rows(runner, consulta_marcas):
            clave = fila.get("idempotency_key")
            if not clave:
                continue
            if doc.plan_hash and fila.get("plan_hash") == doc.plan_hash:
                continue  # es de X: lo dice `residues`
            detalle_marca = {
                "idempotency_key": clave,
                "workspace": ws,
                "plan_hash": fila.get("plan_hash"),
            }
            que_marca = (
                "marca V3AppliedOperation COLGANTE de OTRO apply: afirma una "
                "operacion aplicada de la que no queda nada en el grafo"
            )
            firma = (
                que_marca,
                json.dumps(detalle_marca, sort_keys=True, default=str),
            )
            if firma in ya_dicho:
                continue
            ya_dicho.add(firma)
            fuera.append(
                {
                    "operation_id": SWEEP_OPERATION_ID,
                    "what": que_marca,
                    "detail": detalle_marca,
                }
            )
    return fuera



__all__ = [
    "OWN_ACTIONS",
    "PurgeReport",
    "RollbackReport",
    "ancestors_query",
    "delete_orphan_episode_query",
    "delete_orphan_evidence_query",
    "dangling_applied_marks_query",
    "delete_orphan_source_query",
    "execute_purge",
    "execute_rollback",
    "forget_applied_query",
    "key_evidence_query",
    "live_references_query",
    "observations",
    "orphan_provenance_query",
    "owned_residue_query",
    "ownership_clause",
    "campo_de_marca",
    "marca_de_detalle",
    "Propiedad",
    "propiedad_de",
    "owned_by_apply_query",
    "residues",
    "rollback_query_for",
]
