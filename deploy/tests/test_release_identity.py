# -*- coding: utf-8 -*-
"""Tests de verify_release_identity.py.

El fallo que motivó esta suite: con un venv por symlinks, /proc/<pid>/exe resuelve
siempre al intérprete del sistema, y el verificador antiguo lo tomaba por MISMATCH.
Aquí se fija que eso es VALID_WITH_SYSTEM_INTERPRETER_SYMLINK, sin abrir la mano a
cualquier python del sistema (ver test_interprete_del_sistema_ajeno_al_venv).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_source_fixture import (  # noqa: E402
    declared_auth_db_version,
    plant_schema_sources,
)

from verify_release_identity import (  # noqa: E402
    VERDICT_INVALID,
    VERDICT_UNKNOWN,
    VERDICT_VALID,
    VERDICT_VALID_SYMLINK,
    ProcessFacts,
    classify,
    gather_release_facts,
    verdict_exit_code,
)

RELEASE_ID = "20260716-f8b6153"
COMMIT = "f8b6153be9c4edca1efa905d1c6503ea86e261b5"
LEGACY = os.environ.get(
    "S9K_TEST_LEGACY_ROOT", "/opt/knowledge-services/s9-knowledge-repo"
)
DEFAULT_SERVICE_HOST = os.environ.get("S9K_TEST_VIEWER_HOST", "0.0.0.0")
DEFAULT_SERVICE_PORT = os.environ.get("S9K_TEST_VIEWER_PORT", "8088")


# ---------------------------------------------------------------------------
# Utillaje
# ---------------------------------------------------------------------------

def _make_release(root: Path, release_id: str = RELEASE_ID, commit: str = COMMIT,
                  copies_venv: bool = False, base_exe: str = "/usr/bin/python3.13") -> Path:
    """Crea un layout releases/<id> + current, con un venv simulado."""
    release = root / "releases" / release_id
    venv = release / "viewer" / ".venv"
    (venv / "bin").mkdir(parents=True)
    (release / "manifest.json").write_text(json.dumps({
        "release_id": release_id,
        "git_commit": commit,
        # La version que DECLARA el codigo de esta release. Antes esto era el
        # literal `{"auth_db": 1, ...}` copiado del manifiesto real, que llevaba
        # anyos mintiendo: la fixture heredaba la mentira y por eso nadie la vio.
        "schema_versions": {"auth_db": declared_auth_db_version(), "job_store": 1},
    }), encoding="utf-8")
    plant_schema_sources(release)

    if copies_venv:
        # venv --copies: el intérprete es un fichero real dentro del venv.
        (venv / "bin" / "python3").write_text("#!/bin/false\n", encoding="utf-8")
        cfg = "home = /usr/bin\n"
    else:
        # venv por symlinks: bin/python3 -> intérprete del sistema (symlink REAL,
        # porque resolverlo por error es justo el bug que se corrigió aquí).
        cfg = f"home = /usr/bin\nbase-executable = {base_exe}\n"
        if Path(base_exe).exists():
            (venv / "bin" / "python3").symlink_to(base_exe)
    (venv / "pyvenv.cfg").write_text(cfg + "include-system-site-packages = false\n",
                                     encoding="utf-8")
    (venv / "bin" / "uvicorn").write_text("#!/bin/false\n", encoding="utf-8")

    current = root / "current"
    if current.is_symlink():
        current.unlink()
    current.symlink_to(release)
    return release


def _proc(release: Path, **over) -> ProcessFacts:
    """Hechos de un proceso sano ejecutando la release; `over` los degrada."""
    venv = release / "viewer" / ".venv"
    facts = ProcessFacts(
        pid=4242,
        alive=True,
        cwd=str(release / "viewer"),
        exe="/usr/bin/python3.13",
        cmdline=[str(venv / "bin" / "uvicorn"), "app.main:app"],
        module_paths=[
            str(release / "viewer" / "app" / "main.py"),
            str(venv / "lib" / "python3.13" / "site-packages" / "_x.so"),
            "/usr/lib/x86_64-linux-gnu/libc.so.6",
        ],
        environ_file="/etc/s9-knowledge/viewer.env",
        proc_readable=True,
    )
    for k, v in over.items():
        setattr(facts, k, v)
    return facts


def _classify(root: Path, proc: ProcessFacts, **kw):
    kw.setdefault("expected_release", RELEASE_ID)
    kw.setdefault("expected_commit", COMMIT)
    kw.setdefault("legacy_root", LEGACY)
    return classify(gather_release_facts(root), proc, **kw)


def _ind(result, name):
    for i in result["indicators"]:
        if i["indicator"] == name:
            return i
    raise AssertionError(f"indicador ausente: {name}")


def _ind_unico(result, name):
    """Como `_ind`, pero exige que el indicador aparezca UNA sola vez.

    `_ind` es first-match: colar un homonimo benigno DELANTE del indicador real
    lo ensombrece y una prueba de enchufe escrita sobre `_ind` sigue verde
    (observacion N-2 de la revision). `_verdict` recorre TODOS los indicadores,
    asi que un duplicado no es un detalle de utillaje: es un estado en el que
    esta funcion deja de hablar del indicador que decide el veredicto.
    """
    encontrados = [i for i in result["indicators"] if i["indicator"] == name]
    if not encontrados:
        raise AssertionError(f"indicador ausente: {name}")
    if len(encontrados) > 1:
        raise AssertionError(
            f"indicador duplicado: {name} aparece {len(encontrados)} veces; "
            f"el primero puede ensombrecer al que decide el veredicto"
        )
    return encontrados[0]


# ---------------------------------------------------------------------------
# El falso fallo que motiva el hotfix
# ---------------------------------------------------------------------------

def test_venv_con_symlinks_es_valido(tmp_path):
    """EL CASO REAL DE RC2: exe=/usr/bin/python3.13 y aun así la identidad es buena."""
    release = _make_release(tmp_path)
    r = _classify(tmp_path, _proc(release))
    assert r["verdict"] == VERDICT_VALID_SYMLINK
    assert r["failed_indicators"] == []
    assert verdict_exit_code(r["verdict"]) == 0
    assert _ind(r, "interpreter_identity")["ok"] is True


@pytest.mark.skipif(not Path("/usr/bin/python3.13").exists(),
                    reason="requiere /usr/bin/python3.13 para el symlink real")
def test_cmdline_systemd_parametrizable(tmp_path):
    """Forma systemd parametrizable; los defaults reproducen la VM105 histórica.

    cmdline[0] es un symlink al python del sistema y cmdline[1] llega por `current`.
    Resolver el binario (en vez de solo su directorio) daba un falso INVALID.
    """
    release = _make_release(tmp_path)
    venv = release / "viewer" / ".venv"
    r = _classify(tmp_path, _proc(release, cmdline=[
        str(venv / "bin" / "python3"),                       # symlink -> /usr/bin/python3.13
        str(tmp_path / "current" / "viewer" / ".venv" / "bin" / "uvicorn"),
        "app.main:app", "--host", DEFAULT_SERVICE_HOST, "--port", DEFAULT_SERVICE_PORT,
    ]))
    assert r["verdict"] == VERDICT_VALID_SYMLINK, r["failed_indicators"]


def test_venv_con_copies_es_valido_a_secas(tmp_path):
    release = _make_release(tmp_path, copies_venv=True)
    exe = str(release / "viewer" / ".venv" / "bin" / "python3")
    r = _classify(tmp_path, _proc(release, exe=exe))
    assert r["verdict"] == VERDICT_VALID
    assert verdict_exit_code(r["verdict"]) == 0


# ---------------------------------------------------------------------------
# Lo que NO debe aceptarse
# ---------------------------------------------------------------------------

def test_interprete_del_sistema_ajeno_al_venv(tmp_path):
    """La tolerancia al symlink no puede degenerar en aceptar cualquier python."""
    release = _make_release(tmp_path, base_exe="/usr/bin/python3.13")
    r = _classify(tmp_path, _proc(release, exe="/usr/local/bin/python3.9"))
    assert r["verdict"] == VERDICT_INVALID
    assert "interpreter_identity" in r["failed_indicators"]


def test_proceso_legacy(tmp_path):
    release = _make_release(tmp_path)
    r = _classify(tmp_path, _proc(
        release,
        cwd=f"{LEGACY}/viewer",
        cmdline=[f"{LEGACY}/viewer/.venv/bin/uvicorn", "app.main:app"],
        module_paths=[f"{LEGACY}/viewer/app/main.py"],
    ))
    assert r["verdict"] == VERDICT_INVALID
    assert "proc_cwd_not_legacy" in r["failed_indicators"]
    assert "modules_not_legacy" in r["failed_indicators"]


def test_current_correcto_pero_proceso_antiguo(tmp_path):
    """current ya apunta a la release nueva, pero el proceso no se reinició."""
    _make_release(tmp_path, release_id="20260101-viejo", commit="0" * 40)
    nueva = _make_release(tmp_path)  # current -> release nueva
    vieja = tmp_path / "releases" / "20260101-viejo"
    r = _classify(tmp_path, _proc(
        nueva,
        cwd=str(vieja / "viewer"),
        cmdline=[str(vieja / "viewer" / ".venv" / "bin" / "uvicorn"), "app.main:app"],
        module_paths=[str(vieja / "viewer" / "app" / "main.py")],
    ))
    assert r["verdict"] == VERDICT_INVALID
    assert "proc_cwd_under_release" in r["failed_indicators"]


def test_modulos_mezclados_entre_releases(tmp_path):
    _make_release(tmp_path, release_id="20260101-viejo", commit="0" * 40)
    nueva = _make_release(tmp_path)
    vieja = tmp_path / "releases" / "20260101-viejo"
    proc = _proc(nueva)
    proc.module_paths = proc.module_paths + [str(vieja / "viewer" / "app" / "legacy.py")]
    r = _classify(tmp_path, proc)
    assert r["verdict"] == VERDICT_INVALID
    assert "modules_not_mixed" in r["failed_indicators"]


def test_commit_incorrecto(tmp_path):
    release = _make_release(tmp_path, commit="a" * 40)
    r = _classify(tmp_path, _proc(release))
    assert r["verdict"] == VERDICT_INVALID
    assert "manifest_git_commit" in r["failed_indicators"]


def test_manifest_manipulado(tmp_path):
    release = _make_release(tmp_path)
    (release / "manifest.json").write_text('{"release_id": "otra-cosa"}', encoding="utf-8")
    r = _classify(tmp_path, _proc(release))
    assert r["verdict"] == VERDICT_INVALID
    assert "manifest_release_id" in r["failed_indicators"]


def test_manifest_ilegible(tmp_path):
    release = _make_release(tmp_path)
    (release / "manifest.json").write_text("{ esto no es json", encoding="utf-8")
    r = _classify(tmp_path, _proc(release))
    assert r["verdict"] == VERDICT_INVALID
    assert "manifest_present" in r["failed_indicators"]


def test_entrypoint_fuera_del_venv(tmp_path):
    release = _make_release(tmp_path)
    r = _classify(tmp_path, _proc(release, cmdline=["/usr/bin/uvicorn", "app.main:app"]))
    assert r["verdict"] == VERDICT_INVALID
    assert "cmdline_entrypoint_in_venv" in r["failed_indicators"]


# ---------------------------------------------------------------------------
# Indeterminación (no es lo mismo que fallo)
# ---------------------------------------------------------------------------

def test_pid_inexistente_es_unknown(tmp_path):
    release = _make_release(tmp_path)
    r = _classify(tmp_path, _proc(release, alive=False, pid=999999))
    assert r["verdict"] == VERDICT_UNKNOWN
    assert verdict_exit_code(r["verdict"]) == 2


def test_proc_sin_permisos_es_unknown(tmp_path):
    """Sin permisos no se puede afirmar identidad: UNKNOWN, nunca VALID."""
    release = _make_release(tmp_path)
    r = _classify(tmp_path, _proc(release, proc_readable=False, cwd=None, exe=None))
    assert r["verdict"] == VERDICT_UNKNOWN
    assert verdict_exit_code(r["verdict"]) == 2


def test_fallo_constatado_gana_a_la_indeterminacion(tmp_path):
    """current apunta a otra release Y el proceso no se ve: eso es INVALID.

    Devolver UNKNOWN aqui seria mentir por omision: el fallo ya esta probado.
    """
    _make_release(tmp_path)
    r = _classify(tmp_path, ProcessFacts(pid=None, alive=False),
                  expected_release="otra-release-distinta")
    assert r["verdict"] == VERDICT_INVALID
    assert "active_is_expected_release" in r["failed_indicators"]


def test_current_ausente_es_invalid(tmp_path):
    (tmp_path / "releases").mkdir(parents=True)
    r = _classify(tmp_path, ProcessFacts(pid=1, alive=True))
    assert r["verdict"] == VERDICT_INVALID
    assert "current_resolves" in r["failed_indicators"]


# ---------------------------------------------------------------------------
# Detalles finos
# ---------------------------------------------------------------------------

def test_release_hermana_con_prefijo_comun_no_confunde(tmp_path):
    """`X-old` no debe contar como "dentro de" `X`: la comparación es por componentes."""
    release = _make_release(tmp_path)
    hermana = str(release) + "-old"
    r = _classify(tmp_path, _proc(release, cwd=hermana + "/viewer"))
    assert r["verdict"] == VERDICT_INVALID
    assert "proc_cwd_under_release" in r["failed_indicators"]


def test_commit_truncado_se_acepta(tmp_path):
    """El encargo circula con el sha a 34 caracteres; es un prefijo, no otro commit."""
    release = _make_release(tmp_path)
    r = _classify(tmp_path, _proc(release), expected_commit=COMMIT[:34])
    assert r["verdict"] == VERDICT_VALID_SYMLINK


def test_environment_file_incorrecto_no_invalida(tmp_path):
    """Informativo: se reporta, pero no tumba la identidad del proceso."""
    release = _make_release(tmp_path)
    r = _classify(tmp_path, _proc(release, environ_file="/otro/sitio.env"))
    assert r["verdict"] == VERDICT_VALID_SYMLINK
    assert _ind(r, "environment_file")["ok"] is False


@pytest.mark.parametrize("verdict,code", [
    (VERDICT_VALID, 0), (VERDICT_VALID_SYMLINK, 0),
    (VERDICT_INVALID, 1), (VERDICT_UNKNOWN, 2),
])
def test_codigos_de_salida(verdict, code):
    assert verdict_exit_code(verdict) == code


# ---------------------------------------------------------------------------
# Hallazgos de la auditoria independiente del PR #28
# ---------------------------------------------------------------------------

def test_pyvenv_cfg_falsificado_no_da_valid(tmp_path):
    """El pyvenv.cfg NO esta cubierto por el checksum (.venv esta excluido).

    Quien pueda escribir en la release puede declarar `base-executable` a un
    binario propio SIN alterar el hash. Aceptar esa base a ciegas convertia el
    verificador en un sello de goma.
    """
    release = _make_release(tmp_path, base_exe="/tmp/evil/python")
    r = _classify(tmp_path, _proc(release, exe="/tmp/evil/python"))
    assert r["verdict"] == VERDICT_INVALID
    assert "interpreter_identity" in r["failed_indicators"]
    assert "confianza" in _ind(r, "interpreter_identity")["detail"]


def test_base_dentro_de_la_release_no_da_valid(tmp_path):
    """Un 'interprete del sistema' que vive dentro de la release no es tal."""
    release = _make_release(tmp_path)
    colado = str(release / "viewer" / "python-colado")
    release_facts = gather_release_facts(tmp_path)
    release_facts.venv_base_interpreter = colado
    r = classify(release_facts, _proc(release, exe=colado),
                 expected_release=RELEASE_ID, expected_commit=COMMIT)
    assert r["verdict"] == VERDICT_INVALID
    assert "interpreter_identity" in r["failed_indicators"]


def test_base_en_prefijo_del_sistema_sigue_siendo_valida(tmp_path):
    """El endurecimiento no puede romper el caso legitimo de RC2."""
    release = _make_release(tmp_path, base_exe="/usr/bin/python3.13")
    r = _classify(tmp_path, _proc(release, exe="/usr/bin/python3.13"))
    assert r["verdict"] == VERDICT_VALID_SYMLINK, r["failed_indicators"]


# ---------------------------------------------------------------------------
# El CABLEADO del indicador de esquema dentro de `classify()`
#
# Observacion O-2 de la revision: las pruebas de `_schema_versions_match` y de
# `_verdict` cubrian las dos piezas por separado, pero NADA fijaba que la pieza
# estuviera ENCHUFADA en `classify()` ni que lo estuviera como CRITICA. Se podia
# borrar el `add("schema_versions_match_code", ...)` entero, o degradarlo a
# `critical=False`, y la bateria seguia verde: una barrera que deja de evaluarse
# sin que nada se ponga rojo, que es justo el defecto que persigue este carril.
#
# Estas cuatro pruebas atacan el CABLEADO, no la funcion.
# ---------------------------------------------------------------------------

def test_el_indicador_de_esquema_esta_enchufado_y_es_critico(tmp_path):
    """Existe en la salida de `classify()` y es CRITICO.

    Borrarlo, o degradarlo a `critical=False`, pone esta prueba en rojo por si
    sola, sin depender de ningun veredicto.
    """
    release = _make_release(tmp_path)
    r = _classify(tmp_path, _proc(release))
    indicador = _ind_unico(r, "schema_versions_match_code")  # ausente/duplicado -> AssertionError
    assert indicador["critical"] is True, (
        "degradado a no critico: podria fallar sin invalidar la release"
    )
    assert indicador["ok"] is True, indicador["detail"]


def test_un_manifiesto_que_miente_invalida_la_release_entera(tmp_path):
    """El estado exacto que habia en main: manifiesto `auth_db: 1`, codigo v3.

    No basta con que la funcion devuelva False: el VEREDICTO de la release tiene
    que hundirse, porque es lo que decide si un despliegue sigue o aborta.
    """
    release = _make_release(tmp_path)
    manifiesto = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    manifiesto["schema_versions"] = {"auth_db": 1, "job_store": 1}
    (release / "manifest.json").write_text(json.dumps(manifiesto), encoding="utf-8")

    r = _classify(tmp_path, _proc(release))
    assert r["verdict"] == VERDICT_INVALID
    assert "schema_versions_match_code" in r["failed_indicators"]


def test_una_release_sin_los_fuentes_no_se_puede_comparar_y_queda_unknown(tmp_path):
    """No poder comprobarlo no es aprobarlo: UNKNOWN, nunca VALID."""
    release = _make_release(tmp_path)
    (release / "viewer" / "app" / "auth" / "db.py").unlink()

    r = _classify(tmp_path, _proc(release))
    assert r["verdict"] == VERDICT_UNKNOWN, r["failed_indicators"]
    assert _ind_unico(r, "schema_versions_match_code")["ok"] is None


def test_un_manifiesto_sin_schema_versions_no_pasa_por_valido(tmp_path):
    """Tercera formulacion: la clave ni siquiera esta en el manifiesto."""
    release = _make_release(tmp_path)
    manifiesto = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    del manifiesto["schema_versions"]
    (release / "manifest.json").write_text(json.dumps(manifiesto), encoding="utf-8")

    r = _classify(tmp_path, _proc(release))
    assert r["verdict"] == VERDICT_UNKNOWN, r["failed_indicators"]
