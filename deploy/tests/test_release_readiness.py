"""Tests del kit de preparación de release (deploy/release/).

Cubren las tres afirmaciones que el kit hace y que, si dejan de ser ciertas,
convierten el gate de despliegue en teatro:

  1. El manifiesto no contradice las decisiones tomadas del proyecto
     (NO APPLY del grafo legacy, auth.db en v3).
  2. El comprobador de configuración enrojece ante una ausencia crítica y nunca
     sale con 0 cuando falla internamente.
  3. La smoke suite comprueba aislamiento, no solo códigos 200.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = REPO_ROOT / "deploy" / "release"
sys.path.insert(0, str(RELEASE_DIR))

import config_check  # noqa: E402
import generate_manifest  # noqa: E402
import spec  # noqa: E402
from spec import Level, Status  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Manifiesto
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def manifest() -> dict:
    return generate_manifest.build_manifest()


def test_manifiesto_declara_auth_db_en_v3(manifest):
    """El esquema de auth.db va por la v3; el manifiesto debe decirlo."""
    assert manifest["schema_versions"]["auth_db"] == 3


def test_version_de_esquema_se_lee_del_codigo_no_de_una_constante(manifest):
    """Si el código sube a v4, el manifiesto debe seguirlo solo."""
    db_py = (REPO_ROOT / "viewer" / "app" / "auth" / "db.py").read_text(encoding="utf-8")
    esperado = int(re.search(r"^SCHEMA_VERSION\s*=\s*(\d+)", db_py, re.M).group(1))
    assert manifest["schema_versions"]["auth_db"] == esperado


def test_migracion_de_auth_db_v3_esta_declarada_como_necesaria(manifest):
    ids = {m["id"] for m in manifest["migrations_required"]}
    assert "auth_db.v3" in ids
    v3 = next(m for m in manifest["migrations_required"] if m["id"] == "auth_db.v3")
    for columna in ("max_visible_session", "character_id"):
        assert columna in v3["description"]
    assert v3["reversible"] is False


def test_grafo_legacy_declarado_no_necesario_y_nunca_necesario(manifest):
    """NO APPLY: el manifiesto no puede pedir migrar el grafo legacy."""
    no_requeridas = {m["id"] for m in manifest["migrations_not_required"]}
    requeridas = {m["id"] for m in manifest["migrations_required"]}
    assert "graph.legacy_visibility_m5b" in no_requeridas
    assert "graph.legacy_visibility_m5b" not in requeridas

    legacy = next(m for m in manifest["migrations_not_required"]
                  if m["id"] == "graph.legacy_visibility_m5b")
    assert "NO APPLY" in legacy["rationale"]


def test_ninguna_migracion_de_grafo_es_necesaria(manifest):
    """Salvaguarda genérica: ninguna migración de Neo4j puede ser obligatoria."""
    for migracion in manifest["migrations_required"]:
        assert "Neo4j" not in migracion["component"], (
            f"{migracion['id']} exige migrar el grafo, en contra de la decisión NO APPLY"
        )


def test_las_tres_metricas_de_recuperacion_estan_separadas(manifest):
    metricas = {m["metric"]: m for m in manifest["rollback"]["recovery_metrics"]}
    assert set(metricas) == {"RPO observado", "RTO de restore", "RTO hasta servicio"}
    assert metricas["RTO de restore"]["value"] == "8,2 min"
    assert metricas["RTO de restore"]["measured"] == "sí"
    # Lo medido es la fase de restore, NO el tiempo hasta servicio.
    assert metricas["RTO hasta servicio"]["measured"] == "no"
    assert metricas["RPO observado"]["measured"] == "no"


def test_el_manifiesto_no_contiene_ningun_valor_secreto(manifest):
    """Los secretos se referencian por ruta; nunca por valor."""
    texto = json.dumps(manifest, ensure_ascii=False)
    for prohibido in ("S9K_CSRF_SECRET=", "neo4j_password=", "password\":"):
        assert prohibido not in texto
    for referencia in manifest["configuration"]["secret_references"]:
        assert referencia["path"].startswith("/")
        assert "contenido no se lee" in referencia["note"]


def test_la_ingesta_real_no_se_activa(manifest):
    assert any("S9K_ALLOW_REAL_INGEST" in objetivo
               for objetivo in manifest["explicit_non_goals"])


def test_el_generador_produce_json_valido_por_cli(tmp_path):
    destino = tmp_path / "manifest.json"
    code = generate_manifest.main(["-o", str(destino)])
    assert code == 0
    json.loads(destino.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 2. Comprobador de configuración
# ---------------------------------------------------------------------------

def _entorno_valido() -> dict[str, str]:
    import calibrate_config_check
    return calibrate_config_check.build_valid_env()


def test_entorno_completo_sale_en_ok():
    status, _ = _verdict(_entorno_valido())
    assert status is Status.OK


def _verdict(env):
    findings = config_check.check_env_vars(env, production=True)
    return config_check.verdict(findings), findings


@pytest.mark.parametrize("variable", [
    v.name for v in spec.ENV_VARS
    if v.level is Level.CRITICAL and not v.file_alternative
])
def test_una_ausencia_critica_siempre_produce_error(variable):
    """La regla que este proyecto ha pagado siete veces."""
    env = _entorno_valido()
    del env[variable]
    status, findings = _verdict(env)
    assert status is Status.ERROR, f"quitar {variable} no puso el veredicto en ERROR"
    hallazgo = next(f for f in findings if f.target == variable)
    assert hallazgo.status == Status.ERROR.value
    assert "AUSENTE" in hallazgo.message


def test_calibracion_completa_pasa():
    import calibrate_config_check
    assert calibrate_config_check.main([]) == 0


def test_fallo_interno_nunca_sale_con_codigo_cero():
    assert config_check.main(["--env-file", "/ruta/que/no/existe.env"]) == 3


def test_un_critico_en_rojo_manda_sobre_el_recuento_de_oks():
    findings = [
        config_check.Finding("env", f"OK_{i}", Status.OK.value, Level.CRITICAL.value, "ok")
        for i in range(50)
    ]
    findings.append(
        config_check.Finding("env", "MALA", Status.ERROR.value, Level.CRITICAL.value, "falta")
    )
    assert config_check.verdict(findings) is Status.ERROR


def test_el_secreto_nunca_se_imprime():
    env = _entorno_valido()
    env["S9K_CSRF_SECRET"] = "valor-secretisimo-que-no-debe-aparecer-jamas-1234"
    _, findings = _verdict(env)
    for hallazgo in findings:
        assert "valor-secretisimo" not in hallazgo.message
    csrf = next(f for f in findings if f.target == "S9K_CSRF_SECRET")
    assert csrf.status == Status.OK.value
    assert config_check.REDACTED in csrf.message


def test_placeholder_de_secreto_se_detecta_sin_mostrarlo():
    env = _entorno_valido()
    env["S9K_CSRF_SECRET"] = "s9k-csrf-change-me"
    status, findings = _verdict(env)
    assert status is Status.ERROR
    csrf = next(f for f in findings if f.target == "S9K_CSRF_SECRET")
    assert "s9k-csrf-change-me" not in csrf.message


def test_mock_en_produccion_es_error():
    env = _entorno_valido()
    env["S9K_GRAPH_PROVIDER"] = "mock"
    status, _ = _verdict(env)
    assert status is Status.ERROR


def test_estado_dentro_de_la_release_es_error():
    """auth.db bajo el árbol de la release se pierde en el siguiente despliegue."""
    env = _entorno_valido()
    env["S9K_AUTH_DB_PATH"] = "/opt/s9-knowledge/releases/abc123/viewer/state/auth.db"
    status, findings = _verdict(env)
    assert status is Status.ERROR
    hallazgo = next(f for f in findings if f.target == "S9K_AUTH_DB_PATH")
    assert "release" in hallazgo.message


def test_flag_de_ingesta_real_encendida_es_error():
    env = _entorno_valido()
    env["S9K_ALLOW_REAL_INGEST"] = "true"
    status, _ = _verdict(env)
    assert status is Status.ERROR


def test_auth_desactivada_es_error():
    env = _entorno_valido()
    env["S9K_AUTH_ENABLED"] = "false"
    status, _ = _verdict(env)
    assert status is Status.ERROR


def test_lo_no_comprobable_se_declara_como_warning_no_como_ok():
    """Sin acceso al host, ficheros y unidades no se pueden dar por buenos."""
    findings = config_check.run_checks(_entorno_valido(), production=True,
                                       check_filesystem=False, check_units=False,
                                       check_neo4j=False)
    no_comprobables = [f for f in findings
                       if "NO COMPROB" in f.message.upper()]
    assert no_comprobables, "el comprobador no declara sus propios límites"
    for hallazgo in no_comprobables:
        assert hallazgo.status != Status.OK.value


# ---------------------------------------------------------------------------
# 3. Coherencia entre la especificación y la plantilla versionada
# ---------------------------------------------------------------------------

def test_las_criticas_del_spec_coinciden_con_la_plantilla():
    """Si la plantilla y el spec divergen, uno de los dos miente."""
    plantilla = (REPO_ROOT / "deploy" / "config" / "viewer.env.example").read_text("utf-8")
    marcadas = set()
    for linea in plantilla.splitlines():
        if "[CRÍTICA]" not in linea:
            continue
        match = re.match(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=", linea)
        if match:
            marcadas.add(match.group(1))

    criticas_spec = {v.name for v in spec.ENV_VARS if v.level is Level.CRITICAL}
    # La plantilla marca bloques enteros (p.ej. las rutas de estado) con una
    # sola marca, así que se exige inclusión en el sentido comprobable: todo lo
    # marcado en la plantilla es crítico en el spec.
    assert marcadas <= criticas_spec, (
        f"marcadas [CRÍTICA] en la plantilla pero no críticas en spec.py: "
        f"{sorted(marcadas - criticas_spec)}"
    )


def test_toda_variable_del_spec_existe_en_el_codigo():
    """Ninguna variable inventada: deben leerse en config.py o auth/config.py."""
    fuentes = "\n".join(
        (REPO_ROOT / "viewer" / "app" / ruta).read_text(encoding="utf-8")
        for ruta in ("config.py", "auth/config.py", "health/runner.py", "health/storage.py")
    )
    for var in spec.ENV_VARS:
        assert var.name in fuentes, f"{var.name} no aparece en el código del visor"


def test_todo_secreto_del_spec_se_declara_como_tal():
    for var in spec.ENV_VARS:
        if "PASSWORD" in var.name or "SECRET" in var.name:
            if var.name.endswith("_FILE"):
                continue
            assert var.secret, f"{var.name} debería estar marcada como secreto"


# ---------------------------------------------------------------------------
# 4. Smoke suite
# ---------------------------------------------------------------------------

def test_la_smoke_suite_declara_el_check_de_datos_no_autorizados():
    ids = {cid for cid, _ in spec.SMOKE_CHECKS}
    assert "unauthorized_data_invisible" in ids
    import smoke_lab
    implementados = {nombre for nombre, _ in smoke_lab.CHECKS}
    assert ids == implementados, "la lista declarada y la implementada divergen"


@pytest.mark.slow
def test_la_smoke_suite_pasa_entera():
    """Se ejecuta en subproceso: monta un entorno global y purga módulos.

    Hacerlo en el mismo proceso que el resto de la suite contaminaría
    ``sys.modules`` y las cachés de settings de otros tests.
    """
    resultado = subprocess.run(
        [sys.executable, str(RELEASE_DIR / "smoke_lab.py"), "--json"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    informe = json.loads(resultado.stdout)
    assert informe["passed"] is True
    fallos = [r for r in informe["results"] if not r["passed"]]
    assert not fallos, fallos


@pytest.mark.slow
def test_el_aislamiento_entre_partidas_es_lo_que_hace_util_al_smoke():
    resultado = subprocess.run(
        [sys.executable, str(RELEASE_DIR / "smoke_lab.py"), "--json"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300,
    )
    informe = json.loads(resultado.stdout)
    check = next(r for r in informe["results"]
                 if r["check"] == "unauthorized_data_invisible")
    assert check["passed"] is True
    assert "partida:dos" in check["detail"] or "no ve" in check["detail"]
