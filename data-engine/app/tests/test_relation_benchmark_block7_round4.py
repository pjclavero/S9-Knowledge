# -*- coding: utf-8 -*-
"""Bloque 7 - RONDA 4: cobertura REAL de los DOS bloqueantes que quedaron abiertos.

  B1  Un carril con muestra suficiente y CERO respuestas confirmadas
      (`total_responded==0`) NO puede salir PARTIAL -> APTO -> rc=0. El punto de
      contacto con el modelo es cero (envio BLOQUEADO por secreto, config
      invalida, error base, o 100% INDETERMINADAS): simetrico con
      `total_attempted==0`, va a NOT_MEASURED (fail-closed) y el proceso termina
      con rc!=0. El candado imprescindible es `responded>0` en el gate, con
      independencia de la CATEGORIA del fallo.

  B2  `--recombine-from` con un manifiesto fabricado desde ficheros PUBLICOS del
      repo (ground_truth_sha256, corpus_hashes, code_sha=HEAD) daba P=R=F1=1.0 con
      rc=0. El manifiesto solo prueba INTEGRIDAD, no AUTENTICIDAD. Sin HMAC de
      operador verificado la recombinacion es FAIL-CLOSED (rc!=0) y se marca
      AUTENTICIDAD NO VERIFICADA, salvo reconocimiento explicito del operador con
      --accept-unauthenticated-recombine (rc=0 pero con la marca visible).

MUTATION CHECKS
---------------
Cada bloqueante lleva un mutante CONSTRUIBLE (`_mata_mutante`): se aplica la
mutacion (que revierte el arreglo), se exige que la comprobacion FALLE, se
revierte y se exige que vuelva a pasar.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from relations.benchmark import cli as bench_cli  # noqa: E402
from relations.benchmark import metrics as bench_metrics  # noqa: E402
from relations.benchmark import report as bench_report  # noqa: E402
from relations.benchmark import runner as bench_runner  # noqa: E402

SAMPLE_IDS = ["src-01", "src-02"]


@pytest.fixture(scope="module")
def corpus():
    return bench_runner.load_corpus()


class _NetworkAttempt(AssertionError):
    pass


@pytest.fixture
def no_network(monkeypatch):
    attempts: list[str] = []

    def _boom(name):
        def _fn(*args, **kwargs):
            attempts.append(name)
            raise _NetworkAttempt(f"intento de red prohibido via {name}: {args!r}")
        return _fn

    monkeypatch.setattr(socket, "socket", _boom("socket.socket"))
    monkeypatch.setattr(socket, "create_connection", _boom("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", _boom("socket.getaddrinfo"))
    return attempts


def _mata_mutante(monkeypatch, aplicar, comprobar, *, mutante: str):
    """Aplica la MUTACION, exige que `comprobar` FALLE, revierte y reexige que pase."""
    comprobar()  # control: sin mutacion, el invariante se cumple
    sobrevive = True
    with monkeypatch.context() as mp:
        aplicar(mp)
        try:
            comprobar()
        except BaseException:  # noqa: BLE001 - cualquier fallo mata al mutante
            sobrevive = False
    assert not sobrevive, f"MUTANTE SUPERVIVIENTE ({mutante}): la comprobacion no lo detecta"
    comprobar()  # revertido: el invariante vuelve a cumplirse


# ===========================================================================
# BLOQUEANTE 1 - responded==0 con muestra suficiente NO da APTO/rc=0
# ===========================================================================
def _run_todo_indeterminado(corpus, monkeypatch_env=None):
    """Run END-TO-END en modo con proveedor donde el carril local lanza un error
    base inclasificable -> 100% INDETERMINADAS -> total_responded==0."""
    from external_ai.errors import ExternalAIError

    def _generico(messages):
        raise ExternalAIError("fallo generico e inclasificable")

    return bench_runner.run_benchmark(
        corpus, mode="ollama_shadow", source_ids=SAMPLE_IDS,
        local_transport=_generico, enable_providers=True)


def test_b1_health_responded_cero_no_es_evaluable(corpus):
    """Unidad: con muestra suficiente pero 0 respuestas confirmadas, el chequeo de
    salud del transporte marca `evaluable=False` (no puede emitir dictamen)."""
    monkey = pytest.MonkeyPatch()
    monkey.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    try:
        run = _run_todo_indeterminado(corpus)
    finally:
        monkey.undo()
    stats = run.provider_transport
    assert stats["total_attempted"] >= bench_runner.PROVIDER_TRANSPORT_MIN_CALLS
    assert stats["total_responded"] == 0
    assert stats["total_errors"] == 0  # indeterminado NO es transporte
    assert stats["evaluable"] is False, "responded==0 no puede ser evaluable"


def test_b1_gate_responded_cero_es_not_measured_y_sin_dictamen(corpus, monkeypatch):
    """El gate va a NOT_MEASURED (no PARTIAL) y el dictamen es SIN DICTAMEN."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    run = _run_todo_indeterminado(corpus)
    rep = bench_report.build_report(corpus, run, check_determinism=False)
    gate = rep["gates"]["provider_transport"]
    assert gate["status"] == "NOT_MEASURED"
    assert rep["verdict"].startswith("SIN DICTAMEN")
    assert rep["verdict_scope"].startswith("NO MEDIDO")
    # simetria con attempted==0: ambos declaran "NO MEDIDO" y no evaluan calidad.
    verdict, _ = bench_report.decide_verdict(rep["gates"])
    assert verdict.startswith("SIN DICTAMEN")


def test_b1_cli_rc_no_es_cero_con_responded_cero(corpus, monkeypatch, capsys):
    """END-TO-END por CLI: un run 100% INDETERMINADO en modo con proveedor termina
    con rc!=0. Antes salia PARTIAL -> APTO -> rc=0 (el vector del bloqueante 1)."""
    from external_ai.errors import ExternalAIError

    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")

    def _generico(messages):
        raise ExternalAIError("fallo generico e inclasificable")

    monkeypatch.setattr(bench_cli, "_build_providers", lambda args: (_generico, None, {}))
    rc = bench_cli.run_cli([
        "--mode=ollama_shadow", "--enable-providers",
        f"--sources={','.join(SAMPLE_IDS)}", "--no-determinism",
    ])
    assert rc == bench_cli.EXIT_BENCHMARK_ERROR
    err = capsys.readouterr().err
    assert "SIN DICTAMEN" in err and "NOT_MEASURED" in err


def test_b1_mutation_responded_no_distinguido_de_indeterminado(corpus, monkeypatch):
    """MUTANTE: se revierte el arreglo de `total_responded` de modo que las
    llamadas INDETERMINADAS vuelvan a contar como RESPONDIDAS (el bug pre-ronda-4:
    `responded = attempted - errors`, sin restar las indeterminadas). Con el
    mutante, un run 100% INDETERMINADO presenta `responded>0`, el gate baja a
    PARTIAL y el dictamen deja de ser SIN DICTAMEN: el candado `responded>0`
    desaparece y el test cae."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    _real = bench_metrics.provider_transport_errors

    def comprobar():
        run = _run_todo_indeterminado(corpus)
        rep = bench_report.build_report(corpus, run, check_determinism=False)
        assert rep["gates"]["provider_transport"]["status"] == "NOT_MEASURED"
        assert rep["verdict"].startswith("SIN DICTAMEN")

    def aplicar(mp):
        def _mutante(results):
            out = _real(results)
            # indeterminadas cuentan como respondidas (arreglo revertido):
            out["total_responded"] = out["total_attempted"] - out["total_errors"]
            return out
        mp.setattr(bench_metrics, "provider_transport_errors", _mutante)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="total_responded incluye las INDETERMINADAS (responded>0 anulado)")


# ===========================================================================
# BLOQUEANTE 2 - recombinacion forjada de valores publicos SIN HMAC es fail-closed
# ===========================================================================
def _forja_desde_ficheros_publicos(tmp_path, corpus, *, sources=SAMPLE_IDS,
                                   code_sha=None, hmac_key=None):
    """Fabrica un JSONL de payloads que copia el GROUND TRUTH (P=R=F1=1.0) y su
    manifiesto con SOLO datos publicos del repo. Devuelve la ruta del JSONL.

    Esto es EXACTAMENTE lo que puede hacer cualquiera con el repositorio: no hay
    ninguna llamada a proveedor, ningun secreto, nada privado."""
    import hmac as _hmac
    import hashlib as _hashlib

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
                "local": {"latency_ms": 99999, "validation_errors": []},
                "local_status": "EXECUTED", "external": None, "external_status": "NOT_EXECUTED",
            })
    forjado = tmp_path / "forjado.jsonl"
    texto = "\n".join(json.dumps(r) for r in recs) + "\n"
    forjado.write_text(texto, encoding="utf-8")

    manifest = {
        "manifest": bench_cli.PAYLOAD_MANIFEST_VERSION,
        "mode": "ensemble_offline",
        "payloads_sha256": bench_cli._sha256_bytes(texto.encode("utf-8")),
        "payloads_bytes": len(texto.encode("utf-8")),
        "records": len(recs),
        "code_sha": code_sha if code_sha is not None else bench_cli._code_sha(),
        "source_ids": list(sources),
        "ground_truth_sha256": corpus.manifest["ground_truth"]["sha256"],
        "corpus_hashes": {sid: corpus.corpus_hashes[sid] for sid in sources},
    }
    if hmac_key is not None:
        # Un atacante SIN la clave no puede calcular esto; solo el test lo usa para
        # el caso legitimo con clave de operador.
        manifest["hmac_sha256"] = bench_cli._manifest_hmac(manifest, hmac_key)
    bench_cli.manifest_path_for(forjado).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return forjado


def test_b2_reproduce_integridad_pasa_pero_metrica_es_perfecta(tmp_path, corpus,
                                                               monkeypatch, no_network):
    """Confirma que la forja es REALISTA: pasa TODAS las comprobaciones de
    integridad (sha256, corpus_hashes, ground_truth, code_sha) y produce
    P=R=F1=1.0. Es lo que hace peligroso al vector: integridad != autenticidad."""
    monkeypatch.delenv(bench_cli.MANIFEST_HMAC_KEY_ENV, raising=False)
    forjado = _forja_desde_ficheros_publicos(tmp_path, corpus)
    out = tmp_path / "rec.json"
    # Con reconocimiento explicito pasa la integridad y calcula la metrica perfecta.
    rc = bench_cli.main([f"--recombine-from={forjado}", f"--out-json={out}",
                         "--accept-unauthenticated-recombine"])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    g = data["metrics"]["global_existence"]
    assert (g["precision"], g["recall"], g["f1"]) == (1.0, 1.0, 1.0)
    assert data["authenticity_verified"] is False
    assert no_network == []


def test_b2_forjado_publico_sin_hmac_es_fail_closed(tmp_path, corpus, monkeypatch,
                                                    capsys, no_network):
    """EL BLOQUEANTE: manifiesto forjado de valores publicos, SIN HMAC y SIN
    reconocimiento -> rc!=0 y marca AUTENTICIDAD NO VERIFICADA. Antes: rc=0."""
    monkeypatch.delenv(bench_cli.MANIFEST_HMAC_KEY_ENV, raising=False)
    forjado = _forja_desde_ficheros_publicos(tmp_path, corpus)
    out = tmp_path / "rec.json"
    rc = bench_cli.run_cli([f"--recombine-from={forjado}", f"--out-json={out}"])
    assert rc == bench_cli.EXIT_BENCHMARK_ERROR, "sin autenticidad no puede ser rc=0"
    err = capsys.readouterr().err
    assert "AUTENTICIDAD NO VERIFICADA" in err
    # La salida se escribe (documenta el intento) pero se autodelata.
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["authenticity"] == "NO VERIFICADA"
    assert data["authenticity_verified"] is False
    # La metrica sigue siendo perfecta: la integridad NO detecta la forja; lo que
    # la ataja es el rc fail-closed, no las cifras.
    g = data["metrics"]["global_existence"]
    assert (g["precision"], g["recall"], g["f1"]) == (1.0, 1.0, 1.0)
    assert no_network == []


def test_b2_accept_flag_vuelve_rc0_pero_marca_no_autenticidad(tmp_path, corpus,
                                                              monkeypatch, no_network):
    """Con --accept-unauthenticated-recombine el operador reconoce el modo: rc=0,
    pero la marca AUTENTICIDAD NO VERIFICADA persiste bien visible en el JSON."""
    monkeypatch.delenv(bench_cli.MANIFEST_HMAC_KEY_ENV, raising=False)
    forjado = _forja_desde_ficheros_publicos(tmp_path, corpus)
    out = tmp_path / "rec.json"
    rc = bench_cli.main([f"--recombine-from={forjado}", f"--out-json={out}",
                         "--accept-unauthenticated-recombine"])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["authenticity"].startswith("NO VERIFICADA")
    assert "reconocida explicitamente" in data["authenticity"]
    assert data["authenticity_verified"] is False
    assert no_network == []


def test_b2_con_hmac_de_operador_autentica_y_rc0(tmp_path, corpus, monkeypatch, no_network):
    """Con la clave de operador y un HMAC valido, la autenticidad SI se verifica:
    rc=0 sin necesidad de la bandera de reconocimiento, y la marca es VERIFICADA."""
    clave = "clave-de-operador-de-test"
    monkeypatch.setenv(bench_cli.MANIFEST_HMAC_KEY_ENV, clave)
    forjado = _forja_desde_ficheros_publicos(tmp_path, corpus, hmac_key=clave)
    out = tmp_path / "rec.json"
    rc = bench_cli.main([f"--recombine-from={forjado}", f"--out-json={out}"])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["authenticity"].startswith("VERIFICADA")
    assert data["authenticity_verified"] is True
    assert no_network == []


def test_b2_hmac_definido_pero_manifiesto_sin_hmac_se_rechaza(tmp_path, corpus,
                                                             monkeypatch, no_network):
    """Con la clave definida, un manifiesto forjado SIN hmac_sha256 no puede
    autenticarse: se rechaza en bloque (no cae al modo no autenticado)."""
    clave = "clave-de-operador-de-test"
    monkeypatch.setenv(bench_cli.MANIFEST_HMAC_KEY_ENV, clave)
    forjado = _forja_desde_ficheros_publicos(tmp_path, corpus, hmac_key=None)
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_cli.main([f"--recombine-from={forjado}",
                        f"--out-json={tmp_path / 'rec.json'}"])
    assert "hmac_sha256" in str(exc.value) and "RECHAZADO" in str(exc.value)
    assert no_network == []


def test_b2_mutation_fail_closed_desactivado(tmp_path, corpus, monkeypatch):
    """MUTANTE: se revierte el fail-closed haciendo que `_load_verified_payloads`
    declare el manifiesto como HMAC VERIFICADO aunque NO haya clave de operador
    (equivale a no distinguir 'autenticado' de 'ausente'). Con el mutante el
    forjado publico vuelve a dar rc=0 y el test cae."""
    monkeypatch.delenv(bench_cli.MANIFEST_HMAC_KEY_ENV, raising=False)
    forjado = _forja_desde_ficheros_publicos(tmp_path, corpus)
    _real = bench_cli._load_verified_payloads

    def comprobar():
        rc = bench_cli.run_cli([f"--recombine-from={forjado}",
                                f"--out-json={tmp_path / 'rec.json'}"])
        assert rc == bench_cli.EXIT_BENCHMARK_ERROR

    def aplicar(mp):
        def _mutante(args):
            records, manifest, digest = _real(args)
            manifest["_hmac_status"] = "VERIFICADO (mutante: sin clave real)"
            return records, manifest, digest
        mp.setattr(bench_cli, "_load_verified_payloads", _mutante)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="_hmac_status 'VERIFICADO' sin clave de operador (fail-closed anulado)")


# ===========================================================================
# ENDURECIMIENTO (defensa en profundidad): el DEFAULT de clasificacion es
# INDETERMINATE, no RESPONDED. Solo lo que prueba contacto POSITIVO es RESPONDED.
# ===========================================================================
R = bench_metrics.CATEGORY_RESPONDED
I = bench_metrics.CATEGORY_INDETERMINATE
T = bench_metrics.CATEGORY_TRANSPORT


def test_hardening_invalid_candidate_es_indeterminate():
    """`reason_codes=['invalid_candidate']` = `RelationContractError` ANTES de
    contactar el modelo -> contacto cero -> INDETERMINATE (no RESPONDED)."""
    payload = {"reason_codes": ["invalid_candidate"],
               "validation_errors": ["Candidato invalido: algo"]}
    cat, kind = bench_metrics.classify_provider_outcome(payload)
    assert cat == I, "invalid_candidate no puede contarse como respuesta del modelo"
    assert kind == "invalid_candidate"
    # No es transporte: no debe abortar el run.
    assert bench_metrics.classify_provider_payload(payload) is None


def test_hardening_dict_vacio_y_no_dict_son_indeterminate():
    """Payloads sinteticos sin ninguna senal de contacto -> INDETERMINATE."""
    for p in ({}, {"validation_errors": []}, {"reason_codes": []}, None, "x", 123):
        assert bench_metrics.classify_provider_outcome(p)[0] == I, repr(p)


def test_hardening_invalid_candidate_no_cuenta_como_responded_lleva_a_not_measured():
    """END-TO-END del candado: un carril 100% `invalid_candidate` tiene
    `total_responded==0` -> el gate va a NOT_MEASURED, NO a un APTO/rc=0."""
    results = [{"local": {"reason_codes": ["invalid_candidate"],
                          "validation_errors": ["Candidato invalido"]}}
               for _ in range(6)]
    stats = bench_metrics.provider_transport_errors(results)
    assert stats["total_attempted"] == 6
    assert stats["total_responded"] == 0, "invalid_candidate no es respuesta"
    assert stats["total_errors"] == 0, "invalid_candidate no es transporte (no aborta)"
    assert stats["total_indeterminate"] == 6
    # El gate del informe: responded==0 -> NOT_MEASURED (candado del bloqueante 1).
    gates = bench_report.evaluate_gates(
        match={}, struct=_STRUCT_VACIO, contamination={"clean": True},
        determinism={"deterministic": None}, provider_transport=stats)
    assert gates["provider_transport"]["status"] == "NOT_MEASURED"


def test_hardening_marcadores_de_calidad_conocidos_siguen_siendo_responded():
    """REGRESION: el default seguro NO se come la medicion legitima. Los marcadores
    de CALIDAD conocidos (el modelo respondio, el contenido es lo que falla) y una
    respuesta valida cronometrada SIGUEN siendo RESPONDED."""
    quality = [
        {"validation_errors": ["parse:InvalidResponseError"]},   # JSON no parseable
        {"validation_errors": ["response_too_large"]},           # respuesta enorme
        {"validation_errors": ["predicate_invalid"]},            # campo invalido
        {"validation_errors": ["offsets_do_not_match_evidence"]},  # offsets malos
        {"validation_errors": ["no_relation_extracted"]},        # sin relacion
        {"reason_codes": ["invalid_response"], "validation_errors": ["x"],
         "latency_ms": 30},                                      # HTTP 200 invalido
        {"validation_errors": ["provider_error:InvalidResponseError"]},  # calidad
        {"latency_ms": 12, "validation_status": "VALID", "validation_errors": []},  # OK local
        {"request_hash": "a", "response_hash": "b", "latency_ms": 0,
         "validation_errors": []},                               # OK external por hash
    ]
    for p in quality:
        assert bench_metrics.classify_provider_outcome(p)[0] == R, repr(p)
    # Y el transporte real SIGUE abortando (no lo relaja el default).
    assert bench_metrics.classify_provider_outcome(
        {"validation_errors": ["transport_error:HTTPError"]})[0] == T


def test_hardening_corpus_ollama_18_respondidas_siguen_siendo_responded():
    """REGRESION del corpus REAL de Ollama: 10 offsets + 7 sin relacion + 1
    evidencia fuera = 18 RESPONDIDAS cronometradas. Todas deben seguir contando
    como RESPONDED y sumar 18 (P/R/F1 no cambian porque la particion no cambia)."""
    respondidas = (
        [{"local": {"validation_errors": ["offsets_do_not_match_evidence"],
                    "latency_ms": 40, "validation_status": "INVALID"}} for _ in range(10)]
        + [{"local": {"validation_errors": ["no_relation_extracted"],
                      "latency_ms": 35, "validation_status": "INVALID"}} for _ in range(7)]
        + [{"local": {"validation_errors": ["evidence_out_of_bounds"],
                      "latency_ms": 33, "validation_status": "INVALID"}}]
    )
    stats = bench_metrics.provider_transport_errors(respondidas)
    assert stats["total_attempted"] == 18
    assert stats["total_responded"] == 18, "las 18 respuestas reales siguen siendo RESPONDED"
    assert stats["total_errors"] == 0 and stats["total_indeterminate"] == 0


def test_hardening_mutation_default_responded(monkeypatch):
    """MUTANTE: se revierte el default de INDETERMINATE a RESPONDED (el hueco de
    defensa en profundidad). Con el mutante, `invalid_candidate` y el dict vacio
    vuelven a contar como respondidas y el test cae."""
    _real = bench_metrics.classify_provider_outcome

    def comprobar():
        assert bench_metrics.classify_provider_outcome(
            {"reason_codes": ["invalid_candidate"],
             "validation_errors": ["Candidato invalido"]})[0] == I
        assert bench_metrics.classify_provider_outcome({})[0] == I

    def aplicar(mp):
        def _mutante(payload):
            cat, kind = _real(payload)
            # el default seguro se relaja: lo indeterminado vuelve a RESPONDED.
            if cat == I and kind in ("invalid_candidate", "sin_evidencia_de_respuesta",
                                     "no_dict"):
                return (R, None)
            return (cat, kind)
        mp.setattr(bench_metrics, "classify_provider_outcome", _mutante)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="default de clasificacion revertido a RESPONDED")


_STRUCT_VACIO = {
    "subgroups": {
        "simple_relations": {"evidence_correct": {"rate": 0.0}},
        "negated_relations": {"negation_correct": {"rate": 0.0}},
        "temporal_relations": {"temporal_correct": {"rate": 0.0}},
        "rumored_relations": {"epistemic_correct": {"rate": 0.0}},
    },
    "evidence_correct": {"rate": 0.0},
    "offsets_correct": {"rate": 0.0},
    "predicate_correct": {"rate": 0.0},
}


# ===========================================================================
# DEFECTO NVIDIA: el carril externo enviaba el placeholder 'external-model' (404)
# disfrazado de fallo de TRANSPORTE. Falta el id REAL del modelo externo.
# ===========================================================================
_REAL_EXTERNAL_MODEL = "meta/llama-3.3-70b-instruct"


class _RecordingProvider:
    """Doble de proveedor externo que REGISTRA el id de modelo que recibe."""
    provider_name = "recording"

    def __init__(self):
        self.models = []

    def _post_chat(self, model, messages):
        self.models.append(model)
        return {"choices": [{"message": {"content": '{"relations": []}'}}]}, 100


def test_nvidia_sin_external_model_aborta_como_configuracion_no_transporte(
        corpus, monkeypatch, no_network):
    """`nvidia_shadow` sin `external_model` (ni review_models) -> `BenchmarkError`
    de CONFIGURACION, ANTES de tocar transporte/proveedor. NUNCA un fallo de
    transporte 5/5 disfrazado de INFRAESTRUCTURA."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    monkeypatch.delenv("S9K_NVIDIA_REVIEW_MODELS", raising=False)
    rec = _RecordingProvider()
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_runner.run_benchmark(corpus, mode="nvidia_shadow", source_ids=["src-01"],
                                   external_provider=rec, enable_providers=True)
    msg = str(exc.value)
    assert "CONFIGURACION" in msg
    assert "external-model" in msg and "404" in msg
    assert "ANTES DE CONSTRUIR TRANSPORTE" in msg
    # No es transporte y no llego a llamar al proveedor.
    assert not isinstance(exc.value, bench_runner.ProviderTransportError)
    assert rec.models == [], "el proveedor NO debe ser invocado"
    assert no_network == []


def test_nvidia_con_external_model_llega_el_id_real_no_el_placeholder(
        corpus, monkeypatch, no_network):
    """Con `external_model` real, `_post_chat` recibe el id real y la config lo lleva;
    el placeholder 'external-model' NUNCA llega al proveedor."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    rec = _RecordingProvider()
    run = bench_runner.run_benchmark(
        corpus, mode="nvidia_shadow", source_ids=["src-01"],
        external_provider=rec, enable_providers=True,
        external_model=_REAL_EXTERNAL_MODEL)
    assert rec.models, "el proveedor deberia haber sido invocado"
    assert set(rec.models) == {_REAL_EXTERNAL_MODEL}
    assert bench_runner.PLACEHOLDER_EXTERNAL_MODEL not in rec.models
    # La config del run publica el id real, no el placeholder.
    assert run.config["external_model"] == _REAL_EXTERNAL_MODEL
    assert no_network == []


def test_nvidia_config_for_mode_thread_del_external_model():
    """Assert directo sobre la config construida: el override entra en
    `PipelineConfig.external_model`; sin override queda el placeholder por defecto."""
    cfg = bench_runner._config_for_mode("nvidia_shadow", external_model=_REAL_EXTERNAL_MODEL)
    assert cfg.external_model == _REAL_EXTERNAL_MODEL
    assert cfg.external_ai_enabled is True
    # Sin override: se conserva el default (el placeholder), que la guarda rechaza.
    cfg_def = bench_runner._config_for_mode("nvidia_shadow")
    assert cfg_def.external_model == bench_runner.PLACEHOLDER_EXTERNAL_MODEL


def test_ensemble_full_tambien_exige_external_model(corpus, monkeypatch, no_network):
    """El otro modo con IA externa (`ensemble_full`) tambien esta protegido."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    monkeypatch.delenv("S9K_NVIDIA_REVIEW_MODELS", raising=False)

    def _local(messages):
        return {"choices": [{"message": {"content": '{"relations": []}'}}]}, 10

    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_runner.run_benchmark(
            corpus, mode="ensemble_full", source_ids=["src-01"],
            local_transport=_local, external_provider=_RecordingProvider(),
            enable_providers=True)
    assert "CONFIGURACION" in str(exc.value)
    assert no_network == []


def test_ollama_shadow_no_afectado_por_la_guarda(corpus, monkeypatch, no_network):
    """Un modo SIN IA externa (`ollama_shadow`) no exige `external_model`: la guarda
    no se convierte en un rechazo universal de los modos con proveedor."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")

    def _local(messages):
        return {"choices": [{"message": {"content": '{"relations": []}'}}]}, 10

    run = bench_runner.run_benchmark(
        corpus, mode="ollama_shadow", source_ids=["src-01"],
        local_transport=_local, enable_providers=True)
    assert run.mode == "ollama_shadow"
    assert bench_runner.mode_enables_external("ollama_shadow") is False
    assert no_network == []


def test_cli_external_model_flag_llega_al_proveedor(corpus, monkeypatch, no_network):
    """END-TO-END por CLI: `--external-model` se propaga hasta `_post_chat`."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    rec = _RecordingProvider()
    monkeypatch.setattr(bench_cli, "_build_providers", lambda args: (None, rec, {}))
    rc = bench_cli.run_cli([
        "--mode=nvidia_shadow", "--enable-providers", "--sources=src-01",
        "--no-determinism", f"--external-model={_REAL_EXTERNAL_MODEL}",
    ])
    # El proveedor recibio el id real (rc puede ser !=0 por NOT_MEASURED, pero el
    # placeholder jamas llego): lo que se prueba es el threading del id.
    assert set(rec.models) == {_REAL_EXTERNAL_MODEL}
    assert bench_runner.PLACEHOLDER_EXTERNAL_MODEL not in rec.models
    assert no_network == []


def test_cli_default_external_model_desde_review_models(corpus, monkeypatch, no_network):
    """Sin `--external-model`, el CLI toma el primer id de S9K_NVIDIA_REVIEW_MODELS
    (no hardcodea ninguno)."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    monkeypatch.setenv("S9K_NVIDIA_REVIEW_MODELS", f"{_REAL_EXTERNAL_MODEL},otro/modelo")
    rec = _RecordingProvider()
    monkeypatch.setattr(bench_cli, "_build_providers", lambda args: (None, rec, {}))

    class _Args:
        mode = "nvidia_shadow"
        external_model = None
    assert bench_cli._resolve_external_model(_Args()) == _REAL_EXTERNAL_MODEL
    assert no_network == []


def test_nvidia_mutation_guarda_placeholder(corpus, monkeypatch):
    """MUTANTE: se revierte la guarda para permitir el placeholder. Con el mutante,
    `nvidia_shadow` sin `external_model` deja de abortar como configuracion (vuelve
    a colar el placeholder hacia el transporte) y el test cae."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    monkeypatch.delenv("S9K_NVIDIA_REVIEW_MODELS", raising=False)

    def comprobar():
        rec = _RecordingProvider()
        with pytest.raises(bench_runner.BenchmarkError) as exc:
            bench_runner.run_benchmark(corpus, mode="nvidia_shadow", source_ids=["src-01"],
                                       external_provider=rec, enable_providers=True)
        assert "CONFIGURACION" in str(exc.value)
        assert rec.models == []

    def aplicar(mp):
        # La guarda se relaja: acepta cualquier cosa (incluido el placeholder).
        mp.setattr(bench_runner, "require_external_model", lambda mode, em: None)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="require_external_model permite el placeholder 'external-model'")
