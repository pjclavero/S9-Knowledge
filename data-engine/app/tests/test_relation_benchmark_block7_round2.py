# -*- coding: utf-8 -*-
"""Bloque 7 - RONDA 2: regresiones de los 5 bloqueantes y de los no bloqueantes.

Cubren, con dobles y SIN una sola conexion real:

  B1  la doble llave vive en el NUCLEO: `run_benchmark`/`run_source` con un modo
      con proveedor y sin inyeccion fallan CERRADO (antes abrian conexiones
      reales contra NVIDIA a traves del registry).
  B2  el umbral de salud del transporte se aplica en TODO modo con proveedor
      (antes estaba muerto en el carril externo) y el campo `network` del informe
      se deriva de las llamadas contabilizadas.
  B3  muestra por debajo del minimo => criterio ENDURECIDO; 0 llamadas => no hay
      dictamen normal, sino `verdict_scope` NO MEDIDO.
  B4  `--recombine-from` exige y verifica un manifiesto con sha256.
  B5  `normalize_local_endpoint` solo admite http/https con host y sin
      credenciales.
  N1  redirecciones entre origenes rechazadas.
  N2  lectura acotada y deadline de reloj de pared.
  N4  el determinismo no se relanza en modos con proveedor.
  N5  `build_external_provider` ya no es la identidad.
  N7  la fixture de bloqueo de red parchea tambien `socket.getaddrinfo`.
  N8  camino `nvidia_shadow` AUTORIZADO (con doble) y caso `attempted < 3`.
"""
from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from relations.benchmark import cli as bench_cli  # noqa: E402
from relations.benchmark import providers as bench_providers  # noqa: E402
from relations.benchmark import report as bench_report  # noqa: E402
from relations.benchmark import runner as bench_runner  # noqa: E402

SAMPLE_IDS = ["src-01", "src-02"]


@pytest.fixture(scope="module")
def corpus():
    return bench_runner.load_corpus()


class _NetworkAttempt(AssertionError):
    """Se lanza si el codigo bajo test intenta abrir cualquier conexion."""


@pytest.fixture
def no_network(monkeypatch):
    """Bloquea TODA apertura de red Y la resolucion DNS (N7).

    La fixture original no parcheaba `socket.getaddrinfo`: una fuga que solo
    resolviera DNS (exfiltracion por nombre, por ejemplo) no se habria detectado.
    """
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


def test_n7_la_fixture_detecta_una_fuga_de_solo_dns(no_network):
    """Meta-test: si algo resolviera DNS sin conectar, la fixture lo caza."""
    with pytest.raises(_NetworkAttempt):
        socket.getaddrinfo("integrate.api.nvidia.com", 443)
    assert no_network == ["socket.getaddrinfo"]


# ===========================================================================
# B1 - la doble llave vive en el NUCLEO, no solo en la CLI
# ===========================================================================
@pytest.mark.parametrize("mode", sorted(bench_runner.PROVIDER_MODES))
def test_b1_run_benchmark_sin_llaves_falla_cerrado(corpus, mode, monkeypatch, no_network):
    """API publica: `run_benchmark(mode='nvidia_shadow')` NO puede abrir red."""
    monkeypatch.delenv(bench_runner.PROVIDERS_ENV_VAR, raising=False)
    monkeypatch.setenv("S9K_NVIDIA_API_KEY", "nvapi-FAKE-NO-DEBE-USARSE")
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_runner.run_benchmark(corpus, mode=mode, source_ids=["src-01"])
    assert "ABORTADO ANTES DE ABRIR RED" in str(exc.value)
    assert no_network == []


@pytest.mark.parametrize("mode", sorted(bench_runner.PROVIDER_MODES))
def test_b1_run_source_sin_llaves_falla_cerrado(corpus, mode, monkeypatch, no_network):
    monkeypatch.delenv(bench_runner.PROVIDERS_ENV_VAR, raising=False)
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.run_source(corpus, "src-01", mode=mode)
    assert no_network == []


def test_b1_doble_llave_sin_inyeccion_sigue_fallando_cerrado(corpus, monkeypatch, no_network):
    """Ni siquiera con las DOS llaves se delega en el registry: hay que inyectar."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    monkeypatch.setenv("S9K_NVIDIA_API_KEY", "nvapi-FAKE-NO-DEBE-USARSE")
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_runner.run_benchmark(corpus, mode="nvidia_shadow", source_ids=["src-01"],
                                   enable_providers=True)
    assert "sin proveedor INYECTADO" in str(exc.value)
    assert no_network == []


def test_b1_build_report_con_determinismo_no_relanza_modo_proveedor(corpus, monkeypatch):
    """N4 + B1: la 2a pasada de determinismo no duplica llamadas ni miente."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    llamadas = {"n": 0}

    def _transporte(messages):
        llamadas["n"] += 1
        return {"choices": [{"message": {"content": json.dumps({"relations": []})}}]}, 11

    run = bench_runner.run_benchmark(corpus, mode="ollama_shadow", source_ids=["src-01"],
                                     local_transport=_transporte, enable_providers=True)
    n_primera = llamadas["n"]
    assert n_primera > 0
    rep = bench_report.build_report(corpus, run, check_determinism=True)
    # Ni una llamada mas, y el determinismo se declara NO EVALUADO (no False).
    assert llamadas["n"] == n_primera
    assert rep["determinism"]["deterministic"] is None
    assert rep["gates"]["determinism"]["status"] == "NOT_EVALUATED"
    assert rep["verdict"] != "NO APTO"


# ===========================================================================
# B2 / N8 - camino nvidia_shadow AUTORIZADO con doble, sin red real
# ===========================================================================
class _ProveedorExternoDoble:
    """Doble de proveedor externo: cuenta llamadas y falla SIEMPRE (transporte)."""

    provider_name = "doble"

    def __init__(self):
        self.calls = 0

    def _post_chat(self, *a, **k):
        self.calls += 1
        raise RuntimeError("proveedor externo caido (doble de test)")


def test_b2_nvidia_shadow_autorizado_no_emite_dictamen_de_calidad(corpus, monkeypatch,
                                                                 no_network):
    """El carril externo ya NO emite 'APTO ...' con el proveedor caido.

    LIMITACION HONESTA: cuando el proveedor externo falla, `pipeline._run_external`
    (FUERA DE ALCANCE) devuelve `(None, FAILED_CLOSED)`, asi que NO deja payload y
    los contadores de transporte ven `attempted == 0`: la tasa de error del carril
    externo es inobservable desde el benchmark. Por eso el criterio correcto no es
    solo la tasa, sino tambien "no se midio nada" -> `NOT_MEASURED` y SIN DICTAMEN.
    Antes, este mismo escenario producia `APTO CON REVISION HUMANA TOTAL` y rc=0.
    """
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    doble = _ProveedorExternoDoble()
    # Ronda 4: los modos externos exigen un id de modelo REAL (guarda de config).
    # El doble lo ignora; se pasa para llegar al escenario de transporte que prueba.
    run = bench_runner.run_benchmark(corpus, mode="nvidia_shadow", source_ids=SAMPLE_IDS,
                                     external_provider=doble, enable_providers=True,
                                     external_model="meta/llama-3.3-70b-instruct")
    assert doble.calls > 0, "el doble deberia haber sido invocado"
    rep = bench_report.build_report(corpus, run, check_determinism=False)
    assert rep["gates"]["provider_transport"]["status"] == "NOT_MEASURED"
    assert rep["verdict"] == "SIN DICTAMEN: PROVEEDOR NO MEDIDO"
    assert not rep["verdict"].startswith("APTO")
    assert rep["verdict_scope"].startswith("NO MEDIDO")
    assert no_network == []


def test_b2_carril_externo_caido_aborta_el_run(corpus, monkeypatch, no_network):
    """Con el error REAL del proveedor (ExternalAIError) la tasa si es observable.

    Es el escenario del PoC: `--mode nvidia_shadow` contra un endpoint que
    responde 500. Antes emitia `APTO CON REVISION HUMANA TOTAL` con rc=0 y
    `transport_error_rate=1.0`, porque `providers_injected` era False y el umbral
    nunca se evaluaba. Ahora aborta.
    """
    from external_ai.errors import ProviderServerError

    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")

    class _Caido:
        provider_name = "doble"

        def __init__(self):
            self.calls = 0

        def _post_chat(self, *a, **k):
            self.calls += 1
            raise ProviderServerError("500 simulado")

    doble = _Caido()
    with pytest.raises(bench_runner.ProviderTransportError) as exc:
        bench_runner.run_benchmark(corpus, mode="nvidia_shadow", source_ids=["src-01"],
                                   external_provider=doble, enable_providers=True,
                                   external_model="meta/llama-3.3-70b-instruct")
    assert "NO se emite dictamen" in str(exc.value)
    assert doble.calls > 0
    assert no_network == []


def test_b2_network_se_deriva_de_las_llamadas_contabilizadas(corpus, monkeypatch):
    """`network` sale de las llamadas contadas, no de si un objeto es None."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")

    def _transporte(messages):
        return {"choices": [{"message": {"content": json.dumps({"relations": []})}}]}, 7

    run = bench_runner.run_benchmark(corpus, mode="ollama_shadow", source_ids=SAMPLE_IDS,
                                     local_transport=_transporte, enable_providers=True,
                                     provider_endpoints={"local_llm": "http://127.0.0.1:11434"})
    rep = bench_report.build_report(corpus, run, check_determinism=False)
    prov = rep["providers"]
    assert prov["network_calls_counted"] == run.provider_transport["total_attempted"] > 0
    assert prov["network"].startswith("yes (")
    assert str(prov["network_calls_counted"]) in prov["network"]
    # Atestacion auditable del endpoint, sin credenciales (B5).
    assert prov["endpoints"] == {"local_llm": "http://127.0.0.1:11434"}
    # Y jamas se publica "none" cuando ha habido llamadas.
    assert not prov["network"].startswith("none")


def test_b2_no_se_publica_atestacion_falsa_si_status_y_llamadas_se_contradicen(corpus,
                                                                              monkeypatch):
    """Llamadas contabilizadas + provider_status sin EXECUTED => se declara."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")

    def _transporte(messages):
        return {"choices": [{"message": {"content": json.dumps({"relations": []})}}]}, 7

    run = bench_runner.run_benchmark(corpus, mode="ollama_shadow", source_ids=["src-01"],
                                     local_transport=_transporte, enable_providers=True)
    # Simulamos el literal que calcula pipeline.py (fuera de alcance).
    run.provider_status = {"local_llm": "FAILED_CLOSED", "external_ai": "FAILED_CLOSED"}
    rep = bench_report.build_report(corpus, run, check_determinism=False)
    assert rep["providers"]["status_consistency"].startswith("INCONSISTENTE")
    assert rep["providers"]["network"].startswith("yes (")


# ===========================================================================
# B3 - muestra pequena ENDURECE; 0 llamadas => sin dictamen normal
# ===========================================================================
def test_b3_muestra_pequena_con_error_aborta():
    """1-2 llamadas TODAS fallidas ya no pasan como 'ruido puro'."""
    def _rec(err):
        return {"local": {"latency_ms": 1, "validation_errors": [err] if err else []}}

    for n in (1, 2):
        with pytest.raises(bench_runner.ProviderTransportError) as exc:
            bench_runner.check_provider_transport_health(
                [_rec("transport_error:HTTPError") for _ in range(n)],
                mode="ollama_shadow", strict_small_sample=True)
        assert "POR DEBAJO del minimo" in str(exc.value)

    # Sin errores y con muestra pequena no hay nada que abortar.
    stats = bench_runner.check_provider_transport_health(
        [_rec(None)], mode="ollama_shadow", strict_small_sample=True)
    assert stats["sample_below_minimum"] is True and stats["total_errors"] == 0


def test_b3_run_con_dos_llamadas_fallidas_no_emite_dictamen(corpus, monkeypatch):
    """END-TO-END: el run aborta aunque la muestra sea de 1-2 llamadas."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")

    def _caido(messages):
        raise bench_runner.ProviderTransportError("caido")

    fuentes_pequenas = [sid for sid in ("src-07", "src-13", "src-14") if sid in corpus.sources]
    assert fuentes_pequenas
    for sid in fuentes_pequenas:
        with pytest.raises(bench_runner.ProviderTransportError):
            bench_runner.run_benchmark(corpus, mode="ollama_shadow", source_ids=[sid],
                                       local_transport=_caido, enable_providers=True)


def test_b3_cero_llamadas_en_modo_proveedor_no_da_dictamen_normal(corpus, monkeypatch):
    """`attempted == 0` => verdict_scope NO MEDIDO y dictamen sin calidad."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    llamadas = {"n": 0}

    def _transporte(messages):  # no llega a invocarse en estas fuentes
        llamadas["n"] += 1
        return {"choices": [{"message": {"content": json.dumps({"relations": []})}}]}, 5

    candidatas = [sid for sid in sorted(corpus.sources)]
    elegida = None
    for sid in candidatas:
        run = bench_runner.run_benchmark(corpus, mode="ollama_shadow", source_ids=[sid],
                                         local_transport=_transporte, enable_providers=True)
        if int(run.provider_transport.get("total_attempted", 0)) == 0:
            elegida = run
            break
    assert elegida is not None, "no hay ninguna fuente sin llamadas al proveedor"
    rep = bench_report.build_report(corpus, elegida, check_determinism=False)
    assert rep["gates"]["provider_transport"]["status"] == "NOT_MEASURED"
    assert rep["verdict"] == "SIN DICTAMEN: PROVEEDOR NO MEDIDO"
    assert rep["verdict"] in bench_report.VERDICTS
    assert rep["verdict_scope"].startswith("NO MEDIDO")


def test_b3_modo_offline_no_tiene_gate_de_transporte(corpus):
    run = bench_runner.run_benchmark(corpus, mode="baseline1", source_ids=["src-01"])
    rep = bench_report.build_report(corpus, run, check_determinism=False)
    assert "provider_transport" not in rep["gates"]


# ===========================================================================
# B4 - manifiesto obligatorio y verificado en --recombine-from
# ===========================================================================
def _run_offline_con_payloads(tmp_path):
    out_json = tmp_path / "res.json"
    payloads = tmp_path / "payloads.jsonl"
    rc = bench_cli.main([
        "--mode=ensemble_offline", f"--sources={','.join(SAMPLE_IDS)}",
        f"--out-json={out_json}", f"--out-payloads={payloads}", "--no-determinism",
    ])
    assert rc == 0
    return payloads


def test_b4_out_payloads_emite_manifiesto_verificable(tmp_path, no_network):
    payloads = _run_offline_con_payloads(tmp_path)
    man = bench_cli.manifest_path_for(payloads)
    assert man.is_file()
    manifest = json.loads(man.read_text(encoding="utf-8"))
    assert manifest["manifest"] == bench_cli.PAYLOAD_MANIFEST_VERSION
    assert manifest["source_ids"] == SAMPLE_IDS
    assert manifest["mode"] == "ensemble_offline"
    assert manifest["ground_truth_sha256"]
    assert manifest["payloads_sha256"] == bench_cli._sha256_bytes(payloads.read_bytes())
    assert no_network == []


def test_b4_recombine_marca_procedencia(tmp_path, no_network):
    payloads = _run_offline_con_payloads(tmp_path)
    out = tmp_path / "rec.json"
    # BLOQUEANTE 2 (ronda 4): recombinacion no autenticada -> reconocida con bandera.
    assert bench_cli.main([f"--recombine-from={payloads}", f"--out-json={out}",
                           "--accept-unauthenticated-recombine"]) == 0
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["provenance"]["recombined"] is True
    assert rec["provenance"]["payloads_sha256"]
    assert no_network == []


def test_b4_jsonl_forjado_sin_manifiesto_es_rechazado(tmp_path, corpus, capsys):
    """El JSONL forjado que daba P=R=F1=1.0 con rc=0 ahora no se recombina."""
    forjado = tmp_path / "forjado.jsonl"
    gt = [r for r in corpus.relations if r["source_id"] == "src-01"]
    recs = []
    for i, r in enumerate(gt):
        recs.append({
            "source_id": "src-01", "candidate_id": f"forged-{i}", "pair_id": f"p{i}",
            "candidate": {
                "source_id": "src-01", "workspace": corpus.workspace_by_source["src-01"],
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
    forjado.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
    out = tmp_path / "forjado-out.json"
    rc = bench_cli.run_cli([f"--recombine-from={forjado}", f"--out-json={out}"])
    assert rc == bench_cli.EXIT_BENCHMARK_ERROR
    assert "manifiesto" in capsys.readouterr().err
    assert not out.exists(), "no debe producirse ninguna metrica desde un JSONL sin manifiesto"


def test_b4_manifiesto_valido_pero_payloads_alterados(tmp_path, no_network):
    """Alterar el JSONL tras emitir el manifiesto invalida el sha256."""
    payloads = _run_offline_con_payloads(tmp_path)
    texto = payloads.read_text(encoding="utf-8")
    payloads.write_text(texto.replace("\"latency_ms\":", "\"latency_ms_x\":", 1) + "\n",
                        encoding="utf-8")
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_cli.main([f"--recombine-from={payloads}", f"--out-json={tmp_path / 'x.json'}"])
    msg = str(exc.value)
    assert "sha256" in msg or "tamano" in msg or "registros" in msg


def test_b4_jsonl_malformado_da_codigo_de_salida_del_contrato(tmp_path, capsys):
    """Entrada malformada -> EXIT_BENCHMARK_ERROR, no una traza cruda con rc=1."""
    payloads = _run_offline_con_payloads(tmp_path)
    man = bench_cli.manifest_path_for(payloads)
    payloads.write_text("{esto no es json}\n", encoding="utf-8")
    rc = bench_cli.run_cli([f"--recombine-from={payloads}"])
    assert rc == bench_cli.EXIT_BENCHMARK_ERROR
    assert man.is_file()


def test_b4_validacion_de_esquema_rechaza_en_bloque():
    buenos = [{
        "source_id": "src-01", "candidate_id": "c1",
        "candidate": {k: None for k in bench_runner._CANDIDATE_REQUIRED},
    }]
    assert bench_runner.validate_payload_records(buenos) == buenos
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.validate_payload_records(buenos + [{"source_id": "src-01"}])
    with pytest.raises(bench_runner.BenchmarkError):
        bench_runner.validate_payload_records(["no soy un objeto"])


# ===========================================================================
# B5 - validacion del endpoint
# ===========================================================================
@pytest.mark.parametrize("malo", [
    "file:///tmp/evil/chat/completions",
    "file:///etc/passwd",
    "ftp://attacker.example:21/x",
    "gopher://a/x",
    "localhost:11434",
    "h:11434",
    "http://user:secretpass@h:11434",
    "https://:clave@h/v1",
])
def test_b5_endpoints_no_admitidos(malo, no_network):
    with pytest.raises(bench_runner.BenchmarkError):
        bench_providers.normalize_local_endpoint(malo)
    with pytest.raises(bench_runner.BenchmarkError):
        bench_providers.build_local_transport(malo)
    assert no_network == []


def test_b5_credenciales_no_aparecen_en_ningun_error(no_network):
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_providers.build_local_transport("http://user:secretpass@h:11434")
    assert "secretpass" not in str(exc.value)
    assert no_network == []


def test_b5_atestacion_de_endpoint_sin_ruta_ni_credenciales():
    assert bench_providers.endpoint_attestation(
        "http://127.0.0.1:11434/v1/chat/completions") == "http://127.0.0.1:11434"
    assert bench_providers.endpoint_attestation("https://api.example/v1") == "https://api.example"


# ===========================================================================
# N1 / N2 - redirecciones y lectura acotada
# ===========================================================================
def test_n1_redireccion_entre_origenes_se_rechaza():
    import urllib.error

    handler = bench_providers._NoCrossOriginRedirect()

    class _Req:
        full_url = "http://127.0.0.1:11434/v1/chat/completions"

    with pytest.raises(urllib.error.HTTPError) as exc:
        handler.redirect_request(_Req(), None, 302, "Found", {},
                                 "http://otro.host:8080/v1/chat/completions")
    assert "BLOQUEADA" in str(exc.value)


def test_n2_lectura_acotada_por_tamano():
    class _Resp:
        def __init__(self):
            self.restante = bench_providers.MAX_RESPONSE_BYTES * 4

        def read(self, n=None):
            if self.restante <= 0:
                return b""
            n = n or self.restante
            n = min(n, self.restante)
            self.restante -= n
            return b"A" * n

    with pytest.raises(bench_runner.ProviderTransportError) as exc:
        bench_providers._read_bounded(_Resp(), deadline=time.monotonic() + 60, url="http://h")
    assert "demasiado grande" in str(exc.value)


def test_n2_deadline_de_reloj_de_pared():
    class _Goteo:
        def read(self, n=None):
            time.sleep(0.01)
            return b"A"

    with pytest.raises(bench_runner.ProviderTransportError) as exc:
        bench_providers._read_bounded(_Goteo(), deadline=time.monotonic() + 0.05,
                                      url="http://h")
    assert "deadline" in str(exc.value)


# ===========================================================================
# N5 / N6 - codigo muerto y constantes justificadas
# ===========================================================================
def test_n5_build_external_provider_ya_no_es_identidad(monkeypatch):
    """Sin API key falla CERRADO en vez de devolver None silenciosamente."""
    monkeypatch.delenv("S9K_NVIDIA_API_KEY", raising=False)
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_providers.build_external_provider()
    assert "FALLO CERRADO" in str(exc.value)
    centinela = object()
    assert bench_providers.build_external_provider(centinela) is centinela


def test_n5_no_queda_mapa_identidad_de_etiquetas():
    src = Path(bench_report.__file__).read_text(encoding="utf-8")
    assert "_PROVIDER_LABEL = {" not in src


def test_n6_timeout_local_con_margen_sobre_la_medicion_real():
    """p50 medido 97,8 s y maximo 175,7 s: 180 s no dejaba margen."""
    assert bench_runner.PROVIDER_LOCAL_TIMEOUT_S >= 300
    for modulo in (bench_runner, bench_providers):
        src = Path(modulo.__file__).read_text(encoding="utf-8")
        # La afirmacion refutada ya no se sostiene: si aparece "10-65 s" es
        # unicamente citada junto a la medicion que la refuta.
        assert "p50 real de Ollama\n# de 10-65 s" not in src
        assert "97,8" in src and "175,7" in src


# ===========================================================================
# N3 - max_time_per_candidate_ms no se publica como control efectivo
# ===========================================================================
def test_n3_el_informe_declara_que_el_limite_no_se_aplica(corpus):
    run = bench_runner.run_benchmark(corpus, mode="baseline1", source_ids=["src-01"])
    rep = bench_report.build_report(corpus, run, check_determinism=False)
    nota = rep["config_notes"]["max_time_per_candidate_ms"]
    assert "NO APLICADO" in nota
    md = bench_cli.render_markdown(rep)
    assert "max_time_per_candidate_ms" in md and "NO APLICADO" in md
