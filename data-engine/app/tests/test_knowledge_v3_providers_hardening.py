# -*- coding: utf-8 -*-
"""Endurecimiento del transporte y de la trazabilidad (ronda de revision).

Un fichero por ronda de hallazgos, con el identificador del revisor en cada
test, para que quede claro qué defecto concreto impide volver.

H1 · fuga de credenciales por redirect      H8  · KeyboardInterrupt tragado
H2 · Retry-After sin tope                   H9  · lectura no acotada
H3 · sin deadline de pared                  H10 · timeouts de politica muertos
H4 · RecursionError escapando               H13 · anclaje ambiguo silencioso
H5 · claves de decision sin normalizar
H6 · provider_trace por convencion
H7 · embeddings: 501 tratado como reintentable
"""
from __future__ import annotations

import http.server
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from external_processing.capabilities import Capability
from external_processing.errors import (
    InputTooLargeError,
    ProviderUnavailableError,
    RateLimitError,
    TimeoutError as ProcTimeoutError,
    UnsupportedCapabilityError,
)
from external_processing.http_safe import (
    MAX_RETRY_AFTER_SECONDS,
    RedirectRejectedError,
    build_safe_opener,
    cap_retry_after,
    read_bounded,
)
from external_processing.provider import ExternalProcessingProvider
from external_processing.providers.nvidia import NvidiaProcessingProvider
from external_processing.providers.ollama import (
    PERMANENT_HTTP_STATUS,
    OllamaProcessingProvider,
)
from knowledge_v3.providers import (
    AmbiguousAnchorError,
    Budget,
    GuardError,
    ProviderRouter,
    RoutingPolicy,
    Tier,
    UnverifiedAttributionError,
    V3Capability,
    assert_size,
    guard_provider_result,
    mentions_from_extraction,
    sanitize_model,
)

from tests.test_knowledge_v3_providers_support import (
    DrippingResponse,
    FakeResponse,
    FakeTransport,
    UnboundedReadResponse,
    http_error,
    make_anchor,
    make_outcome,
    nvidia_chat_response,
    ollama_chat_response,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CLAVE = "nvapi-CLAVE-QUE-NO-DEBE-VIAJAR-0123456789"


# ==========================================================================
# H1 — Fuga de la API key por redirect
# ==========================================================================
class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    """Servidor 'atacante': apunta todo lo que le llega."""

    received: list = []

    def do_POST(self):  # noqa: N802
        type(self).received.append(dict(self.headers))
        body = b'{"choices":[{"message":{"content":"{\\"robado\\": true}"}}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST

    def log_message(self, *a):  # silencio en los tests
        pass


def _make_redirect_handler(destino: str):
    class _RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.send_response(302)
            self.send_header("Location", destino)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST

        def log_message(self, *a):
            pass

    return _RedirectHandler


def _serve(handler):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


@pytest.fixture
def atacante_y_redirector():
    """Dos servidores reales: uno redirige al otro, que apunta las cabeceras."""
    _RecordingHandler.received = []
    atacante = _serve(_RecordingHandler)
    destino = f"http://127.0.0.1:{atacante.server_address[1]}/robado"
    redirector = _serve(_make_redirect_handler(destino))
    try:
        yield redirector, atacante
    finally:
        redirector.shutdown()
        atacante.shutdown()


def test_h1_urllib_por_defecto_SI_filtraria_la_key(atacante_y_redirector):
    """Control: demuestra que el agujero era real y no teorico.

    Con el `urlopen` estandar, un 302 a OTRO host se sigue y la cabecera
    `Authorization` viaja con el. Este test documenta el ataque; el siguiente
    demuestra que el opener endurecido lo corta.
    """
    redirector, atacante = atacante_y_redirector
    req = urllib.request.Request(
        f"http://127.0.0.1:{redirector.server_address[1]}/v1/chat/completions",
        data=b"{}",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {CLAVE}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()

    filtradas = [h for h in _RecordingHandler.received if "Authorization" in h]
    assert filtradas, "el escenario del ataque no se ha reproducido"
    assert CLAVE in filtradas[0]["Authorization"]


def test_h1_el_opener_endurecido_rechaza_el_redirect(atacante_y_redirector):
    redirector, atacante = atacante_y_redirector
    opener = build_safe_opener()
    req = urllib.request.Request(
        f"http://127.0.0.1:{redirector.server_address[1]}/v1/chat/completions",
        data=b"{}",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {CLAVE}"},
        method="POST",
    )
    with pytest.raises(RedirectRejectedError):
        opener.open(req, timeout=10)
    assert _RecordingHandler.received == [], "la key ha viajado al host atacante"


def test_h1_nvidia_no_sigue_redirects_y_la_key_no_viaja(atacante_y_redirector):
    """El proveedor real, de extremo a extremo, contra servidores reales."""
    redirector, atacante = atacante_y_redirector
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url=f"http://127.0.0.1:{redirector.server_address[1]}/v1",
        api_key_getter=lambda: CLAVE,
        timeout_seconds=10,
    )
    with pytest.raises(ProviderUnavailableError) as exc:
        provider.chat_json([{"role": "user", "content": "hola"}])

    assert _RecordingHandler.received == [], "la API key ha llegado al atacante"
    assert CLAVE not in str(exc.value)


def test_h1_ollama_tampoco_sigue_redirects(atacante_y_redirector):
    """Ollama no lleva credencial, pero un 302 seguido sigue siendo SSRF."""
    redirector, atacante = atacante_y_redirector
    provider = OllamaProcessingProvider(
        base_url=f"http://127.0.0.1:{redirector.server_address[1]}",
        timeout_seconds=10,
        max_retries=0,
    )
    with pytest.raises(ProviderUnavailableError):
        provider.chat_json([{"role": "user", "content": "hola"}])
    assert _RecordingHandler.received == []


def test_h1_el_error_de_redirect_no_revela_la_url_entera():
    """La `Location` puede llevar credenciales en el userinfo: solo el host."""
    exc = RedirectRejectedError(302, "https://user:secreto@malo.example/captura")
    assert "secreto" not in str(exc)
    assert "malo.example" in str(exc)


# ==========================================================================
# H2 — Retry-After sin tope
# ==========================================================================
def test_h2_retry_after_absurdo_queda_acotado():
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-X",
        urlopen=FakeTransport([http_error(429, headers={"Retry-After": "99999999"})]),
    )
    with pytest.raises(RateLimitError) as exc:
        provider.chat_json([{"role": "user", "content": "hola"}])
    assert exc.value.retry_after == MAX_RETRY_AFTER_SECONDS


@pytest.mark.parametrize(
    "valor,esperado",
    [("30", 30.0), ("0", 0.0), ("99999999", 60.0), ("-5", 0.0), ("manana", 0.0),
     (None, 0.0), ("inf", 0.0), ("nan", 0.0)],
)
def test_h2_cap_retry_after_normaliza_todo(valor, esperado):
    assert cap_retry_after(valor) == esperado


def test_h2_un_retry_after_razonable_se_respeta():
    """Acotar no es ignorar: por debajo del tope, se obedece al proveedor."""
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-X",
        urlopen=FakeTransport([http_error(429, headers={"Retry-After": "12"})]),
    )
    with pytest.raises(RateLimitError) as exc:
        provider.chat_json([{"role": "user", "content": "hola"}])
    assert exc.value.retry_after == 12.0


# ==========================================================================
# H3 — Deadline de pared
# ==========================================================================
def test_h3_servidor_goteante_no_retiene_el_hilo_indefinidamente():
    goteo = DrippingResponse()
    t0 = time.monotonic()
    with pytest.raises(ProcTimeoutError, match="plazo total"):
        read_bounded(goteo, max_bytes=10_000_000, deadline=t0 + 0.2)
    assert time.monotonic() - t0 < 5.0
    assert goteo.calls > 0


def test_h3_nvidia_corta_una_respuesta_a_goteo():
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-X",
        timeout_seconds=1,
        urlopen=FakeTransport([DrippingResponse(delay=0.001)]),
    )
    t0 = time.monotonic()
    with pytest.raises(ProcTimeoutError):
        provider.chat_json([{"role": "user", "content": "hola"}])
    assert time.monotonic() - t0 < 10.0


def test_h3_ollama_corta_una_respuesta_a_goteo():
    provider = OllamaProcessingProvider(
        base_url="http://x:1",
        timeout_seconds=1,
        max_retries=0,
        urlopen=FakeTransport([DrippingResponse(delay=0.001)]),
    )
    with pytest.raises(ProcTimeoutError):
        provider.chat_json([{"role": "user", "content": "hola"}])


def test_h3_una_respuesta_normal_no_se_ve_afectada():
    """Control: el deadline no rompe el camino feliz."""
    provider = OllamaProcessingProvider(
        base_url="http://x:1",
        timeout_seconds=30,
        max_retries=0,
        urlopen=FakeTransport([ollama_chat_response({"ok": True})]),
    )
    assert provider.chat_json([{"role": "user", "content": "hola"}])["parsed"] == {"ok": True}


# ==========================================================================
# H9 — La respuesta se corta ANTES de cargarla en memoria
# ==========================================================================
def test_h9_nunca_se_llama_a_read_sin_limite():
    """Mutante que este test mata: volver a `resp.read()` a pelo."""
    doble = UnboundedReadResponse(ollama_chat_response({"ok": True}))
    provider = OllamaProcessingProvider(
        base_url="http://x:1", max_retries=0, urlopen=FakeTransport([doble])
    )
    provider.chat_json([{"role": "user", "content": "hola"}])
    assert doble.reads, "no se ha leido nada"
    assert all(n is not None for n in doble.reads)


def test_h9_nvidia_tampoco_lee_sin_limite():
    doble = UnboundedReadResponse(nvidia_chat_response({"ok": True}))
    provider = NvidiaProcessingProvider(
        REPO_ROOT,
        base_url="https://nvidia.test/v1",
        api_key_getter=lambda: "nvapi-X",
        urlopen=FakeTransport([doble]),
    )
    provider.chat_json([{"role": "user", "content": "hola"}])
    assert all(n is not None for n in doble.reads)


def test_h9_no_se_pide_mas_de_lo_que_falta_para_pasarse_del_tope():
    """Se detecta el exceso con un byte, no materializando la respuesta."""
    gigante = FakeResponse(None, raw=b"x" * 100_000)
    with pytest.raises(InputTooLargeError):
        read_bounded(gigante, max_bytes=1000)
    assert sum(n for n in gigante.reads if n) <= 1001


def test_h9_lectura_exacta_en_el_limite_no_falla():
    """Control de frontera: justo el tope es valido."""
    exacto = FakeResponse(None, raw=b"x" * 1000)
    assert len(read_bounded(exacto, max_bytes=1000)) == 1000


# ==========================================================================
# H4 — RecursionError escapando de las guardas
# ==========================================================================
def _anidado(niveles: int) -> dict:
    raiz: dict = {}
    actual = raiz
    for _ in range(niveles):
        actual["n"] = {}
        actual = actual["n"]
    return raiz


def test_h4_diez_mil_niveles_dan_guard_error_no_recursion_error():
    with pytest.raises(GuardError):
        assert_size(_anidado(10_000))


def test_h4_guard_provider_result_no_deja_escapar_recursion_error():
    """Antes salia un `RuntimeError` que nadie trataba como respuesta invalida."""
    try:
        guard_provider_result(_anidado(10_000))
    except GuardError:
        pass
    except RecursionError:  # pragma: no cover - es justo lo que no debe pasar
        pytest.fail("RecursionError ha escapado de guard_provider_result")


def test_h4_el_router_convierte_el_anidamiento_en_fallo_limpio():
    class _Hondo(ExternalProcessingProvider):
        provider_name = "hondo"
        capabilities = {Capability.EXTRACT_TEXT_ENTITIES}

        def execute(self, job):
            return {"provider": "hondo", "payload": _anidado(10_000)}

    router = ProviderRouter(budget=Budget(0, 0.0))
    router.register(_Hondo(), Tier.OLLAMA)
    outcome = router.run(
        V3Capability.EXTRACTION,
        workspace="leyenda",
        source_id="s",
        payload={"text": "x"},
        max_attempts=1,
    )
    assert not outcome.ok
    assert outcome.error_code == "GUARD_REJECTED"


# ==========================================================================
# H5 — Claves de decision normalizadas
# ==========================================================================
@pytest.mark.parametrize(
    "clave",
    ["approvedBy", "Approved_By", "APPROVED", " approved ", "is_approved",
     "isApproved", "localApproval", "decisionHash", "planHash", "auto_approved",
     "approval_status", "signature"],
)
def test_h5_las_variantes_de_clave_de_decision_se_cortan(clave):
    from knowledge_v3.providers import ForbiddenContractError, assert_not_a_decision

    with pytest.raises(ForbiddenContractError):
        assert_not_a_decision({"payload": {clave: True}})


def test_h5_una_clave_legitima_parecida_no_se_bloquea():
    """`approval_notes` no es una decision; no puede caer por parecido."""
    from knowledge_v3.providers import assert_not_a_decision

    assert_not_a_decision({"payload": {"approval_notes_from_text": "el rey aprobo"}})


# ==========================================================================
# H6 — provider_trace verificada, no convenida
# ==========================================================================
def test_h6_una_atribucion_escrita_a_mano_ya_no_cuela():
    from knowledge_v3.providers import ProviderAttribution

    a_mano = ProviderAttribution(
        tier=Tier.LOCAL, name="s9k", version="3.0.0", step="x", model=None
    )
    with pytest.raises(UnverifiedAttributionError):
        mentions_from_extraction(
            make_anchor(),
            {"mentions": [{"surface": "Daiki", "type": "Character"}]},
            attribution=a_mano,
            evidence_fragment_ids=["fragment:p12:0"],
        )


def test_h6_la_atribucion_derivada_conserva_el_tier_real():
    """Un resultado EXTERNAL no puede acabar declarandose local."""
    outcome = make_outcome(tier=Tier.EXTERNAL, provider_name="nvidia",
                           model="meta/llama-3.3-70b-instruct")
    attribution = outcome.attribution(name="s9k.extractor")
    assert attribution.tier is Tier.EXTERNAL
    assert attribution.verified is True

    mentions, _ = mentions_from_extraction(
        make_anchor(),
        {"mentions": [{"surface": "Daiki", "type": "Character", "confidence": 0.9}]},
        attribution=attribution,
        evidence_fragment_ids=["fragment:p12:0"],
    )
    from knowledge_v3.contracts import producing_step

    assert producing_step(mentions[0].to_dict())["provider"] == "external"


def test_h6_el_llamante_no_puede_elegir_tier_ni_model():
    """La API sancionada sólo admite nombre y version del mapeador."""
    import inspect

    from knowledge_v3.providers import ProviderOutcome

    params = set(inspect.signature(ProviderOutcome.attribution).parameters)
    assert "tier" not in params
    assert "model" not in params
    assert "provider_name" not in params


@pytest.mark.parametrize(
    "sucio",
    ["x" * 300, "modelo con espacios", "qwen\n2.5", "<script>alert(1)</script>", ""],
)
def test_h6_un_model_envenenado_se_registra_como_none(sucio):
    assert sanitize_model(sucio) is None


@pytest.mark.parametrize("limpio", ["qwen2.5:7b", "meta/llama-3.3-70b-instruct",
                                    "nvidia/nv-embedqa-e5-v5"])
def test_h6_los_modelos_reales_sobreviven_al_saneado(limpio):
    assert sanitize_model(limpio) == limpio


def test_h6_el_model_llega_saneado_a_la_traza():
    outcome = make_outcome(model="modelo inventado con espacios y  basura")
    attribution = outcome.attribution(name="s9k.extractor")
    assert attribution.model is None

    mentions, _ = mentions_from_extraction(
        make_anchor(),
        {"mentions": [{"surface": "Daiki", "type": "Character", "confidence": 0.9}]},
        attribution=attribution,
        evidence_fragment_ids=["fragment:p12:0"],
    )
    mentions[0].validate()


def test_h6_no_se_atribuye_un_resultado_fallido():
    outcome = make_outcome(ok=False, tier=None)
    with pytest.raises(ValueError):
        outcome.attribution(name="s9k.extractor")


def test_h6_mutacion_si_se_quita_la_verificacion_el_engano_pasa():
    """Demuestra que es `_require_verified` quien corta, y no otra cosa."""
    from knowledge_v3.providers import ProviderAttribution, proposals

    a_mano = ProviderAttribution(
        tier=Tier.LOCAL, name="s9k", version="3.0.0", step="x", model=None
    )
    original = proposals._require_verified
    try:
        proposals._require_verified = lambda _a: None
        mentions, _ = mentions_from_extraction(
            make_anchor(),
            {"mentions": [{"surface": "Daiki", "type": "Character", "confidence": 0.9}]},
            attribution=a_mano,
            evidence_fragment_ids=["fragment:p12:0"],
        )
        assert mentions, "sin la guarda, la atribucion falsa pasaria"
    finally:
        proposals._require_verified = original


# ==========================================================================
# H7 — Embeddings: el servidor real responde 501
# ==========================================================================
def test_h7_501_es_permanente_y_no_se_reintenta():
    """Comportamiento REAL del servidor sin `--embeddings`: HTTP 501."""
    transport = FakeTransport([http_error(501)])
    provider = OllamaProcessingProvider(
        base_url="http://x:1", max_retries=3, embeddings=True, urlopen=transport
    )
    with pytest.raises(UnsupportedCapabilityError):
        provider.embed(["hola"])
    assert transport.calls == 1, "un 501 no es transitorio: reintentarlo es gastar tiempo"


@pytest.mark.parametrize("status", sorted(PERMANENT_HTTP_STATUS))
def test_h7_los_estados_permanentes_no_se_reintentan(status):
    transport = FakeTransport([http_error(status)])
    provider = OllamaProcessingProvider(
        base_url="http://x:1", max_retries=3, urlopen=transport
    )
    with pytest.raises(UnsupportedCapabilityError):
        provider.chat_json([{"role": "user", "content": "hola"}])
    assert transport.calls == 1


def test_h7_un_500_si_se_reintenta(monkeypatch):
    """Control: distinguir permanente de transitorio, no bloquearlo todo."""
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    transport = FakeTransport([http_error(500)])
    provider = OllamaProcessingProvider(
        base_url="http://x:1", max_retries=2, urlopen=transport
    )
    with pytest.raises(ProviderUnavailableError):
        provider.chat_json([{"role": "user", "content": "hola"}])
    assert transport.calls == 3


def test_h7_el_camino_200_con_error_sigue_cubierto():
    """Algunas versiones responden 200 + {"error": ...}: tambien permanente."""
    provider = OllamaProcessingProvider(
        base_url="http://x:1",
        max_retries=0,
        embeddings=True,
        urlopen=FakeTransport(
            [{"error": "This server does not support embeddings. Start it with `--embeddings`"}]
        ),
    )
    with pytest.raises(UnsupportedCapabilityError, match="embeddings"):
        provider.embed(["hola"])


# ==========================================================================
# H8 — Cancelar tiene que cancelar
# ==========================================================================
@pytest.mark.parametrize("senal", [KeyboardInterrupt, SystemExit])
def test_h8_las_senales_de_parada_no_se_convierten_en_fallo_de_proveedor(senal):
    class _Interrumpe(ExternalProcessingProvider):
        provider_name = "interrumpe"
        capabilities = {Capability.EXTRACT_TEXT_ENTITIES}

        def execute(self, job):
            raise senal()

    router = ProviderRouter(budget=Budget(0, 0.0))
    router.register(_Interrumpe(), Tier.OLLAMA)
    with pytest.raises(senal):
        router.run(
            V3Capability.EXTRACTION,
            workspace="leyenda",
            source_id="s",
            payload={"text": "x"},
            max_attempts=1,
        )


# ==========================================================================
# H10 — Los timeouts de la politica se aplican de verdad
# ==========================================================================
def test_h10_el_router_aplica_el_timeout_del_tier_al_registrar():
    policy = RoutingPolicy(
        timeout_seconds_by_tier={Tier.LOCAL: 11, Tier.OLLAMA: 22, Tier.EXTERNAL: 33}
    )
    router = ProviderRouter(policy=policy, budget=Budget(0, 0.0))
    ollama = OllamaProcessingProvider(base_url="http://x:1", urlopen=FakeTransport([{}]))
    router.register(ollama, Tier.OLLAMA)
    assert ollama.timeout_seconds == 22


def test_h10_se_puede_pinchar_un_timeout_propio():
    policy = RoutingPolicy(timeout_seconds_by_tier={Tier.OLLAMA: 22})
    router = ProviderRouter(policy=policy, budget=Budget(0, 0.0))
    ollama = OllamaProcessingProvider(
        base_url="http://x:1", timeout_seconds=7, urlopen=FakeTransport([{}])
    )
    router.register(ollama, Tier.OLLAMA, apply_policy_timeout=False)
    assert ollama.timeout_seconds == 7


# ==========================================================================
# H13 — Anclaje ambiguo
# ==========================================================================
AMBIGUO = "Umbra cayo. Umbra ardio."


def test_h13_un_literal_repetido_no_se_ancla_a_la_primera_ocurrencia():
    with pytest.raises(AmbiguousAnchorError):
        make_anchor(text=AMBIGUO).locate("Umbra")


def test_h13_la_mencion_ambigua_se_descarta_con_codigo():
    mentions, codes = mentions_from_extraction(
        make_anchor(text=AMBIGUO),
        {"mentions": [{"surface": "Umbra", "type": "Location", "confidence": 0.9}]},
        attribution=make_outcome().attribution(name="s9k.extractor"),
        evidence_fragment_ids=["fragment:p12:0"],
    )
    assert mentions == ()
    assert "PROVIDER_MENTION_AMBIGUOUS_ANCHOR" in codes


def test_h13_un_literal_unico_sigue_anclando():
    """Control: la guarda no rompe el caso normal."""
    start, end = make_anchor(text=AMBIGUO).locate("cayo")
    assert AMBIGUO[start:end] == "cayo"


def test_h13_la_evidencia_ambigua_se_rechaza():
    from knowledge_v3.providers import evidence_fragment_from_text

    with pytest.raises(AmbiguousAnchorError):
        evidence_fragment_from_text(
            make_anchor(text=AMBIGUO),
            fragment_id="fragment:x:0",
            literal_text="Umbra",
            media_type="EMBEDDED_TEXT",
            attribution=make_outcome().attribution(name="s9k.extractor"),
        )
