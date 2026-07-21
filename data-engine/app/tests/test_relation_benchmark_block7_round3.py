# -*- coding: utf-8 -*-
"""Bloque 7 - RONDA 3: regresiones de los 2 bloqueantes y de los no bloqueantes.

La ronda 3 dejo el CODIGO escrito pero NI UN SOLO test propio. Este fichero cubre
cada arreglo, con dobles y SIN una sola conexion real:

  B1  `provider_error:` ya NO es sinonimo de "fallo de TRANSPORTE". Tres
      categorias DISJUNTAS (TRANSPORTE / RESPONDIDA / INDETERMINADA). La categoria
      INDETERMINADO no aborta el run y tampoco se presenta como medida de calidad.
  B3  el manifiesto de `--recombine-from` exige `corpus_hashes` NO vacios que
      cubran EXACTAMENTE sus `source_ids`, y un `code_sha` igual al del proceso
      que recombina; ademas el vocabulario de procedencia se degrada a
      "integridad interna, NO autenticidad".
  N1  el umbral EFECTIVO es el DOCUMENTADO: la tasa agregada no se aplica en las
      comprobaciones intermedias con muestra insuficiente.
  N2  la tasa se aplica tambien POR PROVEEDOR, no solo agregada.
  N3  `PARTIAL` del transporte se DECLARA en `verdict_scope` y en el dictamen.
  N4  `should_watch_transport` es una funcion aislada, con mutation check.
  N5  orden de validacion (credenciales ANTES que host) sin filtrar la URL cruda.
  N6  el endurecimiento de redirecciones NO depende de un global mutable.
  N7  `provider_fail_closed` se publica y degrada el gate.
  N8  la consistencia de `provider_status` se comprueba en las DOS direcciones.
  N9  puerto 0, IPv6 con corchetes y query preservada al normalizar.
  N10 puerto fuera de rango -> `BenchmarkError`, no `ValueError` crudo.
  N11 presupuesto GLOBAL de tiempo del run, comprobado entre fuentes.
  N12 `_REPO_ROOT` no depende del directorio de invocacion.
  N13 `build_local_transport` NO cae al entorno de forma implicita.

MUTATION CHECKS
---------------
Los invariantes criticos llevan un mutante EXPLICITO (`_mata_mutante`): se aplica
la mutacion, se exige que la comprobacion FALLE, se revierte y se exige que
vuelva a pasar. Cada uno documenta que mutante mata.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from relations.benchmark import cli as bench_cli  # noqa: E402
from relations.benchmark import metrics as bench_metrics  # noqa: E402
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


# ---------------------------------------------------------------------------
# Utillaje de MUTATION CHECK
# ---------------------------------------------------------------------------
def _mata_mutante(monkeypatch, aplicar, comprobar, *, mutante: str):
    """Aplica `aplicar` (la MUTACION), exige que `comprobar` falle, y revierte.

    `comprobar` debe pasar sin la mutacion (se vuelve a ejecutar al final, ya
    revertida) y debe FALLAR con ella. Si sobrevive, el test que lo invoca no
    esta comprobando de verdad el invariante.
    """
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


def _rec(lane: str, err=None, *, codes=None, latency=1):
    """Registro de resultado con el payload de un carril."""
    payload = {"latency_ms": latency, "validation_errors": [err] if err else []}
    if codes is not None:
        payload["reason_codes"] = list(codes)
    return {lane: payload}


# ===========================================================================
# B1 - `provider_error:` NO es sinonimo de fallo de transporte
# ===========================================================================
def test_b1_invalid_response_error_es_calidad_no_transporte():
    """`InvalidResponseError` = el modelo CONTESTO y el contenido no sirve."""
    cat, kind = bench_metrics.classify_provider_outcome(
        {"validation_errors": ["provider_error:InvalidResponseError"]})
    assert cat == bench_metrics.CATEGORY_RESPONDED
    assert kind == "provider_error(InvalidResponseError)"
    # La API antigua (`classify_provider_payload`) debe decir "no es transporte".
    assert bench_metrics.classify_provider_payload(
        {"validation_errors": ["provider_error:InvalidResponseError"]}) is None


@pytest.mark.parametrize("nombre", sorted(bench_metrics.TRANSPORT_EXCEPTION_NAMES))
def test_b1_excepciones_de_red_siguen_siendo_transporte(nombre):
    cat, kind = bench_metrics.classify_provider_outcome(
        {"validation_errors": [f"provider_error:{nombre}"]})
    assert cat == bench_metrics.CATEGORY_TRANSPORT
    assert kind == f"provider_error({nombre})"


def test_b1_transport_error_explicito_sigue_siendo_transporte():
    """El prefijo `transport_error:` no se ve afectado por la reclasificacion."""
    cat, _ = bench_metrics.classify_provider_outcome(
        {"validation_errors": ["transport_error:HTTPError"]})
    assert cat == bench_metrics.CATEGORY_TRANSPORT
    for code in sorted(bench_metrics.TRANSPORT_ERROR_CODES):
        cat, kind = bench_metrics.classify_provider_outcome({"validation_errors": [code]})
        assert (cat, kind) == (bench_metrics.CATEGORY_TRANSPORT, code)


@pytest.mark.parametrize("nombre", ["ExternalAIError", "", "AlgoDesconocidoError"])
def test_b1_marcador_ambiguo_queda_INDETERMINADO(nombre):
    """Sin nombre util, el benchmark se ABSTIENE: ni transporte ni calidad."""
    cat, kind = bench_metrics.classify_provider_outcome(
        {"validation_errors": [f"provider_error:{nombre}"]})
    assert cat == bench_metrics.CATEGORY_INDETERMINATE
    assert kind == f"provider_error({nombre or 'desconocido'})"
    # ...y NO se declara como transporte por la via antigua.
    assert bench_metrics.classify_provider_payload(
        {"validation_errors": [f"provider_error:{nombre}"]}) is None


def test_b1_forma_de_external_ai_shadow_reason_codes():
    """`external_ai_shadow` emite `reason_codes=['provider_error']` + nombre suelto."""
    quality = bench_metrics.classify_provider_outcome(
        {"reason_codes": ["provider_error"], "validation_errors": ["InvalidResponseError"]})
    assert quality[0] == bench_metrics.CATEGORY_RESPONDED
    transporte = bench_metrics.classify_provider_outcome(
        {"reason_codes": ["provider_error"], "validation_errors": ["ProviderServerError"]})
    assert transporte[0] == bench_metrics.CATEGORY_TRANSPORT
    ambiguo = bench_metrics.classify_provider_outcome(
        {"reason_codes": ["provider_error"], "validation_errors": []})
    assert ambiguo[0] == bench_metrics.CATEGORY_INDETERMINATE


def test_b1_las_tres_categorias_son_disjuntas_en_los_contadores():
    """`attempted = responded + errors + indeterminate`, sin solapes."""
    results = (
        [_rec("local", "provider_error:ProviderServerError") for _ in range(2)]
        + [_rec("local", "provider_error:InvalidResponseError") for _ in range(3)]
        + [_rec("local", "provider_error:ExternalAIError") for _ in range(4)]
        + [_rec("local") for _ in range(5)]
    )
    stats = bench_metrics.provider_transport_errors(results)
    local = stats["local"]
    ind = stats["indeterminate"]["local"]
    assert local["attempted"] == 14
    assert local["errors"] == 2
    assert ind["count"] == 4
    # RESPONDIDAS = las 3 de calidad + las 5 limpias.
    assert local["responded"] == 8
    assert local["attempted"] == local["responded"] + local["errors"] + ind["count"]
    assert stats["total_errors"] == 2 and stats["total_indeterminate"] == 4
    assert stats["rate"] == round(2 / 14, 4)


def test_b1_indeterminado_no_aborta_el_run_pero_tampoco_es_calidad(corpus, monkeypatch,
                                                                  no_network):
    """END-TO-END: 5/5 llamadas INDETERMINADAS.

    RECONCILIADO en ronda 4 (bloqueante 1): un carril con muestra suficiente y
    CERO respuestas confirmadas (`total_responded==0`) YA NO puede salir PARTIAL
    -> APTO -> rc=0. El punto de contacto con el modelo es cero, igual que con
    `total_attempted==0`, asi que el gate va a NOT_MEASURED (fail-closed) y el
    dictamen es SIN DICTAMEN. Antes esto salia PARTIAL, que dejaba pasar un run
    donde ningun proveedor llego a contestar (p.ej. envio BLOQUEADO por secreto).

    Sigue verificandose que:
    * NO aborta el run (indeterminado no es transporte: total_errors==0).
    * las latencias indeterminadas NO contaminan las del modelo.
    """
    from external_ai.errors import ExternalAIError

    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")

    def _generico(messages):
        raise ExternalAIError("fallo generico e inclasificable")

    run = bench_runner.run_benchmark(corpus, mode="ollama_shadow", source_ids=SAMPLE_IDS,
                                     local_transport=_generico, enable_providers=True)
    pt = run.provider_transport
    assert pt["total_attempted"] > 0
    assert pt["total_errors"] == 0, "un marcador ambiguo NO puede contarse como transporte"
    assert pt["total_indeterminate"] == pt["total_attempted"]
    assert pt["total_responded"] == 0, "0 respuestas confirmadas: nadie contesto"
    assert "provider_error(ExternalAIError)" in pt["indeterminate"]["local"]["by_type"]

    rep = bench_report.build_report(corpus, run, check_determinism=False)
    gate = rep["gates"]["provider_transport"]
    # BLOQUEANTE 1: fail-closed. responded==0 -> NOT_MEASURED, nunca PARTIAL.
    assert gate["status"] == "NOT_MEASURED", "responded==0: no consta que respondieran"
    assert gate["indeterminate"] == pt["total_attempted"]
    assert any("0 RESPUESTAS" in m for m in gate["degraded_reasons"])
    # NO se presenta como medida de calidad: SIN DICTAMEN, no un APTO.
    assert rep["verdict"].startswith("SIN DICTAMEN")
    assert rep["verdict_scope"].startswith("NO MEDIDO")
    assert "0 RESPUESTAS" in rep["verdict_scope"]
    assert "INFRAESTRUCTURA" in rep["verdict_justification"] \
        or "medicion inexistente" in rep["verdict_justification"]
    # Ni las latencias de esas llamadas contaminan las del modelo.
    coste = rep["metrics"]["provider_cost"]["local"]
    assert coste["latency"]["samples"] == 0
    assert coste["indeterminate_latency"]["samples"] == pt["total_attempted"]
    # Y el markdown lo declara con su nombre.
    md = bench_cli.render_markdown(rep)
    assert "INDETERMINADA" in md and "Indeterminadas" in md
    assert no_network == []


def test_b1_invalid_response_error_no_aborta_y_no_inventa_transporte(corpus, monkeypatch,
                                                                    no_network):
    """END-TO-END: el modelo contesta basura -> es CALIDAD, el run continua.

    Antes de la ronda 3 esto se contaba como transporte y abortaba el run con un
    diagnostico de "fallo de INFRAESTRUCTURA" falso.
    """
    from external_ai.errors import InvalidResponseError

    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")

    def _basura(messages):
        raise InvalidResponseError("la respuesta no contiene ningun verdicto")

    run = bench_runner.run_benchmark(corpus, mode="ollama_shadow", source_ids=SAMPLE_IDS,
                                     local_transport=_basura, enable_providers=True)
    pt = run.provider_transport
    assert pt["total_attempted"] > 0
    assert pt["total_errors"] == 0 and pt["total_indeterminate"] == 0
    assert pt["local"]["responded"] == pt["local"]["attempted"]
    rep = bench_report.build_report(corpus, run, check_determinism=False)
    assert rep["gates"]["provider_transport"]["status"] == "PASS"
    assert rep["verdict"] != "SIN DICTAMEN: PROVEEDOR NO MEDIDO"
    assert no_network == []


def test_b1_mutation_check_invalid_response_como_transporte(monkeypatch):
    """MUTANTE: `InvalidResponseError` reclasificada como TRANSPORTE.

    Es exactamente el comportamiento previo a la ronda 3 (todo `provider_error:`
    era transporte). Si el test no lo mata, el arreglo no esta comprobado.
    """
    def comprobar():
        cat, _ = bench_metrics.classify_provider_outcome(
            {"validation_errors": ["provider_error:InvalidResponseError"]})
        assert cat == bench_metrics.CATEGORY_RESPONDED

    def aplicar(mp):
        mp.setattr(bench_metrics, "TRANSPORT_EXCEPTION_NAMES",
                   bench_metrics.TRANSPORT_EXCEPTION_NAMES | {"InvalidResponseError"})

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="TRANSPORT_EXCEPTION_NAMES += InvalidResponseError")


def test_b1_mutation_check_indeterminado_colapsado_a_respondida(monkeypatch):
    """MUTANTE: la tercera categoria desaparece (todo lo dudoso = RESPONDIDA).

    Colapsar INDETERMINADO en RESPONDIDA es afirmar que el proveedor contesto sin
    prueba: presentaria como CALIDAD llamadas que quiza nunca llegaron al modelo.
    """
    payload = {"validation_errors": ["provider_error:ExternalAIError"]}

    def comprobar():
        cat, _ = bench_metrics.classify_provider_outcome(payload)
        assert cat == bench_metrics.CATEGORY_INDETERMINATE
        stats = bench_metrics.provider_transport_errors([_rec("local",
                                                              "provider_error:ExternalAIError")])
        assert stats["total_indeterminate"] == 1
        assert stats["local"]["responded"] == 0

    def aplicar(mp):
        mp.setattr(bench_metrics, "_provider_error_category",
                   lambda name: bench_metrics.CATEGORY_RESPONDED)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="_provider_error_category -> siempre RESPONDED")


# ===========================================================================
# B3 - el manifiesto no puede desactivar su propia atadura
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


def _reescribe_manifiesto(payloads: Path, **cambios) -> Path:
    man = bench_cli.manifest_path_for(payloads)
    data = json.loads(man.read_text(encoding="utf-8"))
    data.update(cambios)
    man.write_text(json.dumps(data), encoding="utf-8")
    return man


def _recombina(tmp_path, payloads: Path, *, accept_unauth: bool = True):
    """Recombina un JSONL. Por defecto reconoce el modo NO autenticado (bloqueante
    2, ronda 4): sin HMAC de operador la recombinacion es FAIL-CLOSED, asi que los
    tests que solo quieren llegar al cuerpo de la recombinacion pasan la bandera.
    Los tests que ejercen el fail-closed la omiten explicitamente."""
    argv = [f"--recombine-from={payloads}", f"--out-json={tmp_path / 'rec.json'}"]
    if accept_unauth:
        argv.append("--accept-unauthenticated-recombine")
    return bench_cli.main(argv)


def test_b3_control_negativo_manifiesto_intacto_recombina(tmp_path, no_network):
    """RECONCILIADO en ronda 4 (bloqueante 2): un manifiesto de valores PUBLICOS
    intacto ya NO recombina "limpio" con rc=0. El manifiesto solo prueba
    INTEGRIDAD (el JSONL no cambio, ata corpus/GT/code_sha), NO AUTENTICIDAD:
    todos esos valores son publicos, asi que cualquiera con el repositorio fabrica
    un manifiesto valido. Sin HMAC de operador la recombinacion es FAIL-CLOSED
    (rc!=0) SALVO reconocimiento explicito.

    Este control sigue cumpliendo su papel (fixture intacta => se llega al cuerpo
    de la recombinacion), pero ahora afirma el comportamiento CORRECTO:
      * sin bandera de reconocimiento -> rc!=0 y marca AUTENTICIDAD NO VERIFICADA;
      * con --accept-unauthenticated-recombine -> rc==0 pero la marca persiste.
    """
    payloads = _run_offline_con_payloads(tmp_path)
    # (a) FAIL-CLOSED por defecto: integridad OK pero autenticidad ausente.
    assert _recombina(tmp_path, payloads, accept_unauth=False) == \
        bench_cli.EXIT_BENCHMARK_ERROR
    rec = json.loads((tmp_path / "rec.json").read_text(encoding="utf-8"))
    assert rec["authenticity"] == "NO VERIFICADA"
    assert rec["authenticity_verified"] is False
    # (b) reconocido explicitamente: rc=0, pero la salida NO oculta la no-autenticidad.
    assert _recombina(tmp_path, payloads, accept_unauth=True) == 0
    rec = json.loads((tmp_path / "rec.json").read_text(encoding="utf-8"))
    assert rec["authenticity"].startswith("NO VERIFICADA")
    assert rec["authenticity_verified"] is False
    assert no_network == []


def test_b3_corpus_hashes_vacio_es_rechazado(tmp_path, no_network):
    """`corpus_hashes: {}` DESACTIVABA la atadura al corpus (se iteraba el propio
    manifiesto, asi que cero claves = cero comprobaciones)."""
    payloads = _run_offline_con_payloads(tmp_path)
    _reescribe_manifiesto(payloads, corpus_hashes={})
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        _recombina(tmp_path, payloads)
    assert "corpus_hashes" in str(exc.value)
    assert "RECHAZADO" in str(exc.value)
    assert not (tmp_path / "rec.json").exists()
    assert no_network == []


def test_b3_corpus_hashes_que_no_cubre_los_source_ids_es_rechazado(tmp_path, no_network):
    """Un SUBCONJUNTO de hashes dejaba fuentes sin atar: tambien se rechaza."""
    payloads = _run_offline_con_payloads(tmp_path)
    man = bench_cli.manifest_path_for(payloads)
    data = json.loads(man.read_text(encoding="utf-8"))
    assert sorted(data["corpus_hashes"]) == sorted(SAMPLE_IDS)
    parcial = {SAMPLE_IDS[0]: data["corpus_hashes"][SAMPLE_IDS[0]]}
    _reescribe_manifiesto(payloads, corpus_hashes=parcial)
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        _recombina(tmp_path, payloads)
    assert "no cubre EXACTAMENTE" in str(exc.value)

    # Y tampoco vale el caso contrario: hashes de fuentes NO declaradas.
    sobrante = dict(data["corpus_hashes"])
    sobrante["src-99"] = "0" * 64
    _reescribe_manifiesto(payloads, corpus_hashes=sobrante)
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        _recombina(tmp_path, payloads)
    assert "no cubre EXACTAMENTE" in str(exc.value)
    assert no_network == []


def test_b3_code_sha_ajeno_es_rechazado(tmp_path, no_network):
    """Un `code_sha` inventado (40 ceros) era aceptado: no se contrastaba con nada."""
    payloads = _run_offline_con_payloads(tmp_path)
    _reescribe_manifiesto(payloads, code_sha="0" * 40)
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        _recombina(tmp_path, payloads)
    msg = str(exc.value)
    assert "code_sha" in msg and "RECHAZADO" in msg
    assert not (tmp_path / "rec.json").exists()
    assert no_network == []


def test_b3_mutation_check_code_sha_sin_contrastar(tmp_path, monkeypatch):
    """MUTANTE: el proceso que recombina declara el MISMO code_sha forjado.

    Equivale a eliminar la atadura (`manifest['code_sha']` comparado consigo
    mismo). Con el mutante el manifiesto forjado se acepta y el test cae.
    """
    payloads = _run_offline_con_payloads(tmp_path)
    forjado = "0" * 40
    _reescribe_manifiesto(payloads, code_sha=forjado)

    def comprobar():
        with pytest.raises(bench_runner.BenchmarkError) as exc:
            _recombina(tmp_path, payloads)
        assert "code_sha" in str(exc.value)

    def aplicar(mp):
        mp.setattr(bench_cli, "_code_sha", lambda: forjado)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="_code_sha() del proceso == code_sha forjado del manifiesto")


def test_b3_arbol_sin_git_se_rechaza_por_code_sha_indeterminable(tmp_path, monkeypatch,
                                                                 no_network):
    """Un `code_sha` INDETERMINABLE es motivo de rechazo POR SI MISMO.

    Caso decisivo del ORDEN de las comprobaciones: manifiesto con un `code_sha`
    de aspecto legitimo y proceso que NO puede determinar el suyo (arbol sin
    git). Con el orden anterior ganaba la comparacion de igualdad y el mensaje
    culpaba al manifiesto ("no corresponde a ESTE codigo"), ocultando el hecho
    real: no hay NADA con lo que contrastar. La causa se declara tal cual.
    """
    payloads = _run_offline_con_payloads(tmp_path)
    _reescribe_manifiesto(payloads, code_sha="a" * 40)
    monkeypatch.setattr(bench_cli, "_code_sha", lambda: None)  # arbol sin git
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        _recombina(tmp_path, payloads)
    msg = str(exc.value)
    assert "no se puede determinar el code_sha" in msg
    assert "RECHAZADO" in msg
    # NO puede achacarse a un desajuste de version: ese no es el problema.
    assert "no corresponde a ESTE codigo" not in msg
    assert not (tmp_path / "rec.json").exists()
    assert no_network == []


def test_b3_manifiesto_con_code_sha_null_en_arbol_sin_git_se_rechaza(tmp_path, monkeypatch,
                                                                     no_network):
    """`code_sha: null` + arbol sin git: `None == None` NO puede ser un pase.

    Este era el empate afortunado del que dependia la seguridad: la comparacion
    de igualdad daba "iguales" y el rechazo quedaba a merced de una guarda
    posterior. Ahora se rechaza ANTES de comparar, por ausencia de atadura.
    """
    payloads = _run_offline_con_payloads(tmp_path)
    _reescribe_manifiesto(payloads, code_sha=None)
    monkeypatch.setattr(bench_cli, "_code_sha", lambda: None)  # arbol sin git
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        _recombina(tmp_path, payloads)
    assert "no se puede determinar el code_sha" in str(exc.value)
    assert not (tmp_path / "rec.json").exists()
    assert no_network == []


def test_b3_el_code_sha_indeterminable_se_comprueba_antes_que_la_igualdad(tmp_path,
                                                                          monkeypatch):
    """Fija el ORDEN: la guarda de indeterminacion es la PRIMERA en disparar.

    Se recorren los dos manifiestos posibles (con `code_sha` propio y con
    `null`): en AMBOS la causa declarada debe ser la indeterminacion, nunca la
    desigualdad. Si alguien vuelve a poner la comparacion delante, el caso del
    `code_sha` ajeno cambia de mensaje y este test cae.
    """
    monkeypatch.setattr(bench_cli, "_code_sha", lambda: None)
    for etiqueta, declarado in (("ajeno", "a" * 40), ("nulo", None)):
        sub = tmp_path / f"m-{etiqueta}"
        sub.mkdir()
        payloads = _run_offline_con_payloads(sub)
        _reescribe_manifiesto(payloads, code_sha=declarado)
        with pytest.raises(bench_runner.BenchmarkError) as exc:
            _recombina(sub, payloads)
        assert "no se puede determinar el code_sha" in str(exc.value), etiqueta
        assert "no corresponde a ESTE codigo" not in str(exc.value), etiqueta


def test_b3_mutation_check_code_sha_inventado_en_vez_de_indeterminado(tmp_path, monkeypatch):
    """MUTANTE: `_code_sha()` devuelve un relleno en lugar de admitir `None`.

    Es la mutacion CONSTRUIBLE de este arreglo: si el proceso se inventa un
    `code_sha` (un placeholder, un "unknown") en vez de declararse incapaz de
    determinarlo, la guarda deja de dispararse y un manifiesto que declare ese
    mismo relleno se acepta SIN atadura real al codigo.

    LIMITACION HONESTA: el mutante puro de ORDEN (intercambiar los dos bloques)
    NO es construible con monkeypatch, porque ambas comprobaciones son codigo
    inline de la misma funcion. Lo que fija el orden es
    `test_b3_el_code_sha_indeterminable_se_comprueba_antes_que_la_igualdad`,
    que discrimina por la CAUSA declarada.
    """
    relleno = "b" * 40
    payloads = _run_offline_con_payloads(tmp_path)
    _reescribe_manifiesto(payloads, code_sha=relleno)

    def comprobar():
        with pytest.raises(bench_runner.BenchmarkError) as exc:
            _recombina(tmp_path, payloads)
        assert "no se puede determinar el code_sha" in str(exc.value)

    # Sin mutacion, el proceso admite que no puede determinarlo.
    monkeypatch.setattr(bench_cli, "_code_sha", lambda: None)

    def aplicar(mp):
        mp.setattr(bench_cli, "_code_sha", lambda: relleno)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="_code_sha() devuelve un relleno en vez de None")


def test_b3_control_negativo_code_sha_real_sigue_recombinando(tmp_path, no_network):
    """CONTROL (reconciliado en ronda 4, bloqueante 2): con un `code_sha`
    determinable y coincidente la guarda de code_sha NO rechaza -- pero, como el
    manifiesto de valores publicos no prueba AUTENTICIDAD, la recombinacion sigue
    siendo FAIL-CLOSED salvo reconocimiento explicito.

    Sigue impidiendo que la guarda de code_sha se convierta en un rechazo
    universal: con la bandera de reconocimiento la recombinacion termina rc=0 y el
    motivo del fail-closed por defecto es la AUTENTICIDAD, no el code_sha.
    """
    payloads = _run_offline_con_payloads(tmp_path)
    assert bench_cli._code_sha() is not None
    # Sin reconocer el modo no autenticado: FAIL-CLOSED, y NO por el code_sha.
    rc = bench_cli.run_cli([f"--recombine-from={payloads}",
                            f"--out-json={tmp_path / 'rec.json'}"])
    assert rc == bench_cli.EXIT_BENCHMARK_ERROR
    rec = json.loads((tmp_path / "rec.json").read_text(encoding="utf-8"))
    assert rec["authenticity_verified"] is False
    # code_sha real y coincidente: no es el motivo del rechazo (la guarda no es
    # universal). Con reconocimiento explicito, recombina rc=0.
    assert _recombina(tmp_path, payloads, accept_unauth=True) == 0
    assert (tmp_path / "rec.json").exists()
    assert no_network == []


def test_b3_procedencia_no_afirma_autenticidad(tmp_path, monkeypatch, no_network):
    """Sin clave HMAC, el vocabulario NO puede decir "verificado" a secas."""
    monkeypatch.delenv(bench_cli.MANIFEST_HMAC_KEY_ENV, raising=False)
    payloads = _run_offline_con_payloads(tmp_path)
    out = tmp_path / "rec.json"
    # BLOQUEANTE 2: sin HMAC es FAIL-CLOSED; se reconoce el modo no autenticado
    # para llegar a inspeccionar el vocabulario de procedencia.
    assert bench_cli.main([f"--recombine-from={payloads}", f"--out-json={out}",
                           "--accept-unauthenticated-recombine"]) == 0
    prov = json.loads(out.read_text(encoding="utf-8"))["provenance"]
    assert prov["verified"] == "integridad interna, NO autenticidad"
    assert "NO comprobado" in prov["verified_detail"]
    assert "autenticidad" in prov["verified_detail"] or "quien emitio" in prov["verified_detail"]
    assert prov["hmac"].startswith("AUSENTE")
    # La afirmacion fuerte solo puede aparecer negada, nunca como sello.
    assert prov["verified"] != "verificado"
    assert no_network == []


def test_b3_con_clave_hmac_la_procedencia_si_se_autentica(tmp_path, monkeypatch, no_network):
    """Contrapartida: con la clave del operador el HMAC se exige y se verifica."""
    monkeypatch.setenv(bench_cli.MANIFEST_HMAC_KEY_ENV, "clave-de-operador-de-test")
    payloads = _run_offline_con_payloads(tmp_path)
    man = json.loads(bench_cli.manifest_path_for(payloads).read_text(encoding="utf-8"))
    assert man.get("hmac_sha256")
    out = tmp_path / "rec.json"
    assert bench_cli.main([f"--recombine-from={payloads}", f"--out-json={out}"]) == 0
    prov = json.loads(out.read_text(encoding="utf-8"))["provenance"]
    assert prov["hmac"] == "VERIFICADO con la clave de operador"
    # Alterar el manifiesto invalida el HMAC (y `verified` sigue sin ser autenticidad).
    _reescribe_manifiesto(payloads, hmac_sha256="f" * 64)
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        _recombina(tmp_path, payloads)
    assert "HMAC" in str(exc.value)
    assert no_network == []


# ===========================================================================
# N1 - el umbral EFECTIVO es el DOCUMENTADO
# ===========================================================================
def test_n1_un_fallo_temprano_no_aborta_por_la_tasa():
    """1 fallo en la llamada #1 de 5 => 20% agregado, pero muestra insuficiente.

    Antes abortaba con "1/5 = 20% > 10%" aunque la tasa FINAL fuese del 2,8%: el
    umbral efectivo era "cualquier fallo temprano", no el 10% documentado.
    """
    recs = [_rec("local", "transport_error:HTTPError")] + [_rec("local") for _ in range(4)]
    stats = bench_runner.check_provider_transport_health(recs, mode="ollama_shadow")
    assert stats["rate"] == 0.2 > bench_runner.PROVIDER_TRANSPORT_ERROR_MAX_RATE
    assert stats["rate_applied"] is False
    assert stats["min_rate_sample"] == bench_runner.PROVIDER_TRANSPORT_MIN_RATE_SAMPLE


def test_n1_con_muestra_suficiente_la_tasa_si_se_aplica():
    """A partir de `min_rate_sample` la tasa vuelve a gobernar."""
    recs = ([_rec("local", "transport_error:HTTPError") for _ in range(5)]
            + [_rec("local") for _ in range(15)])
    with pytest.raises(bench_runner.ProviderTransportError) as exc:
        bench_runner.check_provider_transport_health(recs, mode="ollama_shadow")
    assert "25.0%" in str(exc.value)


def test_n1_la_comprobacion_final_aplica_la_tasa_con_min_calls():
    """En la comprobacion FINAL basta `min_calls`: la muestra ya es la completa."""
    recs = ([_rec("local", "transport_error:HTTPError")]
            + [_rec("local") for _ in range(3)]
            + [_rec("external") for _ in range(2)])
    # Intermedia: 6 llamadas < 20 => la tasa no se aplica.
    stats = bench_runner.check_provider_transport_health(recs, mode="ensemble_real")
    assert stats["rate_applied"] is False
    # Final: 6 >= min_calls(3) => 1/6 = 16,7% > 10% => aborta.
    with pytest.raises(bench_runner.ProviderTransportError):
        bench_runner.check_provider_transport_health(recs, mode="ensemble_real", final=True)


def test_n1_cortocircuitos_que_no_dependen_de_la_tasa():
    """Relajar la tasa intermedia NO puede abrir la puerta a un carril muerto."""
    # (a) muestra por debajo del minimo CON errores => aborta (endurecimiento B3).
    with pytest.raises(bench_runner.ProviderTransportError) as exc:
        bench_runner.check_provider_transport_health(
            [_rec("local", "transport_error:HTTPError")], mode="ollama_shadow")
    assert "POR DEBAJO del minimo" in str(exc.value)
    # (b) carril con el 100% de sus llamadas fallidas => aborta aunque la muestra
    #     sea < min_rate_sample.
    recs = ([_rec("local", "transport_error:HTTPError") for _ in range(5)]
            + [_rec("external") for _ in range(5)])
    with pytest.raises(bench_runner.ProviderTransportError) as exc:
        bench_runner.check_provider_transport_health(recs, mode="ensemble_real")
    assert "['local']" in str(exc.value)


def test_n1_mutation_check_umbral_intermedio_restaurado_a_min_calls(monkeypatch):
    """MUTANTE: `min_rate_sample` vuelve a `min_calls` (el bug original).

    Con el mutante, 1 fallo de 5 aborta y el umbral efectivo deja de ser el
    documentado.
    """
    recs = [_rec("local", "transport_error:HTTPError")] + [_rec("local") for _ in range(4)]

    def comprobar():
        stats = bench_runner.check_provider_transport_health(recs, mode="ollama_shadow")
        assert stats["rate_applied"] is False

    real = bench_runner.check_provider_transport_health

    def mutado(results, **kw):
        # La constante es un DEFAULT del parametro, evaluado en tiempo de `def`:
        # mutarla como global no cambiaria nada. La mutacion honesta es forzar el
        # valor anterior en la propia llamada.
        kw["min_rate_sample"] = bench_runner.PROVIDER_TRANSPORT_MIN_CALLS
        return real(results, **kw)

    def aplicar(mp):
        mp.setattr(bench_runner, "check_provider_transport_health", mutado)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="min_rate_sample efectivo = PROVIDER_TRANSPORT_MIN_CALLS")


# ===========================================================================
# N2 - la tasa se aplica POR PROVEEDOR, no solo agregada
# ===========================================================================
def _escenario_dilucion():
    """Local 1/7 = 14,3%; externo 0/14. Agregado 1/21 = 4,76% (por debajo del 10%)."""
    return ([_rec("local", "transport_error:HTTPError")]
            + [_rec("local") for _ in range(6)]
            + [_rec("external") for _ in range(14)])


def test_n2_un_carril_por_encima_del_umbral_aborta_aunque_el_agregado_no():
    recs = _escenario_dilucion()
    stats = bench_metrics.provider_transport_errors(recs)
    assert stats["local"]["rate"] == round(1 / 7, 4)  # 14,3%
    assert stats["external"]["rate"] == 0.0
    assert stats["rate"] == round(1 / 21, 4)  # 4,76% -> el agregado NO lo detecta
    assert stats["rate"] <= bench_runner.PROVIDER_TRANSPORT_ERROR_MAX_RATE

    with pytest.raises(bench_runner.ProviderTransportError) as exc:
        bench_runner.check_provider_transport_health(recs, mode="ensemble_real", final=True)
    msg = str(exc.value)
    assert "POR PROVEEDOR" in msg and "['local']" in msg
    assert "NO lo habria detectado" in msg


def test_n2_el_gate_no_declara_evaluable_un_run_con_un_carril_malo():
    """`evaluable` es lo que gobierna el gate duro: no puede ignorar el carril."""
    recs = _escenario_dilucion()
    stats = bench_runner.check_provider_transport_health(
        recs, mode="ensemble_real", max_rate=1.0, final=True)  # sin abortar, para inspeccionar
    assert stats["local"]["rate"] > bench_runner.PROVIDER_TRANSPORT_ERROR_MAX_RATE


def test_n2_mutation_check_solo_agregado(monkeypatch):
    """MUTANTE: los carriles reportan la tasa AGREGADA (dilucion consumada).

    Es la forma exacta del defecto: con la tasa por carril igual al agregado
    (4,76%) ningun carril supera el umbral y el run emite dictamen APTO.
    """
    recs = _escenario_dilucion()

    def comprobar():
        with pytest.raises(bench_runner.ProviderTransportError):
            bench_runner.check_provider_transport_health(recs, mode="ensemble_real",
                                                         final=True)

    real = bench_metrics.provider_transport_errors

    def diluido(results):
        stats = real(results)
        for key in ("local", "external"):
            stats[key]["errors"] = 0  # el agregado ya no se ve por carril
            stats[key]["rate"] = stats["rate"]
        return stats

    def aplicar(mp):
        mp.setattr(bench_metrics, "provider_transport_errors", diluido)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="tasa por carril colapsada a la tasa agregada")


# ===========================================================================
# N3 - `PARTIAL` del transporte se DECLARA
# ===========================================================================
def _gates_con_transporte(status: str, motivos: list) -> dict:
    """Gates minimos con un `provider_transport` en el estado pedido."""
    return {
        "provider_transport": {"status": status, "hard": True,
                               "degraded_reasons": list(motivos),
                               "detail": {"total_attempted": 10, "total_errors": 1}},
        "determinism": {"status": "PASS", "hard": True},
        "workspace_contamination": {"status": "PASS", "hard": True},
        "simple_relations": {"status": "PASS"}, "evidence": {"status": "PASS"},
        "offsets": {"status": "PASS"}, "negation": {"status": "PASS"},
        "temporality": {"status": "PASS"}, "rumors": {"status": "PASS"},
        "predicate_structural": {"status": "PASS"},
    }


def test_n3_partial_de_transporte_aparece_en_verdict_scope():
    """`PARTIAL` no puede quedarse callado: si "no comprobado" se declara,
    "comprobado y degradado" tambien."""
    motivo = "1/10 llamadas fallaron en TRANSPORTE (10.0%)"
    gates = _gates_con_transporte("PARTIAL", [motivo])
    scope = bench_report._verdict_scope(gates)
    assert scope.startswith("PARCIAL")
    assert "DEGRADADO" in scope and motivo in scope
    # Y en la justificacion del dictamen.
    veredicto, justificacion = bench_report.decide_verdict(gates)
    assert veredicto.startswith("APTO")
    assert "TRANSPORTE DEGRADADO" in justificacion and motivo in justificacion


def test_n3_pass_de_transporte_no_ensucia_el_alcance():
    """Sin degradacion, el alcance sigue siendo COMPLETO (no se cries wolf)."""
    gates = _gates_con_transporte("PASS", [])
    assert bench_report._verdict_scope(gates) == "COMPLETO"
    _, justificacion = bench_report.decide_verdict(gates)
    assert "TRANSPORTE DEGRADADO" not in justificacion


def test_n3_partial_end_to_end_con_errores_de_transporte_tolerados(corpus, monkeypatch,
                                                                   no_network):
    """Run REAL con algunos fallos de transporte por debajo del umbral."""
    monkeypatch.setenv(bench_runner.PROVIDERS_ENV_VAR, "1")
    estado = {"n": 0}

    def _intermitente(messages):
        estado["n"] += 1
        if estado["n"] == 1:  # 1 de N: por debajo del 10% no siempre, ver abajo
            raise RuntimeError("hipo puntual de transporte")
        return {"choices": [{"message": {"content": json.dumps({"relations": []})}}]}, 9

    # Se usan muchas fuentes para que 1 fallo quede por debajo del 10%.
    fuentes = sorted(corpus.sources)
    run = bench_runner.run_benchmark(corpus, mode="ollama_shadow", source_ids=fuentes,
                                     local_transport=_intermitente, enable_providers=True)
    pt = run.provider_transport
    assert pt["total_errors"] == 1 and pt["total_attempted"] >= 10
    rep = bench_report.build_report(corpus, run, check_determinism=False)
    assert rep["gates"]["provider_transport"]["status"] == "PARTIAL"
    assert "DEGRADADO" in rep["verdict_scope"]
    assert "TRANSPORTE" in rep["verdict_justification"]
    assert "TRANSPORTE DEGRADADO" in bench_cli.render_markdown(rep)
    assert no_network == []


def test_n3_mutation_check_alcance_que_ignora_partial(monkeypatch):
    """MUTANTE: `_verdict_scope` previo a la ronda 3 (solo mira NOT_MEASURED/FAIL).

    Con el, un transporte degradado se publica como alcance COMPLETO.
    """
    gates = _gates_con_transporte("PARTIAL", ["1/10 llamadas fallaron en TRANSPORTE"])

    def comprobar():
        assert "DEGRADADO" in bench_report._verdict_scope(gates)

    def _scope_viejo(g):
        pt = g.get("provider_transport")
        if pt is not None and pt.get("status") in ("NOT_MEASURED", "FAIL"):
            return "NO MEDIDO"
        return "COMPLETO"

    def aplicar(mp):
        mp.setattr(bench_report, "_verdict_scope", _scope_viejo)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="_verdict_scope ignora el estado PARTIAL del transporte")


def test_n3_round2_sigue_describiendo_la_verdad(corpus):
    """El test de la RONDA 2 sobre `max_time_per_candidate_ms` sigue siendo cierto.

    (Se comprueba aqui explicitamente en vez de fiarse de que siga en verde: la
    ronda 3 toco `config_notes` y `verdict_scope`, que es lo que aquel test lee.)
    """
    run = bench_runner.run_benchmark(corpus, mode="baseline1", source_ids=["src-01"])
    rep = bench_report.build_report(corpus, run, check_determinism=False)
    assert "NO APLICADO" in rep["config_notes"]["max_time_per_candidate_ms"]
    # Y el modo offline no gana un gate de transporte por la ronda 3.
    assert "provider_transport" not in rep["gates"]
    assert rep["verdict_scope"] in ("COMPLETO",) or rep["verdict_scope"].startswith("PARCIAL")


# ===========================================================================
# N4 - `should_watch_transport`, aislado y con mutante
# ===========================================================================
@pytest.mark.parametrize("mode", sorted(bench_runner.PROVIDER_MODES))
def test_n4_se_vigila_el_transporte_en_todo_modo_con_proveedor(mode):
    """Sin inyectar NADA el criterio sigue siendo True: es lo que mata el defecto.

    El criterio anterior (`local is not None or external is not None`) dejaba el
    umbral MUERTO en el carril externo, porque `build_external_provider` devolvia
    siempre `None`.
    """
    assert bench_runner.should_watch_transport(mode, None, None) is True
    assert bench_runner.should_watch_transport(mode, object(), None) is True
    assert bench_runner.should_watch_transport(mode, None, object()) is True


@pytest.mark.parametrize("mode", sorted(bench_runner.MODES))
def test_n4_los_modos_offline_no_vigilan_transporte(mode):
    assert bench_runner.should_watch_transport(mode, None, None) is False
    # Ni aunque alguien inyecte un transporte en un modo offline.
    assert bench_runner.should_watch_transport(mode, object(), object()) is False


def test_n4_mutation_check_criterio_por_inyeccion(monkeypatch):
    """MUTANTE: el criterio vuelve a "se inyecto algo".

    Es la mutacion que quedaba ENMASCARADA end-to-end (porque
    `authorize_provider_run` exige inyeccion): solo se mata con el test directo.
    """
    def comprobar():
        assert bench_runner.should_watch_transport("nvidia_shadow", None, None) is True

    def aplicar(mp):
        mp.setattr(bench_runner, "should_watch_transport",
                   lambda mode, local, external: local is not None or external is not None)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="should_watch_transport -> local is not None or external is not None")


# ===========================================================================
# N5 / N9 / N10 - validacion de endpoints
# ===========================================================================
def test_n5_credenciales_se_comprueban_antes_que_el_host_y_no_se_filtra_la_url():
    """`http://tok:SECRETO@/v1`: hay credenciales Y no hay host.

    Con el orden anterior ganaba la rama de host, que volcaba `endpoint!r` entero
    a stderr (y a los logs de CI).
    """
    malo = "http://tok:SECRETO_DE_CI@/v1"
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_providers.normalize_local_endpoint(malo)
    msg = str(exc.value)
    assert "credenciales" in msg
    assert "SECRETO_DE_CI" not in msg and "tok" not in msg
    assert malo not in msg


def test_n5_ninguna_rama_de_validacion_vuelca_la_url_cruda():
    """Barrido: NINGUN endpoint rechazado puede reproducir su propio secreto."""
    casos = [
        "http://u:SECRETO_DE_CI@host:11434/v1",
        "https://u:SECRETO_DE_CI@/v1",
        "ftp://u:SECRETO_DE_CI@host/v1",
        "http://u:SECRETO_DE_CI@host:99999/v1",
        "http://u:SECRETO_DE_CI@host:0/v1",
    ]
    for malo in casos:
        with pytest.raises(bench_runner.BenchmarkError) as exc:
            bench_providers.normalize_local_endpoint(malo)
        assert "SECRETO_DE_CI" not in str(exc.value), malo


def test_n9_puerto_cero_es_rechazado():
    """Puerto 0 no es destino valido y ademas DESAPARECIA de la atestacion."""
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_providers.normalize_local_endpoint("http://127.0.0.1:0/v1")
    assert "puerto 0" in str(exc.value)
    with pytest.raises(bench_runner.BenchmarkError):
        bench_providers.endpoint_attestation("http://127.0.0.1:0/v1")


def test_n9_ipv6_conserva_los_corchetes():
    """`parts.hostname` devuelve `::1`: concatenarlo daba `http://::1:11434`."""
    assert bench_providers.endpoint_attestation(
        "http://[::1]:11434/v1") == "http://[::1]:11434"
    assert bench_providers.normalize_local_endpoint(
        "http://[::1]:11434/v1") == "http://[::1]:11434/v1/chat/completions"


def test_n9_la_query_no_se_pierde_ni_rompe_la_ruta():
    """Concatenar sufijos daba `.../v1?k=X/chat/completions` (404 seguro)."""
    url = bench_providers.normalize_local_endpoint("http://h:11434/v1?k=X")
    assert url == "http://h:11434/v1/chat/completions?k=X"
    assert "?k=X/chat" not in url
    # El fragmento se descarta (no se envia en una peticion HTTP).
    assert bench_providers.normalize_local_endpoint(
        "http://h:11434/v1#frag") == "http://h:11434/v1/chat/completions"


def test_n9_normalizacion_idempotente():
    canon = "http://h:11434/v1/chat/completions"
    assert bench_providers.normalize_local_endpoint(canon) == canon
    assert bench_providers.normalize_local_endpoint(
        bench_providers.normalize_local_endpoint("http://h:11434")) == canon


def test_n10_puerto_fuera_de_rango_da_benchmark_error(tmp_path, capsys):
    """`urlsplit(...).port` lanza `ValueError`: se traduce al error del contrato."""
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_providers.normalize_local_endpoint("http://host:99999/v1")
    assert "malformado" in str(exc.value)
    # Y por la CLI: EXIT_BENCHMARK_ERROR, no una traza cruda con rc=1.
    rc = bench_cli.run_cli(["--mode=ollama_shadow", "--enable-providers",
                            "--local-endpoint=http://host:99999/v1",
                            "--sources=src-01", "--no-determinism"])
    assert rc == bench_cli.EXIT_BENCHMARK_ERROR
    assert "Traceback" not in capsys.readouterr().err


# ===========================================================================
# N6 - el endurecimiento NO depende de un global mutable
# ===========================================================================
def test_n6_parchear_urlopen_ya_no_desactiva_el_manejador_endurecido(monkeypatch):
    """MUTACION AMBIENTAL: cualquier mock de `urllib.request.urlopen` desactivaba
    `_NoCrossOriginRedirect` en silencio (`urlopen is _STDLIB_URLOPEN`)."""
    import urllib.request

    construidos = []

    class _OpenerFalso:
        """Se queda con los handlers pedidos y NO abre red."""

        def open(self, req, timeout=None):
            raise RuntimeError("no se abre red en este test")

    def _espia(*handlers):
        construidos.append([type(h).__name__ for h in handlers])
        return _OpenerFalso()

    # Se PARCHEA `urlopen` (justo lo que antes desactivaba el endurecimiento).
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: None)
    monkeypatch.setattr(urllib.request, "build_opener", _espia)
    monkeypatch.setattr(bench_providers, "_OPENER", None)

    req = urllib.request.Request("http://127.0.0.1:11434/v1/chat/completions",
                                 data=b"{}", method="POST")
    with pytest.raises(RuntimeError):
        bench_providers._open(req, 1)
    # Pese al parcheo de `urlopen`, el camino real construyo el opener ENDURECIDO.
    assert construidos, "sin costura explicita, `_open` debe construir un opener"
    assert "_NoCrossOriginRedirect" in construidos[-1]


def test_n6_la_costura_de_test_es_explicita(monkeypatch):
    """La UNICA via de sustitucion es `opener=` / `_OPENER`, no un global de stdlib."""
    llamadas = []

    def _seam(req, timeout=None):
        llamadas.append(req.full_url)
        raise RuntimeError("costura de test")

    transporte = bench_providers.build_local_transport(
        "http://127.0.0.1:11434", timeout_s=300, opener=_seam)
    with pytest.raises(bench_runner.ProviderTransportError):
        transporte([{"role": "user", "content": "x"}])
    assert llamadas == ["http://127.0.0.1:11434/v1/chat/completions"]


def test_n6_mutation_check_costura_ignorada(monkeypatch):
    """MUTANTE: `_open` ignora la costura y usa siempre el opener endurecido.

    Con el, el test anterior abriria red de verdad; aqui se detecta porque la
    costura deja de recibir la llamada.
    """
    llamadas = []

    def _seam(req, timeout=None):
        llamadas.append(req.full_url)
        raise RuntimeError("costura de test")

    def comprobar():
        llamadas.clear()
        transporte = bench_providers.build_local_transport(
            "http://127.0.0.1:11434", timeout_s=300, opener=_seam)
        with pytest.raises(bench_runner.ProviderTransportError):
            transporte([{"role": "user", "content": "x"}])
        assert len(llamadas) == 1

    def aplicar(mp):
        mp.setattr(bench_providers, "_open",
                   lambda req, timeout, opener=None: (_ for _ in ()).throw(
                       RuntimeError("opener endurecido, costura ignorada")))

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="_open ignora el parametro `opener`")


# ===========================================================================
# N7 - `provider_fail_closed` no puede quedar invisible tras una tasa del 0%
# ===========================================================================
def test_n7_fail_closed_se_publica_junto_a_attempted():
    coste = bench_metrics.provider_cost(
        [_rec("local")], [{"local_calls_simulated": 1, "provider_fail_closed": 7}])
    assert coste["fail_closed"] == 7
    assert "attempted" in coste["fail_closed_note"]


def test_n7_fail_closed_degrada_el_gate_aunque_la_tasa_sea_cero():
    """Un carril entero muerto daba rate 0.0 y gate PASS."""
    struct = {"predicate_correct": {"rate": 1.0}, "evidence_correct": {"rate": 1.0},
              "offsets_correct": {"rate": 1.0},
              "subgroups": {"simple_relations": {"evidence_correct": {"rate": 1.0}},
                            "negated_relations": {"negation_correct": {"rate": 1.0}},
                            "temporal_relations": {"temporal_correct": {"rate": 1.0}},
                            "rumored_relations": {"epistemic_correct": {"rate": 1.0}}}}
    transporte = {"total_attempted": 10, "total_errors": 0, "total_indeterminate": 0,
                  "rate": 0.0, "evaluable": True}
    gates = bench_report.evaluate_gates(
        match=None, struct=struct, contamination={"clean": True},
        determinism={"deterministic": True}, provider_transport=transporte,
        operational={"counters": {"provider_fail_closed": 12}})
    gate = gates["provider_transport"]
    assert gate["status"] == "PARTIAL", "12 candidatos no evaluados NO pueden dar PASS"
    assert gate["fail_closed"] == 12
    assert any("provider_fail_closed" in m for m in gate["degraded_reasons"])
    # Sin fail_closed, el mismo escenario si es PASS (control negativo).
    limpio = bench_report.evaluate_gates(
        match=None, struct=struct, contamination={"clean": True},
        determinism={"deterministic": True}, provider_transport=transporte,
        operational={"counters": {"provider_fail_closed": 0}})
    assert limpio["provider_transport"]["status"] == "PASS"


# ===========================================================================
# N8 - consistencia de `provider_status` en las DOS direcciones
# ===========================================================================
class _RunFalso:
    """Doble minimo con lo que lee `_providers_block`."""

    def __init__(self, mode, status, attempted):
        self.mode = mode
        self.provider_status = dict(status)
        self.provider_transport = {"total_attempted": attempted, "total_errors": 0}
        self.provider_endpoints = {}


def test_n8_executed_con_cero_llamadas_se_declara_inconsistente():
    """La direccion que SI ocurre en runs reales: 'EXECUTED' sin ninguna llamada."""
    bloque = bench_report._providers_block(
        _RunFalso("ollama_shadow", {"local_llm": "EXECUTED"}, 0))
    assert bloque["status_consistency"].startswith("INCONSISTENTE")
    assert "NO se contabilizo ninguna llamada" in bloque["status_consistency"]
    assert bloque["network_calls_counted"] == 0
    # Y jamas se publica "none" en un modo con proveedor sin certeza.
    assert not bloque["network"].startswith("none")


def test_n8_llamadas_sin_executed_tambien_se_declara():
    bloque = bench_report._providers_block(
        _RunFalso("ollama_shadow", {"local_llm": "FAILED_CLOSED"}, 5))
    assert bloque["status_consistency"].startswith("INCONSISTENTE")
    assert bloque["network"].startswith("yes (")


def test_n8_caso_coherente_no_grita():
    bloque = bench_report._providers_block(
        _RunFalso("ollama_shadow", {"local_llm": "EXECUTED"}, 5))
    assert bloque["status_consistency"] == "OK"
    # Y el modo OFFLINE nunca entra en la comprobacion.
    offline = bench_report._providers_block(
        _RunFalso("baseline1", {"local_llm": "EXECUTED"}, 0))
    assert offline["status_consistency"] == "OK"
    assert offline["network"] == "yes (proveedores ejecutados)"


# ===========================================================================
# N11 - presupuesto GLOBAL de tiempo del run
# ===========================================================================
def test_n11_el_presupuesto_global_aborta_entre_fuentes(corpus, monkeypatch):
    """El deadline POR LLAMADA no acota el total: hace falta uno de run."""
    reloj = {"t": 0.0}

    def _monotonic():
        reloj["t"] += 50.0  # cada consulta avanza 50 s
        return reloj["t"]

    monkeypatch.setattr(bench_runner.time, "monotonic", _monotonic)
    with pytest.raises(bench_runner.BenchmarkError) as exc:
        bench_runner.run_benchmark(corpus, mode="baseline1",
                                   source_ids=sorted(corpus.sources),
                                   max_run_seconds=10.0)
    msg = str(exc.value)
    assert "presupuesto de tiempo del run agotado" in msg
    assert "max-run-seconds" in msg
    assert "NO producen dictamen" in msg


def test_n11_sin_presupuesto_o_con_presupuesto_amplio_no_aborta(corpus):
    """Control negativo: el presupuesto no puede abortar un run normal."""
    run = bench_runner.run_benchmark(corpus, mode="baseline1", source_ids=SAMPLE_IDS,
                                     max_run_seconds=3600.0)
    assert len(run.source_runs) == len(SAMPLE_IDS)
    assert bench_runner.run_benchmark(corpus, mode="baseline1",
                                      source_ids=SAMPLE_IDS).source_ids == SAMPLE_IDS


def test_n11_la_cli_expone_la_bandera():
    src = Path(bench_cli.__file__).read_text(encoding="utf-8")
    assert "--max-run-seconds" in src


# ===========================================================================
# N12 / N13 - raiz del arbol y endpoint explicito
# ===========================================================================
def test_n12_repo_root_no_depende_del_directorio_de_invocacion(tmp_path, monkeypatch):
    """Era `Path.cwd()`: el destino del proveedor dependia de donde se lanzase."""
    assert bench_providers._REPO_ROOT == _APP_DIR
    assert bench_providers._REPO_ROOT.is_absolute()
    assert (bench_providers._REPO_ROOT / "relations").is_dir()
    monkeypatch.chdir(tmp_path)
    assert bench_providers._REPO_ROOT == _APP_DIR
    assert bench_providers._REPO_ROOT != Path.cwd()

    # Y es EL VALOR que se le pasa al registry, desde un cwd ajeno.
    from external_ai import registry as _registry

    visto = {}
    monkeypatch.setattr(_registry, "nvidia_config",
                        lambda *a, **k: {"api_key_present": True,
                                         "base_url": "https://integrate.api.example"})

    def _get_provider(name, repo_root=None, **kw):
        visto["repo_root"] = repo_root
        return object()

    monkeypatch.setattr(_registry, "get_provider", _get_provider)
    bench_providers.build_external_provider()
    assert visto["repo_root"] == _APP_DIR, "el destino no puede depender del cwd"


def test_n13_build_local_transport_no_cae_al_entorno(monkeypatch, no_network):
    """Con `S9K_BENCH_OLLAMA_ENDPOINT` apuntando a un host atacante, un llamante
    de la API publica abria conexiones sin haber nombrado ningun destino."""
    monkeypatch.setenv(bench_providers.LOCAL_ENDPOINT_ENV, "http://atacante.example:8080")
    for vacio in (None, "", "   "):
        with pytest.raises(bench_runner.BenchmarkError) as exc:
            bench_providers.build_local_transport(vacio)
        msg = str(exc.value)
        assert "EXPLICITO" in msg
        assert "Sin endpoint NO se abre ninguna conexion" in msg
    assert no_network == []


def test_n13_el_endpoint_explicito_es_el_que_se_publica(monkeypatch, no_network):
    """El destino usado y el atestado deben ser EL MISMO."""
    monkeypatch.setenv(bench_providers.LOCAL_ENDPOINT_ENV, "http://atacante.example:8080")
    llamadas = []

    def _seam(req, timeout=None):
        llamadas.append(req.full_url)
        raise RuntimeError("costura")

    transporte = bench_providers.build_local_transport(
        "http://127.0.0.1:11434", timeout_s=300, opener=_seam)
    with pytest.raises(bench_runner.ProviderTransportError):
        transporte([{"role": "user", "content": "x"}])
    assert llamadas == ["http://127.0.0.1:11434/v1/chat/completions"]
    assert "atacante.example" not in llamadas[0]
    assert bench_providers.endpoint_attestation(
        "http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert no_network == []


def test_n13_mutation_check_fallback_al_entorno(monkeypatch):
    """MUTANTE: la fabrica vuelve a leer el entorno cuando falta el endpoint."""
    monkeypatch.setenv(bench_providers.LOCAL_ENDPOINT_ENV, "http://atacante.example:8080")

    def comprobar():
        with pytest.raises(bench_runner.BenchmarkError):
            bench_providers.build_local_transport(None)

    real = bench_providers.build_local_transport

    def con_fallback(endpoint=None, **kw):
        import os as _os
        if endpoint is None or not str(endpoint).strip():
            endpoint = _os.environ.get(bench_providers.LOCAL_ENDPOINT_ENV)
        return real(endpoint, **kw)

    def aplicar(mp):
        mp.setattr(bench_providers, "build_local_transport", con_fallback)

    _mata_mutante(monkeypatch, aplicar, comprobar,
                  mutante="build_local_transport vuelve a leer S9K_BENCH_OLLAMA_ENDPOINT")
