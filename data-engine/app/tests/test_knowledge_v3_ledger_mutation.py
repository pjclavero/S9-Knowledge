# -*- coding: utf-8 -*-
"""Pruebas de MUTACION del ledger temporal.

Cada test de aqui existe para poner en rojo una forma concreta de romper el
subsistema. Si alguien quita la verificacion de cadena, permite mutar una
entrada en el sitio o afloja la matriz de transiciones, esta suite lo dice.

Las manipulaciones se hacen sobre el fichero JSONL, que es donde un atacante o
un descuido tendria acceso real: reescribir una linea es exactamente el ataque
que la cadena de custodia debe detectar.

Las fixtures se reutilizan del modulo hermano `test_knowledge_v3_ledger`: dos
constructores distintos del mismo documento acabarian divergiendo y una de las
dos suites probaria un contrato que ya no existe.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("jsonschema")

from knowledge_v3.contracts import AssertionStatus, V3ContractError  # noqa: E402
from knowledge_v3.ledger import (  # noqa: E402
    GENESIS_HASH,
    InMemoryLedgerStore,
    JsonlLedgerStore,
    LedgerEntry,
    LedgerError,
    LedgerIntegrityError,
    LedgerOperation,
    LedgerTransitionError,
    LedgerWorkspaceError,
    TemporalLedger,
    check_transition,
    compute_entry_hash,
    make_entry,
)
from test_knowledge_v3_ledger import (  # noqa: E402
    WORKSPACE,
    _successor,
    make_assertion,
)


@pytest.fixture()
def jsonl_ledger(tmp_path):
    """Ledger de tres entradas en fichero: assert -> confirm -> supersede(x2)."""
    path = tmp_path / "ledger.jsonl"
    led = TemporalLedger(WORKSPACE, JsonlLedgerStore(path))
    led.assert_fact(make_assertion())
    led.confirm(
        "assertion:0001",
        recorded_at="2026-02-01T09:00:00Z",
        evidence_fragment_ids=["fragment:p20:1"],
        confidence=0.9,
    )
    led.supersede("assertion:0001", _successor())
    assert led.verify_chain() is True
    return path


def _lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write(path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
                for r in rows),
        encoding="utf-8",
    )


# ==========================================================================
# 1. Manipulacion de una entrada antigua
# ==========================================================================
def test_editing_an_old_entry_breaks_the_verification(jsonl_ledger):
    rows = _lines(jsonl_ledger)
    rows[0]["assertion"]["confidence"] = 0.99
    _write(jsonl_ledger, rows)
    with pytest.raises(LedgerIntegrityError, match="entry_hash no corresponde"):
        TemporalLedger(WORKSPACE, JsonlLedgerStore(jsonl_ledger))


def test_editing_an_old_entry_and_resealing_it_breaks_the_next_link(jsonl_ledger):
    """El retoque local no basta: hay que reescribir el ledger entero."""
    rows = _lines(jsonl_ledger)
    rows[0]["assertion"]["confidence"] = 0.99
    body = {k: v for k, v in rows[0].items() if k != "entry_hash"}
    rows[0]["entry_hash"] = compute_entry_hash(body)
    _write(jsonl_ledger, rows)
    with pytest.raises(LedgerIntegrityError, match="no enlaza"):
        TemporalLedger(WORKSPACE, JsonlLedgerStore(jsonl_ledger))


def test_changing_the_status_of_an_old_entry_is_detected(jsonl_ledger):
    rows = _lines(jsonl_ledger)
    rows[1]["assertion"]["status"] = "RETRACTED"
    _write(jsonl_ledger, rows)
    with pytest.raises(LedgerIntegrityError):
        TemporalLedger(WORKSPACE, JsonlLedgerStore(jsonl_ledger))


def test_changing_the_reason_code_is_detected(jsonl_ledger):
    rows = _lines(jsonl_ledger)
    rows[-1]["reason_code"] = "CORROBORATING_EVIDENCE"
    _write(jsonl_ledger, rows)
    with pytest.raises(LedgerIntegrityError):
        TemporalLedger(WORKSPACE, JsonlLedgerStore(jsonl_ledger))


# ==========================================================================
# 2. Borrado, reordenacion e insercion
# ==========================================================================
def test_deleting_an_entry_breaks_the_chain(jsonl_ledger):
    rows = _lines(jsonl_ledger)
    del rows[1]
    _write(jsonl_ledger, rows)
    with pytest.raises(LedgerIntegrityError):
        TemporalLedger(WORKSPACE, JsonlLedgerStore(jsonl_ledger))


def test_truncating_the_tail_is_detected_by_the_snapshot_not_by_the_chain(jsonl_ledger):
    """Cortar por el final deja una cadena valida: es el limite honesto del diseno.

    Un log encadenado detecta ediciones e inserciones, pero NO un truncado
    limpio del final, porque el prefijo sigue siendo una cadena legitima. Lo que
    lo delata es el `snapshot_id`: el ancla que el motor cito ya no se puede
    reproducir. Se documenta como limite, no se disimula.
    """
    completo = TemporalLedger(WORKSPACE, JsonlLedgerStore(jsonl_ledger))
    ancla = completo.snapshot().snapshot_id

    rows = _lines(jsonl_ledger)
    _write(jsonl_ledger, rows[:-1])
    truncado = TemporalLedger(WORKSPACE, JsonlLedgerStore(jsonl_ledger))
    assert truncado.verify_chain() is True  # la cadena prefijo es valida
    assert truncado.snapshot().snapshot_id != ancla  # pero el ancla ya no cuadra


def test_reordering_entries_breaks_the_chain(jsonl_ledger):
    rows = _lines(jsonl_ledger)
    rows[0], rows[1] = rows[1], rows[0]
    _write(jsonl_ledger, rows)
    with pytest.raises(LedgerIntegrityError):
        TemporalLedger(WORKSPACE, JsonlLedgerStore(jsonl_ledger))


def test_an_unreadable_line_is_not_silently_skipped(jsonl_ledger):
    with jsonl_ledger.open("a", encoding="utf-8") as fh:
        fh.write("{esto no es json}\n")
    with pytest.raises(ValueError, match="ilegible"):
        TemporalLedger(WORKSPACE, JsonlLedgerStore(jsonl_ledger))


def test_an_entry_with_unknown_fields_is_rejected(jsonl_ledger):
    rows = _lines(jsonl_ledger)
    rows[0]["firmado_por"] = "nvidia"
    _write(jsonl_ledger, rows)
    with pytest.raises(ValueError, match="campos desconocidos"):
        TemporalLedger(WORKSPACE, JsonlLedgerStore(jsonl_ledger))


# ==========================================================================
# 3. Entradas fabricadas a mano (saltandose la API del ledger)
# ==========================================================================
def _forge(store, *, prev_hash, seq, recorded_at, assertion, revision=1, workspace=WORKSPACE):
    store.append(
        make_entry(
            seq=seq,
            operation=LedgerOperation.ASSERT,
            recorded_at=recorded_at,
            workspace=workspace,
            assertion=assertion,
            revision=revision,
            reason_code="INITIAL_ASSERTION",
            prev_hash=prev_hash,
        )
    )


def test_a_forged_entry_going_back_in_transaction_time_is_caught():
    store = InMemoryLedgerStore()
    a = make_assertion(recorded_at="2026-03-01T09:00:00Z")
    _forge(store, prev_hash=GENESIS_HASH, seq=0, recorded_at=a["recorded_at"], assertion=a)
    b = make_assertion("assertion:0002", subject="entity:ren", recorded_at="2026-01-01T09:00:00Z")
    _forge(
        store, prev_hash=store.last().entry_hash, seq=1,
        recorded_at=b["recorded_at"], assertion=b,
    )
    with pytest.raises(LedgerIntegrityError, match="retrocede"):
        TemporalLedger(WORKSPACE, store)


def test_a_forged_entry_from_another_workspace_is_caught():
    store = InMemoryLedgerStore()
    a = make_assertion(workspace="otra-boveda")
    _forge(
        store, prev_hash=GENESIS_HASH, seq=0, recorded_at=a["recorded_at"],
        assertion=a, workspace="otra-boveda",
    )
    with pytest.raises(LedgerWorkspaceError):
        TemporalLedger(WORKSPACE, store)


def test_a_forged_revision_number_is_caught():
    store = InMemoryLedgerStore()
    a = make_assertion()
    _forge(
        store, prev_hash=GENESIS_HASH, seq=0, recorded_at=a["recorded_at"],
        assertion=a, revision=7,
    )
    with pytest.raises(LedgerIntegrityError, match="revision"):
        TemporalLedger(WORKSPACE, store)


def test_a_document_that_breaks_the_frozen_contract_is_caught_in_deep_verification():
    """`superseded_by` sin `status=SUPERSEDED` es invalido en el contrato."""
    store = InMemoryLedgerStore()
    a = make_assertion()
    a["superseded_by"] = "assertion:0002"
    _forge(store, prev_hash=GENESIS_HASH, seq=0, recorded_at=a["recorded_at"], assertion=a)
    led = TemporalLedger(WORKSPACE, store, verify_on_load=False)
    assert led.verify_chain() is True  # la cadena esta bien: el documento no
    with pytest.raises(V3ContractError):
        led.verify_chain(validate_documents=True)


def test_entry_and_document_cannot_disagree_on_the_transaction_time():
    store = InMemoryLedgerStore()
    a = make_assertion(recorded_at="2026-01-10T09:00:00Z")
    _forge(store, prev_hash=GENESIS_HASH, seq=0, recorded_at="2026-05-05T09:00:00Z", assertion=a)
    with pytest.raises(LedgerIntegrityError, match="dos tiempos de transaccion"):
        TemporalLedger(WORKSPACE, store)


def test_entry_and_document_cannot_disagree_on_the_assertion_id():
    store = InMemoryLedgerStore()
    a = make_assertion()
    entry = make_entry(
        seq=0, operation=LedgerOperation.ASSERT, recorded_at=a["recorded_at"],
        workspace=WORKSPACE, assertion=a, revision=1,
        reason_code="INITIAL_ASSERTION", prev_hash=GENESIS_HASH,
    )
    forged = LedgerEntry(**{**entry.to_dict(), "assertion_id": "assertion:otra"})
    forged = LedgerEntry(
        **{**forged.to_dict(), "entry_hash": compute_entry_hash(forged.body())}
    )
    store.append(forged)
    with pytest.raises(LedgerIntegrityError, match="no coinciden"):
        TemporalLedger(WORKSPACE, store)


# ==========================================================================
# 4. La mutacion in-place no existe: el ledger no la ofrece ni la sufre
# ==========================================================================
def test_the_ledger_exposes_no_update_or_delete():
    prohibidos = {"update", "delete", "remove", "set_status", "edit", "truncate", "clear"}
    assert prohibidos & set(dir(TemporalLedger)) == set()
    assert prohibidos & set(dir(InMemoryLedgerStore)) == set()
    assert prohibidos & set(dir(JsonlLedgerStore)) == set()


def test_the_jsonl_store_only_ever_opens_the_file_for_appending():
    import inspect

    src = inspect.getsource(JsonlLedgerStore)
    assert 'open("a"' in src
    for modo in ('open("w"', "open('w'", 'open("r+"', 'open("w+"'):
        assert modo not in src


def test_mutating_the_document_after_asserting_does_not_reach_the_ledger():
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    doc = make_assertion()
    led.assert_fact(doc)
    doc["confidence"] = 0.01
    doc["status"] = "RETRACTED"
    assert led.current("assertion:0001")["confidence"] == 0.72
    assert led.current("assertion:0001")["status"] == "ASSERTED"
    assert led.verify_chain() is True


def test_mutating_a_history_document_does_not_reach_the_ledger():
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    led.assert_fact(make_assertion())
    led.confirm(
        "assertion:0001", recorded_at="2026-02-01T09:00:00Z",
        evidence_fragment_ids=["fragment:p20:1"],
    )
    led.history("assertion:0001")[0].document["status"] = "RETRACTED"
    assert led.history("assertion:0001")[0].document["status"] == "ASSERTED"


def test_a_confirmation_does_not_rewrite_the_previous_evidence_list():
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    led.assert_fact(make_assertion())
    led.confirm(
        "assertion:0001", recorded_at="2026-02-01T09:00:00Z",
        evidence_fragment_ids=["fragment:p20:1"],
    )
    assert led.history("assertion:0001")[0].document["evidence_fragment_ids"] == [
        "fragment:p12:0"
    ]


# ==========================================================================
# 5. La matriz no se puede aflojar por la puerta de atras
# ==========================================================================
@pytest.mark.parametrize("estado", [AssertionStatus.SUPERSEDED, AssertionStatus.RETRACTED])
@pytest.mark.parametrize("destino", list(AssertionStatus))
def test_terminal_statuses_admit_nothing(estado, destino):
    with pytest.raises(LedgerTransitionError):
        check_transition(estado, destino)


def test_no_operation_can_resurrect_a_retracted_assertion():
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    led.assert_fact(make_assertion())
    led.retract(
        "assertion:0001", recorded_at="2026-02-01T09:00:00Z",
        reason_code="EXTRACTION_ERROR",
    )
    with pytest.raises(LedgerTransitionError):
        led.confirm(
            "assertion:0001", recorded_at="2026-03-01T09:00:00Z",
            evidence_fragment_ids=["fragment:nuevo"],
        )
    with pytest.raises(LedgerTransitionError):
        led.supersede("assertion:0001", _successor())
    with pytest.raises(LedgerTransitionError):
        led.retract(
            "assertion:0001", recorded_at="2026-03-01T09:00:00Z",
            reason_code="EXTRACTION_ERROR",
        )
    assert len(led) == 2  # ninguna de las tres dejo rastro


def test_a_failed_supersession_leaves_nothing_behind():
    """Si la vigencia no se puede cerrar, no queda una version nueva huerfana."""
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    led.assert_fact(make_assertion())
    with pytest.raises(LedgerError):
        led.supersede("assertion:0001", _successor(valid_from=None, event_time=None))
    assert len(led) == 1
    assert led.current("assertion:0002") is None
    assert led.verify_chain() is True


def test_an_invalid_document_never_reaches_the_store():
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    malo = make_assertion(subject="entity:daiki", obj="entity:daiki")
    with pytest.raises(V3ContractError):
        led.assert_fact(malo)
    assert len(led) == 0


# ==========================================================================
# 6. H1 — la entrada DEVUELTA no es la entrada del ledger
# ==========================================================================
def test_mutating_the_returned_entry_does_not_change_the_ledger():
    """H1(a): el objeto devuelto por una operacion es una COPIA.

    Si el ledger devolviera el mismo `LedgerEntry` que guarda en su cache,
    `frozen=True` no protegeria nada: el dict `assertion` es mutable y quien lo
    tocase reescribiria el estado materializado — `current`, `view`, `live`,
    `history`, `snapshot`, `project` — sin alterar ningun hash, porque el hash
    ya estaba calculado.
    """
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    entrada = led.assert_fact(make_assertion())
    ancla = led.snapshot().snapshot_id

    entrada.assertion["status"] = "RETRACTED"
    entrada.assertion["confidence"] = 0.01
    entrada.assertion["subject_entity_id"] = "entity:impostor"

    assert led.current("assertion:0001")["status"] == "ASSERTED"
    assert led.current("assertion:0001")["confidence"] == 0.72
    assert led.view().document("assertion:0001")["subject_entity_id"] == "entity:daiki"
    assert [r.assertion_id for r in led.live()] == ["assertion:0001"]
    assert led.history("assertion:0001")[0].document["status"] == "ASSERTED"
    assert led.snapshot().snapshot_id == ancla
    assert led.verify_chain() is True


def test_the_retract_mutate_confirm_attack_is_impossible():
    """H1(b): el ataque exacto que demostro el revisor.

    Retractar, mutar en memoria el `status` de la entrada devuelta y confirmar:
    si la mutacion llegase al ledger, la comprobacion de transicion leeria
    ASSERTED donde hay RETRACTED y PERSISTIRIA un RETRACTED -> CONFIRMED que
    `verify_chain` aceptaria para siempre.
    """
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    led.assert_fact(make_assertion())
    entrada = led.retract(
        "assertion:0001", recorded_at="2026-02-01T09:00:00Z",
        reason_code="EXTRACTION_ERROR",
    )
    entrada.assertion["status"] = "ASSERTED"  # el ataque

    with pytest.raises(LedgerTransitionError):
        led.confirm(
            "assertion:0001", recorded_at="2026-03-01T09:00:00Z",
            evidence_fragment_ids=["fragment:falso"],
        )
    assert led.current("assertion:0001")["status"] == "RETRACTED"
    assert len(led) == 2
    assert led.verify_chain() is True


def test_mutating_a_view_record_does_not_corrupt_the_view():
    """H5: `AssertionVersion.document` devuelve copia; la vista no se corrompe."""
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    led.assert_fact(make_assertion())
    vista = led.view()
    registro = vista.records()[0]
    registro.document["status"] = "RETRACTED"
    assert registro.document["status"] == "ASSERTED"
    assert vista.document("assertion:0001")["status"] == "ASSERTED"
    assert registro.status == "ASSERTED"


def test_mutating_the_entries_of_a_view_does_not_reach_the_ledger():
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    led.assert_fact(make_assertion())
    vista = led.view()
    vista.entries[0].assertion["confidence"] = 0.01
    assert led.current("assertion:0001")["confidence"] == 0.72
    assert vista.document("assertion:0001")["confidence"] == 0.72


# ==========================================================================
# 7. H2 — verify_chain tambien comprueba la matriz de transiciones
# ==========================================================================
def _chain(store, docs: list[tuple[dict, int]]) -> None:
    """Encadena a mano documentos ya sellados, saltandose toda la API."""
    prev = GENESIS_HASH
    for seq, (doc, revision) in enumerate(docs):
        entry = make_entry(
            seq=seq,
            operation=LedgerOperation.ASSERT,
            recorded_at=doc["recorded_at"],
            workspace=WORKSPACE,
            assertion=doc,
            revision=revision,
            reason_code="INITIAL_ASSERTION",
            prev_hash=prev,
        )
        store.append(entry)
        prev = entry.entry_hash


def test_a_forged_ledger_with_an_illegal_transition_does_not_verify():
    """Hashes perfectos, ciclo de vida imposible: RETRACTED -> ASSERTED."""
    store = InMemoryLedgerStore()
    _chain(
        store,
        [
            (make_assertion(recorded_at="2026-01-10T09:00:00Z"), 1),
            (make_assertion(recorded_at="2026-02-10T09:00:00Z", status="RETRACTED"), 2),
            (make_assertion(recorded_at="2026-03-10T09:00:00Z", status="ASSERTED"), 3),
        ],
    )
    with pytest.raises(LedgerIntegrityError, match="historia imposible"):
        TemporalLedger(WORKSPACE, store)


def test_a_forged_ledger_whose_assertion_is_born_confirmed_does_not_verify():
    store = InMemoryLedgerStore()
    _chain(store, [(make_assertion(status="CONFIRMED"), 1)])
    with pytest.raises(LedgerIntegrityError, match="historia imposible"):
        TemporalLedger(WORKSPACE, store)


def test_a_forged_ledger_that_resurrects_a_superseded_version_does_not_verify():
    store = InMemoryLedgerStore()
    _chain(
        store,
        [
            (make_assertion(recorded_at="2026-01-10T09:00:00Z"), 1),
            (
                make_assertion(
                    recorded_at="2026-02-10T09:00:00Z", status="SUPERSEDED",
                    state="ENDED", valid_to="1050-01-01T00:00:00Z",
                ),
                2,
            ),
            (make_assertion(recorded_at="2026-03-10T09:00:00Z", status="CONFIRMED"), 3),
        ],
    )
    with pytest.raises(LedgerIntegrityError, match="historia imposible"):
        TemporalLedger(WORKSPACE, store)


def test_a_legitimate_ledger_passes_the_transition_check_on_every_operation():
    """La comprobacion nueva no puede poner en rojo una historia legitima."""
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    led.assert_fact(make_assertion())
    led.confirm(
        "assertion:0001", recorded_at="2026-02-01T09:00:00Z",
        evidence_fragment_ids=["fragment:p20:1"],
    )
    led.supersede("assertion:0001", _successor())
    led.retract(
        "assertion:0002", recorded_at="2026-04-01T09:00:00Z",
        reason_code="OPERATOR_RETRACTION",
    )
    assert led.verify_chain(validate_documents=True) is True


# ==========================================================================
# 8. H3 — fracciones de segundo de longitudes DISTINTAS
# ==========================================================================
def test_fractions_of_different_lengths_keep_their_true_order():
    """`.5` es medio segundo; `.250` es un cuarto. Medio va DESPUES.

    Sin normalizar la fraccion a microsegundos, la comparacion seria `5 < 250`
    y el orden quedaria invertido: exactamente el mutante que sobrevivia.
    """
    from knowledge_v3.ledger import time_key

    cuarto = time_key("2026-01-01T00:00:00.250Z")
    medio = time_key("2026-01-01T00:00:00.5Z")
    assert cuarto < medio
    # Y una fraccion mas larga con el mismo valor es el MISMO instante.
    assert time_key("2026-01-01T00:00:00.5Z") == time_key("2026-01-01T00:00:00.500000Z")
    assert time_key("2026-01-01T00:00:00Z") == time_key("2026-01-01T00:00:00.0Z")


def test_a_ledger_ordered_by_fractions_of_different_lengths():
    led = TemporalLedger(WORKSPACE, InMemoryLedgerStore())
    led.assert_fact(make_assertion(recorded_at="2026-01-10T09:00:00.250Z"))
    led.confirm(
        "assertion:0001",
        recorded_at="2026-01-10T09:00:00.5Z",
        evidence_fragment_ids=["fragment:p20:1"],
    )
    assert led.verify_chain() is True
    assert led.view("2026-01-10T09:00:00.300Z").document("assertion:0001")["status"] == "ASSERTED"
    assert led.view("2026-01-10T09:00:00.900Z").document("assertion:0001")["status"] == "CONFIRMED"


# ==========================================================================
# 9. H4 — la guarda de numeracion, probada por si sola
# ==========================================================================
def _entry_with_seq(seq: int) -> LedgerEntry:
    doc = make_assertion()
    return make_entry(
        seq=seq, operation=LedgerOperation.ASSERT, recorded_at=doc["recorded_at"],
        workspace=WORKSPACE, assertion=doc, revision=1,
        reason_code="INITIAL_ASSERTION", prev_hash=GENESIS_HASH,
    )


@pytest.mark.parametrize("seq", [1, 2, 7, 99])
def test_the_store_rejects_a_seq_that_jumps_forward(seq):
    """Un `seq` DEMASIADO ALTO deja huecos: la cadena dejaria de serlo.

    Se prueba hacia arriba a proposito: una guarda escrita como `<` en vez de
    `!=` seguiria rechazando los `seq` bajos y dejaria pasar estos.
    """
    store = InMemoryLedgerStore()
    with pytest.raises(ValueError, match="fuera de orden"):
        store.append(_entry_with_seq(seq))
    assert len(store) == 0


@pytest.mark.parametrize("seq", [0, 1, 3, 50])
def test_the_store_rejects_a_seq_that_repeats_or_skips_on_a_non_empty_log(seq):
    store = InMemoryLedgerStore()
    store.append(_entry_with_seq(0))
    store.append(
        make_entry(
            seq=1, operation=LedgerOperation.ASSERT, recorded_at="2026-02-10T09:00:00Z",
            workspace=WORKSPACE, assertion=make_assertion(
                "assertion:0002", subject="entity:ren", recorded_at="2026-02-10T09:00:00Z"
            ),
            revision=1, reason_code="INITIAL_ASSERTION",
            prev_hash=store.last().entry_hash,
        )
    )
    with pytest.raises(ValueError, match="espera 2"):
        store.append(_entry_with_seq(seq))
    assert len(store) == 2


def test_the_store_accepts_exactly_the_expected_seq():
    store = InMemoryLedgerStore()
    store.append(_entry_with_seq(0))
    assert len(store) == 1
