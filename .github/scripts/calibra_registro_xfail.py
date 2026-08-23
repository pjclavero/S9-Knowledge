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
import os
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

TOCABLES = (SUITE, REGISTRO,
            REPO / "viewer" / "tests" / "test_auth_core.py",
            REPO / "viewer" / "tests" / "conftest.py")

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


def _entorno(mutado: bool, ablacion: str = "") -> dict:
    """`S9K_REGISTRO_MUTADO` solo cuando el caso muta el registro A PROPOSITO.

    Sin esta bandera todos los casos que tocan el registro saldrian rojos por
    INTEGRIDAD en vez de por el control que cada uno calibra: rojos prestados.
    Y con ella puesta siempre, el caso que calibra la propia integridad no
    podria existir. Por eso va por caso, no global.
    """
    entorno = dict(os.environ)
    if mutado:
        entorno["S9K_REGISTRO_MUTADO"] = "1"
    else:
        entorno.pop("S9K_REGISTRO_MUTADO", None)
    entorno.pop("S9K_INVENTARIO_ABLACION", None)
    entorno.pop("S9K_EJECUCION_ABLACION", None)
    if ablacion == "ESTATICA":
        # Se desarma el reconocedor estatico entero (control A: A5, A6, A7).
        entorno["S9K_INVENTARIO_ABLACION"] = "A"
    elif ablacion == "RESULTADOS":
        entorno["S9K_EJECUCION_ABLACION"] = "1"
    return entorno


def capa_de_resultados(informe: Path, mutado: bool,
                       ablacion: str = "") -> tuple[int, str]:
    """El control de resultados AISLADO: sin gate estatico de por medio."""
    p = subprocess.run(
        [sys.executable, str(CONTROL), "--junit", str(informe), "--solo-registro"],
        cwd=REPO, capture_output=True, text=True, timeout=600,
        env=_entorno(mutado, ablacion),
    )
    return p.returncode, p.stdout + p.stderr


def capa_estatica(mutado: bool, ablacion: str = "") -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(GATE), "--base-fichero", str(INVENTARIO)],
        cwd=REPO, capture_output=True, text=True, timeout=2400,
        env=_entorno(mutado, ablacion),
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


NO_CRITICO = REPO / "viewer" / "tests" / "test_auth_core.py"
MODULO_NO_CRITICO = NO_CRITICO.relative_to(REPO).as_posix()


def m_l_registro_en_caliente() -> None:
    """L: una entrada escrita EN TIEMPO DE EJECUCION, como la escribiria CI.

    Es el bypass exacto que atraveso la guardia anterior, que enumeraba
    operadores de escritura en las lineas de `ci.yml` que nombraran el fichero:

        REG=.github/xfail-registro.txt      <- nombra, no escribe
        echo "AUTO-01 | ..." >> "$REG"      <- escribe, no nombra

    Este caso se ejecuta SIN `S9K_REGISTRO_MUTADO`, que es lo que lo convierte
    en el control negativo de la INTEGRIDAD: el contenido del arbol deja de
    coincidir con HEAD y da igual por que via se escribio.
    """
    REGISTRO.write_text(
        REGISTRO.read_text(encoding="utf-8")
        + f"AUTO-01 | {MODULO_NO_CRITICO}::test_x | sellado automatico\n",
        encoding="utf-8")


def m_m_defecto_conocido_nuevo() -> None:
    """M: un `xfail(strict=True)` NUEVO con su entrada CORRECTA en el registro.

    El patron legitimo que este carril identifico y preservo: la prueba que
    DEBERIA pasar, escrita ya, para que al arreglar el defecto el XPASS obligue
    a retirar la marca. Tiene que salir VERDE.

    Salia ROJO por D2 —`TESTS EN PIE A LA BAJA: 18 -> 17`— aunque X-T quedara
    satisfecho por el registro, porque `tests_en_pie` descuenta tambien los
    `xfail` autorizados. Era el mismo hallazgo de la escotilla desplazado un
    control. Este caso existe para que no vuelva a pasar sin que nadie se
    entere.
    """
    NO_CRITICO.write_text(
        NO_CRITICO.read_text(encoding="utf-8")
        + "\n\n@pytest.mark.xfail(strict=True, reason='DEFECTO CONOCIDO #1234')\n"
          "def test_calibracion_defecto_conocido_nuevo():\n    assert 1 == 2\n",
        encoding="utf-8")
    REGISTRO.write_text(
        REGISTRO.read_text(encoding="utf-8")
        + f"CAL-06 | {MODULO_NO_CRITICO}::test_calibracion_defecto_conocido_nuevo | "
          f"defecto conocido declarado por la calibracion\n",
        encoding="utf-8")


def m_n_indirecto() -> None:
    """N: la escritura INDIRECTA, con el nombre partido en dos tramos.

    Es la forma con la que un revisor atraveso la guardia que enumeraba
    operadores: la linea que nombra el fichero no escribe, y la que escribe no
    lo nombra. La propiedad no distingue vias, asi que da igual.
    """
    destino = REPO / ".github" / "xfail-registro.txt"
    ruta = str(destino)  # el "nombre construido" del ataque
    with open(ruta, "a", encoding="utf-8") as fh:
        fh.write(f"AUTO-02 | {MODULO_NO_CRITICO}::test_y | escrito indirectamente\n")


def m_o_registro_no_ablanda_a6() -> None:
    """O (RECIPROCO): una entrada legitima NO ablanda A6.

    El registro autoriza un RESULTADO —que esa prueba termine `xfail`—, no un
    MECANISMO. Marcar en ejecucion desde un `conftest` sigue prohibido aunque
    el nodeid este autorizado, y tiene que seguir estandolo: si una entrada
    ablandara A6, bastaria registrar una prueba cualquiera para abrir la
    inyeccion en tiempo de ejecucion para TODAS.
    """
    m_e_registrado()
    CONFTEST = REPO / "viewer" / "tests" / "conftest.py"
    CONFTEST.write_text(
        CONFTEST.read_text(encoding="utf-8")
        + "\n\nimport pytest as _p_cal_o  # INYECTADO POR LA CALIBRACION\n"
          "def pytest_collection_modifyitems(config, items):\n"
          "    for _it in items:\n"
          "        _it.add_marker(_p_cal_o.mark.xfail(reason='infra'))\n",
        encoding="utf-8")


def m_p_registro_no_ablanda_a7() -> None:
    """P (RECIPROCO): una entrada legitima NO ablanda A7.

    Mismo principio: el decorador de una suite critica tiene que resolver a una
    marca literal, este o no autorizado el nodeid. Autorizar un resultado no
    puede volver verificable un decorador que no lo es.
    """
    _añade("\n\ndef _marca_infra_calibracion(motivo):\n"
           "    return pytest.mark.xfail(reason=motivo)\n\n\n"
           "@_marca_infra_calibracion('inestable')\n"
           "def test_calibracion_helper_registrado():\n    assert 1 == 2\n")
    REGISTRO.write_text(
        REGISTRO.read_text(encoding="utf-8")
        + f"CAL-07 | {MODULO}::test_calibracion_helper_registrado | "
          f"autorizado, pero escrito de forma no verificable\n",
        encoding="utf-8")


CASOS = [
    # (titulo, mutacion, esp_resultados, esp_estatica, muta_registro, destino,
    #  ablacion)
    # --- LA MATRIZ EXIGIDA -------------------------------------------------
    # 1. registro del commit == registro usado -> VERDE
    ("K registro del commit == registro usado", None, VERDE, VERDE, True, "SUITE", ""),
    # 2. CI modifica el registro antes de pytest -> ROJO
    ("L CI modifica el registro (escritura directa)",
     m_l_registro_en_caliente, ROJO, ROJO, False, "SUITE", ""),
    # 3. CI lo modifica INDIRECTAMENTE (nombre partido) -> ROJO
    ("N CI modifica el registro INDIRECTAMENTE (nombre partido)",
     m_n_indirecto, ROJO, ROJO, False, "SUITE", ""),
    # 4. xfail critico no registrado -> ROJO
    ("A xfail critico NO registrado", m_a_directo, ROJO, ROJO, True, "SUITE", ""),
    # 5. entrada registrada sin xfail correspondiente -> ROJO
    ("F entrada registrada SIN xfail correspondiente",
     m_f_registro_obsoleto, ROJO, VERDE, True, "SUITE", ""),
    # 6. xfail registrado legitimo -> VERDE
    ("E xfail registrado legitimo", m_e_registrado, VERDE, VERDE, True, "SUITE", ""),
    # 7. sin reconocedor estatico, los casos de la capa de resultados siguen ROJO.
    #    Se usa B (fixture `autouse`) y no A a proposito: A escribe un decorador
    #    en el codigo, asi que con el control A desarmado lo sigue cazando X-T
    #    —el censo de sitios crece— y el caso no aislaria nada. Se escribio
    #    primero con A y la calibracion lo delato: estatica salia ROJA por
    #    `MAS PRUEBAS QUE NO PUEDEN FALLAR`, o sea por otro control. B marca en
    #    EJECUCION: no hay sitio que censar, asi que con A quitado la unica que
    #    puede verlo es la capa de resultados.
    ("Q7 con el RECONOCEDOR ESTATICO desarmado, B sigue ROJO por resultados",
     m_b_fixture, ROJO, VERDE, True, "SUITE", "ESTATICA"),
    # 8. sin capa de resultados, los casos puramente estaticos siguen ROJO
    ("Q8 con la CAPA DE RESULTADOS desarmada, H sigue ROJO por la estatica",
     m_h_suite_desaparecida, VERDE, ROJO, True, "SUITE", "RESULTADOS"),

    # --- el resto de vias de marca, que siguen cubiertas -------------------
    ("B xfail por FIXTURE autouse", m_b_fixture, ROJO, ROJO, True, "SUITE", ""),
    ("C xfail devuelto por una FUNCION AUXILIAR", m_c_helper, ROJO, ROJO, True, "SUITE", ""),
    ("D xfail a nivel de MODULO en suite critica", m_d_modulo, ROJO, ROJO, True, "SUITE", ""),
    ("G defecto ARREGLADO que produce XPASS", m_g_xpass, ROJO, VERDE, True, "SUITE", ""),
    ("H suite critica DESAPARECIDA (aislado del registro)",
     m_h_suite_desaparecida, VERDE, ROJO, True, "SUITE", ""),
    ("J una entrada para `test_a` no ampara `test_a_bis`",
     m_j_prefijo, ROJO, ROJO, True, "SUITE", ""),
    ("M defecto conocido NUEVO con su entrada correcta (D2 respeta la escotilla)",
     m_m_defecto_conocido_nuevo, VERDE, VERDE, True, "NO_CRITICO", ""),

    # --- RECIPROCO: ninguna capa reconoce DE MAS ---------------------------
    ("I el registro NO da ni quita criticidad",
     m_i_registro_no_da_criticidad, VERDE, VERDE, True, "SUITE", ""),
    # O sale VERDE en resultados y no es un fallo: es el limite ya documentado
    # de esa capa, medido otra vez. El `conftest` marca TODAS las pruebas, pero
    # las que aprueban terminan XPASS y en JUnit un `xpassed` es un `<testcase>`
    # pelado; la unica que llega a `xfailed` es la que falla, y esa esta
    # autorizada. O sea que la capa de resultados no tiene nada que objetar, y
    # es EXACTAMENTE por eso que A6 tiene que existir aparte y no puede
    # ablandarse con una entrada del registro.
    ("O el registro NO ablanda A6 (marcar en ejecucion sigue prohibido)",
     m_o_registro_no_ablanda_a6, VERDE, ROJO, True, "SUITE", ""),
    ("P el registro NO ablanda A7 (decorador no verificable sigue prohibido)",
     m_p_registro_no_ablanda_a7, VERDE, ROJO, True, "SUITE", ""),
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
        for titulo, mutacion, esp_res, esp_est, mutado, cual, ablacion in CASOS:
            for f, datos in respaldo.items():
                f.write_bytes(datos)
            subprocess.run(["find", str(REPO), "-name", "__pycache__", "-type",
                            "d", "-not", "-path", "*/.git/*", "-exec", "rm",
                            "-rf", "{}", "+"], capture_output=True, timeout=120)
            print(f"\n########## {titulo}")
            if mutacion is not None:
                mutacion()

            destino = SUITE if cual == "SUITE" else NO_CRITICO
            if destino.exists():
                informe = corre_pytest(destino, tmp)
                rc_res, sal_res = capa_de_resultados(informe, mutado, ablacion)
            else:
                # La suite ya no existe: la capa de resultados no puede decir
                # nada de un informe que no se puede producir, y eso es
                # justamente lo que aisla H.
                rc_res, sal_res = 0, "(suite borrada: no hay informe que juzgar)"
            rc_est, sal_est = capa_estatica(mutado, ablacion)

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
