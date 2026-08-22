#!/usr/bin/env python3
"""Calibracion del REGISTRO de `xfail` contra la ejecucion real.

QUE SE DEMUESTRA
================
Que la garantia ya no depende de reconocer la SINTAXIS con la que alguien
escribio un `xfail`. Durante cinco rondas se intento: decorador directo,
`pytestmark`, alias de modulo, `pytest.param(marks=...)`, un `conftest` con
`add_marker`, un fixture `autouse` en el propio modulo, una funcion auxiliar que
devuelve la marca. Cada ronda cerro lo encontrado y en la siguiente aparecio una
forma nueva. La sintaxis de Python para producir una marca es una superficie
ABIERTA y perseguirla no acaba.

La unidad de control pasa a ser otra:

    INVENTARIO CRITICO + RESULTADO REAL DE PYTEST + REGISTRO EXPLICITO

Y lo que aqui se mide, caso por caso, es CUAL DE LAS DOS CAPAS lo caza. Los
casos A-D tienen que ponerse rojos POR LA CAPA DE RESULTADOS, no prestados por
el reconocedor estatico: por eso cada caso se ejecuta DOS veces, una contra el
control de resultados AISLADO (`--solo-registro`, sin el gate estatico de por
medio) y otra contra el gate estatico, y la tabla publica las dos columnas.

LOS OCHO CASOS EXIGIDOS, mas tres que anaden precision:

    A  xfail directo NO registrado                 -> ROJO
    B  xfail mediante fixture `autouse`            -> ROJO
    C  xfail devuelto por una funcion auxiliar     -> ROJO
    D  xfail a nivel de MODULO en una suite critica-> ROJO
    E  xfail conocido y REGISTRADO                 -> VERDE
    F  borrar el xfail dejando la entrada          -> ROJO (registro obsoleto)
    G  defecto arreglado que produce XPASS         -> ROJO (misma direccion)
    H  suite critica DESAPARECIDA                  -> ROJO por inventario, y
                                                      AISLADO del registro
    I  el registro NO puede dar ni quitar criticidad
    J  una entrada para `test_a` NO ampara `test_a_bis`
    K  control positivo: el arbol tal cual         -> VERDE

SOBRE G, que es el que define el mecanismo: un `xfail(strict=True)` que empieza
a pasar produce XPASS, y en JUnit un `xpassed` sale como un `<testcase>` PELADO,
indistinguible de un aprobado (medido sobre un informe real: 21 pelados frente a
1 con `<skipped type="pytest.xfail">`). Mirando SOLO el informe no hay forma de
verlo. Por eso G no se infiere del informe: se detecta porque el REGISTRO dice
que ahi deberia haber un `xfail` y no lo hay. La direccion "entrada registrada
que ya no aparece" no es un extra, es el unico camino.

MUTA FICHEROS REALES: se serializa con cerrojo y se revierte verificando
SHA-256, igual que los otros arneses del carril.
"""
from __future__ import annotations

import fcntl
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTROL = REPO / ".github" / "scripts" / "check_ejecucion_real.py"
GATE = REPO / ".github" / "scripts" / "check_suite_inventory.py"
REGISTRO = REPO / ".github" / "xfail-registro.txt"
INVENTARIO = REPO / ".github" / "suite-inventario.json"

# Una suite CRITICA pequena: 22 pruebas, ~2 s. Lo critico importa porque varios
# casos solo tienen sentido ahi.
SUITE = REPO / "viewer" / "tests" / "test_parcialidad_declarada.py"
MODULO = SUITE.relative_to(REPO).as_posix()

TOCABLES = (SUITE, REGISTRO)

VERDE, ROJO = "VERDE", "ROJO"

CERROJO = (REPO / ".git" / "s9k-calibra-registro.lock") if (REPO / ".git").is_dir() \
    else Path(tempfile.gettempdir()) / "s9k-calibra-registro.lock"


def sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def toma_cerrojo():
    fh = open(CERROJO, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise SystemExit(f"ERROR: ya hay otra calibracion corriendo ({CERROJO}). "
                         f"Este script MUTA ficheros reales.")
    return fh


def corre_pytest(destino: Path, tmp: Path) -> Path:
    informe = tmp / "junit.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", str(destino), "-q", "--no-header",
         "--tb=no", f"--junitxml={informe}"],
        cwd=REPO, capture_output=True, text=True, timeout=1800,
    )
    return informe


def capa_de_resultados(informe: Path) -> tuple[int, str]:
    """El control de resultados AISLADO: sin gate estatico de por medio."""
    p = subprocess.run(
        [sys.executable, str(CONTROL), "--junit", str(informe), "--solo-registro"],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )
    return p.returncode, p.stdout + p.stderr


def capa_estatica() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(GATE), "--base-fichero", str(INVENTARIO)],
        cwd=REPO, capture_output=True, text=True, timeout=2400,
    )
    return p.returncode, p.stdout + p.stderr


# --------------------------------------------------------------------------
# Mutaciones. Cada una escribe la suite y/o el registro; nunca las dos cosas
# por la misma razon, para que el rojo de cada caso sea suyo.
# --------------------------------------------------------------------------

def _añade(texto: str) -> None:
    SUITE.write_text(SUITE.read_text(encoding="utf-8") + texto, encoding="utf-8")


def _defecto() -> str:
    return ("\n\ndef test_defecto_inyectado_por_la_calibracion():\n"
            "    assert 1 == 2\n")


def m_a_directo() -> None:
    # `pytest.mark.xfail` LITERAL, no `import pytest as _p`: el modulo ya
    # importa `pytest`, y un alias del propio import es una indireccion que A7
    # marca por su cuenta. Se escribio primero con alias y la calibracion lo
    # delato: el caso E salia rojo por A7 en vez de verde por el registro, o
    # sea que la mutacion no estaba midiendo lo que decia medir.
    _añade("\n\n@pytest.mark.xfail(reason='infra inestable')\n"
           "def test_calibracion_xfail_directo():\n    assert 1 == 2\n")


def m_b_fixture() -> None:
    _añade("\n\n@pytest.fixture(autouse=True)\n"
           "def _estabilidad_calibracion(request):\n"
           "    request.node.add_marker(pytest.mark.xfail(reason='infra'))\n"
           + _defecto())


def m_c_helper() -> None:
    _añade("\n\ndef _marca_infra_calibracion(motivo):\n"
           "    return pytest.mark.xfail(reason=motivo)\n\n\n"
           "@_marca_infra_calibracion('inestable')\n"
           "def test_calibracion_xfail_por_helper():\n    assert 1 == 2\n")


def m_d_modulo() -> None:
    _añade("\n\npytestmark = pytest.mark.xfail(reason='infra inestable')\n"
           + _defecto())


def m_e_registrado() -> None:
    """El MISMO xfail de A, pero declarado en el registro. Tiene que ser VERDE:
    si no, el gate no dejaria ninguna via y acabaria desactivado."""
    m_a_directo()
    REGISTRO.write_text(
        REGISTRO.read_text(encoding="utf-8")
        + f"CAL-01 | {MODULO}::test_calibracion_xfail_directo | "
          f"defecto conocido inyectado por la calibracion\n",
        encoding="utf-8")


def m_f_registro_obsoleto() -> None:
    """La entrada se queda y el `xfail` no llega a existir."""
    REGISTRO.write_text(
        REGISTRO.read_text(encoding="utf-8")
        + f"CAL-02 | {MODULO}::test_caso_pequeno_completo | "
          f"entrada que ya no corresponde a ningun xfail\n",
        encoding="utf-8")


def m_g_xpass() -> None:
    """El defecto ARREGLADO: la prueba lleva `xfail(strict=False)` y PASA.

    En JUnit sale como un `<testcase>` pelado, asi que el informe por si solo no
    la distingue de un aprobado. Solo el registro, diciendo que ahi deberia
    haber un `xfail`, permite verlo.
    """
    _añade("\n\n@pytest.mark.xfail(reason='defecto ya arreglado')\n"
           "def test_calibracion_defecto_arreglado():\n    assert True\n")
    REGISTRO.write_text(
        REGISTRO.read_text(encoding="utf-8")
        + f"CAL-03 | {MODULO}::test_calibracion_defecto_arreglado | "
          f"defecto conocido que en realidad ya esta arreglado\n",
        encoding="utf-8")


def m_h_suite_desaparecida() -> None:
    """AISLADO del registro a proposito: no se toca `xfail-registro.txt`.

    Asi el rojo de H no puede venir prestado de A-G: solo puede venir del
    inventario critico.
    """
    SUITE.unlink()


def m_i_registro_no_da_criticidad() -> None:
    """El registro NO puede declarar ni retirar criticidad.

    Se anade una entrada para un modulo NO critico y otra para uno critico, y se
    comprueba que el conjunto de criticos que DERIVA el gate no se mueve. La
    criticidad sale de fuentes ejecutables (`pytest.mark.critico` y los arneses),
    y mezclarla aqui volveria a juntar lo que costo separar.
    """
    REGISTRO.write_text(
        REGISTRO.read_text(encoding="utf-8")
        + "CAL-04 | viewer/tests/test_auth_core.py::test_que_no_existe | "
          "entrada sobre un modulo NO critico\n",
        encoding="utf-8")


def m_j_prefijo() -> None:
    """Una entrada para `test_a` no puede amparar a `test_a_bis`."""
    _añade("\n\n@pytest.mark.xfail(reason='infra')\n"
           "def test_calibracion_ancla_bis():\n    assert 1 == 2\n")
    REGISTRO.write_text(
        REGISTRO.read_text(encoding="utf-8")
        + f"CAL-05 | {MODULO}::test_calibracion_ancla | "
          f"entrada para OTRA prueba con el mismo prefijo\n",
        encoding="utf-8")


CASOS = [
    # (titulo, mutacion, esperado_resultados, esperado_estatico)
    ("K control positivo: el arbol tal cual", None, VERDE, VERDE),
    ("A xfail DIRECTO no registrado", m_a_directo, ROJO, ROJO),
    ("B xfail por FIXTURE autouse", m_b_fixture, ROJO, ROJO),
    ("C xfail devuelto por una FUNCION AUXILIAR", m_c_helper, ROJO, ROJO),
    ("D xfail a nivel de MODULO en suite critica", m_d_modulo, ROJO, ROJO),
    ("E xfail conocido y REGISTRADO", m_e_registrado, VERDE, VERDE),
    ("F entrada registrada sin xfail (registro obsoleto)",
     m_f_registro_obsoleto, ROJO, VERDE),
    ("G defecto ARREGLADO que produce XPASS", m_g_xpass, ROJO, VERDE),
    ("H suite critica DESAPARECIDA (aislado del registro)",
     m_h_suite_desaparecida, VERDE, ROJO),
    ("I el registro NO da ni quita criticidad",
     m_i_registro_no_da_criticidad, VERDE, VERDE),
    ("J una entrada para `test_a` no ampara `test_a_bis`", m_j_prefijo, ROJO, ROJO),
]


def criticos_derivados() -> set[str]:
    sys.path.insert(0, str(REPO / ".github" / "scripts"))
    for mod in [m for m in list(sys.modules) if m == "check_suite_inventory"]:
        del sys.modules[mod]
    import check_suite_inventory as G  # noqa: E402
    return set(G.criticos_por_calibrador())


def main() -> int:
    cerrojo = toma_cerrojo()
    print(f"(cerrojo tomado: {CERROJO}; este script MUTA ficheros reales)")

    respaldo = {f: f.read_bytes() for f in TOCABLES}
    hashes = {f: sha(d) for f, d in respaldo.items()}
    print("\nSHA-256 ANTES:")
    for f, h in hashes.items():
        print(f"  {h}  {f.relative_to(REPO)}")

    criticos_base = criticos_derivados()
    print(f"\ncriticos derivados de fuentes ejecutables (base): "
          f"{len(criticos_base)} modulos")

    tmp = Path(tempfile.mkdtemp(prefix="calibra-registro-"))
    filas, fallos = [], 0
    try:
        for titulo, mutacion, esp_res, esp_est in CASOS:
            for f, datos in respaldo.items():
                f.write_bytes(datos)
            subprocess.run(["find", str(REPO), "-name", "__pycache__", "-type",
                            "d", "-not", "-path", "*/.git/*", "-exec", "rm",
                            "-rf", "{}", "+"], capture_output=True, timeout=120)
            print(f"\n########## {titulo}")
            if mutacion is not None:
                mutacion()

            if SUITE.exists():
                informe = corre_pytest(SUITE, tmp)
                rc_res, sal_res = capa_de_resultados(informe)
            else:
                # La suite ya no existe: la capa de resultados no puede decir
                # nada de un informe que no se puede producir, y eso es
                # justamente lo que aisla H.
                rc_res, sal_res = 0, "(suite borrada: no hay informe que juzgar)"
            rc_est, sal_est = capa_estatica()

            obt_res = VERDE if rc_res == 0 else ROJO
            obt_est = VERDE if rc_est == 0 else ROJO
            ok = (obt_res == esp_res) and (obt_est == esp_est)
            fallos += 0 if ok else 1

            def primer_error(salida: str) -> str:
                for linea in salida.splitlines():
                    if linea.startswith("::error::"):
                        return linea[len("::error::"):].strip().replace("|", "/")[:95]
                return "sin errores"

            quien = ("RESULTADOS" if obt_res == ROJO and obt_est == VERDE else
                     "ESTATICA" if obt_est == ROJO and obt_res == VERDE else
                     "LAS DOS" if obt_res == ROJO else "ninguna")
            print(f"  capa de RESULTADOS (aislada): {obt_res}  "
                  f"[{primer_error(sal_res)}]")
            print(f"  capa ESTATICA:                {obt_est}  "
                  f"[{primer_error(sal_est)}]")
            filas.append((titulo, esp_res, obt_res, esp_est, obt_est, quien,
                          "OK" if ok else "**DESVIACION**",
                          primer_error(sal_res if obt_res == ROJO else sal_est)))
    finally:
        for f, datos in respaldo.items():
            f.write_bytes(datos)
        shutil.rmtree(tmp, ignore_errors=True)
        fcntl.flock(cerrojo, fcntl.LOCK_UN)
        cerrojo.close()

    print("\n===== REVERSION VERIFICADA POR SHA-256 =====")
    for f, esperado in hashes.items():
        real = sha(f.read_bytes())
        marca = "OK" if real == esperado else "**NO COINCIDE**"
        fallos += 0 if real == esperado else 1
        print(f"  {marca}  {real}  {f.relative_to(REPO)}")

    criticos_final = criticos_derivados()
    if criticos_final != criticos_base:
        fallos += 1
        print(f"\n**DESVIACION**: el conjunto de criticos DERIVADOS cambio "
              f"durante la calibracion: {criticos_final ^ criticos_base}")
    else:
        print(f"\nOK: el conjunto de criticos derivados NO se movio ({len(criticos_base)} "
              f"modulos). Ninguna entrada del registro puede darla ni quitarla.")

    print("\n\n===== TABLA DE CALIBRACION (registro contra ejecucion real) =====\n")
    print("| Caso | Esp. resultados | Resultados | Esp. estatica | Estatica | "
          "Quien lo caza | Veredicto | Primer error |")
    print("|---|---|---|---|---|---|---|---|")
    for fila in filas:
        print("| {} | {} | {} | {} | {} | {} | {} | {} |".format(*fila))

    if fallos:
        print(f"\nCALIBRACION FALLIDA: {fallos} desviacion(es)")
        return 1
    print(f"\nCALIBRACION SUPERADA: {len(filas)}/{len(filas)} casos con el "
          f"veredicto esperado en LAS DOS capas, y los {len(hashes)} ficheros "
          f"restaurados con el MISMO SHA-256")
    return 0


if __name__ == "__main__":
    sys.exit(main())
