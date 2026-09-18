"""Clasificacion RUTA -> AMBITO de la boveda. La tabla del contrato, y nada mas.

QUE ES ESTO
-----------
La reproduccion EJECUTABLE de la tabla `§3 Correspondencia carpeta -> ambito`
del documento de esquema de bovedas. No la rediseña: la traduce. Cada fila de
la tabla es una entrada de `_REGLAS` y cada entrada cita su fila.

POR QUE EXISTE, Y POR QUE NO PUEDE LLEGAR TARDE
-----------------------------------------------
El catalogo de fuentes era PLANO (`raiz.iterdir()`), asi que descartaba los
subdirectorios en silencio: cuatro niveles entraban, uno salia, sin warning y
con `stderr` vacio. La correccion obvia —hacerlo recursivo— es PEOR que el
defecto, porque la ruta viaja pero nada aguas abajo deriva ambito de ella: el
`workspace` sale de un unico perfil y el payload encolado no lleva ni
`partida_id` ni `visibility`. Un `rglob` a secas meteria `reservado/`,
`secretos/` y `compartido/` TODOS con el mismo ambito unico de la raiz.

Por eso la recursion y la clasificacion ENTRAN JUNTAS, y la union no es una
convencion sino una imposibilidad de construccion: `FuenteDisponible` exige
`ambito` como campo OBLIGATORIO (ver `sources_catalog`), de modo que no existe
ninguna rama de codigo capaz de producir una fuente sin ambito. Quitar la
clasificacion no degrada el resultado: impide construirlo.

LO QUE ESTE MODULO NO HACE, A PROPOSITO
---------------------------------------
  * NO decide permisos. La carpeta propone un valor INICIAL de `visibility`;
    a partir de ahi manda `KnowledgeVisibilityV1` y el motor.
  * NO concede `known_by`. `known_by` se produce en UN solo sitio, dentro de
    `stamp()`, y este modulo no lo nombra siquiera. Una carpeta no otorga
    conocimiento a nadie.
  * NO deriva `known_from_session`. `sesion-NN` es CONTRATO DE ENTRADA —como se
    permite que se llame una carpeta— y no identidad global ni declaracion de
    revelacion. Derivarla seria exactamente conceder conocimiento por
    inferencia de directorio.
  * NO traduce carpeta -> workspace. El nombre externo de la carpeta del juego
    (`l5r/`) es un nombre EXTERNO; su equivalencia con el workspace
    (`leyenda`) se DECLARA en el perfil de la boveda, no se infiere aqui. Este
    modulo devuelve la carpeta observada en `carpeta_juego` y quien llama la
    resuelve contra el perfil.

FALLA CERRADO, Y DISTINGUE DOS ROJOS
------------------------------------
    ruta conocida + valida   -> Ambito
    ruta desconocida         -> NO INGERIBLE, motivo RUTA_DESCONOCIDA
    ruta conocida INCOHERENTE-> NO INGERIBLE, motivo RUTA_INCOHERENTE

Son dos diagnosticos distintos porque son dos errores distintos del operador:
«esto no va en la boveda» y «esto va aqui pero esta mal nombrado». Colapsarlos
en un unico «no se ingiere» obliga a adivinar cual de los dos ha pasado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional, Sequence

__all__ = [
    "Ambito",
    "NoIngerible",
    "MOTIVO_DESCONOCIDA",
    "MOTIVO_INCOHERENTE",
    "MOTIVO_RESERVADA",
    "MOTIVO_NO_INGERIBLE",
    "CARPETA_PLANTILLA",
    "RE_SESION",
    "REGLAS_DOCUMENTADAS",
    "clasificar",
]

#: `_plantilla` con guion bajo: la ancla arriba al ordenar y la deja fuera de la
#: ingesta por convencion VISIBLE, no por una regla escondida. Hoy no existe en
#: el arbol medido; el parser debe saber que hacer si aparece, y lo sabe.
CARPETA_PLANTILLA = "_plantilla"

#: Contrato de ENTRADA para el nombre de una sesion. `sesion-01`, no `sesion 1`:
#: el espacio complica rutas y sin cero de relleno la sesion 10 se ordena antes
#: que la 2. Se admite mas de dos digitos para no poner un techo en 99.
#: NO es un identificador global: solo dice como puede llamarse la carpeta.
RE_SESION = re.compile(r"^sesion-[0-9]{2,}$")

MOTIVO_DESCONOCIDA = "RUTA_DESCONOCIDA"
MOTIVO_INCOHERENTE = "RUTA_INCOHERENTE"
MOTIVO_RESERVADA = "RUTA_RESERVADA"
MOTIVO_NO_INGERIBLE = "RUTA_NO_INGERIBLE"


@dataclass(frozen=True)
class Ambito:
    """El ambito de UNA ruta, derivado de la tabla §3.

    `carpeta_juego` es el nombre EXTERNO de la carpeta, no el workspace: la
    equivalencia la declara el perfil de la boveda. `workspace` se rellena
    despues, por quien lee ese perfil, y por eso es opcional aqui.
    """

    carpeta_juego: str
    partida_id: Optional[str]
    visibility: str
    regla: str
    workspace: Optional[str] = None

    def con_workspace(self, workspace: str) -> "Ambito":
        """El mismo ambito con el workspace DECLARADO por el perfil."""
        if not workspace:
            raise ValueError("workspace vacio: el perfil de la boveda debe declararlo")
        return Ambito(
            carpeta_juego=self.carpeta_juego,
            partida_id=self.partida_id,
            visibility=self.visibility,
            regla=self.regla,
            workspace=workspace,
        )

    def para_pantalla(self) -> dict:
        """Lo que el operador puede ver del ambito. Sin rutas del servidor."""
        return {
            "workspace": self.workspace,
            "partida_id": self.partida_id,
            "visibility": self.visibility,
            "regla": self.regla,
        }


class NoIngerible(Exception):
    """La ruta no se ingiere, y se dice POR QUE.

    `motivo` es el codigo estable (desconocida / incoherente / reservada) y
    `detalle` la explicacion para el operador. La ruta completa NO se guarda
    aqui: este objeto acaba en pantalla y el repositorio es publico. Se guarda
    la ruta RELATIVA a la raiz de bovedas, que no revela nada del servidor.
    """

    def __init__(self, motivo: str, ruta_relativa: str, detalle: str):
        self.motivo = motivo
        self.ruta_relativa = ruta_relativa
        self.detalle = detalle
        super().__init__(f"{motivo}: {ruta_relativa}: {detalle}")

    def para_pantalla(self) -> dict:
        return {
            "motivo": self.motivo,
            "ruta": self.ruta_relativa,
            "detalle": self.detalle,
        }


#: La tabla §3, fila por fila, tal y como esta escrita en el documento. Se
#: declara como DATO para que la suite pueda cruzarla con lo implementado en
#: vez de volver a escribir las mismas filas en un test.
#:
#:   (patron de la fila, partida?, visibility, texto de la fila)
REGLAS_DOCUMENTADAS: tuple[tuple[str, bool, Optional[str], str], ...] = (
    ("<juego>/compartido/**", False, "player", "capa compartida, visible por jugador"),
    ("<juego>/reservado/**", False, "narrator", "capa compartida, reservada al narrador"),
    ("<juego>/partidas/<p>/aportaciones/<p>-<jugador>/**", True, "secret",
     "aportacion de un jugador, lo mas restrictivo hasta revision"),
    ("<juego>/partidas/<p>/material-jugadores/**", True, "player", "material de jugadores"),
    ("<juego>/partidas/<p>/sesiones/**", True, "player", "sesiones de la partida"),
    ("<juego>/partidas/<p>/notas-narrador/**", True, "narrator", "notas del narrador"),
    ("<juego>/partidas/<p>/secretos/**", True, "secret", "secretos de la partida"),
    ("<juego>/partidas/<p>/personajes/**", True, "narrator", "fichas de PJ"),
    ("<juego>/referencia/**", False, "reference", "material externo citable"),
    ("<juego>/entrada/**", False, "secret", "sin clasificar, lo mas restrictivo"),
    ("<juego>/archivo/**", False, None, "retirado: NO se ingiere nunca"),
    ("_plantilla/**", False, None, "plantilla: NO se ingiere"),
    ("cualquier otra ruta", False, None, "NO se ingiere"),
)

#: Carpetas de PRIMER nivel dentro de `<juego>/` cuyo ambito es de capa juego
#: (`partida_id = None`). El `**` de la tabla: todo lo que cuelgue hereda.
#: `lore/` y `manuales/` NO aparecen: son ORGANIZATIVAS y transparentes para el
#: ambito, asi que caen dentro del `**` de su contenedor sin regla propia.
#: Anadir una carpeta organizativa nueva nunca cambia la visibilidad de nada.
_CAPA_JUEGO: dict[str, str] = {
    "compartido": "player",
    "reservado": "narrator",
    "referencia": "reference",
    "entrada": "secret",
}

#: Carpetas de primer nivel dentro de `<juego>/` que existen en el arbol y NO
#: se ingieren. Se nombran EXPLICITAMENTE para que su rechazo sea "retirado, no
#: se ingiere nunca" y no "no se que es esto".
_NO_INGERIBLE_JUEGO: dict[str, str] = {
    "archivo": "material retirado: no se ingiere nunca (fila `<juego>/archivo/**`)",
}

#: Carpetas de primer nivel dentro de `<juego>/partidas/<p>/`.
_CAPA_PARTIDA: dict[str, str] = {
    "material-jugadores": "player",
    "sesiones": "player",
    "notas-narrador": "narrator",
    "secretos": "secret",
    "personajes": "narrator",
    "aportaciones": "secret",
}

_RAIZ_PARTIDAS = "partidas"
_APORTACIONES = "aportaciones"
_SESIONES = "sesiones"


def _no(motivo: str, partes: Sequence[str], detalle: str) -> NoIngerible:
    return NoIngerible(motivo, "/".join(partes), detalle)


def clasificar(ruta_relativa: str | PurePosixPath) -> Ambito:
    """El ambito de `ruta_relativa`, o `NoIngerible` con su motivo.

    `ruta_relativa` es la ruta del FICHERO relativa a la raiz de bovedas, con
    separadores `/`. No se toca el sistema de ficheros: es una funcion pura
    sobre la ruta, para que la suite pueda barrer la tabla entera sin montar
    nada y para que no haya forma de que una comprobacion de ambito dependa de
    lo que exista en disco en ese momento.
    """
    bruta = PurePosixPath(str(ruta_relativa))
    partes = [p for p in bruta.parts if p not in ("", ".")]

    if not partes:
        raise NoIngerible(MOTIVO_DESCONOCIDA, str(ruta_relativa),
                          "ruta vacia: no hay nada que clasificar")
    if any(p == ".." for p in partes):
        raise NoIngerible(MOTIVO_INCOHERENTE, "/".join(partes),
                          "la ruta sube por encima de la raiz de bovedas")
    if bruta.is_absolute():
        raise NoIngerible(MOTIVO_INCOHERENTE, str(ruta_relativa),
                          "se esperaba una ruta RELATIVA a la raiz de bovedas")

    # `_plantilla/` es lo primero que se mira, y a proposito: se copia al anadir
    # un juego, asi que contiene una replica del arbol entero. Si se clasificara
    # despues, cada fichero suyo caeria en la regla de la carpeta que imita y
    # entraria con el ambito de la carpeta REAL que no es.
    if partes[0] == CARPETA_PLANTILLA:
        raise _no(MOTIVO_RESERVADA, partes,
                  "`_plantilla/` es la plantilla que se copia al anadir un "
                  "juego: reservada, no se ingiere (fila `_plantilla/**`)")

    juego = partes[0]
    if len(partes) < 2:
        raise _no(MOTIVO_DESCONOCIDA, partes,
                  "fichero suelto en la raiz de bovedas: fuera del esquema, "
                  "ninguna fila de la tabla lo cubre")

    seccion = partes[1]

    if seccion in _NO_INGERIBLE_JUEGO:
        raise _no(MOTIVO_NO_INGERIBLE, partes, _NO_INGERIBLE_JUEGO[seccion])

    if seccion in _CAPA_JUEGO:
        if len(partes) < 3:
            raise _no(MOTIVO_DESCONOCIDA, partes,
                      f"`{juego}/{seccion}/` no contiene ningun fichero en la "
                      "ruta dada; la fila cubre `**`, no la carpeta misma")
        return Ambito(
            carpeta_juego=juego,
            partida_id=None,
            visibility=_CAPA_JUEGO[seccion],
            regla=f"<juego>/{seccion}/**",
        )

    if seccion != _RAIZ_PARTIDAS:
        raise _no(MOTIVO_DESCONOCIDA, partes,
                  f"`{juego}/{seccion}/` no es ninguna seccion del esquema; "
                  "un fichero fuera del esquema es un error de colocacion que "
                  "debe verse, no un hecho que entra con visibilidad adivinada")

    # --- capa de partida -------------------------------------------------
    if len(partes) < 3:
        raise _no(MOTIVO_DESCONOCIDA, partes,
                  "`partidas/` sin partida: no hay ambito de partida que derivar")
    partida = partes[2]
    if len(partes) < 4:
        raise _no(MOTIVO_DESCONOCIDA, partes,
                  f"fichero suelto en `partidas/{partida}/`: ninguna fila "
                  "cubre la raiz de una partida, solo sus secciones")
    sub = partes[3]
    if sub not in _CAPA_PARTIDA:
        raise _no(MOTIVO_DESCONOCIDA, partes,
                  f"`partidas/{partida}/{sub}/` no es ninguna seccion de "
                  "partida del esquema")

    if sub == _APORTACIONES:
        # `<partida>-<jugador>` se CONSERVA tal cual y es deliberado: Nextcloud
        # fija el `file_target` al crear el compartido y NO lo actualiza, asi
        # que renombrarlo obligaria a rehacer todos los compartidos.
        #
        # El prefijo se VALIDA contra la partida del contexto, pero la partida
        # del contexto es `partes[2]` —la carpeta bajo `partidas/`—, que es la
        # unica autoridad. El prefijo solo puede DESMENTIRLA, nunca definirla.
        if len(partes) < 5:
            raise _no(MOTIVO_DESCONOCIDA, partes,
                      "fichero suelto en `aportaciones/`: el esquema exige una "
                      "subcarpeta por jugador, `<partida>-<jugador>/`")
        buzon = partes[4]
        prefijo = f"{partida}-"
        if not buzon.startswith(prefijo) or len(buzon) == len(prefijo):
            raise _no(MOTIVO_INCOHERENTE, partes,
                      f"el buzon `{buzon}` no corresponde a la partida "
                      f"`{partida}`: el esquema exige `<partida>-<jugador>/`. "
                      "La partida del contexto manda; el nombre del buzon la "
                      "desmiente, asi que no se ingiere")
        if len(partes) < 6:
            raise _no(MOTIVO_DESCONOCIDA, partes,
                      f"`{buzon}/` no contiene ningun fichero en la ruta dada")

    if sub == _SESIONES:
        if len(partes) < 5:
            raise _no(MOTIVO_DESCONOCIDA, partes,
                      "fichero suelto en `sesiones/`: el esquema exige una "
                      "carpeta por sesion, `sesion-NN/`")
        sesion = partes[4]
        if not RE_SESION.match(sesion):
            raise _no(MOTIVO_INCOHERENTE, partes,
                      f"`{sesion}` no cumple el contrato de entrada de una "
                      "sesion (`sesion-NN`, dos digitos o mas, sin espacios). "
                      "Es solo como puede llamarse la carpeta: no es un "
                      "identificador global ni declara revelacion alguna")
        if len(partes) < 6:
            raise _no(MOTIVO_DESCONOCIDA, partes,
                      f"`{sesion}/` no contiene ningun fichero en la ruta dada")
        # Todo lo que cuelgue de `sesion-NN/` hereda: `videos/`,
        # `transcripciones/` y las que el operador anada son carpetas de
        # FORMATO, transparentes para el ambito. No aparecen en la tabla a
        # proposito y no pueden modificarlo.

    return Ambito(
        carpeta_juego=juego,
        partida_id=partida,
        visibility=_CAPA_PARTIDA[sub],
        regla=(f"<juego>/partidas/<p>/{sub}/"
               + ("<p>-<jugador>/**" if sub == _APORTACIONES else "**")),
    )
