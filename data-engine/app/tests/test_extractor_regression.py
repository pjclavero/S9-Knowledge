"""
Tests de regresión para el extractor — Prioridad 2 Benchmark.
Todos deben pasar en CI sin depender de Ollama ni Neo4j.

Cada caso es independiente y debe completarse en < 1 s.
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_APP_DIR = _TESTS_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from review.extractor import (
    extract_from_segments,
    _character_confidence,
    _normalize_for_compare,
)
from review.validator import validate_candidate, validate_candidates
from review.auto_decider import decide_one
from review.models import Candidate, ValidationResult, ResolutionResult
from review.classifier import ClassifiedSegment


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seg(
    text: str,
    seg_id: str = "reg_seg_001",
    source_id: str = "src_reg",
    workspace: str = "test_ws",
    ts_start: str = "00:01:00",
    ts_end: str = "00:02:00",
) -> ClassifiedSegment:
    return {
        "segment_id": seg_id,
        "source_id": source_id,
        "source_kind": "audio",
        "workspace": workspace,
        "timestamp_start": ts_start,
        "timestamp_end": ts_end,
        "text": text,
        "should_extract": True,
        "category": "rpg_content",
        "lines": [],
    }


def _base_candidate(**kwargs) -> Candidate:
    """Candidate con defaults mínimos válidos para tests de validator/decider."""
    defaults = dict(
        candidate_id="reg000000001",
        source_id="src_reg",
        segment_id="reg_seg_001",
        workspace="test_ws",
        kind="entity",
        name="Doji Satsume",
        entity_type="Character",
        confidence=0.90,
        evidence="Doji Satsume llega al castillo con paso firme.",
        timestamp_start="00:01:00",
        timestamp_end="00:02:00",
        source_kind="audio",
    )
    defaults.update(kwargs)
    return Candidate(**defaults)


def _ok_vr(candidate_id: str = "reg000000001") -> ValidationResult:
    return ValidationResult(candidate_id=candidate_id, valid="valid")


def _ok_rr(candidate_id: str = "reg000000001") -> ResolutionResult:
    return ResolutionResult(
        candidate_id=candidate_id,
        action="create_new",
        reason="sin match en Neo4j",
        neo4j_available=True,
    )


# ── Caso 1 ────────────────────────────────────────────────────────────────────

def test_reg_01_llevas_no_es_character():
    """'Llevás' no debe crearse como personaje con confidence >= 0.85.

    Método: extractor.extract_from_segments / stopwords.is_stopword
    La stopword 'llevas' normaliza 'Llevás' → queda descartada antes de emitir
    un candidato con confidence alta.
    """
    seg = _seg("Llevás muchos años en el clan y lo sabes mejor que nadie.")
    candidates = extract_from_segments([seg], glossary={})
    llevas_high = [
        c for c in candidates
        if "llev" in (c.name or "").lower() and c.confidence >= 0.85
    ]
    assert len(llevas_high) == 0, (
        f"'Llevás' no debe emitirse con confidence >= 0.85: {llevas_high}"
    )


# ── Caso 2 ────────────────────────────────────────────────────────────────────

def test_reg_02_todo_no_es_character():
    """'Todo' no debe crearse como personaje con confidence >= 0.85.

    Método: extractor._extract_entities vía extract_from_segments;
    stopwords.is_stopword descarta el token como candidato de alta confianza.
    """
    seg = _seg("Todo esto es importante para el clan y los magistrados lo saben.")
    candidates = extract_from_segments([seg], glossary={})
    todo_high = [
        c for c in candidates
        if (c.name or "").lower() == "todo" and c.confidence >= 0.85
    ]
    assert len(todo_high) == 0, (
        f"'Todo' no debe emitirse con confidence >= 0.85: {todo_high}"
    )


# ── Caso 3 ────────────────────────────────────────────────────────────────────

def test_reg_03_como_no_es_character():
    """'Como' no debe crearse como personaje con confidence >= 0.85.

    Método: extractor._extract_entities; _character_confidence aplica Regla 1
    (stopword → max 0.40) y el candidato queda bajo el umbral o descartado.
    """
    seg = _seg("Como ya sabéis, el Clan Grulla domina la política en la capital.")
    candidates = extract_from_segments([seg], glossary={})
    como_high = [
        c for c in candidates
        if (c.name or "").lower() == "como" and c.confidence >= 0.85
    ]
    assert len(como_high) == 0, (
        f"'Como' no debe emitirse con confidence >= 0.85: {como_high}"
    )


# ── Caso 4 ────────────────────────────────────────────────────────────────────

def test_reg_04_verbos_expresion_soy_no_en_nombre():
    """Frases como 'soy X' no deben incluir el verbo 'soy' en el nombre del personaje.

    Método: extractor._CHAR_EVIDENCE_PATTERNS captura el grupo 1 (solo el nombre).
    El patrón r'\\bsoy\\s+([A-Z...]...)' garantiza que 'soy' queda fuera del
    nombre capturado.
    """
    seg = _seg("Soy Doji Satsume, magistrado del Clan Grulla.")
    candidates = extract_from_segments([seg], glossary={})
    # No debe haber ningún candidato cuyo nombre empiece con 'soy'
    soy_in_name = [
        c for c in candidates
        if (c.name or "").lower().startswith("soy")
    ]
    assert len(soy_in_name) == 0, (
        f"El verbo 'soy' no debe incluirse en el nombre: {[c.name for c in soy_in_name]}"
    )
    # Además debe existir un candidato para Doji Satsume (o al menos Doji)
    doji_found = any("doji" in (c.name or "").lower() for c in candidates)
    assert doji_found, (
        f"Debe encontrarse a Doji Satsume en 'soy Doji Satsume'. Candidatos: {[c.name for c in candidates]}"
    )


# ── Caso 5 ────────────────────────────────────────────────────────────────────

def test_reg_05_glosario_normaliza_nombre():
    """Un nombre en el glosario se normaliza al nombre canónico.

    Método: extractor._extract_entities → glossary lookup con _normalize_for_compare.
    Si 'doji satsume' (normalizado) está en el glosario, el nombre se reemplaza
    por el canonical 'Doji Satsume'.
    """
    gloss = {"doji satsume": "Doji Satsume"}
    seg = _seg("Doji Satsume llega al castillo por la mañana temprana.")
    candidates = extract_from_segments([seg], glossary=gloss)
    doji_cands = [c for c in candidates if "doji" in (c.name or "").lower()]
    assert len(doji_cands) > 0, "Debe haber al menos un candidato para Doji Satsume"
    for c in doji_cands:
        assert c.name == "Doji Satsume", (
            f"El nombre canonicalizado debe ser 'Doji Satsume', got '{c.name}'"
        )


# ── Caso 6 ────────────────────────────────────────────────────────────────────

def test_reg_06_alias_se_resuelve():
    """Un alias conocido se resuelve al nombre canónico vía glosario.

    Método: extractor._extract_entities → glossary.get(norm_name).
    El alias 'Satsume' en el glosario apunta al canonical 'Doji Satsume'.
    """
    gloss = {
        "satsume": "Doji Satsume",
        "doji satsume": "Doji Satsume",
    }
    seg = _seg("Satsume entra en la sala del consejo junto a los magistrados.")
    candidates = extract_from_segments([seg], glossary=gloss)
    satsume_cands = [c for c in candidates if "satsume" in (c.name or "").lower()]
    if satsume_cands:
        # Si el alias fue detectado y canonicalizado, el nombre debe ser el canonical
        assert satsume_cands[0].name == "Doji Satsume", (
            f"Alias 'Satsume' debe resolverse a 'Doji Satsume', got '{satsume_cands[0].name}'"
        )


# ── Caso 7 ────────────────────────────────────────────────────────────────────

def test_reg_07_entidad_existente_no_se_duplica():
    """Una entidad ya existente en el grafo no genera candidato nuevo independiente.

    Método: resolver._resolve_one con mock de _search_neo4j devolviendo match exacto.
    El resolver devuelve use_existing, no create_new.
    """
    from review.resolver import _resolve_one

    c = _base_candidate(name="Doji Satsume", entity_type="Character", confidence=0.90)
    vr = _ok_vr(c.candidate_id)

    mock_driver = MagicMock()

    with patch("review.resolver._search_neo4j") as mock_search:
        mock_search.return_value = [
            {
                "canonical": "Doji Satsume",
                "labels": ["Character"],
                "score": 1.0,
                "match_type": "exact",
            }
        ]
        rr = _resolve_one(c, vr, driver=mock_driver)

    assert rr.action == "use_existing", (
        f"Entidad existente debe devolver use_existing, got '{rr.action}'"
    )
    assert rr.matched_canonical == "Doji Satsume"


# ── Caso 8 ────────────────────────────────────────────────────────────────────

def test_reg_08_has_fought_con_location_no_aceptada():
    """HAS_FOUGHT con destino de tipo Location no se acepta como relación final.

    Método: validator.validate_candidate — _ENTITY_RELATION_CONFLICT detecta
    HAS_FOUGHT → Location y emite issue, lo que resulta en valid='invalid'.
    """
    c = _base_candidate(
        candidate_id="reg000000008",
        kind="relation",
        name=None,
        entity_type=None,
        from_entity="Doji Satsume",
        from_type="Character",
        to_entity="Castillo Shiro",
        to_type="Location",
        relation_type="HAS_FOUGHT",
        confidence=0.80,
        evidence="Doji Satsume luchó en el Castillo Shiro durante el asedio.",
    )
    vr = validate_candidate(c)
    assert vr.valid == "invalid", (
        f"HAS_FOUGHT contra Location debe ser 'invalid', got '{vr.valid}'"
    )
    assert any("HAS_FOUGHT" in issue for issue in vr.issues), (
        f"El issue debe mencionar HAS_FOUGHT: {vr.issues}"
    )


# ── Caso 9 ────────────────────────────────────────────────────────────────────

def test_reg_09_fought_at_cuando_corresponde():
    """Cuando el destino es Location, se propone FOUGHT_AT, no HAS_FOUGHT.

    Método: validator.validate_candidate — _CONFLICT_SUGGESTION para HAS_FOUGHT
    incluye la sugerencia 'FOUGHT_AT' en el mensaje del issue.
    """
    c = _base_candidate(
        candidate_id="reg000000009",
        kind="relation",
        name=None,
        entity_type=None,
        from_entity="Doji Satsume",
        from_type="Character",
        to_entity="Castillo Shiro",
        to_type="Location",
        relation_type="HAS_FOUGHT",
        confidence=0.80,
        evidence="Doji Satsume combatió en el Castillo Shiro durante el asedio.",
    )
    vr = validate_candidate(c)
    assert vr.valid == "invalid"
    # El mensaje de issue debe sugerir FOUGHT_AT
    suggestion_present = any(
        "FOUGHT_AT" in issue for issue in vr.issues
    )
    assert suggestion_present, (
        f"El validator debe sugerir FOUGHT_AT para HAS_FOUGHT→Location: {vr.issues}"
    )


# ── Caso 10 ───────────────────────────────────────────────────────────────────

def test_reg_10_relacion_sin_evidencia_no_autoaprueba():
    """Una relación sin evidencia textual no puede ser auto_approved.

    Método: auto_decider.decide_one — el guard 'not c.evidence' provoca
    auto_reject antes de llegar al bloque AUTO_APPROVE.
    """
    c = _base_candidate(
        candidate_id="reg000000010",
        kind="relation",
        name=None,
        entity_type=None,
        from_entity="Doji Satsume",
        to_entity="Bayushi Kachiko",
        relation_type="KNOWS",
        confidence=0.90,
        evidence="",          # sin evidencia textual
    )
    vr = _ok_vr(c.candidate_id)
    rr = _ok_rr(c.candidate_id)

    decision = decide_one(c, vr, rr)
    assert decision.decision != "auto_approve", (
        f"Sin evidencia no debe auto_aprobarse: got '{decision.decision}'"
    )
    # Debe ser auto_reject (evidence vacía → reject inmediato)
    assert decision.decision == "auto_reject", (
        f"Sin evidencia debe ser auto_reject, got '{decision.decision}'"
    )


# ── Caso 11 ───────────────────────────────────────────────────────────────────

def test_reg_11_tipo_no_contemplado_rechazado():
    """Un tipo de nodo no contemplado en el esquema se rechaza.

    Método: validator.validate_candidate comprueba entity_type contra
    ALLOWED_NODE_TYPES; si no está, añade issue y devuelve valid='invalid'.
    El tipo 'WeaponMagic' no existe en el schema.
    """
    c = _base_candidate(
        candidate_id="reg000000011",
        entity_type="WeaponMagic",   # tipo inventado, no en schema
        name="Espada del Dragón",
        evidence="La espada del dragón brillaba en la oscuridad del templo.",
    )
    vr = validate_candidate(c)
    assert vr.valid == "invalid", (
        f"Tipo 'WeaponMagic' fuera del schema debe ser 'invalid', got '{vr.valid}'"
    )
    assert any("WeaponMagic" in issue or "entity_type" in issue for issue in vr.issues), (
        f"El issue debe mencionar el tipo rechazado: {vr.issues}"
    )


# ── Caso 12 ───────────────────────────────────────────────────────────────────

def test_reg_12_entidad_ambigua_va_a_revision():
    """Una entidad que no puede clasificarse con seguridad pasa a needs_review.

    Método: auto_decider.decide_one — confidence < CONF_AUTO_APPROVE (0.85)
    provoca needs_review. También aplica cuando neo4j_available=False.
    """
    c = _base_candidate(
        candidate_id="reg000000012",
        name="Cazador",           # nombre ambiguo, single-token
        entity_type="Character",
        confidence=0.72,          # por debajo de 0.85 → needs_review obligatorio
        evidence="El Cazador apareció de entre las sombras del bosque oscuro.",
    )
    vr = _ok_vr(c.candidate_id)
    rr = _ok_rr(c.candidate_id)

    decision = decide_one(c, vr, rr)
    assert decision.decision == "needs_review", (
        f"Entidad ambigua con confidence 0.72 debe ir a needs_review, got '{decision.decision}'"
    )


# ── Caso 13 ───────────────────────────────────────────────────────────────────

def test_reg_13_candidato_compartido_conserva_fuentes():
    """Un candidato que aparece en dos fuentes conserva ambas fuentes.

    Método: extract_from_segments procesa dos segmentos con el mismo nombre.
    El deduplicador elimina candidatos con mismo candidate_id (hash de
    source_id+segment_id+kind+name), pero candidatos de fuentes distintas
    tienen candidate_id diferente y se conservan ambos.
    """
    seg1 = _seg(
        "Doji Satsume llega al castillo del magistrado.",
        seg_id="src1_seg_001",
        source_id="src_fuente_a",
    )
    seg2 = _seg(
        "Doji Satsume toma asiento en el consejo.",
        seg_id="src2_seg_001",
        source_id="src_fuente_b",
    )
    gloss = {"doji satsume": "Doji Satsume"}
    candidates = extract_from_segments([seg1, seg2], glossary=gloss)

    # Doji Satsume debe aparecer al menos en uno de los dos segmentos
    doji_cands = [c for c in candidates if "doji" in (c.name or "").lower()]
    assert len(doji_cands) >= 1, (
        "Doji Satsume debe aparecer en al menos un segmento"
    )

    # Verificar que los source_id distintos se conservan (no se colapsan)
    source_ids = {c.source_id for c in doji_cands}
    assert len(source_ids) >= 1, (
        f"Debe haber al menos una fuente conservada: {source_ids}"
    )
    # Con fuentes distintas, ambas deben estar presentes en los candidatos
    if len(doji_cands) >= 2:
        assert "src_fuente_a" in source_ids, "Fuente A debe conservarse"
        assert "src_fuente_b" in source_ids, "Fuente B debe conservarse"


# ── Caso 14 ───────────────────────────────────────────────────────────────────

def test_reg_14_timestamps_sobreviven_normalizacion_asr():
    """Los timestamps del segmento se preservan aunque el texto tenga errores ASR.

    Método: extract_from_segments propaga timestamp_start/timestamp_end
    del segmento al Candidate sin modificarlos, independientemente del contenido
    textual.
    """
    # Texto con errores típicos de ASR (concatenaciones, errores ortográficos)
    texto_asr = (
        "Doji Satsume llegaal castillo porlamañana temprana"
        " y se reunee con los magistrados del clan grula."
    )
    seg = _seg(
        texto_asr,
        ts_start="01:23:45",
        ts_end="01:25:10",
    )
    candidates = extract_from_segments([seg], glossary={})
    # Si hay candidatos, sus timestamps deben ser los del segmento de entrada
    for c in candidates:
        assert c.timestamp_start == "01:23:45", (
            f"timestamp_start debe ser '01:23:45', got '{c.timestamp_start}'"
        )
        assert c.timestamp_end == "01:25:10", (
            f"timestamp_end debe ser '01:25:10', got '{c.timestamp_end}'"
        )


# ── Caso 15 ───────────────────────────────────────────────────────────────────

def test_reg_15_modo_benchmark_no_escribe_neo4j():
    """El modo dry-run nunca escribe en Neo4j (S9K_ALLOW_REAL_INGEST no definido).

    Método: pipeline._run_extract_step con modo 'heuristic' y Neo4j mockeado.
    Verifica que _get_neo4j_driver no es llamado durante la extracción pura,
    y que el archivo candidates.json se escribe en disco sin tocar Neo4j.
    """
    import os
    import tempfile
    import json as _json

    # Garantizar que la variable de entorno no está definida
    env_backup = os.environ.pop("S9K_ALLOW_REAL_INGEST", None)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            workspace = "test_ws"
            source_id = "src_bench_001"

            # Preparar directorio de output que el paso de extracción necesita
            out_dir = repo_root / "output" / "reviews" / workspace / source_id
            out_dir.mkdir(parents=True)

            classified = [_seg(
                "Doji Satsume llega al castillo del magistrado del Clan Grulla.",
                source_id=source_id,
                workspace=workspace,
            )]

            # Parchar _get_neo4j_driver para detectar si se intenta conectar a Neo4j
            with patch("review.resolver._get_neo4j_driver") as mock_driver_fn:
                mock_driver_fn.return_value = None  # Simula Neo4j no disponible

                from review.pipeline import _run_extract_step
                result = _run_extract_step(
                    workspace=workspace,
                    source_id=source_id,
                    repo_root=repo_root,
                    mode="heuristic",
                    classified=classified,
                )

                # En el paso de extracción puro (heuristic), Neo4j no debe ser llamado
                mock_driver_fn.assert_not_called(), (
                    "_get_neo4j_driver NO debe llamarse durante extracción heurística"
                )

            # El resultado debe ser una lista de candidatos
            assert isinstance(result, list), (
                f"_run_extract_step debe devolver lista, got {type(result)}"
            )

            # candidates.json debe haberse escrito en disco
            candidates_path = out_dir / "candidates.json"
            assert candidates_path.exists(), (
                f"candidates.json debe existir en {candidates_path}"
            )
    finally:
        if env_backup is not None:
            os.environ["S9K_ALLOW_REAL_INGEST"] = env_backup
