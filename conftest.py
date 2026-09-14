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
# Almacén de propuestas de revisión: fuera del árbol durante la suite.
# ---------------------------------------------------------------------------
# Desde Slice 2 · Corte 3 `run_ingest` exporta la cola de revisión SIEMPRE (era
# justo el llamador que faltaba). Sin esta redirección, cada caso que corre una
# ingesta dejaría paquetes en `viewer/output/reviews-v3/proposals`, que es el
# almacén REAL del repositorio: los casos se contaminarían entre sí y un «hay
# propuestas» podría ponerse verde por basura de otra corrida.
#
# No se impone si la variable ya viene declarada: un caso que quiera fijar su
# propio almacén —la prueba insignia lo hace— manda sobre esto.
import os
import tempfile

if not os.environ.get("S9K_V3_REVIEW_PROPOSALS_DIR"):
    os.environ["S9K_V3_REVIEW_PROPOSALS_DIR"] = tempfile.mkdtemp(
        prefix="s9k-proposals-suite-"
    )
