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
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

__all__ = [
    "FuenteDisponible",
    "CatalogoNoDisponible",
    "directorio_de_fuentes",
    "listar_fuentes",
    "resolver",
    "EXTENSIONES_SOPORTADAS",
    "NOMBRE_PERFIL",
    "NOMBRE_CATALOGO",
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


class CatalogoNoDisponible(RuntimeError):
    """El directorio de fuentes no existe o no se puede leer.

    Ausencia declarada, NO lista vacia: "no hay fuentes" y "no se puede mirar"
    son dos afirmaciones distintas sobre produccion, y la segunda no se pinta
    como la primera (misma doctrina que `AUSENCIA != CERO` en el panel B).
    """


@dataclass(frozen=True)
class FuenteDisponible:
    """Una fuente elegible, tal y como se le ofrece al operador.

    `ruta` NO se serializa a la pantalla: existe para que el servidor resuelva.
    Lo que viaja al navegador son `handle`, `titulo`, `formato` y `tamano`.
    """

    handle: str
    titulo: str
    formato: str
    tamano_bytes: int
    ruta: Path

    def para_pantalla(self) -> dict:
        """La fuente SIN nada del servidor dentro. Es lo unico que se pinta."""
        return {
            "handle": self.handle,
            "titulo": self.titulo,
            "formato": self.formato,
            "tamano_bytes": self.tamano_bytes,
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


def listar_fuentes(env: Optional[dict] = None) -> list[FuenteDisponible]:
    """Fuentes elegibles, ordenadas por titulo. Levanta si no se puede mirar.

    Un handle repetido (dos ficheros cuyo nombre produce el mismo slug) se
    desambigua con un sufijo numerico: dos entradas con el mismo handle harian
    que la eleccion del operador fuera ambigua y se resolviera "la primera que
    aparezca", que es un resultado que depende del orden del sistema de
    ficheros.
    """
    raiz = directorio_de_fuentes(env)
    try:
        if not raiz.is_dir():
            raise CatalogoNoDisponible(f"{raiz}: no es un directorio")
        entradas = sorted(raiz.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        raise CatalogoNoDisponible(f"{raiz}: {exc}") from exc

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
