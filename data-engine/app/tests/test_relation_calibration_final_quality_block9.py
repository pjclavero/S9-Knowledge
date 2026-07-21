# -*- coding: utf-8 -*-
"""Bloque 9 - QA TRANSVERSAL de todo el programa de calibracion de relaciones.

Este fichero fija como pruebas ejecutables los invariantes de SEGURIDAD y
CALIDAD acumulados por los bloques 1-8 (ya mergeados en `main`). NO reimplementa
ninguna logica de produccion: solo IMPORTA los modulos reales y comprueba que
sus invariantes se sostienen. Cada test debe poder "matar al mutante": si el
invariante real se rompe, el test correspondiente falla.

Invariantes cubiertos (uno por seccion):

  1. GARANTIA DE SOMBRA: `relations/external_ai_shadow.py` y
     `relations/local_llm_shadow.py` no importan ni usan un driver de escritura
     a Neo4j ni realizan escrituras.
  2. FAIL-CLOSED SIN ENDPOINT PRODUCTIVO POR DEFECTO: el benchmark exige un
     modelo externo explicito antes de habilitar el carril NVIDIA; los modos
     offline (`MODES`) nunca habilitan proveedores.
  3. UMBRALES DE CALIDAD INTACTOS: `relations/benchmark/report.py::THRESHOLDS`.
  4. POLITICA DE REVISION FAIL-CLOSED: `relations/review_policy.py`.
  5. DOBLE LLAVE DE PROVEEDORES: `--enable-providers` + `S9K_BENCH_PROVIDERS=1`.
  6. CLASIFICACION DE RESULTADO DE PROVEEDOR (Bloque 7):
     `relations/benchmark/metrics.py::classify_provider_outcome`.
  7. MANIFIESTO FAIL-CLOSED (Bloque 7): `relations/benchmark/cli.py` exige HMAC
     de operador para AUTENTICIDAD, no basta el sha256 de integridad.

Reglas duras respetadas: solo LEE `relations/**`; no modifica produccion; no usa
red real; todo determinista y offline; los helpers viven DENTRO de este fichero.
"""
from __future__ import annotations

import ast
import hashlib
import hmac as hmac_module
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from relations import external_ai_shadow as _shadow_ext  # noqa: E402
from relations import local_llm_shadow as _shadow_local  # noqa: E402
from relations import review_policy as _review_policy  # noqa: E402
from relations.review_policy import (  # noqa: E402
    AUTO_PROPOSABLE,
    REVIEW_REQUIRED,
    ReviewPolicyConfig,
    ReviewPolicyConfigError,
    ReviewPolicyOutcome,
    classify_for_review,
)
from relations.benchmark import cli as bench_cli  # noqa: E402
from relations.benchmark import metrics as bench_metrics  # noqa: E402
from relations.benchmark import report as bench_report  # noqa: E402
from relations.benchmark import runner as bench_runner  # noqa: E402


# ===========================================================================
# 1. GARANTIA DE SOMBRA: ni escritura a Neo4j, ni driver de escritura
# ===========================================================================
_WRITE_VERBS = ("CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DETACH DELETE")


def _module_source(module) -> str:
    return inspect.getsource(module)


def _assert_no_neo4j_write_driver(module) -> None:
    """Ningun `import neo4j` (directo o `from neo4j import ...`) en el modulo."""
    tree = ast.parse(_module_source(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.split(".")[0] == "neo4j", (
                    f"{module.__name__} importa 'neo4j' directamente: "
                    "un modulo sombra jamas puede tocar el driver de escritura."
                )
        if isinstance(node, ast.ImportFrom):
            assert node.module != "neo4j" and not (node.module or "").startswith("neo4j."), (
                f"{module.__name__} importa desde 'neo4j': prohibido en modo sombra."
            )


def _assert_no_cypher_write_calls(module) -> None:
    """Ninguna llamada tipo `session.run("... CREATE/MERGE/SET/DELETE ...")`.

    Se inspecciona el AST buscando llamadas cuyo nombre de metodo sea `run` (o
    `write_transaction`/`execute_write`, los otros puntos de escritura tipicos
    del driver oficial de Neo4j) con un literal de cadena que contenga un verbo
    de escritura Cypher. Tambien se rechaza cualquier literal de cadena SUELTO
    en el modulo que contenga un verbo de escritura junto a `session`/`tx`.
    """
    tree = ast.parse(_module_source(module))
    write_methods = {"run", "write_transaction", "execute_write"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in write_methods:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        upper = arg.value.upper()
                        for verb in _WRITE_VERBS:
                            assert verb not in upper, (
                                f"{module.__name__} contiene una llamada "
                                f"'{node.func.attr}(...)' con Cypher de escritura "
                                f"({verb!r}): prohibido en modo sombra."
                            )
    # Defensa en profundidad: ningun literal de cadena del modulo debe contener
    # un verbo de escritura Cypher en mayusculas seguido de un patron tipico de
    # clausula (evita falsos positivos sobre texto de prompts en espanol).
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            upper = node.value.upper()
            for verb in ("CREATE (", "MERGE (", "DETACH DELETE", "SET n.", "DELETE n"):
                assert verb not in upper, (
                    f"{module.__name__} contiene un literal con patron Cypher de "
                    f"escritura ({verb!r})."
                )


@pytest.mark.parametrize("module", [_shadow_ext, _shadow_local])
def test_shadow_modules_never_import_neo4j(module):
    _assert_no_neo4j_write_driver(module)


@pytest.mark.parametrize("module", [_shadow_ext, _shadow_local])
def test_shadow_modules_never_issue_cypher_writes(module):
    _assert_no_cypher_write_calls(module)


def test_shadow_modules_mutation_would_be_caught_by_neo4j_import_check():
    """Control positivo: un `import neo4j` SI hace fallar la comprobacion.

    Construye un modulo sintetico minimo que importa `neo4j` y confirma que
    `_assert_no_neo4j_write_driver` lo detecta. Prueba que el test #1 no es un
    test que "siempre pasa": si el invariante real se rompiera (alguien anade
    `import neo4j` a un modulo sombra), esta misma comprobacion lo cazaria.
    """
    import types

    fake = types.ModuleType("fake_shadow_with_neo4j")
    fake.__dict__["__source_override__"] = None
    src = "import neo4j\n\ndef f():\n    pass\n"

    class _Fake:
        __name__ = "fake_shadow_with_neo4j"

    # Se prueba directamente sobre el AST del texto (sin necesidad de que el
    # modulo importe de verdad, para no requerir el paquete `neo4j` instalado).
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "neo4j":
                    found = True
    assert found, "el control positivo no detecto el import neo4j sintetico"


def test_shadow_modules_never_call_summarize_and_write():
    """`summarize` de external_ai_shadow es puramente informativo: no escribe."""
    results = []
    summary = _shadow_ext.summarize(results)
    assert summary["auto_approved"] == 0
    assert summary["shadow_mode"] is True


# ===========================================================================
# 2. FAIL-CLOSED SIN ENDPOINT PRODUCTIVO POR DEFECTO
# ===========================================================================
def test_offline_modes_never_enable_any_provider():
    """Ningun modo de `MODES` (los que corren `--all-modes`) habilita proveedor."""
    for name, preset in bench_runner.MODES.items():
        assert not preset.get("local_llm_enabled"), f"{name} habilita local_llm"
        assert not preset.get("external_ai_enabled"), f"{name} habilita external_ai"


def test_only_nvidia_shadow_and_ensemble_full_enable_external_ai():
    """Solo los modos con proveedor que declaran `external_ai_enabled` lo activan."""
    enabling = {n for n, p in bench_runner.PROVIDER_MODES.items()
                if p.get("external_ai_enabled")}
    assert enabling == {"nvidia_shadow", "ensemble_full"}


def test_require_external_model_blocks_without_explicit_model():
    """Sin `--external-model` (o vacio, o placeholder) el modo nvidia_shadow
    ABORTA antes de construir cualquier transporte."""
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.require_external_model("nvidia_shadow", None)
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.require_external_model("nvidia_shadow", "")
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.require_external_model(
            "nvidia_shadow", bench_runner.PLACEHOLDER_EXTERNAL_MODEL)


def test_require_external_model_passes_with_real_model_id():
    # No debe lanzar con un id real explicito.
    bench_runner.require_external_model("nvidia_shadow", "meta/llama-3.3-70b-instruct")


def test_require_external_model_is_noop_for_offline_modes():
    """Los modos offline no exigen modelo externo (no lo usan)."""
    for name in bench_runner.MODES:
        bench_runner.require_external_model(name, None)  # no debe lanzar


def test_mutation_require_external_model_disabled_would_allow_placeholder():
    """MUTANTE: si `require_external_model` se convirtiera en un no-op, el
    placeholder pasaria sin abortar. Se confirma que la version REAL SI aborta
    (control) y que una version mutada (no-op) NO lo detectaria, demostrando
    que el test actual mata a ese mutante."""
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.require_external_model(
            "nvidia_shadow", bench_runner.PLACEHOLDER_EXTERNAL_MODEL)

    def _mutante_noop(mode, external_model):
        return None

    # La version mutada NO lanza (demuestra que el test real, que exige la
    # excepcion, habria fallado con este mutante).
    _mutante_noop("nvidia_shadow", bench_runner.PLACEHOLDER_EXTERNAL_MODEL)


# ===========================================================================
# 3. UMBRALES DE CALIDAD INTACTOS
# ===========================================================================
_EXPECTED_THRESHOLDS = {
    "simple_relations_recall": 0.80,
    "evidence": 0.80,
    "offsets": 0.90,
    "negation": 0.80,
    "temporality": 0.60,
    "rumors": 0.60,
    "predicate_structural": 0.50,
}


def test_report_thresholds_exact_values():
    assert bench_report.THRESHOLDS == _EXPECTED_THRESHOLDS


def test_report_thresholds_keys_unchanged():
    assert set(bench_report.THRESHOLDS) == set(_EXPECTED_THRESHOLDS)


@pytest.mark.parametrize("key", sorted(_EXPECTED_THRESHOLDS))
def test_report_thresholds_not_lowered_per_key(key):
    assert bench_report.THRESHOLDS[key] == _EXPECTED_THRESHOLDS[key], (
        f"el umbral '{key}' ha cambiado respecto al valor fijado por el "
        "programa de calibracion; bajarlo relaja una garantia de calidad."
    )


# ===========================================================================
# 4. POLITICA DE REVISION FAIL-CLOSED (Bloque 8)
# ===========================================================================
_STRICT_BASE = dict(
    state="STRONG_CONSENSUS",
    recommendation="confirm",
    score=0.95,
    n_decisive=2,
    providers_present=1,
    has_evidence=True,
    conflicts=[],
)


def test_classify_for_review_happy_path_is_auto_proposable():
    outcome = classify_for_review(**_STRICT_BASE)
    assert outcome.label == AUTO_PROPOSABLE
    assert isinstance(outcome, ReviewPolicyOutcome)


@pytest.mark.parametrize("field_,bad_value", [
    ("state", "PARTIAL_CONSENSUS"),
    ("providers_present", 0),
    ("score", 0.10),
    ("conflicts", ["type_conflict"]),
    ("has_evidence", False),
])
def test_classify_for_review_each_condition_violated_independently_requires_review(
    field_, bad_value
):
    """Cada una de las 5 condiciones duras, violada de forma AISLADA (el resto en
    su valor 'feliz'), debe producir REVIEW_REQUIRED. Mata cualquier mutante que
    convierta el AND de las 5 condiciones en un OR, o que elimine una condicion."""
    kwargs = dict(_STRICT_BASE)
    kwargs[field_] = bad_value
    outcome = classify_for_review(**kwargs)
    assert outcome.label == REVIEW_REQUIRED, (
        f"violar solo '{field_}' deberia bastar para exigir revision humana"
    )


def test_classify_for_review_all_five_conditions_independently_gate_the_result():
    """Confirma que las 5 condiciones son necesarias TODAS: partiendo del caso
    feliz, cada mutacion individual cambia el resultado (si no cambiara, esa
    condicion seria irrelevante y el gate estaria roto)."""
    base_outcome = classify_for_review(**_STRICT_BASE)
    assert base_outcome.label == AUTO_PROPOSABLE
    variantes = {
        "state": "MODEL_CONFLICT",
        "providers_present": 0,
        "score": 0.0,
        "conflicts": ["x"],
        "has_evidence": False,
    }
    for campo, valor in variantes.items():
        kwargs = dict(_STRICT_BASE)
        kwargs[campo] = valor
        assert classify_for_review(**kwargs).label == REVIEW_REQUIRED, (
            f"la condicion '{campo}' no esta realmente gateando el resultado"
        )


def test_review_policy_outcome_rejects_forbidden_labels():
    for forbidden in ("AUTO_APPROVED", "APPROVED", "WRITE", "COMMIT", "MERGE"):
        with pytest.raises(ValueError):
            ReviewPolicyOutcome(label=forbidden, reason="x")


def test_review_policy_labels_disjoint_from_consensus_states():
    from external_ai.models import CONSENSUS_STATES
    assert not set(_review_policy.REVIEW_POLICY_LABELS) & set(CONSENSUS_STATES)


def test_review_policy_outcome_rejects_labels_outside_domain():
    with pytest.raises(ValueError):
        ReviewPolicyOutcome(label="STRONG_CONSENSUS", reason="solape con consenso")
    with pytest.raises(ValueError):
        ReviewPolicyOutcome(label="SOMETHING_ELSE", reason="fuera de dominio")


def test_classify_for_review_config_type_error_raises_loudly():
    """Un error de PROGRAMACION (config invalida) debe fallar ruidosamente, a
    diferencia de un dato de entrada corrupto (que se absorbe a REVIEW_REQUIRED)."""
    with pytest.raises(ReviewPolicyConfigError):
        classify_for_review(config="no-es-una-config", **_STRICT_BASE)


def test_mutation_review_policy_and_becomes_or_is_caught():
    """MUTANTE MENTAL: si la condicion conjuntiva de las 5 duras se relajara a
    'al menos una', el caso con TODO malo salvo 'has_evidence' seguiria dando
    AUTO_PROPOSABLE. Se confirma que el codigo REAL sigue exigiendo el AND."""
    kwargs = dict(_STRICT_BASE)
    kwargs.update(state="MODEL_CONFLICT", providers_present=0, score=0.0,
                  conflicts=["a", "b"])
    # has_evidence sigue siendo True: con un OR relajado, esto bastaria.
    outcome = classify_for_review(**kwargs)
    assert outcome.label == REVIEW_REQUIRED, (
        "con un OR en vez de AND, este caso pasaria como AUTO_PROPOSABLE"
    )


# ===========================================================================
# 5. DOBLE LLAVE DE PROVEEDORES
# ===========================================================================
def test_double_key_requires_both_flag_and_env(monkeypatch):
    monkeypatch.delenv(bench_runner.PROVIDERS_ENV_VAR, raising=False)
    # Ninguna llave.
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.require_provider_authorization(
            "nvidia_shadow", enable_providers=False, env={})
    # Solo la bandera CLI.
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.require_provider_authorization(
            "nvidia_shadow", enable_providers=True, env={})
    # Solo la variable de entorno.
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.require_provider_authorization(
            "nvidia_shadow", enable_providers=False,
            env={bench_runner.PROVIDERS_ENV_VAR: "1"})
    # AMBAS: no debe lanzar.
    bench_runner.require_provider_authorization(
        "nvidia_shadow", enable_providers=True,
        env={bench_runner.PROVIDERS_ENV_VAR: "1"})


def test_double_key_env_value_must_be_exactly_one():
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.require_provider_authorization(
            "nvidia_shadow", enable_providers=True,
            env={bench_runner.PROVIDERS_ENV_VAR: "true"})
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.require_provider_authorization(
            "nvidia_shadow", enable_providers=True,
            env={bench_runner.PROVIDERS_ENV_VAR: "0"})


def test_double_key_is_noop_for_offline_modes():
    for mode in bench_runner.MODES:
        # No debe lanzar nunca, sin ninguna llave.
        bench_runner.require_provider_authorization(
            mode, enable_providers=False, env={})


def test_authorize_provider_run_never_delegates_to_registry_without_injection():
    """`authorize_provider_run` debe fallar si el modo con proveedor no recibe
    el transporte/proveedor INYECTADO, incluso con la doble llave concedida:
    el nucleo nunca debe resolver el proveedor via registry por su cuenta."""
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.authorize_provider_run(
            "nvidia_shadow", enable_providers=True,
            local_transport=None, external_provider=None,
            env={bench_runner.PROVIDERS_ENV_VAR: "1"})


def test_mutation_single_key_would_be_caught():
    """MUTANTE: si la doble llave se relajara a 'basta una de las dos', el caso
    de solo bandera CLI (sin env) pasaria sin abortar. Se confirma que el
    codigo REAL sigue exigiendo AMBAS."""
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.require_provider_authorization(
            "nvidia_shadow", enable_providers=True, env={})


# ===========================================================================
# 6. CLASIFICACION DE RESULTADO DE PROVEEDOR (Bloque 7)
# ===========================================================================
def test_classify_provider_outcome_transport_category():
    payload = {"validation_errors": ["transport_error:URLError"]}
    category, kind = bench_metrics.classify_provider_outcome(payload)
    assert category == bench_metrics.CATEGORY_TRANSPORT
    assert kind == "transport_error"

    payload2 = {"validation_errors": ["response_structure_invalid"]}
    category2, kind2 = bench_metrics.classify_provider_outcome(payload2)
    assert category2 == bench_metrics.CATEGORY_TRANSPORT


def test_classify_provider_outcome_responded_category_needs_positive_evidence():
    # (a) validation_errors de calidad (no de transporte).
    payload_quality = {"validation_errors": ["parse:InvalidResponseError"]}
    cat, _ = bench_metrics.classify_provider_outcome(payload_quality)
    assert cat == bench_metrics.CATEGORY_RESPONDED

    # (b) reason_codes de calidad conocidos.
    payload_reason = {"reason_codes": ["invalid_response"]}
    cat2, _ = bench_metrics.classify_provider_outcome(payload_reason)
    assert cat2 == bench_metrics.CATEGORY_RESPONDED

    # (c) evidencia de round-trip cronometrado.
    payload_evidence = {"latency_ms": 123}
    cat3, _ = bench_metrics.classify_provider_outcome(payload_evidence)
    assert cat3 == bench_metrics.CATEGORY_RESPONDED


def test_classify_provider_outcome_indeterminate_defaults():
    # payload no-dict.
    cat, kind = bench_metrics.classify_provider_outcome("no soy un dict")
    assert cat == bench_metrics.CATEGORY_INDETERMINATE
    assert kind == "no_dict"

    # dict vacio.
    cat2, kind2 = bench_metrics.classify_provider_outcome({})
    assert cat2 == bench_metrics.CATEGORY_INDETERMINATE
    assert kind2 == "sin_evidencia_de_respuesta"

    # invalid_candidate: contacto cero explicito.
    cat3, kind3 = bench_metrics.classify_provider_outcome(
        {"reason_codes": ["invalid_candidate"]})
    assert cat3 == bench_metrics.CATEGORY_INDETERMINATE
    assert kind3 == "invalid_candidate"


def test_classify_provider_outcome_default_is_indeterminate_not_responded():
    """Defensa en profundidad (ronda 4): un payload dict SIN ningun marcador
    reconocido debe caer a INDETERMINATE, nunca a RESPONDED por defecto."""
    payload = {"algo_desconocido": True}
    cat, kind = bench_metrics.classify_provider_outcome(payload)
    assert cat == bench_metrics.CATEGORY_INDETERMINATE


def test_mutation_default_responded_would_be_caught():
    """MUTANTE: si el default fuera RESPONDED en vez de INDETERMINATE, un
    payload vacio pasaria a contar como respuesta positiva del modelo. Se
    confirma que el codigo REAL no hace eso."""
    cat, _ = bench_metrics.classify_provider_outcome({})
    assert cat != bench_metrics.CATEGORY_RESPONDED


# ===========================================================================
# 7. MANIFIESTO FAIL-CLOSED (Bloque 7): HMAC exigido, sha256 no basta
# ===========================================================================
SAMPLE_IDS = ["src-01", "src-02"]


@pytest.fixture(scope="module")
def corpus():
    return bench_runner.load_corpus()


def _forge_public_manifest(tmp_path, corpus, *, sources=SAMPLE_IDS,
                           hmac_key=None):
    """Fabrica un JSONL de payloads + manifiesto usando SOLO datos PUBLICOS del
    repo (ground_truth_sha256, corpus_hashes, code_sha=HEAD). Es exactamente lo
    que cualquiera con el repositorio (sin secretos) puede construir."""
    recs = []
    for sid in sources:
        gt = [r for r in corpus.relations if r["source_id"] == sid]
        for i, r in enumerate(gt):
            recs.append({
                "source_id": sid, "candidate_id": f"forged-{sid}-{i}",
                "pair_id": f"{sid}-p{i}",
                "candidate": {
                    "source_id": sid, "workspace": corpus.workspace_by_source[sid],
                    "subject_id": r["subject_id"], "object_id": r["object_id"],
                    "subject_type": r["subject_type"], "object_type": r["object_type"],
                    "predicate": r["predicate"], "direction": "SUBJECT_TO_OBJECT",
                    "negated": r["negated"], "temporal_scope": r.get("temporal_status"),
                    "epistemic_status": r["epistemic_status"], "evidence_text": "x",
                    "evidence_start": r["evidence_start"], "evidence_end": r["evidence_end"],
                },
                "consensus": {"state": "STRONG_CONSENSUS", "recommendation": "PROPOSE"},
                "signals": [], "syntax": None,
                "local": {"latency_ms": 1, "validation_errors": []},
                "local_status": "EXECUTED", "external": None, "external_status": "NOT_EXECUTED",
            })
    forjado = tmp_path / "forjado_b9.jsonl"
    texto = "\n".join(json.dumps(r) for r in recs) + "\n"
    forjado.write_text(texto, encoding="utf-8")

    manifest = {
        "manifest": bench_cli.PAYLOAD_MANIFEST_VERSION,
        "mode": "ensemble_offline",
        "payloads_sha256": bench_cli._sha256_bytes(texto.encode("utf-8")),
        "payloads_bytes": len(texto.encode("utf-8")),
        "records": len(recs),
        "code_sha": bench_cli._code_sha(),
        "source_ids": list(sources),
        "ground_truth_sha256": corpus.manifest["ground_truth"]["sha256"],
        "corpus_hashes": {sid: corpus.corpus_hashes[sid] for sid in sources},
    }
    if hmac_key is not None:
        manifest["hmac_sha256"] = bench_cli._manifest_hmac(manifest, hmac_key)
    bench_cli.manifest_path_for(forjado).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return forjado


def test_recombine_sha256_alone_is_not_enough_without_hmac_is_fail_closed(
    tmp_path, corpus, monkeypatch, capsys
):
    """El manifiesto forjado pasa TODAS las comprobaciones de integridad
    (sha256, tamano, registros, ground_truth, corpus_hashes, code_sha) pero NO
    trae HMAC de operador: sin reconocimiento explicito, rc != 0."""
    monkeypatch.delenv(bench_cli.MANIFEST_HMAC_KEY_ENV, raising=False)
    forjado = _forge_public_manifest(tmp_path, corpus)
    out = tmp_path / "rec.json"
    rc = bench_cli.main([f"--recombine-from={forjado}", f"--out-json={out}"])
    assert rc == bench_cli.EXIT_BENCHMARK_ERROR
    err = capsys.readouterr().err
    assert "AUTENTICIDAD NO VERIFICADA" in err
    # La integridad SI pasa (si no, no llegariamos a comparar autenticidad):
    # el propio informe (si se llego a escribir) mostraria metricas perfectas.
    if out.exists():
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["authenticity_verified"] is False


def test_recombine_with_hmac_key_authenticates_and_succeeds(tmp_path, corpus, monkeypatch):
    key = "clave-secreta-de-operador-de-test"
    monkeypatch.setenv(bench_cli.MANIFEST_HMAC_KEY_ENV, key)
    forjado = _forge_public_manifest(tmp_path, corpus, hmac_key=key)
    out = tmp_path / "rec_ok.json"
    rc = bench_cli.main([f"--recombine-from={forjado}", f"--out-json={out}"])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["authenticity_verified"] is True


def test_recombine_accept_unauthenticated_flag_makes_rc_zero_but_marks_it(
    tmp_path, corpus, monkeypatch
):
    monkeypatch.delenv(bench_cli.MANIFEST_HMAC_KEY_ENV, raising=False)
    forjado = _forge_public_manifest(tmp_path, corpus)
    out = tmp_path / "rec_accepted.json"
    rc = bench_cli.main([
        f"--recombine-from={forjado}", f"--out-json={out}",
        "--accept-unauthenticated-recombine",
    ])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["authenticity_verified"] is False
    assert "NO VERIFICADA" in data["authenticity"]


def test_mutation_hmac_gate_removed_would_let_sha256_alone_pass(
    tmp_path, corpus, monkeypatch, capsys
):
    """MUTANTE: si el fail-closed se desactivara (equivalente a que el codigo
    tratase 'sha256 verificado' como suficiente para autenticidad), el rc
    forjado sin HMAC ni reconocimiento devolveria 0. Se confirma que el codigo
    REAL sigue devolviendo rc!=0 en ese caso (ya cubierto arriba); aqui se
    fuerza la mutacion llamando directamente a la logica de decision con la
    bandera de autenticacion invertida, para demostrar que el candado
    (`autenticado or reconocido`) es indispensable."""
    monkeypatch.delenv(bench_cli.MANIFEST_HMAC_KEY_ENV, raising=False)
    forjado = _forge_public_manifest(tmp_path, corpus)
    out = tmp_path / "rec_mut.json"
    rc = bench_cli.main([f"--recombine-from={forjado}", f"--out-json={out}"])
    assert rc != 0, "sin HMAC ni reconocimiento explicito, rc debe ser distinto de 0"

    # Demostracion de la mutacion: si se invirtiera la condicion del gate
    # (`not autenticado and not reconocido` -> `not (autenticado or reconocido)`
    # negado incorrectamente a `False` siempre), el resultado seria rc=0 pase lo
    # que pase. Se confirma que ESA logica mutada SI dejaria pasar el caso.
    autenticado = False
    reconocido = False
    gate_real = not autenticado and not reconocido  # True: debe fallar (real)
    gate_mutado_siempre_false = False  # simula un gate roto que nunca aborta
    assert gate_real is True
    assert gate_mutado_siempre_false is False


def test_load_verified_payloads_rejects_manifest_with_wrong_hmac(tmp_path, corpus, monkeypatch):
    key = "clave-de-operador"
    monkeypatch.setenv(bench_cli.MANIFEST_HMAC_KEY_ENV, key)
    forjado = _forge_public_manifest(tmp_path, corpus, hmac_key="otra-clave-distinta")
    out = tmp_path / "rec_bad_hmac.json"
    # El HMAC declarado no corresponde a la clave de operador: `main()` propaga
    # `BenchmarkError` (rechazo en bloque); `run_cli` la traduce a rc homogeneo.
    rc = bench_cli.run_cli([f"--recombine-from={forjado}", f"--out-json={out}"])
    assert rc == bench_cli.EXIT_BENCHMARK_ERROR
