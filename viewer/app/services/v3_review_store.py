"""Multiprocess-safe SQLite authority for the V3 human-review workflow."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
  workspace TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  active_hash TEXT NOT NULL,
  PRIMARY KEY (workspace, proposal_id)
);
CREATE TABLE IF NOT EXISTS proposal_versions (
  workspace TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  proposal_hash TEXT NOT NULL,
  document_json TEXT NOT NULL,
  package_origins_json TEXT NOT NULL,
  PRIMARY KEY (workspace, proposal_id, proposal_hash)
);
CREATE TABLE IF NOT EXISTS human_decisions (
  decision_id TEXT PRIMARY KEY,
  workspace TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  record_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (workspace, request_id)
);
CREATE TABLE IF NOT EXISTS decision_audit (
  audit_seq INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_json TEXT NOT NULL,
  previous_hash TEXT,
  record_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS glossary_outbox (
  event_id TEXT PRIMARY KEY,
  workspace TEXT NOT NULL,
  decision_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  processed_at TEXT,
  last_error TEXT,
  UNIQUE (workspace, decision_id)
);
CREATE TABLE IF NOT EXISTS glossary_candidates (
  workspace TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  candidate_json TEXT NOT NULL,
  candidate_hash TEXT NOT NULL,
  PRIMARY KEY (workspace, candidate_id)
);
CREATE INDEX IF NOT EXISTS idx_review_active
  ON human_decisions(workspace, proposal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_glossary_pending
  ON glossary_outbox(workspace, processed_at);
"""


class SQLiteReviewStore:
    """Short SQLite transactions with WAL and database-enforced uniqueness."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(60):
            try:
                with self.connect() as connection:
                    connection.execute("PRAGMA journal_mode=WAL")
                    connection.executescript(SCHEMA)
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 59:
                    raise
                time.sleep(0.05)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def import_proposals(self, proposals: list[dict[str, Any]]) -> None:
        with self.transaction() as connection:
            for proposal in proposals:
                workspace = str(proposal["workspace"])
                proposal_id = str(proposal["proposal_id"])
                proposal_hash = str(proposal["proposal_hash"])
                origins = proposal.get("package_origins") or []
                connection.execute(
                    """INSERT INTO proposal_versions
                       (workspace, proposal_id, proposal_hash, document_json, package_origins_json)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(workspace, proposal_id, proposal_hash) DO UPDATE SET
                         package_origins_json=excluded.package_origins_json""",
                    (workspace, proposal_id, proposal_hash, canonical(proposal), canonical(origins)),
                )
                connection.execute(
                    """INSERT INTO proposals(workspace, proposal_id, active_hash)
                       VALUES (?, ?, ?)
                       ON CONFLICT(workspace, proposal_id) DO UPDATE SET
                         active_hash=excluded.active_hash""",
                    (workspace, proposal_id, proposal_hash),
                )

    def decisions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM human_decisions ORDER BY created_at, decision_id"
            ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def append_decision_and_outbox(
        self,
        record: dict[str, Any],
        outbox_payload: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically append a human decision and its candidate request."""
        with self.transaction() as connection:
            existing = connection.execute(
                """SELECT record_json FROM human_decisions
                   WHERE workspace=? AND request_id=?""",
                (record["workspace"], record["request_id"]),
            ).fetchone()
            if existing:
                return json.loads(existing["record_json"]), False
            connection.execute(
                """INSERT INTO human_decisions
                   (decision_id, workspace, proposal_id, request_id, record_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    record["decision_id"],
                    record["workspace"],
                    record["proposal_id"],
                    record["request_id"],
                    canonical(record),
                    record["timestamp"],
                ),
            )
            previous = connection.execute(
                """SELECT record_hash FROM decision_audit
                   WHERE workspace=? ORDER BY audit_seq DESC LIMIT 1""",
                (record["workspace"],),
            ).fetchone()
            audit = {
                "event": "HUMAN_DECISION_RECORDED",
                "decision_id": record["decision_id"],
                "request_id": record["request_id"],
                "proposal_id": record["proposal_id"],
            }
            previous_hash = previous["record_hash"] if previous else None
            record_hash = digest({"previous_hash": previous_hash, **audit})
            connection.execute(
                """INSERT INTO decision_audit
                   (workspace, event_type, event_json, previous_hash, record_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    record["workspace"],
                    audit["event"],
                    canonical(audit),
                    previous_hash,
                    record_hash,
                ),
            )
            if outbox_payload:
                connection.execute(
                    """INSERT INTO glossary_outbox
                       (event_id, workspace, decision_id, payload_json)
                       VALUES (?, ?, ?, ?)""",
                    (
                        f"glossary-request:{record['decision_id']}",
                        record["workspace"],
                        record["decision_id"],
                        canonical(outbox_payload),
                    ),
                )
        return record, True

    def audit_stale(self, event: dict[str, Any]) -> None:
        with self.transaction() as connection:
            previous = connection.execute(
                """SELECT record_hash FROM decision_audit
                   WHERE workspace=? ORDER BY audit_seq DESC LIMIT 1""",
                (event["workspace"],),
            ).fetchone()
            previous_hash = previous["record_hash"] if previous else None
            record_hash = digest({"previous_hash": previous_hash, **event})
            connection.execute(
                """INSERT INTO decision_audit
                   (workspace, event_type, event_json, previous_hash, record_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    event["workspace"],
                    event["event"],
                    canonical(event),
                    previous_hash,
                    record_hash,
                ),
            )

    def project_outbox(self, workspace: str, now: str) -> int:
        """Idempotently materialise candidates and mark events in one commit."""
        projected = 0
        with self.transaction() as connection:
            rows = connection.execute(
                """SELECT event_id, payload_json FROM glossary_outbox
                   WHERE workspace=? AND processed_at IS NULL ORDER BY event_id""",
                (workspace,),
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                for candidate in payload.get("candidates") or []:
                    candidate_id = candidate["candidate_id"]
                    existing = connection.execute(
                        """SELECT candidate_json FROM glossary_candidates
                           WHERE workspace=? AND candidate_id=?""",
                        (workspace, candidate_id),
                    ).fetchone()
                    item = json.loads(existing["candidate_json"]) if existing else candidate
                    if existing:
                        item["source_ids"] = sorted(
                            set(item["source_ids"]) | set(candidate["source_ids"])
                        )
                        item["episode_ids"] = sorted(
                            set(item["episode_ids"]) | set(candidate["episode_ids"])
                        )
                        item["evidence"] = sorted(
                            {
                                canonical(value): value
                                for value in item["evidence"] + candidate["evidence"]
                            }.values(),
                            key=canonical,
                        )
                        item["origin"]["human_decision_ids"] = sorted(
                            set(item["origin"]["human_decision_ids"])
                            | set(candidate["origin"]["human_decision_ids"])
                        )
                        item["origin"]["proposal_ids"] = sorted(
                            set(item["origin"]["proposal_ids"])
                            | set(candidate["origin"]["proposal_ids"])
                        )
                    item["occurrence_count"] = len(item["origin"]["human_decision_ids"])
                    item["source_count"] = len(item["source_ids"])
                    item["candidate_hash"] = digest(
                        {key: value for key, value in item.items() if key != "candidate_hash"}
                    )
                    connection.execute(
                        """INSERT INTO glossary_candidates
                           (workspace, candidate_id, candidate_json, candidate_hash)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(workspace, candidate_id) DO UPDATE SET
                             candidate_json=excluded.candidate_json,
                             candidate_hash=excluded.candidate_hash""",
                        (
                            workspace,
                            candidate_id,
                            canonical(item),
                            item["candidate_hash"],
                        ),
                    )
                connection.execute(
                    "UPDATE glossary_outbox SET processed_at=?, last_error=NULL WHERE event_id=?",
                    (now, row["event_id"]),
                )
                projected += 1
        return projected

    def candidates(self, workspace: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT candidate_json FROM glossary_candidates
                   WHERE workspace=? ORDER BY candidate_id""",
                (workspace,),
            ).fetchall()
        return [json.loads(row["candidate_json"]) for row in rows]
