"""La FRONTERA DE ADQUISICION: el montaje rclone, mirado en la capa de fichero.

POR QUE ESTE MODULO EXISTE
--------------------------
`main` consume Nextcloud por MONTAJE (`S9K_RCLONE_MOUNT`, ver
`app.health.checks.check_nextcloud_rclone`), no por un cliente WebDAV. Este
modulo no abre ninguna conexion: se limita a distinguir, ANTES de enumerar,
en cual de los estados posibles esta esa frontera.

EL CASO TRAICIONERO, Y LA RAZON DE TODO ESTO
--------------------------------------------
Un mountpoint que EXISTE pero SIN montaje activo parece un directorio local
perfectamente vacio. No hay excepcion que ignorar, no hay `rc != 0`, no hay
nada en `stderr`. Un `if not path.exists(): return []` lo da por bueno y un
`glob()` pelado devuelve `[]`. Las dos cosas se leen como «la boveda esta
vacia», que es la conclusion CONTRARIA a la correcta: la boveda puede estar
llena y lo que falta es el montaje.

No es hipotetico. La credencial que alimenta este montaje dio un 401 real en
produccion, con `stdout` vacio y `rc=1`, justo en la medicion que decidia el
alcance de este trabajo. Tratarlo como lista vacia habria concluido «boveda
plana» —exactamente la decision equivocada—.

De ahi la regla: se VERIFICA que esta realmente montado, y SOLO DESPUES se
enumera. `MONTAJE_VACIO` y `MONTAJE_AUSENTE` son dos estados distintos y este
modulo no los deja colapsar: son valores distintos de un enum cerrado, y el
que no esta montado NO trae listado (`entradas is None`), asi que quien llama
no puede confundir «mire y no habia nada» con «no pude mirar».
"""
from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

__all__ = ["EstadoMontaje", "Montaje", "inspeccionar", "MontajeNoDisponible"]


class EstadoMontaje(str, Enum):
    """Estados de la frontera. Enum CERRADO: no hay "otro"."""

    #: Montado, legible y CON contenido.
    MONTAJE_CON_CONTENIDO = "MOUNT_AVAILABLE_CONTENT"
    #: Montado y legible, pero sin ninguna entrada. La boveda esta vacia DE
    #: VERDAD: se ha mirado dentro de un montaje real.
    MONTAJE_VACIO = "MOUNT_AVAILABLE_EMPTY"
    #: La ruta existe y es un directorio, pero NO es un punto de montaje. Este
    #: es el caso que parece un directorio local vacio y no lo es.
    MONTAJE_AUSENTE = "MOUNT_MISSING"
    #: Montado, pero no se puede listar (permisos).
    MONTAJE_ILEGIBLE = "MOUNT_UNREADABLE"
    #: FUSE roto: el `stat` falla con ENOTCONN / ESTALE. El proceso rclone se
    #: fue y dejo el mountpoint colgado.
    MONTAJE_ROTO = "MOUNT_STALE"
    #: La ruta no existe siquiera.
    RUTA_AUSENTE = "PATH_MISSING"
    #: Cualquier otro fallo del sistema de ficheros, declarado como fallo y no
    #: silenciado.
    ERROR = "ERROR"


#: Estados en los que ENUMERAR seria mentir. Se declara como conjunto para que
#: quien llama no tenga que repetir la lista y para que la suite pueda cruzarlo.
_NO_ENUMERABLES = frozenset({
    EstadoMontaje.MONTAJE_AUSENTE,
    EstadoMontaje.MONTAJE_ILEGIBLE,
    EstadoMontaje.MONTAJE_ROTO,
    EstadoMontaje.RUTA_AUSENTE,
    EstadoMontaje.ERROR,
})

#: `errno` que delatan un FUSE muerto. `ENOTCONN` es el que deja rclone al
#: morir; `ESTALE` el clasico de un NFS caido.
_ERRNO_ROTO = frozenset({errno.ENOTCONN, errno.ESTALE})


@dataclass(frozen=True)
class Montaje:
    """El veredicto sobre la frontera.

    `entradas` es `None` cuando NO se ha podido mirar, y una lista cuando si.
    La distincion es estructural a proposito: `None` no es iterable, asi que un
    consumidor que trate «no pude mirar» como «no habia nada» revienta en vez
    de devolver una boveda falsamente vacia.
    """

    estado: EstadoMontaje
    ruta: Path
    detalle: str
    entradas: Optional[list[str]] = None

    @property
    def utilizable(self) -> bool:
        """Solo si se ha verificado el montaje Y se ha podido enumerar."""
        return self.estado not in _NO_ENUMERABLES

    @property
    def vacio_de_verdad(self) -> bool:
        """Vacio COMPROBADO dentro de un montaje real. Nunca por defecto."""
        return self.estado is EstadoMontaje.MONTAJE_VACIO

    def para_pantalla(self) -> dict:
        """Sin la ruta del servidor: este repositorio es publico."""
        return {
            "estado": self.estado.value,
            "detalle": self.detalle,
            "utilizable": self.utilizable,
            "entradas": None if self.entradas is None else len(self.entradas),
        }


class MontajeNoDisponible(RuntimeError):
    """No se pudo mirar la boveda. AUSENCIA declarada, NO lista vacia."""

    def __init__(self, montaje: Montaje):
        self.montaje = montaje
        self.estado = montaje.estado
        super().__init__(f"{montaje.estado.value}: {montaje.detalle}")


def inspeccionar(ruta: Path, *, exigir_montaje: bool = True) -> Montaje:
    """Clasifica la frontera. NO enumera hasta haber verificado el montaje.

    `exigir_montaje=False` existe para la suite y para los despliegues en los
    que el directorio de fuentes es local (el material de ejemplo del
    repositorio, que no esta montado y nunca lo estara). Es un interruptor
    EXPLICITO: el defecto es exigirlo, de modo que olvidarse no degrada a
    «cualquier directorio vale».
    """
    p = Path(ruta)

    # 1. ¿Existe? Un `stat` que falla con ENOTCONN/ESTALE NO es "no existe":
    #    es un FUSE roto, y `Path.exists()` lo devuelve como False, que es
    #    justamente como se pierde la distincion.
    try:
        p.stat()
    except OSError as exc:
        if exc.errno in _ERRNO_ROTO:
            return Montaje(EstadoMontaje.MONTAJE_ROTO, p,
                           "el punto de montaje esta colgado (FUSE roto): el "
                           "proceso que lo servia ya no responde")
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return Montaje(EstadoMontaje.RUTA_AUSENTE, p,
                           "la ruta de la boveda no existe")
        return Montaje(EstadoMontaje.ERROR, p,
                       "no se pudo consultar la ruta de la boveda: %s"
                       % type(exc).__name__)

    if not p.is_dir():
        return Montaje(EstadoMontaje.RUTA_AUSENTE, p,
                       "la ruta de la boveda existe pero no es un directorio")

    # 2. ¿Esta REALMENTE montado? Antes de enumerar, no despues. Este es el
    #    orden que impide que un mountpoint sin montaje se lea como vacio.
    if exigir_montaje:
        try:
            montado = os.path.ismount(str(p))
        except OSError as exc:
            return Montaje(EstadoMontaje.ERROR, p,
                           "no se pudo comprobar si la ruta es un montaje: %s"
                           % type(exc).__name__)
        if not montado:
            return Montaje(
                EstadoMontaje.MONTAJE_AUSENTE, p,
                "la ruta existe pero NO hay un montaje activo sobre ella. "
                "Parece un directorio vacio y no lo es: la boveda no se ha "
                "mirado. No se enumera, porque el resultado se leeria como "
                "«no hay fuentes»",
            )

    # 3. Solo ahora se enumera.
    try:
        entradas = sorted(os.listdir(str(p)))
    except OSError as exc:
        if exc.errno in _ERRNO_ROTO:
            return Montaje(EstadoMontaje.MONTAJE_ROTO, p,
                           "el montaje se rompio al enumerarlo (FUSE roto)")
        return Montaje(EstadoMontaje.MONTAJE_ILEGIBLE, p,
                       "el montaje existe pero no se puede leer: %s"
                       % type(exc).__name__)

    if not entradas:
        return Montaje(EstadoMontaje.MONTAJE_VACIO, p,
                       "montaje verificado y legible: no contiene nada",
                       entradas=[])
    return Montaje(EstadoMontaje.MONTAJE_CON_CONTENIDO, p,
                   "montaje verificado y legible",
                   entradas=entradas)
