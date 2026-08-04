# -*- coding: utf-8 -*-
"""Puerta 4, bloque B3: bateria adversarial del agente de tests.

Ataca cinco puntos concretos del carril NVIDIA en sombra
(`scripts/gate4/measure_b3.py`):

1. si conectar el carril semantico al MISMO runner E2E que mide B0-B2 (para
   comparar contra el 0.607 real, no contra el 0.000 de `semantic_bench`
   config A) es tan costoso como declara `docs/v3/40` -- se demuestra que
   NO lo es: el pipeline general (`knowledge_v3.pipeline.runner`) ya acepta
   un `external_port` sobre el MISMO split `negation`, sin tocar una linea
   de produccion;
2. si el denominador de `family_recall` (B3) usa la MISMA convencion de
   "casos evaluables" que el runner congelado (B0-B2 excluyen el unico gold
   ABSTAIN sin polaridad declarada: 56, no 57) -- se demuestra que NO: B3
   cuenta 57, inflando el denominador con un caso que no puede emparejarse
   jamas (`subject_mentions`/`object_mentions` vacios);
3. que un episodio con fallo de proveedor (tras agotar reintentos) NO se
   excluye del denominador de cobertura -- se verifica que SI se cuenta como
   fallo, no como caso invisible;
4. que la copia en memoria de episodios (`_episode_for_semantic_pipeline`)
   nunca muta el gold en disco;
5. que dos corridas `--mock` (mismo guion, sin red) producen METRICAS
   identicas -- la unica parte no reproducible es la marca de tiempo/latencia
   simulada, nunca las cifras que alimentan las puertas.

Sin red: todo lo que "parece NVIDIA" aqui es `MockProviderPort`.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1]
_REPO_ROOT = _APP.parents[1]
_SCRIPTS = _REPO_ROOT / "scripts" / "gate4"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import measure_b3 as b3  # noqa: E402
from knowledge_v3.benchmarks.loader import DATASETS_DIR, load_gold  # noqa: E402
from knowledge_v3.eval import _frozen_runner as _fr  # noqa: E402
from knowledge_v3.eval.dev_corpus import load_dev_gold  # noqa: E402
from knowledge_v3.extraction.provider_port import (  # noqa: E402
    MockProviderPort,
    ProviderUnavailable,
)

SPLIT = _fr.dev_split_name()


# ---------------------------------------------------------------------------
# Hallazgo 1: conectar el carril externo al runner E2E general SI es factible
# con el codigo YA EXISTENTE, sin tocar produccion ni el runner congelado.
# ---------------------------------------------------------------------------
def test_el_pipeline_general_acepta_un_proveedor_externo_sobre_el_mismo_split():
    """`docs/v3/40` declara que comparar B3 contra el 0.607 de B2 "exigiria
    conectar NVIDIA al MISMO runner E2E, que es un carril de integracion mas
    profundo y no es lo que este bloque midio" -- presentandolo como fuera de
    alcance razonable.

    Este test demuestra que la ejecucion E2E CON un puerto de proveedor
    externo, sobre el MISMO split `negation` y con el MISMO arnes de
    puntuacion (`benchmarks.harness.run`, via `pipeline.runner.run_one`) que
    ya usan `pipeline/runner.py` para los splits `dev`/`heldout`, funciona
    hoy sin cambiar una linea de codigo de produccion: solo hace falta
    invocar `run_one(gold, "external_only", ..., external_port=puerto)`.

    No es el runner CONGELADO (`artifacts/v3-final-validation/
    gate4_negation_measure.py`, que fija `ablation="local_only"` a proposito
    y no expone forma de inyectar un proveedor) -- ese es correcto que quede
    fuera de alcance de un bloque de sombra, porque tocarlo violaria el
    guardian de la bateria. Pero SI existe, en el mismo repo, un segundo
    camino ya cableado (`knowledge_v3.pipeline.runner.run_one`) que ejecuta
    la cadena completa (normalizador, motor, resolutor, writer en DRY-RUN)
    sobre el MISMO gold `negation`, con el MISMO `benchmarks.harness`, y que
    ya acepta `external_port`. La cifra de "cobertura E2E con NVIDIA
    comparable al 0.607 de B2" no exige "un carril de integracion mas
    profundo": exige llamar a una funcion que ya existe con un argumento que
    ya acepta.
    """
    from knowledge_v3.pipeline.runner import run_one

    gold = load_gold(SPLIT)
    # Guion minimo: SIEMPRE responde vacio, pero con la FORMA que el
    # extractor semantico espera (mentions/claims/abstentions). Basta para
    # probar que el arnes E2E general evalua la salida del proveedor externo
    # con el vocabulario `extractor.coverage`, no para que "gane" nada -- una
    # corrida real con `NvidiaProviderPort` es lo que produciria cobertura
    # distinta de cero.
    port = MockProviderPort(handler=lambda _r: {"mentions": [], "claims": [], "abstentions": []})
    report, _result = run_one(
        gold, "external_only", workspace=f"bench-{SPLIT}", entry="raw", external_port=port
    )
    assert report["ablation"]["label"] == "external_only"
    assert report["ablation"]["providers"] == "external_only"
    # El informe sale en el MISMO vocabulario que puntua B0-B2
    # (`extractor.coverage`, via `benchmarks.harness.run`), no en el de
    # `semantic_bench` (config A). Con un proveedor que no propone nada, el
    # arnes lo dice explicitamente en vez de fingir una cobertura: eso, en si
    # mismo, es la prueba de que el enganche funciona (no un `KeyError`, ni
    # una excepcion del pipeline, ni un `PipelineError` de configuracion).
    assert report["extractor"] == {
        "status": "not_evaluated",
        "reason": "la prediccion no trae ni menciones ni claims",
    }


# ---------------------------------------------------------------------------
# Hallazgo 2: el denominador de B3 (57) no es el de B0-B2 (56) pese a que el
# propio docstring de measure_b3.py declara "56 casos evaluables".
# ---------------------------------------------------------------------------
def test_family_recall_infla_el_denominador_con_el_unico_gold_abstain():
    """El gold de `negation` tiene 57 claims, 1 de ellos un ABSTAIN puro
    (`claim:ambar-escaneo:e07:c1`, `expected_negated=None`,
    `subject_mentions=[]`, `object_mentions=[]`): no declara polaridad y no
    tiene menciones con las que emparejar nada, ASI QUE NO PUEDE cubrirse
    jamas por ningun extractor, perfecto o no.

    El runner E2E congelado que mide B0-B2 lo EXCLUYE explicitamente del
    denominador (`build_rows`: "el unico ABSTAIN del gold no declara
    polaridad: fuera, igual que hace `negation_split_metrics`"), dejando
    56 casos evaluables -- la misma cifra que cita el docstring de
    `measure_b3.py` ("57 claims / 56 casos evaluables que ya miden B0-B2").

    Pero `family_recall` (B3) NO reproduce esa exclusion: usa
    `total = len(gold_claims)` = 57. El resultado es que TODAS las cifras de
    cobertura/recall de las TRES vistas de B3 (determinista, nvidia, union)
    estan calculadas sobre un denominador un caso mas grande -- y ese caso de
    mas es estructuralmente incoverable. Con los datos reales de la corrida
    (20 casos cubiertos de NVIDIA), la diferencia es 0.3509 (20/57, lo
    publicado) frente a 0.3571 (20/56, la convencion de B0-B2): no cambia el
    veredicto de la puerta en esta corrida, pero rompe la comparabilidad
    numerica directa que el propio docstring de B3 da por sentada.
    """
    gold = load_dev_gold(verify=True)
    gold_claims = gold.claims_for("extractor")
    assert len(gold_claims) == 57

    abstain_puro = [
        c
        for c in gold_claims
        if not c["object_mentions"] and not c["subject_mentions"]
    ]
    assert len(abstain_puro) == 1, "se esperaba exactamente el ABSTAIN puro conocido del gold"
    assert abstain_puro[0]["claim_id"] == "claim:ambar-escaneo:e07:c1"

    # Convencion de B0-B2 (runner congelado): 56 casos evaluables.
    evaluables_b0_b2 = len(gold_claims) - len(abstain_puro)
    assert evaluables_b0_b2 == 56

    # Convencion real de B3 (measure_b3.family_recall), reproducida aqui con
    # un bundle vacio: el "total" que usa para TODAS sus divisiones.
    class _BundleVacio:
        mentions: list = []
        claims: list = []

    from knowledge_v3.benchmarks.matching import MatchConfig

    metrics = b3.family_recall(gold, _BundleVacio(), MatchConfig(symmetric_predicates=gold.symmetric_predicates))
    assert metrics["evaluable_cases"] == 57, (
        "measure_b3.family_recall no excluye el ABSTAIN puro: su denominador "
        "(57) NO coincide con el que B0-B2 declaran evaluable (56), pese a "
        "que el docstring del propio script cita 56."
    )


# ---------------------------------------------------------------------------
# Hallazgo 3 (verificacion, no defecto): un episodio con fallo de proveedor
# no se excluye del denominador -- cuenta como fallo, no se esconde.
# ---------------------------------------------------------------------------
def test_episodio_con_fallo_de_proveedor_cuenta_como_fallo_no_se_excluye():
    """Si `SemanticEpisodeExtractor` no logra respuesta de un episodio (tras
    agotar los reintentos de `RetryingPort`, como paso 2 veces en la corrida
    real), el claim gold de ese episodio DEBE seguir en el denominador de
    `family_recall` como caso no cubierto -- nunca desaparecer del calculo.

    Se verifica end-to-end con un puerto guionizado que falla SIEMPRE (todas
    las llamadas transitoriamente indisponibles): el extractor semantico debe
    producir abstenciones (`PROVIDER_UNAVAILABLE`), y `family_recall` debe
    seguir contando el numero COMPLETO de claims gold en `evaluable_cases`,
    con `covered_cases == 0` (nada se emparejo), no con un denominador
    reducido.
    """
    gold = load_dev_gold(verify=True)
    ctx = b3._build_context_negation(gold)

    def _siempre_falla(_req):
        return ProviderUnavailable("simulado: proveedor siempre cae")

    from knowledge_v3.extraction import semantic_bench as bench
    from knowledge_v3.benchmarks.matching import MatchConfig

    port = MockProviderPort(handler=_siempre_falla)
    result = bench.run_config("C2", ctx, port=port)
    bundle = bench.to_bundle(result, ctx)

    match_config = MatchConfig(symmetric_predicates=gold.symmetric_predicates)
    metrics = b3.family_recall(gold, bundle, match_config)

    gold_claims = gold.claims_for("extractor")
    assert metrics["evaluable_cases"] == len(gold_claims) == 57, (
        "un proveedor que falla para TODOS los episodios no debe reducir el "
        "denominador de evaluable_cases: los casos siguen contando, como "
        "fallo, no se excluyen"
    )
    assert metrics["covered_cases"] == 0
    assert metrics["coverage"] == 0.0


# ---------------------------------------------------------------------------
# Hallazgo 4: el ajuste de compatibilidad en memoria no muta el gold en disco.
# ---------------------------------------------------------------------------
def _hash_dataset_dir(split: str) -> str:
    root = DATASETS_DIR / split
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            h.update(str(path.relative_to(root)).encode("utf-8"))
            h.update(path.read_bytes())
    return h.hexdigest()


def test_el_ajuste_de_compatibilidad_no_muta_el_gold_en_disco(tmp_path):
    """`_episode_for_semantic_pipeline` declara operar sobre una COPIA en
    memoria (`out = dict(episode)`). Se comprueba con un hash de todo el
    directorio del split ANTES y DESPUES de una corrida completa
    (`build_report` con `--mock`), y ademas que los dicts de
    `gold.episodes` en memoria (la misma instancia que devuelve
    `load_dev_gold`) no ganan las claves `speaker`/`turn`/`table` como efecto
    colateral de haber sido pasados por el ajuste.
    """
    antes = _hash_dataset_dir(SPLIT)

    gold = load_dev_gold(verify=True)
    original_keys = [set(e.keys()) for e in gold.episodes]

    b3.build_report(cache_dir=tmp_path / "cache.json", mock=True, timeout_seconds=5, concurrency=1, price_per_million_tokens_usd=None)

    despues_keys = [set(e.keys()) for e in gold.episodes]
    assert original_keys == despues_keys, (
        "los episodios en memoria de `gold.episodes` ganaron claves nuevas: "
        "el ajuste de compatibilidad no esta operando sobre una copia"
    )

    despues = _hash_dataset_dir(SPLIT)
    assert antes == despues, "el gold en disco cambio tras ejecutar measure_b3"


# ---------------------------------------------------------------------------
# Hallazgo 5: reproducibilidad de las metricas (no de los campos de tiempo).
# ---------------------------------------------------------------------------
def test_dos_corridas_mock_producen_las_mismas_metricas_de_puerta(tmp_path):
    """Dos corridas `--mock` (mismo guion, sin red, sin cache compartida)
    deben coincidir EXACTAMENTE en `lanes` (metricas y veredictos) y en
    `gold`. Los campos de latencia/tokens pueden variar porque
    `MockProviderPort` no fija su reloj, asi que se excluyen a proposito
    -- no son las cifras que deciden la puerta.
    """
    r1 = b3.build_report(
        cache_dir=tmp_path / "c1.json", mock=True, timeout_seconds=5, concurrency=1,
        price_per_million_tokens_usd=None,
    )
    r2 = b3.build_report(
        cache_dir=tmp_path / "c2.json", mock=True, timeout_seconds=5, concurrency=1,
        price_per_million_tokens_usd=None,
    )
    def _sin_tiempos(lanes: dict) -> dict:
        return {
            name: {k: v for k, v in datos.items() if k != "wall_ms"}
            for name, datos in lanes.items()
        }

    assert _sin_tiempos(r1["lanes"]) == _sin_tiempos(r2["lanes"])
    assert r1["gold"] == r2["gold"]
    assert r1["split"] == r2["split"]
