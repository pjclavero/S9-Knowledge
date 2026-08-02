# -*- coding: utf-8 -*-
"""PUERTA 6B — 24 casos de CANDIDATOS DE GLOSARIO de la revisión humana V3.

Un candidato es una PROPUESTA de término, alias, forma hablada, tipo de entidad
o mala transcripción, originada SIEMPRE en un campo que un humano escribió
explícitamente al corregir una propuesta. Nunca se aplica: el glosario efectivo
del motor (`Lexicon` del workspace + fuente de glosario de la cascada) no tiene
ninguna vía de escritura desde este camino, y los casos 23-24 lo demuestran con
el hash del glosario antes y después.

Los casos 23 y 24 recorren la cadena real (pipeline determinista -> paquete de
revisión -> ReviewService -> candidatos). Los casos 1-22 ejercitan el almacén
directamente, que es donde vive la invariante de append-only y deduplicación.

Sin Ollama, sin NVIDIA, sin Neo4j; writer siempre en dry-run.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
_VIEWER = _APP_DIR.parents[1] / "viewer"
for _p in (str(_APP_DIR), str(_TESTS_DIR), str(_VIEWER)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("jsonschema")

from app.services.v3_glossary_candidates import (  # noqa: E402
    TYPES,
    GlossaryCandidateStore,
)
from app.services.v3_review import ReviewService, read_history  # noqa: E402

WORKSPACE = "bench-dev"
OTHER_WORKSPACE = "bench-ajeno"

EVIDENCE = {"start": 0, "end": 15, "literal_text": "Ilaria Vandreth"}


def _propose(store: GlossaryCandidateStore, **overrides):
    payload = dict(
        workspace=WORKSPACE,
        candidate_type="ALIAS_CANDIDATE",
        canonical_value="Ilaria Vandreth",
        candidate_value="Ilaria",
        entity_type="PERSON",
        resolved_entity_id="entity:ilaria",
        source_id="leyenda-cronica",
        episode_id="ep-1",
        evidence=EVIDENCE,
        decision_id="human:d1",
        proposal_id="review:p1",
    )
    payload.update(overrides)
    return store.propose(**payload)


@pytest.fixture
def store(tmp_path) -> GlossaryCandidateStore:
    return GlossaryCandidateStore(tmp_path / "glossary-candidates")


def _lines(store: GlossaryCandidateStore, workspace: str = WORKSPACE) -> list[dict]:
    safe = hashlib.sha256(workspace.encode()).hexdigest()[:16]
    path = store.root / safe / "candidates.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _audit(store: GlossaryCandidateStore, workspace: str = WORKSPACE) -> list[dict]:
    safe = hashlib.sha256(workspace.encode()).hexdigest()[:16]
    path = store.root / safe / "audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ===========================================================================
# 1-7. IDENTIDAD Y VALIDACIÓN
# ===========================================================================

def test_01_tipo_de_candidato_invalido_se_rechaza(store):
    with pytest.raises(ValueError, match="candidate_type inválido"):
        _propose(store, candidate_type="TERMINO_QUE_NO_EXISTE")
    assert _lines(store) == [], "un tipo inválido escribió en el almacén"


def test_02_los_cinco_tipos_declarados_se_aceptan(store):
    assert TYPES == frozenset({
        "CANONICAL_TERM_CANDIDATE", "ALIAS_CANDIDATE", "SPOKEN_FORM_CANDIDATE",
        "ENTITY_TYPE_CANDIDATE", "KNOWN_MISRECOGNITION_CANDIDATE",
    })
    for index, candidate_type in enumerate(sorted(TYPES)):
        item = _propose(store, candidate_type=candidate_type,
                        candidate_value=f"valor-{index}", decision_id=f"human:d{index}")
        assert item["candidate_type"] == candidate_type
    assert len(store.list(WORKSPACE)) == len(TYPES)


def test_03_candidate_id_es_determinista(store, tmp_path):
    first = _propose(store)
    otro = GlossaryCandidateStore(tmp_path / "otro")
    second = _propose(otro, decision_id="human:d-distinto", source_id="otra-fuente")
    assert first["candidate_id"] == second["candidate_id"]
    assert first["candidate_id"].startswith("glossary:")


def test_04_candidate_id_depende_del_workspace(store):
    uno = _propose(store)
    dos = _propose(store, workspace=OTHER_WORKSPACE)
    assert uno["candidate_id"] != dos["candidate_id"]


def test_05_candidate_id_depende_del_tipo(store):
    uno = _propose(store)
    dos = _propose(store, candidate_type="SPOKEN_FORM_CANDIDATE")
    assert uno["candidate_id"] != dos["candidate_id"]


def test_06_candidate_id_depende_del_valor_y_de_la_entidad_resuelta(store):
    base = _propose(store)
    assert _propose(store, candidate_value="Ila")["candidate_id"] != base["candidate_id"]
    assert _propose(store, resolved_entity_id="entity:otra")["candidate_id"] != base["candidate_id"]


def test_07_candidate_id_normaliza_mayusculas_y_espacios(store):
    base = _propose(store)
    variante = _propose(store, candidate_value="  ILARIA  ", decision_id="human:d2")
    assert variante["candidate_id"] == base["candidate_id"]
    # Pero conserva el valor tal y como lo escribió el humano en la 1ª versión.
    assert variante["candidate_value"] == "Ilaria"


# ===========================================================================
# 8-12. DEDUPLICACIÓN Y AGREGACIÓN
# ===========================================================================

def test_08_repetir_incrementa_ocurrencias_sin_duplicar_en_la_vista(store):
    _propose(store)
    _propose(store, decision_id="human:d2", proposal_id="review:p2")
    items = store.list(WORKSPACE)
    assert len(items) == 1
    assert items[0]["occurrence_count"] == 2


def test_09_repetir_agrega_fuentes_y_episodios(store):
    _propose(store)
    _propose(store, source_id="mareas-cuaderno", episode_id="ep-9",
             decision_id="human:d2", proposal_id="review:p2")
    item = store.list(WORKSPACE)[0]
    assert item["source_ids"] == ["leyenda-cronica", "mareas-cuaderno"]
    assert item["episode_ids"] == ["ep-1", "ep-9"]


def test_10_repetir_agrega_evidencias_de_forma_estable(store):
    otra = {"start": 40, "end": 55, "literal_text": "Ilaria Vandreth"}
    _propose(store)
    _propose(store, evidence=otra, decision_id="human:d2", proposal_id="review:p2")
    evidences = store.list(WORKSPACE)[0]["evidence"]
    assert len(evidences) == 2
    assert evidences == sorted(
        evidences, key=lambda e: json.dumps(e, sort_keys=True, ensure_ascii=False))


def test_11_el_origen_acumula_todas_las_decisiones_humanas(store):
    _propose(store)
    _propose(store, decision_id="human:d2", proposal_id="review:p2")
    origin = store.list(WORKSPACE)[0]["origin"]
    assert origin["human_decision_ids"] == ["human:d1", "human:d2"]
    assert origin["proposal_ids"] == ["review:p1", "review:p2"]


def test_12_source_count_es_el_numero_de_fuentes_distintas(store):
    _propose(store)
    _propose(store, source_id="mareas-cuaderno", decision_id="human:d2")
    _propose(store, source_id="mareas-cuaderno", decision_id="human:d3")
    item = store.list(WORKSPACE)[0]
    assert item["occurrence_count"] == 3
    assert item["source_count"] == 2 == len(item["source_ids"])


# ===========================================================================
# 13-16. APPEND-ONLY Y PERSISTENCIA
# ===========================================================================

def test_13_el_jsonl_es_append_only(store):
    _propose(store)
    _propose(store, decision_id="human:d2", proposal_id="review:p2")
    raw = _lines(store)
    assert len(raw) == 2, "una versión anterior fue sobrescrita"
    assert raw[0]["occurrence_count"] == 1 and raw[1]["occurrence_count"] == 2
    assert raw[0]["candidate_hash"] != raw[1]["candidate_hash"]


def test_14_list_pliega_por_candidate_id_tras_reiniciar(store):
    _propose(store)
    _propose(store, decision_id="human:d2", proposal_id="review:p2")
    reiniciado = GlossaryCandidateStore(store.root)
    items = reiniciado.list(WORKSPACE)
    assert len(items) == 1
    assert items[0]["occurrence_count"] == 2, "el plegado no se quedó con la última versión"


def test_15_list_devuelve_orden_estable(store):
    for index in range(5):
        _propose(store, candidate_value=f"alias-{index}", decision_id=f"human:d{index}")
    ids = [item["candidate_id"] for item in store.list(WORKSPACE)]
    assert ids == sorted(ids)


def test_16_aislamiento_por_workspace(store):
    _propose(store)
    _propose(store, workspace=OTHER_WORKSPACE, decision_id="human:d2")
    mios = store.list(WORKSPACE)
    ajenos = store.list(OTHER_WORKSPACE)
    assert len(mios) == len(ajenos) == 1
    assert mios[0]["workspace"] == WORKSPACE
    assert ajenos[0]["workspace"] == OTHER_WORKSPACE
    assert len(_lines(store)) == 1 and len(_lines(store, OTHER_WORKSPACE)) == 1


# ===========================================================================
# 17-22. AUDITORÍA, HASH Y AUSENCIA DE APLICACIÓN
# ===========================================================================

def test_17_cada_propuesta_deja_una_entrada_de_auditoria(store):
    first = _propose(store)
    second = _propose(store, decision_id="human:d2", proposal_id="review:p2")
    audit = _audit(store)
    assert len(audit) == 2
    assert {entry["event"] for entry in audit} == {"CANDIDATE_PROPOSED"}
    assert [entry["decision_id"] for entry in audit] == ["human:d1", "human:d2"]
    assert audit[0]["candidate_hash"] == first["candidate_hash"]
    assert audit[1]["candidate_hash"] == second["candidate_hash"]


def test_18_candidate_hash_no_depende_del_reloj(store, tmp_path):
    uno = _propose(store)
    dos = _propose(GlossaryCandidateStore(tmp_path / "otro"))
    assert uno["created_at"] is not None
    assert uno["candidate_hash"] == dos["candidate_hash"], (
        "el hash del candidato depende de created_at y no es reproducible")


def test_19_candidate_hash_cambia_si_cambia_el_contenido(store):
    uno = _propose(store)
    dos = _propose(store, candidate_value="Ila", decision_id="human:d2")
    assert uno["candidate_hash"] != dos["candidate_hash"]


def test_20_todo_candidato_nace_propuesto_y_sin_bandera_de_aplicacion(store):
    item = _propose(store)
    assert item["status"] == "PROPOSED"
    assert "apply" not in item and "applied" not in item and "approved" not in item
    assert item["reason_codes"] == []


def test_21_el_almacen_no_expone_ninguna_via_de_aplicacion(store):
    publicos = {name for name in dir(store) if not name.startswith("_")}
    assert publicos == {"root", "list", "propose"}, publicos
    for prohibido in ("apply", "approve", "commit", "delete", "update", "upsert", "merge"):
        assert not hasattr(store, prohibido), prohibido


def test_22_workspace_sin_candidatos_devuelve_lista_vacia(store):
    assert store.list("workspace-que-no-existe") == []
    _propose(store)
    assert store.list("workspace-que-no-existe") == []


# ===========================================================================
# 23-24. CADENA REAL: pipeline -> revisión -> candidatos (y NO-MUTACIÓN)
# ===========================================================================

@pytest.fixture(scope="module")
def real_review(tmp_path_factory):
    """Pipeline determinista real -> paquete de revisión real."""
    from test_knowledge_v3_e2e_fixtures import gold_dev, pipeline, snapshot_entities
    from knowledge_v3.pipeline import from_raw

    gold = gold_dev()
    engine = pipeline(gold)
    assert engine.config.workspace == WORKSPACE
    directory = tmp_path_factory.mktemp("gloss-candidates") / "proposals"
    engine.run([from_raw(source) for source in gold.sources],
               catalog_entities=snapshot_entities(gold),
               review_proposals_dir=directory)
    return directory, engine


def effective_glossary_hash(engine) -> str:
    """Hash canónico del glosario efectivo (Lexicon del workspace + fuente)."""
    entries = []
    for entry in getattr(engine.config.lexicon, "entries", ()) or ():
        entries.append({
            "canonical": getattr(entry, "canonical", None),
            "entity_type": getattr(entry, "entity_type", None),
            "variants": sorted(getattr(entry, "variants", ()) or ()),
            "confidence": getattr(entry, "confidence", None),
            "origin": getattr(entry, "origin", None),
        })
    entries.sort(key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    body = {
        "lexicon": entries,
        "glossary_source": type(getattr(engine.config, "glossary", None)).__name__,
        "workspace": engine.config.workspace,
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_23_un_rechazo_humano_no_propone_ningun_candidato(real_review, tmp_path):
    directory, _engine = real_review
    service = ReviewService(directory, tmp_path / "decisions.jsonl")
    item = service.queue(WORKSPACE).items[0]
    service.record(proposal_id=item["proposal_id"], workspace=WORKSPACE, reviewer="mara",
                   human_decision="REJECT", request_id="rej-1",
                   rationale="La evidencia no sostiene la relación.",
                   correction={"subject_alias": "Ilaria"},
                   expected_proposal_hash=item["proposal_hash"])
    assert len(read_history(tmp_path / "decisions.jsonl")) == 1
    candidates = service.glossary_candidates(WORKSPACE)
    assert candidates == [], "un REJECT propuso candidatos de glosario"


def test_24_correccion_real_propone_candidatos_sin_mutar_el_glosario(real_review, tmp_path):
    directory, engine = real_review
    antes = effective_glossary_hash(engine)

    service = ReviewService(directory, tmp_path / "decisions.jsonl")
    item = service.queue(WORKSPACE).items[0]
    record = service.record(
        proposal_id=item["proposal_id"], workspace=WORKSPACE, reviewer="mara",
        human_decision="CORRECT", request_id="corr-1",
        expected_proposal_hash=item["proposal_hash"],
        correction={
            "subject_canonical_name": "Ilaria Vandreth", "subject_alias": "Ilaria",
            "spoken_form": "ilaria vandret", "misrecognition": "Ylaria",
            "suggested_entity_type": "PERSON",
        },
    )
    candidates = service.glossary_candidates(WORKSPACE)
    tipos = {c["candidate_type"] for c in candidates}
    assert tipos == {
        "CANONICAL_TERM_CANDIDATE", "ALIAS_CANDIDATE", "SPOKEN_FORM_CANDIDATE",
        "ENTITY_TYPE_CANDIDATE", "KNOWN_MISRECOGNITION_CANDIDATE",
    }, tipos
    for candidate in candidates:
        assert candidate["status"] == "PROPOSED"
        assert candidate["reason_codes"] == ["EXPLICIT_HUMAN_CORRECTION"]
        assert candidate["origin"]["human_decision_ids"] == [record["decision_id"]]
        assert candidate["origin"]["proposal_ids"] == [item["proposal_id"]]
        assert candidate["source_ids"] == [item["source_id"]]

    despues = effective_glossary_hash(engine)
    assert despues == antes, (
        "proponer candidatos mutó el glosario efectivo\n"
        f"  antes:   {antes}\n  después: {despues}"
    )
    print(f"\nGLOSARIO_ANTES={antes}\nGLOSARIO_DESPUES={despues}")
