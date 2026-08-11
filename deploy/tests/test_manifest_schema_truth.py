"""El manifiesto no puede mentir sobre su propio esquema (carril I).

Defecto real de este repositorio, corregido aquí: `deploy/scripts/lib.sh`
escribía `"schema_versions": {"auth_db": 1, "job_store": 1}` como literal a
mano, mientras `viewer/app/auth/db.py` iba por `SCHEMA_VERSION = 3`. Además
`verify_release_identity.py` sólo comprobaba que la clave EXISTIESE
(`schema_versions_present`, no crítica), así que la mentira pasaba la
verificación.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "scripts" / "schema_versions.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sv = _load("_s9k_schema_versions", SCRIPT)
vri = _load("_s9k_verify_release_identity",
            REPO / "deploy" / "scripts" / "verify_release_identity.py")


# ---------------------------------------------------------------------------
# 1. La versión declarada se EXTRAE del código
# ---------------------------------------------------------------------------

def test_la_version_declarada_sale_del_codigo_y_es_la_real():
    versions = sv.declared_versions(REPO)
    # Se comprueba contra el módulo importado de verdad, no contra un literal.
    sys.path.insert(0, str(REPO / "viewer"))
    from app.auth import db as auth_db

    assert versions["auth_db"] == auth_db.SCHEMA_VERSION
    assert versions["auth_db"] != 1, (
        "si esto vuelve a valer 1 con el código en 3, hemos reintroducido el bug"
    )


def test_no_queda_ningun_literal_de_schema_versions_en_lib_sh():
    # Se ignoran los comentarios: el propio comentario que explica el defecto
    # cita el literal antiguo, y eso no es código que se ejecute.
    codigo = [
        linea
        for linea in (REPO / "deploy" / "scripts" / "lib.sh")
        .read_text(encoding="utf-8").splitlines()
        if not linea.lstrip().startswith("#")
    ]
    texto = "\n".join(codigo)
    assert '"auth_db"' not in texto, (
        "el manifiesto debe DERIVAR las versiones del código, no repetirlas a mano"
    )
    assert "schema_versions.py" in texto


def test_el_rango_soportado_viaja_en_el_manifiesto():
    bloque = sv.manifest_block(REPO)
    rango = bloque["schema_supported_ranges"]["auth_db"]
    assert rango["min"] <= bloque["schema_versions"]["auth_db"] <= rango["max"]


def test_el_cli_emite_json_valido():
    out = subprocess.run([sys.executable, str(SCRIPT), str(REPO)],
                         capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    assert set(data) == {"schema_versions", "schema_supported_ranges"}


# ---------------------------------------------------------------------------
# 2. Si no se puede leer la versión, se ABORTA (no se inventa un número)
# ---------------------------------------------------------------------------

def test_sin_fuente_no_se_inventa_una_version(tmp_path):
    with pytest.raises(sv.SchemaDeclarationError):
        sv.declared_versions(tmp_path)


def test_fuente_sin_constante_no_se_inventa_una_version(tmp_path):
    destino = tmp_path / "viewer" / "app" / "auth"
    destino.mkdir(parents=True)
    (destino / "db.py").write_text("# sin SCHEMA_VERSION\n", encoding="utf-8")
    with pytest.raises(sv.SchemaDeclarationError):
        sv.declared_versions(tmp_path)


def test_el_cli_sale_con_error_si_no_puede_declarar(tmp_path):
    out = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)],
                         capture_output=True, text=True)
    assert out.returncode == 1
    assert "ERROR schema_versions" in out.stderr


# ---------------------------------------------------------------------------
# 3. El verificador detecta la divergencia declarado != real
# ---------------------------------------------------------------------------

def _facts(schema_versions):
    facts = vri.ReleaseFacts()
    facts.active_dir = str(REPO)
    facts.manifest = {"release_id": "r1", "schema_versions": schema_versions}
    return facts


def test_verificador_acepta_un_manifiesto_veraz():
    ok, detail = vri._schema_versions_match(_facts(sv.declared_versions(REPO)))
    assert ok is True, detail


def test_verificador_marca_rojo_un_manifiesto_que_miente():
    """Exactamente el estado que había en main: manifiesto 1, código 3."""
    ok, detail = vri._schema_versions_match(_facts({"auth_db": 1, "job_store": 1}))
    assert ok is False
    assert "auth_db" in detail and "manifiesto=1" in detail


def test_verificador_no_puede_comparar_es_unknown_no_ok():
    facts = vri.ReleaseFacts()
    facts.active_dir = str(REPO)
    facts.manifest = {"release_id": "r1"}  # sin schema_versions
    ok, detail = vri._schema_versions_match(facts)
    assert ok is None, "no poder comparar no es aprobar"


def test_el_indicador_es_critico_y_hunde_el_veredicto():
    indicadores = [{"indicator": "schema_versions_match_code", "ok": False,
                    "critical": True, "detail": "auth_db: manifiesto=1 código=3"}]
    veredicto = vri._verdict(indicadores)
    assert veredicto["verdict"] == vri.VERDICT_INVALID
    assert "schema_versions_match_code" in veredicto["failed_indicators"]


# ---------------------------------------------------------------------------
# 4. UNKNOWN jamás colapsa a OK
# ---------------------------------------------------------------------------

def test_un_critico_indeterminado_no_da_valido():
    """Antes `_verdict` sólo miraba `ok is False`: un crítico en None pasaba."""
    indicadores = [{"indicator": "schema_versions_match_code", "ok": None,
                    "critical": True, "detail": "no se pudo leer"}]
    veredicto = vri._verdict(indicadores)
    assert veredicto["verdict"] == vri.VERDICT_UNKNOWN
    assert "no evaluables" in veredicto.get("reason", "")


def test_un_fallo_constatado_manda_sobre_la_indeterminacion():
    indicadores = [
        {"indicator": "a", "ok": False, "critical": True, "detail": ""},
        {"indicator": "b", "ok": None, "critical": True, "detail": ""},
    ]
    assert vri._verdict(indicadores)["verdict"] == vri.VERDICT_INVALID


def test_un_no_critico_indeterminado_sigue_sin_hundir_nada():
    indicadores = [{"indicator": "c", "ok": None, "critical": False, "detail": ""}]
    assert vri._verdict(indicadores)["verdict"] == vri.VERDICT_VALID
