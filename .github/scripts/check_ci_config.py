#!/usr/bin/env python3
"""Integridad de los gates del propio CI.

Este fichero existe porque las barreras de CI de este repositorio se han
apagado solas tres veces sin que nada se pusiera rojo. Cada apartado de aqui
abajo corresponde a un apagado REAL, no a un riesgo imaginado.

1. COBERTURA DE RAMAS. `on.push.branches` era una lista blanca de prefijos.
   Una rama cuya familia no estuviera escrita a mano NO disparaba CI al hacer
   push, y no habia ningun aviso: el carril `test/viewer-browser-e2e-v1` se
   desarrollo entero sin senal. La primera version de este gate comparaba las
   ramas de `origin` con los patrones del workflow: detectaba el agujero, pero
   la unica reparacion que ofrecia era anadir un prefijo mas, asi que el ciclo
   se repitio tres veces y a la cuarta habia otras nueve ramas descubiertas.
   Un gate que solo sabe pedir mantenimiento manual convierte el defecto en
   rutina.

   Ahora se comprueba la PROPIEDAD, no la lista: que CUALQUIER nombre de rama
   —los que existen hoy en `origin` y ademas una bateria de nombres
   deliberadamente inventados (`RAMAS_SONDA`), de familias que aun no
   existen— quede cubierto. Solo un patron universal (`**`) satisface eso; una
   lista blanca, por exhaustiva que sea con las ramas de hoy, falla contra los
   nombres inventados.

2. SILENCIADORES. Mirar solo `on.push.branches` deja vias de escape que no lo
   tocan: `paths-ignore: ['**']` apaga CI en todas las ramas, `branches-ignore`
   recorta la cobertura universal por detras, y `paths` la acota. Con
   `branches: ['**']` intacto, el gate seguia VERDE en los tres casos.

   La version anterior de esta comprobacion buscaba esos campos con una REGEX
   DE TEXTO sobre el bloque `on.push`. Un revisor independiente demostro tres
   bypasses, los tres YAML valido que GitHub interpreta EXACTAMENTE igual que
   la forma bloqueada:

     - clave entrecomillada:      "paths-ignore": ['**']
     - espacio antes de los dos puntos:  paths-ignore : ['**']
     - el campo bajo `pull_request`, que la regex no miraba en absoluto
       (eso apaga el CI de TODOS los PR contra main)

   La regex vigilaba UNA forma de escribir; el YAML admite infinitas. Por eso
   ahora el fichero se parsea con `yaml.safe_load` y se comprueban las CLAVES
   DEL MAPA, normalizadas: la comilla, el espacio y el orden dejan de existir
   como concepto antes de que el gate mire nada. Es la misma idea que `'**'`
   frente a la lista blanca: cubrir la familia entera por construccion en vez
   de enumerar los casos conocidos.

3. EJECUCION CONDICIONAL. La misma familia que (2), una vuelta mas: apagar la
   barrera sin tocar la barrera. Un revisor independiente demostro dos formas
   VIVAS sobre este mismo `ci.yml`, cada una de UNA linea:

     - `if: false` a nivel de job: el job de pruebas no se ejecuta y reporta
       `skipped`. No es `failure`, asi que nada se pone rojo, y una proteccion
       de rama puede dar por satisfecho un check saltado.
     - `continue-on-error: true`: el job o el paso falla y aun asi reporta
       exito. La barrera se evalua, falla, y no bloquea nada.

   Se prohiben en ambos niveles (job y paso). Unica condicion admitida:
   `always()`, la unica que solo puede hacer que se ejecute MAS. Ver
   `CONDICIONES_PERMITIDAS`.

   3 bis. LA MISMA FAMILIA, DENTRO DEL `run:`. `continue-on-error: true` estaba
   prohibido, pero `comando || true` hace EXACTAMENTE lo mismo una capa mas
   abajo: el comando se ejecuta, falla, y el paso sale en verde. Un revisor lo
   demostro VIVO sobre el gate de reproducibilidad de entorno —anadiendo
   `|| true` a la vez en `ci.yml` y en su fragmento, para que ni la
   comprobacion de fidelidad de fragmentos viera diferencia— y NINGUN control
   se entero. Prohibir `continue-on-error` en el YAML y dejar libre su
   equivalente en el shell era vigilar la puerta y no la ventana.

   Tambien aqui: un workflow puede perder un JOB entero en una resolucion de
   conflicto. Los gates listados en `JOBS_EXIGIDOS` tienen que seguir
   existiendo, por la misma razon por la que `supply-chain.yml` no puede
   desaparecer en silencio.

4. META-GATES. Un job en verde no prueba nada por si mismo. Dos formas de
   verde vacio ya vistas en este repositorio:

     - un job que ejecuta 0 tests (un filtro que no casa, un directorio que se
       renombra, una coleccion que se vacia) y sale con exito;
     - un test que se auto-omite cuando falta una herramienta (`skipif` sobre
       `shutil.which("node")`, `importorskip("playwright")`) y el job sigue
       verde: la prueba no existe el dia que el runner cambie de imagen.

   Ambas se comprueban aqui: todo paso que invoque pytest en un workflow
   vigilado tiene que llevar guardia anti-cero, y todo test que dependa de una
   herramienta externa tiene que tener un job que la instale, lo ejecute por
   nombre y lleve guardia anti-salto.

DEPENDENCIA: PyYAML. Es deliberado. La version anterior presumia de no tener
dependencias y por eso parseaba con regex, que es justo el defecto que este
fichero corrige. `pip install pyyaml` en el job es un precio menor que un gate
que se puede saltar con un espacio.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print(
        "::error::falta PyYAML y este gate parsea YAML de verdad (no con regex). "
        "Anade `pip install pyyaml` al job `check-ci-config`. NO se degrada a "
        "una comprobacion textual: seria volver al defecto que este gate cierra."
    )
    sys.exit(1)

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
SUPPLY = WORKFLOWS / "supply-chain.yml"
FRAGMENTO_NODE = REPO / ".github" / "ci-fragments" / "test-graph-js.yml"

# Todos los workflows cuya politica de disparo se EXIGE universal. No basta con
# `ci.yml`: `supply-chain.yml` es el unico que audita dependencias, y si vuelve
# a una lista blanca de prefijos reproduce exactamente el agujero silencioso
# que este gate existe para cerrar. Si uno DESAPARECE, es fallo: una barrera
# que puede dejar de existir sin ponerse roja no es una barrera.
WORKFLOWS_VIGILADOS = (CI, SUPPLY)

# Campos que pueden APAGAR CI sin tocar `branches`. Se prohiben bajo TODOS los
# disparadores relevantes, no solo `push`: un `paths-ignore` bajo
# `pull_request` apaga el CI de todos los PR contra main, que es peor.
CAMPOS_SILENCIADORES = ("paths", "paths-ignore", "branches-ignore")

# Disparadores cuyo bloque se inspecciona en busca de silenciadores.
DISPARADORES_VIGILADOS = ("push", "pull_request", "pull_request_target")

# Condiciones `if:` toleradas en un workflow vigilado. La lista es MINIMA a
# proposito y la razon es asimetrica:
#
#   El comportamiento por defecto de un paso o un job (ejecutarse si lo
#   anterior fue bien) es el MAXIMO de ejecucion. Cualquier `if:` distinto de
#   `always()` solo puede hacer que se ejecute MENOS, y un job que no se
#   ejecuta no reporta `failure`: reporta `skipped`, que a ojos de una
#   proteccion de rama puede contar como satisfecho. `always()` es la unica
#   condicion que va en la direccion contraria (ejecutar tambien cuando el
#   defecto no lo haria), asi que es la unica que no puede apagar nada.
#
# Si algun dia hace falta una condicion de verdad, la reparacion NO es
# relajarla aqui en silencio: es meter la decision DENTRO del `run:`, donde
# tiene que dejarla escrita y donde un fallo sale en rojo en vez de en gris.
CONDICIONES_PERMITIDAS = ("always()",)

# Formas de neutralizar el codigo de salida de un comando en `sh`. `|| true` es
# la canonica, `|| :` la misma con el builtin nulo, `|| exit 0` la misma
# escrita en largo. Todas convierten un rojo en un verde DENTRO del `run:`, que
# es `continue-on-error` por otra via.
RE_NEUTRALIZA = re.compile(r"\|\|\s*(true\b|:\s*$|:\s|exit\s+0\b)")

# La misma neutralizacion escrita como condicional, que es la forma MAS
# alcanzable por accidente porque no parece un truco:
#
#     if ! python3 .github/scripts/un_gate.py; then echo "ignorado"; fi
#
# El gate corre, falla, y el paso sale en verde. No se puede prohibir `if !` a
# secas: en `ci.yml` hay 9 usos y los 9 son LEGITIMOS —son las guardias
# anti-cero (`if ! grep -q 'N passed'; then ... exit 1`) que este mismo fichero
# EXIGE, mas una comprobacion de deriva con `git diff --quiet`—. Prohibirlas
# seria ponerse rojo por cumplir la propia regla.
#
# Lo que distingue una guardia de un apagado no es la sintaxis sino el DESENLACE:
# la guardia termina en `exit 1`, el apagado no. Asi que solo se mira el caso en
# que lo negado es un GATE (`.github/scripts/...`) y el bloque NO falla.
RE_IF = re.compile(r"(?:^|;|&&|\|\||\bthen\b|\bdo\b)\s*if\s")
RE_BLOQUE_FALLA = re.compile(r"(?:\bexit\s+(?:[1-9]\d*|\$)|\breturn\s+[1-9]\d*|\bfalse\b)")
INVOCA_GATE = ".github/scripts/"

# Una variable que guarda la ruta de un gate ES el gate. Sin esto, la
# indireccion evade la comprobacion:
#     G=".github/scripts/un_gate.py"
#     if ! python3 "$G" all; then echo x; fi
RE_ASIGNA = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

# Cuantas negaciones lleva el `if`. NO basta con «esta negado o no»: `! !` es
# bash valido y VUELVE A INVERTIR la polaridad, asi que
#
#     if ! ! GATE; then exit 1; fi
#
# tiene todo el aspecto de una guardia —lleva su `exit 1`— y hace lo contrario:
# con el gate ROJO la rama `then` no se ejecuta y el paso sale en VERDE.
# Comprobado ejecutandolo en bash, no leyendolo. Es un solo caracter de
# diferencia respecto de la guardia correcta, asi que la negacion multiple se
# RECHAZA de plano: no existe una razon legitima para escribirla, y calcular su
# paridad en silencio seria justo la clase de sutileza que nadie revisa.
RE_NEGACIONES = re.compile(r"\bif\s+((?:!\s*)+)")

# NO hay lista de excepciones, y no por descuido: se comprobo que los dos
# workflows vigilados no necesitan ninguna. Una exencion que hoy no hace falta
# es la rendija por la que manana entra el apagado, y este fichero existe
# porque eso ya paso tres veces.

# Jobs cuya AUSENCIA nadie mas detectaria. Un gate que puede desaparecer en una
# resolucion de conflicto sin que nada se ponga rojo no es un gate; el fragmento
# de restitucion existe justo porque eso ya ha estado a punto de pasar.
JOBS_EXIGIDOS = {
    "ci.yml": (
        "check-ci-config",
        "calibracion-de-gates",
        "check-env-reproducibility",
    ),
}

# Gates cuya INVOCACION tiene que seguir existiendo en `ci.yml`. `JOBS_EXIGIDOS`
# protege el job; esto protege el PASO. Son cosas distintas y la diferencia ya
# ha mordido: un job puede sobrevivir a una fusion con uno de sus pasos menos, y
# entonces el gate esta en el arbol, en verde, sin ejecutarse nunca.
#
# Los dos de aqui abajo son la respuesta al ejercicio RC 1, donde silenciar un
# fichero de test entero dejaba CI en verde. Si desaparecen, vuelve el agujero.
# Un gate que puede dejar de INVOCARSE sin ponerse rojo no es un gate. La lista
# protegia DOS scripts y para entonces habia SEIS: los otros cuatro se podian
# sustituir por un `echo` de una linea y este fichero seguia en EXIT=0. Entre
# ellos `check_ejecucion_real.py`, que es la GARANTIA PRINCIPAL frente a
# `xfail`, y el arnes de la base recien anadido —o sea que lo que acababa de
# escribirse podia dejar de correr sin que nada enrojeciera—. Comprobado en
# cadena: con la capa de resultados des-invocada, `check_suite_inventory.py`
# seguia saliendo EXIT=0 con su mensaje de siempre.
#
# La lista se mantiene A MANO y eso es una deuda conocida; lo que la hace
# soportable es que cada entrada tiene su caso de calibracion, asi que si
# alguien anade un gate y no lo mete aqui, el caso que falta se nota al
# escribirlo, no seis meses despues.
GATES_EXIGIDOS = {
    "ci.yml": (
        ".github/scripts/check_suite_inventory.py",
        ".github/scripts/calibra_suite_inventory.py",
        ".github/scripts/check_ejecucion_real.py",
        ".github/scripts/calibra_ejecucion_real.py",
        ".github/scripts/calibra_registro_xfail.py",
        ".github/scripts/calibra_base_materializada.py",
    ),
}

# Ramas efimeras de maquina: no se les EXIGE CI. Con la politica universal
# `**` de todas formas la tienen, y esto solo evita que su ausencia se pueda
# alegar como excusa; la exencion sigue siendo EXPLICITA y esta a la vista.
EXENTAS = ("worktree-*", "gh-readonly-queue/*", "revert-*")

# Nombres INVENTADOS a proposito. No son ramas reales ni pretenden serlo: son
# la calibracion del gate. Representan familias que hoy no existen y que
# manana apareceran igual que aparecieron `work/`, `impl/` e `integration/`.
#
# Su unico proposito es que una lista blanca NO pueda pasar el gate: para
# cubrirlos haria falta escribirlos, y no se pueden escribir porque no se
# sabe cuales seran. Si alguien anade estos nombres literalmente a ci.yml
# para poner el gate en verde, se ha saltado la comprobacion a mano y la
# revision lo vera en el diff.
RAMAS_SONDA = (
    # Familias reales que la lista blanca ya dejo sin cubrir alguna vez.
    "main",
    "feat/lo-que-sea",
    "fix/lo-que-sea",
    "test/lo-que-sea",
    "ops/lo-que-sea",
    "perf/lo-que-sea",
    "dependabot/pip/lo-que-sea",
    "work",
    "work-carril-a",
    "impl/lo-que-sea",
    "integration/lo-que-sea",
    "docs-estado-verificado",
    # Y familias que no existen: el corazon de la calibracion.
    "familia-que-aun-no-existe",
    "familia/que/aun/no/existe",
    "zzz-inventada-2099/sub/rama",
    "UPPERCASE-Y-Simbolos_.raros/x",
)

# Herramientas externas de las que dependen tests que se auto-omiten si faltan.
# Clave: nombre legible. Valores:
#   deteccion  -> regex que, en un fichero de test, indica que ese test se
#                 omite solo cuando la herramienta no esta;
#   instalador -> marcas que, en el texto de un job, prueban que la instala.
# La forma de la tabla es lo importante: anadir una herramienta nueva es una
# fila, no un `if` nuevo.
HERRAMIENTAS = {
    "Node": {
        "deteccion": (
            r"which\(\s*[\"']node[\"']\s*\)",
            r"which\(\s*[\"']npx?[\"']\s*\)",
        ),
        "instalador": ("actions/setup-node",),
        "remedio": f"Anade el job preparado en {FRAGMENTO_NODE.relative_to(REPO)}",
    },
    "Chromium/Playwright": {
        "deteccion": (
            r"importorskip\(\s*[\"']playwright",
            r"which\(\s*[\"'](chromium|google-chrome)[\"']\s*\)",
        ),
        "instalador": ("playwright install",),
        "remedio": (
            "Anade un job que haga `python -m playwright install --with-deps "
            "chromium`, ejecute esos tests por nombre y falle si aparece "
            "`skipped`"
        ),
    },
}

# Un paso que invoca pytest sin comprobar que ha ejecutado algo es un verde que
# no prueba nada. La guardia canonica es un `grep` sobre `N passed`.
#
# Ojo a la diferencia entre INVOCAR y INSTALAR: `pip install "pytest>=8.2"` no
# ejecuta ninguna prueba, asi que exigirle guardia seria ruido. Se busca la
# invocacion real (`python -m pytest ...` o `pytest ...` como comando).
RE_INVOCA_PYTEST = re.compile(r"(python[0-9.]*\s+-m\s+pytest|(?<![\w./\"'-])pytest\s)")
RE_INSTALA = re.compile(r"\bpip\s+install\b|\buv\s+pip\b")
RE_GUARDIA_CERO = re.compile(r"(grep|if|assert)[^\n]*passed", re.I)
RE_GUARDIA_SALTO = re.compile(r"(grep|if)[^\n]*skipped", re.I)


# --------------------------------------------------------------------------
# Parseo
# --------------------------------------------------------------------------

def carga(ruta: Path) -> dict:
    """Parsea un workflow. Un YAML que no parsea es fallo, no ausencia."""
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SystemExit(f"ERROR: {ruta.name} no es YAML valido: {exc}")
    if not isinstance(datos, dict):
        raise SystemExit(f"ERROR: {ruta.name} no es un mapa YAML en la raiz")
    return datos


def clave_normalizada(k) -> str:
    """`"paths-ignore"`, `paths-ignore ` y `paths-ignore` son la MISMA clave.

    Tras `safe_load` las comillas y el espacio antes de los dos puntos ya han
    desaparecido (son sintaxis, no contenido). Aqui solo queda normalizar
    espacios de sobra y mayusculas, para que el gate no dependa de como se
    escriba sino de que se declara.
    """
    return str(k).strip().lower()


def bloque_on(datos: dict, nombre: str) -> dict:
    """Devuelve el mapa de disparadores.

    Ojo: en YAML 1.1 la clave `on:` se parsea como el booleano `True`, no como
    la cadena `"on"`. Se aceptan ambas para no depender del parser.
    """
    for clave in (True, "on", "On", "ON"):
        if clave in datos:
            bloque = datos[clave]
            break
    else:
        raise SystemExit(f"ERROR: {nombre} no declara `on:`")
    if isinstance(bloque, str):
        return {bloque: None}
    if isinstance(bloque, list):
        return {str(x): None for x in bloque}
    if isinstance(bloque, dict):
        return {clave_normalizada(k): v for k, v in bloque.items()}
    raise SystemExit(f"ERROR: {nombre}: `on:` tiene una forma inesperada")


# --------------------------------------------------------------------------
# 1 + 2. Politica de disparo
# --------------------------------------------------------------------------

def comprueba_silenciadores(disparadores: dict, nombre: str) -> list[str]:
    """Ningun disparador vigilado puede apagar CI por detras de `branches`.

    Se miran las CLAVES DEL MAPA ya parseado, no el texto. Por eso da igual que
    se escriban entrecomilladas, con espacio antes de los dos puntos, en otro
    orden o en forma de flujo (`{paths-ignore: ['**']}`): todas colapsan a la
    misma clave antes de llegar aqui.
    """
    errores = []
    for trigger in DISPARADORES_VIGILADOS:
        cuerpo = disparadores.get(trigger)
        if not isinstance(cuerpo, dict):
            continue
        presentes = {clave_normalizada(k) for k in cuerpo}
        for campo in CAMPOS_SILENCIADORES:
            if campo in presentes:
                errores.append(
                    f"{nombre}: `on.{trigger}` declara `{campo}`. Ese campo "
                    f"APAGA CI en silencio sin tocar `branches`: con "
                    f"`branches: ['**']` intacto, un `paths-ignore: ['**']` "
                    f"bajo `push` deja de ejecutar CI en todas las ramas, y "
                    f"bajo `pull_request` deja sin CI a todos los PR contra "
                    f"main. En ambos casos la barrera deja de evaluarse y NADA "
                    f"se pone rojo. Si de verdad hace falta acotar por rutas, "
                    f"hazlo DENTRO del job (un paso que decida y lo deje "
                    f"escrito), no en el disparador."
                )
    return errores


def patrones_push(disparadores: dict, nombre: str) -> list[str]:
    """Extrae `on.push.branches` del YAML ya parseado.

    Sin regex: la lista inline `[ '**' ]`, la lista de guiones y la cadena
    suelta son la misma estructura despues de `safe_load`.
    """
    if "push" not in disparadores:
        raise SystemExit(
            f"ERROR: {nombre} no declara `on.push`. Sin disparador de push, "
            f"una rama puede desarrollarse entera sin senal: es exactamente el "
            f"agujero que este gate cierra."
        )
    cuerpo = disparadores["push"]
    if not isinstance(cuerpo, dict):
        raise SystemExit(
            f"ERROR: {nombre}: `on.push` no declara `branches`; la politica de "
            f"disparo tiene que estar escrita y ser universal (`- '**'`)"
        )
    cuerpo = {clave_normalizada(k): v for k, v in cuerpo.items()}
    if "branches" not in cuerpo:
        raise SystemExit(f"ERROR: no se encuentra `on.push.branches` en {nombre}")
    valor = cuerpo["branches"]
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list):
        raise SystemExit(f"ERROR: {nombre}: `on.push.branches` no es una lista")
    return [str(p).strip() for p in valor if str(p).strip()]


def cubierta(rama: str, patrones: list[str]) -> bool:
    for p in patrones:
        # En los filtros de GitHub, `**` casa tambien con `/`; `fnmatch` trata
        # `*` como comodin sin distinguir separadores, que es exactamente el
        # comportamiento de `**`. Para `*` (un solo segmento) hay que excluir
        # los que llevan `/` despues del prefijo.
        if p.endswith("/**"):
            # `feat/**` cubre `feat/x` y `feat/x/y`, pero NO la rama `feat`.
            if rama.startswith(p[:-3] + "/"):
                return True
        elif "*" in p:
            if fnmatch.fnmatch(rama, p) and (
                "/" not in rama[len(p.split("*", 1)[0]):] or "**" in p
            ):
                return True
        elif rama == p:
            return True
    return False


def ramas_remotas() -> list[str]:
    try:
        salida = subprocess.run(
            ["git", "ls-remote", "--heads", "origin"],
            cwd=REPO, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        print(f"AVISO: no se pudo consultar origin ({exc}); se usan refs locales")
        salida = None
    if salida is None or salida.returncode != 0:
        salida = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname)", "refs/remotes/origin"],
            cwd=REPO, capture_output=True, text=True, timeout=60,
        )
        if salida.returncode != 0:
            print("AVISO: sin acceso a las ramas; se omite la comprobacion de prefijos")
            return []
    ramas = []
    for linea in salida.stdout.splitlines():
        ref = linea.split()[-1]
        for prefijo in ("refs/heads/", "refs/remotes/origin/"):
            if ref.startswith(prefijo):
                ramas.append(ref[len(prefijo):])
    return [r for r in ramas if r and r != "HEAD"]


def comprueba_disparo(datos: dict, nombre: str) -> list[str]:
    """La politica debe cubrir CUALQUIER rama, no una lista de las de hoy."""
    disparadores = bloque_on(datos, nombre)

    # 0. Antes que la cobertura: que no haya un campo capaz de apagar CI sin
    #    que `branches` cambie. Si lo hay, `branches` ya no decide nada.
    silenciadores = comprueba_silenciadores(disparadores, nombre)

    patrones = patrones_push(disparadores, nombre)
    print(f"{nombre}: patrones de `on.push.branches`: {patrones}")

    # 1. La propiedad. Se prueba contra nombres inventados, que es lo que
    #    ninguna lista blanca puede cubrir.
    sin_cubrir = [r for r in RAMAS_SONDA if not cubierta(r, patrones)]
    if sin_cubrir:
        return silenciadores + [
            f"{nombre}: `on.push.branches` NO cubre toda rama: no dispararian CI, entre "
            f"otros, {sin_cubrir}. La reparacion NO es anadir esos nombres "
            "(son inventados, y manana seran otros) sino dejar la politica "
            "universal:\n"
            "      push:\n"
            "        branches:\n"
            "          - '**'\n"
            f"    Asi una rama nueva tiene CI el dia que nace, sin editar {nombre}."
        ]

    # 2. Ademas, y como red por si la propiedad se cumpliera por accidente:
    #    ninguna rama que exista HOY en origin puede quedarse fuera.
    errores = list(silenciadores)
    for rama in sorted(set(ramas_remotas())):
        if any(fnmatch.fnmatch(rama, e) for e in EXENTAS):
            continue
        if not cubierta(rama, patrones):
            errores.append(
                f"{nombre}: la rama `{rama}` existe en origin y NO dispara CI al hacer push"
            )
    return errores


# --------------------------------------------------------------------------
# 3. META-GATES
# --------------------------------------------------------------------------

def texto_de_pasos(job: dict) -> str:
    """Concatena los `run:` de un job. Es lo unico que ejecuta comandos."""
    if not isinstance(job, dict):
        return ""
    trozos = []
    for paso in job.get("steps") or []:
        if isinstance(paso, dict):
            for campo in ("run", "uses", "name"):
                valor = paso.get(campo)
                if isinstance(valor, str):
                    trozos.append(valor)
    return "\n".join(trozos)


def pasos_run(job: dict) -> list[tuple[str, str]]:
    """(nombre del paso, cuerpo del `run:`) de cada paso que ejecuta comandos."""
    salida = []
    if not isinstance(job, dict):
        return salida
    for paso in job.get("steps") or []:
        if isinstance(paso, dict) and isinstance(paso.get("run"), str):
            salida.append((str(paso.get("name") or "(sin nombre)"), paso["run"]))
    return salida


def comprueba_cero_tests(datos: dict, nombre: str) -> list[str]:
    """Un job que ejecuta 0 tests y sale en verde no comprueba nada.

    pytest sale con codigo 5 cuando no colecciona nada, pero basta un `-q` con
    filtro que no casa, un directorio renombrado o un `|| true` para que el
    paso pase. La unica prueba de que el job ha EJECUTADO algo es que lo
    afirme: una guardia sobre `N passed`.
    """
    errores = []
    for job_id, job in (datos.get("jobs") or {}).items():
        for paso_nombre, cuerpo in pasos_run(job):
            invoca = any(
                RE_INVOCA_PYTEST.search(linea) and not RE_INSTALA.search(linea)
                for linea in cuerpo.splitlines()
            )
            if not invoca:
                continue
            if RE_GUARDIA_CERO.search(cuerpo):
                continue
            errores.append(
                f"{nombre}: el job `{job_id}`, paso `{paso_nombre}`, invoca "
                f"pytest SIN guardia anti-cero. Si esa invocacion llega a "
                f"ejecutar 0 tests (filtro que no casa, directorio renombrado, "
                f"coleccion vacia) el job sale VERDE sin haber comprobado "
                f"nada. Captura la salida y anade:\n"
                f"      if ! grep -qE '[0-9]+ passed' <<<\"$out\"; then\n"
                f"        echo '::error::no se ejecuto ninguna prueba'; exit 1\n"
                f"      fi"
            )
    return errores


def _normaliza_condicion(valor) -> str:
    """`${{ always() }}`, `always()` y `ALWAYS( )` son la misma condicion."""
    texto = str(valor).strip()
    if texto.startswith("${{") and texto.endswith("}}"):
        texto = texto[3:-2]
    return "".join(texto.split()).lower()


def comprueba_ejecucion_condicional(datos: dict, nombre: str) -> list[str]:
    """Un job puede apagarse entero con UNA linea, sin tocar el disparador.

    Dos formas, ambas demostradas VIVAS sobre este mismo `ci.yml`:

      - `if: false` a nivel de job: el job no se ejecuta y reporta `skipped`.
        No es `failure`, asi que nada se pone rojo; y una proteccion de rama
        puede dar por satisfecho un check saltado.
      - `continue-on-error: true`: el job (o el paso) puede fallar y aun asi
        reportar exito. La barrera se evalua, falla, y no bloquea nada.

    Es exactamente la familia de `paths-ignore`: la barrera deja de decidir sin
    que la barrera cambie. Por eso se tratan igual —presencia = fallo— y no
    como aviso. Se miran las CLAVES DEL MAPA ya parseado, asi que la comilla,
    el espacio antes de los dos puntos y el orden vuelven a dar igual.
    """
    errores = []
    permitidas = {_normaliza_condicion(c) for c in CONDICIONES_PERMITIDAS}

    def revisa(claves: dict, donde: str) -> None:
        if "if" in claves:
            cond = claves["if"]
            if _normaliza_condicion(cond) not in permitidas:
                errores.append(
                    f"{nombre}: {donde} declara `if: {cond}`. Una condicion "
                    f"solo puede hacer que se ejecute MENOS: si no se cumple, "
                    f"no hay `failure`, hay `skipped`, y un check saltado no "
                    f"pone nada rojo (y una proteccion de rama puede darlo por "
                    f"satisfecho). `if: false` apaga un job de pruebas entero "
                    f"con una linea. Unica condicion admitida: "
                    f"{list(CONDICIONES_PERMITIDAS)}. Si de verdad hace falta "
                    f"decidir, hazlo DENTRO del `run:`, donde queda escrito y "
                    f"donde un fallo sale en rojo, no en gris."
                )
        if "continue-on-error" in claves:
            valor = claves["continue-on-error"]
            if valor is not False:
                errores.append(
                    f"{nombre}: {donde} declara `continue-on-error: {valor}`. "
                    f"Eso convierte un rojo en un verde: la barrera se evalua, "
                    f"falla, y NO bloquea nada. Una barrera que no puede "
                    f"bloquear no es una barrera. Quitalo; si un paso puede "
                    f"fallar sin consecuencias, es que no deberia estar en un "
                    f"workflow vigilado."
                )

    for job_id, job in (datos.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        revisa({clave_normalizada(k): v for k, v in job.items()}, f"el job `{job_id}`")
        for i, paso in enumerate(job.get("steps") or []):
            if not isinstance(paso, dict):
                continue
            etiqueta = str(paso.get("name") or paso.get("uses") or f"#{i}")
            revisa(
                {clave_normalizada(k): v for k, v in paso.items()},
                f"el job `{job_id}`, paso `{etiqueta}`",
            )
    return errores


def comprueba_neutralizacion(datos: dict, nombre: str) -> list[str]:
    """`comando || true` es `continue-on-error` escrito dentro del `run:`.

    Se mira SOLO el codigo: en estos workflows hay comentarios que dicen «Sin
    `|| true`: ...», y tomarlos por codigo seria el defecto simetrico —un gate
    que se pone rojo por un comentario—. Por eso se corta cada linea en el `#`
    antes de buscar nada, igual que el resto del fichero mira claves parseadas
    y no texto.
    """
    errores = []
    for job_id, job in (datos.get("jobs") or {}).items():
        for paso_nombre, cuerpo in pasos_run(job):
            for linea in cuerpo.splitlines():
                codigo = linea.split("#", 1)[0]
                if not codigo.strip() or not RE_NEUTRALIZA.search(codigo):
                    continue
                errores.append(
                    f"{nombre}: el job `{job_id}`, paso `{paso_nombre}`, "
                    f"neutraliza el codigo de salida de un comando: "
                    f"`{codigo.strip()}`. Eso convierte un rojo en un verde "
                    f"exactamente igual que `continue-on-error: true`, solo que "
                    f"una capa mas abajo: el comando se ejecuta, falla, y el "
                    f"paso sale en verde. Si el fallo de ese comando de verdad "
                    f"no importa, capturalo (`out=$(cmd) || rc=$?`) y DECIDE "
                    f"con el codigo a la vista, para que la decision quede "
                    f"escrita en vez de desaparecer."
                )
    return errores


def _bloque_if(lineas: list[str], inicio: int) -> list[str]:
    """Lineas del `if ... fi` que empieza en `inicio` (contando anidamiento).

    Corta tambien cuando el `if` entero cabe en UNA linea (`if ...; then ...;
    fi`): antes se seguia leyendo mas alla del `fi` y la guardia de una sola
    linea se leia como si no tuviera `exit 1`.
    """
    profundidad = 0
    fuera = []
    for linea in lineas[inicio:]:
        fuera.append(linea)
        profundidad += len(re.findall(r"(?:^|;|&&|\|\||\bthen\b|\bdo\b)\s*if\s", linea))
        profundidad -= len(re.findall(r"(?:^|;)\s*fi\b", linea))
        if profundidad <= 0:
            break
    return fuera


def variables_de_gate(lineas: list[str], marca: str) -> set[str]:
    """Variables cuyo valor contiene la ruta de un gate."""
    return {
        m.group(1)
        for m in (RE_ASIGNA.match(l) for l in lineas)
        if m and marca in m.group(2)
    }


def _invoca_gate(texto: str, marca: str, variables: set[str]) -> bool:
    if marca in texto:
        return True
    return any(
        re.search(rf"\$\{{?{re.escape(v)}\}}?", texto) for v in variables
    )


def gates_sin_desenlace(cuerpo: str, marca: str = INVOCA_GATE) -> list[str]:
    """`if` que ejecuta un gate y cuya rama de FALLO no falla.

    El discriminante es el DESENLACE, no la sintaxis, y se aplica a la forma
    del `if` completa —no solo a `if !`—, porque la negacion se puede desplazar
    sin cambiar el efecto:

        if ! GATE; then echo x; fi          -> la rama de fallo es el `then`
        if GATE; then :; else echo x; fi    -> la rama de fallo es el `else`
        if GATE; then echo ok; fi           -> la rama de fallo esta VACIA

    Las tres dejan el paso en verde con el gate rojo. Y la ruta del gate se
    reconoce tambien a traves de una VARIABLE, porque la indireccion no cambia
    lo que se ejecuta.

    Una rama de fallo que termina en `exit 1` es una guardia legitima: no se
    toca. Por eso los 9 `if !` reales de `ci.yml` —las guardias anti-cero que
    este mismo fichero exige— siguen en verde: su condicion ni siquiera invoca
    un gate.
    """
    lineas = [l.split("#", 1)[0] for l in cuerpo.splitlines()]
    variables = variables_de_gate(lineas, marca)
    hallazgos = []
    for i, linea in enumerate(lineas):
        if not RE_IF.search(linea):
            continue
        texto = "\n".join(_bloque_if(lineas, i))
        m_then = re.search(r"\bthen\b", texto)
        if not m_then:
            continue
        condicion = texto[: m_then.start()]
        if not _invoca_gate(condicion, marca, variables):
            continue
        m_neg = RE_NEGACIONES.search(condicion)
        negaciones = m_neg.group(1).count("!") if m_neg else 0
        if negaciones > 1:
            # Polaridad invertida: parece guardia y apaga. Se rechaza sin
            # mirar las ramas, porque el problema es la condicion misma.
            hallazgos.append(("doble-negacion", condicion.strip().replace("\n", " ")))
            continue
        resto = re.sub(r"\bfi\b\s*$", "", texto[m_then.end():].rstrip())
        m_else = re.search(r"(?:^|;|\n)\s*else\b", resto)
        rama_then = resto[: m_else.start()] if m_else else resto
        rama_else = resto[m_else.end():] if m_else else ""
        rama_fallo = rama_then if negaciones == 1 else rama_else
        if not RE_BLOQUE_FALLA.search(rama_fallo):
            hallazgos.append(("sin-desenlace", condicion.strip().replace("\n", " ")))
    return hallazgos


def comprueba_if_negado(datos: dict, nombre: str) -> list[str]:
    errores = []
    for job_id, job in (datos.get("jobs") or {}).items():
        for paso_nombre, cuerpo in pasos_run(job):
            for clase, linea in gates_sin_desenlace(cuerpo):
                donde = f"{nombre}: el job `{job_id}`, paso `{paso_nombre}`"
                if clase == "doble-negacion":
                    errores.append(
                        f"{donde}, ejecuta un gate con NEGACION MULTIPLE: "
                        f"`{linea}`. `! !` es bash valido y vuelve a invertir "
                        f"la polaridad: aunque la rama lleve su `exit 1`, con "
                        f"el gate ROJO esa rama NO se ejecuta y el paso sale en "
                        f"VERDE. Tiene el aspecto exacto de una guardia "
                        f"correcta y hace lo contrario, con un solo caracter de "
                        f"diferencia. Escribe una sola negacion."
                    )
                else:
                    errores.append(
                        f"{donde}, ejecuta un gate dentro de un `if` cuya rama "
                        f"de FALLO no falla: `{linea}`. El gate corre, se pone "
                        f"rojo, y el paso sale en VERDE: es `|| true` escrito "
                        f"como condicional. Da igual donde este la negacion "
                        f"(`if !`, un `else`, o ninguna rama), y da igual que "
                        f"la ruta llegue por una variable: lo que cuenta es que "
                        f"cuando el gate falla no pasa nada. La rama de fallo "
                        f"tiene que terminar en `exit 1`; si no, invoca el gate "
                        f"a secas y deja decidir a su codigo de salida."
                    )
    return errores


def comprueba_jobs_exigidos(datos: dict, nombre: str) -> list[str]:
    """Un gate que puede desaparecer sin ponerse rojo no es un gate."""
    exigidos = JOBS_EXIGIDOS.get(nombre, ())
    if not exigidos:
        return []
    presentes = {clave_normalizada(k) for k in (datos.get("jobs") or {})}
    return [
        f"{nombre}: falta el job `{job}`. Es una barrera: si un merge o una "
        f"resolucion de conflicto se la lleva por delante, deja de evaluarse y "
        f"NADA se pone rojo. Restituyelo (hay copia canonica en "
        f".github/ci-fragments/ para los que la tienen)."
        for job in exigidos
        if job not in presentes
    ]




def _ambitos_anidados(nodo):
    """Los sub-ambitos directos: defs anidados, lambdas y clases."""
    import ast
    return (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _nodos_propios(ambito):
    """Nodos que pertenecen a ESTE ambito, sin entrar en los anidados.

    Sin esto, los parametros de una funcion anidada se atribuian a la de fuera
    y salian como "no definidos". Lo detecte con el propio control: sus 20
    primeros hallazgos eran TODOS falsos positivos de esta clase, ninguno un
    defecto del repositorio. Un control que grita sobre codigo correcto es tan
    inutil como uno que calla: se arregla el control, no se silencia el aviso.
    """
    import ast
    cuerpo = list(getattr(ambito, "body", []))
    if not isinstance(cuerpo, list):
        cuerpo = [cuerpo]
    pila = list(cuerpo)
    while pila:
        nodo = pila.pop()
        yield nodo
        # Se YIELDA el ambito anidado (para que quien recorre sepa que existe y
        # baje a el con su propio contexto) pero NO se desciende dentro. La
        # version anterior filtraba al empujar y no al sacar, asi que los
        # cuerpos de las funciones de primer nivel se recorrian como si fueran
        # el modulo: 156 falsos positivos. Lo delato el propio control.
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda, ast.ClassDef)):
            continue
        for hijo in ast.iter_child_nodes(nodo):
            pila.append(hijo)


def _nombres_ligados(ambito) -> set:
    """Nombres que este ambito LIGA (sin contar los de ambitos anidados)."""
    import ast
    ligados = set()
    args = getattr(ambito, "args", None)
    if args is not None:
        for grupo in (args.posonlyargs, args.args, args.kwonlyargs):
            ligados |= {x.arg for x in grupo}
        for extra in (args.vararg, args.kwarg):
            if extra:
                ligados.add(extra.arg)
    for nodo in _nodos_propios(ambito):
        if isinstance(nodo, ast.Name) and isinstance(nodo.ctx, (ast.Store, ast.Del)):
            ligados.add(nodo.id)
        elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ligados.add(nodo.name)
        elif isinstance(nodo, (ast.Import, ast.ImportFrom)):
            for alias in nodo.names:
                ligados.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(nodo, ast.ExceptHandler) and nodo.name:
            ligados.add(nodo.name)
        elif isinstance(nodo, ast.Global):
            ligados |= set(nodo.names)
    return ligados


def comprueba_nombres_definidos(rutas) -> list:
    """Nombres usados que NO existen en ningun ambito visible.

    EXISTE POR UN DEFECTO PROPIO. Un empalme por ancla borro
    `RE_ASIGNA_NOMBRE_CONSTRUIDO` de `check_suite_inventory.py`: el fichero
    seguia COMPILANDO -`ast.parse` no protesta por un nombre inexistente- y el
    fallo solo aparecia al EJECUTAR la rama que lo usa. Un gate cuyo codigo se
    rompe en silencio es un gate que puede dejar de mirar sin avisar, que es la
    familia entera de este carril.

    Ademas cierra una afirmacion que llegue a escribir sin que existiera como
    codigo: dije que habia una "comprobacion estructural de definiciones contra
    el commit anterior" y era una comprobacion manual de una vez. O se
    implementa o se retira; esto es implementarla, con su caso de calibracion.

    Es ESTATICA y modesta: no reemplaza a los arneses, caza la clase concreta
    de fallo que se pago.
    """
    import ast
    import builtins
    problemas = []
    base = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__"}

    def recorre(ambito, visibles, ruta):
        propios = visibles | _nombres_ligados(ambito)
        for nodo in _nodos_propios(ambito):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.Lambda, ast.ClassDef)):
                recorre(nodo, propios, ruta)
                continue
            if isinstance(nodo, ast.Name) and isinstance(nodo.ctx, ast.Load):
                if nodo.id not in propios:
                    donde = getattr(ambito, "name", "<modulo>")
                    problemas.append(
                        f"{ruta.name}:{nodo.lineno}: `{nodo.id}` se usa en "
                        f"`{donde}` y NO esta definido en ningun ambito. El "
                        f"fichero compila igual, asi que esto solo saldria al "
                        f"ejecutar esa rama, o no saldria.")

    for ruta in rutas:
        try:
            arbol = ast.parse(ruta.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            problemas.append(f"{ruta.name}: no parsea ({e.msg})")
            continue
        recorre(arbol, base, ruta)
    return problemas


def comprueba_gates_exigidos(datos: dict, nombre: str) -> list[str]:
    """Un gate que puede dejar de INVOCARSE sin ponerse rojo no es un gate."""
    exigidos = GATES_EXIGIDOS.get(nombre, ())
    if not exigidos:
        return []
    # Solo cuentan las lineas que EJECUTAN el gate. Nombrarlo en un comentario
    # o dentro de un `echo` no lo ejecuta, y la primera version de esta
    # comprobacion se daba por satisfecha con eso: su propia calibracion la
    # cazo saliendo VERDE con las dos invocaciones sustituidas por `echo`.
    lineas = []
    for job in (datos.get("jobs") or {}).values():
        for _, cuerpo in pasos_run(job):
            lineas += cuerpo.splitlines()
    invocadas = [l for l in lineas
                 if re.match(r"\s*(sudo\s+)?python[0-9.]*\s+\S*\.py\b", l)]
    texto = "\n".join(invocadas)
    return [
        f"{nombre}: ningun paso invoca `{gate}`. El fichero puede seguir en el "
        f"arbol y no ejecutarse NUNCA: el gate estaria en verde sin comprobar "
        f"nada, que es justo el fallo que ese gate existe para cerrar."
        for gate in exigidos
        if gate not in texto
    ]


def ficheros_con_skip_critico() -> dict[str, list[str]]:
    """Tests que se auto-omiten si falta una herramienta -> herramientas."""
    hallazgos: dict[str, list[str]] = {}
    raices = [REPO / "viewer" / "tests", REPO / "data-engine", REPO / "contracts",
              REPO / "tests", REPO / "shared", REPO / "scripts"]
    vistos = set()
    for raiz in raices:
        if not raiz.exists():
            continue
        for py in raiz.rglob("*.py"):
            if any(p in (".git", "node_modules", ".venv", "__pycache__") for p in py.parts):
                continue
            rel = py.relative_to(REPO).as_posix()
            if rel in vistos:
                continue
            vistos.add(rel)
            try:
                cuerpo = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for herramienta, cfg in HERRAMIENTAS.items():
                if any(re.search(p, cuerpo) for p in cfg["deteccion"]):
                    hallazgos.setdefault(rel, []).append(herramienta)
    return hallazgos


def referencias_posibles(rel: str) -> list[str]:
    """Formas en que un job puede nombrar ese fichero (o su directorio).

    Los jobs hacen `cd viewer` y luego `pytest tests/browser`, asi que hay que
    aceptar sufijos de la ruta y tambien los directorios que la contienen.
    """
    partes = rel.split("/")
    refs = []
    for i in range(len(partes)):
        refs.append("/".join(partes[i:]))
    # Directorios contenedores, tambien por sufijos.
    for corte in range(1, len(partes)):
        dir_partes = partes[:-corte]
        for i in range(len(dir_partes)):
            sufijo = "/".join(dir_partes[i:])
            if sufijo:
                refs.append(sufijo)
    return [r for r in dict.fromkeys(refs) if r not in ("tests", "viewer")]


def comprueba_skips_criticos(datos: dict, nombre: str) -> list[str]:
    """Un test que se omite por falta de herramienta es un test que no existe.

    Para cada fichero que se auto-omite se exige un job que, a la vez:
      (a) instale la herramienta,
      (b) lo ejecute NOMBRANDOLO (si no, solo corre en jobs sin la herramienta,
          donde se omite), y
      (c) falle si la salida contiene `skipped`.
    Las tres condiciones en el MISMO job: cumplirlas en jobs distintos no
    ejecuta nada con guardia.
    """
    errores = []
    jobs = datos.get("jobs") or {}
    textos = {jid: texto_de_pasos(job) for jid, job in jobs.items()}

    for rel, herramientas in sorted(ficheros_con_skip_critico().items()):
        refs = referencias_posibles(rel)
        for herramienta in herramientas:
            cfg = HERRAMIENTAS[herramienta]
            candidatos = [
                jid for jid, txt in textos.items()
                if any(m in txt for m in cfg["instalador"])
            ]
            if not candidatos:
                errores.append(
                    f"{rel} se auto-omite si falta {herramienta} y NINGUN job de "
                    f"{nombre} la instala: esas pruebas se saltarian en verde. "
                    f"{cfg['remedio']}"
                )
                continue
            ejecutan = [jid for jid in candidatos if any(r in textos[jid] for r in refs)]
            if not ejecutan:
                errores.append(
                    f"{rel} depende de {herramienta} y ningun job de {nombre} que "
                    f"la instale lo ejecuta por nombre; sin eso solo corre en "
                    f"jobs sin {herramienta}, donde se OMITE en silencio"
                )
                continue
            if not any(RE_GUARDIA_SALTO.search(textos[jid]) for jid in ejecutan):
                errores.append(
                    f"{rel} se ejecuta en {ejecutan} con {herramienta} instalada, "
                    f"pero ningun job de esos falla si la salida dice `skipped`. "
                    f"El dia que la instalacion se rompa, el test se auto-omite "
                    f"y el job sigue VERDE. Anade:\n"
                    f"      if grep -qi skipped <<<\"$out\"; then\n"
                    f"        echo '::error::pruebas OMITIDAS con la herramienta "
                    f"disponible'; exit 1\n"
                    f"      fi"
                )
    return errores


# --------------------------------------------------------------------------

def main() -> int:
    errores = []
    parseados = {}
    for ruta in WORKFLOWS_VIGILADOS:
        if not ruta.exists():
            errores.append(
                f"{ruta.name}: el workflow no existe. Se exige su politica de "
                f"disparo universal; si desaparece, la comprobacion no puede "
                f"darse por satisfecha en silencio."
            )
            continue
        datos = carga(ruta)
        parseados[ruta.name] = datos
        errores += comprueba_disparo(datos, ruta.name)
        errores += comprueba_cero_tests(datos, ruta.name)
        errores += comprueba_ejecucion_condicional(datos, ruta.name)
        errores += comprueba_neutralizacion(datos, ruta.name)
        errores += comprueba_if_negado(datos, ruta.name)
        errores += comprueba_jobs_exigidos(datos, ruta.name)
        errores += comprueba_gates_exigidos(datos, ruta.name)

    # Los gates tienen que estar SANOS, no solo invocados: un nombre que no
    # existe no rompe el import, solo la rama que lo usa.
    guardados = sorted((REPO / ".github" / "scripts").glob("*.py"))
    errores += comprueba_nombres_definidos(guardados)

    if CI.name in parseados:
        errores += comprueba_skips_criticos(parseados[CI.name], CI.name)

    for e in errores:
        print(f"::error::{e}")
    if errores:
        print(f"\nFALLO: {len(errores)} problema(s) de integridad de gates")
        return 1
    print(
        "OK: ci.yml y supply-chain.yml disparan en toda rama, sin campos que "
        "puedan apagar CI en silencio (comprobado sobre el YAML parseado, no "
        "sobre el texto), sin `if:` ni `continue-on-error` que apaguen o "
        "desarmen un job, sin `|| true` que haga lo mismo dentro del `run:`, "
        "sin que falte ninguno de los jobs exigidos, sin jobs que puedan "
        "ejecutar 0 tests en verde y sin tests que se omitan por falta de Node "
        "o Chromium"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
