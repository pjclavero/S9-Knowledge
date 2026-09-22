"""Catalogo de fuentes ingeribles: lo que el operador ELIGE, por su nombre.

EL PROBLEMA QUE RESUELVE
------------------------
`USABLE` en el Slice 2 significa CERO CONOCIMIENTO INTERNO: sin `plan_id`, sin
`workspace`, sin `partida_id`, sin rutas del servidor y sin mandos de backend.
Si el operador tiene que saber algo de eso para completar el paso, el paso no
esta hecho.

La CLI de ingesta exige hoy, como minimo, una ruta de fichero y un `--perfil`.
Ninguna de las dos cosas puede aparecer en una pantalla de operador. Este
modulo es la traduccion:

    lo que ve el operador          lo que el servidor resuelve solo
    ---------------------------    --------------------------------
    "Nota de la Cofradia de        fichero de la fuente
     Ambar" (Markdown, 2 KB)       perfil del workspace
                                   catalogo de entidades
                                   workspace

EL IDENTIFICADOR NO ES UNA RUTA
-------------------------------
El formulario viaja con un `handle`: un slug estable derivado del nombre del
fichero, NO la ruta. Dos razones, y la segunda es la importante:

  1. una ruta en un formulario es una ruta en el HTML, y este repo es publico;
  2. una ruta en un formulario es una ruta que el CLIENTE elige. Aceptarla
     seria dejar que el navegador nombre cualquier fichero del servidor.

La resolucion va siempre en el sentido seguro: se ENUMERA el directorio y se
busca el handle entre los que el servidor mismo genero. Un handle que no salga
de esa enumeracion no existe, y con el no se resuelve ninguna ruta —ni siquiera
para comprobarla—. Por construccion no hay nada que recorrer hacia arriba: no
se concatena nunca la entrada del cliente con un directorio.

DE DONDE SALE EL DIRECTORIO
---------------------------
`S9K_INGEST_SOURCES_DIR`, y si no esta, `examples/ingesta-v3` del repositorio,
que es el material de prueba que el Corte 1 usa. El operador no lo escribe ni
lo ve.

EL UNICO AMBITO QUE NO SALE DE UNA RUTA CLASIFICADA: `AMBITO_PLANO`
-------------------------------------------------------------------
Se nombra aqui, arriba y con todas las letras, porque es EL sitio del arbol
donde alguien podria apoyarse manana sin entender por que es seguro.

En modo boveda todo ambito lo produce `vault_scope.clasificar` a partir de la
ruta. En el catalogo PLANO heredado no hay arbol del que derivar nada, asi que
la fuente se construye con `AMBITO_PLANO`. NO es «el ambito por defecto» ni una
puerta trasera del invariante, y estas son las tres razones, comprobables:

  1. es lo mas RESTRICTIVO —`visibility="secret"`, el mismo defecto fail-closed
     que aplica el estampador—, asi que no puede sobreexponer nada;
  2. lleva `regla="catalogo-plano-sin-boveda"`, que se PINTA en la pantalla:
     no se disfraza de ruta clasificada, se ve que no lo es;
  3. no trae `workspace`, y el alta lo vuelve a EXIGIR
     (`SOURCE_WORKSPACE_UNDECLARED` si el perfil no lo declara), asi que
     tampoco inventa ambito.

Lo que NO debe hacerse con el: usarlo para «rellenar» un ambito en modo boveda.
Si una ruta no se sabe clasificar, la respuesta es un rechazo con su motivo, no
este objeto.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:  # modo normal: el visor importa esto como parte del paquete `app`
    from . import vault_mount
    from .vault_scope import Ambito, NoIngerible, clasificar
except ImportError:  # pragma: no cover - cargado POR RUTA, sin paquete padre
    # COSTURA REAL, no defensa hipotetica. El preflight del ensayo RC
    # (`deploy/scripts/preflight_ensayo_rc.py`) carga ESTE fichero con
    # `spec_from_file_location`, sin paquete padre, para comprobar que el
    # catalogo del producto ve fuentes. Mientras este modulo no tuvo imports
    # relativos eso funciono; al partirlo en tres, los imports dejaron de
    # resolver y el preflight paso a decir PENDIENTE —«no se pudo cargar el
    # catalogo»— en vez de medir. Las dos piezas estaban verdes por separado.
    #
    # Se resuelven los hermanos por RUTA, desde el directorio de este fichero,
    # que es la unica referencia fiable cuando no hay paquete. No se toca
    # `sys.path`: eso alteraria la resolucion de imports del proceso que nos
    # carga, que no es nuestro.
    import importlib.util as _importlib_util

    def _hermano(_nombre: str):
        _ruta = Path(__file__).resolve().parent / f"{_nombre}.py"
        _spec = _importlib_util.spec_from_file_location(
            f"_s9k_sources_catalog_{_nombre}", _ruta)
        if _spec is None or _spec.loader is None:  # pragma: no cover
            raise ImportError(str(_ruta))
        _modulo = _importlib_util.module_from_spec(_spec)
        # Registrado ANTES de ejecutar: los `@dataclass` del modulo cargado
        # resuelven sus anotaciones por `sys.modules[__module__]`.
        sys.modules[_spec.name] = _modulo
        _spec.loader.exec_module(_modulo)
        return _modulo

    vault_mount = _hermano("vault_mount")
    _vault_scope = _hermano("vault_scope")
    Ambito = _vault_scope.Ambito
    NoIngerible = _vault_scope.NoIngerible
    clasificar = _vault_scope.clasificar

__all__ = [
    "FuenteDisponible",
    "CatalogoNoDisponible",
    "directorio_de_fuentes",
    "raiz_de_bovedas",
    "modo_boveda",
    "listar_fuentes",
    "listar_fuentes_boveda",
    "rechazos_de_boveda",
    "resolver",
    "EXTENSIONES_SOPORTADAS",
    "NOMBRE_PERFIL",
    "NOMBRE_CATALOGO",
    "AMBITO_PLANO",
    "MOTIVO_AUXILIAR",
    "ENV_RAIZ_BOVEDAS",
    "ENV_DIRECTORIO_DE_FUENTES",
    "ubicacion_declarada",
    "ENV_EXIGIR_MONTAJE",
]

#: Extensiones que el nucleo de ingesta declara saber leer
#: (`knowledge_v3.pipeline.ingest_cli.KIND_BY_EXTENSION`). Se listan aqui en vez
#: de importarse porque el visor no debe depender de data-engine para PINTAR una
#: lista: si el motor no esta, el panel sigue sabiendo decir que hay.
EXTENSIONES_SOPORTADAS = {
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".txt": "Texto",
    ".text": "Texto",
    ".note": "Nota",
}

#: Ficheros de configuracion del workspace: acompanan a las fuentes, pero NO son
#: fuentes. Ofrecerlos en el desplegable seria ofrecer al operador que ingiera
#: la ontologia del propio workspace.
NOMBRE_PERFIL = "perfil-operador.json"
NOMBRE_CATALOGO = "catalogo-workspace.json"
_NO_SON_FUENTES = {NOMBRE_PERFIL, NOMBRE_CATALOGO, "README.md"}

#: Motivo con el que se DECLARA un fichero auxiliar (perfil, catalogo, README)
#: encontrado durante el recorrido de una boveda. Existe para que no haya
#: ninguna salida muda: ver el comentario en `listar_fuentes_boveda`.
MOTIVO_AUXILIAR = "AUXILIAR_NO_ES_FUENTE"


class CatalogoNoDisponible(RuntimeError):
    """El directorio de fuentes no existe o no se puede leer.

    Ausencia declarada, NO lista vacia: "no hay fuentes" y "no se puede mirar"
    son dos afirmaciones distintas sobre produccion, y la segunda no se pinta
    como la primera (misma doctrina que `AUSENCIA != CERO` en el panel B).
    """


#: El ambito de una fuente del catalogo PLANO heredado (un unico directorio sin
#: estructura de boveda: el material de ejemplo del repositorio). No hay arbol
#: del que derivar nada, asi que se declara lo mas restrictivo —`secret`, el
#: mismo defecto fail-closed que el estampador— y se dice POR QUE REGLA se
#: obtuvo. No es una ruta clasificada: es la ausencia de boveda, nombrada.
AMBITO_PLANO = Ambito(
    carpeta_juego="",
    partida_id=None,
    visibility="secret",
    regla="catalogo-plano-sin-boveda",
)

#: Raiz del arbol de bovedas (el MONTAJE rclone). Su presencia es lo que
#: enciende el modo boveda: descubrimiento jerarquico + clasificacion.
ENV_RAIZ_BOVEDAS = "S9K_VAULT_ROOT"
#: Interruptor EXPLICITO para no exigir montaje activo (suites, y despliegues
#: donde la raiz es un directorio local). El defecto es exigirlo.
ENV_EXIGIR_MONTAJE = "S9K_VAULT_REQUIRE_MOUNT"


@dataclass(frozen=True)
class FuenteDisponible:
    """Una fuente elegible, tal y como se le ofrece al operador.

    `ruta` NO se serializa a la pantalla: existe para que el servidor resuelva.
    Lo que viaja al navegador son `handle`, `titulo`, `formato`, `tamano` y el
    AMBITO —que si se pinta, y a proposito: es lo que el operador necesita para
    ver que va a ingerir algo marcado `secret` de la partida que cree—.

    EL INVARIANTE, HECHO IMPOSIBLE DE SEPARAR
    -----------------------------------------
    `ambito` es un campo OBLIGATORIO y SIN DEFECTO. No es una convencion ni una
    comprobacion que alguien pueda olvidarse de llamar: es la firma del
    constructor. Ninguna rama de este modulo —ni de ningun otro— puede producir
    una fuente sin ambito, porque `FuenteDisponible(...)` sin `ambito` es un
    `TypeError` antes de que exista el objeto.

    Es exactamente la garantia que pide el encargo: hacer el catalogo recursivo
    sin activar la clasificacion no da un resultado peor, no da NINGUN
    resultado.
    """

    handle: str
    titulo: str
    formato: str
    tamano_bytes: int
    ruta: Path
    ambito: Ambito
    perfil: Path
    catalogo: Optional[Path] = None

    def para_pantalla(self) -> dict:
        """La fuente SIN nada del servidor dentro. Es lo unico que se pinta."""
        return {
            "handle": self.handle,
            "titulo": self.titulo,
            "formato": self.formato,
            "tamano_bytes": self.tamano_bytes,
            # EL AMBITO SE VE. Una garantia que no se pinta no la puede
            # comprobar quien opera: `workspace`, `partida_id` y `visibility`
            # inicial viajan a la pantalla. No son datos internos del servidor
            # —no hay rutas aqui—, son lo que el operador esta autorizando.
            "ambito": self.ambito.para_pantalla(),
        }


def _slug(nombre: str) -> str:
    """Handle estable y opaco derivado del NOMBRE del fichero, sin la ruta."""
    base = unicodedata.normalize("NFKD", Path(nombre).stem)
    base = base.encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or "fuente"


def _titulo(nombre: str) -> str:
    """Nombre humano: el del fichero, sin extension y con espacios."""
    base = Path(nombre).stem.replace("_", " ").replace("-", " ").strip()
    return base[:1].upper() + base[1:] if base else nombre


def directorio_de_fuentes(env: Optional[dict] = None) -> Path:
    """Directorio de donde salen las fuentes elegibles."""
    entorno = env if env is not None else os.environ
    crudo = entorno.get("S9K_INGEST_SOURCES_DIR")
    if crudo:
        return Path(crudo)
    # `viewer/app/sources_catalog.py` -> raiz del repositorio.
    return Path(__file__).resolve().parents[2] / "examples" / "ingesta-v3"


#: Variable con la que el operador declara donde estan las fuentes cuando no
#: hay arbol de bovedas.
ENV_DIRECTORIO_DE_FUENTES = "S9K_INGEST_SOURCES_DIR"


def ubicacion_declarada(env: Optional[dict] = None) -> bool:
    """¿Ha DECLARADO el operador donde esta la boveda de este despliegue?

    EL MATERIAL DE EJEMPLO DEL REPOSITORIO NO ES UNA DECLARACION
    ------------------------------------------------------------
    `directorio_de_fuentes()` cae en `examples/ingesta-v3/` cuando no se
    declara nada, y ese directorio trae un `perfil-operador.json`. Sin este
    predicado, el workspace de un fichero de EJEMPLO gobierna un despliegue.

    Este predicado es la UNICA definicion de «hay boveda declarada», y lo
    consultan LOS DOS LADOS del camino:

      - la autoridad de workspace (`authz/autoridad_workspace.py`), para no
        dejar que el perfil del ejemplo mande en los permisos;
      - el catalogo de fuentes (`listar_fuentes`), para no derivar de el el
        ambito de una ingesta.

    Tenerlo en un solo lado fue exactamente el defecto: authz respetaba la
    regla y la ingesta segui­a derivando del ejemplo, con lo que la DOBLE
    AUTORIDAD volvia intacta y ademas muda. Medido con la configuracion de
    fabrica: authz `leyenda`, ambito de la fuente `ws-cofradia`.

    Es coherente con lo que el preflight ya exige por su cuenta:
    `S9K_INGEST_SOURCES_DIR` sin declarar es ROJO porque «el catalogo caeria en
    los ejemplos del repositorio».
    """
    entorno = env if env is not None else os.environ
    for clave in (ENV_RAIZ_BOVEDAS, ENV_DIRECTORIO_DE_FUENTES):
        valor = entorno.get(clave)
        if isinstance(valor, str) and valor.strip():
            return True
    return False


def raiz_de_bovedas(env: Optional[dict] = None) -> Optional[Path]:
    """Raiz del arbol de bovedas, si este despliegue tiene una."""
    entorno = env if env is not None else os.environ
    crudo = entorno.get(ENV_RAIZ_BOVEDAS)
    return Path(crudo) if crudo else None


def modo_boveda(env: Optional[dict] = None) -> bool:
    """`True` si hay arbol de bovedas: descubrimiento jerarquico."""
    return raiz_de_bovedas(env) is not None


def _exigir_montaje(env: Optional[dict] = None) -> bool:
    entorno = env if env is not None else os.environ
    crudo = str(entorno.get(ENV_EXIGIR_MONTAJE, "1")).strip().lower()
    return crudo not in {"0", "false", "no", ""}


def _workspace_declarado(perfil: Path) -> str:
    """El workspace que el PERFIL DE LA BOVEDA declara. No se infiere nunca.

    `l5r/` es un nombre EXTERNO de carpeta. Que corresponda al workspace
    `leyenda` es una DECLARACION del operador en el perfil, no algo que el
    codigo pueda deducir del nombre. Por eso no hay aqui ninguna tabla global
    carpeta -> workspace: hay un perfil por boveda, y dice lo suyo.

    Se reutiliza el mecanismo que YA existe (el alta lee `workspace` de un
    perfil JSON), no se inventa otro.
    """
    datos = json.loads(perfil.read_text(encoding="utf-8"))
    if not isinstance(datos, dict):
        raise ValueError("el perfil de la boveda no es un objeto JSON")
    ws = datos.get("workspace")
    if not isinstance(ws, str) or not ws.strip():
        raise ValueError("el perfil de la boveda no declara `workspace`")
    return ws.strip()


def _perfiles_por_juego(raiz: Path, carpetas: list[str]) -> tuple[dict, list[dict]]:
    """Perfil (y catalogo) de cada carpeta de juego, mas los rechazos.

    Una carpeta de juego SIN perfil valido no aporta ninguna fuente: sin perfil
    no hay `workspace` DECLARADO, y sin workspace declarado la alternativa seria
    inventarlo a partir del nombre de la carpeta. FALLA CERRADO.
    """
    perfiles: dict[str, dict] = {}
    rechazos: list[dict] = []
    for carpeta in carpetas:
        perfil = raiz / carpeta / NOMBRE_PERFIL
        catalogo = raiz / carpeta / NOMBRE_CATALOGO
        try:
            ws = _workspace_declarado(perfil)
        except (OSError, ValueError) as exc:
            rechazos.append({
                "motivo": "PERFIL_DE_BOVEDA_INVALIDO",
                "ruta": carpeta,
                "detalle": (
                    "el perfil de esta boveda no declara a que juego "
                    "corresponde la carpeta (%s). El nombre de la carpeta es "
                    "un nombre EXTERNO y no se da por supuesto: sin esa "
                    "declaracion no se ingiere nada de esta boveda"
                    % type(exc).__name__
                ),
            })
            continue
        perfiles[carpeta] = {
            "workspace": ws,
            "perfil": perfil,
            "catalogo": catalogo if catalogo.is_file() else None,
        }
    return perfiles, rechazos


def listar_fuentes_boveda(
    env: Optional[dict] = None,
) -> tuple[list[FuenteDisponible], list[dict]]:
    """DESCUBRIMIENTO JERARQUICO con clasificacion, indivisibles.

    Devuelve `(fuentes, rechazos)`. Todo FICHERO recorrido acaba en uno de los
    dos sitios: o es una fuente CON ambito, o es un rechazo CON motivo. No hay
    tercera salida, y en particular no existe la que habia antes —descartado en
    silencio, sin warning y con `stderr` vacio—.

    El alcance de esa afirmacion, acotado a proposito para que no prometa de
    mas: se refiere a los FICHEROS que el recorrido visita. Un DIRECTORIO no
    genera entrada por si mismo —lo hacen los ficheros que contiene—, y un
    directorio vacio no produce ni fuente ni rechazo porque no hay nada que
    ingerir en el.

    Los auxiliares (`_NO_SON_FUENTES`) tampoco son una excepcion: se declaran
    con `MOTIVO_AUXILIAR`. Lo fueron hasta que un revisor encontro que un
    `README.md` anidado salia en silencio.

    El orden es el que impone la frontera: primero se VERIFICA el montaje
    (`vault_mount.inspeccionar`), y solo despues se enumera. Un mountpoint sin
    montaje activo parece un directorio vacio; aqui levanta.
    """
    raiz = raiz_de_bovedas(env)
    if raiz is None:  # pragma: no cover - lo decide `listar_fuentes`
        raise CatalogoNoDisponible("no hay raiz de bovedas configurada")

    montaje = vault_mount.inspeccionar(raiz, exigir_montaje=_exigir_montaje(env))
    if not montaje.utilizable:
        # AUSENCIA DECLARADA. `MONTAJE_AUSENTE` no se degrada a lista vacia:
        # es el caso por el que existe todo este modulo.
        raise CatalogoNoDisponible(f"{montaje.estado.value}: {montaje.detalle}")

    carpetas = [n for n in (montaje.entradas or []) if (raiz / n).is_dir()]
    perfiles, rechazos = _perfiles_por_juego(raiz, carpetas)

    fuentes: list[FuenteDisponible] = []
    vistos: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(raiz):
        dirnames.sort()
        for nombre in sorted(filenames):
            absoluta = Path(dirpath) / nombre
            relativa = absoluta.relative_to(raiz).as_posix()
            if nombre in _NO_SON_FUENTES:
                # AUXILIAR, PERO DECLARADO. Antes esto era un `continue` mudo, y
                # era la TERCERA SALIDA que el docstring negaba: un `README.md`
                # con contenido real dentro de `compartido/lore/` se iba sin ser
                # fuente ni rechazo, en silencio, a cualquier profundidad. Es el
                # defecto de este corte en forma residual —no puede producir un
                # ambito erroneo ni sobreexponer, porque excluye; pero descartar
                # sin avisar es exactamente lo que se vino a corregir—.
                #
                # Ahora se emite un rechazo. Cuesta una linea en la pantalla y
                # convierte un silencio en un hecho visible: el operador ve que
                # su `README.md` no se ingiere, en vez de preguntarse por que no
                # aparece.
                rechazos.append({
                    "motivo": MOTIVO_AUXILIAR,
                    "ruta": relativa,
                    "detalle": (
                        "acompana a las fuentes pero NO es una fuente: es "
                        "material auxiliar del workspace. No se ingiere, y se "
                        "dice para que no desaparezca sin explicacion"
                    ),
                })
                continue

            # CLASIFICAR ES EL PASO 1, NO UN FILTRO POSTERIOR. Se hace antes de
            # mirar la extension o el tamano: una ruta que no se sabe clasificar
            # no llega siquiera a evaluarse como candidata.
            try:
                ambito = clasificar(relativa)
            except NoIngerible as exc:
                rechazos.append(exc.para_pantalla())
                continue

            declarado = perfiles.get(ambito.carpeta_juego)
            if declarado is None:
                # Su carpeta de juego ya fue rechazada por perfil invalido: la
                # boveda entera esta rechazada y no se repite fila por fila.
                continue
            ambito = ambito.con_workspace(declarado["workspace"])

            formato = EXTENSIONES_SOPORTADAS.get(absoluta.suffix.lower())
            if formato is None:
                rechazos.append({
                    "motivo": "FORMATO_NO_SOPORTADO",
                    "ruta": relativa,
                    "detalle": (
                        "la extension `%s` no esta entre las que el nucleo "
                        "declara saber leer"
                        % (absoluta.suffix.lower() or "(ninguna)")
                    ),
                })
                continue
            try:
                tamano = absoluta.stat().st_size
            except OSError as exc:
                rechazos.append({
                    "motivo": "FUENTE_ILEGIBLE",
                    "ruta": relativa,
                    "detalle": f"no se pudo medir la fuente: {type(exc).__name__}",
                })
                continue

            handle = _slug(nombre)
            if handle in vistos:
                vistos[handle] += 1
                handle = f"{handle}-{vistos[handle]}"
            else:
                vistos[handle] = 1

            fuentes.append(FuenteDisponible(
                handle=handle,
                titulo=_titulo(nombre),
                formato=formato,
                tamano_bytes=tamano,
                ruta=absoluta,
                ambito=ambito,
                perfil=declarado["perfil"],
                catalogo=declarado["catalogo"],
            ))

    return (sorted(fuentes, key=lambda f: (f.ambito.workspace or "", f.titulo)),
            sorted(rechazos, key=lambda r: r["ruta"]))


def rechazos_de_boveda(env: Optional[dict] = None) -> list[dict]:
    """Solo los rechazos. Para pintarlos: lo que NO entra tiene que verse."""
    if not modo_boveda(env):
        return []
    return listar_fuentes_boveda(env)[1]


def listar_fuentes(env: Optional[dict] = None) -> list[FuenteDisponible]:
    """Fuentes elegibles, ordenadas por titulo. Levanta si no se puede mirar.

    Con raiz de bovedas configurada delega en `listar_fuentes_boveda`: el modo
    jerarquico. Sin ella conserva el catalogo PLANO heredado, que sigue siendo
    NO recursivo A PROPOSITO —un directorio suelto no tiene esquema del que
    derivar ambito, asi que recorrerlo en profundidad seria justamente la
    recursion sin clasificacion que el invariante prohibe—.

    Un handle repetido (dos ficheros cuyo nombre produce el mismo slug) se
    desambigua con un sufijo numerico: dos entradas con el mismo handle harian
    que la eleccion del operador fuera ambigua y se resolviera "la primera que
    aparezca", que es un resultado que depende del orden del sistema de
    ficheros.
    """
    if modo_boveda(env):
        return listar_fuentes_boveda(env)[0]

    raiz = directorio_de_fuentes(env)
    try:
        if not raiz.is_dir():
            raise CatalogoNoDisponible(f"{raiz}: no es un directorio")
        entradas = sorted(raiz.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        raise CatalogoNoDisponible(f"{raiz}: {exc}") from exc

    perfil_raiz = raiz / NOMBRE_PERFIL
    catalogo_raiz = raiz / NOMBRE_CATALOGO
    catalogo_raiz = catalogo_raiz if catalogo_raiz.is_file() else None

    # EL CATALOGO PLANO TAMBIEN DECLARA SU AMBITO. No porque tenga arbol, sino
    # porque `FuenteDisponible` no admite fuentes sin el: aqui se ve que el
    # invariante no tiene puerta trasera ni siquiera en el camino heredado.
    try:
        if not ubicacion_declarada(env):
            # EL OTRO LADO DE LA MISMA REGLA. Sin ubicacion declarada, el
            # perfil que hay bajo `examples/` es material del repositorio, no
            # una declaracion del operador: no da ambito a nada. El ambito se
            # queda SIN workspace y el alta falla cerrada con su codigo
            # (`SOURCE_WORKSPACE_UNDECLARED`), que es donde el operador ya sabe
            # leerlo. AUSENCIA DECLARADA, no cero.
            raise ValueError("ubicacion de boveda sin declarar")
        ambito_plano = AMBITO_PLANO.con_workspace(_workspace_declarado(perfil_raiz))
    except (OSError, ValueError):
        # Sin perfil legible no hay workspace declarado. Se conserva el ambito
        # sin workspace: el alta lo vuelve a exigir y falla con su codigo, que
        # es donde el operador ya sabe leerlo.
        ambito_plano = AMBITO_PLANO

    fuentes: list[FuenteDisponible] = []
    vistos: dict[str, int] = {}
    for entrada in entradas:
        if not entrada.is_file() or entrada.name in _NO_SON_FUENTES:
            continue
        formato = EXTENSIONES_SOPORTADAS.get(entrada.suffix.lower())
        if formato is None:
            continue
        handle = _slug(entrada.name)
        if handle in vistos:
            vistos[handle] += 1
            handle = f"{handle}-{vistos[handle]}"
        else:
            vistos[handle] = 1
        try:
            tamano = entrada.stat().st_size
        except OSError:
            continue
        fuentes.append(FuenteDisponible(
            handle=handle,
            titulo=_titulo(entrada.name),
            formato=formato,
            tamano_bytes=tamano,
            ruta=entrada,
            ambito=ambito_plano,
            perfil=perfil_raiz,
            catalogo=catalogo_raiz,
        ))
    return sorted(fuentes, key=lambda f: f.titulo)


def resolver(handle: str, env: Optional[dict] = None) -> Optional[FuenteDisponible]:
    """La fuente cuyo handle coincide, o ``None``.

    Se resuelve ENUMERANDO y comparando, nunca componiendo una ruta con lo que
    llego del cliente. Un handle con `../`, una ruta absoluta o un nombre
    inventado simplemente no coincide con nada y sale `None`: no hay ninguna
    rama en la que la cadena del cliente llegue a tocar el sistema de ficheros.
    """
    if not handle:
        return None
    for fuente in listar_fuentes(env):
        if fuente.handle == handle:
            return fuente
    return None


def perfil_y_catalogo(env: Optional[dict] = None) -> tuple[Path, Optional[Path]]:
    """Perfil (obligatorio) y catalogo (opcional) del workspace de las fuentes.

    Los elige el SERVIDOR a partir del directorio, no el operador: son
    exactamente el tipo de dato interno que el Slice 2 prohibe pedirle.
    """
    raiz = directorio_de_fuentes(env)
    perfil = raiz / NOMBRE_PERFIL
    catalogo = raiz / NOMBRE_CATALOGO
    return perfil, (catalogo if catalogo.is_file() else None)
