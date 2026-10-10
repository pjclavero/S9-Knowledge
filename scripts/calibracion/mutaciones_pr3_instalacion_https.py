#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR-3 (USABLE-V1) — arnés de calibración de «la instalación provisiona y
VERIFICA la vía HTTPS».

Mismo motor que `mutaciones_pr1_review_console_apagada.py`: una garantía no
cuenta hasta que hay una prueba CAPAZ DE PONERSE ROJA, y roja POR SU CAUSA.
Cada mutación reintroduce UN defecto real de este corte sobre el código
commiteado, uno cada vez, corre el testigo
(`deploy/tests/test_preflight_https.py`) y comprueba:

    1. que las pruebas que DEBÍAN caer cayeron, y
    2. que el MENSAJE del rojo dice la causa (fragmento discriminante, nunca
       un `AssertionError` pelado).

Las DOS mutaciones obligatorias del encargo están aquí y nombradas:

    M1 — la verificación PASA sin que el endpoint responda.
    M2 — se ACEPTA HTTP plano como instalación válida.

Localizador ESTRUCTURAL: todas las mutaciones usan
`localizadores.mutar_en_funcion`, que devuelve ``None`` —DETECTOR ROTO— en vez
de elegir una ocurrencia ambigua. Nada de `.replace(..., 1)`, nada de anclas
por indentación, nada de mutaciones que no llamen al producto: el testigo
abre sockets TLS reales contra el código mutado.

TECHO DE ESTE CALIBRADOR
------------------------
* Muta por SUSTITUCIÓN DE TEXTO EXACTO dentro de una función localizada por
  AST. No ve alias, ni una segunda copia de la misma lógica en otro módulo.
* Calibra la mitad PYTHON del contrato (`preflight_https.py`). La mitad
  `bash` (`validate_deploy.sh::validate_https_contract`) y el rol Ansible
  `tls` **no están calibrados por mutación aquí**: lo que CI ejerce de ellos
  es shellcheck, yamllint y `ansible-playbook --syntax-check`. Queda
  registrado como deuda, no como garantía.
* No mide despliegue real, ni nginx, ni systemd, ni navegador, ni el
  recorrido de crear el primer administrador. Eso es el ensayo RC
  (`deploy/README.md`), **PENDIENTE**.

Uso: python3 scripts/calibracion/mutaciones_pr3_instalacion_https.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localizadores import mutar_en_funcion, python_sigue_siendo_valido  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
TESTIGO = "deploy/tests/test_preflight_https.py"
FICHERO = "deploy/scripts/preflight_https.py"


def _sh(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True)


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio_tracked() -> bool:
    r = _sh(["git", "status", "--porcelain", "--untracked-files=no"])
    return r.returncode == 0 and r.stdout.strip() == ""


def _correr_testigo():
    _purgar_pycache()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", TESTIGO, "-q", "--no-header",
         "--color=no", "-p", "no:randomly"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def _fallos(salida: str) -> list:
    return sorted({
        linea.split("::")[-1].split(" ")[0]
        for linea in salida.splitlines()
        if linea.startswith("FAILED") or "FAILED " in linea
    })


# ---------------------------------------------------------------------------
# Las mutaciones
# ---------------------------------------------------------------------------

# M1 (OBLIGATORIA) — la verificación POR EFECTO deja de ser por efecto: si el
# endpoint no contesta, se devuelve "sin hallazgos". Es el defecto de clase de
# este corte: confundir "la configuración está escrita" con "el endpoint
# responde".
def _mutar_el_endpoint_no_hace_falta_que_responda(texto: str):
    return mutar_en_funcion(
        texto,
        "comprobar_endpoint_responde",
        "    except Exception as exc:\n        return Hallazgo(",
        "    except Exception as exc:\n        return None\n        return Hallazgo(",
    )


# M2 (OBLIGATORIA) — se acepta HTTP plano como instalación válida: el esquema
# deja de comprobarse. Es exactamente la forma del fallback a HTTP que D3
# prohíbe.
def _mutar_acepta_http_plano(texto: str):
    return mutar_en_funcion(
        texto,
        "comprobar_esquema_https",
        '    if esquema != "https":',
        "    if False:",
    )


# M3 — la cookie `Secure` sobre HTTP deja de ser un fallo. Es la "solución"
# que se consideró y se DESCARTÓ: degradar la garantía para que la
# instalación pase.
def _mutar_cookie_secure_sobre_http_no_es_fallo(texto: str):
    return mutar_en_funcion(
        texto,
        "comprobar_cookie_secure_coherente",
        "    if not session_secure:\n        return None",
        "    if True:\n        return None",
    )


# M4 — el hostname check se apaga: un certificado válido de OTRO nombre
# pasaría. Es el error clásico de "pero el certificado es bueno".
def _mutar_no_comprueba_el_nombre(texto: str):
    return mutar_en_funcion(
        texto,
        "_contexto",
        "    ctx.check_hostname = comprobar_nombre",
        "    ctx.check_hostname = False",
    )


# M5 — el fallo de verificación de cadena se SILENCIA (se devuelve None en vez
# del hallazgo). Equivale a un `verify=False` disfrazado: un autofirmado no
# declarado pasaría.
def _mutar_silencia_el_fallo_de_cadena(texto: str):
    return mutar_en_funcion(
        texto,
        "comprobar_cadena_de_certificado",
        "    except ssl.SSLCertVerificationError as exc:\n        return Hallazgo(",
        "    except ssl.SSLCertVerificationError as exc:\n        return None\n        return Hallazgo(",
    )


# M6 — un 502 del terminador TLS sin backend se acepta como "contestó". El
# endpoint responde HTTP, sí, pero el visor no está detrás.
def _mutar_cualquier_estado_vale(texto: str):
    return mutar_en_funcion(
        texto,
        "comprobar_endpoint_responde",
        "    if estado not in ESTADOS_QUE_SIGNIFICAN_QUE_CONTESTO:",
        "    if False:",
    )


# M7 — el código de salida deja de reflejar los hallazgos: fallo de HTTPS y
# aun así rc=0. La instalación se declararía COMPLETA sin HTTPS.
def _mutar_fallo_de_https_no_impide_completar(texto: str):
    return mutar_en_funcion(
        texto,
        "codigo_de_salida",
        "    return 0 if not hallazgos else 1",
        "    return 0",
    )


# M8 — reaparece el FALLBACK A HTTP: con una URL http:// el preflight se pone
# a sondear igual, en vez de negarse.
def _mutar_sondea_http_plano(texto: str):
    return mutar_en_funcion(
        texto,
        "verificar",
        "    if hallazgos:",
        "    if False:",
    )


MUTACIONES = [
    (
        "M1 (OBLIGATORIA) — la verificación PASA sin que el endpoint responda",
        _mutar_el_endpoint_no_hace_falta_que_responda,
        ["test_tls_levantado_pero_el_endpoint_no_contesta"],
        "ENDPOINT_NO_RESPONDE",
    ),
    (
        "M2 (OBLIGATORIA) — se ACEPTA HTTP plano como instalación válida",
        _mutar_acepta_http_plano,
        ["test_http_plano_con_cookie_secure_es_instalacion_no_valida",
         "test_http_plano_sin_cookie_secure_sigue_siendo_no_https"],
        "ESQUEMA_NO_HTTPS",
    ),
    (
        "M3 — la cookie Secure sobre HTTP deja de ser un fallo (la "
        "degradación que D3 descartó)",
        _mutar_cookie_secure_sobre_http_no_es_fallo,
        ["test_http_plano_con_cookie_secure_es_instalacion_no_valida",
         "test_cli_sobre_env_file_de_http_plano_falla_y_nombra_la_causa"],
        "COOKIE_SECURE_SOBRE_HTTP",
    ),
    (
        "M4 — se apaga el hostname check: un certificado de OTRO nombre pasa",
        _mutar_no_comprueba_el_nombre,
        ["test_nombre_del_certificado_que_no_coincide"],
        "NOMBRE_NO_COINCIDE",
    ),
    (
        "M5 — se silencia el fallo de verificación de cadena (verify=False "
        "disfrazado)",
        _mutar_silencia_el_fallo_de_cadena,
        ["test_certificado_no_declarado_no_verifica"],
        "CERTIFICADO_NO_VERIFICABLE",
    ),
    (
        "M6 — un 502 del terminador sin backend cuenta como «contestó»",
        _mutar_cualquier_estado_vale,
        ["test_terminador_tls_sin_backend_da_respuesta_inesperada"],
        "ENDPOINT_RESPUESTA_INESPERADA",
    ),
    (
        "M7 — fallo de HTTPS y aun así rc=0: la instalación se declararía "
        "COMPLETA sin HTTPS",
        _mutar_fallo_de_https_no_impide_completar,
        ["test_cualquier_hallazgo_impide_completar_la_instalacion[ESQUEMA_NO_HTTPS]",
         "test_cualquier_hallazgo_impide_completar_la_instalacion[COOKIE_SECURE_SOBRE_HTTP]",
         "test_cualquier_hallazgo_impide_completar_la_instalacion[ENDPOINT_NO_RESPONDE]",
         "test_cli_sobre_env_file_de_http_plano_falla_y_nombra_la_causa"],
        "INSTALACION NO COMPLETA",
    ),
    (
        "M8 — reaparece el FALLBACK A HTTP: se sondea la URL http:// en vez "
        "de negarse",
        _mutar_sondea_http_plano,
        ["test_nunca_se_sondea_http_plano"],
        "FALLBACK_A_HTTP",
    ),
]


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de "
              "calibrar (el harness restaura con escrituras sobre el fichero "
              "y un cambio no commiteado se perdería).")
        return 2

    rc, salida = _correr_testigo()
    if rc != 0:
        print(f"ABORTA: el testigo no está verde en la base (PYTEST_RC={rc})")
        print(salida[-3000:])
        return 2
    print(f"BASE: testigo verde, PYTEST_RC={rc}\n")

    f = RAIZ / FICHERO
    original = f.read_text(encoding="utf-8")

    veredictos = []
    for nombre, mutador, esperadas, fragmento in MUTACIONES:
        mutado = mutador(original)
        if mutado is None or mutado == original or not python_sigue_siendo_valido(mutado):
            print(f"### {nombre}\n  DETECTOR ROTO: la mutación no se pudo "
                  f"aplicar sobre {FICHERO} (ancla ausente/ambigua, o el "
                  f"resultado no es Python válido). Un verde aquí sería "
                  f"FALSO.\n")
            veredictos.append((nombre, "DETECTOR ROTO"))
            continue

        f.write_text(mutado, encoding="utf-8")
        rc_mut, salida_mut = _correr_testigo()
        fallos = _fallos(salida_mut)
        mensaje_ok = fragmento in salida_mut

        f.write_text(original, encoding="utf-8")
        _purgar_pycache()
        limpio = _arbol_limpio_tracked()
        rc_post, _ = _correr_testigo()

        print(f"### {nombre}")
        print(f"  fichero            : {FICHERO}")
        print(f"  PYTEST_RC mutado   : {rc_mut}  (esperado != 0)")
        print(f"  pruebas en rojo    : {fallos}")
        print(f"  esperadas (subset) : {sorted(esperadas)}")
        print(f"  MENSAJE contiene   : {fragmento!r} -> {mensaje_ok}")
        print(f"  restaurado (tracked limpio): {limpio}")
        print(f"  restaurado (PYTEST_RC post): {rc_post}  (esperado 0)")

        ok = (
            rc_mut != 0
            and len(fallos) > 0
            and set(esperadas).issubset(set(fallos))
            and mensaje_ok
            and limpio
            and rc_post == 0
        )
        print(f"  VEREDICTO          : {'CALIBRADA' if ok else 'NO CALIBRADA'}\n")
        veredictos.append((nombre, "CALIBRADA" if ok else "NO CALIBRADA"))

    print("=" * 70)
    for nombre, v in veredictos:
        print(f"  {v:<14} {nombre.splitlines()[0]}")
    print(f"  TOTAL: {sum(1 for _, v in veredictos if v == 'CALIBRADA')}"
          f"/{len(MUTACIONES)}")
    return 0 if all(v == "CALIBRADA" for _, v in veredictos) else 1


if __name__ == "__main__":
    sys.exit(main())
