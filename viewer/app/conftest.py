"""Conftest para viewer/app: asegurar que el módulo se carga desde aquí."""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
