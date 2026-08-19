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

FALLO CERRADO ANTE UN PINTOR NUEVO: LOS DOS LADOS
=================================================
Un pintor puede escaparse por dos sitios, y hay que cerrar LOS DOS. La primera
version solo cerro uno, y el revisor lo midio con un pintor escrito con
``functools.partial``::

    partial -> pintadas={}   no_clasificables=[]

El pintor DESAPARECIA sin gritar: el nombre de la plantilla si resolvia, asi
que el unico fallo cerrado que habia no se activaba, y como el sembrado no se
reconocia, la funcion se descartaba en silencio. Un caso silencioso, no
ruidoso, que es exactamente el defecto que este fichero existe para impedir.

* **Lado A -- la plantilla.** Una funcion que renderiza un nombre que no se
  puede resolver ni acotar sale como no clasificable.
* **Lado B -- el sembrado.** Una funcion que renderiza y NO se reconoce como
  pintora, pero en la que ha quedado algo sin resolver, sale TAMBIEN como no
  clasificable. La respuesta honesta ahi no es «no pinta»: es «no lo se».

LA CLASE, NO LAS INSTANCIAS
---------------------------
La primera version de esta seccion enumeraba nueve formas y afirmaba «ningun
pintor desaparece en silencio». Era FALSO, y el revisor lo midio: encontro SEIS
que ni se reconocian ni se denunciaban (`sn: Callable = serialize_node`,
`a, b = serialize_node, None`, `def v(..., ser=serialize_node)`,
`self.ser = serialize_node`, `(sn := serialize_node)`,
`for f in (serialize_node,)`). Causa raiz UNICA: el punto fijo solo propagaba
por `Assign` simple con un destino `Name`, asi que cualquier otra ligadura
REBAUTIZABA la sembradora bajo un nombre desconocido -- y la llamada resultante
si era `Name`/`Attribute`, de modo que el motivo de «invocado irresoluble»
tampoco saltaba. Una garantia enumerada vale para lo enumerado: eso no es una
garantia, es una lista.

Se cierra la CLASE con una regla, no con diez parches. Para que una sembradora
llegue a un pintor solo hay dos caminos:

* **se la llama** -- `serialize_node(n)`, `mod.serialize_node(n)`, un alias, un
  helper (punto fijo transitivo entre modulos), un helper RENOMBRADO al
  importarlo, un `partial(sn)`: RECONOCIDO;
* **se la menciona sin llamarla** (posicion de valor) para bautizarla con otro
  nombre: eso es precisamente lo que el analisis no puede seguir, y por eso es
  MOTIVO. No importa la sintaxis de la ligadura -- anotada, desempaquetada, por
  defecto, atributo, walrus, bucle, lista, retorno, argumento, dict--: todas
  pasan por una mencion en posicion de valor.

Y lo que no es ninguna de las dos (dict-dispatch, `(lambda...)()`, `f()()`) cae
en «invocado irresoluble», que tambien es motivo.

`FORMAS_DE_PINTOR` ejerce VEINTE formas: 8 reconocidas y 12 denunciadas.
Ninguna desaparece. La afirmacion que se sostiene es esa: **una sembradora o se
llama --y se reconoce-- o se menciona --y se denuncia--**; no que hayamos
imaginado todas las sintaxis posibles.

COLISION DE NOMBRES: el precio, medido y pagado
-----------------------------------------------
Cerrar la clase saco a la luz la cara fea del emparejamiento por nombre:
`app/main.py` importa `from app.api import entities as api_entities`, y
`api_entities` es tambien el nombre de una funcion de `readonly.py` que
serializa. Eso produjo OCHO falsos positivos de golpe. Se cierra con la
semantica de Python, no con una excepcion: un nombre ligado aqui por un import
cuyo ORIGEN no es una sembradora no es, en este modulo, la sembradora homonima
de otro fichero (`importados_ajenos`); y al reves, un import cuyo origen SI lo
es liga su nombre local como sembradora (`alias_locales_de_sembradoras`). Con
las dos, los falsos positivos vuelven a CERO.

COTA QUE QUEDA
--------------
El emparejamiento sigue siendo por NOMBRE, no por resolucion completa de
imports. Con los dos filtros de arriba las colisiones conocidas estan cubiertas,
pero un caso patologico (dos funciones homonimas, una sembradora y otra no, sin
import de por medio) denunciaria de mas. Es una cota de PRECISION -- puede
gritar sin motivo -- no de SILENCIO.

ENSANCHAR SOLO DONDE CONSTA EL TIPO
-----------------------------------
``chassis_slot.py`` renderiza ``slot.template`` con ``slot`` como PARAMETRO: una
linea que sirve las cuatro pantallas de hueco. Ahi se toman las CUATRO
plantillas del chasis... **pero solo porque el parametro esta ANOTADO como
``FeatureSlot``** (la anotacion se busca tambien en los ambitos externos, que es
donde vive: el render esta en el cierre ``slot_screen``).

La cautela es del revisor y hay que decirla con sus palabras: de los 11 renders
de ``<x>.template`` de ``viewer/app``, 10 tienen base resoluble y solo ese es
irresoluble, y ahi ``pinta=False``, asi que **el ensanchamiento no aporta hoy ni
una plantilla**. Sin atarlo al tipo, su unico efecto seria evitar que esa linea
saliera como no clasificable --funcionalmente una EXENCION-- y, peor, cualquier
futuro ``x.template`` que NO fuera del chasis se le atribuiria en vez de gritar:
ahi ensanchar no «solo sobra», **SUSTITUYE**. Con la anotacion exigida, un
``x.template`` sin tipo declarado no se ensancha: se denuncia.

COTA QUE QUEDA (declarada, y ahora RUIDOSA)
------------------------------------------
El punto fijo empareja por NOMBRE de funcion, no por resolucion completa de
imports: un helper importado con ``as`` bajo otro nombre en cada modulo seguiria
sin reconocerse COMO PINTOR. Lo que ya no ocurre es que se pierda en silencio:
si esa funcion renderiza y su sembrado no se resuelve, cae en el lado B. La cota
que queda es de PRECISION (puede denunciar de mas), no de SILENCIO.

COSTE MEDIDO de los dos fallos cerrados: sobre los 51 puntos de render de
``viewer/app``, ``renderizadores_no_clasificables()`` esta VACIO. Cero falsos
positivos y ninguna exencion escrita a mano.

MIS PROPIOS CONTROLES, ABLACIONADOS
-----------------------------------
Quitar el lado B (``if not pinta and motivos`` -> ``if False``): **2 failed**.
Quitar la atadura del ensanchamiento a la anotacion: **1 failed**. Los dos son
load-bearing; medido con reversion por SHA-256.

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


def importados_ajenos(arbol: ast.AST, conocidas: set[str]) -> set[str]:
    """Nombres que en ESTE modulo estan ligados por un `import` a OTRA cosa.

    El emparejamiento por nombre tiene una cara fea y medida: `app/main.py`
    importa `from app.api import entities as api_entities`, y resulta que
    `api_entities` es TAMBIEN el nombre de una funcion de `readonly.py` que
    serializa. Sin este filtro, ocho renderizadores de `main.py` salian como no
    clasificables por una colision de nombres: ocho falsos positivos.

    La regla es la semantica de Python, no una excepcion: si el nombre esta
    ligado aqui por un import cuyo ORIGEN no es una sembradora, en este modulo
    ese nombre NO es la sembradora homonima de otro fichero.
    """
    ajenos = set()
    for n in ast.walk(arbol):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                ligado = a.asname or a.name.split(".")[0]
                origen = a.name.split(".")[-1]
                if origen not in conocidas:
                    ajenos.add(ligado)
    return ajenos


def alias_locales_de_sembradoras(arbol: ast.AST, conocidas: set[str]) -> set[str]:
    """La otra mitad del import: `from otro import helper as h` con `helper`
    sembradora liga `h` a una sembradora EN ESTE MODULO.

    Sin esto, `h(n)` no se reconocia (el nombre local no esta en el conjunto) y
    tampoco se denunciaba (importar no es mencionar en posicion de valor): otro
    caso silencioso, esta vez a traves de modulos.
    """
    out = set()
    for n in ast.walk(arbol):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name.split(".")[-1] in conocidas:
                    out.add(a.asname or a.name.split(".")[0])
    return out


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


#: Nombres que envuelven una funcion sin llamarla: `partial(f)` es `f` diferido.
_ENVOLTORIOS = {"partial", "singledispatch", "wraps", "lru_cache", "cache"}


def _expandir(nodo: ast.AST, sembradoras_: set[str],
              impostores: frozenset[str] = frozenset()) -> tuple[set[str], list[str]]:
    """``(siembra, motivos por los que NO se puede afirmar que no siembre)``.

    ESTE ES EL AGUJERO QUE CIERRA (revision de `9217381`)
    ------------------------------------------------------
    La version anterior contestaba con un `bool` y punto: si no reconocia la
    llamada, la funcion se descartaba EN SILENCIO. Medido por el revisor con un
    pintor escrito con `functools.partial`::

        partial -> pintadas={}   no_clasificables=[]

    El pintor desaparecia sin gritar. El fallo cerrado de entonces solo cubria
    «no se que plantilla renderiza»; este cubre el otro lado, «no se si
    siembra», que es el que producia casos SILENCIOSOS en vez de ruidosos.

    Devuelve motivos --no un `bool`-- para que quien no se pueda clasificar
    acabe en `renderizadores_no_clasificables()` y ponga un test ROJO:

    * **alias encadenado** (`sn2 = sn`): se RESUELVE, propagando por
      asignaciones `Name = Name` hasta punto fijo.
    * **envoltorio** (`partial(sn)`): se RESUELVE si el argumento es un nombre;
      si no lo es, es motivo de no clasificable.
    * **dict-dispatch** (`FUNCS['s'](x)`): NO se puede resolver, y por eso es
      motivo. Cualquier llamada cuyo invocado no sea `Name` ni `Attribute`
      cuenta igual: `(lambda...)()`, `f()()`, `objs[i].m()`.
    """
    motivos: list[str] = []

    # (a) alias encadenados y envoltorios, por punto fijo dentro de este ambito.
    locales: set[str] = set()
    cambio = True
    while cambio:
        cambio = False
        for a in ast.walk(nodo):
            if not (isinstance(a, ast.Assign) and len(a.targets) == 1
                    and isinstance(a.targets[0], ast.Name)):
                continue
            destino = a.targets[0].id
            if destino in locales:
                continue
            v = a.value
            origen = None
            if isinstance(v, (ast.Name, ast.Attribute)):
                origen = v.id if isinstance(v, ast.Name) else v.attr
            elif isinstance(v, ast.Call) and _nombre_llamado(v) in _ENVOLTORIOS:
                primero = v.args[0] if v.args else None
                if isinstance(primero, (ast.Name, ast.Attribute)):
                    origen = (primero.id if isinstance(primero, ast.Name)
                              else primero.attr)
                else:
                    motivos.append(
                        f"envoltorio `{_nombre_llamado(v)}` sobre algo que no es "
                        f"un nombre (linea {v.lineno})")
                    continue
            if origen and (origen in sembradoras_ or origen in locales):
                locales.add(destino)
                cambio = True
    # (b) invocados irresolubles: no se puede afirmar que NO siembren.
    for c in ast.walk(nodo):
        if isinstance(c, ast.Call) and not isinstance(c.func, (ast.Name, ast.Attribute)):
            motivos.append(
                f"invocado irresoluble `{type(c.func).__name__}` (linea {c.lineno})")

    # (c) LA CLASE, no nueve instancias: una sembradora en POSICION DE VALOR.
    #
    # El arreglo de (a) solo propaga por `Assign` simple con UN destino `Name`.
    # Cualquier otra ligadura --`sn: Callable = serialize_node`, `a, b =
    # serialize_node, None`, `def v(..., ser=serialize_node)`, `self.ser =
    # serialize_node`, `(sn := serialize_node)`, `for f in (serialize_node,)`--
    # REBAUTIZA la sembradora bajo un nombre desconocido, y la llamada que
    # sigue SI es `Name`/`Attribute`, asi que (b) tampoco salta. Resultado: el
    # pintor desaparecia, otra vez, en silencio.
    #
    # La regla general: si una sembradora se MENCIONA sin llamarla (posicion de
    # valor) y esa mencion no es una de las ligaduras que (a) resolvio, entonces
    # se ha bautizado algo que no sabemos seguir. Eso es motivo. No enumera
    # formas: enumera el UNICO sitio por el que la clase entera se escapa.
    conocidas = sembradoras_ | locales
    padre = {}
    for n in ast.walk(nodo):
        for h in ast.iter_child_nodes(n):
            padre[h] = n

    for n in ast.walk(nodo):
        if isinstance(n, ast.Name):
            bare = n.id
        elif isinstance(n, ast.Attribute):
            bare = n.attr
        else:
            continue
        if bare not in conocidas or bare in impostores:
            continue
        p = padre.get(n)
        # invocarla no la rebautiza: `serialize_node(x)`, `mod.serialize_node(x)`
        if isinstance(p, ast.Call) and p.func is n:
            continue
        # la ligadura que (a) SI resolvio: `sn2 = sn`, `pintar = partial(sn)`
        if isinstance(p, ast.Assign) and p.value is n \
           and len(p.targets) == 1 and isinstance(p.targets[0], ast.Name) \
           and p.targets[0].id in locales:
            continue
        if isinstance(p, ast.Call) and _nombre_llamado(p) in _ENVOLTORIOS:
            abuelo = padre.get(p)
            if isinstance(abuelo, ast.Assign) and len(abuelo.targets) == 1 \
               and isinstance(abuelo.targets[0], ast.Name) \
               and abuelo.targets[0].id in locales:
                continue
        # importarla tampoco: el alias ya se resolvio en `_alias_de_la_semilla`
        if isinstance(p, (ast.ImportFrom, ast.Import, ast.alias)):
            continue
        motivos.append(
            f"sembradora `{bare}` en POSICION DE VALOR sin resolver, dentro de "
            f"`{type(p).__name__}` (linea {getattr(n, 'lineno', '?')})")

    return conocidas, motivos


def _sembrado(nodo: ast.AST, sembradoras_: set[str],
              impostores: frozenset[str] = frozenset()) -> tuple[bool, list[str]]:
    """``(siembra, motivos)`` para UNA funcion, con los nombres ya extendidos."""
    nombres, motivos = _expandir(nodo, sembradoras_, impostores)
    return bool((_llamadas(nodo) - impostores) & nombres), motivos


def _anotaciones(pila) -> dict[str, str]:
    """``parametro -> nombre del tipo anotado``, incluidos los ambitos externos.

    Hace falta el ambito externo porque el caso real vive en un cierre:
    `build_slot_router(slot: FeatureSlot)` define `slot` y la anotacion, y quien
    renderiza es la funcion interna `slot_screen`.
    """
    out: dict[str, str] = {}
    for fn in pila:
        args = fn.args
        for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            if isinstance(a.annotation, ast.Name):
                out[a.arg] = a.annotation.id
            elif isinstance(a.annotation, ast.Attribute):
                out[a.arg] = a.annotation.attr
    return out


def _funciones_con_pila(nodo, pila=()):
    """Cada funcion con la PILA de funciones que la contienen."""
    for hijo in ast.iter_child_nodes(nodo):
        if isinstance(hijo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield hijo, pila + (hijo,)
            yield from _funciones_con_pila(hijo, pila + (hijo,))
        else:
            yield from _funciones_con_pila(hijo, pila)


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


def _nombres_de_plantilla(nodo, modulo, anotaciones=None) -> list[str]:
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
        # `<x>.template` con `x` ANOTADO como `FeatureSlot`: el valor no se puede
        # fijar pero el DOMINIO si, y son los cuatro huecos. El ensanchamiento va
        # ATADO A LA ANOTACION a proposito (ver la nota «ENSANCHAR SOLO DONDE
        # CONSTA EL TIPO» en la cabecera): sin ella, un `x.template` de otra cosa
        # se atribuiria al chasis en vez de gritar, y ensanchar dejaria de
        # «sobrar» para pasar a SUSTITUIR.
        if nodo.attr == "template" and isinstance(nodo.value, ast.Name) \
           and (anotaciones or {}).get(nodo.value.id) == "FeatureSlot":
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
        p, nc = _analizar_arbol(arbol, nombres, py.relative_to(VIEWER_ROOT),
                                lambda py=py: _modulo_importado(py))
        for k, v in p.items():
            pintadas.setdefault(k, set()).update(v)
        no_clasificables.extend(nc)
    return pintadas, no_clasificables


def _analizar_arbol(arbol, nombres, ruta, dame_modulo):
    """El analisis de UN arbol. Se separa para poder CALIBRARLO con codigo
    sintetico: es la unica forma de demostrar que un pintor escrito con
    `partial` o con dict-dispatch enrojece en vez de desaparecer."""
    pintadas: dict[str, set[str]] = {}
    no_clasificables: list[str] = []
    modulo = None
    # Los alias de ESTE modulo y los encadenados de su ambito global: `sn2 = sn`
    # vive fuera de la funcion que lo usa, asi que mirar solo dentro de la
    # funcion lo perdia -- y perderlo era, otra vez, un pintor en silencio.
    base = nombres | _alias_de_la_semilla(arbol)
    base |= alias_locales_de_sembradoras(arbol, base)
    impostores = frozenset(importados_ajenos(arbol, base))
    nombres, motivos_modulo = _expandir(arbol, base, impostores)
    for fn, pila in _funciones_con_pila(arbol):
        renders = _renders(fn)
        if not renders:
            continue
        if modulo is None:
            modulo = dame_modulo()
        donde = f"{ruta}::{fn.name}"
        anot = _anotaciones(pila)
        pinta, motivos = _sembrado(fn, nombres, impostores)
        # Los motivos del AMBITO DE MODULO cuentan para toda funcion que
        # renderice: `sn: Callable = serialize_node` o `self.ser =
        # serialize_node` ligan la sembradora FUERA de la funcion que pinta.
        # Esta linea se perdio en una refactorizacion y dejo cuatro de las
        # seis formas del revisor otra vez SILENCIOSAS: sin ella, la regla
        # de posicion de valor se calcula y no se usa.
        motivos = motivos + motivos_modulo

        for c in renders:
            candidatos = [
                n
                for a in list(c.args) + [k.value for k in c.keywords]
                for n in _nombres_de_plantilla(a, modulo, anot)
            ]
            resueltas = [n for n in candidatos
                         if (PLANTILLAS_DIR / n).is_file()]
            if not resueltas:
                # FALLO CERRADO (1): no se sabe QUE se renderiza aqui, asi
                # que tampoco se puede afirmar que no pinte nodos.
                no_clasificables.append(
                    f"{donde}: plantilla irresoluble (linea {c.lineno})")
                continue
            if pinta:
                for n in resueltas:
                    pintadas.setdefault(n, set()).add(
                        f"{Path(str(ruta)).name}::{fn.name}")

        # FALLO CERRADO (2): el sembrado. Si la funcion NO se reconoce como
        # pintora pero hay algo que no se ha podido resolver, la respuesta
        # honesta no es «no pinta»: es «no lo se». Sin esto, un pintor
        # escrito con `partial` o con dict-dispatch DESAPARECIA en silencio
        # -- medido: `partial -> pintadas={} no_clasificables=[]`.
        if not pinta and motivos:
            no_clasificables.append(f"{donde}: sembrado sin resolver -- "
                                    + "; ".join(sorted(set(motivos))))
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


#: Las SIETE formas con las que el revisor atacó el descubrimiento sobre
#: `9217381`. Cada una es un modulo sintetico que pinta `entity.html` -- el
#: nombre de la plantilla SI resuelve en todas, que es lo que hacia peligrosas a
#: las tres ultimas: al no reconocerse el sembrado, la funcion se descartaba en
#: SILENCIO en vez de gritar.
#:
#: `esperado` es lo unico que se admite: o se RECONOCE como pintora, o sale como
#: NO CLASIFICABLE. Lo que ninguna puede hacer es desaparecer.
FORMAS_DE_PINTOR = (
    ("directa", "reconocida", """
from app.serializers import serialize_node
def v(request, n):
    return templates.TemplateResponse(request, "entity.html", {"e": serialize_node(n)})
"""),
    ("alias de importacion", "reconocida", """
from app.serializers import serialize_node as sn
def v(request, n):
    return templates.TemplateResponse(request, "entity.html", {"e": sn(n)})
"""),
    ("por atributo", "reconocida", """
from app import serializers
def v(request, n):
    return templates.TemplateResponse(request, "entity.html", {"e": serializers.serialize_node(n)})
"""),
    ("helper de otro modulo", "reconocida", """
from app.routers.readonly import _with_other
def v(request, e):
    return templates.TemplateResponse(request, "entity.html", {"e": _with_other(e, "to")})
"""),
    ("bajo condicional", "reconocida", """
from app.serializers import serialize_node
def v(request, n, quiere):
    ctx = {}
    if quiere:
        ctx["e"] = serialize_node(n)
    return templates.TemplateResponse(request, "entity.html", ctx)
"""),
    ("alias encadenado", "reconocida", """
from app.serializers import serialize_node as sn
sn2 = sn
def v(request, n):
    return templates.TemplateResponse(request, "entity.html", {"e": sn2(n)})
"""),
    ("envoltorio partial", "reconocida", """
from functools import partial
from app.serializers import serialize_node
pintar = partial(serialize_node)
def v(request, n):
    return templates.TemplateResponse(request, "entity.html", {"e": pintar(n)})
"""),
    ("helper renombrado al importar", "reconocida", """
from app.routers.readonly import _with_other as h
def v(request, e):
    return templates.TemplateResponse(request, "entity.html", {"e": h(e, "to")})
"""),
    ("dict-dispatch", "no clasificable", """
from app.serializers import serialize_node
FUNCS = {"s": serialize_node}
def v(request, n):
    return templates.TemplateResponse(request, "entity.html", {"e": FUNCS["s"](n)})
"""),
    ("envoltorio sobre algo que no es un nombre", "no clasificable", """
from functools import partial
FUNCS = {"s": None}
def v(request, n):
    pintar = partial(FUNCS["s"])
    return templates.TemplateResponse(request, "entity.html", {"e": pintar(n)})
"""),
    # --- LIGADURAS FUERA DE `Assign` SIMPLE. Las seis del revisor mas cuatro
    #     propias. Todas comparten causa raiz: rebautizan la sembradora bajo un
    #     nombre que el punto fijo no sigue, y la llamada resultante SI es
    #     `Name`/`Attribute`, asi que el motivo de «invocado irresoluble»
    #     tampoco saltaba. Las diez se DENUNCIAN por la regla de POSICION DE
    #     VALOR, que ataca la clase entera y no diez instancias.
    ("AnnAssign", "no clasificable", """
from typing import Callable
from app.serializers import serialize_node
sn: Callable = serialize_node
def v(request, n):
    return templates.TemplateResponse(request, "entity.html", {"e": sn(n)})
"""),
    ("desempaquetado", "no clasificable", """
from app.serializers import serialize_node
a, b = serialize_node, None
def v(request, n):
    return templates.TemplateResponse(request, "entity.html", {"e": a(n)})
"""),
    ("argumento por defecto", "no clasificable", """
from app.serializers import serialize_node
def v(request, n, ser=serialize_node):
    return templates.TemplateResponse(request, "entity.html", {"e": ser(n)})
"""),
    ("atributo de instancia", "no clasificable", """
from app.serializers import serialize_node
class V:
    def __init__(self):
        self.ser = serialize_node
    def v(self, request, n):
        return templates.TemplateResponse(request, "entity.html", {"e": self.ser(n)})
"""),
    ("walrus", "no clasificable", """
from app.serializers import serialize_node
def v(request, n):
    return templates.TemplateResponse(request, "entity.html", {"e": (sn := serialize_node)(n)})
"""),
    ("bucle sobre una tupla", "no clasificable", """
from app.serializers import serialize_node
def v(request, n):
    ctx = {}
    for f in (serialize_node,):
        ctx["e"] = f(n)
    return templates.TemplateResponse(request, "entity.html", ctx)
"""),
    ("lista de pintores", "no clasificable", """
from app.serializers import serialize_node
PINTORES = [serialize_node]
def v(request, n):
    return templates.TemplateResponse(request, "entity.html", {"e": PINTORES[0](n)})
"""),
    ("devuelta por otra funcion", "no clasificable", """
from app.serializers import serialize_node
def dame():
    return serialize_node
def v(request, n):
    f = dame()
    return templates.TemplateResponse(request, "entity.html", {"e": f(n)})
"""),
    ("pasada como argumento", "no clasificable", """
from app.serializers import serialize_node
def v(request, n):
    ctx = aplicar(serialize_node, n)
    return templates.TemplateResponse(request, "entity.html", ctx)
"""),
    ("dentro de un dict literal", "no clasificable", """
from app.serializers import serialize_node
def v(request, n):
    d = {"s": serialize_node}
    return templates.TemplateResponse(request, "entity.html", {"e": d["s"](n)})
"""),
)


@pytest.mark.parametrize("nombre,esperado,fuente", FORMAS_DE_PINTOR,
                         ids=[n for n, _, _ in FORMAS_DE_PINTOR])
def test_ningun_pintor_DESAPARECE_en_silencio(nombre, esperado, fuente):
    """EL ARREGLO DE FONDO. Medido por el revisor sobre `9217381`::

        partial -> pintadas={}   no_clasificables=[]

    Un pintor que no se reconoce y tampoco se denuncia es un campo sin ablacion
    y sin nadie que enrojezca: el mismo defecto que este carril existe para
    impedir, un nivel mas arriba. Aqui se exige que CADA forma acabe en uno de
    los dos cajones honestos -- reconocida o no clasificable -- y NUNCA en el
    tercero, que es el silencio.
    """
    pintadas, sueltos = _analizar_arbol(
        ast.parse(fuente), sembradoras(), Path("sintetico.py"), lambda: None)

    if esperado == "reconocida":
        assert "entity.html" in pintadas, (
            f"la forma «{nombre}» NO se reconoce como pintora y TAMPOCO sale "
            f"como no clasificable: {sueltos}. Desaparece en silencio.")
        assert not sueltos, f"reconocida y ademas denunciada: {sueltos}"
    else:
        assert "entity.html" not in pintadas
        assert sueltos, (
            f"la forma «{nombre}» ni se reconoce ni se denuncia: DESAPARECE en "
            f"silencio, que es exactamente el defecto que este control cierra")

    # En los dos casos hay respuesta. El silencio se comprueba explicitamente.
    assert pintadas or sueltos, f"la forma «{nombre}» no produjo NINGUNA respuesta"


def test_el_recuento_de_la_cabecera_no_puede_MENTIR():
    """La cabecera dice cuantas formas se ejercen y como se reparten. Un numero
    escrito a mano se queda viejo en cuanto alguien anade una forma, y entonces
    la documentacion afirma una cobertura que no existe. Se comprueba contra la
    tabla real.
    """
    import re as _re

    reconocidas = [f for f in FORMAS_DE_PINTOR if f[1] == "reconocida"]
    denunciadas = [f for f in FORMAS_DE_PINTOR if f[1] != "reconocida"]
    palabras = {8: "OCHO", 11: "ONCE", 12: "DOCE", 19: "DIECINUEVE",
                20: "VEINTE", 21: "VEINTIUNA"}
    esperado = (f"{palabras.get(len(FORMAS_DE_PINTOR), len(FORMAS_DE_PINTOR))} formas: "
                f"{len(reconocidas)} reconocidas y {len(denunciadas)} denunciadas")
    assert esperado in __doc__, (
        f"la cabecera no dice «{esperado}»: el recuento escrito ha quedado viejo")

    ids = [f[0] for f in FORMAS_DE_PINTOR]
    assert len(set(ids)) == len(ids), f"hay formas repetidas: {ids}"
    assert _re.search(r"VEINTE|DIECINUEVE|VEINTIUNA", __doc__)


def test_una_COLISION_DE_NOMBRES_por_import_no_es_un_pintor():
    """El emparejamiento por nombre tiene una cara fea, y esta medida.

    `app/main.py` hace `from app.api import entities as api_entities`, y
    `api_entities` es TAMBIEN el nombre de una funcion de `readonly.py` que
    serializa. Al cerrar la clase de «posicion de valor», esa colision produjo
    OCHO falsos positivos en `main.py` -- ocho renderizadores denunciados por
    llamarse igual que otra cosa. Se cierra con la semantica de Python: si el
    nombre esta ligado aqui por un import cuyo origen no es una sembradora, en
    este modulo ese nombre NO es la sembradora homonima.
    """
    fuente = """
from app.api import entities as api_entities
app.include_router(api_entities.router)
def v(request):
    return templates.TemplateResponse(request, "entity.html", {})
"""
    arbol = ast.parse(fuente)
    assert "api_entities" in sembradoras(), (
        "este caso deja de medir la colision si `api_entities` ya no es una "
        "sembradora: buscar otro nombre colisionante")
    assert "api_entities" in importados_ajenos(arbol, sembradoras())

    pintadas, sueltos = _analizar_arbol(arbol, sembradoras(), Path("sintetico.py"),
                                        lambda: None)
    assert not sueltos, f"falso positivo por colision de nombres: {sueltos}"
    assert not pintadas, "y tampoco puede contarse como pintora"


def test_el_ensanchamiento_esta_ATADO_a_la_anotacion():
    """El ensanchamiento por dominio (`<x>.template` -> las cuatro del chasis)
    solo vale cuando CONSTA que `x` es un `FeatureSlot`.

    Por que importa, con la medida del revisor: de 11 renders de `<x>.template`
    en `viewer/app`, 10 tienen base resoluble y solo la de `chassis_slot.py` no,
    y ahi `pinta=False`, asi que hoy el ensanchamiento NO aporta ni una
    plantilla. Su unico efecto seria evitar que esa linea salga como no
    clasificable -- funcionalmente, una exencion. Y sin la anotacion, un
    `x.template` de OTRA cosa se atribuiria al chasis en vez de gritar:
    ensanchar dejaria de «sobrar» para SUSTITUIR. Con la anotacion exigida,
    ensanchar solo puede sobrar.
    """
    con = """
from app.chassis import FeatureSlot
from app.serializers import serialize_node
def v(request, slot: FeatureSlot, n):
    return templates.TemplateResponse(request, slot.template, {"e": serialize_node(n)})
"""
    sin = con.replace("slot: FeatureSlot", "slot")

    pintadas, sueltos = _analizar_arbol(ast.parse(con), sembradoras(),
                                        Path("sintetico.py"), lambda: None)
    assert set(pintadas) == set(_plantillas_del_chasis()), (
        f"con la anotacion, el dominio son los cuatro huecos: {sorted(pintadas)}")
    assert not sueltos

    pintadas, sueltos = _analizar_arbol(ast.parse(sin), sembradoras(),
                                        Path("sintetico.py"), lambda: None)
    assert not pintadas, (
        "sin anotacion NO se puede afirmar que ese `.template` sea del chasis: "
        "atribuirselo seria SUSTITUIR, no sobrar")
    assert sueltos, "y sin anotacion tiene que GRITAR, no callarse"


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
