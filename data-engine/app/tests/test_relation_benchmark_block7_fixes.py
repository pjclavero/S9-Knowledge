# -*- coding: utf-8 -*-
"""Tests de regresion de la ronda de correcciones del Bloque 7.

Cubren los defectos detectados en la pasada real contra un Ollama vivo y por el
agente de tests:

  D1  fallo de TRANSPORTE != respuesta invalida del MODELO; y por encima del
      umbral el run ABORTA sin emitir dictamen de calidad.
  D2  `build_local_transport` normaliza el endpoint (.../v1 -> .../v1/chat/completions)
      y valida la forma OpenAI de la respuesta.
  D4  `--all-modes` + modo con proveedor aborta ANTES de construir transportes.
  D5  codigo de salida homogeneo via `run_cli`.
  D7  determinismo NO EVALUADO no es un FAIL de gate duro y no fuerza "NO APTO".

TODO es OFFLINE: los "proveedores" son transportes inyectados que lanzan o
devuelven diccionarios en memoria. No se abre ni un socket.
"""
from __future__ import annotations

import json

import pytest

from relations.benchmark import cli as bench_cli
from relations.benchmark import metrics as bench_metrics
from relations.benchmark import providers as bench_providers
from relations.benchmark import report as bench_report
from relations.benchmark import runner as bench_runner

SAMPLE_IDS = ["src-01", "src-02"]


@pytest.fixture()
def corpus():
    return bench_runner.load_corpus()


# ===========================================================================
# D2 - normalizacion del endpoint y validacion de forma
# ===========================================================================
@pytest.mark.parametrize("dado,esperado", [
    ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1/chat/completions"),
    ("http://127.0.0.1:11434/v1/", "http://127.0.0.1:11434/v1/chat/completions"),
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434/v1/chat/completions"),
    ("http://127.0.0.1:11434/v1/chat/completions",
     "http://127.0.0.1:11434/v1/chat/completions"),
    ("http://127.0.0.1:11434/v1/chat/completions/",
     "http://127.0.0.1:11434/v1/chat/completions"),
])
def test_d2_endpoint_se_normaliza(dado, esperado):
    """La base OpenAI-compatible `/v1` ya no produce un 404 silencioso."""
    assert bench_providers.normalize_local_endpoint(dado) == esperado


def test_d2_transporte_usa_la_url_normalizada(monkeypatch):
    """El POST se hace contra la URL normalizada, no contra la que se paso."""
    monkeypatch.setenv(bench_providers.LOCAL_ENDPOINT_ENV, "http://127.0.0.1:11434/v1")
    urls = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "{\"relations\": []}"}}]}
            ).encode("utf-8")

    def _fake_urlopen(req, timeout=None):
        urls.append(req.full_url)
        return _Resp()

    # N6: la costura de test es EXPLICITA (`opener=`); parchear
    # `urllib.request.urlopen` ya NO desactiva el endurecimiento del opener.
    # N13: el endpoint es EXPLICITO; la fabrica ya no lo toma del entorno.
    transport = bench_providers.build_local_transport("http://127.0.0.1:11434/v1", opener=_fake_urlopen)
    data, latency_ms = transport([{"role": "user", "content": "x"}])

    assert urls == ["http://127.0.0.1:11434/v1/chat/completions"]
    assert data["choices"][0]["message"]["content"]
    assert isinstance(latency_ms, int)


def test_d2_respuesta_sin_forma_openai_es_error_de_transporte(monkeypatch):
    """404/HTML/JSON ajeno -> ProviderTransportError, NO respuesta del modelo."""
    monkeypatch.setenv(bench_providers.LOCAL_ENDPOINT_ENV, "http://127.0.0.1:11434/v1")

    def _resp_with(payload_bytes):
        class _R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return payload_bytes

        return _R()

    # (a) JSON valido pero sin choices[0].message.content
    with pytest.raises(bench_runner.ProviderTransportError) as e1:
        bench_providers.build_local_transport(
            "http://127.0.0.1:11434/v1",
            opener=lambda req, timeout=None: _resp_with(b'{"error": "not found"}'),
        )([{"role": "user", "content": "x"}])
    assert "forma OpenAI" in str(e1.value)

    # (b) cuerpo no parseable como JSON (tipico 404 con HTML)
    with pytest.raises(bench_runner.ProviderTransportError) as e2:
        bench_providers.build_local_transport(
            "http://127.0.0.1:11434/v1",
            opener=lambda req, timeout=None: _resp_with(b"<html>404</html>"),
        )([{"role": "user", "content": "x"}])
    assert "JSON" in str(e2.value)

    # (c) excepcion de red / HTTP
    def _boom(req, timeout=None):
        raise OSError("connection refused")

    with pytest.raises(bench_runner.ProviderTransportError) as e3:
        bench_providers.build_local_transport("http://127.0.0.1:11434/v1", opener=_boom)(
            [{"role": "user", "content": "x"}])
    assert "transporte" in str(e3.value)


# ===========================================================================
# D1 - transporte vs calidad: clasificacion y aborto ruidoso
# ===========================================================================
def test_d1_clasificacion_distingue_transporte_de_calidad():
    """Un 404 y un JSON malformado del modelo NO son la misma categoria.

    RONDA 3 (B1): la version anterior de este test consagraba el defecto --
    afirmaba que CUALQUIER `provider_error` era transporte. No lo es: el `except`
    de `external_ai_shadow` agrupa toda la familia `ExternalAIError`, e
    `InvalidResponseError` (respuesta HTTP 200 sin verdictos, o texto libre
    no-JSON) es una averia de CALIDAD. Ahora se exige la clasificacion por la
    excepcion subyacente y una tercera categoria explicita cuando no se puede
    saber.
    """
    T = bench_metrics.CATEGORY_TRANSPORT
    R = bench_metrics.CATEGORY_RESPONDED
    I = bench_metrics.CATEGORY_INDETERMINATE

    transporte = {"validation_errors": ["transport_error:HTTPError"]}
    forma = {"validation_errors": ["response_structure_invalid"]}
    # provider_error con excepcion de RED/servidor -> transporte
    timeout_local = {"validation_errors": ["provider_error:ProviderTimeoutError"]}
    server_ext = {"reason_codes": ["provider_error"],
                  "validation_errors": ["ProviderServerError"]}
    # provider_error con excepcion de CONTENIDO -> calidad (responded)
    sin_verdicto = {"reason_codes": ["provider_error"],
                    "validation_errors": ["InvalidResponseError"]}
    texto_libre = {"validation_errors": ["provider_error:InvalidResponseError"]}
    # provider_error generico -> INDETERMINADO (ni transporte ni calidad)
    generico = {"validation_errors": ["provider_error:ExternalAIError"]}
    generico_ext = {"reason_codes": ["provider_error"],
                    "validation_errors": ["ExternalAIError"]}
    sin_pista = {"reason_codes": ["provider_error"]}
    # Respuestas del MODELO: si son calidad, no transporte.
    parseo = {"validation_errors": ["parse:InvalidResponseError"]}
    grande = {"validation_errors": ["response_too_large"]}
    campo = {"validation_errors": ["predicate_invalid"]}
    ok = {"validation_errors": []}

    for payload, kind in ((transporte, "transport_error"),
                          (forma, "response_structure_invalid"),
                          (timeout_local, "provider_error(ProviderTimeoutError)"),
                          (server_ext, "provider_error(ProviderServerError)")):
        assert bench_metrics.classify_provider_outcome(payload) == (T, kind)
        assert bench_metrics.classify_provider_payload(payload) == kind

    for payload in (sin_verdicto, texto_libre):
        cat, _kind = bench_metrics.classify_provider_outcome(payload)
        assert cat == R, "una respuesta HTTP 200 sin verdictos es CALIDAD"
        assert bench_metrics.classify_provider_payload(payload) is None

    for payload in (generico, generico_ext, sin_pista):
        cat, _kind = bench_metrics.classify_provider_outcome(payload)
        assert cat == I, "'provider_error' generico no autoriza a afirmar nada"
        assert bench_metrics.classify_provider_payload(payload) is None

    # Marcadores de CALIDAD conocidos: el modelo respondio y el CONTENIDO es lo que
    # falla (o es valido). Siguen siendo RESPONDED.
    for sano in (parseo, grande, campo):
        assert bench_metrics.classify_provider_outcome(sano)[0] == R
        assert bench_metrics.classify_provider_payload(sano) is None

    # DEFENSA EN PROFUNDIDAD (ronda 4): un payload SIN evidencia positiva de
    # contacto ya NO se afirma RESPONDED. Un `validation_errors: []` vacio, un
    # payload no-dict (`None`, `"x"`) o un dict vacio no autorizan a decir que el
    # modelo contesto: el default seguro es INDETERMINATE (que, por el candado
    # `responded>0`, lleva a NOT_MEASURED en vez de a un APTO falso).
    for indet in (ok, None, "x", {}):
        assert bench_metrics.classify_provider_outcome(indet)[0] == I
        assert bench_metrics.classify_provider_payload(indet) is None


def test_d1_provider_cost_separa_fallos_y_no_contamina_latencias():
    """La latencia reportada es la de llamadas RESPONDIDAS; los fallos van aparte."""
    results = [
        # 3 fallos de transporte con latencia ridicula (el 404 de la pasada real)
        {"local": {"latency_ms": 0, "validation_errors": ["transport_error:HTTPError"]},
         "local_status": "EXECUTED"},
        {"local": {"latency_ms": 1, "validation_errors": ["transport_error:HTTPError"]},
         "local_status": "EXECUTED"},
        {"local": {"latency_ms": 65, "validation_errors": ["response_structure_invalid"]},
         "local_status": "EXECUTED"},
        # 1 respuesta real del modelo, invalida por CALIDAD
        {"local": {"latency_ms": 3900, "validation_errors": ["parse:InvalidResponseError"]},
         "local_status": "EXECUTED"},
    ]
    cost = bench_metrics.provider_cost(results, [{"local_calls_simulated": 4}])

    t = cost["local"]["transport_errors"]
    assert t == {"attempted": 4, "responded": 1, "errors": 3, "rate": 0.75,
                 "by_type": {"response_structure_invalid": 1, "transport_error": 2}}
    assert cost["local"]["transport_error_rate"] == 0.75
    assert cost["transport_error_rate"] == 0.75
    # La latencia "del modelo" ya no incluye los 0 ms del 404.
    assert cost["local"]["latency"] == {"samples": 1, "p50_ms": 3900.0,
                                        "p95_ms": 3900.0, "max_ms": 3900.0}
    assert cost["local"]["failed_latency"]["samples"] == 3


def test_d1_umbral_aborta_y_no_emite_dictamen():
    """El umbral EFECTIVO es el DOCUMENTADO (N1), y `strict` es el defecto.

    RONDA 3: la version anterior de este test (escrita por este mismo bloque en
    la ronda 1) afirmaba que 1 sola llamada fallida "no aborta (ruido puro)" --
    un comportamiento que ya no existe y que ademas contradecia a B3. Se
    sustituye por aserciones MAS ESTRICTAS:

      * el defecto de `strict_small_sample` es True: 1 llamada fallida ABORTA;
      * un unico fallo temprano sobre muestra insuficiente ya NO aborta por TASA
        (era el defecto N1: "1/5 = 20% > 10%" con una tasa final del 2,8%);
      * un carril completamente caido aborta SIEMPRE, sin depender de la tasa;
      * la comprobacion FINAL si aplica la tasa desde `min_calls`.
    """
    import inspect

    def _rec(err, key="local"):
        return {key: {"latency_ms": 1,
                      "validation_errors": [err] if err else []}}

    firma = inspect.signature(bench_runner.check_provider_transport_health)
    assert firma.parameters["strict_small_sample"].default is True

    # 3 de 3 fallidas -> carril COMPLETAMENTE caido -> aborta (sin tasa de por medio).
    caidas = [_rec("transport_error:HTTPError") for _ in range(3)]
    with pytest.raises(bench_runner.ProviderTransportError) as exc:
        bench_runner.check_provider_transport_health(caidas, mode="ollama_shadow")
    msg = str(exc.value)
    assert "INFRAESTRUCTURA" in msg and "NO se emite dictamen" in msg

    # 1 de 20 -> 5% <= 10% -> no aborta, devuelve estadisticas.
    sanas = [_rec(None) for _ in range(19)] + [_rec("transport_error:HTTPError")]
    stats = bench_runner.check_provider_transport_health(sanas, mode="ollama_shadow")
    assert stats["total_errors"] == 1 and stats["rate"] == 0.05 and stats["rate_applied"]

    # MAS ESTRICTO que antes: 1 sola llamada fallida ABORTA por defecto.
    with pytest.raises(bench_runner.ProviderTransportError) as exc2:
        bench_runner.check_provider_transport_health(
            [_rec("transport_error:HTTPError")], mode="ollama_shadow")
    assert "POR DEBAJO del minimo" in str(exc2.value)

    # N1: 1 fallo de 5 (20%) en una comprobacion INTERMEDIA no aborta: la muestra
    # no alcanza `PROVIDER_TRANSPORT_MIN_RATE_SAMPLE` y la tasa final seria 2,8%.
    parcial = [_rec(None) for _ in range(4)] + [_rec("transport_error:HTTPError")]
    stats3 = bench_runner.check_provider_transport_health(parcial, mode="ollama_shadow")
    assert stats3["rate"] == 0.2 and stats3["rate_applied"] is False
    # ...pero en la comprobacion FINAL, con la misma muestra, SI aborta.
    with pytest.raises(bench_runner.ProviderTransportError):
        bench_runner.check_provider_transport_health(parcial, mode="ollama_shadow",
                                                     final=True)

    assert bench_runner.PROVIDER_TRANSPORT_ERROR_MAX_RATE == 0.10
    assert bench_runner.PROVIDER_TRANSPORT_MIN_RATE_SAMPLE >= 20


def test_d1_run_con_proveedor_caido_aborta_en_vez_de_dictaminar(corpus, monkeypatch):
    """END-TO-END offline: transporte que SIEMPRE falla -> nunca hay veredicto."""
    llamadas = []

    def _transporte_caido(messages):
        llamadas.append(1)
        raise bench_runner.ProviderTransportError("HTTP 404 simulado")

    with pytest.raises(bench_runner.ProviderTransportError) as exc:
        bench_runner.run_benchmark(corpus, mode="ollama_shadow",
                                   source_ids=SAMPLE_IDS,
                                   local_transport=_transporte_caido)
    assert "ABORTADO" in str(exc.value)
    assert llamadas, "el transporte inyectado deberia haberse invocado"

    # Y el mismo corpus con un transporte SANO si produce un run evaluable.
    def _transporte_sano(messages):
        return {"choices": [{"message": {"content": json.dumps({"relations": []})}}]}, 12

    run = bench_runner.run_benchmark(corpus, mode="ollama_shadow",
                                     source_ids=SAMPLE_IDS,
                                     local_transport=_transporte_sano)
    assert run.provider_transport["total_errors"] == 0
    rep = bench_report.build_report(corpus, run, check_determinism=False)
    assert rep["verdict"] in bench_report.VERDICTS
    assert rep["providers"]["transport"]["total_errors"] == 0


def test_d1_fail_fast_no_recorre_todo_el_corpus(corpus):
    """El aborto ocurre tras la PRIMERA fuente, no al final del corpus."""
    fuentes = sorted(corpus.sources)
    assert len(fuentes) > 1
    vistas = []

    def _transporte_caido(messages):
        raise bench_runner.ProviderTransportError("caido")

    real_run_source = bench_runner.run_source

    def _spy(corpus_, sid, **kw):
        vistas.append(sid)
        return real_run_source(corpus_, sid, **kw)

    bench_runner.run_source = _spy
    try:
        with pytest.raises(bench_runner.ProviderTransportError):
            bench_runner.run_benchmark(corpus, mode="ollama_shadow",
                                       local_transport=_transporte_caido)
    finally:
        bench_runner.run_source = real_run_source
    assert len(vistas) == 1, f"se siguieron pagando llamadas: {vistas}"


# ===========================================================================
# D3 - provider_status visible y directo en el JSON
# ===========================================================================
def test_d3_provider_status_directo_en_el_json(corpus, tmp_path):
    run = bench_runner.run_benchmark(corpus, mode="baseline1", source_ids=["src-01"])
    run.provider_status = {"local_llm": "EXECUTED", "external_ai": "NOT_EXECUTED"}
    rep = bench_report.build_report(corpus, run, check_determinism=False)

    assert rep["provider_status"] == run.provider_status
    assert rep["providers"]["provider_status"] == run.provider_status
    # Compatibilidad con el consumidor previo.
    assert rep["providers"]["provider_status_raw"] == run.provider_status
    # Sobrevive a la serializacion JSON (no queda a None).
    volcado = json.loads(json.dumps(rep, sort_keys=True, default=str))
    assert volcado["provider_status"]["local_llm"] == "EXECUTED"


# ===========================================================================
# D4 - el guard de --all-modes se evalua ANTES de construir transportes
# ===========================================================================
def test_d4_all_modes_con_proveedor_aborta_antes_de_construir_transportes(monkeypatch):
    """Con la DOBLE LLAVE concedida, no se paga ni una llamada."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    monkeypatch.setenv(bench_providers.LOCAL_ENDPOINT_ENV, "http://127.0.0.1:11434/v1")

    construidos = []
    monkeypatch.setattr(bench_providers, "build_local_transport",
                        lambda *a, **k: construidos.append("local"))
    monkeypatch.setattr(bench_providers, "build_external_provider",
                        lambda *a, **k: construidos.append("external"))
    corpus_cargado = []
    real_load = bench_cli.load_corpus
    monkeypatch.setattr(bench_cli, "load_corpus",
                        lambda *a, **k: (corpus_cargado.append(1), real_load(*a, **k))[1])
    ejecutados = []
    monkeypatch.setattr(bench_cli, "run_benchmark",
                        lambda *a, **k: ejecutados.append(1))

    for mode in sorted(bench_runner.PROVIDER_MODES):
        with pytest.raises(bench_runner.BenchmarkError) as exc:
            bench_cli.main([f"--mode={mode}", "--all-modes", "--enable-providers"])
        assert "--all-modes solo recorre modos OFFLINE" in str(exc.value)

    assert construidos == [], "se construyeron transportes antes de abortar"
    assert corpus_cargado == [], "se cargo el corpus antes de abortar"
    assert ejecutados == [], "se ejecuto el benchmark antes de abortar"


# ===========================================================================
# D5 - codigo de salida homogeneo
# ===========================================================================
def test_d5_run_cli_traduce_benchmark_error_a_codigo_de_salida(capsys):
    rc = bench_cli.run_cli(["--mode=ollama_shadow"])
    assert rc == bench_cli.EXIT_BENCHMARK_ERROR == 2
    assert "DOBLE LLAVE" in capsys.readouterr().err

    # main() sigue propagando la excepcion (contrato de los tests del bloque).
    with pytest.raises(bench_runner.BenchmarkError):
        bench_cli.main(["--mode=ollama_shadow"])


# ===========================================================================
# D7 - determinismo NO EVALUADO no es un FAIL
# ===========================================================================
def test_d7_determinismo_no_evaluado_no_fuerza_no_apto(corpus):
    run = bench_runner.run_benchmark(corpus, mode="baseline1", source_ids=SAMPLE_IDS)
    con = bench_report.build_report(corpus, run, check_determinism=True)
    sin = bench_report.build_report(corpus, run, check_determinism=False)

    assert con["gates"]["determinism"]["status"] == "PASS"
    assert con["verdict_scope"] == "COMPLETO"

    assert sin["gates"]["determinism"]["status"] == "NOT_EVALUATED"
    assert sin["gates"]["determinism"]["evaluated"] is False
    assert sin["verdict"] != "NO APTO"
    assert sin["verdict"] == con["verdict"], "el dictamen no debe depender del atajo"
    assert "NO EVALUADOS" in sin["verdict_justification"]
    assert sin["verdict_scope"].startswith("PARCIAL")
    # El gate sigue siendo DURO: si se comprueba y falla, NO APTO.
    assert sin["gates"]["determinism"]["hard"] is True
    gates_falso = dict(sin["gates"])
    gates_falso["determinism"] = {"status": "FAIL", "hard": True}
    veredicto, _ = bench_report.decide_verdict(gates_falso)
    assert veredicto == "NO APTO"


def test_d7_all_modes_no_reporta_todo_no_apto(tmp_path):
    out_json = tmp_path / "all.json"
    rc = bench_cli.main([
        "--mode=baseline1", "--all-modes", "--no-determinism",
        f"--sources={','.join(SAMPLE_IDS)}", f"--out-json={out_json}",
    ])
    assert rc == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    veredictos = {n: r["verdict"] for n, r in payload["all_modes"].items()}
    assert veredictos, "sin filas no hay comparativa"
    assert all(v != "NO APTO" for v in veredictos.values()), veredictos
    assert all(v in bench_report.VERDICTS for v in veredictos.values())
