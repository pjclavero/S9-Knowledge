#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR-4 (USABLE-V1) — arnés de calibración de «tras el bootstrap, la
instalación está COMPLETA: el primer administrador se crea, entra y persiste».

ESTADO
------
::

    CODE         PASS
    CALIBRATION  PASS      es lo que este arnés mide
    RC-E2E       PENDING   sin nginx, sin systemd, sin VM, sin navegador

Mismo motor que `mutaciones_pr3_instalacion_https.py`: una garantía no cuenta
hasta que hay una prueba CAPAZ DE PONERSE ROJA, y roja POR SU CAUSA. Cada
mutación reintroduce UN defecto real de este corte sobre el código commiteado,
uno cada vez, corre el testigo (`deploy/tests/test_preflight_setup_admin.py`)
y comprueba:

    1. que las pruebas que DEBÍAN caer cayeron, y
    2. que el MENSAJE del rojo dice la causa (fragmento discriminante, nunca
       un `AssertionError` pelado).

Las CUATRO mutaciones obligatorias del encargo están aquí y nombradas:

    M1 — el preflight PASA con un `GET 200` SIN completar el POST.
    M2 — se ACEPTA HTTP plano como instalación completa.
    M3 — la verificación pasa SIN comprobar la persistencia tras reinicio.
    M4 — se rompe el FAIL-CLOSED de un setup corrupto o parcial.

Localizador ESTRUCTURAL: todas las mutaciones usan
`localizadores.mutar_en_funcion`, que devuelve ``None`` —DETECTOR ROTO— en vez
de elegir una ocurrencia ambigua. Nada de `.replace(..., 1)`, nada de anclas
por indentación, nada de mutaciones que no llamen al producto: el testigo
arranca el VISOR REAL por `uvicorn` con TLS y reinicia su PROCESO contra el
código mutado.

TECHO DE ESTE CALIBRADOR
------------------------
* Muta por SUSTITUCIÓN DE TEXTO EXACTO dentro de una función localizada por
  AST. No ve alias, ni una segunda copia de la misma lógica en otro módulo.
* Calibra `deploy/scripts/preflight_setup_admin.py`. Las puertas estáticas que
  ese módulo IMPORTA de `preflight_https.py` están calibradas en el arnés del
  PR-3, no aquí: M2 ataca la ORQUESTACIÓN que las llama —que es lo propio de
  este corte—, no su interior.
* NO muta el visor. Que el producto ponga `Secure`, firme el token y selle la
  instalación lo OBSERVA el testigo contra el visor real; lo que este arnés
  calibra es que el PREFLIGHT no deje pasar las formas en que eso falla.
* No mide despliegue real, ni nginx, ni systemd, ni navegador, ni una VM
  limpia. Eso es el ensayo RC (`deploy/README.md`), **PENDIENTE**.

Uso: python3 scripts/calibracion/mutaciones_pr4_instalacion_completa.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localizadores import mutar_en_funcion, python_sigue_siendo_valido  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
TESTIGO = "deploy/tests/test_preflight_setup_admin.py"
FICHERO = "deploy/scripts/preflight_setup_admin.py"


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

# M1 (OBLIGATORIA) — EL GUARDIAN DE «NO BASTA GET 200» DEJA DE GUARDAR.
# `comprobar_recorrido_completo` calla siempre, así que las fases no ejercidas
# dejan de constar. Es el defecto de clase de este corte: confundir «el
# endpoint respondió» con «el administrador se puede crear», y es exactamente
# la forma en que un `GET 200` sin POST daría verde.
def _mutar_el_get_200_basta(texto: str):
    return mutar_en_funcion(
        texto,
        "comprobar_recorrido_completo",
        "    faltan = recorrido.no_observadas(fases)\n    if not faltan:",
        "    faltan = recorrido.no_observadas(fases)\n    if True:",
    )


# M2 (OBLIGATORIA) — se ACEPTA HTTP plano: la puerta estática se queda muda y
# la orquestación se pone a sondear `http://`. Es el fallback a HTTP que D3
# prohíbe, reaparecido en la capa que este corte añade.
def _mutar_acepta_http_plano(texto: str):
    return mutar_en_funcion(
        texto,
        "_puerta_estatica",
        "    return hallazgos",
        "    return []",
    )


# M3 (OBLIGATORIA) — la verificación pasa SIN comprobar la persistencia: el
# resultado de mirar el sello tras el reinicio se ignora. Una base no durable
# —ruta en tmpfs, volumen sin montar, contenedor que recrea su almacén—
# volvería a ofrecer `/setup/admin` y esto lo daría por bueno.
def _mutar_no_comprueba_la_persistencia(texto: str):
    return mutar_en_funcion(
        texto,
        "verificar_persistencia",
        "    if sello is not None:",
        "    if False:",
    )


# M4 (OBLIGATORIA) — se rompe el FAIL-CLOSED: el 503 con el que el producto
# dice «el almacén de autenticación existe y no se puede leer, o estaba y ha
# desaparecido» deja de reconocerse. Un setup corrupto o parcial se leería
# como una instalación cualquiera en vez de como «NO SE SABE».
def _mutar_rompe_el_fail_closed(texto: str):
    return mutar_en_funcion(
        texto,
        "comprobar_get_del_formulario",
        "    if estado == ESTADO_FAIL_CLOSED:",
        "    if False:",
    )


# M5 — la cookie de setup sin `Secure` deja de ser un fallo. Es LA
# DEGRADACIÓN QUE D3 CONSIDERÓ Y DESCARTÓ: quitarle `Secure` a la cookie (o
# deducirla de `request.scheme`) para que la instalación pase.
def _mutar_cookie_sin_secure_no_es_fallo(texto: str):
    return mutar_en_funcion(
        texto,
        "comprobar_get_del_formulario",
        "    if not galleta.secure:",
        "    if False:",
    )


# M6 — el 403 del POST deja de nombrarse como el bucle CSRF y cae en el cajón
# genérico. El veredicto seguiría siendo rojo, pero el operador perdería el
# diagnóstico: un gate puede acertar el veredicto y no decir en qué capa falló.
def _mutar_el_403_no_se_nombra(texto: str):
    return mutar_en_funcion(
        texto,
        "comprobar_post_crea_el_administrador",
        "    if estado == 403:",
        "    if False:",
    )


# M7 — el sello deja de comprobarse: `/setup/admin` sigue sirviéndose tras
# crear el primer administrador y se da por bueno. Una instalación que sigue
# ofreciendo crear el primer administrador permite que un desconocido cree otro.
def _mutar_el_sello_no_se_comprueba(texto: str):
    return mutar_en_funcion(
        texto,
        "comprobar_sello_cierra_el_setup",
        "    if estado != 404:",
        "    if False:",
    )


# M8 — una redirección de login sin cookie de sesión cuenta como login
# correcto. En el navegador eso se ve como un login que vuelve al login.
def _mutar_sesion_no_hace_falta(texto: str):
    return mutar_en_funcion(
        texto,
        "hay_cookie_de_sesion",
        "    return any(nombre not in csrf for nombre in cliente.cookies)",
        "    return True",
    )


# M9 — el código de salida deja de reflejar los hallazgos: el recorrido falla
# y aun así rc=0, así que el despliegue seguiría adelante declarando la
# instalación completa.
def _mutar_el_fallo_no_impide_completar(texto: str):
    return mutar_en_funcion(
        texto,
        "codigo_de_salida",
        "    return 0 if not hallazgos else 1",
        "    return 0",
    )


# M10 — el cliente deja de respetar `Secure` y devuelve la cookie por
# cualquier canal. Es la mutación que ciega al INSTRUMENTO: con ella el
# control positivo del bucle de 403 dejaría de reproducirse, y un arnés que no
# ve el defecto cuando está no vale como medida de su ausencia.
def _mutar_el_cliente_ignora_secure(texto: str):
    return mutar_en_funcion(
        texto,
        "_cabecera_cookie",
        "            if (not g.secure) or self.esquema == \"https\"",
        "            if True",
    )


MUTACIONES = [
    (
        "M1 (OBLIGATORIA) — el preflight PASA con un GET 200 SIN completar "
        "el POST (el guardián de «no basta GET 200» deja de guardar)",
        _mutar_el_get_200_basta,
        ["test_un_get_200_sin_post_no_basta_para_declarar_la_instalacion_completa",
         "test_el_guardian_nombra_cada_fase_no_observada",
         "test_el_preflight_nunca_sondea_http_plano"],
        "RECORRIDO_INCOMPLETO",
    ),
    (
        "M2 (OBLIGATORIA) — se ACEPTA HTTP plano como instalación completa "
        "(reaparece el fallback que D3 prohíbe)",
        _mutar_acepta_http_plano,
        ["test_el_preflight_nunca_sondea_http_plano"],
        "FALLBACK A HTTP",
    ),
    (
        "M3 (OBLIGATORIA) — la verificación pasa SIN comprobar la "
        "persistencia tras reinicio",
        _mutar_no_comprueba_la_persistencia,
        ["test_persistencia_sobre_una_instalacion_de_fabrica_dice_que_no_persiste"],
        "ESTADO_NO_PERSISTE",
    ),
    (
        "M4 (OBLIGATORIA) — se rompe el FAIL-CLOSED de un setup corrupto o "
        "parcial (el 503 del almacén deja de reconocerse)",
        _mutar_rompe_el_fail_closed,
        ["test_el_fail_closed_de_un_almacen_corrupto_no_se_lee_como_instalacion_nueva"],
        "ALMACEN_DE_AUTH_NO_DISPONIBLE",
    ),
    (
        "M5 — la cookie de setup sin Secure deja de ser un fallo (la "
        "degradación que D3 descartó)",
        _mutar_cookie_sin_secure_no_es_fallo,
        ["test_la_cookie_de_setup_sin_secure_se_rechaza"],
        "COOKIE_SETUP_SIN_SECURE",
    ),
    (
        "M6 — el 403 del POST deja de nombrarse como el bucle CSRF",
        _mutar_el_403_no_se_nombra,
        ["test_control_positivo_el_bucle_403_sobre_http_plano_es_real",
         "test_un_get_200_sin_post_no_basta_para_declarar_la_instalacion_completa"],
        "BUCLE_403_CSRF",
    ),
    (
        "M7 — el sello deja de comprobarse: /setup/admin sigue abierto tras "
        "crear el primer administrador y se da por bueno",
        _mutar_el_sello_no_se_comprueba,
        ["test_el_sello_que_no_cierra_el_setup_es_un_fallo"],
        "SELLO_NO_CIERRA_SETUP",
    ),
    (
        "M8 — un login que redirige SIN emitir sesión cuenta como correcto",
        _mutar_sesion_no_hace_falta,
        ["test_un_login_que_redirige_sin_emitir_sesion_es_un_fallo"],
        "SESION_NO_EMITIDA",
    ),
    (
        "M9 — el recorrido falla y aun así rc=0: la instalación se "
        "declararía COMPLETA",
        _mutar_el_fallo_no_impide_completar,
        ["test_cualquier_hallazgo_impide_declarar_la_instalacion_completa[ESQUEMA_NO_HTTPS]",
         "test_cualquier_hallazgo_impide_declarar_la_instalacion_completa[RECORRIDO_INCOMPLETO]",
         "test_cualquier_hallazgo_impide_declarar_la_instalacion_completa[SELLO_NO_CIERRA_SETUP]",
         "test_cualquier_hallazgo_impide_declarar_la_instalacion_completa[ALMACEN_DE_AUTH_NO_DISPONIBLE]"],
        "IMPEDIR DECLARAR LA INSTALACION COMPLETA",
    ),
    (
        "M10 — el cliente ignora Secure y devuelve la cookie por cualquier "
        "canal: CIEGA al instrumento (el bucle de 403 deja de reproducirse)",
        _mutar_el_cliente_ignora_secure,
        ["test_control_positivo_el_bucle_403_sobre_http_plano_es_real"],
        "EL CONTROL POSITIVO HA FALLADO",
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
