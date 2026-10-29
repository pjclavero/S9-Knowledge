# -*- coding: utf-8 -*-
"""Resolucion CANONICA de las rutas del almacen de revision V3.

POR QUE ESTE MODULO EXISTE
--------------------------
Slice 2 · Corte 3 encontro el mismo patron por tercera vez: una capacidad
completa y SIN LLAMADOR en el camino del producto. `Pipeline.run` sabia
exportar propuestas (`review_proposals_dir`), pero la cadena que el panel usa
—`/panel/operations` -> `ingest_v3` -> `run_ingest`— no le pasaba nunca esa
ruta. El informe decia `REVIEW=2` y `/panel/review` decia «Sin propuestas
visibles». El operador daba por buena una ingesta cuyas ambiguedades no vio.

Al enchufar el llamador aparecio el riesgo de siempre: el handler derivaria una
ruta por su cuenta y `default_proposals_dir()` del visor derivaria otra. **Si
hay dos derivaciones de una ruta, hay dos verdades**, y el sintoma seria
exactamente el mismo que se acaba de arreglar: el motor escribiendo propuestas
en una carpeta y el visor mirando otra, ambos «funcionando».

Por eso la resolucion vive AQUI y SOLO AQUI. El visor no vuelve a derivarla:
`app.services.v3_review.default_proposals_dir` reexporta esta funcion.

INVARIANTE DE DESPLIEGUE
------------------------
``S9K_V3_REVIEW_PROPOSALS_DIR`` la comparten ESCRITOR (el worker que corre la
ingesta) y LECTOR (el visor que pinta `/panel/review`). Si cada servicio la
resuelve a un almacenamiento distinto, no hay error: hay una cola de revision
vacia y un operador tranquilo. Es la misma exigencia que el Corte 2 ya impuso a
``review.sqlite3``. Queda declarada en ``docs/88`` y en el rol de despliegue.

DIRECCION DE IMPORTACION
------------------------
Motor -> visor NO se puede: motor y visor publican dos paquetes ``app``
distintos (ver ``review_decisions.py``). Visor -> motor SI, y ya se hace: es el
puente que usa ``viewer/app/jobs_client.py`` para `jobs.job_store`. Por eso el
unico resolvedor vive en el motor y es el visor quien lo importa.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

__all__ = [
    "PROPOSALS_DIR_ENV", "default_proposals_dir",
    "REVIEW_DB_ENV", "REVIEW_DECISIONS_ENV", "REVIEW_DB_FILENAME",
    "ReviewDbConfigError", "ReviewDbRef", "Inspeccion",
    "CAUSA_VAR_VACIA", "CAUSA_VAR_RELATIVA", "CAUSA_NO_EXISTE",
    "CAUSA_NO_ES_FICHERO", "CAUSA_SIN_PERMISOS", "CAUSA_CORRUPTA",
    "CAUSA_SCHEMA_INVALIDO", "CAUSA_CARACTER_NO_PERMITIDO", "CAUSAS",
    "resolve_review_db", "default_review_db", "inspect_review_db",
    "validar_declaracion", "sqlite_uri",
]

#: La variable del invariante de despliegue. Se nombra una sola vez en todo el
#: producto: cualquier otra lectura de este nombre seria la segunda derivacion.
PROPOSALS_DIR_ENV = "S9K_V3_REVIEW_PROPOSALS_DIR"


def default_proposals_dir() -> Path:
    """El almacen de propuestas de revision. UNICA derivacion del producto.

    Precedencia:
      1. ``S9K_V3_REVIEW_PROPOSALS_DIR``, si esta declarada;
      2. la ubicacion por defecto del repositorio,
         ``viewer/output/reviews-v3/proposals``.

    El defecto apunta al arbol del VISOR a proposito: es quien tiene que leerlo.
    """
    configured = os.environ.get(PROPOSALS_DIR_ENV)
    if configured:
        return Path(configured)
    return (
        Path(__file__).resolve().parents[3]
        / "viewer" / "output" / "reviews-v3" / "proposals"
    )


# ===========================================================================
# review.sqlite3 — LA resolucion canonica (C1 · H-04 + H-18)
# ===========================================================================
# Hasta C1 habia TRES derivaciones de esta ruta: el visor
# (`default_database_path`), el motor (`default_decisions_db`) y el «esperado»
# del preflight. Tres derivaciones son tres verdades, y la diferencia se pagaba
# con decisiones humanas ignoradas en silencio. Ahora se resuelve AQUI y SOLO
# AQUI; visor, motor y preflight llaman a `default_review_db()`.
#
# QUIEN CREA EL ALMACEN (contrato del operador):
#   * DEPLOY es la autoridad: `deploy/scripts/review_store.py` lo crea en
#     `--mode fresh` y lo EXIGE en upgrade.
#   * El RUNTIME (visor y motor) CONSUME y VERIFICA; con la variable DECLARADA
#     nunca lo crea y falla cerrado con la causa real.
#   * Sin variable declarada (desarrollo) se conserva el defecto del repo como
#     TECHO DECLARADO: ahi el visor puede crearlo y el motor lee `{}` si no
#     existe. Una instalacion productiva no puede estar en ese caso: la
#     variable esta en CRITICAL_ENV_VARS.

REVIEW_DB_ENV = "S9K_V3_REVIEW_DATABASE_PATH"
REVIEW_DECISIONS_ENV = "S9K_V3_REVIEW_DECISIONS_PATH"
REVIEW_DB_FILENAME = "review.sqlite3"

CAUSA_VAR_VACIA = "VAR_VACIA"
CAUSA_VAR_RELATIVA = "VAR_RELATIVA"
CAUSA_NO_EXISTE = "NO_EXISTE"
CAUSA_NO_ES_FICHERO = "NO_ES_FICHERO"
CAUSA_SIN_PERMISOS = "SIN_PERMISOS"
CAUSA_CORRUPTA = "CORRUPTA"
CAUSA_SCHEMA_INVALIDO = "SCHEMA_INVALIDO"
CAUSA_CARACTER_NO_PERMITIDO = "CARACTER_NO_PERMITIDO"

#: Cada causa tiene SU frase: «no existe» no es «no es escribible» no es «no
#: es un fichero» no es «schema invalido». Sin rutas: el repositorio es publico
#: y estas frases llegan a pantallas y a `error_message` de jobs.
CAUSAS = {
    CAUSA_VAR_VACIA: (
        "S9K_V3_REVIEW_DATABASE_PATH esta declarada pero vacia (o solo espacios)"),
    CAUSA_VAR_RELATIVA: (
        "S9K_V3_REVIEW_DATABASE_PATH es una ruta relativa: dos procesos con "
        "distinto directorio de trabajo resolverian dos almacenes"),
    CAUSA_NO_EXISTE: (
        "el almacen de decisiones humanas declarado NO EXISTE: lo crea el "
        "despliegue, nunca el runtime"),
    CAUSA_NO_ES_FICHERO: (
        "la ruta del almacen de decisiones humanas no es un fichero (es un "
        "directorio u otro objeto)"),
    CAUSA_SIN_PERMISOS: (
        "el almacen de decisiones humanas existe pero el proceso no tiene los "
        "PERMISOS necesarios (lectura o escritura) sobre el"),
    CAUSA_CORRUPTA: (
        "el almacen de decisiones humanas esta CORRUPTO: no es una base SQLite "
        "legible"),
    CAUSA_SCHEMA_INVALIDO: (
        "el fichero declarado es SQLite pero no tiene la tabla human_decisions "
        "con la forma esperada: no es el almacen de revision"),
    CAUSA_CARACTER_NO_PERMITIDO: (
        "caracter no permitido en la ruta del almacen: S9K_V3_REVIEW_DATABASE_PATH "
        "contiene '#', '?', '%' o un caracter de control, que SQLite interpreta "
        "como parte de una URI y cortaria la ruta (abriendo OTRO fichero)"),
}

#: Caracteres que una URI ``file:`` de SQLite interpreta (fragmento, consulta,
#: escape) y los de control. Una ruta DECLARADA no puede llevarlos (P1-2 de la
#: revision independiente de C1): con ``#`` o ``?`` SQLite cortaba la ruta,
#: perdia ``mode=`` y abria —CREANDOLO— otro fichero. `sqlite_uri` los escapa
#: igualmente (defensa en profundidad); esto es la frontera fail-closed.
CARACTERES_NO_PERMITIDOS = frozenset("#?%")


def _tiene_caracter_no_permitido(texto: str) -> bool:
    return any(c in CARACTERES_NO_PERMITIDOS or ord(c) < 32 or ord(c) == 127
               for c in texto)


def sqlite_uri(path, mode: str, *, immutable: bool = False) -> str:
    """LA unica construccion de URI ``file:`` del almacen de revision.

    La comparten `inspect_review_db` (despliegue y runtime), el almacen del
    visor (`SQLiteReviewStore` con ``crear=False``) y la lectura del motor
    (`review_decisions._records`). Construirla a mano en otro sitio es repetir
    el P1-2: sin escapar, ``#``/``?`` en la ruta cortan la URI, ``mode=`` se
    pierde y SQLite abre en ``rwc``: el runtime CREA un fichero ajeno y lee
    cero decisiones.

    ``mode`` solo admite ``ro`` y ``rw``: el runtime NUNCA crea (``rwc``).
    """
    if mode not in ("ro", "rw"):
        raise ValueError("modo de apertura no admitido para el almacen: %r" % (mode,))
    uri = "file:%s?mode=%s" % (quote(str(path), safe="/"), mode)
    if immutable:
        uri += "&immutable=1"
    return uri

#: Columnas que `human_decisions` DEBE tener para ser el almacen de revision.
COLUMNAS_HUMAN_DECISIONS = frozenset({
    "decision_id", "workspace", "proposal_id", "request_id", "record_json",
    "created_at",
})


class ReviewDbConfigError(RuntimeError):
    """La declaracion o el estado del almacen no son utilizables.

    `causa` es uno de los codigos `CAUSA_*`; `str(exc)` es la frase estable de
    `CAUSAS` (sin rutas).
    """

    def __init__(self, causa: str, mensaje: Optional[str] = None):
        super().__init__(mensaje or CAUSAS[causa])
        self.causa = causa


@dataclass(frozen=True)
class ReviewDbRef:
    """La ruta resuelta y si viene de una DECLARACION explicita.

    `declarada=True` -> contrato de produccion: el almacen tiene que existir y
    ser valido; nadie en runtime lo crea ni lo sustituye por `{}`.
    `declarada=False` -> defecto de desarrollo (TECHO DECLARADO).
    """

    path: Path
    declarada: bool


def validar_declaracion(crudo: Optional[str]) -> Path:
    """Valida el VALOR de una declaracion de `S9K_V3_REVIEW_DATABASE_PATH`.

    ``None`` no es una declaracion (el llamador decide). Vacia, solo espacios,
    relativa, con un caracter que SQLite interpreta en una URI (``#``, ``?``,
    ``%``, control: N19) o apuntando a un directorio levantan
    `ReviewDbConfigError` con la causa real. Es la unica validacion: la usan `resolve_review_db` (runtime) y
    la herramienta de despliegue.
    """
    if crudo is None or crudo.strip() == "":
        raise ReviewDbConfigError(CAUSA_VAR_VACIA)
    ruta = Path(crudo)
    if not ruta.is_absolute():
        raise ReviewDbConfigError(CAUSA_VAR_RELATIVA)
    if _tiene_caracter_no_permitido(crudo):
        raise ReviewDbConfigError(CAUSA_CARACTER_NO_PERMITIDO)
    try:
        es_directorio = ruta.is_dir()
    except OSError:
        # Sin permiso para ni mirar el padre: no es una declaracion invalida,
        # es un problema de PERMISOS que `inspect_review_db` diagnostica.
        es_directorio = False
    if es_directorio:
        raise ReviewDbConfigError(CAUSA_NO_ES_FICHERO)
    return ruta


def resolve_review_db() -> ReviewDbRef:
    """LA unica resolucion de la ruta de `review.sqlite3`.

    Precedencia: ``S9K_V3_REVIEW_DATABASE_PATH`` (DECLARADA: se valida) >
    carpeta de ``S9K_V3_REVIEW_DECISIONS_PATH`` > defecto del repositorio.
    Una variable presente pero vacia, de solo espacios, relativa o que apunta a
    un directorio NO cae al defecto: levanta `ReviewDbConfigError`.
    """
    crudo = os.environ.get(REVIEW_DB_ENV)
    if crudo is not None:
        return ReviewDbRef(validar_declaracion(crudo), True)
    decisiones = os.environ.get(REVIEW_DECISIONS_ENV)
    if decisiones:
        return ReviewDbRef(Path(decisiones).with_name(REVIEW_DB_FILENAME), False)
    return ReviewDbRef(
        Path(__file__).resolve().parents[3]
        / "viewer" / "output" / "reviews-v3" / REVIEW_DB_FILENAME,
        False,
    )


def default_review_db() -> Path:
    """La ruta de `review.sqlite3` para visor, motor y preflight."""
    return resolve_review_db().path


@dataclass(frozen=True)
class Inspeccion:
    """Resultado de mirar un almacen SIN modificarlo."""

    causa: Optional[str]  # None == valido
    detalle: str
    decisiones: int = 0

    @property
    def valido(self) -> bool:
        return self.causa is None


def _puede(st: "os.stat_result", como: "tuple[int, frozenset]", bit: int) -> bool:
    """¿Permite `st.st_mode` el acceso `bit` (4=r, 2=w) a `como=(uid, gids)`?

    Evalua los BITS de modo y propietario, no `os.access`: `os.access` contesta
    por el proceso que pregunta, y un despliegue que corre como root
    contestaria «si» a todo. Lo que se quiere saber es lo que podra hacer el
    USUARIO DEL SERVICIO.
    """
    uid, gids = como
    if uid == 0:
        return True
    if st.st_uid == uid:
        return bool(st.st_mode & (bit << 6))
    if st.st_gid in gids:
        return bool(st.st_mode & (bit << 3))
    return bool(st.st_mode & bit)


def inspect_review_db(path: Path, *, escritura: bool = False,
                      como: "Optional[tuple[int, frozenset]]" = None) -> Inspeccion:
    """Mira el almacen por EFECTO y sin tocarlo: ni lo crea ni lo repara.

    Distingue las causas (`CAUSA_*`): ausente, no fichero, sin permisos,
    corrupto, schema ajeno. Con ``escritura=True`` exige ademas permiso de
    escritura sobre el fichero. Con ``como=(uid, gids)`` los permisos se
    evaluan para ESE usuario por los bits de modo (el usuario del servicio),
    no para el proceso que mira.
    """
    path = Path(path)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return Inspeccion(CAUSA_NO_EXISTE, CAUSAS[CAUSA_NO_EXISTE])
    except NotADirectoryError:
        return Inspeccion(CAUSA_NO_EXISTE, CAUSAS[CAUSA_NO_EXISTE])
    except PermissionError:
        return Inspeccion(CAUSA_SIN_PERMISOS, CAUSAS[CAUSA_SIN_PERMISOS])
    import stat as _stat  # noqa: PLC0415
    if not _stat.S_ISREG(st.st_mode):
        return Inspeccion(CAUSA_NO_ES_FICHERO, CAUSAS[CAUSA_NO_ES_FICHERO])
    if como is not None:
        legible = _puede(st, como, 4)
        escribible = _puede(st, como, 2)
    else:
        legible = os.access(path, os.R_OK)
        escribible = os.access(path, os.W_OK)
    if not legible or (escritura and not escribible):
        return Inspeccion(CAUSA_SIN_PERMISOS, CAUSAS[CAUSA_SIN_PERMISOS])
    # MIRAR NO ES TOCAR. Una conexion de solo lectura a una base en modo WAL
    # CREA `-wal`/`-shm` junto a ella (y, al ser de solo lectura, no puede
    # borrarlos al cerrar): un preflight o un upgrade «de solo lectura» dejaria
    # ficheros nuevos. Sin WAL con contenido el fichero principal es TODA la
    # verdad y se abre `immutable` (sin locks ni efectos laterales). Con WAL
    # pendiente se abre normalmente: ahi puede haber decisiones aun sin
    # checkpoint y ocultarlas seria contar de menos.
    wal = Path(str(path) + "-wal")
    try:
        hay_wal = wal.exists() and wal.stat().st_size > 0
    except OSError:
        hay_wal = True
    uri = sqlite_uri(path, "ro", immutable=not hay_wal)
    try:
        conexion = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return Inspeccion(CAUSA_SIN_PERMISOS, CAUSAS[CAUSA_SIN_PERMISOS])
    try:
        try:
            columnas = {
                fila[1] for fila in conexion.execute(
                    "PRAGMA table_info(human_decisions)")
            }
        except sqlite3.DatabaseError as exc:
            texto = str(exc).lower()
            if "unable to open" in texto or "readonly" in texto \
                    or "permission" in texto:
                return Inspeccion(CAUSA_SIN_PERMISOS, CAUSAS[CAUSA_SIN_PERMISOS])
            return Inspeccion(CAUSA_CORRUPTA, CAUSAS[CAUSA_CORRUPTA])
        if not COLUMNAS_HUMAN_DECISIONS <= columnas:
            return Inspeccion(CAUSA_SCHEMA_INVALIDO, CAUSAS[CAUSA_SCHEMA_INVALIDO])
        try:
            filas = conexion.execute(
                "SELECT COUNT(*) FROM human_decisions").fetchone()[0]
        except sqlite3.DatabaseError:
            return Inspeccion(CAUSA_CORRUPTA, CAUSAS[CAUSA_CORRUPTA])
    finally:
        conexion.close()
    return Inspeccion(None, "valido", int(filas))
