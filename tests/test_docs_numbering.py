"""Unicidad de la numeracion de `docs/`.

Cuatro carriles distintos reclamaron `docs/55` a la vez porque cada uno numero
mirando solo `main`, sin ver las ramas abiertas. Git no lo detecta: son cuatro
nombres de fichero distintos y fusionan limpios. Es un conflicto de
significado, no de merge, y por eso hace falta una prueba que lo vea.

Dos comprobaciones:

1. Ningun prefijo numerico `NN-` puede repetirse dentro de un mismo directorio
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

#: `NN-` al principio del nombre: el prefijo numerico bien formado.
NUMBERED_PREFIX = re.compile(r"^(\d{2,3})-")

#: `NN` seguido de cualquier cosa que no sea un guion: separador prohibido.
BAD_SEPARATOR = re.compile(r"^(\d{2,3})(?![-\d])")


def _numbered_markdown_files() -> list[Path]:
    """Todos los .md bajo `docs/`, saltando los subarboles exentos."""
    files: list[Path] = []
    for path in DOCS_ROOT.rglob("*.md"):
        relative = path.relative_to(DOCS_ROOT)
        if EXCLUDED_DIRS.intersection(relative.parts[:-1]):
            continue
        files.append(path)
    return files


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
