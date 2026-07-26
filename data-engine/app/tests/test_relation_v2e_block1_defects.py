# -*- coding: utf-8 -*-
"""BLOQUE 1 de "Motor V2 temporal, episodico y trazable" — cierre de defectos.

Cada test de este fichero ataca UN defecto concreto de la lista abierta de
`docs/relation-engine-v2-results.md` §8 y ejercita la RUTA REAL, no un alias.
Junto a cada invariante se documenta que MUTACION del codigo de produccion lo pone
en rojo (los mutantes se ejecutaron de verdad; ver
`artifacts/relation-v2e/blocks/b01/mutation-log.md`).

Defectos cubiertos:

  * B5-D4 — retencion global de texto crudo en la cache sintactica.
  * B5-D7 — el objeto cacheado se compartia por identidad.
  * B7    — dos envolventes de aceptacion (`TIER_NORMALIZED` inalcanzable en real).
  * B7    — `validate_external_verdict` sin llamador de produccion.
  * Negacion — el gate `negation` no podia ponerse rojo (medía RECALL).

NO se toca el corpus, ni el ground truth, ni `THRESHOLDS`, ni los defaults del motor
(hay un test explicito que lo verifica al final).
"""
from __future__ import annotations

import pytest

from relations import evidence_realignment as realign
from relations import external_consult as consult
from relations import external_ai_shadow as shadow
from relations import pipeline as pipe
from relations import syntax as syn
from relations.abstention import AbstentionPolicy
from relations.benchmark import metrics as bench_metrics
from relations.benchmark import report as bench_report


# ===========================================================================
# 1. B5-D4 — la cache no retiene texto crudo, esta acotada y esta aislada
# ===========================================================================
TEXTO_A = "Kael rompio el pacto en el valle de Ysera."
TEXTO_B = "Marcus juro lealtad a Kael en Neverwinter."


def _cache(**kw) -> syn.CachingSyntaxAnalyzer:
    return syn.CachingSyntaxAnalyzer(syn.HeuristicSyntaxAnalyzer(), **kw)


def test_la_clave_de_la_cache_NO_es_el_texto_crudo():
    """B5-D4: antes la clave era `(text, language)` y retenia el texto DOS veces.

    MUTANTE: devolver `(self._scope, language, text, len(text))` en `_key` ->
    este test se pone rojo.
    """
    c = _cache(scope="doc-1")
    c.analyze(TEXTO_A)
    claves = list(c._cache.keys())
    assert len(claves) == 1
    plano = repr(claves[0])
    assert TEXTO_A not in plano
    for trozo in TEXTO_A.split():
        assert trozo not in plano, f"la clave filtra el token {trozo!r} del documento"
    # Y la huella es la que dice ser (misma regla, no un valor cualquiera).
    assert syn._digest(TEXTO_A) in plano


def test_la_cache_esta_AISLADA_POR_AMBITO_y_purga_al_cambiar():
    """B5-D4: el texto del workspace A no sobrevive al pasar al B.

    MUTANTE: no limpiar `self._cache` en `set_scope` -> rojo (queda la entrada de A).
    """
    c = _cache(scope="ws-a|doc-1")
    c.analyze(TEXTO_A)
    assert c.stats()["size"] == 1
    c.set_scope("ws-b|doc-2")
    assert c.stats()["size"] == 0, "el ambito nuevo hereda la retencion del anterior"
    assert c.scope == "ws-b|doc-2"
    # El mismo texto en el ambito nuevo es un MISS: no hay acierto entre ambitos.
    antes = c.misses
    c.analyze(TEXTO_A)
    assert c.misses == antes + 1


def test_dos_ambitos_distintos_no_comparten_entrada():
    a = _cache(scope="ws-a")
    b = _cache(scope="ws-b")
    a.analyze(TEXTO_A)
    b.analyze(TEXTO_A)
    assert set(a._cache) & set(b._cache) == set(), "la clave no discrimina el ambito"


def test_la_cache_CADUCA_por_antiguedad_no_solo_por_LRU():
    """B5-D4: no habia TTL; con 512 huecos libres una entrada vivia para siempre.

    Reloj INYECTADO: el test no duerme y no depende del reloj real.
    MUTANTE: `ttl_seconds=None` por defecto, o quitar `_purge_expired` -> rojo.
    """
    reloj = {"t": 0.0}
    c = _cache(scope="doc-1", ttl_seconds=10.0, clock=lambda: reloj["t"])
    c.analyze(TEXTO_A)
    reloj["t"] = 5.0
    c.analyze(TEXTO_A)
    assert c.hits == 1, "dentro del TTL debe acertar"
    reloj["t"] = 15.0
    c.analyze(TEXTO_A)
    assert c.hits == 1, "pasado el TTL NO puede acertar"
    assert c.expirations >= 1
    assert c.stats()["expirations"] >= 1


def test_un_acierto_NO_renueva_el_TTL():
    """La entrada caduca por ANTIGUEDAD. Si el acierto renovase el reloj, un texto
    muy pedido quedaria retenido indefinidamente: seria el defecto otra vez."""
    reloj = {"t": 0.0}
    c = _cache(scope="doc-1", ttl_seconds=10.0, clock=lambda: reloj["t"])
    c.analyze(TEXTO_A)
    for t in (2.0, 4.0, 6.0, 8.0):
        reloj["t"] = t
        c.analyze(TEXTO_A)
    assert c.hits == 4
    reloj["t"] = 11.0
    c.analyze(TEXTO_A)
    assert c.hits == 4, "el TTL se reinicio con los aciertos"


def test_desalojo_LRU_real_y_metricas_de_la_cache():
    """MUTANTE: quitar el `popitem(last=False)` -> el tamano crece y esto es rojo."""
    c = _cache(scope="doc-1", maxsize=3, ttl_seconds=None)
    for i in range(10):
        c.analyze(f"segmento numero {i}")
    st = c.stats()
    assert st["size"] == 3
    assert st["misses"] == 10
    assert st["hits"] == 0
    assert st["evictions"] == 7
    assert st["maxsize"] == 3
    assert st["scope"] == "doc-1"
    assert set(st) == {"scope", "size", "maxsize", "ttl_seconds", "hits", "misses",
                       "evictions", "expirations"}


def test_proceso_LONGEVO_no_crece_sin_limite_ni_retiene_al_final():
    """Proceso longevo simulado: 3 documentos x 400 segmentos distintos.

    Comprueba lo que el defecto describia: (a) la memoria no crece sin techo, y
    (b) al cerrar el ambito no queda NADA retenido.
    """
    c = _cache(scope="doc-0", maxsize=50, ttl_seconds=None)
    for doc in range(3):
        c.set_scope(f"ws-{doc}|doc-{doc}")
        for i in range(400):
            c.analyze(f"documento {doc} segmento {i}: Kael y Ysera")
        assert c.stats()["size"] <= 50
    c.cache_clear()
    assert c.stats()["size"] == 0
    assert c._cache == {}


def test_reset_default_analyzer_DESCARTA_el_singleton_de_modulo():
    """B5-D4: `cache_clear()` vaciaba la cache pero el singleton seguia vivo todo el
    proceso, y no habia NINGUNA API para soltarlo ni ningun llamador.

    MUTANTE: que `reset_default_analyzer` solo llame a `cache_clear()` sin poner
    `_DEFAULT_ANALYZER = None` -> rojo (el objeto seria el mismo).
    """
    a = syn.get_default_analyzer()
    a.analyze(TEXTO_A)
    syn.reset_default_analyzer()
    b = syn.get_default_analyzer()
    assert b is not a, "el singleton no se solto"
    assert b.stats()["size"] == 0
    assert "reset_default_analyzer" in syn.__all__
    syn.reset_default_analyzer()  # idempotente
    syn.reset_default_analyzer()


def test_el_analizador_de_PRODUCCION_nace_con_TTL_y_con_tope():
    """El TTL no vale de nada si el analizador que usa el pipeline nace sin el.

    MUTANTE: `DEFAULT_CACHE_TTL_SECONDS = None` -> rojo (sobrevivio a la primera
    ronda de mutantes: los tests de TTL inyectaban el valor a mano).
    """
    assert isinstance(syn.DEFAULT_CACHE_TTL_SECONDS, (int, float))
    assert not isinstance(syn.DEFAULT_CACHE_TTL_SECONDS, bool)
    assert syn.DEFAULT_CACHE_TTL_SECONDS > 0

    a = syn.new_scoped_analyzer("ws|doc|exec")
    st = a.stats()
    assert st["ttl_seconds"] == syn.DEFAULT_CACHE_TTL_SECONDS
    assert st["maxsize"] == syn._DEFAULT_CACHE_MAXSIZE == 512

    # Y el singleton de proceso tampoco puede nacer sin caducidad.
    syn.reset_default_analyzer()
    assert syn.get_default_analyzer().stats()["ttl_seconds"] == syn.DEFAULT_CACHE_TTL_SECONDS
    syn.reset_default_analyzer()


def test_new_scoped_analyzer_exige_ambito():
    with pytest.raises(syn.SyntaxAdapterError):
        syn.new_scoped_analyzer("   ")
    with pytest.raises(syn.SyntaxAdapterError):
        _cache(ttl_seconds=0)
    with pytest.raises(syn.SyntaxAdapterError):
        _cache(maxsize=0)


# --- La ruta REAL: el pipeline ya no usa el singleton de proceso ------------
def _payload(ws: str, doc: str) -> dict:
    return {
        "workspace": ws,
        "document_id": doc,
        "segments": [{
            "segment_id": "seg-1",
            "text": "Kael rompio el pacto con Ysera en el valle.",
            "entities": [
                {"id": "kael", "name": "Kael", "type": "Character", "start": 0, "end": 4},
                {"id": "ysera", "name": "Ysera", "type": "Character", "start": 30, "end": 35},
            ],
        }],
    }


def test_RUTA_REAL_el_pipeline_usa_un_analizador_POR_EJECUCION(monkeypatch):
    """B5-D4 en el punto que lo consumia: `pipeline._process_segment`.

    MUTANTE: volver a `safe_analyze(get_default_analyzer(), text)` -> rojo, porque
    no se crea ningun analizador con ambito y el singleton se comparte entre
    workspaces.
    """
    creados: list = []
    real = syn.new_scoped_analyzer

    def _espia(scope, **kw):
        obj = real(scope, **kw)
        creados.append(obj)
        return obj

    monkeypatch.setattr(pipe, "new_scoped_analyzer", _espia)

    syn.reset_default_analyzer()
    singleton = syn.get_default_analyzer()

    pipe.run_pipeline(_payload("ws-alfa", "doc-1"))
    pipe.run_pipeline(_payload("ws-beta", "doc-2"))

    assert len(creados) == 2, "no se creo un analizador por ejecucion"
    assert creados[0] is not creados[1]
    ambitos = [a.scope for a in creados]
    assert ambitos[0].startswith("ws-alfa|doc-1|")
    assert ambitos[1].startswith("ws-beta|doc-2|")
    assert len(set(ambitos)) == 2
    # El singleton de proceso NO se toco: el pipeline ya no lo usa.
    assert singleton.stats()["size"] == 0
    # Y ninguna cache sobrevive con contenido al final de su corrida.
    for a in creados:
        assert a.stats()["size"] == 0, "queda texto del documento retenido tras la corrida"


def test_RUTA_REAL_las_metricas_de_cache_llegan_a_la_traza():
    """Las metricas viven en la OBSERVABILIDAD, no en `summary`: meterlas en
    `summary` cambiaria el `result_hash` funcional de salidas identicas."""
    out = pipe.run_pipeline(_payload("ws-alfa", "doc-1"))
    eventos = [e for e in out["observability"]["events"]
               if e["component"] == "pipeline.syntax_cache"]
    assert len(eventos) == 1
    m = eventos[0]["metrics"]
    assert set(m) == {"hits", "misses", "evictions", "expirations", "size"}
    assert all(isinstance(v, int) for v in m.values())
    assert m["misses"] >= 1
    assert "syntax_cache" not in str(out["summary"])


def test_RUTA_REAL_el_result_hash_no_depende_de_la_cache():
    """Neutralidad: la correccion de B5-D4 no puede mover la salida funcional."""
    a = pipe.run_pipeline(_payload("ws-alfa", "doc-1"))
    b = pipe.run_pipeline(_payload("ws-alfa", "doc-1"))
    assert a["result_hash"] == b["result_hash"]
    assert a["execution_id"] == b["execution_id"]


# ===========================================================================
# 2. B5-D7 — nadie puede contaminar a nadie a traves de la cache
# ===========================================================================
def test_un_llamador_NO_puede_contaminar_a_otro_via_la_cache():
    """B5-D7: `SyntaxAnalysis` es `frozen`, pero `object.__setattr__` lo salta y el
    objeto cacheado se devolvia POR IDENTIDAD a todos los llamadores.

    MUTANTE: `return entry[1]` en vez de `copy.deepcopy(entry[1])` -> rojo.
    MUTANTE: guardar `result` en vez de `copy.deepcopy(result)` -> rojo (el
    contaminador seria el propio primer llamador, que recibe el objeto guardado).
    """
    c = _cache(scope="doc-1")
    primero = c.analyze(TEXTO_A)
    object.__setattr__(primero, "text", "TEXTO ENVENENADO")
    object.__setattr__(primero, "quality", -99.0)

    segundo = c.analyze(TEXTO_A)
    assert c.hits == 1, "el segundo llamador debe estar acertando en la cache"
    assert segundo.text == TEXTO_A
    assert segundo.quality != -99.0
    assert segundo is not primero

    tercero = c.analyze(TEXTO_A)
    assert tercero is not segundo, "dos llamadores comparten objeto por identidad"
    assert tercero.text == TEXTO_A


def test_la_contaminacion_alcanza_tambien_a_las_estructuras_anidadas():
    """La copia es PROFUNDA: mutar una frase o un token tampoco viaja.

    Se envenena el objeto devuelto en un ACIERTO (no en el fallo inicial): con una
    copia superficial ese objeto comparte la tupla `sentences` con lo guardado, asi
    que la contaminacion SI llegaria al tercer llamador.

    MUTANTE: `dataclasses.replace(entry[1])` (copia superficial) -> rojo.
    MUTANTE: `copy.copy(entry[1])` -> rojo por la misma razon.
    """
    c = _cache(scope="doc-1")
    c.analyze(TEXTO_A)                 # fallo: llena la cache
    segundo = c.analyze(TEXTO_A)       # ACIERTO: este es el que se envenena
    assert c.hits == 1
    assert segundo.sentences, "el analizador heuristico debe producir frases"

    frase = segundo.sentences[0]
    object.__setattr__(frase, "text", "FRASE ENVENENADA")
    assert frase.tokens, "el analizador heuristico debe producir tokens"
    object.__setattr__(frase.tokens[0], "text", "TOKEN ENVENENADO")

    tercero = c.analyze(TEXTO_A)
    assert c.hits == 2
    assert tercero.sentences[0].text != "FRASE ENVENENADA"
    assert tercero.sentences[0].tokens[0].text != "TOKEN ENVENENADO"
    assert tercero.sentences[0] is not frase
    assert tercero.sentences[0].tokens[0] is not frase.tokens[0]


def test_el_objeto_guardado_NO_sale_nunca_del_analizador():
    c = _cache(scope="doc-1")
    devuelto = c.analyze(TEXTO_A)
    guardado = list(c._cache.values())[0][1]
    assert devuelto is not guardado
    assert devuelto.to_dict() == guardado.to_dict()


def test_la_cache_sigue_siendo_METRIC_NEUTRAL():
    """Control no trivial: cachear (con copia) no cambia el analisis."""
    sin = syn.HeuristicSyntaxAnalyzer()
    con = _cache(scope="doc-1")
    for texto in (TEXTO_A, TEXTO_B, TEXTO_A):
        assert con.analyze(texto).to_dict() == sin.analyze(texto).to_dict()


# ===========================================================================
# 3. B7 — UNA sola envolvente de aceptacion, y es la ESTRICTA
# ===========================================================================
DOC = ("Gorm rompio el pacto en el valle de Ysera. "
       "Kael dijo «el pacto» a Ysera. "
       "Marcus juro lealtad a Kael.")
UNICA = "Marcus juro lealtad a Kael."
TIPOGRAFICA = 'Kael dijo "el pacto" a Ysera.'  # casa solo tras normalizar


def test_REALIGN_OK_TIERS_solo_admite_exact():
    """MUTANTE: `REALIGN_OK_TIERS = {TIER_EXACT, TIER_NORMALIZED}` -> rojo."""
    assert realign.REALIGN_OK_TIERS == frozenset({realign.TIER_EXACT})


def test_TIER_NORMALIZED_no_ancla_en_NINGUNA_de_las_dos_rutas():
    """El defecto era que `normalized` SOLO era alcanzable por la ruta de API.

    Se cierra por el lado estricto: ahora NINGUNA de las dos lo acepta. Se comprueban
    las dos rutas con la MISMA entrada.
    """
    # (a) resolutor compartido
    r = realign.realign_evidence_unique(DOC, TIPOGRAFICA)
    assert not r.ok and r.tier == realign.TIER_NORMALIZED

    # (b) ruta de API
    cand = _candidato()
    out = consult.validate_external_verdict(
        DOC, cand, _crudo(cand, evidence_text=TIPOGRAFICA))
    assert out.status != consult.STATUS_ACCEPTED
    assert out.evidence_text == ""

    # (c) ruta REAL del motor
    limpio, errores = shadow._validate_verdict(
        _crudo(cand, evidence_text=TIPOGRAFICA), cand, _cid(cand), document=DOC)
    assert limpio is None and errores

    # CONTROL no trivial: la cita LITERAL y unica si se acepta por las dos.
    s = DOC.find(UNICA)
    ok_api = consult.validate_external_verdict(
        DOC, cand, _crudo(cand, evidence_text=UNICA, evidence_start=s,
                          evidence_end=s + len(UNICA)))
    assert ok_api.status == consult.STATUS_ACCEPTED
    ok_real, err_real = shadow._validate_verdict(
        _crudo(cand, evidence_text=UNICA, evidence_start=s, evidence_end=s + len(UNICA)),
        cand, _cid(cand), document=DOC)
    assert err_real == [] and ok_real is not None
    assert ok_real["evidence_text"] == UNICA


def _candidato():
    """Reutiliza el constructor de candidatos de la bateria B7 (contrato congelado:
    `RelationCandidate/internal-v1`, 20 campos, no se toca)."""
    from tests.test_relation_v2_b7_external import _candidate
    return _candidate()


def _cid(cand) -> str:
    from tests.test_relation_v2_b7_external import _cid as _b7_cid
    return _b7_cid(cand)


def _crudo(cand, **over) -> dict:
    s = DOC.find(UNICA)
    raw = {
        "candidate_id": _cid(cand),
        "verdict": "confirm",
        "negated": False,
        "evidence_text": UNICA,
        "evidence_start": s,
        "evidence_end": s + len(UNICA),
        "confidence": 0.9,
    }
    raw.update(over)
    return raw


def test_LA_RUTA_REAL_PASA_POR_validate_external_verdict(monkeypatch):
    """B7 defecto 4: la API tenia 23 llamadas de test y CERO de produccion.

    Aqui se demuestra que el camino que USA el motor (`evaluate_relation_external`
    -> `_validate_verdict`) la invoca de verdad.

    MUTANTE: deshacer la conexion (volver a la llamada suelta a
    `realign_evidence_unique` dentro de `external_ai_shadow`) -> rojo.
    """
    llamadas: list = []
    real = consult.validate_external_verdict

    def _espia(*a, **kw):
        llamadas.append((a, kw))
        return real(*a, **kw)

    monkeypatch.setattr(consult, "validate_external_verdict", _espia)

    cand = _candidato()
    limpio, errores = shadow._validate_verdict(
        _crudo(cand), cand, _cid(cand), document=DOC)

    assert errores == []
    assert limpio is not None
    assert llamadas, "el camino real NO pasa por validate_external_verdict"
    assert llamadas[0][1]["candidate_id"] == _cid(cand)


def test_LA_RUTA_REAL_COMPLETA_pasa_por_validate_external_verdict(monkeypatch):
    """Lo mismo, pero entrando por la puerta publica del motor con un proveedor
    falso (sin red): `evaluate_relation_external`."""
    from tests.test_relation_v2_b7_external import _FakeProvider
    from relations.external_ai_shadow import RelationExternalConfig, evaluate_relation_external

    llamadas: list = []
    real = consult.validate_external_verdict
    monkeypatch.setattr(consult, "validate_external_verdict",
                        lambda *a, **kw: (llamadas.append(1), real(*a, **kw))[1])

    cand = _candidato()
    provider = _FakeProvider({"verdicts": [_crudo(cand)]})
    cfg = RelationExternalConfig(model="modelo-falso", provider=provider)
    assert cfg.protocol == "legacy", "debe correr por el protocolo POR DEFECTO"

    res = evaluate_relation_external(cand, config=cfg, document=DOC)[0]
    assert llamadas, "la puerta publica del motor no llega a validate_external_verdict"
    assert res.verdict is not None
    assert res.verdict["evidence_text"] == UNICA


def test_las_dos_rutas_ACEPTAN_EXACTAMENTE_LO_MISMO():
    """La prueba de que la envolvente es UNA: barrido de citas sobre el mismo doc.

    MUTANTE: reabrir `normalized` en `REALIGN_OK_TIERS` -> rojo por divergencia
    (la API aceptaria la cita tipografica y la ruta real seguiria rechazandola).
    """
    cand = _candidato()
    intentos = [
        UNICA,
        TIPOGRAFICA,
        "Gorm rompio el pacto en el valle de Ysera.",
        "el pacto",                       # ambigua: aparece varias veces
        "Marcus  juro  lealtad a Kael.",  # solo casa tras colapsar blancos
        "esto no existe en el documento",
        "",
    ]
    for ev in intentos:
        s = DOC.find(ev)
        raw = _crudo(cand, evidence_text=ev, evidence_start=max(s, 0),
                     evidence_end=max(s, 0) + len(ev))
        api = consult.validate_external_verdict(DOC, cand, raw)
        real, _err = shadow._validate_verdict(raw, cand, _cid(cand), document=DOC)
        acepta_api = api.status == consult.STATUS_ACCEPTED
        acepta_real = real is not None
        assert acepta_api == acepta_real, (
            f"envolventes divergentes para {ev!r}: api={acepta_api} real={acepta_real}")
    # Control: el barrido no es trivialmente "todo rechazado".
    assert any(
        consult.validate_external_verdict(
            DOC, cand,
            _crudo(cand, evidence_text=e, evidence_start=DOC.find(e),
                   evidence_end=DOC.find(e) + len(e))).status == consult.STATUS_ACCEPTED
        for e in (UNICA,))


def test_no_queda_ningun_knob_de_seguridad_decorativo():
    """`allow_realignment_fallback` encendia una envolvente que la ruta real no
    tenia; `PROTOCOL_REALIGNMENT` etiquetaba una rama que ya no existe."""
    assert not hasattr(consult.DEFAULT_CONSULT_CONFIG, "allow_realignment_fallback")
    assert "realignment" not in consult.CONSULT_PROTOCOLS
    assert "PROTOCOL_REALIGNMENT" not in consult.__all__


# ===========================================================================
# 4. Negacion — una metrica de PRECISION que SI puede ponerse roja
# ===========================================================================
def _match_sintetico(pares: list) -> object:
    """`pares` = lista de (gt_negated, pred_negated)."""
    class _M:
        pass
    m = _M()
    m.true_positives = []
    m.false_negatives = []
    m.tp = len(pares)
    m.fp = 0
    m.fn = 0
    for i, (gt_neg, pred_neg) in enumerate(pares):
        gt = {"relation_id": f"rel-{i}", "negated": gt_neg, "predicate": "RELATED_TO",
              "temporal_status": "NONE", "epistemic_status": "ASSERTED",
              "expected_decision": "ACCEPT"}
        pred = {"negated": pred_neg}
        flags = {
            "predicate_correct": True, "direction_correct": True,
            "direction_orientation_ok": True, "types_correct": True,
            "negation_correct": bool(gt_neg) == bool(pred_neg),
            "temporal_correct": True, "epistemic_correct": True,
            "evidence_correct": True, "offsets_correct": True,
            "workspace_correct": True, "decision_correct": True,
        }
        m.true_positives.append({"gt": gt, "pred": pred, "flags": flags})
    return m


def test_la_metrica_de_PRECISION_de_negacion_existe_y_mide_lo_que_dice():
    # 4 aciertos, 5 falsos positivos: exactamente la forma del 4/9 medido.
    pares = [(True, True)] * 4 + [(False, True)] * 5 + [(False, False)] * 34
    struct = bench_metrics.structural_quality(_match_sintetico(pares))
    sig = struct["negation_signal"]
    assert sig["predicted_positive"] == 9
    assert sig["true_positive"] == 4
    assert sig["false_positive"] == 5
    assert sig["precision"] == 0.4444
    assert sig["measurable"] is True


def test_el_gate_negation_NO_PUEDE_ponerse_rojo_y_el_nuevo_SI():
    """El hallazgo que motiva la metrica: `negation` mide RECALL sobre los GT-negados.

    Con 4 GT-negados acertados vale 1.0 -> PASS, por muchos falsos positivos que
    dispare la senal. Se comprueba de forma EJECUTABLE que el gate viejo no reacciona
    y el nuevo si.
    """
    for n_fp in (0, 5, 30):
        pares = [(True, True)] * 4 + [(False, True)] * n_fp
        struct = bench_metrics.structural_quality(_match_sintetico(pares))
        gates = bench_report.evaluate_gates(
            match=None, struct=struct, contamination={"clean": True},
            determinism={"deterministic": True})
        assert gates["negation"]["status"] == "PASS", (
            "sorpresa: el gate viejo SI reacciona a los falsos positivos")
        if n_fp == 0:
            assert gates["negation_precision"]["status"] == "PASS"
        else:
            assert gates["negation_precision"]["status"] == "FAIL", (
                "la metrica nueva tampoco puede ponerse roja: no vale para nada")


def test_el_gate_nuevo_es_INFORMATIVO_y_no_gobierna_el_dictamen():
    """Decision declarada del bloque: la metrica nace en rojo (0.4444 real) y
    convertirla en gate de calidad cambiaria el dictamen de las 4 corridas por una
    medicion que ya era verdad ANTES de este bloque. Eso es trabajo del bloque 2."""
    pares = [(True, True)] * 4 + [(False, True)] * 5
    struct = bench_metrics.structural_quality(_match_sintetico(pares))
    gates = bench_report.evaluate_gates(
        match=None, struct=struct, contamination={"clean": True},
        determinism={"deterministic": True})
    assert gates["negation_precision"]["status"] == "FAIL"
    assert gates["negation_precision"]["informative"] is True
    assert gates["negation_precision"]["governs_verdict"] is False
    veredicto, _just = bench_report.decide_verdict(gates)
    assert veredicto != "NO APTO", "una metrica informativa no puede tumbar el dictamen"


def test_sin_positivos_predichos_la_precision_se_declara_NO_EVALUADA():
    """No se disfraza de 0.0 (ni de 1.0, que seria peor)."""
    struct = bench_metrics.structural_quality(_match_sintetico([(False, False)] * 5))
    gates = bench_report.evaluate_gates(
        match=None, struct=struct, contamination={"clean": True},
        determinism={"deterministic": True})
    assert gates["negation_precision"]["status"] == "NOT_EVALUATED"
    assert struct["negation_signal"]["measurable"] is False


def test_THRESHOLDS_intacto_y_el_suelo_nuevo_va_aparte():
    """Prohibicion del bloque: no se toca `THRESHOLDS` ni se baja ningun umbral."""
    assert bench_report.THRESHOLDS == {
        "simple_relations_recall": 0.80,
        "evidence": 0.80,
        "offsets": 0.90,
        "negation": 0.80,
        "temporality": 0.60,
        "rumors": 0.60,
        "predicate_structural": 0.50,
    }
    assert bench_report.NEGATION_PRECISION_FLOOR == 0.80


def test_el_camino_de_RECHAZO_por_negacion_NO_se_promociona():
    """Condicion explicita del bloque: la senal de negacion sigue como estaba.

    No se ha tocado `abstention`: el rechazo por negacion sigue exactamente con la
    misma configuracion que tenia (sombra), a la espera del held-out que construye
    otro agente.
    """
    p = AbstentionPolicy()
    assert p.reject_on_negation is True
    assert p.predicate_abstention_blocks_reject is True
    assert p.name == "abstention-default-1.0.0"


# ===========================================================================
# 5. Defaults del motor: NADA se activa por este bloque
# ===========================================================================
def test_los_defaults_del_motor_siguen_intactos():
    cfg = pipe.PipelineConfig()
    assert cfg.predicate_selector == "v1"
    assert cfg.consensus_policy == "auto"
    assert cfg.local_llm_enabled is False
    assert cfg.external_ai_enabled is False
    assert cfg.external_protocol == "legacy"
    assert consult.DEFAULT_CONSULT_CONFIG.protocol == "legacy"
