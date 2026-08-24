#!/usr/bin/env python3
"""El binario que certifica comprueba que ARRANCA COMO SALIO DE FABRICA.

LA GRIETA QUE CIERRA
====================
`site` importa `usercustomize.py` del directorio *user site* AL ARRANCAR EL
INTERPRETE, antes que el codigo del gate. Ese modulo puede hacer:

    import sys; sys.path.insert(0, "<repo>/.github/scripts")
    import registro_xfail
    registro_xfail.MUTADO = True

y cuando el gate hace su `import registro_xfail` recibe EL MISMO OBJETO de
`sys.modules`, ya envenenado. La linea de invocacion queda intacta. Medido de
punta a punta, con un defecto real tragado por `xfail(strict=True)` en una suite
critica y una autorizacion escrita en caliente:

    GATE_EXIT=0    errores: 0    ficheros sin commitear: 2

Y es alcanzable desde `ci.yml`: basta un paso que escriba
`"$(python3 -m site --user-site)/usercustomize.py"` antes de invocar el gate.

POR QUE `SUP-9` NO LLEGABA
==========================
`SUP-9` prohibe `sitecustomize.py`/`usercustomize.py` DENTRO del repositorio
—la clase de fichero estaba pensada— pero el *user site* esta FUERA del arbol, y
es justo ahi donde Python lo importa solo. Perseguir ficheros fuera del repo
seria enumerar otra vez, y van nueve grietas ganadas por enumerar.

LA PROPIEDAD
============
No se pregunta QUE FICHEROS hay ni QUIEN los escribio: se afirma que el ESTADO
DEL PROCESO con el que se va a certificar es el de fabrica. Cualquier perilla
que la certificacion de por sentada se declara aqui, y anadir una nueva es una
linea. Ademas se comprueba la PROCEDENCIA de los modulos de los que depende el
gate: que su `__file__` este dentro del repositorio, para que sustituir un
modulo entero tampoco pase inadvertido.

CUANDO SE COMPRUEBA
===================
Solo cuando el gate se invoca DESDE LA LINEA DE COMANDOS, que es como certifica.
Los arneses llaman a `main()` dentro de su propio proceso y legitimamente
levantan perillas ANTES de llamar: comprobarles el estado de fabrica los
romperia, y un arreglo que rompe la calibracion no sirve. Es la misma
distincion que ya gobierna `--sin-base` y `--base-fichero`.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# (modulo, atributo, valor de fabrica). Anadir una perilla es una linea.
PERILLAS = (
    ("registro_xfail", "MUTADO", False),
    ("registro_xfail", "MIDIENDO", False),
)

# Modulos cuyo codigo tiene que venir DEL REPOSITORIO.
PROCEDENCIA = ("registro_xfail", "normaliza_shell")


def comprueba(extra: tuple = ()) -> list[str]:
    """Errores si el proceso no arranca como salio de fabrica.

    `extra` son perillas que el propio gate conoce y pasa ya resueltas, como
    tuplas `(nombre, valor_actual, valor_de_fabrica)`.
    """
    problemas: list[str] = []

    for modulo, atributo, fabrica in PERILLAS:
        mod = sys.modules.get(modulo)
        if mod is None:
            continue
        actual = getattr(mod, atributo, fabrica)
        if actual != fabrica:
            problemas.append(
                f"ESTADO ALTERADO ANTES DE ARRANCAR: `{modulo}.{atributo}` vale "
                f"{actual!r} y de fabrica es {fabrica!r}. Alguien modifico este "
                f"proceso ANTES de que el gate empezara —el sospechoso habitual "
                f"es un `usercustomize.py`/`sitecustomize.py` en el *user site*, "
                f"que Python importa solo al arrancar el interprete y que vive "
                f"FUERA del repositorio—. Un gate que certifica con una perilla "
                f"levantada no esta comprobando lo que dice comprobar.")

    for modulo in PROCEDENCIA:
        mod = sys.modules.get(modulo)
        if mod is None:
            continue
        origen = getattr(mod, "__file__", None)
        if not origen:
            problemas.append(f"PROCEDENCIA DESCONOCIDA: `{modulo}` no declara "
                             f"fichero de origen.")
            continue
        try:
            Path(origen).resolve().relative_to(REPO)
        except ValueError:
            problemas.append(
                f"PROCEDENCIA FUERA DEL REPOSITORIO: `{modulo}` se cargo desde "
                f"`{origen}`, que no esta bajo `{REPO}`. El gate estaria "
                f"confiando en codigo que no es el que se revisa en el diff.")

    for nombre, actual, fabrica in extra:
        if actual != fabrica:
            problemas.append(
                f"ESTADO ALTERADO ANTES DE ARRANCAR: `{nombre}` vale {actual!r} "
                f"y de fabrica es {fabrica!r}.")

    return problemas
