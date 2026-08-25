#!/usr/bin/env python3
"""Antes de medir nada, el gate comprueba que su estado inicial es el limpio.

LA REGLA, y es mas amplia que cualquier lista de mecanismos
===========================================================
    Antes de empezar a medir, todo estado que el gate presupone limpio debe
    comprobarse EXPLICITAMENTE como limpio.

ESTE MODULO ES DEFENSA COMPLEMENTARIA, NO LA GARANTIA.
La garantia la sostiene `bootstrap_certificacion.py`, que ejecuta la
certificacion en un interprete AISLADO y carga el codigo critico desde el sujeto
Git verificado. Lo de aqui corre YA DENTRO de ese interprete limpio y sirve para
detectar lo que llegue a alcanzar al codigo critico si alguien retirase el
aislamiento.

Y una promesa que estuvo escrita aqui y era mala: "cubre cualquier mecanismo que
se invente manana". Eso es una garantia absoluta, innecesaria y no medible. Se
retira. La que se sostiene y se mide es la del bootstrap.

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

EL AISLAMIENTO SI ESTA PUESTO, Y ESTE FICHERO LLEGO A MENTIR SOBRE ESO
=====================================================================
Una version anterior de esta cabecera afirmaba que `ci.yml` invocaba los gates
con `-s -E` cuando `ci.yml` documentaba lo contrario: prosa que mentia sobre una
garantia, que es justo lo que este carril persigue. Corregido.

Hoy `ci.yml` invoca la certificacion como
`python3 -I .github/scripts/bootstrap_certificacion.py <gate>`, y el
aislamiento es PARTE DE LA ARQUITECTURA, no un extra. El problema de PyYAML
-que vive en el *user site* y `-I` deja fuera- lo resuelve el bootstrap
devolviendo ESA RUTA a `sys.path` despues del arranque: tener la dependencia
disponible no es lo mismo que ejecutar los ganchos de arranque que viven en ese
directorio.
"""
from __future__ import annotations

import importlib.util
import sys
import types
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

# Modulos de los que la certificacion DEPENDE y que, por tanto, no se dan por
# buenos solo porque esten en `sys.modules`: se recargan del fichero del repo y
# se comparan FUNCION A FUNCION.
CRITICOS = ("registro_xfail", "normaliza_shell")

# NO HAY BANDERA DE ABLACION EN ESTE MODULO, Y ES DELIBERADO.
#
# Una bandera aqui seria una perilla mas que un `usercustomize` podria levantar
# —importa el modulo, la pone, y el control se calla— y habria que defenderla,
# y estariamos otra vez discutiendo quien la puso. La calibracion demuestra que
# este control CARGA quitando la ASERCION DE VERDAD del gate (con restauracion
# verificada por SHA-256) y comprobando que entonces el ataque externo vuelve a
# pasar. Una ablacion real no necesita una puerta en el producto.


def _carga_desde_disco(nombre: str):
    """Carga el modulo DEL FICHERO DEL REPO, sin pasar por `sys.modules`.

    `spec_from_file_location` + `exec_module` no consulta `sys.modules` ni pasa
    por `builtins.__import__`, asi que un gancho puesto en el arranque no puede
    devolver una version preparada. Es la copia contra la que se compara.
    """
    ruta = REPO / ".github" / "scripts" / f"{nombre}.py"
    spec = importlib.util.spec_from_file_location(f"_s9k_limpio_{nombre}", ruta)
    if spec is None or spec.loader is None:
        raise ImportError(f"no se pudo cargar {ruta}")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo, ruta


def _funciones(modulo, ruta) -> dict:
    """`nombre -> bytecode` de las funciones definidas EN ESE FICHERO."""
    salida = {}
    for nombre, obj in vars(modulo).items():
        if isinstance(obj, types.FunctionType):
            codigo = getattr(obj, "__code__", None)
            if codigo is not None and Path(codigo.co_filename).name == ruta.name:
                salida[nombre] = codigo.co_code
    return salida


def comprueba_codigo_en_uso() -> list[str]:
    """El codigo que el gate va a USAR tiene que ser el del repositorio.

    POR QUE ESTO NO ES UNA PERILLA MAS. La version anterior comparaba cuatro
    PERILLAS y el `__file__` de tres modulos, y AFIRMABA cubrir "plugins,
    monkeypatches y cualquier mecanismo que se invente manana". No era verdad:
    un `usercustomize` que engancha `builtins.__import__` y SUSTITUYE
    `registro_xfail.contenido_verificado` no toca ninguna perilla ni cambia
    ningun `__file__`. Medido: EXIT=0, 0 errores, con un defecto real tragado y
    una autorizacion nunca commiteada. Falso verde sobre la garantia rectora.

    Enumerar la funcion sustituida habria sido el caso N+1 de siempre. Se cambia
    la unidad: en vez de preguntar "¿esta esta perilla como la deje?", se
    compara EL CODIGO QUE SE VA A EJECUTAR contra el que hay en el fichero del
    repositorio, funcion por funcion. Eso cubre perillas, funciones, envoltorios
    y lo que venga, porque lo que se afirma es una propiedad -"el codigo en uso
    es el del repo"- y no una lista de mecanismos.

    LIMITE DECLARADO: si alguien sustituyera las funciones de ESTE fichero, esta
    comprobacion no se ejecutaria para delatarlo. Ningun control puede
    verificarse a si mismo desde dentro; lo que cubre ese flanco es que el
    fichero vive en el repositorio y su invocacion esta exigida
    (`GATES_EXIGIDOS`), asi que retirarlo o cambiarlo se ve en el diff.
    """
    problemas = []
    for nombre in CRITICOS:
        en_uso = sys.modules.get(nombre)
        if en_uso is None:
            continue
        try:
            limpio, ruta = _carga_desde_disco(nombre)
        except Exception as e:  # noqa: BLE001
            problemas.append(
                f"ESTADO INICIAL CONTAMINADO: no se pudo cargar `{nombre}` desde "
                f"el repositorio para compararlo ({e}). Sin la copia limpia no "
                f"se puede afirmar que el codigo en uso sea el del repo.")
            continue
        esperado = _funciones(limpio, ruta)
        actual = _funciones(en_uso, ruta)
        for fn, bytecode in esperado.items():
            objeto = getattr(en_uso, fn, None)
            if not isinstance(objeto, types.FunctionType):
                problemas.append(
                    f"ESTADO INICIAL CONTAMINADO: `{nombre}.{fn}` ya no es la "
                    f"funcion del repositorio (es {type(objeto).__name__}). "
                    f"Alguien la sustituyo antes de que el gate midiera.")
                continue
            if actual.get(fn) != bytecode:
                origen = Path(objeto.__code__.co_filename).name
                problemas.append(
                    f"ESTADO INICIAL CONTAMINADO: `{nombre}.{fn}` NO es el codigo "
                    f"del repositorio (viene de `{origen}`). Se comparo el "
                    f"bytecode contra el fichero del repo, asi que da igual como "
                    f"se hiciera el reemplazo -un gancho en `__import__`, un "
                    f"decorador, un envoltorio-: lo que se afirma es que el "
                    f"codigo en uso es el que se revisa en el diff.")
    return problemas


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

    problemas += comprueba_codigo_en_uso()

    for nombre, actual, fabrica in extra:
        if actual != fabrica:
            problemas.append(
                f"ESTADO INICIAL CONTAMINADO: `{nombre}` vale {actual!r} y de "
                f"fabrica es {fabrica!r}.")

    return problemas
