"""Slice 2 · Corte 5 — `validate_worker_env`, y su tabla de calibración.

QUÉ GUARDA ESTE FICHERO
-----------------------
El worker que corre `ingest_v3` observa el grafo y **falla cerrado** sin
conexión declarada. `deploy/README.md` lo documenta como condición previa al
despliegue, pero una condición que sólo vive en un README **depende de que una
persona la lea**. `validate_worker_env` la convierte en una puerta, y este
fichero es lo que impide que la puerta esté pintada.

CADA FILA ROMPE UNA COSA Y EXIGE ROJO. Un validador al que no se le ha visto
en rojo no es un validador: es una función que devuelve 0.

LA FILA MÁS IMPORTANTE ES `S9K_NEO4J_PASSWORD`. El motor
(`knowledge_v3/driver_neo4j.py`) **sólo** lee `S9K_NEO4J_PASSWORD_FILE`, así
que un `worker.env` copiado de `viewer.env` funciona igual y deja el secreto en
una variable de entorno **sin que nada avise**. Ese es justo el fallo que no se
nota.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VALIDADOR = REPO / "deploy" / "scripts" / "validate_deploy.sh"
EJEMPLO = REPO / "deploy" / "config" / "worker.env.example"


def _correr(env_file: Path) -> subprocess.CompletedProcess:
    """Invoca la función real del script real. Sin reimplementarla aquí."""
    # EL rc SE CAPTURA, NO SE HEREDA. `validate_deploy.sh` trae `set -e`: al
    # hacerle `source`, un retorno distinto de 0 mata el shell ANTES del
    # `echo`, y el arnes se quedaba sin rc que leer aunque el validador hubiera
    # hecho exactamente lo correcto. MEDIDO: las cuatro filas de rojo daban
    # "el validador no llego a devolver un rc" con el stderr correcto al lado.
    guion = (
        f'. "{VALIDADOR}"; rc=0; validate_worker_env "{env_file}" || rc=$?; '
        f'echo "RC=${{rc}}"'
    )
    return subprocess.run(["bash", "-c", guion], capture_output=True, text=True)


def _rc(resultado: subprocess.CompletedProcess) -> int:
    for linea in resultado.stdout.splitlines():
        if linea.startswith("RC="):
            return int(linea[3:])
    raise AssertionError(
        f"el validador no llegó a devolver un rc.\nstdout={resultado.stdout!r}\n"
        f"stderr={resultado.stderr!r}"
    )


@pytest.fixture
def secreto(tmp_path) -> Path:
    fichero = tmp_path / "neo4j_worker_password"
    fichero.write_text("un-secreto", encoding="utf-8")
    fichero.chmod(0o600)
    return fichero


def _env(tmp_path, secreto: Path, **cambios) -> Path:
    """Un `worker.env` VÁLIDO, con los cambios que se le pidan."""
    valores = {
        "S9K_NEO4J_URI": "bolt://127.0.0.1:7687",
        "S9K_NEO4J_USER": "s9k_worker_lector",
        "S9K_NEO4J_PASSWORD_FILE": str(secreto),
    }
    valores.update(cambios)
    fichero = tmp_path / "worker.env"
    fichero.write_text(
        "".join(f"{k}={v}\n" for k, v in valores.items() if v is not None),
        encoding="utf-8",
    )
    return fichero


# ---------------------------------------------------------------------------
# C0 — el baseline. Sin esto, todas las filas de abajo podrían ser rojas por
#      una razón cualquiera y la tabla no distinguiría nada.
# ---------------------------------------------------------------------------
def test_C0_un_worker_env_correcto_pasa(tmp_path, secreto):
    resultado = _correr(_env(tmp_path, secreto))
    assert _rc(resultado) == 0, resultado.stderr


def test_ausente_AVISA_pero_no_bloquea(tmp_path):
    """AUSENTE != INVÁLIDO, y es deliberado.

    Hoy no hay ninguna unidad de worker instalada; exigir el fichero rompería
    todos los despliegues actuales. Pero callarse tampoco vale: se avisa, y el
    aviso nombra el código con el que el operador se lo encontraría.
    """
    resultado = _correr(tmp_path / "no-existe.env")
    assert _rc(resultado) == 0
    assert "GRAPH_OBSERVATION_UNCONFIGURED" in resultado.stderr, resultado.stderr


@pytest.mark.parametrize(
    "falta", ["S9K_NEO4J_URI", "S9K_NEO4J_USER", "S9K_NEO4J_PASSWORD_FILE"]
)
def test_falta_una_variable_obligatoria_BLOQUEA(tmp_path, secreto, falta):
    """Las tres, una a una. Comprobar sólo una dejaría las otras dos sin guarda."""
    resultado = _correr(_env(tmp_path, secreto, **{falta: None}))
    assert _rc(resultado) == 1, resultado.stderr
    assert falta in resultado.stderr


def test_el_secreto_en_una_VARIABLE_bloquea(tmp_path, secreto):
    """EL ERROR FÁCIL: copiar `viewer.env`.

    El visor admite las dos formas; el motor sólo la de fichero. Con las dos
    puestas el worker funciona —coge el fichero— y el secreto queda además en
    una variable que nadie usa. Sin esta fila, ese caso pasa en verde.
    """
    resultado = _correr(
        _env(tmp_path, secreto, S9K_NEO4J_PASSWORD="la-contrasena-en-claro")
    )
    assert _rc(resultado) == 1, resultado.stderr
    assert "S9K_NEO4J_PASSWORD" in resultado.stderr
    # Y NO SE IMPRIME EL VALOR. Un validador que filtra el secreto al log es
    # peor que el defecto que persigue.
    assert "la-contrasena-en-claro" not in resultado.stderr
    assert "la-contrasena-en-claro" not in resultado.stdout


def test_un_fichero_de_secreto_legible_por_todos_bloquea(tmp_path, secreto):
    """Reutiliza `validate_secret_file`, que ya existía. No se reimplanta."""
    secreto.chmod(0o644)
    resultado = _correr(_env(tmp_path, secreto))
    assert _rc(resultado) == 1, resultado.stderr


def test_un_secreto_que_no_existe_bloquea(tmp_path, secreto):
    resultado = _correr(
        _env(tmp_path, secreto, S9K_NEO4J_PASSWORD_FILE=str(tmp_path / "fantasma"))
    )
    assert _rc(resultado) == 1, resultado.stderr


# ---------------------------------------------------------------------------
# El ejemplo publicado tiene que pasar su propio validador
# ---------------------------------------------------------------------------
def test_el_ejemplo_publicado_es_coherente_con_el_validador(tmp_path, secreto):
    """Un `.example` que no pasaría la puerta manda al operador contra el muro.

    Se copia el ejemplo REAL y sólo se sustituye la ruta del secreto por una
    que existe en el árbol de pruebas: todo lo demás es lo que se publica.
    """
    assert EJEMPLO.is_file(), f"falta {EJEMPLO}"
    texto = EJEMPLO.read_text(encoding="utf-8").replace(
        "/etc/s9-knowledge/secrets/neo4j_worker_password", str(secreto)
    )
    copia = tmp_path / "worker.env"
    copia.write_text(texto, encoding="utf-8")

    resultado = _correr(copia)
    assert _rc(resultado) == 0, (
        f"el ejemplo publicado NO pasa su propio validador:\n{resultado.stderr}"
    )


def test_el_ejemplo_no_trae_el_secreto_en_una_variable():
    """La línea prohibida sólo puede aparecer COMENTADA, como contraejemplo."""
    for numero, linea in enumerate(
        EJEMPLO.read_text(encoding="utf-8").splitlines(), 1
    ):
        limpia = linea.strip()
        if limpia.startswith("#"):
            continue
        assert not limpia.startswith("S9K_NEO4J_PASSWORD="), (
            f"{EJEMPLO.name}:{numero} define el secreto en una variable"
        )
