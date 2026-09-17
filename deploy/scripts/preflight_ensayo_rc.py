# -*- coding: utf-8 -*-
"""Lista de comprobacion PREVIA al ensayo del recorrido real (RC). Solo lectura.

QUE ES ESTO
-----------
El ensayo RC recorre entero el camino del producto:

    subir fichero -> el escaner lo detecta -> mapping decide workspace/ambito/
    partida -> Source -> ingest_v3 -> progreso -> REVIEW -> plan sellado ->
    APPLY -> el worker OBSERVA Neo4j real -> proyecta -> resultado navegable
    -> procedencia -> evidencia literal

Las rondas anteriores midieron que ese recorrido no se rompe por codigo, sino
POR DESPLIEGUE: almacenes que escritor y lector resuelven distinto, un
directorio de fuentes vacio, un interruptor de panel escrito con el nombre del
hueco en vez de con su LETRA. Ninguno de esos fallos produce un error: producen
una pantalla vacia y un operador tranquilo. Este guion los convierte en
comprobaciones que se OBSERVAN antes de empezar.

DOCTRINA
--------
- **Fail closed.** Solo el codigo de salida 0 autoriza a empezar el ensayo.
- **AUSENCIA != CERO.** Una comprobacion que no pudo mirar devuelve PENDIENTE,
  nunca VERDE. PENDIENTE no autoriza nada.
- **Sin instrumental externo.** Solo biblioteca estandar: `jq` no esta
  instalado en el entorno de trabajo y un vigia que lo usaba giro en vacio sin
  emitir nada. Y la primera comprobacion que corre es el CANARIO: un sondeo
  que TIENE que salir en rojo. Si el canario sale verde, el instrumento no
  sirve y el guion aborta sin juzgar nada mas.
- **Ni un secreto por pantalla.** De las credenciales se observan existencia,
  modo y propietario. Nunca el valor, ni en salida, ni en errores, ni en
  `argv`.

QUE **NO** HACE
---------------
No despliega, no enciende maquinas, no escribe en el grafo, no arranca
servicios y no toca produccion. Lo unico que escribe es un fichero temporal
dentro del almacen de propuestas —la unica forma de saber si el escritor podra
escribir es escribir— y lo borra acto seguido.

USO
---
    python3 deploy/scripts/preflight_ensayo_rc.py --workspace <ws>

Codigos de salida:
    0 = todas VERDE          -> el ensayo puede empezar
    1 = alguna PENDIENTE     -> NO empezar: hay algo que no se pudo mirar
    2 = alguna ROJA          -> NO empezar: hay un requisito incumplido
    3 = instrumental invalido (el canario no dio rojo) o uso incorrecto
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

VERDE = "VERDE"
ROJO = "ROJO"
PENDIENTE = "PENDIENTE"

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Las LETRAS de los huecos del chasis que el ensayo necesita encendidos.
#: Con el nombre del hueco en vez de la letra no monta nada y la pantalla no
#: distingue «apagado» de «no autorizado»: por eso se comprueba la letra.
HUECOS_DEL_ENSAYO = {
    "B": "Operaciones (alta de fuente y lanzamiento de ingesta)",
    "C": "Review (cola de propuestas y decision humana)",
    "F": "Sources (catalogo de fuentes)",
    "G": "Entities (resultado navegable)",
}

#: Unicos valores que ENCIENDEN un hueco. Copiados del contrato del chasis
#: (`viewer/app/chassis.py::FLAG_ON_VALUES`): "si" o "yes" no encienden nada.
VALORES_ENCENDIDO = frozenset({"true", "1"})

#: Variables cuyo VALOR es un secreto: no se imprimen jamas, y estar en el
#: entorno del proceso ya es un defecto (el orden correcto es gestor de
#: secretos -> fichero 0600 -> stdin -> variable efimera).
SECRETOS_EN_ENTORNO = ("S9K_NEO4J_PASSWORD",)


@dataclass(frozen=True)
class Resultado:
    """El desenlace de UNA comprobacion. `detalle` nunca lleva un secreto."""

    id: str
    estado: str
    detalle: str


@dataclass(frozen=True)
class Contexto:
    """Lo que las comprobaciones necesitan saber del ensayo."""

    env: dict
    workspace: str


# ---------------------------------------------------------------------------
# Resolvedores CANONICOS del producto
# ---------------------------------------------------------------------------
# No se vuelve a derivar aqui ninguna ruta. Derivarla seria crear la segunda
# verdad que este guion existe para detectar: el motor escribiendo en una
# carpeta y el visor mirando otra, los dos «funcionando». Se cargan los
# modulos del producto por ruta (solo dependen de la biblioteca estandar) y si
# no se pueden cargar, la comprobacion sale PENDIENTE, nunca VERDE.

def _cargar(nombre: str, ruta: Path):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    if spec is None or spec.loader is None:  # pragma: no cover - ruta inexistente
        raise ImportError(str(ruta))
    modulo = importlib.util.module_from_spec(spec)
    # Registrado ANTES de ejecutar: `@dataclass` del modulo cargado resuelve
    # sus anotaciones por `sys.modules[__module__]` y sin esto revienta.
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _review_paths(raiz: Path = REPO_ROOT):
    return _cargar(
        "_s9k_review_paths",
        raiz / "data-engine" / "app" / "knowledge_v3" / "review_paths.py",
    )


def _review_decisions(raiz: Path = REPO_ROOT):
    return _cargar(
        "_s9k_review_decisions",
        raiz / "data-engine" / "app" / "knowledge_v3" / "review_decisions.py",
    )


def _sources_catalog(raiz: Path = REPO_ROOT):
    return _cargar(
        "_s9k_sources_catalog", raiz / "viewer" / "app" / "sources_catalog.py"
    )


# ---------------------------------------------------------------------------
# 0. CANARIO — el instrumento tiene que saber dar rojo
# ---------------------------------------------------------------------------

def canario(ctx: Contexto) -> Resultado:
    """Sondeo con la respuesta conocida: la condicion es falsa a proposito.

    Un vigia que gira en vacio y no emite nada se lee igual que uno que no
    encontro defectos. Antes de creerse ningun VERDE de abajo, este guion
    comprueba que su propia maquinaria sabe producir un ROJO.
    """
    condicion_falsa = Path("/s9k/no/existe/jamas").exists()
    if condicion_falsa:  # pragma: no cover - el sistema de ficheros no miente
        return Resultado("canario", VERDE, "imposible")
    return Resultado("canario", ROJO, "rojo esperado: el instrumento responde")


# ---------------------------------------------------------------------------
# 1. Almacen de propuestas — el invariante del Corte 3
# ---------------------------------------------------------------------------

def propuestas_declarada(ctx: Contexto) -> Resultado:
    crudo = ctx.env.get("S9K_V3_REVIEW_PROPOSALS_DIR")
    if not crudo:
        return Resultado(
            "propuestas.declarada", ROJO,
            "S9K_V3_REVIEW_PROPOSALS_DIR sin declarar: escritor y visor caerian "
            "cada uno en su defecto y la cola de revision saldria vacia sin error",
        )
    ruta = Path(crudo)
    if not ruta.is_absolute():
        return Resultado(
            "propuestas.declarada", ROJO,
            "ruta relativa: dos procesos con distinto directorio de trabajo "
            "resuelven dos almacenes distintos",
        )
    if _bajo(ruta, REPO_ROOT):
        return Resultado(
            "propuestas.declarada", ROJO,
            "el almacen esta DENTRO del arbol del codigo: un redespliegue lo "
            "sustituye y la cola de revision desaparece",
        )
    return Resultado("propuestas.declarada", VERDE, f"declarada: {ruta}")


def propuestas_utilizable(ctx: Contexto) -> Resultado:
    """Existe, se lee y se ESCRIBE. Apuntarla a algo inexistente daba consola muda."""
    crudo = ctx.env.get("S9K_V3_REVIEW_PROPOSALS_DIR")
    if not crudo:
        return Resultado("propuestas.utilizable", PENDIENTE,
                         "sin ruta declarada no hay nada que mirar")
    ruta = Path(crudo)
    if not ruta.is_dir():
        return Resultado("propuestas.utilizable", ROJO,
                         "el directorio declarado NO existe")
    if not os.access(ruta, os.R_OK | os.X_OK):
        return Resultado("propuestas.utilizable", ROJO,
                         "existe pero el visor no podria leerlo")
    # EL TESTIGO SE BORRA SIEMPRE. Sin `finally`, un fallo a mitad (medido:
    # un `OSError` en el `unlink`) deja `.s9k-preflight-testigo` residual en el
    # almacen que el operador va a mirar. El estado resultante es ROJO, asi que
    # no es un falso verde -- pero un guion de SOLO LECTURA no puede dejar
    # basura detras, y menos ahi.
    testigo = ruta / ".s9k-preflight-testigo"
    quedo = False
    try:
        testigo.write_text("", encoding="utf-8")
        # Se comprueba el EFECTO, no que la llamada no levantara: un montaje de
        # solo lectura con cache puede aceptar el `write` y no dejar nada.
        if not testigo.is_file():
            return Resultado("propuestas.utilizable", ROJO,
                             "la escritura no dejo el fichero: el almacen no es "
                             "escribible de verdad")
    except OSError as exc:
        return Resultado("propuestas.utilizable", ROJO,
                         f"el escritor no podria escribir: {exc.strerror}")
    finally:
        # SIEMPRE. Sin esto, cualquier salida entre el `write` y el borrado deja
        # `.s9k-preflight-testigo` residual en el almacen que el operador va a
        # mirar; el desenlace era ROJO --no un falso verde-- pero un guion de
        # solo lectura no deja basura, y menos ahi.
        try:
            testigo.unlink(missing_ok=True)
        except OSError:
            quedo = True
    if quedo:
        # No se pudo retirar: se dice, no se tapa.
        return Resultado("propuestas.utilizable", ROJO,
                         "quedo un fichero testigo en el almacen de propuestas")
    return Resultado("propuestas.utilizable", VERDE,
                     "existe, legible y escribible (comprobado escribiendo)")


def propuestas_derivacion_unica(ctx: Contexto) -> Resultado:
    """El resolvedor CANONICO del producto tiene que devolver ESA ruta."""
    crudo = ctx.env.get("S9K_V3_REVIEW_PROPOSALS_DIR")
    if not crudo:
        return Resultado("propuestas.derivacion_unica", PENDIENTE,
                         "sin ruta declarada no se puede comparar")
    try:
        resolvedor = _review_paths()
    except Exception as exc:  # noqa: BLE001 - se informa, no se traga
        return Resultado("propuestas.derivacion_unica", PENDIENTE,
                         f"no se pudo cargar el resolvedor del motor: {type(exc).__name__}")
    previo = os.environ.get("S9K_V3_REVIEW_PROPOSALS_DIR")
    os.environ["S9K_V3_REVIEW_PROPOSALS_DIR"] = crudo
    try:
        obtenida = Path(resolvedor.default_proposals_dir())
    finally:
        if previo is None:
            os.environ.pop("S9K_V3_REVIEW_PROPOSALS_DIR", None)
        else:
            os.environ["S9K_V3_REVIEW_PROPOSALS_DIR"] = previo
    if obtenida != Path(crudo):
        return Resultado("propuestas.derivacion_unica", ROJO,
                         "el resolvedor del producto devuelve OTRA ruta")
    return Resultado("propuestas.derivacion_unica", VERDE,
                     "el resolvedor canonico devuelve la ruta declarada")


# ---------------------------------------------------------------------------
# 2. review.sqlite3 — el invariante del Corte 2
# ---------------------------------------------------------------------------

def review_db_compartida(ctx: Contexto) -> Resultado:
    """Visor y motor tienen que resolver EL MISMO fichero.

    Si se separan los volumenes, el falso exito vuelve POR DESPLIEGUE: el
    operador decide, el motor no ve la decision, y nadie ve un error.
    """
    base = ctx.env.get("S9K_V3_REVIEW_DATABASE_PATH")
    decisiones = ctx.env.get("S9K_V3_REVIEW_DECISIONS_PATH")
    if not base and not decisiones:
        return Resultado(
            "review_db.compartida", ROJO,
            "ni S9K_V3_REVIEW_DATABASE_PATH ni S9K_V3_REVIEW_DECISIONS_PATH: "
            "cada proceso caeria en el defecto de SU arbol",
        )
    try:
        motor = _review_decisions()
    except Exception as exc:  # noqa: BLE001
        return Resultado("review_db.compartida", PENDIENTE,
                         f"no se pudo cargar el lector del motor: {type(exc).__name__}")
    guardado = {k: os.environ.get(k) for k in
                ("S9K_V3_REVIEW_DATABASE_PATH", "S9K_V3_REVIEW_DECISIONS_PATH")}
    for clave, valor in (("S9K_V3_REVIEW_DATABASE_PATH", base),
                         ("S9K_V3_REVIEW_DECISIONS_PATH", decisiones)):
        if valor:
            os.environ[clave] = valor
        else:
            os.environ.pop(clave, None)
    try:
        del_motor = motor.default_decisions_db()
    finally:
        for clave, valor in guardado.items():
            if valor is None:
                os.environ.pop(clave, None)
            else:
                os.environ[clave] = valor
    if del_motor is None:
        return Resultado("review_db.compartida", ROJO,
                         "el motor no resuelve NINGUNA base de decisiones")
    esperada = Path(base) if base else Path(decisiones).with_name("review.sqlite3")
    if Path(del_motor) != esperada:
        return Resultado("review_db.compartida", ROJO,
                         "visor y motor resuelven ficheros DISTINTOS")
    if not esperada.is_absolute():
        return Resultado("review_db.compartida", ROJO, "ruta relativa")
    if _bajo(esperada, REPO_ROOT):
        return Resultado("review_db.compartida", ROJO,
                         "review.sqlite3 bajo el arbol del codigo: un redespliegue "
                         "se lleva por delante las decisiones humanas")
    if not esperada.parent.is_dir():
        return Resultado("review_db.compartida", ROJO,
                         "el directorio de review.sqlite3 no existe")
    return Resultado("review_db.compartida", VERDE,
                     f"visor y motor resuelven el mismo fichero: {esperada}")


def estado_persistente_sobrevive(ctx: Contexto) -> Resultado:
    """Almacen de propuestas y review.sqlite3 bajo el MISMO state root."""
    propuestas = ctx.env.get("S9K_V3_REVIEW_PROPOSALS_DIR")
    base = ctx.env.get("S9K_V3_REVIEW_DATABASE_PATH") or ctx.env.get(
        "S9K_V3_REVIEW_DECISIONS_PATH")
    raiz = ctx.env.get("S9K_STATE_ROOT")
    if not (propuestas and base):
        return Resultado("estado.persistente", PENDIENTE,
                         "faltan rutas por declarar: no se puede comparar")
    if not raiz:
        return Resultado("estado.persistente", ROJO,
                         "S9K_STATE_ROOT sin declarar: no hay un solo sitio del que "
                         "hablar al reiniciar ni al hacer copia")
    # PUERTA DEGENERADA. `S9K_STATE_ROOT=/` hace que TODO caiga "bajo el state
    # root" y la comprobacion salga verde sin comprobar nada: cualquier reparto
    # de rutas la satisface. Un state root es un directorio propio del
    # despliegue, no el sistema de ficheros entero.
    raiz_abs = Path(raiz)
    if not raiz_abs.is_absolute() or len(raiz_abs.resolve().parts) < 3:
        return Resultado("estado.persistente", ROJO,
                         "S9K_STATE_ROOT degenerado: tiene que ser un directorio "
                         "propio del despliegue, no la raiz del sistema")
    fuera = [n for n, p in (("propuestas", propuestas), ("review.sqlite3", base))
             if not _bajo(Path(p), Path(raiz))]
    if fuera:
        return Resultado("estado.persistente", ROJO,
                         f"fuera del state root: {', '.join(fuera)}")
    return Resultado("estado.persistente", VERDE,
                     "propuestas y review.sqlite3 bajo el state root declarado")


def reinicio_no_reprocesa(ctx: Contexto) -> Resultado:
    """Reiniciar NO debe reprocesarlo todo: el escaner recuerda lo ya visto.

    Requisito del ensayo, declarado ANTES de que exista el escaner. No hay
    marca de estado del escaner que mirar, asi que esto no puede salir verde:
    sale PENDIENTE y bloquea, que es lo contrario de darlo por bueno.
    """
    marca = ctx.env.get("S9K_SCANNER_STATE_PATH")
    if not marca:
        return Resultado(
            "reinicio.no_reprocesa", PENDIENTE,
            "el escaner no declara estado durable (S9K_SCANNER_STATE_PATH). "
            "Observacion exigida cuando exista: tras reiniciar, cero jobs "
            "nuevos para ficheros ya ingeridos y los ya vistos no cambian de id",
        )
    if not Path(marca).is_absolute() or _bajo(Path(marca), REPO_ROOT):
        return Resultado("reinicio.no_reprocesa", ROJO,
                         "estado del escaner relativo o bajo el arbol del codigo")
    if not Path(marca).parent.is_dir():
        return Resultado("reinicio.no_reprocesa", ROJO,
                         "el directorio del estado del escaner no existe")
    return Resultado("reinicio.no_reprocesa", VERDE,
                     "el escaner declara estado durable fuera de la release")


# ---------------------------------------------------------------------------
# 3. Fuentes — el paso 1 deja de ser usable SIN NINGUN ERROR
# ---------------------------------------------------------------------------

def fuentes_pobladas(ctx: Contexto) -> Resultado:
    crudo = ctx.env.get("S9K_INGEST_SOURCES_DIR")
    if not crudo:
        return Resultado("fuentes.pobladas", ROJO,
                         "S9K_INGEST_SOURCES_DIR sin declarar: el catalogo caeria "
                         "en los ejemplos del repositorio")
    try:
        catalogo = _sources_catalog()
    except Exception as exc:  # noqa: BLE001
        return Resultado("fuentes.pobladas", PENDIENTE,
                         f"no se pudo cargar el catalogo: {type(exc).__name__}")
    try:
        fuentes = catalogo.listar_fuentes({"S9K_INGEST_SOURCES_DIR": crudo})
    except Exception as exc:  # noqa: BLE001
        return Resultado("fuentes.pobladas", ROJO,
                         f"el catalogo no se pudo consultar: {type(exc).__name__}")
    if not fuentes:
        return Resultado("fuentes.pobladas", ROJO,
                         "directorio de fuentes VACIO: el paso 1 deja de ser usable "
                         "sin dar ni un error")
    return Resultado("fuentes.pobladas", VERDE,
                     f"{len(fuentes)} fuente(s) elegible(s) segun el catalogo del producto")


# ---------------------------------------------------------------------------
# 4. Paneles — interruptor por LETRA, fail closed
# ---------------------------------------------------------------------------

def paneles_por_letra(ctx: Contexto) -> Resultado:
    apagados = []
    for letra, que_es in sorted(HUECOS_DEL_ENSAYO.items()):
        valor = ctx.env.get(f"S9K_PANEL_{letra}_ENABLED")
        encendido = valor is not None and valor.strip().lower() in VALORES_ENCENDIDO
        if not encendido:
            apagados.append(f"{letra} ({que_es})")
    if apagados:
        return Resultado("paneles.por_letra", ROJO,
                         "huecos sin encender: " + "; ".join(apagados))
    return Resultado("paneles.por_letra", VERDE,
                     "B, C, F y G encendidos por LETRA con un valor que el chasis acepta")


def paneles_sin_nombres(ctx: Contexto) -> Resultado:
    """Un interruptor escrito con el NOMBRE del hueco no enciende nada."""
    validas = {f"S9K_PANEL_{l}_ENABLED" for l in HUECOS_DEL_ENSAYO}
    validas.add("S9K_PANEL_RESULTADO_ENABLED")  # pantalla de resultado, no es hueco
    intrusas = sorted(
        k for k in ctx.env
        if k.startswith("S9K_PANEL_") and k.endswith("_ENABLED") and k not in validas
    )
    if intrusas:
        return Resultado("paneles.sin_nombres", ROJO,
                         "interruptores que el chasis no lee (¿nombre en vez de "
                         "letra?): " + ", ".join(intrusas))
    return Resultado("paneles.sin_nombres", VERDE,
                     "ningun interruptor de panel fuera del contrato por letra")


def resultado_navegable(ctx: Contexto) -> Resultado:
    valor = ctx.env.get("S9K_PANEL_RESULTADO_ENABLED")
    if valor is None or valor.strip().lower() not in VALORES_ENCENDIDO:
        return Resultado("resultado.navegable", ROJO,
                         "S9K_PANEL_RESULTADO_ENABLED apagado: el ultimo tramo del "
                         "recorrido (resultado -> procedencia -> evidencia) no se sirve")
    return Resultado("resultado.navegable", VERDE, "pantalla de resultado encendida")


# ---------------------------------------------------------------------------
# 5. APPLY — para que el boton exista
# ---------------------------------------------------------------------------

def apply_habilitado(ctx: Contexto) -> Resultado:
    """La MISMA declaracion que lee `v3_apply._habilitado`. Sin ella: APPLY_NOT_ENABLED."""
    permiso = ctx.env.get("S9K_ALLOW_REAL_INGEST")
    ws = ctx.env.get("S9K_WRITER_WORKSPACE")
    if permiso != "1":
        return Resultado("apply.habilitado", ROJO,
                         "S9K_ALLOW_REAL_INGEST no vale exactamente '1': la pantalla "
                         "NO ofrece el boton y el POST contesta APPLY_NOT_ENABLED")
    if not ws:
        return Resultado("apply.habilitado", ROJO, "S9K_WRITER_WORKSPACE sin declarar")
    if ws != ctx.workspace:
        return Resultado("apply.habilitado", ROJO,
                         "S9K_WRITER_WORKSPACE no es el workspace del ensayo: el "
                         "boton no aparecera en la pantalla que se va a usar")
    return Resultado("apply.habilitado", VERDE,
                     "permiso de escritura declarado para el workspace del ensayo")


# ---------------------------------------------------------------------------
# 6. Neo4j — credencial minima, sin secretos por ninguna superficie
# ---------------------------------------------------------------------------

def credencial_por_fichero(ctx: Contexto) -> Resultado:
    for clave in SECRETOS_EN_ENTORNO:
        if ctx.env.get(clave):
            return Resultado("neo4j.credencial", ROJO,
                             f"{clave} esta en el entorno del proceso: el orden "
                             "correcto es gestor de secretos -> fichero 0600 -> "
                             "stdin -> variable efimera")
    crudo = ctx.env.get("S9K_NEO4J_PASSWORD_FILE")
    if not crudo:
        return Resultado("neo4j.credencial", ROJO,
                         "S9K_NEO4J_PASSWORD_FILE sin declarar: el worker no tendria "
                         "credencial y el apply debe fallar cerrado")
    ruta = Path(crudo)
    if not ruta.is_file():
        return Resultado("neo4j.credencial", ROJO, "el fichero de credencial no existe")
    if _bajo(ruta, REPO_ROOT):
        return Resultado("neo4j.credencial", ROJO,
                         "la credencial vive DENTRO del arbol del repositorio")
    modo = stat.S_IMODE(ruta.stat().st_mode)
    if modo != 0o600:
        return Resultado("neo4j.credencial", ROJO,
                         f"modo {modo:04o}: se exige 0600")
    if ruta.stat().st_size == 0:
        return Resultado("neo4j.credencial", ROJO, "el fichero de credencial esta vacio")
    if ctx.env.get("S9K_NEO4J_USER", "") == "neo4j":
        return Resultado("neo4j.credencial", ROJO,
                         "S9K_NEO4J_USER=neo4j: el ensayo exige un usuario propio con "
                         "el minimo privilegio, no el administrador del servidor")
    if not ctx.env.get("S9K_NEO4J_USER"):
        return Resultado("neo4j.credencial", ROJO, "S9K_NEO4J_USER sin declarar")
    return Resultado("neo4j.credencial", VERDE,
                     "usuario propio y credencial en fichero 0600 fuera del repositorio "
                     "(valor NO leido)")


def neo4j_transporte(ctx: Contexto) -> Resultado:
    uri = ctx.env.get("S9K_NEO4J_URI")
    if not uri:
        return Resultado("neo4j.transporte", ROJO, "S9K_NEO4J_URI sin declarar")
    partes = urlsplit(uri)
    esquema = (partes.scheme or "").lower()
    host = (partes.hostname or "").lower()
    cifrado = esquema.endswith("+s") or esquema.endswith("+ssc")
    local = host in {"localhost", "127.0.0.1", "::1"}
    if not cifrado and not local:
        return Resultado("neo4j.transporte", ROJO,
                         f"esquema '{esquema}' sin cifrar contra un host remoto")
    if esquema.endswith("+ssc"):
        return Resultado("neo4j.transporte", ROJO,
                         "'+ssc' acepta certificados autofirmados sin verificar: es "
                         "una ruta de repuesto silenciosa")
    if cifrado:
        ca = ctx.env.get("S9K_NEO4J_CA_FILE")
        if not ca:
            return Resultado("neo4j.transporte", PENDIENTE,
                             "conexion cifrada sin CA declarada: no se puede observar "
                             "contra que se valida el certificado")
        if not Path(ca).is_file():
            return Resultado("neo4j.transporte", ROJO, "la CA declarada no existe")
        return Resultado("neo4j.transporte", VERDE, "cifrado con CA declarada y presente")
    return Resultado("neo4j.transporte", VERDE,
                     "conexion local sin salir de la maquina")


def worker_observa_el_grafo(ctx: Contexto) -> Resultado:
    """LA comprobacion nueva: el worker tiene que PODER OBSERVAR Neo4j real.

    El ensayo ya no puede validar solo volumenes compartidos. Lo que decide si
    el recorrido termina es si el worker, con SU credencial y SU contexto, ve el
    grafo. El camino de producto hasta el driver real lo esta construyendo el
    carril A; aqui se declara la dependencia y se deja la comprobacion, que
    hasta entonces sale PENDIENTE — que no autoriza nada.

    Cuando el carril A cierre, esto se observa asi (y no antes de tener su
    punto de entrada): con el entorno del ensayo, un sondeo de SOLO LECTURA que
    abra sesion contra el grafo, lea el workspace declarado y devuelva el
    recuento; una credencial ausente o sin permiso tiene que dar un fallo
    explicito, nunca cero nodos.
    """
    proveedor = (ctx.env.get("S9K_GRAPH_PROVIDER") or "").strip().lower()
    if proveedor != "neo4j":
        return Resultado("worker.observa_grafo", ROJO,
                         f"S9K_GRAPH_PROVIDER='{proveedor or 'ausente'}': el ensayo "
                         "exige el grafo real, un mock lo daria por bueno")
    return Resultado(
        "worker.observa_grafo", PENDIENTE,
        "DEPENDENCIA DEL CARRIL A: sin punto de entrada de producto al driver real "
        "no hay capacidad que observar. No se sustituye por un sondeo propio: seria "
        "medir otra cosa distinta de la que usara el worker",
    )


# ---------------------------------------------------------------------------
# 7. Aislamiento por workspace / ambito / partida
# ---------------------------------------------------------------------------

def _head_del_arbol(raiz: Path = REPO_ROOT) -> Optional[str]:
    """El commit que ESTE arbol tiene desplegado, leido de `.git`.

    Sin `subprocess`: invocar `git` metería una herramienta externa en un guion
    que se apoya en no tener ninguna (y el test que lo garantiza se pondria
    rojo). Devuelve ``None`` cuando no se puede resolver: eso es PENDIENTE
    arriba, nunca un verde.
    """
    punto = raiz / ".git"
    try:
        if punto.is_file():
            # Arbol de trabajo enlazado (`git worktree`): apunta a su gitdir.
            crudo = punto.read_text(encoding="utf-8").strip()
            if not crudo.startswith("gitdir:"):
                return None
            gitdir = Path(crudo.split(":", 1)[1].strip())
        else:
            gitdir = punto
        cabeza = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
        if not cabeza.startswith("ref:"):
            return cabeza or None
        referencia = cabeza.split(":", 1)[1].strip()
        comun = gitdir
        enlace = gitdir / "commondir"
        if enlace.is_file():
            comun = (gitdir / enlace.read_text(encoding="utf-8").strip()).resolve()
        for candidato in (gitdir / referencia, comun / referencia):
            if candidato.is_file():
                return candidato.read_text(encoding="utf-8").strip() or None
        empaquetadas = comun / "packed-refs"
        if empaquetadas.is_file():
            for linea in empaquetadas.read_text(encoding="utf-8").splitlines():
                if linea.endswith(" " + referencia):
                    return linea.split(" ", 1)[0]
    except OSError:
        return None
    return None


def arbol_declarado(ctx: Contexto) -> Resultado:
    """El ensayo corre sobre el arbol que dice, no sobre el que se supone.

    Se anade despues de un incidente REAL: un agente reanudado perdio su arbol
    de trabajo y siguio operando en otro que estaba 30 ficheros por detras de
    `main`, creyendo que era el suyo. "El proceso ejecuta el arbol que cree" es
    una propiedad OBSERVABLE, y hasta ahora nadie la miraba; un ensayo sobre el
    arbol equivocado da un veredicto sobre un producto que no es el que se va a
    desplegar, y no se distingue de uno bueno.
    """
    esperado = (ctx.env.get("S9K_ENSAYO_COMMIT") or "").strip()
    if not esperado:
        return Resultado("arbol.declarado", PENDIENTE,
                         "S9K_ENSAYO_COMMIT sin declarar: no hay contra que "
                         "comparar el arbol desde el que se ejecuta")
    obtenido = _head_del_arbol()
    if obtenido is None:
        return Resultado("arbol.declarado", PENDIENTE,
                         "no se pudo leer el HEAD de este arbol")
    if not obtenido.startswith(esperado):
        return Resultado("arbol.declarado", ROJO,
                         f"el arbol esta en {obtenido[:12]} y el ensayo declara "
                         f"{esperado[:12]}: se juzgaria otro producto")
    return Resultado("arbol.declarado", VERDE,
                     f"el arbol ejecuta el commit declarado ({obtenido[:12]})")


def aislamiento_workspace(ctx: Contexto) -> Resultado:
    por_defecto = ctx.env.get("S9K_DEFAULT_WORKSPACE")
    escritor = ctx.env.get("S9K_WRITER_WORKSPACE")
    if not por_defecto:
        return Resultado("aislamiento.workspace", ROJO,
                         "S9K_DEFAULT_WORKSPACE sin declarar")
    if por_defecto != ctx.workspace or escritor != ctx.workspace:
        return Resultado(
            "aislamiento.workspace", ROJO,
            "el workspace del ensayo, el que pinta el visor y aquel en el que el "
            "writer puede escribir NO son el mismo: el ensayo podria leer en uno y "
            "escribir en otro sin que se note")
    return Resultado("aislamiento.workspace", VERDE,
                     "visor, writer y ensayo hablan del mismo workspace")


def autenticacion_activa(ctx: Contexto) -> Resultado:
    if (ctx.env.get("S9K_AUTH_ENABLED") or "").strip().lower() != "true":
        return Resultado("auth.activa", ROJO,
                         "S9K_AUTH_ENABLED != true: sin autoridad de revision el "
                         "ensayo no demuestra nada sobre permisos ni sobre quien decide")
    return Resultado("auth.activa", VERDE, "autenticacion declarada activa")


# ---------------------------------------------------------------------------

def _bajo(ruta: Path, raiz: Path) -> bool:
    try:
        ruta.resolve().relative_to(raiz.resolve())
        return True
    except (ValueError, OSError):
        return False


#: El orden es el del recorrido, no el de importancia: se lee como el ensayo.
COMPROBACIONES: tuple[tuple[str, Callable[[Contexto], Resultado]], ...] = (
    ("arbol.declarado", arbol_declarado),
    ("fuentes.pobladas", fuentes_pobladas),
    ("paneles.por_letra", paneles_por_letra),
    ("paneles.sin_nombres", paneles_sin_nombres),
    ("propuestas.declarada", propuestas_declarada),
    ("propuestas.utilizable", propuestas_utilizable),
    ("propuestas.derivacion_unica", propuestas_derivacion_unica),
    ("review_db.compartida", review_db_compartida),
    ("estado.persistente", estado_persistente_sobrevive),
    ("reinicio.no_reprocesa", reinicio_no_reprocesa),
    ("auth.activa", autenticacion_activa),
    ("apply.habilitado", apply_habilitado),
    ("neo4j.credencial", credencial_por_fichero),
    ("neo4j.transporte", neo4j_transporte),
    ("worker.observa_grafo", worker_observa_el_grafo),
    ("aislamiento.workspace", aislamiento_workspace),
    ("resultado.navegable", resultado_navegable),
)


def ejecutar(ctx: Contexto) -> list[Resultado]:
    """Todas las comprobaciones. Una que revienta es ROJO, no una que falta."""
    salida: list[Resultado] = []
    for nombre, funcion in COMPROBACIONES:
        try:
            salida.append(funcion(ctx))
        except Exception as exc:  # noqa: BLE001 - jamas se traga en silencio
            salida.append(Resultado(nombre, ROJO,
                                    f"la comprobacion reviento: {type(exc).__name__}"))
    return salida


def codigo_de_salida(resultados: list[Resultado]) -> int:
    if any(r.estado == ROJO for r in resultados):
        return 2
    if any(r.estado == PENDIENTE for r in resultados):
        return 1
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lista de comprobacion previa al ensayo RC (solo lectura).")
    parser.add_argument("--workspace", required=True,
                        help="workspace del ensayo (NO es un secreto)")
    args = parser.parse_args(argv)

    prueba = canario(Contexto(env=dict(os.environ), workspace=args.workspace))
    if prueba.estado != ROJO:
        print("INSTRUMENTAL INVALIDO: el canario no dio rojo. No se juzga nada.",
              file=sys.stderr)
        return 3
    print(f"canario           {prueba.detalle}")

    ctx = Contexto(env=dict(os.environ), workspace=args.workspace)
    resultados = ejecutar(ctx)
    ancho = max(len(r.id) for r in resultados)
    for r in resultados:
        print(f"{r.estado:<9} {r.id:<{ancho}}  {r.detalle}")

    codigo = codigo_de_salida(resultados)
    veredicto = {0: "APTO para empezar el ensayo",
                 1: "NO APTO: hay comprobaciones que no pudieron mirar",
                 2: "NO APTO: hay requisitos incumplidos"}[codigo]
    print(f"\n{veredicto}")
    return codigo


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
