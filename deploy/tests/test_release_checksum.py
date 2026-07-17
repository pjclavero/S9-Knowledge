# -*- coding: utf-8 -*-
"""
Tests del checksum de contenido de release (deploy/scripts/lib.sh).

Invariante que se protege: el checksum representa SOLO contenido inmutable de la
release. Ejecutar la aplicación (que escribe bytecode) o pasar los tests no puede
invalidarlo; en cambio, cualquier cambio real de contenido sí debe detectarse.
"""
from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_SH = REPO_ROOT / "deploy" / "scripts" / "lib.sh"


def checksum(release_dir: Path) -> str:
    """Invoca release_files_checksum a través de bash, como en producción."""
    script = 'set -Eeuo pipefail; source "%s"; release_files_checksum "%s"' % (
        LIB_SH, release_dir
    )
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    )
    value = out.stdout.strip()
    assert value.startswith("sha256:"), "salida inesperada: %r" % value
    return value


def file_list(release_dir: Path) -> list[str]:
    script = 'set -Eeuo pipefail; source "%s"; _checksum_file_list "%s" | tr "\\0" "\\n"' % (
        LIB_SH, release_dir
    )
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


@pytest.fixture()
def release(tmp_path: Path) -> Path:
    """Una release mínima pero realista."""
    d = tmp_path / "20260101-abc1234"
    (d / "viewer" / "app").mkdir(parents=True)
    (d / "viewer" / "templates").mkdir(parents=True)
    (d / "viewer" / "static").mkdir(parents=True)
    (d / "viewer" / "systemd").mkdir(parents=True)
    (d / "deploy" / "scripts").mkdir(parents=True)

    (d / "viewer" / "app" / "__init__.py").write_text("")
    (d / "viewer" / "app" / "main.py").write_text(
        textwrap.dedent(
            """
            VALUE = "produccion"

            def suma(a, b):
                return a + b
            """
        )
    )
    (d / "viewer" / "templates" / "login.html").write_text("<form>login</form>\n")
    (d / "viewer" / "static" / "app.css").write_text("body { margin: 0 }\n")
    (d / "viewer" / "systemd" / "s9-knowledge-viewer.service").write_text(
        "[Service]\nExecStart=/opt/s9-knowledge/current/viewer/.venv/bin/uvicorn\n"
    )
    (d / "deploy" / "scripts" / "deploy.sh").write_text("#!/usr/bin/env bash\n")
    (d / "manifest.json").write_text('{"files_checksum": "sha256:placeholder"}\n')

    # venv: contenido volátil que jamás debe entrar en el checksum
    venv = d / "viewer" / ".venv" / "lib" / "python3.13" / "site-packages"
    venv.mkdir(parents=True)
    (venv / "fastapi.py").write_text("# dependencia\n")
    return d


# ---------------------------------------------------------------------------
# Estabilidad frente a artefactos derivados
# ---------------------------------------------------------------------------

def test_bytecode_no_altera_checksum(release: Path) -> None:
    """El fallo real de RC2: importar módulos generaba .pyc y rompía el checksum."""
    before = checksum(release)

    pycache = release / "viewer" / "app" / "__pycache__"
    pycache.mkdir()
    (pycache / "main.cpython-313.pyc").write_bytes(b"\x00bytecode arbitrario")
    (pycache / "__init__.cpython-313.pyc").write_bytes(b"\x00mas bytecode")

    assert checksum(release) == before


def test_import_real_de_python_no_altera_checksum(release: Path) -> None:
    """Importar de verdad (no simulado) tampoco puede mover el checksum."""
    before = checksum(release)
    subprocess.run(
        ["python3", "-c", "import main"],
        cwd=release / "viewer" / "app",
        check=True,
        capture_output=True,
    )
    assert list((release / "viewer" / "app" / "__pycache__").glob("*.pyc")), (
        "el import no generó bytecode; el test no estaría probando nada"
    )
    assert checksum(release) == before


def test_pytest_cache_no_altera_checksum(release: Path) -> None:
    before = checksum(release)
    for name in (".pytest_cache", ".mypy_cache", ".ruff_cache"):
        cache = release / name
        cache.mkdir()
        (cache / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172\n")
    assert checksum(release) == before


def test_logs_temporales_y_cobertura_no_alteran_checksum(release: Path) -> None:
    before = checksum(release)
    (release / "viewer" / "app.log").write_text("2026-01-01 arranque\n")
    (release / "viewer" / "app" / "salida.tmp").write_text("temporal\n")
    (release / ".coverage").write_text("datos de cobertura\n")
    (release / "coverage.xml").write_text("<coverage/>\n")
    assert checksum(release) == before


def test_venv_no_entra_en_el_checksum(release: Path) -> None:
    before = checksum(release)
    site = release / "viewer" / ".venv" / "lib" / "python3.13" / "site-packages"
    (site / "fastapi.py").write_text("# dependencia ACTUALIZADA\n")
    (site / "otra_dependencia.py").write_text("# nueva\n")
    assert checksum(release) == before


def test_manifest_no_se_incluye_a_si_mismo(release: Path) -> None:
    """Autorreferencia: el manifiesto contiene el checksum, no puede computarlo."""
    before = checksum(release)
    (release / "manifest.json").write_text('{"files_checksum": "sha256:otro"}\n')
    assert checksum(release) == before


# ---------------------------------------------------------------------------
# Sensibilidad al contenido real
# ---------------------------------------------------------------------------

def test_cambio_de_codigo_cambia_checksum(release: Path) -> None:
    before = checksum(release)
    (release / "viewer" / "app" / "main.py").write_text("VALUE = 'alterado'\n")
    assert checksum(release) != before


def test_cambio_de_template_cambia_checksum(release: Path) -> None:
    before = checksum(release)
    (release / "viewer" / "templates" / "login.html").write_text(
        "<form action='http://atacante'>login</form>\n"
    )
    assert checksum(release) != before


def test_cambio_de_static_cambia_checksum(release: Path) -> None:
    before = checksum(release)
    (release / "viewer" / "static" / "app.css").write_text("body { margin: 1px }\n")
    assert checksum(release) != before


def test_cambio_de_unidad_systemd_cambia_checksum(release: Path) -> None:
    before = checksum(release)
    (release / "viewer" / "systemd" / "s9-knowledge-viewer.service").write_text(
        "[Service]\nExecStart=/opt/knowledge-services/s9-knowledge-repo/viewer/.venv/bin/uvicorn\n"
    )
    assert checksum(release) != before


def test_cambio_de_script_de_deploy_cambia_checksum(release: Path) -> None:
    before = checksum(release)
    (release / "deploy" / "scripts" / "deploy.sh").write_text("#!/usr/bin/env bash\nrm -rf /\n")
    assert checksum(release) != before


def test_fichero_desconocido_en_el_codigo_no_se_ignora(release: Path) -> None:
    """Un intruso colado entre el código debe alterar el checksum."""
    before = checksum(release)
    (release / "viewer" / "app" / "backdoor.py").write_text("import os\n")
    assert checksum(release) != before


def test_fichero_sin_extension_ni_borrado_pasan_desapercibidos(release: Path) -> None:
    before = checksum(release)
    (release / "viewer" / "app" / "NOTAS").write_text("cualquier cosa\n")
    assert checksum(release) != before

    tras_anadir = checksum(release)
    (release / "viewer" / "app" / "NOTAS").unlink()
    assert checksum(release) != tras_anadir
    assert checksum(release) == before


def test_pyc_suelto_fuera_de_pycache_se_ignora(release: Path) -> None:
    """*.pyc es derivado esté donde esté."""
    before = checksum(release)
    (release / "viewer" / "app" / "suelto.pyc").write_bytes(b"\x00bytecode")
    assert checksum(release) == before


# ---------------------------------------------------------------------------
# Estado mutable y secretos
# ---------------------------------------------------------------------------

def test_sockets_y_fifos_no_entran(release: Path) -> None:
    """Runtime: -type f los deja fuera por construcción."""
    import os

    before = checksum(release)
    os.mkfifo(release / "viewer" / "runtime.sock")
    assert checksum(release) == before


def test_la_lista_no_incluye_estado_mutable_ni_secretos(release: Path) -> None:
    (release / "viewer" / ".env").write_text("S9K_CSRF_SECRET=no-deberia-estar-aqui\n")
    listed = file_list(release)

    # El .env NO debería existir en una release; si aparece, el checksum lo delata
    # en vez de ignorarlo en silencio.
    assert any(".env" in p for p in listed), (
        "un .env colado en la release debe ser visible para el checksum"
    )
    # Pero nada derivado/volátil entra:
    assert not any("/.venv/" in p for p in listed)
    assert not any("__pycache__" in p for p in listed)
    assert not any(p.endswith("manifest.json") for p in listed)


# ---------------------------------------------------------------------------
# verify_release_checksum
# ---------------------------------------------------------------------------

def _verify(release_dir: Path) -> subprocess.CompletedProcess:
    script = 'set -Eeuo pipefail; source "%s"; verify_release_checksum "%s"' % (
        LIB_SH, release_dir
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def _write_manifest_with_real_checksum(release: Path) -> None:
    import json

    value = checksum(release)
    (release / "manifest.json").write_text(
        json.dumps({"files_checksum": value}, indent=2) + "\n"
    )


def test_verify_acepta_checksum_correcto(release: Path) -> None:
    _write_manifest_with_real_checksum(release)
    assert _verify(release).returncode == 0


def test_verify_tolera_bytecode_posterior(release: Path) -> None:
    """El escenario exacto de RC2: manifiesto emitido, luego se corren los tests."""
    _write_manifest_with_real_checksum(release)
    pycache = release / "viewer" / "app" / "__pycache__"
    pycache.mkdir()
    (pycache / "main.cpython-313.pyc").write_bytes(b"\x00bytecode")
    assert _verify(release).returncode == 0


def test_verify_rechaza_release_alterada(release: Path) -> None:
    _write_manifest_with_real_checksum(release)
    (release / "viewer" / "app" / "main.py").write_text("VALUE = 'alterado'\n")
    result = _verify(release)
    assert result.returncode == 1
    assert "NO coincide" in result.stderr


def test_verify_falla_sin_manifiesto(release: Path) -> None:
    (release / "manifest.json").unlink()
    assert _verify(release).returncode == 1


def test_verify_falla_si_el_manifiesto_no_declara_checksum(release: Path) -> None:
    (release / "manifest.json").write_text('{"release_id": "x"}\n')
    result = _verify(release)
    assert result.returncode == 1
    assert "files_checksum" in result.stderr


def test_checksum_es_reproducible_entre_ejecuciones(release: Path) -> None:
    assert checksum(release) == checksum(release) == checksum(release)


def test_generacion_y_verificacion_comparten_la_lista(release: Path) -> None:
    """Si create_manifest y verify usaran listas distintas, el checksum sería inútil."""
    script = (
        'set -Eeuo pipefail; source "%s"; '
        'create_manifest "%s" "20260101-abc1234" "deadbeef" "production" >/dev/null; '
        'verify_release_checksum "%s"'
    ) % (LIB_SH, release, release)
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_create_manifest_tolera_bytecode_generado_despues(release: Path) -> None:
    script_create = 'set -Eeuo pipefail; source "%s"; create_manifest "%s" "r" "c" "production" >/dev/null' % (
        LIB_SH, release
    )
    subprocess.run(["bash", "-c", script_create], check=True, capture_output=True)

    pycache = release / "viewer" / "app" / "__pycache__"
    pycache.mkdir()
    (pycache / "main.cpython-313.pyc").write_bytes(b"\x00bytecode")

    assert _verify(release).returncode == 0
