"""Conftest para viewer/app: asegurar que viewer/ está en sys.path para que
los tests puedan usar `from app.xxx import ...`.

NOTA IMPORTANTE: no insertar viewer/app aquí. Los tests del viewer usan
imports del tipo `from app.config import Settings`, donde `app` = viewer/app.
Para que eso funcione, sys.path debe tener viewer/ (el padre), NO viewer/app.
Insertar viewer/app causaría que Python busque `app` como viewer/app/app/,
lo que no existe y rompe todos los imports del viewer en corrida combinada.
"""
import sys
from pathlib import Path

_VIEWER_ROOT = Path(__file__).resolve().parents[1]
if str(_VIEWER_ROOT) not in sys.path:
    sys.path.insert(0, str(_VIEWER_ROOT))
