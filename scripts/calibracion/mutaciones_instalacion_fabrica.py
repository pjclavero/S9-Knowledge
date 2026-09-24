#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CALIBRACIÓN del corte «instalación cerrada de fábrica».

Mismo motor que `mutaciones_bootstrap_primer_admin.py`: un verde sólo vale si
la prueba que lo da es CAPAZ DE PONERSE ROJA, y roja POR SU CAUSA. Cada
mutación reintroduce UN defecto real de este corte —el default de auth, la
resolución de la ruta de la auth DB, el bootstrap del secreto CSRF, el
opt-out explícito o el fail-closed ante fallos de disco— sobre el código
real, uno cada vez, y comprueba:

    1. que los casos que DEBÍAN caer cayeron, y
    2. que el MENSAJE del rojo dice la causa.

LAS MUTACIONES SE REFERENCIAN POR NOMBRE. EL RECUENTO SALE DEL FICHERO
(`len(MUTACIONES)`). EL CRUCE compara los casos que la suite RECOLECTA contra
los rojos REALES.

TECHO DE ESTE CALIBRADOR:
  * Muta por SUSTITUCIÓN DE TEXTO EXACTO. No ve alias ni una segunda copia de
    la misma lógica en otro módulo.
  * MIRA DOS SUITES (`SUITES`): la del corte y el testigo E2E barato de
    `tests/browser/` (sin Chromium, sólo exige el paquete `playwright`
    instalado para que ese directorio colecte).
  * No mide despliegue real, ni systemd, ni el reverse proxy, ni el recorrido
    de navegador de verdad (eso lo mide `test_browser_auth_flows.py`, fuera
    de este calibrador).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
VIEWER = RAIZ / "viewer"
CONFIG = VIEWER / "app" / "auth" / "config.py"
CSRF_BOOTSTRAP = VIEWER / "app" / "auth" / "csrf_bootstrap.py"
SCHEMA_COMPAT = VIEWER / "app" / "auth" / "schema_compat.py"
MAIN = VIEWER / "app" / "main.py"
ENV_EXAMPLE = VIEWER / ".env.example"
BROWSER_CONFTEST = VIEWER / "tests" / "browser" / "conftest.py"

#: DOS suites, no una: la del corte propiamente dicho, y el testigo BARATO
#: (sin Playwright/Chromium: sólo `urllib` contra el servidor real de
#: módulo) de que el ancla `S9K_AUTH_ENABLED=false` de `tests/conftest.py`
#: sigue sobrescrita en `tests/browser/` (ver `conftest.py` de ese
#: directorio y `test_e2e_servidor_no_queda_sin_auth.py`). Collectarlo NO
#: exige Chromium utilizable, sólo que el paquete `playwright` esté
#: instalado (la condición de colección del propio directorio).
SUITE = "tests/test_instalacion_cerrada_fabrica.py"
SUITE_E2E_SIN_NAVEGADOR = "tests/browser/test_e2e_servidor_no_queda_sin_auth.py"
SUITES = (SUITE, SUITE_E2E_SIN_NAVEGADOR)


@dataclass(frozen=True)
class Mutacion:
    nombre: str
    fichero: Path
    viejo: str
    nuevo: str
    caen: tuple[str, ...]
    dice: str
    porque: str = ""
    extra: tuple[tuple[Path, str, str], ...] = field(default_factory=tuple)


MUTACIONES: tuple[Mutacion, ...] = (
    Mutacion(
        nombre="el-default-de-auth-vuelve-a-ser-false",
        fichero=CONFIG,
        viejo="    S9K_AUTH_ENABLED: bool = True",
        nuevo="    S9K_AUTH_ENABLED: bool = False",
        caen=(
            "test_default_de_fabrica_auth_activada",
            "test_opt_out_no_se_confunde_con_el_default",
            "test_rutas_de_producto_no_son_anonimas_de_fabrica",
        ),
        dice="AssertionError",
        porque=(
            "Es el corazón del corte: si el default vuelve a `False`, una "
            "instalación de fábrica queda anónima otra vez."
        ),
    ),
    Mutacion(
        nombre="la-ruta-de-la-auth-db-vuelve-a-ser-relativa",
        fichero=CONFIG,
        viejo='    S9K_AUTH_DB_PATH: str = DEFAULT_AUTH_DB_PATH',
        nuevo='    S9K_AUTH_DB_PATH: str = "viewer/state/auth.db"',
        caen=("test_auth_db_path_vacio_resuelve_a_ruta_absoluta_del_repo",),
        dice="AssertionError",
        porque=(
            "Con auth activa por defecto, una ruta relativa por defecto "
            "volvería a abortar el arranque de fábrica (AUTH_DB_PATH_NOT_ABSOLUTE) "
            "en cuanto alguien no fije `S9K_AUTH_DB_PATH`: exactamente el "
            "terminal que este corte existe para evitar."
        ),
    ),
    Mutacion(
        nombre="el-validador-de-ruta-vacia-deja-de-resolverse",
        fichero=CONFIG,
        viejo=(
            "    @model_validator(mode=\"after\")\n"
            "    def _resolver_ruta_por_defecto(self) -> \"AuthSettings\":\n"
            "        if not (self.S9K_AUTH_DB_PATH or \"\").strip():\n"
            "            object.__setattr__(self, \"S9K_AUTH_DB_PATH\", DEFAULT_AUTH_DB_PATH)\n"
            "        return self"
        ),
        nuevo=(
            "    @model_validator(mode=\"after\")\n"
            "    def _resolver_ruta_por_defecto(self) -> \"AuthSettings\":\n"
            "        return self"
        ),
        caen=("test_auth_db_path_explicitamente_vacio_tambien_resuelve",),
        dice="AssertionError",
        porque=(
            "La plantilla trae `S9K_AUTH_DB_PATH=` vacío a propósito: sin "
            "este validador, la ruta vacía llegaría tal cual y el arranque "
            "abortaría por AUTH_DB_PATH_EMPTY en vez de resolver un default "
            "absoluto."
        ),
    ),
    Mutacion(
        nombre="el-csrf-vacio-deja-de-bootstrapearse",
        fichero=CONFIG,
        viejo=(
            "        resuelto = resolve_csrf_secret(cfg.S9K_CSRF_SECRET, cfg.S9K_AUTH_DB_PATH)\n"
            "        if resuelto != cfg.S9K_CSRF_SECRET:\n"
            "            cfg = cfg.model_copy(update={\"S9K_CSRF_SECRET\": resuelto})"
        ),
        nuevo="        pass",
        caen=(
            "test_csrf_secret_se_autogenera_sin_terminal",
            "test_csrf_secret_persiste_entre_arranques",
            "test_setup_admin_accesible_mientras_bootstrap_pendiente",
        ),
        dice="CSRF_SECRET_EMPTY",
        porque=(
            "Sin llamar al bootstrap, `S9K_CSRF_SECRET` vacío de la "
            "plantilla llega intacto a `enforce_auth_security`, que aborta "
            "el arranque: vuelve a hacer falta el terminal."
        ),
    ),
    Mutacion(
        nombre="el-secreto-explicito-deja-de-ganar",
        fichero=CSRF_BOOTSTRAP,
        viejo=(
            "    value = (configured_secret or \"\").strip()\n"
            "    if value:\n"
            "        return configured_secret"
        ),
        nuevo=(
            "    value = (configured_secret or \"\").strip()\n"
            "    if False and value:\n"
            "        return configured_secret"
        ),
        caen=("test_csrf_secret_explicito_gana_y_no_se_persiste",),
        dice="AssertionError",
        porque=(
            "Un secreto fijado a mano deja de ganar: se sobreescribiría (o "
            "se le antepondría un fichero) sin que quien lo fijó lo sepa."
        ),
    ),
    Mutacion(
        nombre="el-permiso-del-fichero-de-secreto-deja-de-ser-0600",
        fichero=CSRF_BOOTSTRAP,
        viejo="            os.chmod(tmp_path, 0o600)",
        nuevo="            os.chmod(tmp_path, 0o644)",
        caen=("test_csrf_secret_se_autogenera_sin_terminal",),
        dice="permisos del secreto CSRF deben ser 0600",
        porque=(
            "El secreto CSRF en disco con permisos legibles por cualquier "
            "cuenta del sistema deja de ser un secreto. `mkstemp` ya crea "
            "el temporal en 0600, pero el `chmod` explícito es lo que "
            "documenta y fija la garantía con independencia del umask del "
            "proceso: quitarlo debe enrojecer."
        ),
    ),
    Mutacion(
        nombre="un-fichero-de-secreto-vacio-se-acepta-tal-cual",
        fichero=CSRF_BOOTSTRAP,
        viejo=(
            "    texto = secret_path.read_text(encoding=\"utf-8\").strip()\n"
            "    return texto or None"
        ),
        nuevo=(
            "    texto = secret_path.read_text(encoding=\"utf-8\")\n"
            "    return texto"
        ),
        caen=("test_secreto_csrf_vacio_en_disco_se_regenera",),
        dice="AssertionError",
        porque=(
            "Sin el `.strip()`, un residuo de sólo espacios/salto de línea "
            "(escritura interrumpida a medias) se aceptaría como secreto "
            "válido tal cual: una cadena de baja entropía, trivialmente "
            "adivinable, en vez de regenerarse."
        ),
    ),
    Mutacion(
        nombre="un-fallo-de-escritura-del-secreto-no-aborta",
        fichero=CSRF_BOOTSTRAP,
        viejo=(
            "    except OSError as exc:\n"
            "        log.error(\n"
            "            \"no se pudo generar/leer el secreto CSRF persistido en %s: %s\",\n"
            "            secret_path, type(exc).__name__,\n"
            "        )\n"
            "        raise CsrfSecretBootstrapError(\n"
            "            \"no se pudo generar/leer el secreto CSRF persistido en disco\"\n"
            "        ) from exc"
        ),
        nuevo=(
            "    except OSError as exc:\n"
            "        return secrets.token_urlsafe(_GENERATED_SECRET_BYTES)"
        ),
        caen=("test_fallo_de_escritura_del_secreto_csrf_es_fail_closed",),
        dice="CsrfSecretBootstrapError",
        porque=(
            "Un secreto 'de emergencia' que sólo vive en memoria del "
            "proceso cambiaría en cada reinicio e invalidaría todas las "
            "sesiones en silencio: debe ser fail-closed, no un fallback "
            "silencioso."
        ),
    ),
    Mutacion(
        nombre="la-reclamacion-del-secreto-vuelve-a-ser-leer-generar-pisar",
        fichero=CSRF_BOOTSTRAP,
        viejo=(
            "            for _intento in range(_MAX_INTENTOS_RECLAMACION):\n"
            "                try:\n"
            "                    os.link(str(tmp_path), str(secret_path))\n"
            "                    break\n"
            "                except FileExistsError:\n"
            "                    ganador = _leer_secreto_existente(secret_path)\n"
            "                    if ganador:\n"
            "                        return ganador\n"
            "                    # Vacío/corrupto TODAVÍA en este instante: residuo de un\n"
            "                    # disco lleno a mitad de una escritura anterior, no un\n"
            "                    # ganador. Se retira y se reintenta la reclamación.\n"
            "                    try:\n"
            "                        secret_path.unlink()\n"
            "                    except FileNotFoundError:\n"
            "                        pass\n"
            "            else:\n"
            "                raise CsrfSecretBootstrapError(\n"
            "                    \"no se pudo reclamar el secreto CSRF tras \"\n"
            "                    f\"{_MAX_INTENTOS_RECLAMACION} intentos: residuo vacío \"\n"
            "                    \"persistente en disco\"\n"
            "                )"
        ),
        nuevo="            os.replace(str(tmp_path), str(secret_path))",
        caen=("test_ocho_hilos_a_la_vez_no_producen_secretos_divergentes",),
        dice="LA CARRERA DEL BOOTSTRAP DEL SECRETO CSRF PRODUJO SECRETOS DIVERGENTES",
        porque=(
            "`os.replace` pisa el destino incondicionalmente: con varios "
            "procesos arrancando a la vez sobre una instalación nueva, cada "
            "uno genera su propio secreto y sólo el último en escribir "
            "coincide con el fichero. Los demás firman con un secreto que "
            "ya no vale: CSRF y sesiones fallan de forma intermitente."
        ),
    ),
    Mutacion(
        nombre="env-example-vuelve-a-traer-auth-desactivada",
        fichero=ENV_EXAMPLE,
        viejo="S9K_AUTH_ENABLED=true",
        nuevo="S9K_AUTH_ENABLED=false",
        caen=("test_env_example_del_viewer_trae_auth_enabled_true",),
        dice="AssertionError",
        porque=(
            "El código puede defaultear a True, pero si la PLANTILLA que la "
            "persona copia de verdad dice `false`, la instalación de "
            "fábrica real queda sin auth: es el fichero, no el código, lo "
            "que se copia."
        ),
    ),
    Mutacion(
        nombre="el-opt-out-deja-de-dejar-pasar-al-anonimo",
        fichero=MAIN,
        viejo=(
            "    \"\"\"Para rutas que requieren reviewer o superior.\"\"\"\n"
            "    from fastapi.responses import RedirectResponse as _RR\n"
            "    cfg = get_auth_settings()\n"
            "    if not cfg.S9K_AUTH_ENABLED:\n"
            "        return None"
        ),
        nuevo=(
            "    \"\"\"Para rutas que requieren reviewer o superior.\"\"\"\n"
            "    from fastapi.responses import RedirectResponse as _RR\n"
            "    cfg = get_auth_settings()\n"
            "    if False:\n"
            "        return None"
        ),
        caen=("test_opt_out_explicito_conserva_el_modo_sin_auth",),
        dice="con el opt-out explícito, el comportamiento de laboratorio",
        porque=(
            "Cerrar la instalación de fábrica no puede, de paso, romper el "
            "camino de desarrollo/laboratorio: `S9K_AUTH_ENABLED=false` "
            "explícito debe seguir dejando pasar al anónimo en /reviews."
        ),
    ),
    Mutacion(
        nombre="una-base-corrupta-se-lee-como-instalacion-nueva",
        fichero=SCHEMA_COMPAT,
        viejo=(
            "        except sqlite3.DatabaseError as exc:\n"
            "            raise SchemaVersionUnknown(\n"
            "                f\"{COMPONENT}: '{path}' existe pero no es una base SQLite \"\n"
            "                f\"legible ({exc}). Se rehúsa arrancar.\", SCHEMA_NOT_SQLITE\n"
            "            ) from exc"
        ),
        nuevo=(
            "        except sqlite3.DatabaseError as exc:\n"
            "            return None"
        ),
        caen=("test_base_corrupta_no_es_primera_instalacion",),
        dice="SchemaVersionUnknown",
        porque=(
            "Una base corrupta que se lee como `None` (instalación nueva) "
            "reabriría /setup/admin sobre datos existentes: fail-closed "
            "significa que lo desconocido nunca colapsa a 'primera vez'."
        ),
    ),
    Mutacion(
        nombre="el-ancla-de-la-suite-de-unidad-vuelve-a-pisar-el-e2e",
        fichero=BROWSER_CONFTEST,
        viejo=(
            "@pytest.fixture(autouse=True)\n"
            "def _s9k_auth_enabled_linea_base_false():\n"
            "    \"\"\"SOBRESCRIBE, sólo en este árbol, el ancla `S9K_AUTH_ENABLED=false`\n"
            "    autouse de `tests/conftest.py` (mismo nombre de fixture: pytest resuelve\n"
            "    la de este `conftest.py`, más cercano al test, en lugar de la del padre).\n"
            "\n"
            "    El resto de la suite (unidad) SÍ necesita ese ancla — está pensada para\n"
            "    medir el default previo y, sin ella, el primer test que \"restaurase\"\n"
            "    retirando la variable dejaría el resto de la sesión con auth activada\n"
            "    por defecto sin que nada lo dijera.\n"
            "\n"
            "    Pero `viewer` (fixture de módulo, en este mismo fichero) arranca el\n"
            "    servidor real en un HILO del MISMO proceso, no en un subproceso aislado:\n"
            "    comparte `os.environ` y el `lru_cache` de `get_auth_settings` con el\n"
            "    proceso de test. El ancla es FUNCTION-scoped y se ejecuta ANTES de cada\n"
            "    test individual, así que pisaba el `S9K_AUTH_ENABLED=true` que\n"
            "    `start_viewer()` (en `e2e_support.py`) ya había fijado al arrancar el\n"
            "    servidor de MÓDULO: el servidor E2E quedaba corriendo sin auth y todos\n"
            "    los clics contra el login no llegaban a ningún sitio protegido.\n"
            "    Medido: con el ancla puesta, `test_browser_auth_flows.py` caía 16/22;\n"
            "    retirada aquí, vuelve a 22/22.\n"
            "\n"
            "    Esto no es un no-op decorativo: es la ausencia deliberada del ancla en\n"
            "    el árbol donde el laboratorio (esta fixture) y el producto (el servidor\n"
            "    real) tienen que coincidir en la misma variable.\n"
            "    \"\"\"\n"
            "    yield"
        ),
        nuevo=(
            "@pytest.fixture(autouse=True)\n"
            "def _s9k_auth_enabled_linea_base_false():\n"
            "    import os\n"
            "    from app.auth.config import get_auth_settings\n"
            "    os.environ[\"S9K_AUTH_ENABLED\"] = \"false\"\n"
            "    get_auth_settings.cache_clear()\n"
            "    yield"
        ),
        caen=("test_el_servidor_e2e_de_modulo_exige_autenticacion",),
        dice="EL SERVIDOR E2E DE MODULO RESPONDE 200 ANONIMO",
        porque=(
            "Si el ancla de la suite de unidad vuelve a colarse en "
            "`tests/browser/`, el servidor E2E de módulo (un hilo del "
            "mismo proceso, comparte `os.environ` y el `lru_cache` de "
            "`get_auth_settings`) queda corriendo sin auth. Sin este "
            "testigo barato, eso se ve como 16 timeouts de clic en "
            "`test_browser_auth_flows.py` — o como 16 `errors` mudos en "
            "una máquina sin Chromium — nunca como un mensaje que nombre "
            "la causa."
        ),
    ),
)


def _pytest(selector: str | None = None) -> subprocess.CompletedProcess:
    orden = [sys.executable, "-m", "pytest", *SUITES, "-q", "-p", "no:randomly",
             "--color=no"]
    if selector:
        orden += ["-k", selector]
    return subprocess.run(orden, cwd=VIEWER, capture_output=True, text=True)


def _casos_del_fichero() -> set[str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", *SUITES, "--collect-only", "-q",
         "--color=no", "-p", "no:randomly"],
        cwd=VIEWER, capture_output=True, text=True,
    )
    casos = {
        linea.split("::")[-1].split("[")[0].strip()
        for linea in r.stdout.splitlines() if "::" in linea
    }
    if not casos:
        raise AssertionError(
            "EL CRUCE NO RECOLECTÓ NINGÚN CASO.\n" + r.stdout[-2000:] + r.stderr[-2000:]
        )
    return casos


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        if ".git" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio() -> bool:
    r = subprocess.run(
        ["git", "diff", "--stat", "--"], cwd=RAIZ, capture_output=True, text=True
    )
    return r.stdout.strip() == ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solo", help="calibrar una mutación por NOMBRE")
    args = parser.parse_args()

    if not _arbol_limpio():
        print("ABORTA: el árbol tiene cambios sin commitear.")
        return 2

    seleccionadas = MUTACIONES
    if args.solo:
        seleccionadas = tuple(m for m in MUTACIONES if m.nombre == args.solo)
        if not seleccionadas:
            print(f"ABORTA: no hay mutación llamada {args.solo!r}. "
                  f"Hay: {[m.nombre for m in MUTACIONES]}")
            return 2

    _purgar_pycache()
    base = _pytest()
    if base.returncode != 0:
        print("ABORTA: la suite YA está roja sin mutar.")
        print(base.stdout[-3000:])
        return 2
    print(f"BASE VERDE. {', '.join(SUITES)}\n")

    total = len(seleccionadas)
    fallos: list[str] = []
    rojos_vistos: set[str] = set()
    print(f"{total} mutaciones declaradas en este fichero.\n")

    for mut in seleccionadas:
        print("=" * 74)
        print(f"MUTACIÓN  {mut.nombre}")
        print(f"  fichero {mut.fichero.relative_to(RAIZ)}")
        print(f"  porqué  {mut.porque}")
        parches = ((mut.fichero, mut.viejo, mut.nuevo),) + mut.extra
        try:
            for fichero, viejo, nuevo in parches:
                texto = fichero.read_text(encoding="utf-8")
                if texto.count(viejo) != 1:
                    raise AssertionError(
                        f"el texto a mutar aparece {texto.count(viejo)} veces "
                        f"en {fichero.name} (se esperaba 1)."
                    )
                fichero.write_text(texto.replace(viejo, nuevo), encoding="utf-8")
            if _arbol_limpio():
                raise AssertionError("tras escribir la mutación, git diff no ve NINGÚN cambio.")
            _purgar_pycache()

            res = _pytest()
            salida = res.stdout + res.stderr
            if res.returncode == 0:
                fallos.append(
                    f"{mut.nombre}: LA SUITE SIGUE VERDE CON EL DEFECTO PUESTO."
                )
                print("  RESULTADO  *** VERDE CON EL DEFECTO — CONTROL CIEGO ***")
                continue

            rojos = [
                linea.split("::")[-1].split(" ")[0]
                for linea in salida.splitlines()
                if linea.startswith("FAILED") or linea.startswith("ERROR ")
            ]
            faltan = [c for c in mut.caen if not any(c in r for r in rojos)]
            if faltan:
                fallos.append(
                    f"{mut.nombre}: se esperaba que cayeran {faltan} y NO "
                    f"cayeron. Cayeron: {rojos}"
                )
                print(f"  RESULTADO  rojo, pero NO cayeron {faltan}")
            else:
                # Colapsado por NOMBRE de caso (sin la parametrización entre
                # corchetes) antes de contar: el recuento tiene que coincidir
                # con la lista que se imprime a su lado, no con las líneas
                # crudas de pytest (que repiten el mismo caso una vez por
                # cada parámetro).
                casos_rojos = sorted(set(r.split("[")[0] for r in rojos))
                print(f"  ROJOS      {len(casos_rojos)}: {casos_rojos}")
            rojos_vistos.update(r.split("[")[0] for r in rojos)

            if mut.dice not in salida:
                fallos.append(
                    f"{mut.nombre}: el rojo NO DICE SU CAUSA. Se esperaba "
                    f"{mut.dice!r} y no aparece."
                )
                print(f"  MENSAJE    *** FALTA {mut.dice!r} ***")
            else:
                print(f"  MENSAJE    OK — el rojo dice: «{mut.dice}»")
        finally:
            for fichero, _, _ in parches:
                subprocess.run(
                    ["git", "checkout", "--", str(fichero.relative_to(RAIZ))],
                    cwd=RAIZ, check=True,
                )
            _purgar_pycache()
            if not _arbol_limpio():
                print("  *** EL ÁRBOL NO QUEDÓ RESTAURADO. ABORTA. ***")
                return 3

    print("=" * 74)
    _purgar_pycache()
    final = _pytest()
    if final.returncode != 0:
        print("LA SUITE NO VOLVIÓ A VERDE tras restaurar.")
        print(final.stdout[-3000:])
        return 3

    if not args.solo:
        casos = _casos_del_fichero()
        huerfanos = sorted(casos - rojos_vistos)
        print(f"CRUCE: {len(casos)} casos recolectados, "
              f"{len(casos) - len(huerfanos)} enrojecen con alguna mutación.")
        if huerfanos:
            for h in huerfanos:
                print(f"  ::SIN CALIBRAR:: {h}")
            fallos.append(
                f"{len(huerfanos)} testigo(s) que NINGUNA mutación enrojece: {huerfanos}."
            )

    if fallos:
        print(f"CALIBRACIÓN FALLIDA — {len(fallos)} problemas sobre {total} mutaciones:")
        for f in fallos:
            print("  * " + f)
        return 1
    print(f"CALIBRACIÓN OK — {total}/{total} mutaciones producen un rojo que "
          f"DICE SU CAUSA, y la suite vuelve a verde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
