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
  - Hay perfil legible y el entorno dice **otra cosa** -> NO se elige ninguno.
    `valor = ""`, codigo `WORKSPACE_AUTHORITY_DIVERGENT`. Fail-closed CON
    diagnostico, que es lo que faltaba.
  - **No hay perfil** (ausente o ilegible) y el entorno habla -> se usa el
    entorno, procedencia `FALLBACK_ENTORNO`. El fallback esta PERMITIDO por
    este contrato, y por eso se dice.
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
CODIGOS_FAIL_CLOSED = frozenset(
    {COD_DIVERGENTE, COD_INDETERMINADO, COD_VARIOS_PERFILES,
     COD_CATALOGO_INALCANZABLE}
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

    @property
    def resuelto(self) -> bool:
        return bool(self.valor)

    @property
    def diverge(self) -> bool:
        return self.codigo == COD_DIVERGENTE

    def diagnostico(self) -> str:
        """Frase para el operador. Sin rutas, sin texto del motor, sin secretos.

        Dice QUE declara cada autoridad y COMO se llama cada declaracion. No
        dice cual esta mal: este modulo no lo sabe.
        """
        if self.codigo == COD_DIVERGENTE:
            return (
                f"{COD_DIVERGENTE}: el perfil de la boveda declara "
                f"'{self.declarado_por_perfil}' y {ENV_WORKSPACE_POR_DEFECTO} "
                f"declara '{self.declarado_por_entorno}'. El perfil es la "
                "autoridad canonica y el entorno solo puede ser fallback, asi "
                "que con las dos hablando y diciendo cosas distintas no se "
                "resuelve ningun workspace. Corrige una de las dos "
                "declaraciones; no se elige por ti."
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

    candidatos: list = []
    raiz_bovedas = sources_catalog.raiz_de_bovedas(entorno)
    if raiz_bovedas is not None:
        try:
            carpetas = sorted(
                p for p in raiz_bovedas.iterdir() if p.is_dir()
            )
        except OSError:
            carpetas = []
        candidatos.extend(c / sources_catalog.NOMBRE_PERFIL for c in carpetas)
    else:
        candidatos.append(
            sources_catalog.directorio_de_fuentes(entorno)
            / sources_catalog.NOMBRE_PERFIL
        )

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


def declaracion_de_entorno(env: Optional[dict] = None) -> str:
    """Lo que declara el entorno. `""` si no declara nada."""
    entorno = env if env is not None else os.environ
    return _limpio(entorno.get(ENV_WORKSPACE_POR_DEFECTO))


def resolver(env: Optional[dict] = None, catalogo: object = None) -> Autoridad:
    """El workspace efectivo de este despliegue, con su procedencia.

    Es el UNICO punto que lo decide. Ver el contrato completo en el docstring
    del modulo; el resumen es: manda el perfil, el entorno es fallback, y si
    los dos hablan y no coinciden no manda ninguno.
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
            return Autoridad(
                valor="",
                procedencia=PROCEDENCIA_NINGUNA,
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
