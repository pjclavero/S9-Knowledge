#!/usr/bin/env python3
"""Calibracion de `check_ci_config.py`: el gate tiene que PONERSE ROJO.

Regla del operador: «Una afirmacion no constituye evidencia porque exista un
test verde. La evidencia aparece cuando: sabes que comportamiento afirma;
calibras el mecanismo que lo mide; introduces una violacion; el sistema se pone
rojo; reviertes; vuelve a verde.» Un gate que nunca se ha visto ROJO no es un
gate.

Este script introduce cada violacion de verdad —escribe el fichero, ejecuta el
gate, lee el codigo de retorno, y restaura— y refleja el resultado real. No
simula: si el gate deja de detectar un caso, aqui sale FALLO.

    ┌───────────────────────────────────────────────────────────────────────┐
    │  AVISO: ESTE SCRIPT MUTA `ci.yml` REAL, EN EL SITIO.                  │
    │                                                                       │
    │  Mientras corre, el `ci.yml` del arbol de trabajo esta ROTO A         │
    │  PROPOSITO durante unos segundos por caso. Cualquier otra cosa que    │
    │  lea el repositorio a la vez —otro arnes, otro gate, un `git status`  │
    │  del que te fies— vera esa mutacion y dara un resultado FALSO.        │
    │                                                                       │
    │  NO LO EJECUTES EN PARALELO con nada que lea el repositorio. Ya ha    │
    │  provocado rojos que no eran reales, y un rojo falso cuesta mas caro  │
    │  que uno real: enseña a desconfiar del instrumento.                   │
    │                                                                       │
    │  Para que el descuido no sea silencioso, el script toma un CERROJO    │
    │  (`.git/s9k-calibra-gate.lock`) y se niega a arrancar si ya hay otra  │
    │  copia corriendo. El cerrojo protege de dos escrituras simultaneas;   │
    │  de un LECTOR concurrente no puede protegerte: eso es cosa tuya.      │
    │                                                                       │
    │  Restaura SIEMPRE en `finally`, incluso si lo interrumpes con Ctrl-C. │
    └───────────────────────────────────────────────────────────────────────┘

Uso:  python3 .github/scripts/calibra_gate_integrity.py
Sale 0 si TODOS los casos dan el veredicto esperado.
"""
from __future__ import annotations

import fcntl
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / ".github" / "scripts" / "check_ci_config.py"
CI = REPO / ".github" / "workflows" / "ci.yml"
SUPPLY = REPO / ".github" / "workflows" / "supply-chain.yml"
E2E_CONFTEST = REPO / "tests" / "e2e" / "conftest.py"

# Ficheros que cualquier mutacion puede tocar; se salvan y restauran enteros.
# `check_suite_inventory.py` entra en la lista porque un caso nuevo le borra
# una definicion de nivel superior para calibrar el control de nombres.
GATE_INVENTARIO = REPO / ".github" / "scripts" / "check_suite_inventory.py"
TOCABLES = (CI, SUPPLY, E2E_CONFTEST, GATE_INVENTARIO)

VERDE, ROJO = "VERDE", "ROJO"

# Cerrojo: dos copias de este script mutando `ci.yml` a la vez se pisan y
# producen rojos que no son reales.
#
# En un clon normal vive en `.git/` (existe, no se versiona). En un WORKTREE
# `.git` es un FICHERO, no un directorio, asi que se cae a un temporal del
# sistema — comprobado, no supuesto—. Ese temporal es compartido por todos los
# worktrees de la maquina, lo que ademas es lo que se quiere: dos worktrees del
# mismo repo calibrando a la vez tambien se pisarian.
CERROJO = (REPO / ".git" / "s9k-calibra-gate.lock") if (REPO / ".git").is_dir() \
    else Path(tempfile.gettempdir()) / "s9k-calibra-gate.lock"


def toma_cerrojo():
    """Devuelve el descriptor del cerrojo, o aborta si ya lo tiene otro."""
    fh = open(CERROJO, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise SystemExit(
            f"ERROR: ya hay otra calibracion corriendo ({CERROJO}).\n"
            f"Este script MUTA `ci.yml` en el sitio; dos a la vez se pisan y "
            f"producen rojos falsos. Espera a que termine la otra."
        )
    return fh


def ejecuta_gate() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(GATE)],
        cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    return p.returncode, (p.stdout + p.stderr)


# Ramas REALES de origin capturadas el dia que se escribio esta calibracion.
# Estan aqui para que el caso «lista blanca exhaustiva» funcione TAMBIEN en un
# runner de CI, donde `refs/remotes/origin` no existe porque el checkout no
# trae las ramas. Sin esto, el caso mas importante de la calibracion se
# saltaria en silencio justo donde mas falta hace, y ausencia de dato no puede
# convertirse en caso no probado.
RAMAS_REALES_CONOCIDAS = (
    "main",
    "audit/data-contract-health-v1",
    "audit/viewer-route-contract-map",
    "chore/ci-perf-branch-trigger",
    "chore/ci-test-branches-y-node",
    "cierre/carril-a",
    "docs/panel-rpg-management-design",
    "feat/admin-operations-dashboard",
    "feat/m5b-fog-of-war-design",
    "feat/m5b0-fog-of-war-contract",
    "feat/multipartida-m5a-visor",
    "feat/review-console-v2-readonly",
    "feat/viewer-graph-ux-v2",
    "fix/graph-ux-v2-h1h2h4",
    "fix/test-fixture-secret-reference",
    "fix/v3-semantic-extractor-e2e",
    "impl/v3-review-feed-and-glossary",
    "impl/v3-semantic-shadow-and-factivity",
    "ops/release-readiness-v1",
    "ops/v3-release-readiness",
    "perf/viewer-scale-baseline-v1",
    "test/v3-final-core-gates",
    "test/viewer-browser-e2e-v1",
    "work",
    "work-a",
    "work-carril-a",
)


def ramas_de_origin() -> list[str]:
    """Las ramas que haya HOY en origin, UNIDAS a las conocidas.

    La union es deliberada: en CI la primera fuente esta vacia, y un caso de
    calibracion que no se ejecuta por falta de datos es exactamente el agujero
    silencioso que este gate existe para cerrar.
    """
    p = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
        cwd=REPO, capture_output=True, text=True, timeout=60,
    )
    ramas = set(RAMAS_REALES_CONOCIDAS)
    for linea in p.stdout.split():
        nombre = linea[len("origin/"):] if linea.startswith("origin/") else linea
        if nombre and nombre != "HEAD":
            ramas.add(nombre)
    return sorted(ramas)


# --------------------------------------------------------------------------
# Mutaciones. Cada una devuelve None; opera sobre los ficheros del repo.
# --------------------------------------------------------------------------

def _sustituye(ruta: Path, viejo: str, nuevo: str) -> None:
    """Sustituye un ANCLA LITERAL en el fichero indicado.

    OJO al mantenerlo: varias mutaciones se anclan al texto EXACTO de la
    linea que invoca un gate en `ci.yml`. Si esa invocacion se reescribe
    —se le cambia un flag, se parte en dos lineas, se renombra el script—,
    el ancla deja de encontrarse. No es un agujero: `_sustituye` aborta con
    `MUTACION IMPOSIBLE` y la calibracion entera falla en voz alta, que es
    justo lo que debe pasar. Pero el arreglo es actualizar el ancla aqui,
    no relajar la comprobacion.
    """
    texto = ruta.read_text(encoding="utf-8")
    if viejo not in texto:
        raise SystemExit(f"MUTACION IMPOSIBLE: no se encuentra el ancla en {ruta.name}")
    ruta.write_text(texto.replace(viejo, nuevo, 1), encoding="utf-8")


PUSH_CI = "  push:\n    branches:\n      - '**'\n"
PR_CI = "  pull_request:\n    branches: [ main ]\n"


def m_paths_ignore_push() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches:\n      - '**'\n    paths-ignore: ['**']\n")


def m_paths_ignore_pr() -> None:
    _sustituye(CI, PR_CI, "  pull_request:\n    branches: [ main ]\n    paths-ignore: ['**']\n")


def m_paths_ignore_entrecomillado() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches:\n      - '**'\n    \"paths-ignore\": ['**']\n")


def m_paths_ignore_espacio() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches:\n      - '**'\n    paths-ignore : ['**']\n")


def m_paths_push() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches:\n      - '**'\n    paths: ['viewer/**']\n")


def m_paths_pr() -> None:
    _sustituye(CI, PR_CI, "  pull_request:\n    branches: [ main ]\n    paths: ['viewer/**']\n")


def m_branches_ignore() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches:\n      - '**'\n    branches-ignore: ['ops/**']\n")


def m_solo_main() -> None:
    _sustituye(CI, PUSH_CI, "  push:\n    branches: [ main ]\n")


def m_lista_blanca_exhaustiva() -> None:
    """Lista blanca con TODAS las ramas reales de origin de hoy, una por una.

    Es el caso que la version-lista-blanca del gate aprobaba: cubre el 100% de
    lo que existe. Debe seguir en ROJO, porque no cubre lo que no existe aun.
    """
    ramas = ramas_de_origin()
    if not ramas:  # pragma: no cover - RAMAS_REALES_CONOCIDAS nunca esta vacia
        raise SystemExit("MUTACION IMPOSIBLE: no hay ninguna rama real que listar")
    lineas = "".join(f"      - '{r}'\n" for r in ramas)
    _sustituye(CI, PUSH_CI, f"  push:\n    branches:\n{lineas}")
    print(f"    (lista blanca con {len(ramas)} ramas reales de origin)")


def m_borra_workflow() -> None:
    SUPPLY.unlink()


# --- Ejecucion condicional: apagar la barrera sin tocar la barrera ---------
# Ancla: un job de PRUEBAS de verdad. Neutralizarlo con una sola linea es el
# PoC que un revisor independiente demostro VIVO contra la version anterior.
ANCLA_JOB = "  test-viewer:\n    name: Viewer Tests\n    runs-on: ubuntu-latest\n"
ANCLA_PASO = "      - name: Run viewer tests\n"


def m_if_false_job() -> None:
    """`if: false` a nivel de job: no se ejecuta y reporta `skipped`, no `failure`."""
    _sustituye(CI, ANCLA_JOB,
               ANCLA_JOB.replace("    runs-on:", "    if: false\n    runs-on:"))


def m_if_false_paso() -> None:
    """Lo mismo un nivel mas abajo: el paso que ejecuta las pruebas se salta."""
    _sustituye(CI, ANCLA_PASO, ANCLA_PASO + "        if: false\n")


def m_continue_on_error_job() -> None:
    """El job falla y aun asi reporta exito: la barrera no puede bloquear."""
    _sustituye(CI, ANCLA_JOB,
               ANCLA_JOB.replace("    runs-on:", "    continue-on-error: true\n    runs-on:"))


def m_continue_on_error_paso() -> None:
    _sustituye(CI, ANCLA_PASO, ANCLA_PASO + "        continue-on-error: true\n")


def m_if_disfrazado() -> None:
    """Control: una condicion que NO es `always()`, escrita como expresion.

    Comprueba que la lista permitida no se pueda ensanchar de tapadillo con
    algo que «parece» inofensivo.
    """
    _sustituye(CI, ANCLA_JOB,
               ANCLA_JOB.replace("    runs-on:",
                                 "    if: ${{ github.event_name == 'schedule' }}\n    runs-on:"))


def m_always_permitido() -> None:
    """Control POSITIVO: `always()` es la unica condicion admitida -> VERDE.

    Sin este caso, un gate que rechazara CUALQUIER `if:` pareceria correcto
    aunque estuviera midiendo otra cosa. Aqui se comprueba que la excepcion
    declarada existe de verdad y que el gate distingue.
    """
    _sustituye(CI, ANCLA_PASO, ANCLA_PASO + "        if: ${{ always() }}\n")


def m_job_cero_tests() -> None:
    """Quita la guardia anti-cero de un job: vuelve a poder salir verde con 0."""
    texto = CI.read_text(encoding="utf-8")
    ancla = "      - name: Run viewer tests"
    i = texto.index(ancla)
    j = texto.index("\n  test-neo4j-authz:", i)
    nuevo = (
        "      - name: Run viewer tests\n"
        "        env:\n"
        "          S9K_ALLOW_REAL_INGEST: \"\"\n"
        "        run: |\n"
        "          python -m pytest viewer/tests/ -v --tb=short --no-header\n"
    )
    CI.write_text(texto[:i] + nuevo + texto[j:], encoding="utf-8")


def m_skip_critico() -> None:
    """Un test nuevo que se auto-omite por falta de Chromium, sin job que lo cubra."""
    destino = REPO / "tests" / "e2e" / "conftest.py"
    destino.write_text(
        destino.read_text(encoding="utf-8")
        + '\n\nimport pytest as _p\n'
        + '_p.importorskip("playwright.sync_api")\n',
        encoding="utf-8",
    )


def m_neutraliza_con_true() -> None:
    """`comando || true`: el mismo apagado que `continue-on-error`, en el shell.

    Un revisor lo demostro VIVO sobre el gate de reproducibilidad de entorno,
    aplicandolo a la vez en `ci.yml` y en su fragmento para que ni la
    comprobacion de fidelidad de fragmentos viera diferencia. Ningun control se
    entero: el gate corria, fallaba, y el paso salia verde.
    """
    _sustituye(
        CI,
        "          python3 .github/scripts/check_env_reproducibility.py all --strict-missing",
        "          python3 .github/scripts/check_env_reproducibility.py all --strict-missing || true",
    )


def m_neutraliza_con_dospuntos() -> None:
    """La misma familia escrita con el builtin nulo: `|| :`."""
    # Dentro de un `run: |` (escalar de bloque) a proposito: en un `run:`
    # EN LINEA, un `|| :` final deja el YAML invalido y el gate se pondria
    # rojo por no parsear, no por la regla que aqui se calibra. Un caso que
    # sale rojo por el motivo equivocado no calibra nada.
    _sustituye(
        CI,
        "          python3 .github/scripts/check_env_reproducibility_calibration.py",
        "          python3 .github/scripts/check_env_reproducibility_calibration.py || :",
    )


def m_borra_gate_exigido() -> None:
    """Se deja de invocar el gate de inventario de suites.

    El job sigue existiendo, el fichero sigue en el arbol, y el gate no se
    ejecuta nunca. `JOBS_EXIGIDOS` no ve esto: protege jobs, no pasos.
    """
    _sustituye(
        CI,
        "          python3 .github/scripts/check_suite_inventory.py --escribir-inventario >/dev/null\n",
        "          echo 'el gate ya no se invoca'\n",
    )
    _sustituye(
        CI,
        "          python3 .github/scripts/check_suite_inventory.py\n",
        "          echo 'el gate ya no se invoca'\n",
    )


def _desinvoca(fragmento: str) -> None:
    """Sustituye la INVOCACION de un script por un `echo` de una linea.

    El fichero sigue en el arbol y el job sigue existiendo: lo unico que
    desaparece es que se EJECUTE. Es el ataque que `GATES_EXIGIDOS` cierra, y
    hasta esta ronda solo estaba calibrado para dos de los seis scripts.
    """
    texto = CI.read_text(encoding="utf-8")
    lineas = [l for l in texto.splitlines(keepends=True) if fragmento in l]
    if not lineas:
        raise SystemExit(f"MUTACION IMPOSIBLE: `{fragmento}` no se invoca en ci.yml")
    for linea in lineas:
        sangria = linea[:len(linea) - len(linea.lstrip())]
        texto = texto.replace(linea, f"{sangria}echo 'des-invocado por la calibracion'\n", 1)
    CI.write_text(texto, encoding="utf-8")


def m_desinvoca_ejecucion_real() -> None:
    """LA GARANTIA PRINCIPAL frente a `xfail` deja de ejecutarse.

    Es el caso mas grave de la familia: con la capa de resultados des-invocada,
    `check_suite_inventory.py` sigue saliendo EXIT=0 con su mensaje de siempre,
    asi que nada en CI delata que el registro ya no se compara con nada.
    """
    _desinvoca("check_ejecucion_real.py")


def m_desinvoca_calibra_ejecucion() -> None:
    _desinvoca("calibra_ejecucion_real.py")


def m_desinvoca_calibra_registro() -> None:
    _desinvoca("calibra_registro_xfail.py")


def m_desinvoca_calibra_base() -> None:
    """El arnes de la base, que es el mas reciente.

    Se calibra por la misma razon por la que existe: lo que se acaba de anadir
    es justo lo que nadie vigila todavia.
    """
    _desinvoca("calibra_base_materializada.py")


def m_borra_definicion_de_nivel_superior() -> None:
    """Se borra una constante de modulo que una funcion USA.

    Es EXACTAMENTE el defecto que cometi: un empalme por ancla dejo
    `RE_ASIGNA_NOMBRE_CONSTRUIDO` fuera del fichero. Python compilaba, `ast.parse`
    no protestaba, y el fallo solo salia al ejecutar la rama que la usa. Sin
    este caso, el control de nombres seria una afirmacion sin prueba.
    """
    texto = GATE_INVENTARIO.read_text(encoding="utf-8")
    ancla = "RE_ASIGNA_NOMBRE_CONSTRUIDO = re.compile("
    if ancla not in texto:
        raise SystemExit("MUTACION IMPOSIBLE: no esta la definicion que se borra")
    lineas = texto.splitlines(keepends=True)
    salida, saltando = [], False
    for linea in lineas:
        if linea.startswith(ancla):
            saltando = True
            continue
        if saltando:
            # La definicion ocupa dos lineas: la llamada y su continuacion.
            saltando = False
            continue
        salida.append(linea)
    GATE_INVENTARIO.write_text("".join(salida), encoding="utf-8")


def m_borra_job_exigido() -> None:
    """Un gate desaparece en una resolucion de conflicto y nada se pone rojo."""
    _sustituye(CI, "  check-env-reproducibility:\n", "  check-env-reproducibility-desactivado:\n")


def m_if_negado_sin_fallo() -> None:
    """`if ! GATE; then echo ...; fi`: el apagado escrito como condicional.

    Es la variante MAS alcanzable por accidente de toda la familia, porque no
    parece un truco sino codigo de shell normal.
    """
    _sustituye(
        CI, '          python3 .github/scripts/check_env_reproducibility.py all --strict-missing',
        "          if ! python3 .github/scripts/check_env_reproducibility.py all --strict-missing; then\n"
        "            echo 'gate ignorado'\n"
        "          fi",
    )


def m_if_negado_con_exit() -> None:
    """Control POSITIVO: el MISMO idioma, pero terminando en `exit 1`.

    Es una GUARDIA, no un apagado, y tiene que salir VERDE. Sin este caso, un
    gate que rechazara todo `if !` pareceria correcto —y estaria prohibiendo
    justo el idioma de las guardias anti-cero que este fichero EXIGE—.
    """
    _sustituye(
        CI, '          python3 .github/scripts/check_env_reproducibility.py all --strict-missing',
        "          if ! python3 .github/scripts/check_env_reproducibility.py all --strict-missing; then\n"
        "            echo '::error::el entorno no reproduce lo declarado'\n"
        "            exit 1\n"
        "          fi",
    )


def m_gate_por_variable() -> None:
    """A4: la ruta del gate llega por una VARIABLE.

    La indireccion no cambia lo que se ejecuta, pero evade cualquier busqueda
    del literal `.github/scripts/...` en la linea negada.
    """
    _sustituye(
        CI, '          python3 .github/scripts/check_env_reproducibility.py all --strict-missing',
        '          G=".github/scripts/check_env_reproducibility.py"\n'
        '          if ! python3 "$G" all --strict-missing; then\n'
        "            echo 'gate ignorado'\n"
        "          fi",
    )


def m_negacion_en_else() -> None:
    """A6: la negacion se desplaza al `else`. Mismo desenlace, sin `!`."""
    _sustituye(
        CI, '          python3 .github/scripts/check_env_reproducibility.py all --strict-missing',
        "          if python3 .github/scripts/check_env_reproducibility.py all --strict-missing; then\n"
        "            :\n"
        "          else\n"
        "            echo 'gate ignorado'\n"
        "          fi",
    )


def m_sin_rama_de_fallo() -> None:
    """A6 bis: `if GATE; then ...; fi` sin `else`: la rama de fallo esta VACIA."""
    _sustituye(
        CI, '          python3 .github/scripts/check_env_reproducibility.py all --strict-missing',
        "          if python3 .github/scripts/check_env_reproducibility.py all --strict-missing; then\n"
        "            echo 'todo bien'\n"
        "          fi",
    )


def m_guardia_en_una_linea() -> None:
    """Control POSITIVO: la guardia con `exit 1` escrita en UNA sola linea.

    Antes salia ROJA (falso positivo, fallaba cerrado) porque el bloque se leia
    saltandose la propia linea del `if`.
    """
    _sustituye(
        CI, '          python3 .github/scripts/check_env_reproducibility.py all --strict-missing',
        "          if ! python3 .github/scripts/check_env_reproducibility.py all --strict-missing; then exit 1; fi",
    )


def m_doble_negacion() -> None:
    """N4: `if ! ! GATE; then exit 1; fi`.

    Bash valido. `! !` vuelve a invertir la polaridad, asi que con el gate
    ROJO la rama `then` NO se ejecuta y el paso sale VERDE: tiene el aspecto
    exacto de una guardia correcta —lleva su `exit 1`— y hace lo contrario.
    Un solo caracter separa una de otra.
    """
    _sustituye(
        CI, '          python3 .github/scripts/check_env_reproducibility.py all --strict-missing',
        "          if ! ! python3 .github/scripts/check_env_reproducibility.py all --strict-missing; then\n"
        "            exit 1\n"
        "          fi",
    )


CASOS = [
    # `estado correcto` es tambien el control positivo de la regla de
    # `|| true`: el `ci.yml` real contiene comentarios que dicen «Sin
    # `|| true`: ...». Si el gate mirase el texto en vez del codigo, este
    # caso saldria ROJO y la calibracion lo cazaria aqui mismo.
    ("estado correcto", None, VERDE),
    # UN CASO POR SCRIPT EXIGIDO. Sin esto, `GATES_EXIGIDOS` protegia dos de
    # seis y los otros cuatro se podian sustituir por un `echo` sin que nada
    # enrojeciera.
    ("des-invocar `check_ejecucion_real.py` (garantia PRINCIPAL)",
     m_desinvoca_ejecucion_real, ROJO),
    ("des-invocar `calibra_ejecucion_real.py`", m_desinvoca_calibra_ejecucion, ROJO),
    ("des-invocar `calibra_registro_xfail.py`", m_desinvoca_calibra_registro, ROJO),
    ("des-invocar `calibra_base_materializada.py`", m_desinvoca_calibra_base, ROJO),
    ("borrar una definicion de nivel superior que una funcion usa",
     m_borra_definicion_de_nivel_superior, ROJO),
    ("`paths-ignore` bajo `push`", m_paths_ignore_push, ROJO),
    ("`paths-ignore` bajo `pull_request`", m_paths_ignore_pr, ROJO),
    ('`"paths-ignore"` entrecomillado', m_paths_ignore_entrecomillado, ROJO),
    ("`paths-ignore :` con espacio antes de los dos puntos", m_paths_ignore_espacio, ROJO),
    ("`paths:` bajo `push`", m_paths_push, ROJO),
    ("`paths:` bajo `pull_request`", m_paths_pr, ROJO),
    ("`branches-ignore`", m_branches_ignore, ROJO),
    ("politica reducida a `branches: [main]`", m_solo_main, ROJO),
    ("lista blanca EXHAUSTIVA con todas las ramas reales de origin", m_lista_blanca_exhaustiva, ROJO),
    ("workflow vigilado borrado (`supply-chain.yml`)", m_borra_workflow, ROJO),
    ("`if: false` en un JOB de pruebas", m_if_false_job, ROJO),
    ("`if: false` en un PASO de pruebas", m_if_false_paso, ROJO),
    ("`continue-on-error: true` a nivel de JOB", m_continue_on_error_job, ROJO),
    ("`continue-on-error: true` a nivel de PASO", m_continue_on_error_paso, ROJO),
    ("`if:` con expresion que no es `always()`", m_if_disfrazado, ROJO),
    ("control positivo: `if: ${{ always() }}` (unica permitida)", m_always_permitido, VERDE),
    ("job que puede ejecutar 0 tests", m_job_cero_tests, ROJO),
    ("test que se auto-omite por falta de Chromium", m_skip_critico, ROJO),
    ("`|| true` tras un gate dentro del `run:`", m_neutraliza_con_true, ROJO),
    ("`|| :` (builtin nulo) tras un gate dentro del `run:`", m_neutraliza_con_dospuntos, ROJO),
    ("job exigido que desaparece de ci.yml", m_borra_job_exigido, ROJO),
    ("gate exigido que deja de INVOCARSE (el job sigue)", m_borra_gate_exigido, ROJO),
    ("`if ! GATE` sin fallo en el bloque (apagado condicional)", m_if_negado_sin_fallo, ROJO),
    ("control positivo: `if ! GATE` que termina en `exit 1` (guardia)", m_if_negado_con_exit, VERDE),
    ("A4: gate invocado por VARIABLE (indireccion)", m_gate_por_variable, ROJO),
    ("A6: negacion desplazada al `else`", m_negacion_en_else, ROJO),
    ("A6 bis: `if GATE; then ...; fi` sin rama de fallo", m_sin_rama_de_fallo, ROJO),
    ("control positivo: guardia con `exit 1` en UNA linea", m_guardia_en_una_linea, VERDE),
    ("N4: doble negacion `if ! ! GATE` (polaridad invertida)", m_doble_negacion, ROJO),
    ("restaurado", None, VERDE),
]


def main() -> int:
    # El cerrojo se toma ANTES de tocar nada y se suelta al salir del proceso.
    cerrojo = toma_cerrojo()
    print(f"(cerrojo tomado: {CERROJO}; este script muta `ci.yml` en el sitio, "
          f"no lo ejecutes en paralelo con nada que lea el repositorio)")
    respaldo = Path(tempfile.mkdtemp(prefix="calibra-gate-"))
    for f in TOCABLES:
        shutil.copy2(f, respaldo / f.name)

    filas = []
    fallos = 0
    try:
        for titulo, mutacion, esperado in CASOS:
            # Estado limpio antes de cada caso.
            for f in TOCABLES:
                shutil.copy2(respaldo / f.name, f)
            print(f"\n########## {titulo}  (esperado: {esperado})")
            if mutacion is not None:
                mutacion()
            rc, salida = ejecuta_gate()
            obtenido = VERDE if rc == 0 else ROJO
            print(salida.rstrip())
            print(f"RC={rc}  ->  {obtenido}")
            ok = obtenido == esperado
            fallos += 0 if ok else 1
            motivo = ""
            for linea in salida.splitlines():
                if linea.startswith("::error::"):
                    motivo = linea[len("::error::"):].strip().replace("|", "/")
                    motivo = motivo.split("\n")[0][:120]
                    break
            if not motivo and rc == 0:
                motivo = "sin errores"
            filas.append((titulo, esperado, rc, obtenido, "OK" if ok else "**DESVIACION**", motivo))
    finally:
        # Restaurar SIEMPRE, tambien ante Ctrl-C o una excepcion: dejar el
        # `ci.yml` mutado en el arbol seria peor que no haber calibrado.
        for f in TOCABLES:
            shutil.copy2(respaldo / f.name, f)
        shutil.rmtree(respaldo, ignore_errors=True)
        fcntl.flock(cerrojo, fcntl.LOCK_UN)
        cerrojo.close()

    print("\n\n===== TABLA DE CALIBRACION =====\n")
    print("| Caso | Esperado | RC | Obtenido | Veredicto | Primer error |")
    print("|---|---|---|---|---|---|")
    for fila in filas:
        print("| {} | {} | {} | {} | {} | {} |".format(*fila))

    if fallos:
        print(f"\nCALIBRACION FALLIDA: {fallos} caso(s) no dieron el veredicto esperado")
        return 1
    print(f"\nCALIBRACION SUPERADA: {len(filas)}/{len(filas)} casos con el veredicto esperado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
