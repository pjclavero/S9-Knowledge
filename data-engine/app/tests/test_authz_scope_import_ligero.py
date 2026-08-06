"""El ámbito de visibilidad del visor debe poder importarse SIN las dependencias
del visor.

La suite de data-engine consume ``app.services.v3_review``, que a su vez usa el
ámbito (``app.authz.scope``). El paquete ``app.authz`` NO puede, por tanto,
importar de forma anticipada piezas que dependan de la configuración del visor
y de sus dependencias de terceros: hacerlo rompe la colección de esta suite en
un entorno que solo instala las dependencias de data-engine.

Se comprueba en un intérprete aparte, bloqueando una dependencia que solo el
visor instala, para que el resultado no dependa del entorno de quien ejecute.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_GUION = textwrap.dedent(
    """
    import sys

    class _Bloqueo:
        def find_spec(self, name, path=None, target=None):
            if name == "pydantic_settings":
                raise ImportError("dependencia del visor no disponible")
            return None

    sys.meta_path.insert(0, _Bloqueo())
    sys.path.insert(0, "viewer")

    import app.authz.scope  # noqa: F401

    print("OK")
    """
)


def test_el_ambito_se_importa_sin_las_dependencias_del_visor() -> None:
    resultado = subprocess.run(
        [sys.executable, "-c", _GUION],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, (
        "app.authz arrastra una importación que exige dependencias del visor:\n"
        f"{resultado.stderr}"
    )
    assert "OK" in resultado.stdout
