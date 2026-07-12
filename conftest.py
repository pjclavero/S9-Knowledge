"""Root conftest: garantizar que data-engine/app y viewer/app están al inicio de sys.path ANTES de cualquier importación.

Este archivo se ejecuta PRIMERO cuando pytest carga desde la raíz del repo.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent
_DATA_ENGINE_APP = repo_root / 'data-engine' / 'app'
_VIEWER_APP = repo_root / 'viewer' / 'app'

# Insertar en sys.path con máxima prioridad
sys.path.insert(0, str(_DATA_ENGINE_APP))
sys.path.insert(0, str(_VIEWER_APP))

# Debug (descomenta si falla)
# print(f'[conftest.root] sys.path[0:2] = {sys.path[0:2]}', file=__import__("sys").stderr)
