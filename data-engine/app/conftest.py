"""Conftest para data-engine/app: cargar jobs desde data-engine/app."""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent

# ANTES de cualquier importación de pytest, limpiar property-graph de sys.modules
# y asegurar que data-engine/app esté en sys.path[0]
sys.path.insert(0, str(_APP_DIR))

def pytest_configure(config):
    """Hook de pytest que se ejecuta antes de collection."""
    # Limpiar módulos de property-graph si fueron cargados
    for mod_name in list(sys.modules.keys()):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, '__file__') and mod.__file__:
            if '/property-graph/' in str(mod.__file__) and 'jobs' in mod_name:
                del sys.modules[mod_name]

