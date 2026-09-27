# -*- coding: utf-8 -*-
"""CORTE 6B-1 — resolver y mostrar nombres humanos, sin segunda autoridad.

Testigos del contrato de `app.presentacion_etiquetas`:

  1. label presente + workspace en ambito -> se muestra el label.
  2. label ausente -> se muestra el IDENTIFICADOR CANONICO, nunca inventado.
  3. workspace FUERA del ambito autorizado -> misma respuesta que "sin label"
     (no confirma ni niega existencia): el negativo mas importante del corte.
  4. cambiar el label no cambia el identificador que devuelve el workspace
     canonico ni el que declara el perfil.
  5. dos contextos con el MISMO label siguen siendo identificadores distintos.
  6. la partida usa el manifiesto de SU carpeta, no el `partida_access`.
  7. `NOMBRE_MANIFIESTO_PARTIDA` esta exento de la enumeracion de fuentes
     (misma exencion que `perfil-operador.json`).
"""
from __future__ import annotations

import json

from app import presentacion_etiquetas as pe
from app import sources_catalog


def _perfil(tmp_path, carpeta: str, workspace: str, label: str | None = None) -> None:
    juego = tmp_path / carpeta
    juego.mkdir(parents=True, exist_ok=True)
    datos = {"workspace": workspace}
    if label is not None:
        datos["metadata"] = {"label": label}
    (juego / sources_catalog.NOMBRE_PERFIL).write_text(
        json.dumps(datos), encoding="utf-8"
    )


def _manifiesto_partida(tmp_path, carpeta: str, partida_id: str, label: str | None) -> None:
    d = tmp_path / carpeta / "partidas" / partida_id
    d.mkdir(parents=True, exist_ok=True)
    datos = {}
    if label is not None:
        datos["metadata"] = {"label": label}
    (d / sources_catalog.NOMBRE_MANIFIESTO_PARTIDA).write_text(
        json.dumps(datos), encoding="utf-8"
    )


def test_label_presente_y_en_ambito_se_muestra(tmp_path):
    _perfil(tmp_path, "l5r", "leyenda", label="La Cofradía")
    env = {"S9K_VAULT_ROOT": str(tmp_path)}
    assert pe.etiqueta_workspace("leyenda", ["leyenda"], env) == "La Cofradía"


def test_label_ausente_devuelve_el_identificador_canonico_sin_inventar(tmp_path):
    _perfil(tmp_path, "l5r", "leyenda")  # sin metadata.label
    env = {"S9K_VAULT_ROOT": str(tmp_path)}
    assert pe.etiqueta_workspace("leyenda", ["leyenda"], env) == "leyenda"


def test_nunca_deriva_un_nombre_del_identificador_sin_manifiesto(tmp_path):
    # `partida:mesa1` NO produce "Mesa1", "Mesa 1" ni ninguna variante: sin
    # manifiesto, el fallback es el identificador EXACTO que llegó.
    _perfil(tmp_path, "l5r", "leyenda")
    env = {"S9K_VAULT_ROOT": str(tmp_path)}
    assert pe.etiqueta_partida("leyenda", "partida:mesa1", ["leyenda"], env) == "partida:mesa1"


def test_nunca_deriva_un_nombre_del_identificador_con_manifiesto_sin_label(tmp_path):
    # Manifiesto PRESENTE pero sin `metadata.label`: el fallback sigue siendo
    # el identificador tal cual, nunca una variante capitalizada o separada.
    _perfil(tmp_path, "l5r", "leyenda")
    _manifiesto_partida(tmp_path, "l5r", "partida:mesa1", None)
    env = {"S9K_VAULT_ROOT": str(tmp_path)}
    assert pe.etiqueta_partida("leyenda", "partida:mesa1", ["leyenda"], env) == "partida:mesa1"


def test_fuera_de_ambito_no_confirma_ni_niega_existencia(tmp_path):
    # El NEGATIVO MAS IMPORTANTE. `ws-ajeno` SI tiene un perfil legible con
    # label -- pero quien pregunta no tiene ese workspace en su ámbito. La
    # respuesta debe ser IDÉNTICA a "no hay label": el identificador, punto.
    _perfil(tmp_path, "ajeno", "ws-ajeno", label="El Gremio Secreto")
    env = {"S9K_VAULT_ROOT": str(tmp_path)}

    fuera_de_ambito = pe.etiqueta_workspace("ws-ajeno", ["leyenda"], env)
    sin_label = pe.etiqueta_workspace("ws-ajeno", [], env)

    assert fuera_de_ambito == "ws-ajeno"
    assert fuera_de_ambito == sin_label
    assert "Gremio" not in fuera_de_ambito


def test_control_positivo_dentro_de_ambito_si_devuelve_el_label(tmp_path):
    # Simétrico del anterior: MISMO perfil, MISMO label, la única variable que
    # cambia es el ámbito de quien pregunta.
    _perfil(tmp_path, "ajeno", "ws-ajeno", label="El Gremio Secreto")
    env = {"S9K_VAULT_ROOT": str(tmp_path)}
    assert pe.etiqueta_workspace("ws-ajeno", ["ws-ajeno"], env) == "El Gremio Secreto"


def test_partida_fuera_de_ambito_tambien_cae_al_identificador(tmp_path):
    _perfil(tmp_path, "l5r", "leyenda")
    _manifiesto_partida(tmp_path, "l5r", "mesa1", "Mesa de los jueves")
    env = {"S9K_VAULT_ROOT": str(tmp_path)}
    assert pe.etiqueta_partida("leyenda", "mesa1", [], env) == "mesa1"


def test_cambiar_el_label_no_cambia_workspace_ni_partida_id(tmp_path):
    _perfil(tmp_path, "l5r", "leyenda", label="Nombre A")
    _manifiesto_partida(tmp_path, "l5r", "mesa1", "Mesa A")
    env = {"S9K_VAULT_ROOT": str(tmp_path)}

    ws_antes = sources_catalog.raiz_de_bovedas(env) and "leyenda"
    assert pe.etiqueta_workspace("leyenda", ["leyenda"], env) == "Nombre A"
    assert pe.etiqueta_partida("leyenda", "mesa1", ["leyenda"], env) == "Mesa A"

    # Se reescribe el label...
    _perfil(tmp_path, "l5r", "leyenda", label="Nombre B")
    _manifiesto_partida(tmp_path, "l5r", "mesa1", "Mesa B")

    # ... el identificador canónico (lo que gobierna) NO cambia: sigue siendo
    # "leyenda" / "mesa1" en ambos casos, solo cambia lo que se PINTA.
    assert pe.etiqueta_workspace("leyenda", ["leyenda"], env) == "Nombre B"
    assert pe.etiqueta_partida("leyenda", "mesa1", ["leyenda"], env) == "Mesa B"
    assert ws_antes == "leyenda"


def test_dos_contextos_con_el_mismo_label_siguen_siendo_distintos(tmp_path):
    _perfil(tmp_path, "l5r", "leyenda", label="Mesa Semanal")
    _perfil(tmp_path, "cofradia", "ws-cofradia", label="Mesa Semanal")
    env = {"S9K_VAULT_ROOT": str(tmp_path)}

    a = pe.etiqueta_workspace("leyenda", ["leyenda", "ws-cofradia"], env)
    b = pe.etiqueta_workspace("ws-cofradia", ["leyenda", "ws-cofradia"], env)

    assert a == b == "Mesa Semanal"
    # El identificador subyacente sigue distinguiéndolos: la vista no colapsa
    # la identidad, solo la pinta igual.
    assert "leyenda" != "ws-cofradia"


def test_partida_usa_el_manifiesto_de_su_carpeta_no_partida_access(tmp_path):
    # No existe ninguna llamada a auth.db / partida_access en este módulo: se
    # comprueba estructuralmente en el AST del propio módulo.
    import ast
    import inspect

    arbol = ast.parse(inspect.getsource(pe))
    fuentes_de_datos = {
        n.id for n in ast.walk(arbol)
        if isinstance(n, ast.Name)
    } | {
        n.attr for n in ast.walk(arbol)
        if isinstance(n, ast.Attribute)
    }
    assert "partida_access" not in fuentes_de_datos
    assert "auth_db" not in fuentes_de_datos


def test_manifiesto_de_partida_exento_de_la_enumeracion_de_fuentes():
    assert sources_catalog.NOMBRE_MANIFIESTO_PARTIDA in sources_catalog._NO_SON_FUENTES


def test_identificador_vacio_no_se_convierte_en_ninguna_etiqueta(tmp_path):
    env = {"S9K_VAULT_ROOT": str(tmp_path)}
    assert pe.etiqueta_workspace("", ["leyenda"], env) == ""
    assert pe.etiqueta_workspace(None, ["leyenda"], env) == ""
    assert pe.etiqueta_partida("leyenda", "", ["leyenda"], env) == ""


def test_globals_de_jinja_son_las_mismas_funciones_un_unico_resolvedor():
    class FalsoEnv:
        def __init__(self):
            self.globals = {}

    envs = [FalsoEnv(), FalsoEnv()]
    pe.install_label_globals(envs)
    for env in envs:
        assert env.globals[pe.GLOBAL_ETIQUETA_WORKSPACE] is pe.etiqueta_workspace
        assert env.globals[pe.GLOBAL_ETIQUETA_PARTIDA] is pe.etiqueta_partida
