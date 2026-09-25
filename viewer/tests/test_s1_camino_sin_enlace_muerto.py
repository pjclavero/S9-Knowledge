# -*- coding: utf-8 -*-
"""S-1 · el resultado que se ofrece es el resultado que hay.

PROPIEDAD: no existe un camino normal donde el apply haya escrito conocimiento
real (`V3Assertion > 0`), el panel ofrezca un enlace a «lo que se aplicó», ese
destino responda 404, y el operador concluya razonablemente «no se escribió
nada».

MEDIDO EN DOS CAPAS, A PROPÓSITO. Este módulo mide la LÓGICA que decide el
desenlace (`result_provenance.alcanzable_para` y
`chassis_operations._camino_al_resultado`) contra objetos de mentira, sin
Neo4j: rápido, determinista, y lo que este arnés cubre — la DECISIÓN, no la
materialización. La MATERIALIZACIÓN real (que el apply de verdad deja
`V3Assertion >= 1` y `Entity == 0`, y que el destino de verdad responde 404) la
mide `test_panel_apply_desde_la_ui.py::test_S1_sin_alta_aprobada_el_panel_YA_NO_OFRECE_un_enlace_muerto`
y su hermano `test_SIN_ALTA_APROBADA_el_destino_niega_el_apply_que_acaba_de_ocurrir`,
contra un grafo Neo4j real en Docker (`@neo4j_real`). Este módulo NO sustituye
a esos dos casos: los calibra más barato y más rápido, para que una regresión
en la lógica se vea sin necesitar Docker.

LOS TRES CASOS QUE SE MIDEN AQUÍ, EN LA FUNCIÓN QUE DECIDE:

    1. `assertion > 0, entity > 0`  -> `alcanzable_para` True  -> `disponible`.
    2. `assertion > 0, entity == 0` -> `alcanzable_para` False -> `sin_identidad`.
    3. `assertion == 0`             -> `_camino_al_resultado` ni pregunta:
                                        `no_procede` (no hay `apply_id` que
                                        preguntar).

LO QUE ESTE MÓDULO NO EJERCE, DECLARADO. No arranca Neo4j, no aplica un plan
de verdad y no comprueba que el destino HTTP responda 200/404: eso es
infraestructura real y vive en el caso `@neo4j_real`. Lo que sí comprueba es
que, DADO lo que el grafo real mide (workspace fuera de `provider.workspaces()`
con operaciones presentes en el reader), la decisión del panel es la correcta
— y que un `reader` ausente (despliegues sin backend de procedencia, o esta
misma suite fuera de `neo4j_real`) NO se trata como negativo: se preserva el
desenlace previo, para no romper el resto de esta suite con una guarda que no
puede preguntar nada.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

VIEWER_ROOT = Path(__file__).resolve().parents[1]
if str(VIEWER_ROOT) not in sys.path:
    sys.path.insert(0, str(VIEWER_ROOT))

APPLY_ID = "apply:" + "a" * 32


class _ProveedorDeMentira:
    """Un `GraphProvider` de mentira: sólo lo que `alcanzable_para` mira."""

    def __init__(self, ambitos: tuple[str, ...]):
        self._ambitos = ambitos

    def workspaces(self):
        return self._ambitos


class _LectorDeMentira:
    """Un `ProvenanceReader` de mentira: sólo `operations_of_apply`."""

    def __init__(self, operaciones: list[dict]):
        self._operaciones = operaciones

    def operations_of_apply(self, workspace, apply_id):
        return list(self._operaciones)


# ---------------------------------------------------------------------------
# 1. `result_provenance.alcanzable_para`, la autoridad que decide el 404
# ---------------------------------------------------------------------------

def test_alcanzable_cuando_el_ambito_existe_y_el_apply_dejo_marca():
    """CASO 1: `assertion > 0, entity > 0` -> destino válido y navegable."""
    from app.services import result_provenance as sp

    provider = _ProveedorDeMentira(("ws-cofradia",))
    reader = _LectorDeMentira([{"idempotency_key": "k1"}])
    assert sp.alcanzable_para(provider, reader, "ws-cofradia", APPLY_ID) is True


def test_no_alcanzable_cuando_el_ambito_NO_incluye_el_workspace():
    """CASO 2, LA CAUSA MEDIDA: `assertion > 0, entity == 0`.

    `provider.workspaces()` deriva de nodos `:Entity`; si el apply no creó
    ninguno, el workspace no aparece ahí AUNQUE el reader vea sus operaciones.
    Éste es exactamente el bloqueo que `docs/92` documenta con Cypher real.
    """
    from app.services import result_provenance as sp

    provider = _ProveedorDeMentira(())  # el apply NO creó `:Entity`
    reader = _LectorDeMentira([{"idempotency_key": "k1"}])  # pero SÍ operó
    assert sp.alcanzable_para(provider, reader, "ws-cofradia", APPLY_ID) is False


def test_no_alcanzable_si_el_reader_no_ve_ninguna_operacion():
    from app.services import result_provenance as sp

    provider = _ProveedorDeMentira(("ws-cofradia",))
    reader = _LectorDeMentira([])
    resultado = sp.alcanzable_para(provider, reader, "ws-cofradia", APPLY_ID)
    # RONDA 2 · RESIDUAL 2: mensaje PROPIO, no el `assert ... is False`
    # genérico de pytest -ese repr casaría con cualquier fallo `is False` de
    # este fichero y no diría CUÁL es la causa.
    assert resultado is False, (
        "alcanzable_para() dio alcanzable=True para un apply sin ninguna "
        f"operación registrada en este workspace: {resultado!r}"
    )


def test_no_alcanzable_con_identificador_sin_forma_de_apply_id():
    from app.services import result_provenance as sp

    provider = _ProveedorDeMentira(("ws-cofradia",))
    reader = _LectorDeMentira([{"idempotency_key": "k1"}])
    assert sp.alcanzable_para(
        provider, reader, "ws-cofradia", "no-es-un-apply-id") is False


def test_no_alcanzable_sin_lector_de_procedencia():
    """`reader=None` es INDETERMINADO, y esta función lo trata como negativo:
    quien la llama (`_camino_al_resultado`) es quien decide si preguntarle."""
    from app.services import result_provenance as sp

    provider = _ProveedorDeMentira(("ws-cofradia",))
    assert sp.alcanzable_para(provider, None, "ws-cofradia", APPLY_ID) is False


# ---------------------------------------------------------------------------
# 2. `chassis_operations._camino_al_resultado`, el consumidor del panel
# ---------------------------------------------------------------------------

@dataclass
class _EstadoDeMentira:
    estado: str
    apply_id: Optional[str]


def _con_reader(monkeypatch, operaciones):
    """Instala un `reader_for` que siempre devuelve el lector de mentira."""
    import app.providers.provenance_reader as pr_mod

    lector = _LectorDeMentira(operaciones)
    monkeypatch.setattr(pr_mod, "reader_for", lambda provider: lector)


def _sin_reader(monkeypatch):
    import app.providers.provenance_reader as pr_mod

    monkeypatch.setattr(pr_mod, "reader_for", lambda provider: None)


def _encender_resultado(monkeypatch):
    import app.routers.resultado as pantalla_resultado

    monkeypatch.setattr(pantalla_resultado, "esta_encendida", lambda: True)


def test_camino_no_procede_sin_apply_no_pregunta_nada():
    """CASO 3: `assertion == 0` (no hay corrida aplicada). No hay `apply_id`
    que preguntar, así que el vocabulario es `no_procede` y no se toca el
    proveedor en absoluto."""
    from app.routers import chassis_operations as panel_ops

    estado = _EstadoDeMentira(estado="sealed", apply_id=None)
    vista = panel_ops._camino_al_resultado(estado, "ws-cofradia", object())
    assert vista["resultado"] == "no_procede"


def test_camino_disponible_cuando_alcanzable(monkeypatch):
    """CASO 1 desde el consumidor: alcanzable=True -> `disponible` + enlace."""
    from app.routers import chassis_operations as panel_ops

    _encender_resultado(monkeypatch)
    _con_reader(monkeypatch, [{"idempotency_key": "k1"}])
    provider = _ProveedorDeMentira(("ws-cofradia",))
    estado = _EstadoDeMentira(estado="applied", apply_id=APPLY_ID)

    vista = panel_ops._camino_al_resultado(estado, "ws-cofradia", provider)
    assert vista["resultado"] == "disponible"
    assert vista["apply_id"] == APPLY_ID
    assert vista["workspace"] == "ws-cofradia"


def test_camino_sin_identidad_cuando_NO_alcanzable(monkeypatch):
    """CASO 2 desde el consumidor, EL DEFECTO DE S-1: el destino se sirve
    (`esta_encendida`=True) pero el ámbito no incluye el workspace del apply
    -> el panel NO ofrece el enlace muerto: `sin_identidad`, sin `apply_id`
    publicado."""
    from app.routers import chassis_operations as panel_ops

    _encender_resultado(monkeypatch)
    _con_reader(monkeypatch, [{"idempotency_key": "k1"}])  # el apply ESTÁ
    provider = _ProveedorDeMentira(())  # pero el ámbito NO lo incluye
    estado = _EstadoDeMentira(estado="applied", apply_id=APPLY_ID)

    vista = panel_ops._camino_al_resultado(estado, "ws-cofradia", provider)
    assert vista["resultado"] == "sin_identidad", (
        f"S-1: el panel sigue ofreciendo {vista['resultado']!r} sobre un "
        "apply cuyo ámbito no alcanza el destino"
    )
    assert vista["apply_id"] is None, (
        "no se publica una identidad sobre la que no hay camino"
    )
    # RONDA 2 · RESIDUAL 1: la CAUSA de este `sin_identidad` es que el ámbito
    # no alcanza, NO que falte la identidad -que en este caso SÍ existe
    # (`estado.apply_id` está puesto)-. Sin este campo, la plantilla no tiene
    # cómo distinguir esta causa de la de `identidad_ausente`.
    assert vista["causa_sin_identidad"] == "ambito_no_alcanza", (
        f"la causa publicada no es la real: {vista['causa_sin_identidad']!r}"
    )


def test_camino_sin_identidad_causa_identidad_ausente_cuando_falta_el_apply_id():
    """LA OTRA CAUSA de `sin_identidad`: aquí SÍ es cierto que no consta la
    identidad -la fila no tiene un `apply_id` con forma válida-, y la causa
    publicada tiene que decir eso y no `ambito_no_alcanza`."""
    from app.routers import chassis_operations as panel_ops

    estado = _EstadoDeMentira(estado="applied", apply_id=None)
    vista = panel_ops._camino_al_resultado(estado, "ws-cofradia", object())
    assert vista["resultado"] == "sin_identidad"
    assert vista["causa_sin_identidad"] == "identidad_ausente", (
        f"causa incorrecta para una fila sin apply_id: "
        f"{vista['causa_sin_identidad']!r}"
    )


def test_camino_sigue_disponible_sin_lector_de_procedencia(monkeypatch):
    """SIN backend de procedencia (`reader_for` -> None) no se puede preguntar
    nada, y esta guarda NO degrada a `sin_identidad` por indeterminación: se
    conserva el desenlace previo al arreglo. Es lo que mantiene verde el resto
    de esta suite (proveedor `mock`, sin `_driver`) sin tocar su expectativa.
    """
    from app.routers import chassis_operations as panel_ops

    _encender_resultado(monkeypatch)
    _sin_reader(monkeypatch)
    provider = _ProveedorDeMentira(())  # ámbito vacío, pero NO se llega a mirar
    estado = _EstadoDeMentira(estado="applied", apply_id=APPLY_ID)

    vista = panel_ops._camino_al_resultado(estado, "ws-cofradia", provider)
    assert vista["resultado"] == "disponible", (
        "sin lector de procedencia el desenlace debía conservarse: "
        f"{vista['resultado']!r}"
    )


def test_camino_apagado_si_la_pregunta_de_alcanzabilidad_revienta(monkeypatch):
    """Una excepción al preguntar es fallo CERRADO, igual que la del
    interruptor: se degrada a `apagado`, nunca a `disponible` a ciegas."""
    from app.routers import chassis_operations as panel_ops

    _encender_resultado(monkeypatch)

    import app.providers.provenance_reader as pr_mod

    def _revienta(provider):
        raise RuntimeError("el lector no arranca")

    monkeypatch.setattr(pr_mod, "reader_for", _revienta)
    provider = _ProveedorDeMentira(("ws-cofradia",))
    estado = _EstadoDeMentira(estado="applied", apply_id=APPLY_ID)

    vista = panel_ops._camino_al_resultado(estado, "ws-cofradia", provider)
    assert vista["resultado"] == "apagado"


def test_camino_sin_identidad_previo_no_pregunta_por_alcanzabilidad(monkeypatch):
    """Cuando YA falta el `apply_id` (columna `None`), el camino se cierra
    ANTES de llegar a preguntar por alcanzabilidad: no hay nada que preguntar
    sobre una identidad que no existe."""
    from app.routers import chassis_operations as panel_ops

    llamado = []

    import app.providers.provenance_reader as pr_mod

    def _no_deberia_llamarse(provider):
        llamado.append(True)
        return _LectorDeMentira([{"idempotency_key": "k1"}])

    monkeypatch.setattr(pr_mod, "reader_for", _no_deberia_llamarse)
    provider = _ProveedorDeMentira(("ws-cofradia",))
    estado = _EstadoDeMentira(estado="applied", apply_id=None)

    vista = panel_ops._camino_al_resultado(estado, "ws-cofradia", provider)
    assert vista["resultado"] == "sin_identidad"
    assert vista["causa_sin_identidad"] == "identidad_ausente", (
        "causa incorrecta para una fila sin apply_id: "
        f"{vista['causa_sin_identidad']!r}"
    )
    assert not llamado, (
        "se preguntó por alcanzabilidad sobre un apply sin identidad durable"
    )


def test_camino_apply_id_malformado_es_identidad_ausente_y_no_pregunta(monkeypatch):
    """RONDA 3 · ARREGLO 1. Un `apply_id` PRESENTE pero con basura (sin forma
    de identidad durable) tiene que caer en `identidad_ausente`, NO en
    `ambito_no_alcanza` -eso sería la misma frase falsa que el residual 1
    quitó, desplazada de sitio: la pantalla diría «la identidad está
    registrada» sobre una columna sin identidad legible-.

    Es el CONTROL POSITIVO que falta al lado del caso `None` de arriba: los
    dos valores que hoy enrutan a `identidad_ausente` (ausente y malformado),
    con el mismo par simétrico (no se pregunta por alcanzabilidad -no hay
    nada que preguntar sobre una identidad que no tiene forma-).

    Se declara la ALCANZABILIDAD real de este estado en el docstring de
    `CAUSAS_SIN_IDENTIDAD`: el único llamador de `_camino_al_resultado`
    (`_plan_de_la_corrida`) recibe `estado.apply_id` ya filtrado por
    `es_apply_id` en `ReviewApplyService().estado()`, así que HOY esta rama es
    defensa en profundidad, no una rama que un corpus del árbol alcance. Este
    test la ejerce igualmente porque `_camino_al_resultado` acepta `estado`
    por forma, no por tipo, y perder esta guarda expondría de nuevo la frase
    falsa el día que cualquier otro llamador -o una regresión en
    `v3_apply.py`- deje de filtrar antes de llamar.
    """
    from app.routers import chassis_operations as panel_ops

    _encender_resultado(monkeypatch)
    llamado = []

    import app.providers.provenance_reader as pr_mod

    def _no_deberia_llamarse(provider):
        llamado.append(True)
        return _LectorDeMentira([{"idempotency_key": "k1"}])

    monkeypatch.setattr(pr_mod, "reader_for", _no_deberia_llamarse)
    provider = _ProveedorDeMentira(("ws-cofradia",))
    estado = _EstadoDeMentira(estado="applied", apply_id="no-es-un-apply-id")

    vista = panel_ops._camino_al_resultado(estado, "ws-cofradia", provider)
    assert vista["resultado"] == "sin_identidad"
    assert vista["causa_sin_identidad"] == "identidad_ausente", (
        "un apply_id malformado se está etiquetando como problema de ámbito, "
        f"no de identidad: {vista['causa_sin_identidad']!r}"
    )
    assert not llamado, (
        "se preguntó por alcanzabilidad sobre un apply_id sin forma válida"
    )
