# -*- coding: utf-8 -*-
"""Ledger temporal V3: ciclo de vida, bitemporalidad, snapshot y rollback.

Fixtures PROPIAS (no se importan las de `contracts/knowledge-v3/v1/tests/`): el
ledger debe poder construir sus documentos por si mismo, y compartir el
constructor de otro subsistema haria que un cambio alli pusiera rojo esto por
motivos ajenos.

Todos los instantes son datos literales del test. Ninguna prueba depende del
reloj: si dependiera, manana fallaria sola.
"""
from __future__ import annotations

import hashlib
import json

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.contracts import (  # noqa: E402
    AssertionStatus,
    FactAssertion,
    V3ContractError,
)
from knowledge_v3.ledger import (  # noqa: E402
    CANONICAL_REASONS,
    CREATION_STATUSES,
    GENESIS_HASH,
    LIVE_STATUSES,
    STATUS_TRANSITIONS,
    TERMINAL_STATUSES,
    InMemoryLedgerStore,
    JsonlLedgerStore,
    LedgerError,
    LedgerOperation,
    LedgerTransitionError,
    LedgerWorkspaceError,
    TemporalLedger,
    check_transition,
    logical_identity,
    project,
)

# --------------------------------------------------------------------------
# Fixtures propias
# --------------------------------------------------------------------------
WORKSPACE = "leyenda"
COLLECTION = "collection:campana-leyenda"


def _hash(seed: str) -> dict:
    return {"algorithm": "sha256", "value": hashlib.sha256(seed.encode()).hexdigest()}


def make_assertion(
    assertion_id: str = "assertion:0001",
    *,
    subject: str = "entity:daiki",
    obj: str = "entity:casa-del-ciervo",
    predicate: str = "MEMBER_OF",
    recorded_at: str = "2026-01-10T09:00:00Z",
    valid_from: str | None = "1041-01-01T00:00:00Z",
    valid_to: str | None = None,
    event_time: str | None = "1041-01-01T00:00:00Z",
    status: str = "ASSERTED",
    state: str = "ACTIVE",
    epistemic_status: str = "ASSERTED",
    confidence: float = 0.72,
    negated: bool = False,
    evidence: tuple = ("fragment:p12:0",),
    episodes: tuple = ("episode:manual-001:p12",),
    workspace: str = WORKSPACE,
) -> dict:
    """Documento `fact-assertion/v3-internal-v1` valido y determinista."""
    return {
        "contract_id": "fact-assertion/v3-internal-v1",
        "contract_version": "1.0.0",
        "workspace": workspace,
        "source_asset_id": "asset:manual-001",
        "source_hash": _hash("asset:manual-001"),
        "provider_trace": [
            {
                "step": "engine.decide",
                "provider": "local",
                "name": "s9k.knowledge_v3",
                "version": "3.0.0",
                "model": None,
                "produced": ["predicate", "direction", "status"],
            }
        ],
        "produced_by_step": "engine.decide",
        "assertion_id": assertion_id,
        "subject_entity_id": subject,
        "object_entity_id": obj,
        "predicate": predicate,
        "direction": "SUBJECT_TO_OBJECT",
        "valid_from": valid_from,
        "valid_to": valid_to,
        "recorded_at": recorded_at,
        "epistemic_status": epistemic_status,
        "confidence": confidence,
        "status": status,
        "state": state,
        "event_time": event_time,
        "calendar_id": "calendar:umbra",
        "collection_id": COLLECTION,
        "game_profile": "generic",
        "engine_version": "3.0.0",
        "ontology_version": "core-1.4.0",
        "evidence_fragment_ids": list(evidence),
        "episode_ids": list(episodes),
        "supersedes": None,
        "superseded_by": None,
        "negated": False if not negated else True,
    }


@pytest.fixture()
def ledger() -> TemporalLedger:
    return TemporalLedger(WORKSPACE, InMemoryLedgerStore())


@pytest.fixture()
def seeded(ledger: TemporalLedger) -> TemporalLedger:
    """Ledger con una afirmacion inicial en `2026-01-10T09:00:00Z`."""
    ledger.assert_fact(make_assertion())
    return ledger


# ==========================================================================
# 1. Entradas, almacen y append-only
# ==========================================================================
def test_fixture_is_a_valid_frozen_contract_document():
    FactAssertion.from_dict(make_assertion()).validate()


def test_entry_hash_is_deterministic(seeded: TemporalLedger):
    entry = seeded.entries()[0]
    assert entry.entry_hash == entry.computed_hash()
    assert entry.prev_hash == GENESIS_HASH
    assert entry.seq == 0 and entry.revision == 1


def test_entries_are_chained(seeded: TemporalLedger):
    seeded.confirm(
        "assertion:0001",
        recorded_at="2026-02-01T09:00:00Z",
        evidence_fragment_ids=["fragment:p20:1"],
    )
    a, b = seeded.entries()
    assert b.prev_hash == a.entry_hash
    assert seeded.verify_chain() is True


def test_in_memory_store_returns_copies(seeded: TemporalLedger):
    """Mutar lo que devuelve el almacen NO puede alterar el ledger."""
    entries = seeded.entries()
    entries[0].assertion["confidence"] = 0.01
    assert seeded.entries()[0].assertion["confidence"] == 0.72
    assert seeded.verify_chain() is True


def test_view_documents_are_copies(seeded: TemporalLedger):
    doc = seeded.view().document("assertion:0001")
    doc["status"] = "RETRACTED"
    assert seeded.current("assertion:0001")["status"] == "ASSERTED"


def test_store_rejects_out_of_order_seq(seeded: TemporalLedger):
    entry = seeded.entries()[0]
    with pytest.raises(ValueError, match="fuera de orden"):
        seeded.store.append(entry)


def test_jsonl_store_never_rewrites_previous_lines(tmp_path):
    path = tmp_path / "ledger.jsonl"
    led = TemporalLedger(WORKSPACE, JsonlLedgerStore(path))
    led.assert_fact(make_assertion())
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    led.confirm(
        "assertion:0001",
        recorded_at="2026-02-01T09:00:00Z",
        evidence_fragment_ids=["fragment:p20:1"],
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0] == first_line  # byte a byte: la primera linea no se toco
    assert json.loads(lines[0])["seq"] == 0


def test_jsonl_round_trip_is_byte_stable(tmp_path):
    path = tmp_path / "ledger.jsonl"
    led = TemporalLedger(WORKSPACE, JsonlLedgerStore(path))
    led.assert_fact(make_assertion())
    reloaded = TemporalLedger(WORKSPACE, JsonlLedgerStore(path))
    assert reloaded.entries()[0].to_json() == led.entries()[0].to_json()


def test_the_ledger_never_reads_a_clock():
    """Ninguna funcion del ledger genera timestamps: entran como dato."""
    import knowledge_v3.ledger as pkg
    from pathlib import Path

    prohibited = ("datetime.now", "utcnow", "time.time(", "date.today")
    for src in sorted(Path(pkg.__file__).parent.glob("*.py")):
        text = src.read_text(encoding="utf-8")
        for needle in prohibited:
            assert needle not in text, f"{src.name} usa un reloj: {needle}"


# ==========================================================================
# 2. ASSERT
# ==========================================================================
def test_assert_appends_and_materializes(seeded: TemporalLedger):
    assert len(seeded) == 1
    assert seeded.current("assertion:0001")["status"] == "ASSERTED"
    assert [r.assertion_id for r in seeded.live()] == ["assertion:0001"]


def test_assert_rejects_document_that_breaks_the_frozen_contract(ledger: TemporalLedger):
    bad = make_assertion()
    bad["campo_inventado"] = 1
    with pytest.raises(V3ContractError):
        ledger.assert_fact(bad)
    assert len(ledger) == 0


def test_assert_rejects_state_active_with_valid_to(ledger: TemporalLedger):
    bad = make_assertion(valid_to="1050-01-01T00:00:00Z")  # state ACTIVE
    with pytest.raises(V3ContractError):
        ledger.assert_fact(bad)


def test_assert_rejects_duplicate_assertion_id(seeded: TemporalLedger):
    with pytest.raises(LedgerError, match="ya existe"):
        seeded.assert_fact(make_assertion(recorded_at="2026-03-01T09:00:00Z"))


def test_assert_rejects_duplicate_logical_identity(seeded: TemporalLedger):
    twin = make_assertion("assertion:0009", recorded_at="2026-03-01T09:00:00Z")
    assert logical_identity(twin) == logical_identity(make_assertion())
    with pytest.raises(LedgerError, match="misma identidad logica"):
        seeded.assert_fact(twin)


def test_assert_allows_duplicate_identity_only_when_explicit(seeded: TemporalLedger):
    twin = make_assertion("assertion:0009", recorded_at="2026-03-01T09:00:00Z")
    seeded.assert_fact(twin, allow_duplicate_identity=True)
    assert len(seeded.live()) == 2


def test_assert_rejects_birth_in_a_non_creation_status(ledger: TemporalLedger):
    with pytest.raises(LedgerTransitionError):
        ledger.assert_fact(make_assertion(status="CONFIRMED"))
    assert AssertionStatus.CONFIRMED not in CREATION_STATUSES


def test_assert_rejects_backwards_transaction_time(seeded: TemporalLedger):
    late = make_assertion(
        "assertion:0002", subject="entity:ren", recorded_at="2025-12-01T09:00:00Z"
    )
    with pytest.raises(LedgerError, match="no retrocede"):
        seeded.assert_fact(late)


def test_assert_rejects_foreign_workspace(ledger: TemporalLedger):
    with pytest.raises(LedgerWorkspaceError):
        ledger.assert_fact(make_assertion(workspace="otra-boveda"))


# ==========================================================================
# 3. CONFIRM
# ==========================================================================
def test_confirm_creates_a_new_revision_without_touching_the_previous(seeded: TemporalLedger):
    before = seeded.entries()[0].to_json()
    seeded.confirm(
        "assertion:0001",
        recorded_at="2026-02-01T09:00:00Z",
        evidence_fragment_ids=["fragment:p20:1"],
        confidence=0.9,
    )
    assert seeded.entries()[0].to_json() == before  # la revision 1 intacta
    current = seeded.current("assertion:0001")
    assert current["status"] == "CONFIRMED"
    assert current["confidence"] == 0.9
    assert current["evidence_fragment_ids"] == ["fragment:p12:0", "fragment:p20:1"]
    history = seeded.history("assertion:0001")
    assert [h.revision for h in history] == [1, 2]
    assert history[0].document["status"] == "ASSERTED"


def test_confirm_requires_genuinely_new_evidence(seeded: TemporalLedger):
    with pytest.raises(LedgerError, match="sin evidencia nueva"):
        seeded.confirm(
            "assertion:0001",
            recorded_at="2026-02-01T09:00:00Z",
            evidence_fragment_ids=["fragment:p12:0"],
        )


def test_confirm_cannot_lower_confidence(seeded: TemporalLedger):
    with pytest.raises(LedgerError, match="no puede bajar la confianza"):
        seeded.confirm(
            "assertion:0001",
            recorded_at="2026-02-01T09:00:00Z",
            evidence_fragment_ids=["fragment:p20:1"],
            confidence=0.1,
        )


def test_confirm_blocked_on_planned_state(ledger: TemporalLedger):
    ledger.assert_fact(make_assertion(state="PLANNED"))
    with pytest.raises(LedgerError, match="PLANNED"):
        ledger.confirm(
            "assertion:0001",
            recorded_at="2026-02-01T09:00:00Z",
            evidence_fragment_ids=["fragment:p20:1"],
        )


def test_confirm_of_unknown_assertion(ledger: TemporalLedger):
    with pytest.raises(LedgerError, match="desconocida"):
        ledger.confirm(
            "assertion:nope",
            recorded_at="2026-02-01T09:00:00Z",
            evidence_fragment_ids=["fragment:x"],
        )


# ==========================================================================
# 4. SUPERSEDE
# ==========================================================================
def _successor(**kwargs) -> dict:
    base = {
        "assertion_id": "assertion:0002",
        "recorded_at": "2026-03-01T09:00:00Z",
        "valid_from": "1050-01-01T00:00:00Z",
        "event_time": "1050-01-01T00:00:00Z",
        "evidence": ("fragment:p30:0",),
    }
    base.update(kwargs)
    return make_assertion(**base)


def test_supersede_closes_validity_and_links_the_chain(seeded: TemporalLedger):
    new_entry, old_entry = seeded.supersede("assertion:0001", _successor())
    old = seeded.current("assertion:0001")
    assert old["status"] == "SUPERSEDED"
    assert old["superseded_by"] == "assertion:0002"
    assert old["valid_to"] == "1050-01-01T00:00:00Z"
    assert old["state"] == "ENDED"
    new = seeded.current("assertion:0002")
    assert new["supersedes"] == "assertion:0001"
    assert new["superseded_by"] is None
    assert seeded.supersession_chain("assertion:0001") == ["assertion:0001", "assertion:0002"]
    assert [r.assertion_id for r in seeded.live()] == ["assertion:0002"]
    assert new_entry.related_assertion_ids == ("assertion:0001",)
    assert old_entry.related_assertion_ids == ("assertion:0002",)


def test_supersede_is_atomic_in_transaction_time(seeded: TemporalLedger):
    seeded.supersede("assertion:0001", _successor())
    times = {e.recorded_at for e in seeded.entries()[1:]}
    assert times == {"2026-03-01T09:00:00Z"}
    # No existe ningun as-of que vea la nueva sin la vieja cerrada.
    view = seeded.view("2026-03-01T09:00:00Z")
    assert view.document("assertion:0001")["status"] == "SUPERSEDED"


def test_supersede_needs_an_explicit_valid_to_when_successor_has_no_valid_from(
    seeded: TemporalLedger,
):
    with pytest.raises(LedgerError, match="sin `valid_to`"):
        seeded.supersede("assertion:0001", _successor(valid_from=None, event_time=None))


def test_supersede_accepts_explicit_valid_to(seeded: TemporalLedger):
    seeded.supersede(
        "assertion:0001",
        _successor(valid_from=None, event_time=None),
        valid_to="1049-06-01T00:00:00Z",
    )
    assert seeded.current("assertion:0001")["valid_to"] == "1049-06-01T00:00:00Z"


def test_supersede_refuses_to_move_an_already_closed_validity(ledger: TemporalLedger):
    ledger.assert_fact(
        make_assertion(state="ENDED", valid_to="1045-01-01T00:00:00Z")
    )
    with pytest.raises(LedgerError, match="reescribir el pasado"):
        ledger.supersede("assertion:0001", _successor())


def test_supersede_rejects_reusing_the_same_assertion_id(seeded: TemporalLedger):
    with pytest.raises(LedgerError, match="no puede reutilizar"):
        seeded.supersede(
            "assertion:0001",
            _successor(assertion_id="assertion:0001"),
        )


def test_supersede_rejects_a_successor_that_starts_earlier(seeded: TemporalLedger):
    with pytest.raises(LedgerError, match="eso no es una supersesion"):
        seeded.supersede(
            "assertion:0001",
            _successor(valid_from="1030-01-01T00:00:00Z", event_time=None),
            valid_to="1031-01-01T00:00:00Z",
        )


def test_superseded_is_terminal(seeded: TemporalLedger):
    seeded.supersede("assertion:0001", _successor())
    assert STATUS_TRANSITIONS[AssertionStatus.SUPERSEDED] == frozenset()
    with pytest.raises(LedgerTransitionError):
        seeded.retract(
            "assertion:0001", recorded_at="2026-04-01T09:00:00Z",
            reason_code="EXTRACTION_ERROR",
        )


# ==========================================================================
# 5. CONTRADICT
# ==========================================================================
@pytest.fixture()
def two_facts(ledger: TemporalLedger) -> TemporalLedger:
    ledger.assert_fact(make_assertion("assertion:0001"))
    ledger.assert_fact(
        make_assertion(
            "assertion:0002",
            obj="entity:casa-del-cuervo",
            recorded_at="2026-01-11T09:00:00Z",
            evidence=("fragment:p14:0",),
        )
    )
    return ledger


def test_contradiction_marks_both_and_destroys_nothing(two_facts: TemporalLedger):
    before = [e.to_json() for e in two_facts.entries()]
    two_facts.contradict(
        "assertion:0001", "assertion:0002", recorded_at="2026-02-01T09:00:00Z"
    )
    assert [e.to_json() for e in two_facts.entries()[:2]] == before
    for aid in ("assertion:0001", "assertion:0002"):
        doc = two_facts.current(aid)
        assert doc["status"] == "CONTRADICTED"
        assert doc["epistemic_status"] == "CONFLICTED"
        assert doc["evidence_fragment_ids"]  # la evidencia sigue ahi
        assert len(two_facts.history(aid)) == 2


def test_contradicted_stays_live_and_visible(two_facts: TemporalLedger):
    two_facts.contradict(
        "assertion:0001", "assertion:0002", recorded_at="2026-02-01T09:00:00Z"
    )
    live = {r.assertion_id for r in two_facts.live()}
    assert live == {"assertion:0001", "assertion:0002"}
    assert AssertionStatus.CONTRADICTED in LIVE_STATUSES
    conflicted = {r.assertion_id for r in two_facts.view().conflicted()}
    assert conflicted == live


def test_a_contradiction_can_be_resolved_by_confirming_one_side(two_facts: TemporalLedger):
    two_facts.contradict(
        "assertion:0001", "assertion:0002", recorded_at="2026-02-01T09:00:00Z"
    )
    two_facts.confirm(
        "assertion:0001",
        recorded_at="2026-03-01T09:00:00Z",
        evidence_fragment_ids=["fragment:p40:0"],
    )
    two_facts.retract(
        "assertion:0002", recorded_at="2026-03-01T09:00:00Z",
        reason_code="EVIDENCE_INVALID",
    )
    assert two_facts.current("assertion:0001")["status"] == "CONFIRMED"
    assert [r.assertion_id for r in two_facts.live()] == ["assertion:0001"]


def test_contradiction_with_itself_is_rejected(seeded: TemporalLedger):
    with pytest.raises(LedgerError, match="a si misma"):
        seeded.contradict(
            "assertion:0001", "assertion:0001", recorded_at="2026-02-01T09:00:00Z"
        )


# ==========================================================================
# 6. RETRACT y ciclo completo
# ==========================================================================
def test_retract_keeps_the_history_and_drops_it_from_live(seeded: TemporalLedger):
    seeded.retract(
        "assertion:0001", recorded_at="2026-02-01T09:00:00Z",
        reason_code="EXTRACTION_ERROR",
    )
    assert seeded.current("assertion:0001")["status"] == "RETRACTED"
    assert seeded.live() == []
    assert len(seeded.history("assertion:0001")) == 2
    assert seeded.entries()[-1].reason_code == "EXTRACTION_ERROR"


def test_retract_requires_a_canonical_reason(seeded: TemporalLedger):
    with pytest.raises(LedgerError, match="no es canonico"):
        seeded.retract(
            "assertion:0001", recorded_at="2026-02-01T09:00:00Z",
            reason_code="PORQUE_SI",
        )


def test_retracted_is_terminal(seeded: TemporalLedger):
    seeded.retract(
        "assertion:0001", recorded_at="2026-02-01T09:00:00Z",
        reason_code="SOURCE_WITHDRAWN",
    )
    with pytest.raises(LedgerTransitionError):
        seeded.confirm(
            "assertion:0001", recorded_at="2026-03-01T09:00:00Z",
            evidence_fragment_ids=["fragment:zz"],
        )


def test_full_lifecycle_assert_confirm_supersede_retract(ledger: TemporalLedger):
    ledger.assert_fact(make_assertion())
    ledger.confirm(
        "assertion:0001",
        recorded_at="2026-02-01T09:00:00Z",
        evidence_fragment_ids=["fragment:p20:1"],
        confidence=0.88,
    )
    ledger.supersede("assertion:0001", _successor())
    ledger.retract(
        "assertion:0002", recorded_at="2026-04-01T09:00:00Z",
        reason_code="OPERATOR_RETRACTION",
    )
    assert [e.operation for e in ledger.entries()] == [
        LedgerOperation.ASSERT.value,
        LedgerOperation.CONFIRM.value,
        LedgerOperation.SUPERSEDE.value,
        LedgerOperation.SUPERSEDE.value,
        LedgerOperation.RETRACT.value,
    ]
    assert [h.revision for h in ledger.history("assertion:0001")] == [1, 2, 3]
    assert ledger.live() == []
    assert ledger.verify_chain(validate_documents=True) is True


# ==========================================================================
# 7. Matriz de transiciones (cerrada)
# ==========================================================================
def test_the_matrix_covers_every_status_and_only_those():
    keys = {k for k in STATUS_TRANSITIONS if k is not None}
    assert keys == set(AssertionStatus)
    assert None in STATUS_TRANSITIONS
    for terminal in TERMINAL_STATUSES:
        assert STATUS_TRANSITIONS[terminal] == frozenset()


@pytest.mark.parametrize(
    "origen,destino",
    [
        (AssertionStatus.SUPERSEDED, AssertionStatus.CONFIRMED),
        (AssertionStatus.SUPERSEDED, AssertionStatus.RETRACTED),
        (AssertionStatus.RETRACTED, AssertionStatus.ASSERTED),
        (AssertionStatus.RETRACTED, AssertionStatus.CONFIRMED),
        (AssertionStatus.ASSERTED, AssertionStatus.PROVISIONAL),
        (AssertionStatus.CONFIRMED, AssertionStatus.ASSERTED),
        (None, AssertionStatus.SUPERSEDED),
        (None, AssertionStatus.CONFIRMED),
        (None, AssertionStatus.CONTRADICTED),
    ],
)
def test_illegal_transitions_are_rejected(origen, destino):
    with pytest.raises(LedgerTransitionError):
        check_transition(origen, destino)


@pytest.mark.parametrize(
    "origen,destino",
    [
        (None, AssertionStatus.PROVISIONAL),
        (None, AssertionStatus.ASSERTED),
        (AssertionStatus.PROVISIONAL, AssertionStatus.ASSERTED),
        (AssertionStatus.ASSERTED, AssertionStatus.CONFIRMED),
        (AssertionStatus.CONFIRMED, AssertionStatus.SUPERSEDED),
        (AssertionStatus.CONTRADICTED, AssertionStatus.RETRACTED),
    ],
)
def test_legal_transitions_pass(origen, destino):
    check_transition(origen, destino)


def test_unknown_status_is_rejected():
    with pytest.raises(LedgerTransitionError):
        check_transition("INVENTADO", AssertionStatus.ASSERTED)


def test_reason_catalog_is_closed_per_operation():
    assert set(CANONICAL_REASONS) == set(LedgerOperation)
    for op, reasons in CANONICAL_REASONS.items():
        assert reasons, f"{op} sin motivos canonicos"


# ==========================================================================
# 8. Bitemporalidad
# ==========================================================================
@pytest.fixture()
def bitemporal(ledger: TemporalLedger) -> TemporalLedger:
    """Hecho vigente 1041-1050, sustituido por otro vigente desde 1050.

    El segundo se registra en 2026-03, mucho despues del evento del mundo.
    """
    ledger.assert_fact(make_assertion())
    ledger.supersede("assertion:0001", _successor())
    return ledger


def test_as_of_hides_knowledge_recorded_later(bitemporal: TemporalLedger):
    antes = bitemporal.view("2026-02-01T00:00:00Z")
    assert [r.assertion_id for r in antes.live()] == ["assertion:0001"]
    assert antes.document("assertion:0001")["status"] == "ASSERTED"
    assert antes.document("assertion:0001")["valid_to"] is None
    assert "assertion:0002" not in antes


def test_valid_time_and_transaction_time_are_independent(bitemporal: TemporalLedger):
    # Que era cierto en 1045, segun lo que se sabe HOY.
    en_1045 = bitemporal.valid_at("1045-01-01T00:00:00Z", include_non_live=True)
    assert [r.assertion_id for r in en_1045] == ["assertion:0001"]
    # Que era cierto en 1060, segun lo que se sabe HOY.
    en_1060 = bitemporal.valid_at("1060-01-01T00:00:00Z")
    assert [r.assertion_id for r in en_1060] == ["assertion:0002"]


def test_a_fact_recorded_late_about_a_past_validity(ledger: TemporalLedger):
    """Registrado en 2026-05; valido en el mundo desde 1010.

    El eje de transaccion no se toca: el hecho no existia para el sistema en
    2026-01, aunque en el mundo fuese cierto desde hacia siglos.
    """
    ledger.assert_fact(
        make_assertion(
            "assertion:0100",
            subject="entity:ren",
            recorded_at="2026-05-01T09:00:00Z",
            valid_from="1010-01-01T00:00:00Z",
            event_time="1010-01-01T00:00:00Z",
        )
    )
    assert ledger.view("2026-01-01T00:00:00Z").live() == []
    tarde = ledger.valid_at("1015-01-01T00:00:00Z", as_of="2026-06-01T00:00:00Z")
    assert [r.assertion_id for r in tarde] == ["assertion:0100"]
    # Y como no se sabia en 2026-01, esa consulta bitemporal no lo ve.
    assert ledger.valid_at("1015-01-01T00:00:00Z", as_of="2026-01-01T00:00:00Z") == []


def test_validity_interval_is_half_open(bitemporal: TemporalLedger):
    """En el instante exacto del relevo solo vale la version nueva."""
    en_el_corte = bitemporal.valid_at("1050-01-01T00:00:00Z", include_non_live=True)
    assert [r.assertion_id for r in en_el_corte] == ["assertion:0002"]


def test_unknown_valid_from_is_not_assumed_valid(ledger: TemporalLedger):
    ledger.assert_fact(
        make_assertion("assertion:0200", valid_from=None, event_time=None, state="UNKNOWN")
    )
    assert ledger.valid_at("1500-01-01T00:00:00Z") == []
    incluido = ledger.valid_at("1500-01-01T00:00:00Z", include_unknown_start=True)
    assert [r.assertion_id for r in incluido] == ["assertion:0200"]


def test_event_time_is_a_third_axis(ledger: TemporalLedger):
    """El juramento ocurre en 1041; su efecto dura hasta 1050."""
    ledger.assert_fact(
        make_assertion(valid_from="1041-01-01T00:00:00Z", event_time="1041-01-01T00:00:00Z")
    )
    view = ledger.view()
    assert [r.assertion_id for r in view.by_event_time("1040-01-01T00:00:00Z", "1042-01-01T00:00:00Z")] == [
        "assertion:0001"
    ]
    assert view.by_event_time("1045-01-01T00:00:00Z") == []
    # ... pero en 1045 el hecho SIGUE vigente aunque el evento fuese en 1041.
    assert [r.assertion_id for r in view.valid_at("1045-01-01T00:00:00Z")] == ["assertion:0001"]


def test_fractional_seconds_do_not_break_the_order(ledger: TemporalLedger):
    """`10:00:00Z` va ANTES que `10:00:00.5Z`, pese al orden lexicografico."""
    ledger.assert_fact(make_assertion(recorded_at="2026-01-10T09:00:00Z"))
    ledger.confirm(
        "assertion:0001",
        recorded_at="2026-01-10T09:00:00.500Z",
        evidence_fragment_ids=["fragment:p20:1"],
    )
    assert ledger.verify_chain() is True
    assert ledger.view("2026-01-10T09:00:00.250Z").document("assertion:0001")["status"] == "ASSERTED"
    assert ledger.view("2026-01-10T09:00:00.750Z").document("assertion:0001")["status"] == "CONFIRMED"


def test_as_of_must_be_a_valid_instant(seeded: TemporalLedger):
    with pytest.raises(LedgerError, match="ISO-8601"):
        seeded.view("ayer")


# ==========================================================================
# 9. Snapshot determinista
# ==========================================================================
def test_same_ledger_same_snapshot_id(bitemporal: TemporalLedger):
    assert bitemporal.snapshot().snapshot_id == bitemporal.snapshot().snapshot_id


def test_two_ledgers_with_the_same_content_share_the_snapshot_id(tmp_path):
    def build(store):
        led = TemporalLedger(WORKSPACE, store)
        led.assert_fact(make_assertion())
        led.supersede("assertion:0001", _successor())
        return led

    memoria = build(InMemoryLedgerStore())
    fichero = build(JsonlLedgerStore(tmp_path / "l.jsonl"))
    assert memoria.snapshot().snapshot_id == fichero.snapshot().snapshot_id
    assert memoria.snapshot().snapshot_id.startswith("snapshot:sha256:")


def test_any_operation_changes_the_snapshot_id(seeded: TemporalLedger):
    antes = seeded.snapshot().snapshot_id
    seeded.confirm(
        "assertion:0001", recorded_at="2026-02-01T09:00:00Z",
        evidence_fragment_ids=["fragment:p20:1"],
    )
    assert seeded.snapshot().snapshot_id != antes


def test_snapshot_id_is_content_not_time(seeded: TemporalLedger):
    """Sin cambios, el ancla es la misma aunque se pregunte mas tarde."""
    a = seeded.snapshot("2026-01-20T00:00:00Z")
    b = seeded.snapshot("2026-06-20T00:00:00Z")
    assert a.snapshot_id == b.snapshot_id
    assert a.as_of != b.as_of


def test_snapshot_offers_expected_version_and_hash_for_the_plan(seeded: TemporalLedger):
    snap = seeded.snapshot()
    version, hash_ = snap.expected_for_assertion("assertion:0001")
    assert version == 1
    assert hash_["algorithm"] == "sha256" and len(hash_["value"]) == 64
    ent_version, ent_hash = snap.expected_for_entity("entity:daiki")
    assert ent_version == 1 and ent_hash["algorithm"] == "sha256"
    # Lo que no existe se declara como creacion: (None, None).
    assert snap.expected_for_entity("entity:nadie") == (None, None)


def test_supersession_bumps_the_entity_version(seeded: TemporalLedger):
    antes_v, antes_h = seeded.snapshot().expected_for_entity("entity:daiki")
    seeded.supersede("assertion:0001", _successor())
    despues_v, despues_h = seeded.snapshot().expected_for_entity("entity:daiki")
    assert despues_v > antes_v
    assert despues_h != antes_h


def test_snapshot_lists_live_and_conflicted(two_facts: TemporalLedger):
    two_facts.contradict(
        "assertion:0001", "assertion:0002", recorded_at="2026-02-01T09:00:00Z"
    )
    snap = two_facts.snapshot()
    assert set(snap.live_assertion_ids) == {"assertion:0001", "assertion:0002"}
    assert set(snap.conflicted_assertion_ids) == {"assertion:0001", "assertion:0002"}


# ==========================================================================
# 10. Rollback
# ==========================================================================
def test_rollback_reconstructs_the_exact_past_state(ledger: TemporalLedger):
    ledger.assert_fact(make_assertion())
    antes = ledger.snapshot()
    doc_antes = ledger.current("assertion:0001")

    ledger.confirm(
        "assertion:0001", recorded_at="2026-02-01T09:00:00Z",
        evidence_fragment_ids=["fragment:p20:1"], confidence=0.95,
    )
    ledger.supersede("assertion:0001", _successor())
    ledger.retract(
        "assertion:0002", recorded_at="2026-04-01T09:00:00Z",
        reason_code="EXTRACTION_ERROR",
    )

    reconstruido = ledger.rollback_to("2026-01-10T09:00:00Z")
    assert reconstruido.document("assertion:0001") == doc_antes
    assert [r.assertion_id for r in reconstruido.live()] == ["assertion:0001"]
    assert ledger.snapshot("2026-01-10T09:00:00Z").snapshot_id == antes.snapshot_id


def test_rollback_needs_nothing_but_the_ledger_file(tmp_path):
    """El estado pasado sale del fichero JSONL y de nada mas."""
    path = tmp_path / "ledger.jsonl"
    led = TemporalLedger(WORKSPACE, JsonlLedgerStore(path))
    led.assert_fact(make_assertion())
    ancla = led.snapshot().snapshot_id
    led.supersede("assertion:0001", _successor())
    del led

    otro = TemporalLedger(WORKSPACE, JsonlLedgerStore(path))
    assert otro.snapshot("2026-01-10T09:00:00Z").snapshot_id == ancla
    assert otro.rollback_to("2026-01-10T09:00:00Z").document("assertion:0001")["status"] == "ASSERTED"


def test_rollback_before_the_genesis_is_an_empty_world(seeded: TemporalLedger):
    vacio = seeded.rollback_to("2020-01-01T00:00:00Z")
    assert len(vacio) == 0 and vacio.live() == []


def test_rollback_is_the_same_code_path_as_as_of(seeded: TemporalLedger):
    assert TemporalLedger.rollback_to is TemporalLedger.view


# ==========================================================================
# 11. Proyeccion
# ==========================================================================
def test_projection_only_shows_live_assertions(ledger: TemporalLedger):
    ledger.assert_fact(make_assertion())
    ledger.supersede("assertion:0001", _successor())
    edges = project(ledger.view())
    assert [e.assertion_id for e in edges] == ["assertion:0002"]
    assert edges[0].subject_entity_id == "entity:daiki"
    assert edges[0].predicate == "MEMBER_OF"


def test_projection_carries_the_authority_back_to_the_assertion(seeded: TemporalLedger):
    edge = project(seeded.view())[0]
    assert edge.assertion_id in seeded.view()
    assert edge.revision == 1
    assert edge.to_dict()["valid_from"] == "1041-01-01T00:00:00Z"


def test_projection_can_be_asked_for_a_world_time(ledger: TemporalLedger):
    ledger.assert_fact(make_assertion())
    ledger.supersede("assertion:0001", _successor())
    assert project(ledger.view(), world_time="1045-01-01T00:00:00Z") == []
    en_1060 = project(ledger.view(), world_time="1060-01-01T00:00:00Z")
    assert [e.assertion_id for e in en_1060] == ["assertion:0002"]
