"""Config de pytest para data-engine: añade `data-engine/app` a sys.path.

Los paquetes del proyecto (`media`, `jobs`, `schemas`, ...) son top-level bajo
`data-engine/app`. Se calcula la ruta de forma portable (no rutas fijas de
despliegue) para que los tests corran igual en Windows y en VM105.
"""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
