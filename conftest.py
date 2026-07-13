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
