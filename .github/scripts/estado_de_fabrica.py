#!/usr/bin/env python3
"""Antes de medir nada, el gate comprueba que su estado inicial es el limpio.

LA REGLA, y es mas amplia que cualquier lista de mecanismos
===========================================================
    Antes de empezar a medir, todo estado que el gate presupone limpio debe
    comprobarse EXPLICITAMENTE como limpio.

Eso cubre `sitecustomize`, `usercustomize`, imports previos, plugins,
monkeypatches y cualquier mecanismo que se invente manana. El gate NO intenta
conocer todos los mecanismos capaces de contaminar Python: seria enumerar otra
vez, y van diez grietas ganadas por enumerar.

    LA FRONTERA DE CONFIANZA DE UN GATE NO TERMINA EN EL REPOSITORIO. Incluye
    el proceso que lo ejecuta, sus imports previos, su entorno y cualquier
    estado que el gate de por supuesto. Si una propiedad es requisito para
    decir "PASS", esa propiedad tiene que ser OBSERVADA, no presumida.

LA GRIETA QUE LO PROVOCO
========================
`site` importa `usercustomize.py` del *user site* AL ARRANCAR EL INTERPRETE,
antes que el codigo del gate. Ese modulo hace `import registro_xfail` y pone
`MUTADO = True`; cuando el gate importa, recibe EL MISMO OBJETO ya envenenado,
con la linea de invocacion intacta. Medido: EXIT=0, 0 errores, con un defecto
real tragado por `xfail(strict=True)` en una suite critica y una autorizacion
escrita en caliente. `SUP-9` prohibia esa clase de fichero DENTRO del repo, pero
el *user site* esta fuera.

COMO SE OBSERVA, SIN DEPENDER DE COMO SE INVOCA NI DEL ORDEN
============================================================
Se comparan los valores ACTUALES de las perillas contra los de FABRICA, al
entrar en `main()` y antes de medir nada. Para que eso sea suficiente, LAS
PERILLAS NO SON LA VIA POR LA QUE LOS ARNESES PIDEN LA ABLACION: los arneses la
pasan como PARAMETRO a `main()`, y `main()` la aplica DESPUES de esta
comprobacion. Asi, en el instante en que se mira, un valor distinto del de
fabrica solo puede venir de fuera.

Dos versiones anteriores no valian y conviene decir por que:
  * condicionar la comprobacion a "invocado desde la linea de comandos": esa
    bandera puede desaparecer en un refactor y nadie lo notaria.
  * tomar una INSTANTANEA al importar este modulo: se puede burlar por ORDEN
    -si el contaminador importa primero `estado_de_fabrica` y contamina
    despues, la foto sale limpia-. Medido: con `usercustomize` importando
    `check_suite_inventory` y poniendo su `ABLACION`, la instantanea no lo veia.
Comparar contra fabrica no depende de ningun orden.

BARRERA SECUNDARIA, NO SUSTITUTA
================================
`ci.yml` invoca los gates con `-s -E` (sin *user site*, sin `PYTHONPATH`), que
cierra el vector mas comodo. Es defensa ADICIONAL: si manana alguien cambia la
forma de invocar en un refactor, esta comprobacion interna sigue detectando la
contaminacion. Por eso la principal es esta y no aquella.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# (modulo, atributo, valor de fabrica). Anadir una perilla es UNA LINEA.
PERILLAS = (
    ("registro_xfail", "MUTADO", False),
    ("registro_xfail", "MIDIENDO", False),
    ("check_suite_inventory", "ABLACION", ""),
    ("check_ejecucion_real", "ABLACION", False),
)

# Modulos cuyo codigo tiene que venir DEL REPOSITORIO.
PROCEDENCIA = ("registro_xfail", "normaliza_shell", "estado_de_fabrica")

# NO HAY BANDERA DE ABLACION EN ESTE MODULO, Y ES DELIBERADO.
#
# Una bandera aqui seria una perilla mas que un `usercustomize` podria levantar
# —importa el modulo, la pone, y el control se calla— y habria que defenderla,
# y estariamos otra vez discutiendo quien la puso. La calibracion demuestra que
# este control CARGA quitando la ASERCION DE VERDAD del gate (con restauracion
# verificada por SHA-256) y comprobando que entonces el ataque externo vuelve a
# pasar. Una ablacion real no necesita una puerta en el producto.


def comprueba(extra: tuple = ()) -> list[str]:
    """Errores si el estado INICIAL del proceso no era el de fabrica."""
    problemas: list[str] = []

    for modulo, atributo, fabrica in PERILLAS:
        clave = f"{modulo}.{atributo}"
        mod = sys.modules.get(modulo)
        inicial = getattr(mod, atributo, fabrica) if mod is not None else fabrica
        if inicial != fabrica:
            problemas.append(
                f"ESTADO INICIAL CONTAMINADO: `{clave}` ya valia {inicial!r} "
                f"cuando el gate empezo, y de fabrica es {fabrica!r}. Alguien "
                f"altero este proceso ANTES de que el gate arrancara -un "
                f"`usercustomize.py`/`sitecustomize.py` que Python importa solo, "
                f"un import previo, un plugin, un monkeypatch-. No importa el "
                f"mecanismo: lo que el gate presupone limpio se comprueba, no se "
                f"presume.")

    for modulo in PROCEDENCIA:
        mod = sys.modules.get(modulo)
        if mod is None:
            continue
        origen = getattr(mod, "__file__", None)
        if not origen:
            problemas.append(f"ESTADO INICIAL CONTAMINADO: `{modulo}` no declara "
                             f"fichero de origen.")
            continue
        try:
            Path(origen).resolve().relative_to(REPO)
        except ValueError:
            problemas.append(
                f"ESTADO INICIAL CONTAMINADO: `{modulo}` se cargo desde "
                f"`{origen}`, fuera de `{REPO}`. El gate estaria confiando en "
                f"codigo que no es el que se revisa en el diff.")

    for nombre, actual, fabrica in extra:
        if actual != fabrica:
            problemas.append(
                f"ESTADO INICIAL CONTAMINADO: `{nombre}` vale {actual!r} y de "
                f"fabrica es {fabrica!r}.")

    return problemas
