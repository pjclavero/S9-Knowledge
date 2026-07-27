# -*- coding: utf-8 -*-
"""Ledger temporal de S9-Knowledge V3.

Almacen append-only de `fact-assertion/v3-internal-v1` con historia completa,
bitemporalidad, supersesion, snapshots deterministas y rollback verificable.

    from knowledge_v3.ledger import TemporalLedger, JsonlLedgerStore

    ledger = TemporalLedger("leyenda", JsonlLedgerStore(path))
    ledger.assert_fact(doc)
    ledger.confirm("assertion:0001", recorded_at=..., evidence_fragment_ids=[...])
    snap = ledger.snapshot()                  # ancla para el GraphMutationPlan
    antes = ledger.rollback_to("2026-06-01T00:00:00Z")

Documentacion del modelo: `docs/v3/06-temporal-ledger.md`.
"""
from __future__ import annotations

from .assertions import (  # noqa: F401
    IDENTITY_FIELDS,
    TemporalLedger,
    logical_identity,
)
from .entries import (  # noqa: F401
    GENESIS_HASH,
    LedgerEntry,
    LedgerOperation,
    compute_entry_hash,
    copy_entry,
    entry_id_for,
    make_entry,
)
from .errors import (  # noqa: F401
    LedgerError,
    LedgerIntegrityError,
    LedgerTransitionError,
    LedgerWorkspaceError,
)
from .projection import ProjectedEdge, project  # noqa: F401
from .snapshots import (  # noqa: F401
    SNAPSHOT_ID_PREFIX,
    GraphSnapshot,
    VersionedItem,
    build_snapshot,
)
from .store import InMemoryLedgerStore, JsonlLedgerStore, LedgerStore  # noqa: F401
from .supersession import (  # noqa: F401
    CANONICAL_REASONS,
    CREATION_STATUSES,
    LIVE_STATUSES,
    OPERATION_TARGET_STATUS,
    STATUS_TRANSITIONS,
    TERMINAL_STATUSES,
    check_reason,
    check_transition,
    is_live,
)
from .temporal import AssertionVersion, LedgerView  # noqa: F401
from .timeline import in_validity_interval, is_iso_utc, time_key  # noqa: F401

__all__ = [
    "CANONICAL_REASONS",
    "CREATION_STATUSES",
    "GENESIS_HASH",
    "IDENTITY_FIELDS",
    "LIVE_STATUSES",
    "OPERATION_TARGET_STATUS",
    "SNAPSHOT_ID_PREFIX",
    "STATUS_TRANSITIONS",
    "TERMINAL_STATUSES",
    "AssertionVersion",
    "GraphSnapshot",
    "InMemoryLedgerStore",
    "JsonlLedgerStore",
    "LedgerEntry",
    "LedgerError",
    "LedgerIntegrityError",
    "LedgerOperation",
    "LedgerStore",
    "LedgerTransitionError",
    "LedgerView",
    "LedgerWorkspaceError",
    "ProjectedEdge",
    "TemporalLedger",
    "VersionedItem",
    "build_snapshot",
    "check_reason",
    "check_transition",
    "compute_entry_hash",
    "copy_entry",
    "entry_id_for",
    "in_validity_interval",
    "is_iso_utc",
    "is_live",
    "logical_identity",
    "make_entry",
    "project",
    "time_key",
]
