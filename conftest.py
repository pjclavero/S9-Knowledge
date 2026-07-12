"""Root conftest: añade data-engine/app y viewer/app a sys.path para tests."""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent
_DATA_ENGINE_APP = repo_root / 'data-engine' / 'app'
_VIEWER_APP = repo_root / 'viewer' / 'app'

# Insertar en orden: viewer antes que data-engine (por si hay conflictos)
sys.path.insert(0, str(_DATA_ENGINE_APP))
sys.path.insert(0, str(_VIEWER_APP))
