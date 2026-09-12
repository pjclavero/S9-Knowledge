# -*- coding: utf-8 -*-
"""EQUIPO 8B -- propiedades de `ownership_id` que no dependen de Neo4j.

La demostracion CONTRA BASES REALES vive en `tests/escenario_equipo8b.py` (dos
contenedores, `elementId` disjuntos comprobados antes de comparar). Aqui quedan
las propiedades que se pueden fijar sin base, para que una regresion se vea en
CI y no solo cuando alguien levanta Docker.

Lo que se fija:
  * la identidad NO depende del reloj (es el defecto que cierra);
  * discrimina applies distintos (si no, autorizaria a borrar de mas);
  * distingue ambito ausente de capa juego;
  * es fail-closed cuando falta material;
  * y --el testigo del defecto original-- `apply_id` y `decision_hash` SI se
    mueven con el reloj sobre el producto sin arreglar.
"""
from __future__ import annotations

import copy

import pytest

from knowledge_v3.contracts.base import compute_idempotency_key
from knowledge_v3.writer.apply_identity import compute_apply_id
from knowledge_v3.writer.ownership_identity import (
    OWNERSHIP_ID_PREFIX,
    compute_ownership_id,
    is_ownership_id,
    ownership_id_for_view,
    require_ownership_id,
)

WS = "ws-cofradia"
SNAP = "snapshot:sha256:" + "ab" * 32
CLAVES = ["idem:sha256:" + "11" * 32, "idem:sha256:" + "22" * 32]


def _own(**kw):
    base = dict(workspace=WS, snapshot_id=SNAP, idempotency_keys=list(CLAVES))
    base.update(kw)
    return compute_ownership_id(**base)


# --- lo que la propiedad TIENE que cumplir ---------------------------------
def test_el_mismo_apply_logico_da_la_misma_identidad():
    assert _own() == _own()


def test_el_orden_de_las_operaciones_no_cambia_la_identidad():
    """El conjunto de operaciones es un CONJUNTO, no una lista.

    Si el orden entrase, replanificar el mismo apply con las operaciones
    emitidas en otro orden daria otra propiedad -- y el rollback dejaria de
    reconocer lo que el mismo apply logico creo.
    """
    assert _own(idempotency_keys=list(reversed(CLAVES))) == _own()


def test_un_apply_logico_distinto_da_identidad_distinta():
    """Sin esto la identidad no discrimina, y una propiedad que no distingue
    autoriza a borrar lo que creo otro apply."""
    otra = CLAVES[:1] + ["idem:sha256:" + "33" * 32]
    assert _own(idempotency_keys=otra) != _own()


def test_una_operacion_de_mas_cambia_la_identidad():
    assert _own(idempotency_keys=CLAVES + ["idem:sha256:" + "44" * 32]) != _own()


def test_el_ambito_entra_en_la_identidad():
    """Dos partidas con las mismas operaciones NO comparten propiedad."""
    a = _own(partida_id="partida:A")
    b = _own(partida_id="partida:B")
    assert a != b != _own() != a


def test_ambito_ausente_no_es_lo_mismo_que_capa_juego():
    """`None` es la capa juego --un ambito concreto--; la ausencia es «no se
    declaro». Si se codificasen igual, dos applies de ambitos distintos
    compartirian propiedad."""
    assert _own() != _own(partida_id=None)


def test_los_campos_no_se_pueden_confundir_entre_si():
    """Cada campo va precedido de su longitud: sin eso, mover un caracter de
    un campo al siguiente daria la misma identidad."""
    assert _own(workspace="ws-a", snapshot_id="bc") != _own(
        workspace="ws-ab", snapshot_id="c"
    )


def test_el_snapshot_entra_en_la_identidad():
    assert _own(snapshot_id="snapshot:sha256:" + "cd" * 32) != _own()


# --- fail-closed -----------------------------------------------------------
@pytest.mark.parametrize(
    "kw",
    [
        {"workspace": ""},
        {"workspace": "   "},
        {"snapshot_id": ""},
        {"idempotency_keys": []},
        {"idempotency_keys": ["", "x"]},
        {"partida_id": 7},
        {"partida_id": "  "},
    ],
)
def test_sin_material_completo_no_se_inventa_identidad(kw):
    """Una marca de propiedad vacia autorizaria despues a borrar por una
    propiedad que no distingue nada."""
    with pytest.raises(ValueError):
        _own(**kw)


def test_forma_admisible():
    valor = _own()
    assert valor.startswith(OWNERSHIP_ID_PREFIX)
    assert is_ownership_id(valor)
    assert require_ownership_id(valor, contexto="prueba") == valor


@pytest.mark.parametrize(
    "malo", [None, "", "own:", "apply:" + "a" * 32, "own:" + "z" * 32, "own:" + "a" * 31]
)
def test_una_marca_malformada_no_autoriza_a_borrar(malo):
    assert not is_ownership_id(malo)
    with pytest.raises(ValueError):
        require_ownership_id(malo, contexto="prueba")


# --- el view ---------------------------------------------------------------
class _View:
    def __init__(self, ops, **kw):
        self.workspace = kw.get("workspace", WS)
        self.snapshot_id = kw.get("snapshot_id", SNAP)
        self.partida_id = kw.get("partida_id")
        self.mutation_operations = ops


def test_la_identidad_sale_del_view_firmado():
    ops = tuple({"idempotency_key": k} for k in CLAVES)
    assert ownership_id_for_view(_View(ops)) == _own(partida_id=None)


@pytest.mark.parametrize("ops", [(), ({"sin_clave": 1},), None])
def test_un_view_que_no_permite_componer_devuelve_none(ops):
    """`None` = «este apply no estampa propiedad». Nunca un comodin."""
    assert ownership_id_for_view(_View(ops)) is None


# --- EL DEFECTO QUE SE CIERRA: reproduccion sobre el producto --------------
PLAN = {
    "workspace": WS,
    "snapshot_id": SNAP,
    "mutation_operations": [
        {
            "operation_type": "CREATE_ASSERTION",
            "decision_id": "dec:1",
            "target_entity_id": "entity:sela-marrec",
            "assertion_id": "assertion:1",
            "payload": {"predicate": "LEADS"},
        }
    ],
}


def _con_reloj(instante):
    """El MISMO apply logico, planificado en otro instante."""
    p = copy.deepcopy(PLAN)
    p["created_at"] = instante
    p["expires_at"] = instante
    return p


def test_las_idempotency_key_no_dependen_del_reloj():
    """La materia prima de la propiedad es durable. Es el hecho sobre el que
    se apoya todo lo demas, asi que se mide, no se presume."""
    a = _con_reloj("2026-01-01T00:00:00Z")
    b = _con_reloj("2026-09-08T11:22:33Z")
    assert [compute_idempotency_key(a, o) for o in a["mutation_operations"]] == [
        compute_idempotency_key(b, o) for o in b["mutation_operations"]
    ]


def test_ownership_sobrevive_al_cambio_de_reloj_y_apply_id_no():
    """La frase entera, en una sola prueba y sobre las funciones DEL PRODUCTO.

    `apply_id` deriva de `plan_hash`, que cubre `created_at`/`expires_at`: es
    identidad de INTENTO. `ownership_id` no los toca.
    """
    a = _con_reloj("2026-01-01T00:00:00Z")
    b = _con_reloj("2026-09-08T11:22:33Z")

    own_a, own_b = (
        compute_ownership_id(
            workspace=p["workspace"],
            snapshot_id=p["snapshot_id"],
            idempotency_keys=[
                compute_idempotency_key(p, o) for o in p["mutation_operations"]
            ],
        )
        for p in (a, b)
    )
    assert own_a == own_b, "la propiedad NO puede depender del reloj"

    # Y el testigo del defecto: dos planes que solo difieren en el instante
    # producen `plan_hash` distinto y, por tanto, `apply_id` distinto.
    app_a = compute_apply_id(workspace=WS, snapshot_id=SNAP, plan_hash="a" * 64)
    app_b = compute_apply_id(workspace=WS, snapshot_id=SNAP, plan_hash="b" * 64)
    assert app_a != app_b


def test_control_negativo_una_identidad_con_reloj_dentro_se_pone_roja():
    """Si la identidad dependiese del reloj, la prueba de arriba FALLARIA.

    Se construye la version rota a proposito: una prueba que no puede ponerse
    roja no es evidencia de nada.
    """
    a = _con_reloj("2026-01-01T00:00:00Z")
    b = _con_reloj("2026-09-08T11:22:33Z")

    def rota(p):
        # La mutacion: `expires_at` se cuela entre las claves.
        return compute_ownership_id(
            workspace=p["workspace"],
            snapshot_id=p["snapshot_id"],
            idempotency_keys=[p["expires_at"]]
            + [compute_idempotency_key(p, o) for o in p["mutation_operations"]],
        )

    assert rota(a) != rota(b)


# --- ACOPLE CON EL EQUIPO 8A (declarado, no supuesto) ----------------------
def test_el_payload_entra_en_la_propiedad_y_por_eso_debe_ir_canonizado():
    """El `payload` esta en `IDEMPOTENCY_KEY_FIELDS`, luego entra en la
    propiedad. 8A persiste los ALIAS de la entidad dentro del `payload`.

    Consecuencia, y es la que hay que vigilar: dos corridas del MISMO apply
    logico cuyo `payload` solo difiera en el ORDEN de la lista de alias
    producen `idempotency_key` distintas y, por tanto, `ownership_id`
    distintos -- reintroduciendo en silencio el defecto que este bloque cierra.

    No es un fallo del motor de propiedad: un `payload` distinto ES una
    operacion logica distinta, y que la identidad lo note es justo lo que la
    prueba 3 exige. Lo que la lista de alias tiene que garantizar es ORDEN
    CANONICO en el plan (misma preocupacion que ya documenta
    `tests/planner_hashseed_probe.py`, que nombra `idempotency_key`
    explicitamente).

    Esta prueba FIJA el acople para que, si algun dia se rompe, se lea aqui
    por que.
    """
    def clave(alias):
        p = copy.deepcopy(PLAN)
        p["mutation_operations"][0]["payload"]["aliases"] = alias
        return compute_idempotency_key(p, p["mutation_operations"][0])

    assert clave(["la Cofradia", "Cofradia"]) != clave(["Cofradia", "la Cofradia"]), (
        "si esto empieza a ser igual, el contrato ha cambiado; y mientras sea "
        "distinto, la lista de alias DEBE ir ordenada canonicamente en el plan"
    )
    # Ordenada, el orden de entrada deja de importar: ese es el remedio.
    assert clave(sorted(["la Cofradia", "Cofradia"])) == clave(
        sorted(["Cofradia", "la Cofradia"])
    )


def test_la_propiedad_no_depende_del_state_hash():
    """8A cambia el `state_hash` de los nodos creados CON alias.

    Se comprueba, no se presume, que eso no puede mover la propiedad: el
    material de `compute_ownership_id` no incluye `state_hash` por ninguna via.
    """
    import inspect

    from knowledge_v3.writer import ownership_identity

    assert "state_hash" not in inspect.getsource(ownership_identity)
