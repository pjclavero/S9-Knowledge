#!/usr/bin/env python3
"""H-05 corte B — calibración de «el visor sólo atiende los Host declarados».

Una garantía no cuenta hasta que hay una prueba capaz de ponerse ROJA POR SU
CAUSA. Cada mutación reintroduce UN defecto sobre el código real, una cada vez
(localizador estructural por AST: `localizadores.mutar_en_funcion` /
`mutar_unico`; ancla ausente o ambigua = DETECTOR ROTO, nunca un verde), corre
el testigo `viewer/tests/test_h05b_trusted_host.py` y comprueba (1) que cayeron
las FUNCIONES de prueba esperadas, (2) que el mensaje del rojo dice la causa, y
(3) que la restauración es real (árbol tracked limpio + testigo verde).

  M1  quitar la frontera (`app.add_middleware(PublicHostMiddleware)`).
  M2  comodín `*`: la lista lo incluye y el middleware lo honra.
  M3  `testserver` en la configuración de PRODUCCIÓN (lista de loopback).
  M4  aceptar el placeholder de la plantilla.
  M5  fallback «sin configuración, permitir todo» en la petición.
  M6  autodetectar la IP local de la máquina.
  M7  segunda autoridad: el middleware lee la variable y parsea la URL por su
      cuenta (lo caza el gate de unicidad).
  M8  un Host no declarado llega al endpoint (el middleware deja pasar).
  M9  quitar la guarda ASCII de `normalizar_host` (`\xdf` -> `ss` suplanta al público).

Las mutaciones se aplican sobre el FUENTE (no se fabrica la entrada de la
prueba con la transformación bajo medida) y se restauran siempre.

TECHO DECLARADO: calibra `public_endpoint.py`, `public_host_middleware.py` y el
registro en `main.py`. No calibra el preflight de despliegue
(`deploy/tests/test_h05b_endpoint_publico_despliegue.py` tiene su propia
medida), ni el aliasing dinámico que el gate AST no ve (`getattr`,
`importlib`), ni un proxy que reescriba el Host.

Uso: python3 scripts/calibracion/mutaciones_h05b_trusted_host.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localizadores import (  # noqa: E402
    mutar_en_funcion, mutar_unico, python_sigue_siendo_valido)

RAIZ = Path(__file__).resolve().parents[2]
TESTIGO = "viewer/tests/test_h05b_trusted_host.py"
ENDPOINT = "viewer/app/public_endpoint.py"
MIDDLEWARE = "viewer/app/public_host_middleware.py"
MAIN = "viewer/app/main.py"

T = "test_"  # prefijo de las funciones de prueba nombradas abajo


def _sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True)


def _purgar_pycache() -> None:
    for d in RAIZ.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def _arbol_limpio_tracked() -> bool:
    r = _sh(["git", "status", "--porcelain", "--untracked-files=no"])
    return r.returncode == 0 and r.stdout.strip() == ""


def _correr_testigo() -> tuple[int, str]:
    _purgar_pycache()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", TESTIGO, "-q", "--no-header", "-W", "ignore",
         "--color=no", "-p", "no:randomly", "-p", "no:cacheprovider"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def _funciones_rojas(salida: str) -> set[str]:
    """Nombres de FUNCIÓN (sin parámetros) con al menos un caso FAILED/ERROR."""
    rojas = set()
    for linea in salida.splitlines():
        if linea.startswith(("FAILED", "ERROR")) and "::" in linea:
            rojas.add(linea.split("::", 1)[-1].split("[", 1)[0].split(" ", 1)[0])
    return rojas


# --- mutadores (cada uno devuelve None = DETECTOR ROTO) ---------------------

def _m1_main(t: str) -> str | None:
    return mutar_unico(t, "app.add_middleware(PublicHostMiddleware)\n", "pass\n")


def _m2_endpoint(t: str) -> str | None:
    return mutar_en_funcion(
        t, "resolve_trusted_hosts",
        "lista = [endpoint.hostname, *LOOPBACK_HOSTS]",
        'lista = [endpoint.hostname, *LOOPBACK_HOSTS, "*"]')


def _m2_middleware(t: str) -> str | None:
    return mutar_en_funcion(
        t, "__call__",
        "if host is not None and host in permitidos:",
        'if "*" in permitidos or (host is not None and host in permitidos):')


def _m3(t: str) -> str | None:
    return mutar_unico(
        t, 'LOOPBACK_HOSTS: Tuple[str, ...] = ("localhost", "127.0.0.1", "::1")',
        'LOOPBACK_HOSTS: Tuple[str, ...] = ("localhost", "127.0.0.1", "::1", "testserver")')


def _m4(t: str) -> str | None:
    return mutar_en_funcion(
        t, "interpretar_url_publica",
        'if canonico == PLACEHOLDER_HOST or canonico.endswith("." + PLACEHOLDER_HOST):',
        "if False:")


def _m5(t: str) -> str | None:
    return mutar_en_funcion(
        t, "__call__",
        'await _responder(503, "Public endpoint misconfigured", scope, receive, send)',
        "await self.app(scope, receive, send)")


def _m6(t: str) -> str | None:
    return mutar_en_funcion(
        t, "resolve_trusted_hosts",
        "lista = [endpoint.hostname, *LOOPBACK_HOSTS]",
        'lista = [endpoint.hostname, *LOOPBACK_HOSTS, '
        '__import__("socket").gethostbyname(__import__("socket").gethostname())]')


def _m7(t: str) -> str | None:
    return mutar_en_funcion(
        t, "__call__",
        "permitidos = resolve_trusted_hosts(extra=HOSTS_EXTRA_DE_PRUEBAS)",
        'permitidos = tuple(h for h in (__import__("urllib.parse").parse.urlsplit('
        '__import__("os").environ.get("S9K_PUBLIC_BASE_URL", "")).hostname, '
        '"localhost", "127.0.0.1", "::1", "testserver") if h)')


def _m9(t: str) -> str | None:
    # Las DOS guardas ASCII (cabecera y hostname): la defensa es redundante a
    # proposito y el defecto exige quitar ambas.
    m = mutar_en_funcion(
        t, "normalizar_host", "if not host.isascii():", "if False:")
    if m is None:
        return None
    return mutar_en_funcion(
        m, "normalizar_host_cabecera",
        "if not valor or not valor.isascii():", "if not valor:")


def _m8(t: str) -> str | None:
    return mutar_en_funcion(
        t, "__call__",
        'await _responder(400, "Invalid host header", scope, receive, send)',
        "await self.app(scope, receive, send)")


LISTA_400 = T + "host_no_declarado_da_400"
LLEGA = T + "host_malo_no_llega_al_endpoint_ni_al_almacen_ni_a_la_sesion"
GATE = T + "gate_unicidad_el_arbol_real_no_tiene_segunda_autoridad"
EXACTA = T + "la_lista_de_confianza_es_exactamente_publico_mas_loopback"
SIN_EXTRAS = T + "la_lista_de_confianza_no_tiene_comodin_ni_autodeteccion_ni_testserver"

# (nombre, [(fichero, mutador)], funciones esperadas en rojo, fragmento del mensaje)
MUTACIONES = [
    ("M1 — quitar la frontera de host (`add_middleware(PublicHostMiddleware)`)",
     [(MAIN, _m1_main)],
     {LISTA_400, LLEGA, T + "host_malformado_da_400", T + "host_ausente_da_400",
      T + "la_frontera_es_el_middleware_mas_externo"},
     "evil.example"),
    ("M2 — comodín `*` en la lista y honrado por el middleware",
     [(ENDPOINT, _m2_endpoint), (MIDDLEWARE, _m2_middleware)],
     {LISTA_400, SIN_EXTRAS, EXACTA},
     "evil.example"),
    ("M3 — `testserver` en la configuración de PRODUCCIÓN",
     [(ENDPOINT, _m3)],
     {T + "testserver_no_esta_en_la_configuracion_de_produccion",
      T + "testserver_en_un_interprete_limpio_sin_la_fixture_da_400", EXACTA, GATE},
     "testserver"),
    ("M4 — aceptar el placeholder de la plantilla",
     [(ENDPOINT, _m4)],
     {T + "placeholder_es_stop_aunque_sea_una_url_valida",
      T + "placeholder_el_valor_literal_de_la_plantilla_de_despliegue_se_detecta",
      T + "arranque_aborta_con_url_publica_invalida"},
     "DID NOT RAISE"),
    ("M5 — fallback «sin configuración, permitir todo» en la petición",
     [(MIDDLEWARE, _m5)],
     {T + "sin_configuracion_cada_peticion_falla_cerrada_nunca_abierta",
      T + "el_modo_test_no_se_deduce_de_la_ausencia_de_config_ni_del_hostname"},
     "503"),
    ("M6 — autodetectar la IP local de la máquina",
     [(ENDPOINT, _m6)],
     {EXACTA, SIN_EXTRAS},
     "public.example"),
    ("M7 — segunda autoridad: el middleware lee la variable y parsea la URL",
     [(MIDDLEWARE, _m7)],
     {GATE},
     "URLSPLIT_FUERA_DE_AUTORIDAD"),
    ("M9 — quitar la guarda ASCII: «\xdf» se pliega a «ss» y suplanta al host público",
     [(ENDPOINT, _m9)],
     {T + "n19_sharp_s_no_se_pliega_a_ss_por_asgi",
      T + "n19_sharp_s_en_bytes_crudos_con_servidor_real",
      T + "n19_barrido_latin1_0x80_0xff_todo_400",
      T + "n19_config_con_sharp_s_es_invalid_hostname_sin_convertir"},
     "cla"),
    ("M8 — un Host no declarado llega al endpoint",
     [(MIDDLEWARE, _m8)],
     {LISTA_400, LLEGA, T + "host_malformado_da_400", T + "host_ausente_da_400"},
     "evil.example"),
]


def main() -> int:
    if not _arbol_limpio_tracked():
        print("ABORTA: el árbol tracked no está limpio. Commitea antes de calibrar.")
        return 2
    rc, salida = _correr_testigo()
    if rc != 0:
        print(f"ABORTA: el testigo no está verde en la base (PYTEST_RC={rc})")
        print(salida[-2000:])
        return 2
    print(f"BASE: testigo verde, PYTEST_RC={rc}\n")

    veredictos = []
    for nombre, cambios, esperadas, fragmento in MUTACIONES:
        originales = {f: (RAIZ / f).read_text(encoding="utf-8") for f, _ in cambios}
        mutados = {}
        roto = False
        for fichero, mutador in cambios:
            m = mutador(originales[fichero])
            if m is None or m == originales[fichero] or not python_sigue_siendo_valido(m):
                print(f"### {nombre}\n  DETECTOR ROTO: la mutación no se pudo aplicar sobre "
                      f"{fichero} (ancla ausente/ambigua o Python inválido).\n")
                roto = True
                break
            mutados[fichero] = m
        if roto:
            veredictos.append((nombre, "DETECTOR ROTO"))
            continue
        try:
            for fichero, m in mutados.items():
                (RAIZ / fichero).write_text(m, encoding="utf-8")
            rc_mut, salida_mut = _correr_testigo()
        finally:
            for fichero, original in originales.items():
                (RAIZ / fichero).write_text(original, encoding="utf-8")
        rojas = _funciones_rojas(salida_mut)
        mensaje_ok = fragmento in salida_mut
        limpio = _arbol_limpio_tracked()
        rc_post, _ = _correr_testigo()
        faltan = sorted(esperadas - rojas)
        print(f"### {nombre}")
        print(f"  ficheros           : {', '.join(f for f, _ in cambios)}")
        print(f"  PYTEST_RC mutado   : {rc_mut}  (esperado != 0)")
        print(f"  funciones en rojo  : {len(rojas)}")
        print(f"  esperadas ausentes : {faltan}")
        print(f"  MENSAJE contiene   : {fragmento!r} -> {mensaje_ok}")
        print(f"  restaurado (tracked limpio): {limpio}")
        print(f"  restaurado (PYTEST_RC post): {rc_post}  (esperado 0)")
        ok = rc_mut != 0 and rojas and not faltan and mensaje_ok and limpio and rc_post == 0
        print(f"  VEREDICTO          : {'CALIBRADA' if ok else 'NO CALIBRADA'}\n")
        veredictos.append((nombre, "CALIBRADA" if ok else "NO CALIBRADA"))

    print("=" * 70)
    for nombre, v in veredictos:
        print(f"  {v:<14} {nombre}")
    return 0 if all(v == "CALIBRADA" for _, v in veredictos) else 1


if __name__ == "__main__":
    sys.exit(main())
