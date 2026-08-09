"""PUERTA: el mapa de contratos ruta/UI del visor no puede envejecer en silencio.

El inventario de rutas del visor sólo sirve si es ejecutable. Esta puerta
recorre la aplicación FastAPI REAL (la misma que se monta en producción) y
falla cuando:

  1. aparece una ruta registrada que nadie ha declarado en el mapa —o al revés,
     el mapa declara una ruta que ya no existe;
  2. una ruta declarada no tiene NINGÚN fichero de prueba que la nombre, y
     tampoco está reconocida como hueco conocido en `known_gaps`;
  3. un fichero de prueba declarado como cobertura de una ruta ha dejado de
     nombrarla (la declaración se ha quedado obsoleta);
  4. queda una plantilla huérfana: nadie la renderiza ni la hereda;
  5. una plantilla o el JS del visor enlazan a una ruta que no existe;
  6. la ficha del mapa está incompleta (rol, entrega, plantilla inexistente…).

El coste de mantenerla es una entrada en `route_contract/route_contract_map.json`
por cada ruta nueva; el borrador se saca con
`python3 viewer/tests/route_contract/_generate.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.main import app
from tests.route_contract import inventory as inv

MAP_PATH = Path(__file__).resolve().parent / "route_contract" / "route_contract_map.json"


@pytest.fixture(scope="module")
def mapa() -> dict:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rutas_reales() -> list[inv.RouteInfo]:
    return inv.registered_routes(app)


# ---------------------------------------------------------------------------
# 1. El mapa cubre exactamente las rutas de la aplicación real
# ---------------------------------------------------------------------------
def test_el_mapa_declara_exactamente_las_rutas_registradas(mapa, rutas_reales):
    declaradas = set(mapa["rutas"])
    reales = {r.key for r in rutas_reales}

    sin_declarar = sorted(reales - declaradas)
    fantasmas = sorted(declaradas - reales)

    assert not sin_declarar, (
        "Rutas registradas en el visor que NADIE ha declarado en el mapa de "
        f"contratos: {sin_declarar}. Añádelas a {MAP_PATH.name} con su rol, "
        "plantilla, estados, errores y pruebas "
        "(borrador: python3 viewer/tests/route_contract/_generate.py)."
    )
    assert not fantasmas, (
        f"El mapa declara rutas que ya no existen en la aplicación: {fantasmas}."
    )


def test_el_endpoint_declarado_es_el_que_sirve_la_ruta(mapa, rutas_reales):
    real = {r.key: r.endpoint for r in rutas_reales}
    desviados = {
        k: (v["endpoint"], real[k])
        for k, v in mapa["rutas"].items()
        if k in real and v["endpoint"] != real[k]
    }
    assert not desviados, f"Endpoint declarado != endpoint real: {desviados}"


# ---------------------------------------------------------------------------
# 2 y 3. Cobertura declarada, verificada contra los ficheros de prueba
# ---------------------------------------------------------------------------
def test_ninguna_ruta_se_queda_sin_cobertura_declarada(mapa, rutas_reales):
    huecos = set(mapa["known_gaps"])
    sin_pruebas = sorted(
        k for k, v in mapa["rutas"].items() if not v["tests"] and k not in huecos
    )
    assert not sin_pruebas, (
        f"Rutas sin ninguna prueba que las ejerza: {sin_pruebas}. Escribe la "
        "prueba, o reconoce el hueco en 'known_gaps' con su motivo."
    )


def test_los_huecos_conocidos_no_crecen_y_siguen_siendo_huecos(mapa):
    huecos = mapa["known_gaps"]
    assert len(huecos) <= 4, (
        "La lista de huecos de cobertura ha crecido. Es una lista de deuda "
        "reconocida, no un vertedero: escribe la prueba."
    )
    ya_cubiertos = sorted(k for k in huecos if mapa["rutas"].get(k, {}).get("tests"))
    assert not ya_cubiertos, (
        f"Estas rutas ya tienen pruebas y siguen listadas como hueco: {ya_cubiertos}. "
        "Bórralas de 'known_gaps'."
    )
    desconocidas = sorted(k for k in huecos if k not in mapa["rutas"])
    assert not desconocidas, f"'known_gaps' menciona rutas que no están en el mapa: {desconocidas}"


def test_la_cobertura_declarada_sigue_siendo_cierta(mapa):
    """Un fichero declarado como cobertura debe seguir nombrando la ruta."""
    obsoletos: dict[str, list[str]] = {}
    for key, entry in mapa["rutas"].items():
        path = key.split(" ", 1)[1]
        reales = inv.test_files_mentioning(path)
        perdidos = [t for t in entry["tests"] if t not in reales]
        if perdidos:
            obsoletos[key] = perdidos
    assert not obsoletos, (
        "Ficheros declarados como cobertura que ya no nombran su ruta (o que no "
        f"existen): {obsoletos}. Actualiza el mapa."
    )


# ---------------------------------------------------------------------------
# 4. Plantillas huérfanas
# ---------------------------------------------------------------------------
def test_no_hay_plantillas_huerfanas():
    huerfanas = sorted(inv.orphan_templates())
    assert not huerfanas, (
        f"Plantillas que nadie renderiza ni hereda: {huerfanas}. O se montan en "
        "una ruta, o se borran: una pantalla que no se puede alcanzar es deuda."
    )


def test_toda_plantilla_declarada_en_el_mapa_existe(mapa):
    existentes = inv.template_files()
    faltan = sorted(
        {
            v["entrega"]
            for v in mapa["rutas"].values()
            if v["entrega"].endswith(".html")
            and v["entrega"].split(" ")[0] not in existentes
        }
    )
    assert not faltan, f"El mapa declara plantillas inexistentes: {faltan}"


# ---------------------------------------------------------------------------
# 5. Enlaces rotos (plantillas y JS del visor)
# ---------------------------------------------------------------------------
def test_ningun_enlace_de_la_ui_apunta_a_una_ruta_inexistente(rutas_reales):
    rotos = [f"{ln.template}: {ln.attribute}={ln.raw!r} -> {ln.probe}" for ln in inv.broken_links(app)]
    assert not rotos, (
        "Enlaces de la interfaz que no resuelven contra ninguna ruta registrada: "
        + "; ".join(rotos)
    )


# ---------------------------------------------------------------------------
# 6. La ficha del mapa está completa
# ---------------------------------------------------------------------------
CAMPOS = ("endpoint", "rol", "entrega", "datos", "estados", "errores",
          "nav_entrante", "nav_saliente", "consumidores_js", "tests", "notas")


def test_cada_ficha_del_mapa_esta_completa(mapa):
    incompletas: dict[str, list[str]] = {}
    for key, entry in mapa["rutas"].items():
        faltan = [c for c in CAMPOS if c not in entry]
        vacios = [c for c in ("rol", "entrega", "datos") if not entry.get(c)]
        if faltan or vacios:
            incompletas[key] = faltan + [f"{c} vacío" for c in vacios]
    assert not incompletas, f"Fichas incompletas en el mapa: {incompletas}"
