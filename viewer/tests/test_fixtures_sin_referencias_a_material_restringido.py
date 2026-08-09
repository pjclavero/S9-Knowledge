"""Gate de HIGIENE DE DATOS DE PRUEBA (no del motor de política).

Un nodo/arista de visibilidad restringida (``secret`` / ``narrator``) no se
entrega a un rol inferior: de eso ya se ocupa el motor. Lo que este test vigila
es otra cosa, más tonta y más peligrosa: que el NOMBRE del material restringido
(su ``label``, su id o uno de sus alias) aparezca escrito dentro de un campo de
texto de un elemento que SÍ se entrega a ese rol inferior.

Hoy eso es inocuo porque el índice de búsqueda del visor no incluye
``description``. El día que alguien proponga la mejora razonable "busquemos
también en la descripción", el nombre del secreto se filtraría sin que ninguna
política fallara: el dato ya venía envenenado de fábrica.

Por eso el gate mira los FIXTURES, no el código. Si falla, la corrección es
reescribir el texto del fixture (sin nombrar lo restringido), nunca relajar la
política ni el serializador.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

VIEWER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = VIEWER_ROOT.parent

#: Niveles cuyo material no debe ser nombrado por elementos de nivel inferior.
RESTRICTED_LEVELS = ("secret", "narrator")

#: Campos de texto libre que viajan al cliente junto al elemento.
TEXT_FIELDS = (
    "description",
    "short_summary",
    "summary",
    "notes",
    "label",
    "canonical_name",
    "type_label",
    "text",
    "comment",
)

#: Términos demasiado cortos o genéricos como para ser una filtración útil.
MIN_TERM_LEN = 4

FIXTURE_FILES = sorted(
    set(
        list((VIEWER_ROOT / "examples").glob("*.json"))
        + list((VIEWER_ROOT / "tests" / "fixtures").glob("*.json"))
        + list((REPO_ROOT / "tests" / "fixtures").glob("*.json"))
    )
)


def _norm(s: str) -> str:
    """Minúsculas y sin acentos: "Pozo Viejo" y "pozo viejo" son el mismo dato."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _identity_terms(element: dict) -> list[str]:
    """label + id + canonical_name + alias del elemento restringido."""
    raw = [
        element.get("label"),
        element.get("id"),
        element.get("canonical_name"),
        *(element.get("aliases") or []),
    ]
    return [t for t in raw if isinstance(t, str) and len(t.strip()) >= MIN_TERM_LEN]


def _elements(graph: dict) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for kind in ("nodes", "edges", "relationships"):
        for el in graph.get(kind) or []:
            if isinstance(el, dict):
                out.append((kind, el))
    return out


def _describe(kind: str, el: dict) -> str:
    return "%s %s" % (kind[:-1] if kind.endswith("s") else kind,
                      el.get("id") or el.get("label") or "<sin id>")


def _leaks(path: Path) -> list[str]:
    graph = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(graph, dict):
        return []
    elements = _elements(graph)

    restricted = [
        (kind, el) for kind, el in elements
        if el.get("visibility") in RESTRICTED_LEVELS
    ]
    if not restricted:
        return []

    findings: list[str] = []
    for kind, el in elements:
        if el.get("visibility") in RESTRICTED_LEVELS:
            continue  # sólo importa lo que SÍ se entrega a un rol inferior
        for field in TEXT_FIELDS:
            value = el.get(field)
            if not isinstance(value, str) or not value:
                continue
            haystack = _norm(value)
            for r_kind, r_el in restricted:
                for term in _identity_terms(r_el):
                    if _norm(term) in haystack:
                        findings.append(
                            "%s (visibility=%s) menciona %r —identidad de %s "
                            "(visibility=%s)— en el campo %r: %r"
                            % (
                                _describe(kind, el),
                                el.get("visibility"),
                                term,
                                _describe(r_kind, r_el),
                                r_el.get("visibility"),
                                field,
                                value,
                            )
                        )
    return findings


def test_hay_fixtures_que_revisar():
    """Si el barrido no encuentra ficheros, el gate no está vigilando nada."""
    assert FIXTURE_FILES, "no se ha localizado ningún fixture de grafo"


@pytest.mark.parametrize(
    "fixture", FIXTURE_FILES, ids=[p.name for p in FIXTURE_FILES]
)
def test_ningun_texto_entregado_nombra_material_restringido(fixture: Path):
    findings = _leaks(fixture)
    assert not findings, (
        "%s filtra la identidad de material restringido en texto que sí se "
        "entrega a roles inferiores:\n  - %s\n\nCorrección: REESCRIBIR el texto "
        "del fixture sin nombrar lo restringido. No tocar políticas, motor ni "
        "serializadores." % (fixture.name, "\n  - ".join(findings))
    )
