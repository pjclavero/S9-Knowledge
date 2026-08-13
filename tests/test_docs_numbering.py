"""Unicidad de la numeracion de `docs/`.

Cuatro carriles distintos reclamaron `docs/55` a la vez porque cada uno numero
mirando solo `main`, sin ver las ramas abiertas. Git no lo detecta: son cuatro
nombres de fichero distintos y fusionan limpios. Es un conflicto de
significado, no de merge, y por eso hace falta una prueba que lo vea.

Tres comprobaciones:

0. El instrumento tiene que ENCONTRAR documentacion. Las dos comprobaciones de
   abajo pasaban en verde con `docs/` vacio y con `docs/` inexistente: sobre el
   conjunto vacio no hay colision posible. Un gate que no distingue "no hay
   defecto" de "no he mirado" esta omitido sin decirlo.


1. Ningun prefijo numerico `N-`/`NN-`/`NNN-` puede repetirse dentro de un mismo directorio
   de documentacion (la comparacion es por directorio, no recursiva: `docs/50`
   y `docs/otro/50` son numeraciones independientes).
2. El separador tras el numero tiene que ser un guion. Un fichero llamado
   `47_qa_browser_e2e_visor.md` no lo veria el regex de la primera
   comprobacion, asi que un separador libre seria una puerta trasera a la
   unicidad.

`docs/archivados/` queda excluido A PROPOSITO: ya contiene duplicados
historicos (dos `50-`, tres `51-`) de documentos cerrados hace meses. No se
arregla el pasado reescribiendo nombres a los que apunta la documentacion ya
publicada; lo que se impide es que el presente siga creciendo torcido.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"

#: Subarboles de `docs/` exentos, con el motivo escrito.
EXCLUDED_DIRS = {
    # Duplicados historicos ya consolidados (dos `50-`, tres `51-`): son
    # documentos cerrados y referenciados por su nombre actual.
    "archivados",
}

#: `N-`, `NN-` o `NNN-` al principio del nombre: el prefijo numerico bien
#: formado. Cubre UN solo digito a proposito: `9-algo.md` es un documento
#: numerado, y con `\d{2,3}` no lo era, asi que `9-` y `09-` podian coexistir.
NUMBERED_PREFIX = re.compile(r"^(\d{1,3})-")

#: `N`/`NN`/`NNN` seguido de cualquier cosa que no sea un guion: separador
#: prohibido. El `(?![-\d])` impide que un prefijo de cuatro digitos (una fecha
#: como `2026-08-...`) se lea como documento numerado.
BAD_SEPARATOR = re.compile(r"^(\d{1,3})(?![-\d])")

#: Suelo de plausibilidad: cuantos ficheros .md tiene que ENCONTRAR el
#: instrumento para que su veredicto signifique algo.
#:
#: Sin esto, las dos comprobaciones de abajo pasan en VERDE con `docs/` vacio, y
#: tambien con `docs/` inexistente: `rglob` sobre un directorio que no esta
#: devuelve una lista vacia, ninguna colision es posible sobre el conjunto
#: vacio, y el gate queda verde para siempre en silencio. Es el mismo fallo que
#: un pytest que colecciona 0 tests y sale con exito. Un gate que no puede
#: distinguir "no hay defectos" de "no he mirado" no es un gate.
#:
#: El numero es un SUELO, no un recuento: hoy hay 69 documentos numerados fuera
#: de `archivados/`. 40 deja sitio de sobra para archivar o consolidar
#: documentacion sin tocar esta cifra, y sigue siendo inalcanzable por accidente
#: si el arbol se pierde.
MINIMO_DOCUMENTOS_NUMERADOS = 40


def _numbered_markdown_files() -> list[Path]:
    """Todos los .md bajo `docs/`, saltando los subarboles exentos.

    Falla RUIDOSAMENTE si el instrumento no encuentra material que medir: esa
    es la unica diferencia entre "no hay numeracion duplicada" y "no he sabido
    mirar". Todas las comprobaciones del modulo pasan por aqui, para que un
    `docs/` movido o vaciado las ponga rojas a TODAS y no solo a una.
    """
    assert DOCS_ROOT.is_dir(), (
        f"El instrumento no encuentra el arbol de documentacion en {DOCS_ROOT}. "
        "No es que no haya numeros duplicados: es que no se ha mirado nada. "
        "Si `docs/` se ha movido, hay que actualizar DOCS_ROOT, no dejar el "
        "gate en verde."
    )

    files: list[Path] = []
    for path in DOCS_ROOT.rglob("*.md"):
        relative = path.relative_to(DOCS_ROOT)
        if EXCLUDED_DIRS.intersection(relative.parts[:-1]):
            continue
        files.append(path)

    numerados = [p for p in files if NUMBERED_PREFIX.match(p.name)]
    assert len(numerados) >= MINIMO_DOCUMENTOS_NUMERADOS, (
        f"El instrumento solo ha encontrado {len(numerados)} documentos "
        f"numerados bajo {DOCS_ROOT} (minimo plausible: "
        f"{MINIMO_DOCUMENTOS_NUMERADOS}). Un veredicto sobre un conjunto casi "
        "vacio no dice nada: revisa si `docs/` se ha movido o si el rootdir de "
        "pytest se resuelve a otro sitio antes de tocar este minimo."
    )
    return files


def test_el_instrumento_encuentra_documentacion_que_medir() -> None:
    """Control explicito del propio arnes: 0/0 no es aprobado.

    Existe como test propio, y no solo como asercion interna, para que el
    informe de CI diga con su nombre que esta condicion se ha comprobado.
    """
    assert len(_numbered_markdown_files()) >= MINIMO_DOCUMENTOS_NUMERADOS


def test_no_duplicate_doc_numbers_per_directory() -> None:
    """Ningun numero de documento se repite dentro de su directorio."""
    by_directory: dict[Path, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for path in _numbered_markdown_files():
        match = NUMBERED_PREFIX.match(path.name)
        if match is None:
            continue
        number = match.group(1).lstrip("0") or "0"
        by_directory[path.parent][number].append(path.name)

    collisions = {
        f"{directory.relative_to(REPO_ROOT)} numero {number}": sorted(names)
        for directory, numbers in by_directory.items()
        for number, names in numbers.items()
        if len(names) > 1
    }

    assert not collisions, (
        "Numeracion de documentos duplicada. Cada documento numerado debe "
        "tener un numero libre en la union de main MAS todas las ramas "
        "abiertas, no solo en main:\n"
        + "\n".join(f"  - {clave}: {', '.join(v)}" for clave, v in sorted(collisions.items()))
    )


def test_numbered_docs_use_a_hyphen_separator() -> None:
    """Tras el numero va un guion; cualquier otro separador es evasion."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _numbered_markdown_files()
        if BAD_SEPARATOR.match(path.name) and not NUMBERED_PREFIX.match(path.name)
    ]

    assert not offenders, (
        "Documentos numerados con un separador que no es un guion. Un "
        "`47_qa_...md` esquivaria la comprobacion de unicidad, asi que el "
        "separador es parte del contrato:\n"
        + "\n".join(f"  - {nombre}" for nombre in sorted(offenders))
    )
