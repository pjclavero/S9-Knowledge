# -*- coding: utf-8 -*-
"""AUTORIDAD CANONICA DEL WORKSPACE — un solo sitio que lo decide, y dice de donde.

CORTE F-2. Antes de este modulo habia CUATRO declaraciones del workspace y DOS
de ellas eran autoridades efectivas DISTINTAS, cada una alimentando medio
producto:

  - **el entorno** (`S9K_DEFAULT_WORKSPACE`) -> `existencia.workspace_canonico()`
    -> `/admin/partidas` (campo de solo lectura) y el contexto de visibilidad
    (`allowed_workspaces`, singleton para todo principal);
  - **el perfil de la boveda** (`sources_catalog._workspace_declarado`) -> el
    ambito de la fuente -> el paquete de propuestas -> `/v3/review` ->
    `v3_apply` -> el writer -> Neo4j.

Las otras dos no resuelven nada: son PUERTAS que comparan
(`S9K_WRITER_WORKSPACE` en el gate del writer, y el workspace del ensayo en el
preflight de despliegue).

## El defecto, medido, no supuesto

Con los valores de fabrica las dos autoridades DIVERGEN: el entorno dice
`leyenda` y el perfil del material de ejemplo dice otro. Consecuencias medidas
antes de este corte:

  1. `POST /admin/partidas/grant` con el workspace del perfil devuelve 400. Desde
     la web NO se puede conceder acceso de partida al workspace donde acaba el
     conocimiento. Falla cerrado, y **sin ningun aviso**.
  2. Un revisor con `allowed_workspaces={leyenda}` lee y MUTA material del
     workspace del perfil: la cola de revision se filtra por partida, no por
     workspace (decision documentada en `docs/v3/49-multipartida-diseno.md`,
     que este corte NO revierte).

## Lo que este modulo decide

    EL PERFIL DE LA BOVEDA ES LA AUTORIDAD CANONICA.
    EL ENTORNO ES UN FALLBACK EXPLICITO, NO UN COMPETIDOR SILENCIOSO.

Y todo resultado viene **sellado con su procedencia**: quien pregunta puede
decir si el valor que tiene en la mano lo declaro el operador en el perfil o lo
heredo del entorno. Un valor pelado no se distingue de otro valor pelado; por
eso aqui nunca se devuelve una cadena suelta.

## AUSENCIA != CERO, y la decision se declara

«No hay perfil» **no es** «el workspace por defecto» por si solo. El contrato
que este modulo fija, y que se declara aqui en voz alta para que se pueda
discutir:

  - Hay perfil legible y el entorno **calla** -> manda el perfil.
  - Hay perfil legible y el entorno dice **lo mismo** -> manda el perfil
    (el entorno no aporta autoridad: solo confirma).
  - Hay perfil legible y el entorno dice **otra cosa** -> MANDA EL PERFIL.
    `valor` = el del perfil, procedencia `PERFIL_DE_BOVEDA`, y codigo
    `WORKSPACE_AUTHORITY_DIVERGENT`: se RESUELVE y se REPORTA a la vez.
    Devolver `""` aqui —como se hacia antes— convertia un diagnostico de
    configuracion en una denegacion total del producto, y no eliminaba la doble
    autoridad: la disfrazaba. El veredicto y el diagnostico son ORTOGONALES.
  - **No hay perfil** (ausente, ilegible, o SIN UBICACION DECLARADA) y el
    entorno habla -> se usa el entorno, procedencia `FALLBACK_ENTORNO`. El
    fallback esta PERMITIDO por este contrato, y por eso se dice.
    «Sin ubicacion declarada» es la regla de `sources_catalog.ubicacion_declarada`:
    si el operador no dijo donde esta la boveda, el perfil que hay bajo
    `examples/` es material del repositorio y no gobierna nada — NI AQUI NI EN
    LA INGESTA. Los dos lados consultan el MISMO predicado; aplicarlo a uno
    solo reintroducia la doble autoridad, y ademas muda.
  - No hay perfil y el entorno calla -> `valor = ""`,
    `WORKSPACE_AUTHORITY_UNDETERMINED`. Sin ambito no se concede nada.
  - Hay **varios** perfiles con workspaces distintos (arbol de bovedas con mas
    de un juego) -> `valor = ""`, `WORKSPACE_AUTHORITY_MULTIPLE_PROFILES`.

## Por que «varios perfiles» NO elige uno

Porque el consumidor de este valor es `allowed_workspaces`, que hoy es un
SINGLETON del despliegue y todo el codigo de autorizacion asume que lo es.
Convertirlo en un conjunto por principal es el modelo «usuario -> varios
workspaces» que la documentacion difiere expresamente, y NO entra en este
corte. Elegir uno en silencio seria inventar una autoridad; se NOMBRA el caso
y se falla cerrado.

## NO SE FABRICA CAUSALIDAD

El diagnostico de una divergencia dice QUE declara cada autoridad y DONDE lo
declara. No dice cual esta mal, porque este modulo no lo sabe: las dos son
declaraciones del operador.

## EL TECHO DE LO QUE ESTE MODULO VE

- Ve el perfil de la **raiz de fuentes** y, en modo boveda, el de cada carpeta
  de juego de primer nivel. No recorre mas hondo: la jerarquia de partidas
  cuelga de la carpeta de juego y no vuelve a declarar `workspace`.
- NO ve `S9K_WRITER_WORKSPACE` ni el workspace del ensayo: son puertas, no
  autoridades, y compararlas es trabajo del gate del writer y del preflight.
- NO observa el valor que un proceso YA cargado tenga en memoria: resuelve
  sobre el entorno que se le pasa. Quien quiera la politica EFECTIVA de una
  peticion tiene que llamar aqui en la peticion, no cachear el resultado.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

#: Variable de entorno que declara el workspace del despliegue. Aqui deja de
#: ser autoridad y pasa a ser fallback: ver el contrato del docstring.
ENV_WORKSPACE_POR_DEFECTO = "S9K_DEFAULT_WORKSPACE"

# --- Procedencias -----------------------------------------------------------
#: El valor lo declaro el operador en el perfil de la boveda. AUTORIDAD.
PROCEDENCIA_PERFIL = "PERFIL_DE_BOVEDA"
#: El valor viene del entorno PORQUE no habia perfil. FALLBACK DECLARADO.
PROCEDENCIA_FALLBACK = "FALLBACK_ENTORNO"
#: No hay valor. Nunca acompana a un `valor` no vacio.
PROCEDENCIA_NINGUNA = "SIN_AUTORIDAD"

# --- Codigos ----------------------------------------------------------------
# Se publican CODIGOS, nunca texto libre del motor ni rutas internas. Quien
# pinte esto lo traduce; un codigo que no se sepa traducir se NOMBRA.
COD_PERFIL = "WORKSPACE_AUTHORITY_PROFILE"
COD_PERFIL_CONFIRMADO = "WORKSPACE_AUTHORITY_PROFILE_CONFIRMED"
COD_FALLBACK = "WORKSPACE_AUTHORITY_ENV_FALLBACK"
COD_DIVERGENTE = "WORKSPACE_AUTHORITY_DIVERGENT"
COD_INDETERMINADO = "WORKSPACE_AUTHORITY_UNDETERMINED"
COD_VARIOS_PERFILES = "WORKSPACE_AUTHORITY_MULTIPLE_PROFILES"
#: No se pudo ni MIRAR el perfil (falta el catalogo del producto). AUSENCIA de
#: medicion, que NO es ausencia de declaracion: por eso no cae en el fallback.
COD_CATALOGO_INALCANZABLE = "WORKSPACE_AUTHORITY_CATALOG_UNAVAILABLE"

#: Los codigos con los que NO hay workspace efectivo: todos ellos deniegan.
#:
#: RONDA 3. `COD_DIVERGENTE` **ya no esta aqui**, y esa es la correccion del
#: corte. Devolver `""` ante una discrepancia trataba la divergencia como un
#: error que impide resolver, y dejaba el producto inservible con la
#: configuracion de fabrica (medido: `allowed_workspaces == set()`, 60 rojos).
#: Una discrepancia no es una ausencia de autoridad: es una autoridad —el
#: perfil— y una declaracion secundaria que no coincide. Manda el perfil, y la
#: discrepancia SE REPORTA en vez de gobernar.
CODIGOS_FAIL_CLOSED = frozenset(
    {COD_INDETERMINADO, COD_VARIOS_PERFILES, COD_CATALOGO_INALCANZABLE}
)


@dataclass(frozen=True)
class Autoridad:
    """El workspace efectivo, su procedencia y lo que declaro cada fuente.

    `valor == ""` significa SIEMPRE denegar: no hay ambito resoluble. Nunca es
    «el workspace vacio».
    """

    valor: str
    procedencia: str
    codigo: str
    #: Lo que declara el perfil de boveda. `""` si no hay ninguno legible.
    declarado_por_perfil: str
    #: Lo que declara el entorno. `""` si la variable no esta o esta vacia.
    declarado_por_entorno: str
    #: Cuantos perfiles legibles se encontraron (0, 1 o mas).
    perfiles_legibles: int = 0

    # -----------------------------------------------------------------
    # EL VEREDICTO Y EL DIAGNOSTICO SON DOS COSAS, Y SE LEEN POR SEPARADO
    # -----------------------------------------------------------------
    # RONDA 3. El vicio de forma que habia aqui era mezclarlos en un solo
    # valor: `valor=""` significaba a la vez «no resuelvo» y «hay una
    # anomalia», de modo que el resolvedor NO PODIA reportar la discrepancia
    # sin dejar de resolver — y un diagnostico de configuracion se convertia en
    # una denegacion total del producto.
    #
    # Ahora son ortogonales, y el estado `resuelto=True` + `diverge=True` es
    # legitimo y esperado: «workspace efectivo = A» y «configuracion divergente
    # = si» a la vez.

    @property
    def resuelto(self) -> bool:
        """EL VEREDICTO: ¿hay workspace efectivo? Nada mas."""
        return bool(self.valor)

    @property
    def diverge(self) -> bool:
        """EL DIAGNOSTICO: ¿el entorno contradice al perfil? Nada mas.

        AUSENCIA NO ES DIVERGENCIA, y se decide aqui en voz alta:

          - `WORKSPACE_AUTHORITY_DIVERGENT` = hay perfil Y el entorno dice otra
            cosa. HAY autoridad (el perfil) y HAY anomalia. `diverge` es True y
            `resuelto` tambien.
          - `WORKSPACE_AUTHORITY_UNDETERMINED` / `..._CATALOG_UNAVAILABLE` =
            NO hay perfil, o no se pudo mirar. Eso NO es una discrepancia: es
            una ausencia. `diverge` es False, y `resuelto` tambien False.
          - `..._MULTIPLE_PROFILES` = varias bovedas discordantes. Tampoco es
            «el entorno contradice»: es que no hay UNA autoridad. `diverge`
            False, `resuelto` False.

        Confundirlos haria que un despliegue sin bovedas se pintase como
        «configuracion divergente», que es exactamente la clase de falso aviso
        que el simetrico existe para impedir.
        """
        return self.codigo == COD_DIVERGENTE

    @property
    def configuracion_divergente(self) -> bool:
        """Alias explicito de `diverge`, para leerlo junto a `resuelto`.

        `autoridad.resuelto and autoridad.configuracion_divergente` es el
        estado que este corte hace posible y que antes era irrepresentable.
        """
        return self.diverge

    def diagnostico(self) -> str:
        """Frase para el operador. Sin rutas, sin texto del motor, sin secretos.

        Dice QUE declara cada autoridad y COMO se llama cada declaracion. No
        dice cual esta mal: este modulo no lo sabe.
        """
        if self.codigo == COD_DIVERGENTE:
            return (
                f"{COD_DIVERGENTE}: el perfil de la boveda declara "
                f"'{self.declarado_por_perfil}' y {ENV_WORKSPACE_POR_DEFECTO} "
                f"declara '{self.declarado_por_entorno}'. MANDA EL PERFIL: el "
                f"workspace efectivo es '{self.valor}' en todo el producto "
                "—permisos, revision, apply y grafo—. La declaracion del "
                "entorno NO gobierna nada, pero sigue siendo una discrepancia "
                "sin resolver: corrigela o retirala."
            )
        if self.codigo == COD_VARIOS_PERFILES:
            return (
                f"{COD_VARIOS_PERFILES}: se encontraron "
                f"{self.perfiles_legibles} perfiles de boveda con workspaces "
                "distintos. Este despliegue resuelve UN workspace efectivo "
                "(el contexto de visibilidad es un singleton), asi que no se "
                "elige ninguno."
            )
        if self.codigo == COD_CATALOGO_INALCANZABLE:
            return (
                f"{COD_CATALOGO_INALCANZABLE}: no se pudo cargar el catalogo "
                "del producto, asi que no se pudo mirar si hay perfil de "
                "boveda. NO se cae al entorno: no poder mirar no es no haber."
            )
        if self.codigo == COD_INDETERMINADO:
            return (
                f"{COD_INDETERMINADO}: no hay perfil de boveda legible y "
                f"{ENV_WORKSPACE_POR_DEFECTO} no declara nada. Sin ambito "
                "efectivo no se resuelve ni se concede nada."
            )
        if self.codigo == COD_FALLBACK:
            return (
                f"{COD_FALLBACK}: no hay perfil de boveda legible; se usa "
                f"{ENV_WORKSPACE_POR_DEFECTO}='{self.valor}' como fallback "
                "declarado."
            )
        if self.codigo == COD_PERFIL_CONFIRMADO:
            return (
                f"{COD_PERFIL_CONFIRMADO}: el perfil de la boveda declara "
                f"'{self.valor}' y el entorno dice lo mismo."
            )
        return (
            f"{COD_PERFIL}: el perfil de la boveda declara '{self.valor}'; "
            f"{ENV_WORKSPACE_POR_DEFECTO} no declara nada."
        )


class CatalogoNoAlcanzable(RuntimeError):
    """No se pudo cargar el catalogo del producto: no se pudo MIRAR el perfil.

    Existe para que «no hay perfil» y «no pude mirar si lo hay» no se
    confundan. Confundirlos mandaria al fallback del entorno justo cuando la
    autoridad es indeterminable, que es el falso verde mas caro de este corte.
    """


class WorkspaceSinAutoridad(RuntimeError):
    """Se pidio el workspace efectivo y no hay uno resoluble.

    Lleva el CODIGO y el diagnostico; nunca una ruta ni un secreto.
    """

    def __init__(self, autoridad: "Autoridad") -> None:
        super().__init__(autoridad.diagnostico())
        self.codigo = autoridad.codigo
        self.autoridad = autoridad


def _limpio(valor: object) -> str:
    return valor.strip() if isinstance(valor, str) and valor.strip() else ""


def declaraciones_de_perfil(
    env: Optional[dict] = None, catalogo: object = None
) -> list[str]:
    """Los workspaces DECLARADOS por los perfiles de boveda alcanzables.

    Devuelve la lista ORDENADA y SIN REPETIDOS de valores distintos. Lista
    vacia = no hay perfil legible (ausente o invalido): AUSENCIA, no cero.

    No re-deriva ninguna ruta: usa los resolvedores del propio producto
    (`sources_catalog`), que es el codigo que de verdad alimenta el ambito de
    la fuente. Derivarla aqui crearia la segunda verdad que este modulo existe
    para eliminar.
    """
    entorno = env if env is not None else os.environ
    if catalogo is not None:
        # Inyectado: el preflight de despliegue corre FUERA del paquete `app` y
        # carga los modulos del producto por ruta. Se acepta el suyo en vez de
        # re-derivar aqui la lectura del perfil, que seria la segunda verdad.
        sources_catalog = catalogo
    else:
        try:
            from app import sources_catalog  # noqa: PLC0415
        except Exception as exc:
            raise CatalogoNoAlcanzable(type(exc).__name__) from exc

    candidatos = _candidatos_de_perfil(entorno, sources_catalog)

    valores: list[str] = []
    for perfil in candidatos:
        try:
            ws = sources_catalog._workspace_declarado(perfil)
        except Exception:
            # Perfil ausente o invalido. FALLA CERRADO por omision: esta
            # boveda no aporta declaracion, y si ninguna lo hace la lista sale
            # vacia y el llamante lo trata como AUSENCIA.
            continue
        ws = _limpio(ws)
        if ws and ws not in valores:
            valores.append(ws)
    return sorted(valores)


def _candidatos_de_perfil(entorno, sources_catalog) -> list:
    """Las rutas de perfil que este despliegue DECLARA. Sin leerlas.

    EL MATERIAL DE EJEMPLO DEL REPOSITORIO NO ES UNA DECLARACION DEL OPERADOR
    ------------------------------------------------------------------------
    RONDA 3, y es una decision de contrato, no un apano para la suite.

    Al hacer del perfil la autoridad efectiva aparecio esto: si el operador no
    declara NI `S9K_VAULT_ROOT` NI `S9K_INGEST_SOURCES_DIR`, el resolvedor de
    rutas del producto cae en `examples/ingesta-v3/` del propio repositorio —y
    ese directorio trae un `perfil-operador.json`—. Con la regla ingenua, el
    workspace de un fichero de EJEMPLO habria pasado a gobernar los permisos de
    un despliegue entero. Medido: 142 pruebas rojas, y no por la semantica
    nueva, sino por esto.

    Asi que la autoridad del perfil exige que el operador haya DECLARADO donde
    esta la boveda. Si no lo ha declarado no hay perfil que valga: la lista sale
    vacia y el llamante lo trata como AUSENCIA —con lo que manda el fallback del
    entorno, que es el contrato ya declarado en el docstring del modulo—.

    Esto es coherente con lo que el preflight ya exige por su cuenta:
    `S9K_INGEST_SOURCES_DIR` sin declarar es ROJO precisamente porque «el
    catalogo caeria en los ejemplos del repositorio».

    AUSENCIA != DIVERGENCIA: un despliegue que no declara boveda no tiene una
    discrepancia, tiene una ausencia, y no se le pinta ningun aviso.
    """
    raiz_bovedas = sources_catalog.raiz_de_bovedas(entorno)
    if raiz_bovedas is not None:
        try:
            carpetas = sorted(p for p in raiz_bovedas.iterdir() if p.is_dir())
        except OSError:
            carpetas = []
        return [c / sources_catalog.NOMBRE_PERFIL for c in carpetas]
    if not sources_catalog.ubicacion_declarada(entorno):
        # El operador no ha declarado donde esta la boveda. No hay perfil con
        # autoridad: lo que haya en el arbol del repositorio no lo es.
        #
        # EL PREDICADO ES EL DEL CATALOGO, no una copia. Tenerlo aqui por
        # separado fue lo que permitio aplicar la regla a un solo lado del
        # camino: authz la respetaba y la ingesta no.
        return []
    return [
        sources_catalog.directorio_de_fuentes(entorno)
        / sources_catalog.NOMBRE_PERFIL
    ]


#: LA CACHE DE RESOLUCION SE RETIRO, Y ESTA ES LA RAZON MEDIDA
#: -----------------------------------------------------------
#: Hubo aqui una cache por FIRMA del arbol de perfiles (`mtime_ns` + `st_size`,
#: y despues tambien `st_ctime_ns`). Servia para no hacer E/S de disco en cada
#: peticion.
#:
#: EL COSTE REAL, SIN CACHE, MEDIDO EN ESTA MAQUINA:
#:     sin boveda declarada (la configuracion de fabrica) :   3.6 us
#:     boveda plana declarada, un perfil                  :  50.9 us
#:     arbol de bovedas declarado, doce juegos            : 584.8 us
#: El caso de fabrica no toca el disco en absoluto: sin ubicacion declarada no
#: hay perfil candidato que mirar.
#:
#: Se retira porque **ninguna firma basada en `stat()` es fiable aqui**, y se
#: midio en esta misma maquina:
#:
#:   1. Con `mtime_ns` + `st_size`: reescribir el perfil con un valor DEL MISMO
#:      TAMANO y restaurar el mtime con `os.utime` dejaba la cache sirviendo la
#:      autoridad VIEJA. No es exotico: `rsync -a`, `cp -p`, `tar -x` y toda
#:      restauracion de copia preservan mtime, y las bovedas llegan por carpeta
#:      sincronizada.
#:   2. Anadir `st_ctime_ns` —que `os.utime` no puede restaurar— parecia
#:      cerrarlo, y en una prueba suelta lo cerraba. Pero **la granularidad de
#:      `ctime` en este sistema de ficheros es de UN SEGUNDO**: dos escrituras
#:      dentro del mismo segundo producen exactamente el mismo `st_ctime_ns`, y
#:      la cache volvia a quedarse rancia. Medido:
#:          f1 = (..., 1790064485256000000, 24, 1790064485256000000)
#:          f2 = (..., 1790064485256000000, 24, 1790064485256000000)
#:      La version de una sola prueba pasaba solo porque cruzaba el tic.
#:
#: Esto es la autoridad de AUTORIZACION: una respuesta rancia autoriza sobre un
#: workspace que ya nadie declara. Entre 100 us y una garantia que solo se
#: cumple si el reloj cae bien, se elige la garantia. El coste queda DECLARADO
#: y medido, no escondido; si algun dia molesta, el remedio correcto es cachear
#: con invalidacion explicita (un evento de recarga), no adivinar por `stat()`.


def resolver_por_peticion(env: Optional[dict] = None) -> Autoridad:
    """El workspace efectivo de ESTA peticion. Sin cache, a proposito.

    Se conserva como punto de entrada propio —y no se sustituye por `resolver`
    en los llamantes— para que el coste por peticion siga teniendo un nombre al
    que apuntar, y para que quien vuelva a plantear una cache lea primero por
    que se quito la anterior (ver el comentario de arriba).
    """
    return resolver(env)


def declaracion_de_entorno(env: Optional[dict] = None) -> str:
    """Lo que declara el entorno. `""` si no declara nada.

    REGRESION REAL, CAZADA Y CORREGIDA (ronda 3)
    --------------------------------------------
    Esto leia `os.environ` PELADO. Pero la declaracion de entorno del producto
    no es la variable cruda: es `Settings.S9K_DEFAULT_WORKSPACE`, que TIENE UN
    DEFECTO (`"leyenda"`) y por tanto declara algo aunque la variable no este.

    Al cablear authz a este resolvedor, un despliegue sin la variable —toda la
    suite heredada— pasaba de resolver `"leyenda"` a resolver `""`, es decir a
    DENEGAR. Sintoma medido: `/reviews` devolvia 404 porque el workspace
    efectivo era cadena vacia. 14 pruebas ajenas en rojo por esto, y ninguna
    tenia nada que ver con la semantica nueva.

    Cuando el llamante pasa un `env` EXPLICITO (el preflight, las pruebas), ese
    diccionario es la verdad y no se consulta nada mas: si no declara, no
    declara. El defecto de `Settings` solo entra cuando se esta resolviendo
    para el PRODUCTO, que es cuando `env is None`.
    """
    if env is not None:
        return _limpio(env.get(ENV_WORKSPACE_POR_DEFECTO))
    crudo = _limpio(os.environ.get(ENV_WORKSPACE_POR_DEFECTO))
    if crudo:
        return crudo
    try:
        from app.config import get_settings  # noqa: PLC0415

        return _limpio(get_settings().S9K_DEFAULT_WORKSPACE)
    except Exception:
        return ""


def resolver(env: Optional[dict] = None, catalogo: object = None) -> Autoridad:
    """El workspace efectivo de este despliegue, con su procedencia.

    Es el UNICO punto que lo decide. Ver el contrato completo en el docstring
    del modulo; el resumen es: manda el perfil; el entorno es fallback SOLO
    cuando no hay perfil; y si los dos hablan y no coinciden, sigue mandando el
    perfil y la discrepancia se REPORTA (`WORKSPACE_AUTHORITY_DIVERGENT`), que
    no es lo mismo que dejar de resolver.
    """
    del_entorno = declaracion_de_entorno(env)
    try:
        del_perfil = declaraciones_de_perfil(env, catalogo)
    except CatalogoNoAlcanzable:
        return Autoridad(
            valor="",
            procedencia=PROCEDENCIA_NINGUNA,
            codigo=COD_CATALOGO_INALCANZABLE,
            declarado_por_perfil="",
            declarado_por_entorno=del_entorno,
            perfiles_legibles=0,
        )

    if len(del_perfil) > 1:
        return Autoridad(
            valor="",
            procedencia=PROCEDENCIA_NINGUNA,
            codigo=COD_VARIOS_PERFILES,
            declarado_por_perfil="",
            declarado_por_entorno=del_entorno,
            perfiles_legibles=len(del_perfil),
        )

    if del_perfil:
        unico = del_perfil[0]
        if del_entorno and del_entorno != unico:
            # RONDA 3 — LA CORRECCION DEL CORTE.
            #
            # Antes esto devolvia `""`: se trataba la discrepancia como un
            # error que impide resolver. Eso NO elimina la doble autoridad, la
            # convierte en una denegacion total.
            #
            # Lo correcto es lo que el operador nombro: el perfil ES la
            # autoridad, el entorno pasa a declaracion secundaria que NO
            # gobierna, y la discrepancia se REPORTA. Se resuelve al perfil y
            # se conserva `COD_DIVERGENTE`, que es lo que mantiene el aviso en
            # las tres pantallas y el rojo del preflight.
            #
            # Esto NO es alinear los valores para que la divergencia deje de
            # verse (lo que la pieza 5 prohibe): los dos valores siguen siendo
            # distintos y siguen viendose. Lo que cambia es que uno de los dos
            # deja de ser autoridad.
            return Autoridad(
                valor=unico,
                procedencia=PROCEDENCIA_PERFIL,
                codigo=COD_DIVERGENTE,
                declarado_por_perfil=unico,
                declarado_por_entorno=del_entorno,
                perfiles_legibles=1,
            )
        return Autoridad(
            valor=unico,
            procedencia=PROCEDENCIA_PERFIL,
            codigo=COD_PERFIL_CONFIRMADO if del_entorno else COD_PERFIL,
            declarado_por_perfil=unico,
            declarado_por_entorno=del_entorno,
            perfiles_legibles=1,
        )

    if del_entorno:
        return Autoridad(
            valor=del_entorno,
            procedencia=PROCEDENCIA_FALLBACK,
            codigo=COD_FALLBACK,
            declarado_por_perfil="",
            declarado_por_entorno=del_entorno,
            perfiles_legibles=0,
        )

    return Autoridad(
        valor="",
        procedencia=PROCEDENCIA_NINGUNA,
        codigo=COD_INDETERMINADO,
        declarado_por_perfil="",
        declarado_por_entorno="",
        perfiles_legibles=0,
    )


def exigir(env: Optional[dict] = None, catalogo: object = None) -> Autoridad:
    """Como `resolver`, pero LEVANTA si no hay autoridad.

    Para los caminos que no pueden seguir sin ambito: antes de operar, no
    despues.
    """
    autoridad = resolver(env, catalogo)
    if not autoridad.resuelto:
        raise WorkspaceSinAutoridad(autoridad)
    return autoridad


def aviso_para_pantalla(env: Optional[dict] = None, catalogo: object = None):
    """El aviso de divergencia que pinta CUALQUIER pantalla, o `None`.

    RONDA 2 · D1. Antes este aviso lo montaba `routers/admin.py` a mano, y por
    eso existia en UNA pantalla y en ninguna otra: `/v3/review` y el panel de
    operaciones seguian MUDOS. Y `/v3/review` es justamente donde el dano no es
    un 400 recuperable sino **una decision humana que MUTA material de otro
    workspace** — el defecto nº2 que este mismo corte documenta.

    Aqui vive el UNICO productor. Quien quiera avisar lo pide; no lo rearma.
    Devolver `None` cuando no hay divergencia es lo que mantiene el SIMETRICO:
    una configuracion coherente no ve ni un adorno.

    NO FABRICA CAUSALIDAD: dice que HAY dos declaraciones y cuales son. No
    atribuye a la divergencia ninguna accion concreta del operador — esa
    atribucion se hace, y solo con COMPARACION EXACTA, en el punto de operacion
    (`admin.py::admin_partidas_grant`), no en un cartel.

    Devuelve un diccionario de CODIGOS y valores ya declarados; nunca una ruta,
    un secreto ni texto libre del motor.
    """
    resuelta = resolver(env, catalogo)
    if not resuelta.diverge:
        return None
    return {
        "codigo": resuelta.codigo,
        "diagnostico": resuelta.diagnostico(),
        "procedencia": resuelta.procedencia,
        "declarado_por_perfil": resuelta.declarado_por_perfil,
        "declarado_por_entorno": resuelta.declarado_por_entorno,
        "diverge": True,
    }
