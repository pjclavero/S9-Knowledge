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

    _manifiesto_partida(tmp_path, "l5r", "mesa1", "Partida Homónima")
    _manifiesto_partida(tmp_path, "cofradia", "mesa1", None)

    a = pe.etiqueta_workspace("leyenda", ["leyenda", "ws-cofradia"], env)
    b = pe.etiqueta_workspace("ws-cofradia", ["leyenda", "ws-cofradia"], env)

    assert a == b == "Mesa Semanal"

    # RONDA 2 — antes esto acababa en `assert "leyenda" != "ws-cofradia"`, una
    # tautología sobre dos literales: no podía ponerse roja jamás. Lo que hay
    # que medir es el PRODUCTO: con el mismo label de workspace y el MISMO
    # `partida_id` en los dos, el resolvedor sigue yendo a la carpeta de CADA
    # workspace, así que las dos etiquetas de partida difieren. Si el
    # resolvedor colapsara los contextos por su label, esto se pone rojo.
    pa = pe.etiqueta_partida("leyenda", "mesa1", ["leyenda", "ws-cofradia"], env)
    pb = pe.etiqueta_partida("ws-cofradia", "mesa1", ["leyenda", "ws-cofradia"], env)
    assert pa == "Partida Homónima"
    assert pb == "mesa1"
    assert pa != pb


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
    # RONDA 2: los globals ya NO son las funciones puras, sino los envoltorios
    # `pass_context` que toman el ámbito de la petición. Lo que sigue
    # importando es que sea EL MISMO objeto en todos los entornos: un único
    # resolvedor, no uno por router.
    for env in envs:
        assert env.globals[pe.GLOBAL_ETIQUETA_WORKSPACE] is pe._global_etiqueta_workspace
        assert env.globals[pe.GLOBAL_ETIQUETA_PARTIDA] is pe._global_etiqueta_partida
    assert envs[0].globals[pe.GLOBAL_ETIQUETA_WORKSPACE] is envs[1].globals[
        pe.GLOBAL_ETIQUETA_WORKSPACE
    ]


# =========================================================================
# RONDA 2 — EL AMBITO YA NO LO ELIGE LA PLANTILLA
#
# El revisor independiente midio que la guarda de ambito era TAUTOLOGICA:
# casi todas las llamadas pasaban `[workspace]`, el propio workspace que se
# iba a pintar, de modo que `workspace not in {workspace}` nunca era cierto y
# la guarda NO SE EJECUTABA NUNCA desde una pantalla. Los testigos de arriba
# la ejercitaban pasando el ambito a mano: median la funcion, no el producto.
#
# Ahora el argumento no existe en la superficie de Jinja y el ambito sale de
# la peticion. Lo que sigue mide ESO, renderizando plantillas de verdad.
# =========================================================================

import jinja2
import pytest


class _EstadoFalso:
    pass


class _PeticionFalsa:
    """Lo minimo que `ambito_de_peticion` mira: `state.user_partidas` y
    `state.user`. No se falsea nada mas, y el resolvedor no puede leer otra
    cosa porque no recibe otra cosa."""

    def __init__(self, partidas=(), autenticado=True):
        self.state = _EstadoFalso()
        self.state.user_partidas = list(partidas)
        self.state.user = object() if autenticado else None


class _PartidaFalsa:
    def __init__(self, workspace, partida_id):
        self.workspace = workspace
        self.partida_id = partida_id


def _entorno_jinja():
    env = jinja2.Environment(autoescape=True)
    pe.install_label_globals([env])
    return env


def _dos_bovedas(tmp_path, monkeypatch):
    """Dos juegos en la MISMA raiz, los dos con label.

    Con dos perfiles legibles `autoridad_workspace` no resuelve workspace
    canonico (`COD_VARIOS_PERFILES`), asi que el ambito de la peticion es
    EXACTAMENTE el de las partidas del usuario: sin ese detalle, el canonico
    entraria en el ambito y el negativo no mediria nada.
    """
    _perfil(tmp_path, "l5r", "leyenda", label="La Cofradía")
    _perfil(tmp_path, "ajeno", "ws-ajeno", label="El Gremio Secreto")
    monkeypatch.setenv("S9K_VAULT_ROOT", str(tmp_path))


def test_la_plantilla_no_puede_elegir_su_propio_ambito(tmp_path, monkeypatch):
    """EL NEGATIVO DEL CORTE, AHORA EN EL CAMINO REAL.

    La plantilla pide el nombre de `ws-ajeno`, que TIENE label en disco. Quien
    hace la peticion solo tiene partidas en `leyenda`. Respuesta: el
    identificador. Y la plantilla no tiene forma de pedir otra cosa: el
    argumento de ambito ya no existe.
    """
    _dos_bovedas(tmp_path, monkeypatch)
    peticion = _PeticionFalsa([_PartidaFalsa("leyenda", "mesa1")])
    env = _entorno_jinja()

    pintado = env.from_string(
        "{{ etiqueta_workspace('ws-ajeno') }}"
    ).render(request=peticion)

    assert pintado == "ws-ajeno", (
        "FUGA DE AMBITO: la pantalla ha pintado el nombre humano de un "
        "workspace que NO esta en el ambito de esta peticion."
    )
    assert "Gremio" not in pintado


def test_control_positivo_el_mismo_render_con_el_workspace_en_ambito(
    tmp_path, monkeypatch
):
    """PAR SIMETRICO del anterior: misma boveda, mismo render, misma linea de
    codigo. La UNICA variable que cambia es el ambito de la peticion."""
    _dos_bovedas(tmp_path, monkeypatch)
    peticion = _PeticionFalsa([_PartidaFalsa("ws-ajeno", "mesa1")])
    env = _entorno_jinja()

    pintado = env.from_string(
        "{{ etiqueta_workspace('ws-ajeno') }}"
    ).render(request=peticion)

    assert pintado == "El Gremio Secreto"


def test_la_partida_ajena_tampoco_recibe_nombre_desde_plantilla(
    tmp_path, monkeypatch
):
    _dos_bovedas(tmp_path, monkeypatch)
    _manifiesto_partida(tmp_path, "ajeno", "mesa-secreta", "La Mesa del Gremio")
    env = _entorno_jinja()

    fuera = env.from_string(
        "{{ etiqueta_partida('ws-ajeno', 'mesa-secreta') }}"
    ).render(request=_PeticionFalsa([_PartidaFalsa("leyenda", "mesa1")]))
    dentro = env.from_string(
        "{{ etiqueta_partida('ws-ajeno', 'mesa-secreta') }}"
    ).render(request=_PeticionFalsa([_PartidaFalsa("ws-ajeno", "mesa-secreta")]))

    assert fuera == "mesa-secreta"
    assert dentro == "La Mesa del Gremio"


def test_sin_peticion_y_sin_usuario_el_ambito_es_vacio(tmp_path, monkeypatch):
    """FALLA CERRADO por los dos extremos: sin `request` en el contexto, y con
    `request` anonima teniendo la autenticacion ENCENDIDA."""
    _dos_bovedas(tmp_path, monkeypatch)
    monkeypatch.setenv("S9K_AUTH_ENABLED", "true")
    env = _entorno_jinja()

    sin_peticion = env.from_string("{{ etiqueta_workspace('ws-ajeno') }}").render()
    anonima = env.from_string("{{ etiqueta_workspace('ws-ajeno') }}").render(
        request=_PeticionFalsa([], autenticado=False)
    )

    assert sin_peticion == "ws-ajeno"
    assert anonima == "ws-ajeno"
    assert pe.ambito_de_peticion(None) == frozenset()


def test_el_workspace_canonico_si_esta_en_el_ambito_de_quien_esta_dentro(
    tmp_path, monkeypatch
):
    """El ambito no es solo "las partidas del usuario": el workspace canonico
    del despliegue —el unico que este producto sabe resolver, y que cualquier
    usuario ya ve escrito en su barra de estado— cuenta para quien esta
    autenticado. Una sola boveda: el canonico resuelve."""
    _perfil(tmp_path, "l5r", "leyenda", label="La Cofradía")
    monkeypatch.setenv("S9K_VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("S9K_AUTH_ENABLED", "true")

    autenticado = pe.ambito_de_peticion(_PeticionFalsa([], autenticado=True))
    anonimo = pe.ambito_de_peticion(_PeticionFalsa([], autenticado=False))

    assert "leyenda" in autenticado
    assert anonimo == frozenset()


# =========================================================================
# RONDA 2 — COSTE EN DISCO: MEMOIZACION POR PETICION
#
# Medido por el revisor: 4 `read_text` + 1 `iterdir` POR ETIQUETA, sin cache,
# y escalando con el numero de bovedas. Una tabla de 50 filas con 20 juegos
# son ~1000 lecturas por render, mas la cabecera de TODAS las paginas.
# =========================================================================


def _boveda_grande(tmp_path, monkeypatch, juegos=6, partidas=4):
    for i in range(juegos):
        _perfil(tmp_path, f"juego{i}", f"ws-{i}", label=f"Juego {i}")
        for j in range(partidas):
            _manifiesto_partida(tmp_path, f"juego{i}", f"mesa{j}", f"Mesa {j}")
    monkeypatch.setenv("S9K_VAULT_ROOT", str(tmp_path))


def test_memoizacion_una_lectura_por_ruta_y_por_peticion(tmp_path, monkeypatch):
    """La misma tabla, dos veces: sin memoria y con la de la peticion."""
    _boveda_grande(tmp_path, monkeypatch)
    filas = [("ws-3", f"mesa{j % 4}") for j in range(12)]

    sin_memoria = pe._Lector(cachear=False)
    for ws, pid in filas:
        pe.etiqueta_workspace(ws, ["ws-3"], None, sin_memoria)
        pe.etiqueta_partida(ws, pid, ["ws-3"], None, sin_memoria)

    peticion = _PeticionFalsa([_PartidaFalsa("ws-3", "mesa0")])
    resolvedor = pe.resolvedor_de_peticion(peticion)
    for ws, pid in filas:
        resolvedor.workspace(ws)
        resolvedor.partida(ws, pid)

    con_memoria = resolvedor.lector
    print(
        f"COSTE POR RENDER (12 filas x 2 etiquetas, 6 juegos): "
        f"sin memoria lecturas={sin_memoria.lecturas} "
        f"recorridos={sin_memoria.recorridos} | "
        f"memoizado lecturas={con_memoria.lecturas} "
        f"recorridos={con_memoria.recorridos}"
    )

    # Con memoria: la raiz se recorre UNA vez, y cada ruta se lee UNA vez.
    # Rutas distintas tocadas: los perfiles recorridos hasta `juego3` (4) +
    # el perfil de `ws-3` (ya leido) + 4 manifiestos de partida = 8.
    assert con_memoria.recorridos == 1
    assert con_memoria.lecturas <= 10
    # Y sin memoria el coste crece con las CELDAS, que es el defecto medido.
    assert sin_memoria.recorridos >= 24
    assert sin_memoria.lecturas > 10 * con_memoria.lecturas


def test_el_resolvedor_de_la_peticion_se_crea_una_sola_vez():
    peticion = _PeticionFalsa([])
    assert pe.resolvedor_de_peticion(peticion) is pe.resolvedor_de_peticion(peticion)


def test_la_memoria_no_sobrevive_a_la_peticion(tmp_path, monkeypatch):
    """La cache es POR PETICION a proposito: el operador edita el perfil a
    mano (no hay escritor hasta 6B-2) y el render siguiente tiene que verlo."""
    _perfil(tmp_path, "l5r", "leyenda", label="Nombre A")
    monkeypatch.setenv("S9K_VAULT_ROOT", str(tmp_path))
    partidas = [_PartidaFalsa("leyenda", "mesa1")]

    primera = pe.resolvedor_de_peticion(_PeticionFalsa(partidas)).workspace("leyenda")
    _perfil(tmp_path, "l5r", "leyenda", label="Nombre B")
    segunda = pe.resolvedor_de_peticion(_PeticionFalsa(partidas)).workspace("leyenda")

    assert primera == "Nombre A"
    assert segunda == "Nombre B"


# =========================================================================
# RONDA 2 — NADIE SE SALTA EL RESOLVEDOR
#
# El hueco real que encontro el revisor: revertir UNA plantilla a
# `{{ workspace }}` crudo dejaba la suite verde. El inventario de abajo es la
# lista EXPLICITA de apariciones crudas que son PROTOCOLO (`value=`, URLs,
# `tojson`, `data-*`, rutas de fichero). Cualquier aparicion nueva que no este
# aqui pone esto rojo.
#
# TECHO DECLARADO de esta red: mide expresiones de SALIDA (`{{ ... }}`) cuyo
# nombre termina en uno de `_NOMBRES_DE_IDENTIDAD`. No ve un identificador que
# viaje renombrado por un `{% set %}` intermedio, ni uno compuesto en el
# router y pasado ya como cadena. Para eso estan el parseo de las llamadas y
# los testigos de HTTP.
# =========================================================================

_NOMBRES_DE_IDENTIDAD = {
    "workspace",
    "partida_id",
    "workspace_canonico",
    "active_partida",
}

#: plantilla -> {expresion cruda: cuantas veces} QUE SON PROTOCOLO.
#: Revisada una por una; la razon de cada una, al lado.
_PROTOCOLO_DECLARADO = {
    # `value` del campo de solo lectura que viaja en el POST de concesion.
    "auth/admin/partidas.html": {"workspace_canonico": 1},
    # `value` de cada opcion del selector de partida.
    "base.html": {"p.partida_id": 1},
    # query-string del enlace al resultado, y `data-*` que lee el JS del filtro.
    "chassis/operations.html": {
        "plan.workspace": 1,
        "f.ambito.workspace": 1,
        "f.ambito.partida_id": 1,
    },
    # campo oculto del formulario + dos enlaces de paginacion.
    "entities.html": {"workspace": 3},
    # `tojson` para el JS del grafo.
    "graph.html": {"workspace": 1},
    # query-string de enlaces.
    "resultado/evidencia.html": {"detalle.workspace": 1},
    "resultado/resultado.html": {"resultado.workspace": 1},
    # RUTA EN DISCO (`output/reviews/<workspace>/...`): es un path, no un nombre.
    "reviews.html": {"workspace": 1},
    # dos campos ocultos + una query-string.
    "v3_review.html": {"workspace": 3},
}


def _salidas_crudas_por_plantilla():
    from jinja2 import nodes
    from pathlib import Path

    raiz = Path(pe.__file__).resolve().parent / "templates"
    entorno = jinja2.Environment()

    def nombre(n):
        if isinstance(n, nodes.Name):
            return n.name
        if isinstance(n, nodes.Getattr):
            return (nombre(n.node) or "?") + "." + n.attr
        if isinstance(n, nodes.Getitem) and isinstance(n.arg, nodes.Const):
            return (nombre(n.node) or "?") + "." + str(n.arg.value)
        return None

    def desenvuelve(n):
        while isinstance(n, (nodes.Filter, nodes.MarkSafe)):
            n = n.node
        return n

    inventario = {}
    for f in sorted(raiz.rglob("*.html")):
        arbol = entorno.parse(f.read_text(encoding="utf-8"))
        cuenta = {}
        for salida in arbol.find_all(nodes.Output):
            for hijo in salida.nodes:
                pendientes = [hijo]
                while pendientes:
                    n = desenvuelve(pendientes.pop())
                    if isinstance(n, nodes.CondExpr):
                        pendientes += [x for x in (n.expr1, n.expr2) if x is not None]
                        continue
                    if isinstance(n, nodes.Call):
                        if nombre(n.node) in (
                            pe.GLOBAL_ETIQUETA_WORKSPACE,
                            pe.GLOBAL_ETIQUETA_PARTIDA,
                        ):
                            continue  # pasa por el resolvedor: correcto
                        pendientes += list(n.args)
                        continue
                    if isinstance(n, nodes.Concat):
                        pendientes += list(n.nodes)
                        continue
                    nm = nombre(n)
                    if nm and nm.split(".")[-1] in _NOMBRES_DE_IDENTIDAD:
                        cuenta[nm] = cuenta.get(nm, 0) + 1
        if cuenta:
            inventario[str(f.relative_to(raiz))] = cuenta
    return inventario


def test_ninguna_plantilla_se_salta_el_resolvedor():
    """EL HUECO DE LA RONDA 1: una plantilla que pinta `{{ workspace }}` crudo
    en una superficie de operador no la veia nadie. Ahora si."""
    medido = _salidas_crudas_por_plantilla()

    nuevas = []
    for plantilla, cuenta in sorted(medido.items()):
        declarado = _PROTOCOLO_DECLARADO.get(plantilla, {})
        for expr, n in sorted(cuenta.items()):
            if n > declarado.get(expr, 0):
                nuevas.append(f"{plantilla}: {{{{ {expr} }}}} x{n} "
                              f"(declaradas como protocolo: {declarado.get(expr, 0)})")

    assert not nuevas, (
        "Hay apariciones CRUDAS del identificador en plantilla que no estan "
        "declaradas como protocolo. O pasan por el resolvedor unico "
        "(`etiqueta_workspace` / `etiqueta_partida`), o se declaran aqui con "
        "su razon:\n  " + "\n  ".join(nuevas)
    )


def test_el_inventario_de_protocolo_no_declara_ausencias(tmp_path):
    """CONTROL POSITIVO DEL INSTRUMENTO. Dos partes:

    1. ninguna entrada declarada sobra (si sobra, el inventario describe un
       arbol que ya no existe y sus ceros no valen);
    2. la red SI detecta una plantilla que se salta el resolvedor — se fabrica
       una y se mide.
    """
    medido = _salidas_crudas_por_plantilla()
    sobran = []
    for plantilla, cuenta in sorted(_PROTOCOLO_DECLARADO.items()):
        real = medido.get(plantilla, {})
        for expr, n in sorted(cuenta.items()):
            if real.get(expr, 0) != n:
                sobran.append(f"{plantilla}: {expr} declarado x{n}, medido "
                              f"x{real.get(expr, 0)}")
    assert not sobran, (
        "El inventario de protocolo no coincide con el arbol: " + "; ".join(sobran)
    )

    # CONTROL POSITIVO: la misma funcion, sobre una plantilla que SI se salta
    # el resolvedor, tiene que contarla.
    from jinja2 import nodes

    entorno = jinja2.Environment()
    arbol = entorno.parse("<h2>Juego: {{ workspace }}</h2>")
    crudas = [
        n.name for s in arbol.find_all(nodes.Output) for n in s.nodes
        if isinstance(n, nodes.Name) and n.name in _NOMBRES_DE_IDENTIDAD
    ]
    assert crudas == ["workspace"], (
        "INSTRUMENTO CIEGO: la red no detecta ni el caso evidente, asi que sus "
        "ceros sobre el arbol real no significan nada."
    )


def test_ninguna_pantalla_de_operador_interpola_el_workspace_crudo_en_un_error():
    """La AFIRMACION FALSA de la ronda 1: se dijo «revisado, ningun
    `HTTPException.detail` interpola el identificador crudo». Habia uno, en la
    rama de error de la MISMA pantalla cuyas celdas si se convirtieron. Esto ya
    no se «revisa»: se mide por AST sobre los tres arboles."""
    import ast
    from pathlib import Path

    raices = [
        Path(pe.__file__).resolve().parent,          # viewer/app
        Path(pe.__file__).resolve().parents[2] / "cli",
        Path(pe.__file__).resolve().parents[3] / "src",
    ]
    culpables = []
    for raiz in raices:
        if not raiz.exists():
            continue
        for f in sorted(raiz.rglob("*.py")):
            try:
                arbol = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for nodo in ast.walk(arbol):
                if not (isinstance(nodo, ast.Call)
                        and getattr(nodo.func, "id", "") == "HTTPException"):
                    continue
                for kw in nodo.keywords:
                    if kw.arg != "detail":
                        continue
                    for sub in ast.walk(kw.value):
                        if isinstance(sub, ast.FormattedValue) and isinstance(
                            sub.value, ast.Name
                        ) and sub.value.id in _NOMBRES_DE_IDENTIDAD - {"partida_id"}:
                            culpables.append(f"{f.name}:{nodo.lineno}: {sub.value.id}")

    assert not culpables, (
        "Un mensaje de error dirigido al operador interpola el identificador "
        "crudo del workspace en vez de pasarlo por el resolvedor unico: "
        + "; ".join(culpables)
    )
