#!/usr/bin/env python3
"""Como los ARNESES ejecutan un gate desarmado sin que exista un desarme.

EL PROBLEMA
===========
La ablacion tiene que seguir siendo posible —sin ella no se puede demostrar que
cada control sujeta algo— pero NO puede existir como entrada del binario que
certifica. Se intento primero con variables de entorno protegidas por la
ASCENDENCIA del proceso, y se falsifico en una linea:

    bash -c 'exec -a ".github/scripts/calibra_registro_xfail.py" \
             /usr/bin/python3 /tmp/impostor.py'        -> EXIT=0

`argv` es texto que el proceso elige. Y por debajo hay algo peor: todo lo que
puede hacer un arnes lo puede hacer un paso de `ci.yml`, asi que ningun apreton
de manos —secreto efimero, fichero 0600, descriptor heredado— habria sido una
frontera.

LA SOLUCION
===========
Se quita LA ENTRADA. Los gates ya no leen ninguna variable de desarme: su
ablacion es una variable de MODULO. Y este helper la pone IMPORTANDO el gate
dentro de un proceso nuevo, en vez de exportar nada:

    python3 -c "import gate; gate.ABLACION='A'; sys.exit(gate.main(argv))"

Proceso limpio (sin estado arrastrado entre casos, que es por lo que no se hace
todo dentro del arnes) y sin ninguna variable heredable de por medio.

POR QUE ESTO NO REABRE EL AGUJERO
=================================
Alguien podria escribir ese mismo `python3 -c` en `ci.yml`. No le serviria:
`GATES_EXIGIDOS` (en `check_ci_config.py`) exige la INVOCACION LITERAL de
`check_suite_inventory.py` y `check_ejecucion_real.py`, y esas invocaciones no
tienen forma de ser desarmadas. Anadir una linea `-c` no quita la que certifica;
quitarla pone rojo el gate de configuracion. La garantia no es "nadie puede
escribir esto", es "la linea que certifica corre siempre y corre entera".
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / ".github" / "scripts"


def ejecuta_gate(modulo: str, argv: list[str], *, ablacion=None,
                 registro_mutado: bool = False, cwd: Path | None = None,
                 entorno: dict | None = None,
                 timeout: int = 3600) -> tuple[int, str]:
    """Ejecuta `<modulo>.main(argv)` en un proceso nuevo, con la ablacion puesta.

    `ablacion` es lo que el gate espera en su variable de modulo: una cadena
    (`"A"`..`"H"`) para el inventario, un booleano para la capa de resultados.
    """
    programa = "\n".join([
        "import importlib, sys",
        f"sys.path.insert(0, {str(SCRIPTS)!r})",
        "import registro_xfail",
        f"registro_xfail.MUTADO = {bool(registro_mutado)!r}",
        f"m = importlib.import_module({modulo!r})",
        f"m.ABLACION = {ablacion!r}",
        f"sys.exit(m.main({argv!r}))",
    ])
    p = subprocess.run([sys.executable, "-c", programa],
                       cwd=str(cwd or REPO), capture_output=True, text=True,
                       timeout=timeout, env=entorno or os.environ.copy())
    return p.returncode, p.stdout + p.stderr
