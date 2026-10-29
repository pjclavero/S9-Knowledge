"""Root conftest: configuración de sys.path para corrida combinada data-engine + viewer.

Estructura del proyecto
-----------------------
- data-engine/app/ : directorio raíz de los paquetes del motor (schemas, jobs,
  media, access, ...). Se añade a sys.path para que los paquetes sean importables
  directamente como top-level (e.g. `from schemas.rpg_schema import ...`).
  NO tiene __init__.py para evitar que Python lo registre como paquete 'app'
  colisionando con el paquete viewer/app.

- viewer/          : raíz del viewer FastAPI. Se añade a sys.path para que
  `import app` resuelva a viewer/app/ (que sí tiene __init__.py).

Corrida combinada
-----------------
Con ambos paths en sys.path y data-engine/app sin __init__.py, no existe
colisión de módulos: 'app' siempre resuelve a viewer/app/.
La limpieza de sys.modules en viewer/tests/conftest.py actúa como salvaguarda
extra para sesiones con conftest cargados en orden no determinista.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent
_DATA_ENGINE_APP = repo_root / 'data-engine' / 'app'
_VIEWER_ROOT = repo_root / 'viewer'

# data-engine/app debe estar en sys.path para que los paquetes del motor
# (schemas, jobs, media, etc.) sean importables como top-level.
if str(_DATA_ENGINE_APP) not in sys.path:
    sys.path.insert(0, str(_DATA_ENGINE_APP))

# viewer/ debe estar en sys.path para que 'import app' resuelva a viewer/app/.
# Se inserta después de data-engine/app para que los paquetes del motor
# (que no tienen __init__.py en su raíz) no interfieran con 'app'.
if str(_VIEWER_ROOT) not in sys.path:
    sys.path.append(str(_VIEWER_ROOT))



# ---------------------------------------------------------------------------
# Almacén de propuestas de revisión: propio de CADA caso.
# ---------------------------------------------------------------------------
# Desde Slice 2 · Corte 3 `run_ingest` exporta la cola de revisión SIEMPRE (era
# justo el llamador que faltaba). Eso tiene dos consecuencias para la suite, y
# las dos se arreglan aquí:
#
#   1. sin redirigir, cada caso que corre una ingesta dejaría paquetes en
#      `viewer/output/reviews-v3/proposals`, el almacén REAL del repositorio;
#   2. con un ÚNICO almacén para toda la sesión tampoco basta —se midió—:
#      las propuestas de un caso las veía otro. `test_slot_renders_empty_state`
#      del hueco C pasó a encontrar «1–4 de 4» donde esperaba la pantalla
#      vacía. Un almacén compartido es contaminación entre casos, y ya fabricó
#      aquí un rojo que no era del sujeto.
#
# Por eso el almacén es de CADA caso. Un test que quiera fijar el suyo —la
# prueba insignia del Corte 3 lo hace— vuelve a declarar la variable en su
# propio fixture, que corre después de éste y manda sobre él.
import pytest


@pytest.fixture(autouse=True)
def _almacen_de_propuestas_aislado(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "S9K_V3_REVIEW_PROPOSALS_DIR", str(tmp_path / "reviews-v3" / "proposals")
    )


# ---------------------------------------------------------------------------
# Almacén de decisiones humanas (`review.sqlite3`): DECLARADO y FRESCO por caso.
# ---------------------------------------------------------------------------
# C1 (USABLE-V1) · H-04 + H-18. Hasta C1 el visor CREABA `review.sqlite3` al
# primer uso y el motor leía `{}` si no estaba: la suite entera vivía de ese
# comportamiento. Con la ruta DECLARADA, el runtime ya no crea nada (lo crea el
# despliegue), así que cada caso nace como nace una instalación fresh: ruta
# declarada y almacén creado POR LA MISMA HERRAMIENTA que usa `deploy.sh`
# (`deploy/scripts/review_store.py preparar --modo fresh`), no por un atajo de
# test. Un caso que quiera otro estado (ausente, corrupto, sin declarar, ...)
# lo cambia en SU propio fixture, que corre después de éste y manda sobre él.
def crear_almacen_fresh(ruta):
    """Crea `ruta` exactamente como el despliegue fresh. Devuelve la ruta."""
    import importlib.util as _ilu

    nombre = "_s9k_review_store_deploy_tests"
    modulo = sys.modules.get(nombre)
    if modulo is None:
        spec = _ilu.spec_from_file_location(
            nombre, repo_root / "deploy" / "scripts" / "review_store.py")
        modulo = _ilu.module_from_spec(spec)
        sys.modules[nombre] = modulo
        spec.loader.exec_module(modulo)
    resultado = modulo.preparar("fresh", str(ruta))
    assert resultado.rc == 0, resultado.lineas
    return ruta


@pytest.fixture(autouse=True)
def _almacen_de_decisiones_declarado_y_fresco(tmp_path_factory, monkeypatch):
    # Directorio PROPIO del caso, NO `tmp_path`: hay suites que cuentan lo que
    # hay dentro de `tmp_path` y un `reviews-v3/` ajeno les cambia el recuento.
    ruta = tmp_path_factory.mktemp("c1-decisiones") / "reviews-v3" / "review.sqlite3"
    # La variable DECLARADA manda sobre `S9K_V3_REVIEW_DECISIONS_PATH` (que solo
    # sigue gobernando el `decisions.jsonl` de auditoria): no se toca, porque
    # varios casos del navegador la fijan para NO escribir en el arbol del repo.
    monkeypatch.setenv("S9K_V3_REVIEW_DATABASE_PATH", str(ruta))
    crear_almacen_fresh(ruta)


@pytest.fixture
def almacen_fresh():
    """La función `crear_almacen_fresh` como fixture (los tests no importan conftest)."""
    return crear_almacen_fresh
