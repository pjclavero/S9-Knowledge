#!/usr/bin/env python3
"""Calibracion de A2-LINAJE: que el gate distinga NACER de APAGARSE.

QUE SE CALIBRA Y POR QUE VA APARTE
==================================
`calibra_suite_inventory.py` calibra los controles del inventario contra una
base de FICHERO (`--base-fichero .github/suite-inventario.json`). Esa base no
corresponde a ningun commit, asi que alli A2 no puede preguntar por el linaje y
se queda -a proposito- en su forma ESTRICTA. Es la forma conservadora y hay que
mantenerla calibrada, pero no es la que este PR estrena.

Lo que este arnes calibra es la otra: A2 contra la LINEA BASE GIT de verdad,
`merge-base HEAD origin/main`, que es la que corre en CI. Y lo hace mutando el
ARBOL DE TRABAJO, que es exactamente el sujeto que el gate mide; comparar
contra HEAD habria sido el sesgo conocido de este carril -"con y sin la
mutacion" dando lo mismo en los dos lados-.

LA TABLA QUE TIENE QUE SALIR
============================
    1. fichero nuevo que nace condicional             -> VERDE
    2. fichero nuevo obligatorio                      -> VERDE
    3. obligatorio existente -> condicional           -> ROJO
    3b. el mismo caso con la ablacion A puesta        -> VERDE  (aisla el rojo)
    4. condicional existente -> condicional           -> VERDE
    5. condicional existente -> obligatorio           -> VERDE
    6. obligatorio existente eliminado                -> ROJO
    7. obligatorio RENOMBRADO + condicional           -> ROJO
    7b. lo mismo sin seguir el fichero por Git        -> ROJO  (identidad logica)
    8. control positivo restaurado                    -> VERDE

El caso 7 es el ataque que este PR no puede dejar abierto:

    test_obligatorio.py -> renombrarlo -> anadirle una condicion -> "es nuevo"

y se monta con la baja del modulo viejo YA DECLARADA en `suite-bajas.txt`, para
que el trinquete C quede satisfecho y el unico rojo posible sea el de A2. Un
rojo por la razon equivocada se lee igual que uno legitimo, asi que ademas se
comprueba QUE ERROR sale, no solo que el RC sea 1.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".github" / "scripts"))

import arnes_comun  # noqa: E402

VERDE, ROJO = "VERDE", "ROJO"

# Un modulo OBLIGATORIO de verdad del repositorio, en el inventario de la base
# y sin ninguna condicion. No es un fichero de juguete: el negativo tiene que
# morder sobre una garantia real.
OBLIGATORIO = REPO / "viewer" / "tests" / "test_auth_core.py"
# Y uno CRITICO, para que el negativo tambien se vea sobre lo mas sujeto.
CRITICO = REPO / "viewer" / "tests" / "test_parcialidad_declarada.py"
# Un modulo que YA era condicional en la base c29dfaa6.
CONDICIONAL = REPO / "deploy" / "tests" / "test_resolve_release_commit.py"
BAJAS = REPO / ".github" / "suite-bajas.txt"

TOCABLES = (OBLIGATORIO, CRITICO, CONDICIONAL, BAJAS)

# Ficheros que los casos CREAN. Se borran entre casos y al final.
NUEVO_CONDICIONAL = REPO / "viewer" / "tests" / "test_a2cal_nace_condicional.py"
NUEVO_OBLIGATORIO = REPO / "viewer" / "tests" / "test_a2cal_nace_obligatorio.py"
RENOMBRADO = REPO / "viewer" / "tests" / "test_auth_core_renombrado.py"
CREADOS = (NUEVO_CONDICIONAL, NUEVO_OBLIGATORIO, RENOMBRADO)

CONDICION = (
    "\nimport os as _os_a2cal, pytest as _p_a2cal  # INYECTADO POR LA CALIBRACION\n"
    "pytestmark = _p_a2cal.mark.skipif(\n"
    "    not _os_a2cal.environ.get('S9K_UNA_CONDICION_DE_CALIBRACION'),\n"
    "    reason='calibracion A2-linaje')\n"
)

CERROJO = (REPO / ".git") if (REPO / ".git").is_dir() else None
RUTA_CERROJO = ((REPO / ".git" / "s9k-calibra-a2-linaje.lock") if CERROJO
                else Path(tempfile.gettempdir()) / "s9k-calibra-a2-linaje.lock")


def sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def toma_cerrojo():
    f = open(RUTA_CERROJO, "w")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                          text=True, timeout=180)


def limpia_creados() -> None:
    for f in CREADOS:
        if f.exists():
            f.unlink()
        # Si un caso lo dejo en el indice de Git, tambien se saca de ahi: el
        # arbol tiene que volver EXACTAMENTE a como estaba.
        _git("rm", "--cached", "--force", "--quiet",
             str(f.relative_to(REPO)))


def _texto_de_test_nuevo(nombre: str) -> str:
    return (
        '"""Modulo creado por `calibra_a2_linaje.py`. Se borra al terminar."""\n'
        "from __future__ import annotations\n"
        "\n"
        "\n"
        f"def test_{nombre}_uno():\n"
        "    assert True\n"
        "\n"
        "\n"
        f"def test_{nombre}_dos():\n"
        "    assert True\n"
    )


# --------------------------------------------------------------------------
# Mutaciones
# --------------------------------------------------------------------------

def m_nuevo_condicional() -> None:
    NUEVO_CONDICIONAL.write_text(
        _texto_de_test_nuevo("nace_condicional") + CONDICION, encoding="utf-8")


def m_nuevo_obligatorio() -> None:
    NUEVO_OBLIGATORIO.write_text(
        _texto_de_test_nuevo("nace_obligatorio"), encoding="utf-8")


def m_apaga_obligatorio() -> None:
    OBLIGATORIO.write_text(
        OBLIGATORIO.read_text(encoding="utf-8") + CONDICION, encoding="utf-8")


def m_apaga_critico() -> None:
    CRITICO.write_text(
        CRITICO.read_text(encoding="utf-8") + CONDICION, encoding="utf-8")


def m_condicional_sigue_condicional() -> None:
    """Se toca el modulo condicional SIN tocar su condicion."""
    CONDICIONAL.write_text(
        CONDICIONAL.read_text(encoding="utf-8")
        + "\n# comentario inyectado por la calibracion A2-linaje\n",
        encoding="utf-8")


def m_condicional_pasa_a_obligatorio() -> None:
    """Se le QUITA la condicion de modulo: endurecimiento, no apagado."""
    texto = CONDICIONAL.read_text(encoding="utf-8")
    viejo = ('pytestmark = pytest.mark.skipif(\n'
             '    shutil.which("git") is None, reason="git no disponible"\n'
             ')\n')
    assert texto.count(viejo) == 1, "la condicion del modulo cambio de forma"
    CONDICIONAL.write_text(texto.replace(viejo, ""), encoding="utf-8")


def m_borra_obligatorio() -> None:
    OBLIGATORIO.unlink()


def _declara_baja(rel: str) -> None:
    BAJAS.write_text(
        BAJAS.read_text(encoding="utf-8")
        + f"\n# inyectado por la calibracion A2-linaje\n{rel}\n",
        encoding="utf-8")


def m_renombra_y_apaga(seguido: bool) -> None:
    """El ataque: renombrar un obligatorio y estrenarle una condicion.

    `seguido=True` reproduce el camino normal (Git ve el rename porque el
    fichero nuevo esta en el indice). `seguido=False` es el camino que Git NO
    ve -fichero sin seguir- y que solo cierra la identidad logica por AST.

    En los dos casos la baja del modulo VIEJO se declara: asi el trinquete C
    queda satisfecho y el unico rojo que puede quedar es el de A2.
    """
    texto = OBLIGATORIO.read_text(encoding="utf-8")
    OBLIGATORIO.unlink()
    RENOMBRADO.write_text(texto + CONDICION, encoding="utf-8")
    if seguido:
        _git("add", "--intent-to-add", str(RENOMBRADO.relative_to(REPO)))
    _declara_baja(OBLIGATORIO.relative_to(REPO).as_posix())


def m_renombra_y_apaga_seguido() -> None:
    m_renombra_y_apaga(True)


def m_renombra_y_apaga_sin_seguir() -> None:
    m_renombra_y_apaga(False)


# --------------------------------------------------------------------------
# Casos
# --------------------------------------------------------------------------
# NOTA, y es un DEFECTO AJENO que se declara sin arreglarlo: estas dos no son
# `lambda` a proposito. `check_ci_config.comprueba_nombres_definidos()` recorre
# los `.py` de `.github/scripts/` y su `_nodos_propios()` hace
# `list(nodo.body)`; en un `ast.Lambda` `body` es UNA expresion, no una lista,
# asi que `list()` revienta con `TypeError: 'Call' object is not iterable`
# ANTES de llegar a la guardia `if not isinstance(cuerpo, list)` que hay justo
# debajo y que existe para eso. Medido: con `lambda` aqui, `check_ci_config.py`
# muere y TODA fila de `calibra_gate_integrity.py` que espera VERDE sale ROJA.
# No habia ningun `lambda` en ese directorio, asi que el defecto estaba latente.
# El dueño de ese fichero es otro cambio; aqui solo se evita pisarlo.
# (titulo, mutacion, ablacion, esperado, fragmento que TIENE que salir)
CASOS = [
    ("1. fichero nuevo que NACE condicional",
     m_nuevo_condicional, "", VERDE, None),
    ("2. fichero nuevo OBLIGATORIO",
     m_nuevo_obligatorio, "", VERDE, None),
    ("3. obligatorio existente -> condicional (NEGATIVO sobre modulo REAL)",
     m_apaga_obligatorio, "", ROJO, "GARANTIA APAGADA"),
    ("3-CRITICO. critico existente -> condicional",
     m_apaga_critico, "", ROJO, "GARANTIA APAGADA"),
    ("3b. el mismo caso 3 con la ABLACION A puesta (aisla el rojo en A2)",
     m_apaga_obligatorio, "A", VERDE, None),
    ("4. condicional existente -> sigue condicional",
     m_condicional_sigue_condicional, "", VERDE, None),
    ("5. condicional existente -> OBLIGATORIO (endurecimiento)",
     m_condicional_pasa_a_obligatorio, "", VERDE, None),
    ("6. obligatorio existente ELIMINADO",
     m_borra_obligatorio, "", ROJO, "BORRADO DE SUITE"),
    ("7. obligatorio RENOMBRADO + condicional, con la baja YA declarada",
     m_renombra_y_apaga_seguido, "", ROJO, "GARANTIA APAGADA"),
    ("7b. lo mismo con el fichero nuevo SIN SEGUIR por Git",
     m_renombra_y_apaga_sin_seguir, "", ROJO, "GARANTIA APAGADA"),
    ("8. control positivo restaurado", None, "", VERDE, None),
]


def main() -> int:
    base = _git("merge-base", "HEAD", "origin/main").stdout.strip()
    if not base:
        print("ERROR: no hay merge-base con origin/main; sin commit base no hay "
              "linaje que calibrar.")
        return 1
    cabecera = _git("rev-parse", "HEAD").stdout.strip()
    rama = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    print(f"repo   : {REPO}")
    print(f"rama   : {rama}")
    print(f"HEAD   : {cabecera}")
    print(f"BASE   : {base}   (merge-base con origin/main)")

    cerrojo = toma_cerrojo()
    print(f"(cerrojo tomado: {RUTA_CERROJO}; este script MUTA Y BORRA ficheros "
          f"de test en el sitio, no lo ejecutes en paralelo con nada)")

    respaldo = {f: f.read_bytes() for f in TOCABLES}
    hashes = {f: sha(d) for f, d in respaldo.items()}
    print("\nSHA-256 de los ficheros tocables ANTES de calibrar:")
    for f, h in hashes.items():
        print(f"  {h}  {f.relative_to(REPO)}")

    filas, fallos = [], 0
    try:
        for titulo, mutacion, ablacion, esperado, fragmento in CASOS:
            for f, datos in respaldo.items():
                f.write_bytes(datos)
            limpia_creados()
            print(f"\n########## {titulo}  (esperado: {esperado})")
            if mutacion is not None:
                mutacion()
            rc, salida = arnes_comun.ejecuta_gate(
                "check_suite_inventory", [], ablacion=ablacion,
                entorno={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                timeout=3600)
            obtenido = VERDE if rc == 0 else ROJO
            print("\n".join(salida.splitlines()[-18:]))
            print(f"RC={rc}  ->  {obtenido}")
            ok = obtenido == esperado
            diagnostico = "n/a"
            if fragmento is not None:
                # VEREDICTO Y DIAGNOSTICO SON DOS COSAS. Un rojo por la razon
                # equivocada se lee igual que uno legitimo, asi que aqui se
                # comprueba que el error que sale es EL DE ESTE CASO.
                acierta = any(fragmento in l and l.startswith("::error::")
                              for l in salida.splitlines())
                diagnostico = "OK" if acierta else f"**NO SALE `{fragmento}`**"
                ok = ok and acierta
            fallos += 0 if ok else 1
            motivo = "sin errores"
            for linea in salida.splitlines():
                if linea.startswith("::error::"):
                    motivo = linea[len("::error::"):].strip().replace("|", "/")[:100]
                    break
            filas.append((titulo, esperado, rc, obtenido, diagnostico,
                          "OK" if ok else "**DESVIACION**", motivo))
    finally:
        for f, datos in respaldo.items():
            f.write_bytes(datos)
        limpia_creados()
        fcntl.flock(cerrojo, fcntl.LOCK_UN)
        cerrojo.close()

    print("\n===== REVERSION VERIFICADA POR SHA-256 =====")
    for f, esperado_h in hashes.items():
        real = sha(f.read_bytes())
        marca = "OK" if real == esperado_h else "**NO COINCIDE**"
        fallos += 0 if real == esperado_h else 1
        print(f"  {marca}  {real}  {f.relative_to(REPO)}")
    sobrantes = [f for f in CREADOS if f.exists()]
    if sobrantes:
        fallos += len(sobrantes)
        print(f"  **QUEDAN FICHEROS CREADOS**: {sobrantes}")
    else:
        print("  OK  ningun fichero creado por la calibracion sobrevive")

    print("\n\n===== TABLA DE CALIBRACION A2-LINAJE =====\n")
    print("| Caso | Esperado | RC | Obtenido | Diagnostico | Veredicto | Primer error |")
    print("|---|---|---|---|---|---|---|")
    for fila in filas:
        print("| {} | {} | {} | {} | {} | {} | {} |".format(*fila))

    if fallos:
        print(f"\nCALIBRACION FALLIDA: {fallos} desviacion(es)")
        return 1
    print(f"\nCALIBRACION SUPERADA: {len(filas)}/{len(filas)} casos con el "
          f"veredicto Y el diagnostico esperados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
