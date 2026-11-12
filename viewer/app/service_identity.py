"""Puente visor -> autoridad de identidad y estado privado (H-06 + H-08).

La autoridad (usuario de servicio, state root, modo de fichero, modo de
directorio, comprobacion de arranque) vive en el motor:
``data-engine/app/knowledge_v3/service_state.py``. Motor y visor publican dos
paquetes ``app`` distintos, asi que NO se importa por nombre de paquete: se
carga por ruta, con el MISMO nombre de modulo que usan los guiones de despliegue
(``_s9k_service_state``), de modo que hay una sola instancia por proceso.

Este modulo no define ninguna cifra: solo la entrega. Los modos que el visor
aplica a lo que crea (``auth.db``, su ``.lock``, las copias ``.bak``) salen de
aqui, no de un literal ``0o600`` repetido.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_RUTA = (Path(__file__).resolve().parents[2] / "data-engine" / "app"
         / "knowledge_v3" / "service_state.py")


def service_state():
    """El modulo ``service_state`` (cargado por ruta, una sola instancia)."""
    nombre = "_s9k_service_state"
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, _RUTA)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError("no se puede cargar la autoridad de estado: %s" % _RUTA)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def file_mode() -> int:
    return service_state().FILE_MODE


def dir_mode() -> int:
    return service_state().DIR_MODE


def ensure_private_dir(path) -> Path:
    """Directorio de estado (y padres que falten) con el modo EXACTO de la autoridad."""
    return service_state().ensure_private_dir(path)


def create_private_file(path) -> bool:
    """Fichero de estado vacio con el modo EXACTO de la autoridad si no existe."""
    return service_state().create_private_file(path)


def refuse_root_state_write(path) -> None:
    """H-1: un proceso root no crea ni escribe estado del servicio (ver la autoridad)."""
    service_state().refuse_root_state_write(path)


def open_private_append(path, *, encoding: str = "utf-8", newline=None):
    """Abre ``path`` para anadir, creandolo 0600 en un directorio 0700.

    El modo sale de la autoridad y NO depende de la umask del proceso (cada
    directorio que falte y el fichero se crean con su modo EXACTO): los JSONL de
    decisiones/auditoria/candidatos nacen privados aunque el servicio arranque
    por una ruta sin ``UMask=0077`` (H-06 + H-08, N5/N6). Root no escribe aqui (H-1).
    """
    p = Path(path)
    ensure_private_dir(p.parent)
    fd = service_state().open_private_write(p, append=True)
    return os.fdopen(fd, "a", encoding=encoding, newline=newline)
