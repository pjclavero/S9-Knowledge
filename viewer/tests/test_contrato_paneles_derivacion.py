"""LA LISTA DE CAMPOS DEL CONTRATO SE DERIVA, NO SE ESCRIBE (carril 4 de V3.1).

POR QUE ESTE FICHERO EXISTE APARTE
==================================
Todo lo de aqui es AST puro --Python y Jinja-- y no necesita Neo4j, ni Docker,
ni una peticion HTTP. Vivia dentro de ``test_contrato_paneles_neo4j.py``, que
lleva ``pytestmark = skipif(sin NEO4J_TEST_URI)`` en la cabecera, asi que en
local salia SKIPPED: la pieza central del carril --«un campo nuevo consumido
pone ROJO hasta que alguien lo clasifica»-- solo vigilaba dentro del job de
Neo4j. Un guarda que solo se ejecuta en un job es un guarda mudo en todos los
demas, que es la forma exacta en que se apagan los controles en este repo. Al
sacarlo aqui, corre en TODA ejecucion de la suite del visor.

EL HUECO QUE ESTO CIERRA
========================
Sobre ``main=aaf9695``, ``aliases`` y ``updated_at`` de ``_node_to_dict`` los
consumen las plantillas y NO aparecian en la tabla ``ABLACIONES`` ni en ninguna
otra prueba: quitarlos de la proyeccion dejaba todo verde. No fue un descuido
puntual, fue el METODO: una lista documental mantenida a mano se queda corta el
dia que alguien pinta un campo nuevo.

LOS TRES SALTOS DE LA DERIVACION
================================
  1. QUE PLANTILLAS PINTAN NODOS -- funciones de ``viewer/app`` que llaman a
     ``serialize_node`` (directamente, por alias, por atributo de modulo o a
     traves de otra funcion que lo haga) Y renderizan. El nombre de la
     plantilla se resuelve tambien cuando no es literal (``SLOT.template``,
     ``ITEM_TEMPLATE``), importando el modulo y leyendo el valor real.
  2. QUE ATRIBUTOS CONSUME CADA PLANTILLA -- por el AST de Jinja.
     ``{{ entity.foo }}`` cuenta; un comentario que mencione ``foo``, no.
  3. DE QUE PROPIEDAD DE NEO4J SALE CADA ATRIBUTO -- componiendo el dict que
     devuelve ``serialize_node`` con el que devuelve ``_node_to_dict``. El
     bloque ``technical`` se expande por su constante real
     (``_NODE_TECHNICAL_FIELDS``), que es como ``updated_at`` llega a la
     pantalla.

FALLO CERRADO ANTE UN PINTOR NUEVO
==================================
La primera version fallaba ABIERTA: la deteccion de pintores solo casaba
``ast.Name``, asi que ``serializers.serialize_node(n)``, un alias o un helper no
se detectaban, y la resolucion de plantillas no cubria f-strings ni ``DIC['k']``.
Una plantilla nueva escrita con cualquiera de esas formas traia campos sin
ablacion y NADIE enrojecia: desaparecia del conjunto en silencio. Ahora:

* los nombres que valen como ``serialize_node`` se resuelven por alias de
  importacion y por atributo (``serializers.serialize_node``);
* el «llama a un pintor» es TRANSITIVO y ATRAVIESA MODULOS: se calcula el punto
  fijo de «funciones que llaman a una funcion sembradora», asi que delegar la
  serializacion en un helper no esconde nada;
* cuando el valor no se puede fijar pero SI se conoce el dominio, se ENSANCHA en
  vez de estrechar: ``chassis_slot.py`` renderiza ``slot.template`` con ``slot``
  como PARAMETRO --una linea que sirve las cuatro pantallas de hueco-- y ahi se
  toman las CUATRO plantillas del contrato del chasis. Estrechar pierde
  pintores; ensanchar solo puede sobrar;
* y toda funcion que renderice con un nombre de plantilla que NO se puede
  resolver ni acotar sale en ``renderizadores_no_clasificables()``, que un test
  pone ROJO. No desaparece del conjunto: grita.

COSTE MEDIDO del fallo cerrado: sobre los 51 puntos de render de ``viewer/app``,
la primera version de esta guarda senalo DOS (ambos la misma linea de
``chassis_slot.py``, vista desde la funcion externa y desde la interna). Con el
ensanchamiento por dominio, la lista queda VACIA: cero falsos positivos, y
ninguna exencion escrita a mano.

COTA QUE QUEDA (declarada, no implicita)
----------------------------------------
El punto fijo empareja por NOMBRE de funcion, no por resolucion completa de
imports: un helper importado con ``as`` y con un nombre distinto en cada modulo
seguiria sin verse. Cerrar eso exige un grafo de llamadas de verdad. Lo que NO
queda abierto es el caso silencioso: si ese helper renderiza, su plantilla
tendra un nombre resoluble o caera en ``renderizadores_no_clasificables()``.

POR QUE HAY DOS REDES Y LAS DOS SON NECESARIAS
==============================================
Nota del revisor, escrita aqui para que nadie las simplifique: si el
descubrimiento PERDIERA una plantilla, las 18 propiedades seguirian saliendo
igual en 5 de los 6 casos, por REDUNDANCIA (varias plantillas consumen los
mismos campos) -- un verde silencioso. Lo que salva la garantia es que las dos
redes se reparten exactamente esos casos:

* ``test_las_plantillas_que_pintan_nodos_se_ENCUENTRAN_solas`` ancla CUATRO por
  nombre (incluido el panel G, que llega por ``SLOT.template`` y no como
  literal);
* y la asercion ``sobran`` de ``test_la_lista_de_campos_se_DERIVA_de_las_plantillas``
  cubre el sexto caso, ``entity_detail.html``: es la unica plantilla de la que
  ``source_kind`` y ``workspace`` se derivan EN EXCLUSIVA, asi que perderla
  dejaria esas dos clasificadas sin nadie que las consuma y la asercion lo dice.

Las dos son LOAD-BEARING. Quitar cualquiera de las dos abre un agujero.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import jinja2
import pytest
from jinja2 import nodes as JN

VIEWER_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = VIEWER_ROOT / "app"
PLANTILLAS_DIR = APP_DIR / "templates"

#: La funcion cuya salida pintan las plantillas. Todo el descubrimiento cuelga
#: de este nombre.
SEMILLA_SERIALIZADORA = "serialize_node"


# ---------------------------------------------------------------------------
# Salto 1: que plantillas pintan nodos
# ---------------------------------------------------------------------------

def _modulos_de_la_app() -> list[Path]:
    return sorted(APP_DIR.rglob("*.py"))


def _modulo_importado(ruta: Path):
    """El modulo YA IMPORTADO que corresponde a ese fichero.

    Hace falta para resolver `SLOT.template` e `ITEM_TEMPLATE`: son valores, no
    literales, y leerlos del texto seria adivinar.
    """
    punteado = ".".join(ruta.relative_to(VIEWER_ROOT).with_suffix("").parts)
    try:
        return importlib.import_module(punteado)
    except Exception:
        return None


def _alias_de_la_semilla(arbol: ast.AST) -> set[str]:
    """Nombres que en ESTE modulo significan `serialize_node`.

    Cubre `from app.serializers import serialize_node as sn` y el uso por
    atributo (`serializers.serialize_node`), que la primera version no veia.
    """
    nombres = {SEMILLA_SERIALIZADORA}
    for n in ast.walk(arbol):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name == SEMILLA_SERIALIZADORA and a.asname:
                    nombres.add(a.asname)
    return nombres


def _nombre_llamado(c: ast.Call) -> str | None:
    """El nombre «desnudo» de lo que se llama: `f`, `mod.f`, `self.f` -> `f`."""
    if isinstance(c.func, ast.Name):
        return c.func.id
    if isinstance(c.func, ast.Attribute):
        return c.func.attr
    return None


def _llamadas(nodo: ast.AST) -> set[str]:
    return {n for n in (_nombre_llamado(c) for c in ast.walk(nodo)
                        if isinstance(c, ast.Call)) if n}


def _funciones(arbol: ast.AST):
    for n in ast.walk(arbol):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield n


def _arboles() -> dict[Path, ast.AST]:
    salida = {}
    for py in _modulos_de_la_app():
        try:
            salida[py] = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
    return salida


def sembradoras() -> set[str]:
    """PUNTO FIJO: nombres de funcion que, directa o indirectamente, serializan.

    Se empieza por `serialize_node` (y sus alias en cada modulo) y se repite
    «quien llama a una sembradora es sembradora» hasta que el conjunto deja de
    crecer. Empareja por NOMBRE y ATRAVIESA MODULOS a proposito: delegar la
    serializacion en un helper de otro fichero no puede esconder un pintor.
    """
    arboles = _arboles()
    nombres: set[str] = {SEMILLA_SERIALIZADORA}
    for arbol in arboles.values():
        nombres |= _alias_de_la_semilla(arbol)

    cambio = True
    while cambio:
        cambio = False
        for arbol in arboles.values():
            for fn in _funciones(arbol):
                if fn.name in nombres:
                    continue
                if _llamadas(fn) & nombres:
                    nombres.add(fn.name)
                    cambio = True
    return nombres


def _plantillas_del_chasis() -> list[str]:
    """Las plantillas de los CUATRO huecos, leidas del contrato del chasis."""
    from app.chassis import FEATURE_SLOTS
    return [s.template for s in FEATURE_SLOTS]


def _nombres_de_plantilla(nodo, modulo) -> list[str]:
    """Nombres a los que PUEDE resolver ese argumento. Lista vacia = no se sabe.

    Devuelve una LISTA, no un nombre, porque hay un caso real en el que el valor
    no se puede fijar y aun asi se sabe el DOMINIO: `chassis_slot.py` renderiza
    `slot.template` donde `slot` es un PARAMETRO (`build_slot_router(slot)`), de
    modo que esa unica linea sirve las cuatro pantallas de hueco. Ahi la
    respuesta honesta no es «no se» --que lo sacaria del conjunto-- ni «esta
    concreta», sino EL DOMINIO ENTERO: las cuatro. Ensanchar es la direccion
    segura; estrechar es la que pierde pintores.
    """
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) \
       and nodo.value.endswith(".html"):
        return [nodo.value]
    if isinstance(nodo, ast.Name) and modulo is not None:
        v = getattr(modulo, nodo.id, None)
        return [v] if isinstance(v, str) and v.endswith(".html") else []
    if isinstance(nodo, ast.Attribute):
        if isinstance(nodo.value, ast.Name) and modulo is not None:
            base = getattr(modulo, nodo.value.id, None)
            v = getattr(base, nodo.attr, None)
            if isinstance(v, str) and v.endswith(".html"):
                return [v]
        # `<algo>.template` sin base resoluble: es el contrato del chasis y su
        # dominio son los cuatro huecos.
        if nodo.attr == "template":
            return _plantillas_del_chasis()
    return []


def _renders(fn) -> list[ast.Call]:
    return [c for c in ast.walk(fn)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            and c.func.attr == "TemplateResponse"]


def _analizar() -> tuple[dict[str, set[str]], list[str]]:
    """``(plantilla -> {fichero::funcion}, renderizadores no clasificables)``."""
    nombres = sembradoras()
    arboles = _arboles()
    pintadas: dict[str, set[str]] = {}
    no_clasificables: list[str] = []

    for py, arbol in arboles.items():
        modulo = None
        for fn in _funciones(arbol):
            renders = _renders(fn)
            if not renders:
                continue
            if modulo is None:
                modulo = _modulo_importado(py)
            pinta = bool(_llamadas(fn) & nombres)
            for c in renders:
                candidatos = [
                    n
                    for a in list(c.args) + [k.value for k in c.keywords]
                    for n in _nombres_de_plantilla(a, modulo)
                ]
                resueltas = [n for n in candidatos
                             if (PLANTILLAS_DIR / n).is_file()]
                if not resueltas:
                    # FALLO CERRADO: no se sabe QUE se renderiza aqui, asi que
                    # tampoco se puede afirmar que no pinte nodos. Grita en vez
                    # de desaparecer del conjunto.
                    no_clasificables.append(
                        f"{py.relative_to(VIEWER_ROOT)}::{fn.name} (linea {c.lineno})")
                    continue
                if pinta:
                    for n in resueltas:
                        pintadas.setdefault(n, set()).add(f"{py.name}::{fn.name}")
    return pintadas, no_clasificables


def plantillas_que_pintan_nodos() -> dict[str, set[str]]:
    return _analizar()[0]


def renderizadores_no_clasificables() -> list[str]:
    return _analizar()[1]


# ---------------------------------------------------------------------------
# Salto 2: que consume cada plantilla
# ---------------------------------------------------------------------------

def atributos_de_plantilla(plantilla: str) -> set[str]:
    arbol = jinja2.Environment().parse(
        (PLANTILLAS_DIR / plantilla).read_text(encoding="utf-8"))
    out = set()
    for g in arbol.find_all(JN.Getattr):
        out.add(g.attr)
    for g in arbol.find_all(JN.Getitem):
        if isinstance(g.arg, JN.Const) and isinstance(g.arg.value, str):
            out.add(g.arg.value)
    return out


# ---------------------------------------------------------------------------
# Salto 3: de que propiedad de Neo4j sale cada atributo
# ---------------------------------------------------------------------------

def _lecturas(expr, var: str) -> set[str]:
    """`var.get("x")` y `var["x"]` dentro de una expresion."""
    out = set()
    for c in ast.walk(expr):
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) \
           and c.func.attr == "get" and isinstance(c.func.value, ast.Name) \
           and c.func.value.id == var and c.args and isinstance(c.args[0], ast.Constant):
            out.add(c.args[0].value)
        if isinstance(c, ast.Subscript) and isinstance(c.value, ast.Name) \
           and c.value.id == var and isinstance(c.slice, ast.Constant):
            out.add(c.slice.value)
    return out


def _dict_devuelto(ruta: Path, funcion: str, var: str) -> dict[str, set[str]]:
    """``clave del dict devuelto -> claves de entrada que la alimentan``.

    Resuelve tambien las variables locales (`technical`, `entity_type`, `name`,
    `confidence`) y las constantes de modulo en MAYUSCULAS con cadenas: asi
    `technical` se expande por `_NODE_TECHNICAL_FIELDS` de verdad y no por una
    copia escrita aqui.
    """
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(arbol)
              if isinstance(n, ast.FunctionDef) and n.name == funcion)
    ret = next(n for n in ast.walk(fn) if isinstance(n, ast.Return))
    assert isinstance(ret.value, ast.Dict), (
        f"{funcion} ya no devuelve un diccionario literal: la derivacion no "
        f"puede leerlo y esta prueba tiene que detenerse, no adivinar")
    modulo = _modulo_importado(ruta)
    locales: dict[str, set[str]] = {}
    for n in fn.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            leidas = _lecturas(n.value, var)
            for c in ast.walk(n.value):
                if isinstance(c, ast.Name) and c.id.upper() == c.id:
                    v = getattr(modulo, c.id, None)
                    if isinstance(v, (tuple, list, set, frozenset)) and \
                       all(isinstance(x, str) for x in v):
                        leidas |= set(v)
            locales[n.targets[0].id] = leidas
    mapa: dict[str, set[str]] = {}
    for k, v in zip(ret.value.keys, ret.value.values):
        leidas = _lecturas(v, var)
        for c in ast.walk(v):
            if isinstance(c, ast.Name) and c.id in locales:
                leidas |= locales[c.id]
        mapa[k.value] = leidas
    return mapa


def _propiedades_desde(pares) -> dict[str, set[tuple[str, str]]]:
    """``propiedad de Neo4j -> {(plantilla, atributo) que la consume}``.

    Se separa de `propiedades_neo4j_consumidas` para poder CALIBRAR la
    derivacion: se le pueden pasar pares inventados y comprobar que la cadena
    de composicion los sigue hasta la propiedad.
    """
    ser = _dict_devuelto(APP_DIR / "serializers.py", "serialize_node", "node")
    prov = _dict_devuelto(APP_DIR / "providers" / "neo4j_provider.py",
                          "_node_to_dict", "props")
    evidencia: dict[str, set[tuple[str, str]]] = {}
    for plantilla, attr in pares:
        for clave in ser.get(attr, ()):
            for prop in prov.get(clave, ()):
                evidencia.setdefault(prop, set()).add((plantilla, attr))
    return evidencia


def propiedades_neo4j_consumidas() -> dict[str, set[tuple[str, str]]]:
    return _propiedades_desde(
        (plantilla, attr)
        for plantilla in plantillas_que_pintan_nodos()
        for attr in atributos_de_plantilla(plantilla)
    )


# ---------------------------------------------------------------------------
# LA CLASIFICACION: la lista de campos se deriva, pero COMO se mide cada uno no
# ---------------------------------------------------------------------------
#: Cada propiedad dice DONDE se ablaciona. Esto NO es la lista de campos --esa
#: se deriva-- sino la respuesta a «¿como se mide este?», que es lo unico que no
#: se puede derivar: una ablacion necesita semilla con valor de ancla,
#: superficie donde observarse y DEGRADADO DECLARADO.
CAMPOS_CLASIFICADOS: dict[str, str] = {
    # Panel G (lista), tabla `ABLACIONES` del contrato.
    "canonical_name": "ABLACIONES:G",
    "entity_type": "ABLACIONES:G",
    "confidence": "ABLACIONES:G",
    "review_status": "ABLACIONES:G",
    "source_document": "ABLACIONES:G",
    "visibility": "ABLACIONES:G",
    "workspace": "ABLACIONES:G",
    # Panel F (fuentes), misma tabla.
    "source_kind": "ABLACIONES:F",
    # Ficha `/entity/{id}` (`entity.html`), tabla `ABLACIONES_FICHA`.
    "aliases": "ABLACIONES_FICHA",
    "source_pages": "ABLACIONES_FICHA",
    "description": "ABLACIONES_FICHA",
    "created_at": "ABLACIONES_FICHA",
    "updated_at": "ABLACIONES_FICHA",
    "extractor_version": "ABLACIONES_FICHA",
    "prompt_version": "ABLACIONES_FICHA",
    "source_hash": "ABLACIONES_FICHA",
    # Dos que no caben en ninguna tabla y tienen prueba propia, NOMBRADA:
    # `display_name` no esta sembrado (su respaldo es `canonical_name`), asi que
    # su ablacion necesita ponerlo primero; y quitar `entity_id` deja al nodo sin
    # la clave por la que `_quitar`/`_poner` lo encuentran.
    "display_name": "test:test_ablacion_de_display_name_devuelve_el_nombre_canonico",
    "entity_id": "test:test_ablacion_de_entity_id_retira_la_entidad_de_los_paneles",
}

#: Donde se OBSERVA cada clasificacion. Sirve para comprobar que la superficie
#: en la que se ablaciona un campo es una de las que lo CONSUMEN.
SUPERFICIE = {
    "ABLACIONES:G": {"chassis/entities.html", "chassis/entities_item.html"},
    "ABLACIONES:F": set(),   # el panel F agrega fuentes; su plantilla no pinta nodos
    "ABLACIONES_FICHA": {"entity.html"},
    "test:test_ablacion_de_display_name_devuelve_el_nombre_canonico": {"entity.html"},
    "test:test_ablacion_de_entity_id_retira_la_entidad_de_los_paneles":
        {"chassis/entities.html"},
}

#: Campos cubiertos en una superficie DISTINTA de la que los consume. No es un
#: defecto --el campo se ablaciona y enrojece-- pero si una asimetria que hay
#: que declarar: los dos se derivan EN EXCLUSIVA de `entity_detail.html`
#: (`/entities/{id}`) y se ablacionan en los paneles F/G, donde llegan por otra
#: via. El dia que `entity_detail.html` dejara de consumirlos, su ablacion
#: seguiria verde midiendo una pantalla que ya no los pinta; por eso se declara
#: aqui y una prueba comprueba que la lista es EXACTAMENTE esta.
SUPERFICIE_DISTINTA = {
    "source_kind": "solo lo consume entity_detail.html; se ablaciona en el panel F",
    "workspace": "solo lo consume entity_detail.html; se ablaciona en el panel G",
}


# ===========================================================================
# Las guardas. TODAS son AST puro: corren sin Neo4j y sin Docker.
# ===========================================================================

def test_la_lista_de_campos_se_DERIVA_de_las_plantillas():
    """LA PIEZA CENTRAL DEL CARRIL. Si una plantilla empieza a consumir un campo
    nuevo, esto se pone ROJO hasta que alguien decida COMO se ablaciona.

    Y al reves: si un campo deja de consumirse, sobra de la clasificacion y
    tambien enrojece -- una ablacion de algo que ya nadie pinta es una prueba
    que mide una pantalla que no existe. Esa segunda asercion es la que cubre
    `entity_detail.html` (ver la nota sobre las dos redes en la cabecera).
    """
    derivadas = propiedades_neo4j_consumidas()
    assert derivadas, (
        "la derivacion no encontro NI UN campo: la cadena plantilla -> "
        "serializador -> proveedor se ha roto y esta guarda estaria muda")

    faltan = set(derivadas) - set(CAMPOS_CLASIFICADOS)
    assert not faltan, (
        "campos que una plantilla CONSUME y nadie ablaciona: "
        + ", ".join(f"{c} (lo pinta {sorted(derivadas[c])[0]})" for c in sorted(faltan))
        + ". Clasificalos en CAMPOS_CLASIFICADOS y anadeles su ablacion: esta "
        "parada es el coste declarado de no mantener la lista a mano.")

    sobran = set(CAMPOS_CLASIFICADOS) - set(derivadas)
    assert not sobran, (
        f"campos clasificados que ninguna plantilla consume ya: {sorted(sobran)}")


def test_cada_campo_clasificado_tiene_su_ablacion_DE_VERDAD():
    """La clasificacion no puede ser una etiqueta: cada campo tiene que aparecer
    donde dice aparecer. Sin esto, poner `"loquesea": "ABLACIONES:G"` silenciaria
    la guarda de arriba sin medir nada.

    Se importan las tablas del contrato de paneles. Ese modulo se SALTA sin
    Neo4j, pero IMPORTARLO no ejecuta ninguna prueba ni abre ninguna conexion:
    el `skipif` es de coleccion, no de importacion.
    """
    from test_contrato_paneles_neo4j import ABLACIONES, ABLACIONES_FICHA
    import test_contrato_paneles_neo4j as contrato

    en_g = {c for c, _, p, _ in ABLACIONES if p == "G"}
    en_f = {c for c, _, p, _ in ABLACIONES if p == "F"}
    en_ficha = {c for c, _, _ in ABLACIONES_FICHA}

    for campo, donde in sorted(CAMPOS_CLASIFICADOS.items()):
        if donde == "ABLACIONES:G":
            assert campo in en_g, f"`{campo}` se declara en el panel G y no esta en ABLACIONES"
        elif donde == "ABLACIONES:F":
            assert campo in en_f, f"`{campo}` se declara en el panel F y no esta en ABLACIONES"
        elif donde == "ABLACIONES_FICHA":
            assert campo in en_ficha, f"`{campo}` no esta en ABLACIONES_FICHA"
        elif donde.startswith("test:"):
            nombre = donde.split(":", 1)[1]
            assert callable(getattr(contrato, nombre, None)), (
                f"`{campo}` dice medirse en `{nombre}`, que no existe en el contrato")
        else:
            raise AssertionError(f"clasificacion desconocida para `{campo}`: {donde!r}")


def test_la_superficie_de_cada_ablacion_es_una_que_CONSUME_el_campo():
    """Arreglo 4 del revisor. Un campo puede estar cubierto y aun asi medirse en
    una pantalla distinta de la que lo declara. Eso no es un defecto, pero no
    puede quedar implicito: la lista de asimetrias se COMPARA con la calculada.
    """
    derivadas = propiedades_neo4j_consumidas()
    distintas = {}
    for campo, donde in CAMPOS_CLASIFICADOS.items():
        consumidoras = {plantilla for plantilla, _ in derivadas.get(campo, ())}
        if not (consumidoras & SUPERFICIE[donde]):
            distintas[campo] = sorted(consumidoras)

    assert set(distintas) == set(SUPERFICIE_DISTINTA), (
        f"la asimetria superficie/consumo ha cambiado: calculada={sorted(distintas)}, "
        f"declarada={sorted(SUPERFICIE_DISTINTA)}. Detalle: {distintas}")
    for campo in distintas:
        assert distintas[campo] == ["entity_detail.html"], (
            f"`{campo}` ya no se consume solo en entity_detail.html: {distintas[campo]}")


def test_no_hay_renderizadores_NO_CLASIFICABLES():
    """FALLO CERRADO. Una funcion que renderiza una plantilla cuyo nombre no se
    puede resolver (f-string, `DIC['k']`, concatenacion) no puede declararse «no
    pinta nodos»: nadie sabe que renderiza. Antes desaparecia del conjunto en
    silencio; ahora sale aqui y esto se pone ROJO.

    Coste medido: hoy la lista esta VACIA sobre los 51 puntos de render de
    `viewer/app`, asi que el fallo cerrado no cuesta ni un falso positivo.
    """
    sueltos = renderizadores_no_clasificables()
    assert not sueltos, (
        "pintor-no-clasificable: estas funciones renderizan una plantilla que no "
        "se puede resolver estaticamente, asi que no se puede afirmar que no "
        "pinten nodos: " + ", ".join(sueltos) + ". Usa un literal, una constante "
        "de modulo o un atributo del contrato del chasis.")


def test_el_fallo_cerrado_MUERDE():
    """Calibracion del anterior: un render con nombre no resoluble TIENE que
    aparecer en la lista. Se comprueba sobre codigo sintetico --no se toca
    `viewer/app`-- ejercitando las mismas funciones de analisis.
    """
    fuente = (
        "def pinta(request, n, k):\n"
        "    ctx = {'entity': serialize_node(n)}\n"
        "    return templates.TemplateResponse(request, f'x{k}.html', ctx)\n"
    )
    fn = next(_funciones(ast.parse(fuente)))
    renders = _renders(fn)
    assert len(renders) == 1, "el analizador ya no reconoce un render"
    assert _llamadas(fn) & sembradoras(), (
        "el analizador ya no reconoce a un pintor que llama a serialize_node")
    candidatos = [n for a in renders[0].args
                  for n in _nombres_de_plantilla(a, None)]
    assert not candidatos, (
        "una f-string NO puede resolverse a un nombre de plantilla; si esto pasa, "
        "el fallo cerrado estaria clasificando lo que no puede leer")


def test_el_descubrimiento_de_pintores_ve_las_formas_INDIRECTAS():
    """Calibracion del punto fijo. Las tres formas que la primera version no
    veia --atributo de modulo, alias de importacion y delegacion en un helper--
    tienen que contar como «pinta nodos».
    """
    nombres = sembradoras()

    # (a) por atributo: `serializers.serialize_node(n)`
    a = next(_funciones(ast.parse(
        "def f(n):\n    return serializers.serialize_node(n)\n")))
    assert _llamadas(a) & nombres

    # (b) por alias de importacion, resuelto en el modulo real
    alias = _alias_de_la_semilla(ast.parse(
        "from app.serializers import serialize_node as sn\n"))
    assert "sn" in alias

    # (c) por delegacion: el helper real `_with_other` de readonly.py serializa,
    #     asi que quien lo llame cuenta como pintor. Se comprueba sobre el
    #     codigo REAL, no sobre un ejemplo.
    assert "_with_other" in nombres, (
        "el punto fijo no marco un helper que serializa: la delegacion volveria "
        "a esconder pintores")


def test_la_derivacion_MUERDE():
    """CALIBRACION DE LA DERIVACION. Un derivador que no reacciona a un campo
    nuevo seria la lista a mano otra vez, con mas lineas.

    Se le pasa un par inventado --una plantilla ficticia que consumiria
    `knowledge_layer`, que HOY ninguna pinta (`entity.html` lo omite a
    proposito)-- y se exige (a) que la cadena lo siga hasta la propiedad de
    Neo4j y (b) que ese campo NO este clasificado, es decir, que la guarda se
    habria puesto roja.
    """
    inventado = _propiedades_desde([("ficticia.html", "knowledge_layer_label")])
    assert "knowledge_layer" in inventado, (
        "la composicion serializador->proveedor no sigue un atributo nuevo: la "
        "derivacion no derivaria nada")
    assert "knowledge_layer" not in CAMPOS_CLASIFICADOS, (
        "el ejemplo de calibracion ya esta clasificado; hace falta otro campo "
        "consumible que hoy no se pinte")

    derivadas = dict(propiedades_neo4j_consumidas())
    derivadas.update(inventado)
    faltan = set(derivadas) - set(CAMPOS_CLASIFICADOS)
    assert faltan == {"knowledge_layer"}, (
        f"con un campo nuevo consumido, la guarda tendria que senalarlo a el y "
        f"solo a el; senala {sorted(faltan)}")


def test_las_plantillas_que_pintan_nodos_se_ENCUENTRAN_solas():
    """Suelo del descubrimiento, y PRIMERA de las dos redes (ver cabecera).

    Ancla por nombre las cuatro plantillas cuya perdida NO cambiaria la lista
    de 18 propiedades por redundancia. La quinta y sexta las cubre la asercion
    `sobran` de la guarda principal.
    """
    encontradas = plantillas_que_pintan_nodos()
    from test_contrato_paneles_neo4j import SLOT_G

    assert SLOT_G.template in encontradas, (
        "el panel G no se descubrio: su plantilla llega por el contrato del "
        "chasis (`SLOT.template`), no como literal, y resolverla es justo lo que "
        "hace que este carril no sea una lista escrita a mano")
    for esperada in ("entity.html", "entities.html", "chassis/entities_item.html",
                     "entity_detail.html"):
        assert esperada in encontradas, f"no se descubrio {esperada}"
    for plantilla, funciones in encontradas.items():
        assert funciones, f"{plantilla} descubierta sin funcion que la pinte"


@pytest.mark.parametrize("plantilla", ["entity.html", "entities.html",
                                       "chassis/entities.html",
                                       "chassis/entities_item.html",
                                       "entity_detail.html"])
def test_cada_plantilla_que_pinta_nodos_aporta_algun_campo(plantilla):
    """Ninguna de las cinco esta en el conjunto de adorno: cada una aporta al
    menos una propiedad. Una plantilla descubierta que no aporta nada seria una
    deteccion falsa y engordaria el suelo sin cubrir nada.
    """
    aporta = _propiedades_desde(
        (plantilla, attr) for attr in atributos_de_plantilla(plantilla))
    assert aporta, f"{plantilla} no aporta ninguna propiedad de Neo4j"
