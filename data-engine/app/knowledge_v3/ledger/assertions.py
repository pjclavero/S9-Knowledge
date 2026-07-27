# -*- coding: utf-8 -*-
"""`TemporalLedger`: almacen append-only de `FactAssertion` con historia completa.

Principio unico del subsistema:

    Una afirmacion NUNCA se muta. Todo cambio es una entrada nueva.

De ahi se deriva todo lo demas: la historia es completa porque nada se pierde;
el rollback es posible porque el pasado sigue escrito; y la cadena de custodia
es verificable porque cada entrada sella la anterior.

Cinco operaciones, todas aditivas:

===============  ====================================================
`assert_fact`    registra una afirmacion nueva
`confirm`        evidencia adicional refuerza la misma identidad
`supersede`      una version nueva cierra la vigencia de la anterior
`contradict`     marca DOS afirmaciones en conflicto, sin destruir nada
`retract`        retira una afirmacion, con motivo canonico
===============  ====================================================

Lo que este modulo NO hace, a proposito:

- no escribe en Neo4j (el respaldo es asunto del writer);
- no llama a ningun reloj (todos los instantes entran como dato);
- no llama a ningun proveedor;
- no inventa confianzas: `confirm` exige que la confianza no baje, pero el
  valor lo aporta quien confirma, no el ledger.

El contrato `fact-assertion/v3-internal-v1` esta CONGELADO: cada documento que
sale de aqui se valida contra el, y un fallo del contrato se propaga tal cual.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..contracts import AssertionStatus, FactAssertion, V3ContractError
from .entries import (
    GENESIS_HASH,
    LedgerEntry,
    LedgerOperation,
    copy_entry,
    make_entry,
)
from .errors import (
    LedgerError,
    LedgerIntegrityError,
    LedgerTransitionError,
    LedgerWorkspaceError,
)
from .snapshots import GraphSnapshot, build_snapshot
from .store import InMemoryLedgerStore, LedgerStore
from .supersession import (
    CREATION_STATUSES,
    check_reason,
    check_transition,
    close_validity,
    derive_version,
    is_live,
)
from .temporal import AssertionVersion, LedgerView
from .timeline import before_or_equal, is_iso_utc, time_key

#: Campos que definen la IDENTIDAD LOGICA de un hecho. Dos afirmaciones vivas
#: con la misma identidad son el mismo hecho dicho dos veces: eso es una
#: CONFIRMACION, no un registro nuevo, y el ledger lo exige explicitamente.
#: `valid_from` entra en la identidad porque «Daiki miembro desde 1041» y
#: «Daiki miembro desde 1050» son hechos distintos, no una repeticion.
IDENTITY_FIELDS: Tuple[str, ...] = (
    "workspace",
    "collection_id",
    "subject_entity_id",
    "predicate",
    "object_entity_id",
    "direction",
    "negated",
    "valid_from",
)


def logical_identity(doc: dict) -> Tuple:
    """Identidad logica de una afirmacion (independiente de `assertion_id`)."""
    return tuple(doc.get(f) for f in IDENTITY_FIELDS)


def _as_dict(assertion: "FactAssertion | dict") -> dict:
    if isinstance(assertion, FactAssertion):
        return assertion.to_dict()
    if isinstance(assertion, dict):
        return deepcopy(assertion)
    raise LedgerError(f"se esperaba FactAssertion o dict, no {type(assertion).__name__}")


class TemporalLedger:
    """Ledger temporal de un workspace.

    Un ledger = un workspace. El aislamiento es duro: no hay parametro que
    permita mezclar bovedas, porque un ledger multi-workspace convierte cada
    consulta en una oportunidad de filtracion.
    """

    def __init__(
        self,
        workspace: str,
        store: Optional[LedgerStore] = None,
        *,
        verify_on_load: bool = True,
    ) -> None:
        self.workspace = workspace
        self._store = store if store is not None else InMemoryLedgerStore()
        self._cache: List[LedgerEntry] = self._store.read_all()
        if verify_on_load and self._cache:
            self.verify_chain()

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------
    @property
    def store(self) -> LedgerStore:
        return self._store

    def entries(self) -> Tuple[LedgerEntry, ...]:
        """Todas las entradas, en orden. Copias: no se puede tocar el original."""
        return tuple(self._store.read_all())

    def __len__(self) -> int:
        return len(self._cache)

    def reload(self) -> "TemporalLedger":
        """Relee el almacen (util tras escribir desde otro proceso)."""
        self._cache = self._store.read_all()
        return self

    def _last(self) -> Optional[LedgerEntry]:
        return self._cache[-1] if self._cache else None

    def _revision_of(self, assertion_id: str) -> int:
        rev = 0
        for e in self._cache:
            if e.assertion_id == assertion_id:
                rev = e.revision
        return rev

    def current(self, assertion_id: str) -> Optional[dict]:
        """Ultima revision materializada de una afirmacion (copia)."""
        found: Optional[dict] = None
        for e in self._cache:
            if e.assertion_id == assertion_id:
                found = e.assertion
        return deepcopy(found) if found is not None else None

    def _require_current(self, assertion_id: str) -> dict:
        doc = self.current(assertion_id)
        if doc is None:
            raise LedgerError(f"afirmacion desconocida en el ledger: {assertion_id}")
        return doc

    # ------------------------------------------------------------------
    # Vistas, snapshots y rollback
    # ------------------------------------------------------------------
    def view(self, as_of: Optional[str] = None) -> LedgerView:
        """Vista materializada del ledger hasta el instante de transaccion `as_of`.

        `as_of=None` = estado actual. `as_of=T` = lo que el sistema sabia en T,
        sin contaminacion de nada registrado despues.
        """
        if as_of is None:
            return LedgerView(self._cache, as_of=None)
        if not is_iso_utc(as_of):
            raise LedgerError(f"as_of no es un instante ISO-8601 UTC: {as_of!r}")
        limit = time_key(as_of)
        return LedgerView(
            [e for e in self._cache if time_key(e.recorded_at) <= limit], as_of=as_of
        )

    #: Reconstruir el pasado y consultar el pasado son la MISMA operacion: si
    #: fuesen dos caminos de codigo distintos, uno de los dos acabaria mintiendo.
    rollback_to = view

    def snapshot(self, as_of: Optional[str] = None) -> GraphSnapshot:
        """`GraphSnapshot` determinista: el ancla que citaran los planes."""
        return build_snapshot(self.view(as_of), workspace=self.workspace)

    def valid_at(
        self, world_time: str, *, as_of: Optional[str] = None, **kwargs: Any
    ) -> List[AssertionVersion]:
        """Consulta BITEMPORAL: que era cierto en `world_time` segun lo sabido en `as_of`."""
        return self.view(as_of).valid_at(world_time, **kwargs)

    def live(self, as_of: Optional[str] = None) -> List[AssertionVersion]:
        return self.view(as_of).live()

    def history(self, assertion_id: str) -> List[AssertionVersion]:
        return self.view().history(assertion_id)

    def supersession_chain(self, assertion_id: str) -> List[str]:
        return self.view().supersession_chain(assertion_id)

    # ------------------------------------------------------------------
    # Integridad
    # ------------------------------------------------------------------
    def verify_chain(self, *, validate_documents: bool = False) -> bool:
        """Recalcula la cadena desde el genesis. Lanza `LedgerIntegrityError` si falla.

        Comprueba, en este orden: numeracion sin huecos, enlace `prev_hash`,
        `entry_hash` recalculado, monotonia del tiempo de transaccion, revisiones
        consecutivas por afirmacion, coherencia entrada/documento y la MATRIZ DE
        TRANSICIONES entre revisiones consecutivas de cada afirmacion.

        Editar una entrada antigua rompe su `entry_hash` y, aunque alguien lo
        recalculase, rompe el `prev_hash` de la siguiente. No hay retoque local
        posible: o se reescribe el ledger entero, o la verificacion cae.

        La matriz se comprueba AQUI ademas de al escribir (H2). Escribir por la
        API no es el unico camino: quien reescriba el ledger entero — el modelo
        de amenaza que este diseno admite en su §11 — puede forjar entradas
        coherentes en hashes y absurdas en ciclo de vida, por ejemplo un
        RETRACTED que revive como CONFIRMED. Si la matriz solo viviese en la
        ruta de escritura, la verificacion bendeciria esa historia imposible.
        """
        entries = self._store.read_all()
        prev_hash = GENESIS_HASH
        prev_time: Optional[Tuple] = None
        revisions: Dict[str, int] = {}
        last_status: Dict[str, str] = {}
        for i, e in enumerate(entries):
            if e.seq != i:
                raise LedgerIntegrityError(
                    f"entrada {i}: seq={e.seq}; la cadena tiene huecos o esta desordenada"
                )
            if e.workspace != self.workspace:
                raise LedgerWorkspaceError(
                    f"entrada {e.entry_id}: workspace {e.workspace!r} en un ledger de "
                    f"{self.workspace!r}"
                )
            if e.prev_hash != prev_hash:
                raise LedgerIntegrityError(
                    f"entrada {e.entry_id}: prev_hash {e.prev_hash[:12]}... no enlaza con "
                    f"{prev_hash[:12]}...; la cadena de custodia esta rota"
                )
            recomputed = e.computed_hash()
            if recomputed != e.entry_hash:
                raise LedgerIntegrityError(
                    f"entrada {e.entry_id}: entry_hash no corresponde a su contenido "
                    f"(esperado {recomputed[:12]}..., encontrado {e.entry_hash[:12]}...); "
                    "la entrada fue alterada despues de escribirse"
                )
            k = time_key(e.recorded_at)
            if prev_time is not None and k < prev_time:
                raise LedgerIntegrityError(
                    f"entrada {e.entry_id}: recorded_at {e.recorded_at} retrocede en el "
                    "tiempo de transaccion; un ledger append-only no viaja al pasado"
                )
            expected_rev = revisions.get(e.assertion_id, 0) + 1
            if e.revision != expected_rev:
                raise LedgerIntegrityError(
                    f"entrada {e.entry_id}: revision {e.revision} de {e.assertion_id}, "
                    f"esperada {expected_rev}"
                )
            if e.assertion.get("assertion_id") != e.assertion_id:
                raise LedgerIntegrityError(
                    f"entrada {e.entry_id}: assertion_id de la entrada y del documento "
                    "no coinciden"
                )
            if e.assertion.get("recorded_at") != e.recorded_at:
                raise LedgerIntegrityError(
                    f"entrada {e.entry_id}: recorded_at de la entrada y del documento "
                    "no coinciden; habria dos tiempos de transaccion para un mismo hecho"
                )
            try:
                check_transition(
                    last_status.get(e.assertion_id),
                    e.assertion.get("status"),
                    assertion_id=e.assertion_id,
                )
            except LedgerTransitionError as exc:
                raise LedgerIntegrityError(
                    f"entrada {e.entry_id}: el ledger contiene una historia imposible "
                    f"({exc}); los hashes cuadran, el ciclo de vida no"
                ) from exc
            if validate_documents:
                FactAssertion.from_dict(e.assertion)
            revisions[e.assertion_id] = e.revision
            last_status[e.assertion_id] = str(e.assertion.get("status"))
            prev_hash = e.entry_hash
            prev_time = k
        return True

    # ------------------------------------------------------------------
    # Escritura (todas aditivas)
    # ------------------------------------------------------------------
    def _validated(self, doc: dict) -> dict:
        """Valida contra el contrato congelado. El error del contrato se propaga."""
        FactAssertion.from_dict(doc)  # lanza V3ContractError si no cumple
        return doc

    def _check_workspace(self, doc: dict) -> None:
        if doc.get("workspace") != self.workspace:
            raise LedgerWorkspaceError(
                f"la afirmacion pertenece al workspace {doc.get('workspace')!r} y este "
                f"ledger es de {self.workspace!r}: ningun documento cruza bovedas"
            )

    def _check_monotonic(self, recorded_at: str) -> None:
        if not is_iso_utc(recorded_at):
            raise LedgerError(f"recorded_at invalido: {recorded_at!r}")
        last = self._last()
        if last is not None and time_key(recorded_at) < time_key(last.recorded_at):
            raise LedgerError(
                f"recorded_at {recorded_at} anterior al de la ultima entrada "
                f"({last.recorded_at}): el tiempo de transaccion no retrocede. "
                "Un hecho conocido tarde con validez pasada se expresa con "
                "`valid_from`/`event_time`, nunca retrasando `recorded_at`."
            )

    def _append(
        self,
        *,
        operation: LedgerOperation,
        doc: dict,
        recorded_at: str,
        reason_code: str,
        related: Sequence[str] = (),
    ) -> LedgerEntry:
        self._check_workspace(doc)
        self._validated(doc)
        seq = len(self._cache)
        last = self._last()
        entry = make_entry(
            seq=seq,
            operation=operation,
            recorded_at=recorded_at,
            workspace=self.workspace,
            assertion=doc,
            revision=self._revision_of(doc["assertion_id"]) + 1,
            reason_code=reason_code,
            prev_hash=last.entry_hash if last is not None else GENESIS_HASH,
            related_assertion_ids=tuple(related),
        )
        self._store.append(entry)
        # H1: la cache guarda una COPIA y el llamante recibe OTRA. Si los tres
        # (almacen, cache y retorno) compartieran el mismo dict `assertion`,
        # mutar la entrada devuelta reescribiria el estado materializado del
        # ledger sin tocar ningun hash — el hash ya estaba calculado — y
        # `verify_chain` bendeciria la manipulacion para siempre.
        self._cache.append(copy_entry(entry))
        return copy_entry(entry)

    def _next_seq(self) -> int:
        return len(self._cache)

    # -- ASSERT ------------------------------------------------------------
    def assert_fact(
        self,
        assertion: "FactAssertion | dict",
        *,
        recorded_at: Optional[str] = None,
        reason_code: str = "INITIAL_ASSERTION",
        allow_duplicate_identity: bool = False,
    ) -> LedgerEntry:
        """Registra una afirmacion nueva.

        `recorded_at` se toma del propio documento salvo que se indique otro; el
        del documento y el de la entrada NUNCA divergen.
        """
        check_reason(LedgerOperation.ASSERT, reason_code)
        doc = _as_dict(assertion)
        when = recorded_at or doc.get("recorded_at")
        if not is_iso_utc(when):
            raise LedgerError(f"recorded_at invalido o ausente: {when!r}")
        doc["recorded_at"] = when
        self._check_monotonic(when)

        if self.current(doc.get("assertion_id", "")) is not None:
            raise LedgerError(
                f"{doc['assertion_id']} ya existe en el ledger; para cambiarla usa "
                "confirm/supersede/contradict/retract, no un ASSERT nuevo"
            )
        check_transition(
            None, doc.get("status"), operation=LedgerOperation.ASSERT,
            assertion_id=str(doc.get("assertion_id")),
        )
        if AssertionStatus(doc["status"]) not in CREATION_STATUSES:
            raise LedgerError(
                f"una afirmacion no puede nacer {doc['status']}; solo "
                f"{sorted(s.value for s in CREATION_STATUSES)}"
            )
        if doc.get("superseded_by") is not None:
            raise LedgerError("una afirmacion nueva no puede nacer ya superada")

        if not allow_duplicate_identity:
            identity = logical_identity(doc)
            for rec in self.view().live():
                if logical_identity(rec.stored_document) == identity:
                    raise LedgerError(
                        f"ya existe una afirmacion viva con la misma identidad logica "
                        f"({rec.assertion_id}); repetir un hecho es CONFIRMARLO, no "
                        "registrarlo dos veces (usa `confirm`, o "
                        "`allow_duplicate_identity=True` si de verdad son dos registros)"
                    )
        return self._append(
            operation=LedgerOperation.ASSERT,
            doc=doc,
            recorded_at=when,
            reason_code=reason_code,
        )

    # -- CONFIRM -----------------------------------------------------------
    def confirm(
        self,
        assertion_id: str,
        *,
        recorded_at: str,
        evidence_fragment_ids: Iterable[str],
        episode_ids: Iterable[str] = (),
        confidence: Optional[float] = None,
        reason_code: str = "CORROBORATING_EVIDENCE",
    ) -> LedgerEntry:
        """Refuerza una afirmacion con evidencia adicional (misma identidad).

        Exige evidencia REALMENTE nueva: confirmar con los mismos fragmentos que
        ya sostenian la afirmacion no anade informacion, solo sube el estado. Y
        la confianza no puede bajar en una confirmacion; si baja, lo que hay es
        una contradiccion o una supersesion, no un refuerzo.
        """
        check_reason(LedgerOperation.CONFIRM, reason_code)
        self._check_monotonic(recorded_at)
        previous = self._require_current(assertion_id)
        check_transition(
            previous["status"], AssertionStatus.CONFIRMED,
            operation=LedgerOperation.CONFIRM, assertion_id=assertion_id,
        )
        if previous["state"] == "PLANNED":
            raise LedgerError(
                f"{assertion_id} tiene state=PLANNED: el contrato prohibe CONFIRMED "
                "sobre un hecho planificado (aun no ha ocurrido)"
            )
        new_frag = sorted(set(evidence_fragment_ids) - set(previous["evidence_fragment_ids"]))
        if not new_frag:
            raise LedgerError(
                f"confirmacion de {assertion_id} sin evidencia nueva: los fragmentos "
                "aportados ya sostenian la afirmacion"
            )
        conf = previous["confidence"] if confidence is None else float(confidence)
        if conf < previous["confidence"]:
            raise LedgerError(
                f"una confirmacion no puede bajar la confianza de {assertion_id} "
                f"({previous['confidence']} -> {conf})"
            )
        changes = {
            "status": AssertionStatus.CONFIRMED.value,
            "confidence": conf,
            "evidence_fragment_ids": sorted(
                set(previous["evidence_fragment_ids"]) | set(evidence_fragment_ids)
            ),
            "episode_ids": sorted(set(previous["episode_ids"]) | set(episode_ids)),
        }
        doc = derive_version(
            previous,
            operation=LedgerOperation.CONFIRM,
            seq=self._next_seq(),
            recorded_at=recorded_at,
            changes=changes,
            produced=["status", "confidence", "evidence_fragment_ids"],
            engine_version=previous["engine_version"],
        )
        return self._append(
            operation=LedgerOperation.CONFIRM,
            doc=doc,
            recorded_at=recorded_at,
            reason_code=reason_code,
        )

    # -- SUPERSEDE ---------------------------------------------------------
    def supersede(
        self,
        assertion_id: str,
        new_assertion: "FactAssertion | dict",
        *,
        recorded_at: Optional[str] = None,
        valid_to: Optional[str] = None,
        reason_code: str = "SUPERSEDED_BY_NEWER",
    ) -> Tuple[LedgerEntry, LedgerEntry]:
        """Una version nueva sustituye a la anterior y cierra su vigencia.

        Devuelve `(entrada_de_la_nueva, entrada_de_cierre_de_la_vieja)`. Las DOS
        comparten `recorded_at`: para cualquier consulta as-of la supersesion es
        atomica, y no existe ningun instante en el que se vea la nueva sin la
        vieja cerrada.

        `valid_to` por defecto es el `valid_from` de la nueva version: el hecho
        anterior deja de valer justo cuando empieza el siguiente. Si la nueva no
        tiene `valid_from`, hay que darlo explicitamente — deducirlo seria
        inventar la fecha en la que algo dejo de ser cierto.
        """
        check_reason(LedgerOperation.SUPERSEDE, reason_code)
        previous = self._require_current(assertion_id)
        new_doc = _as_dict(new_assertion)
        when = recorded_at or new_doc.get("recorded_at")
        if not is_iso_utc(when):
            raise LedgerError(f"recorded_at invalido o ausente: {when!r}")
        self._check_monotonic(when)

        if new_doc.get("assertion_id") == assertion_id:
            raise LedgerError(
                "la version nueva no puede reutilizar el `assertion_id` de la anterior: "
                "la supersesion enlaza DOS registros, no reescribe uno"
            )
        if self.current(new_doc.get("assertion_id", "")) is not None:
            raise LedgerError(
                f"{new_doc['assertion_id']} ya existe en el ledger; una supersesion crea "
                "un registro nuevo"
            )
        check_transition(
            previous["status"], AssertionStatus.SUPERSEDED,
            operation=LedgerOperation.SUPERSEDE, assertion_id=assertion_id,
        )
        check_transition(
            None, new_doc.get("status"), operation=LedgerOperation.SUPERSEDE,
            assertion_id=str(new_doc.get("assertion_id")),
        )

        closing_at = valid_to if valid_to is not None else new_doc.get("valid_from")
        new_doc["recorded_at"] = when
        new_doc["supersedes"] = assertion_id
        new_doc["superseded_by"] = None
        self._check_workspace(new_doc)

        if not before_or_equal(previous.get("valid_from"), new_doc.get("valid_from")):
            raise LedgerError(
                f"la version nueva empieza ({new_doc.get('valid_from')}) antes que la "
                f"anterior ({previous.get('valid_from')}): eso no es una supersesion"
            )
        # Cierre calculado ANTES de escribir nada: si la vigencia no se puede
        # cerrar, no debe quedar en el ledger una version nueva huerfana.
        closing_changes = close_validity(
            previous, successor_id=new_doc["assertion_id"], valid_to=closing_at
        )

        entry_new = self._append(
            operation=LedgerOperation.SUPERSEDE,
            doc=new_doc,
            recorded_at=when,
            reason_code=reason_code,
            related=(assertion_id,),
        )
        closing_doc = derive_version(
            previous,
            operation=LedgerOperation.SUPERSEDE,
            seq=self._next_seq(),
            recorded_at=when,
            changes=closing_changes,
            produced=["status", "superseded_by", "valid_to", "state"],
            engine_version=previous["engine_version"],
        )
        entry_old = self._append(
            operation=LedgerOperation.SUPERSEDE,
            doc=closing_doc,
            recorded_at=when,
            reason_code=reason_code,
            related=(new_doc["assertion_id"],),
        )
        return entry_new, entry_old

    # -- CONTRADICT --------------------------------------------------------
    def contradict(
        self,
        assertion_id: str,
        other_assertion_id: str,
        *,
        recorded_at: str,
        reason_code: str = "CONTRADICTORY_EVIDENCE",
    ) -> Tuple[LedgerEntry, LedgerEntry]:
        """Marca DOS afirmaciones en conflicto. No destruye ninguna.

        Ambas quedan `status=CONTRADICTED` y `epistemic_status=CONFLICTED`, y
        ambas siguen VIVAS y consultables: el sistema no elige ganador por su
        cuenta. Resolver el conflicto es una decision posterior (confirmar una,
        superarla, retractar la otra), y cada una de esas rutas deja su propia
        entrada en el ledger.
        """
        check_reason(LedgerOperation.CONTRADICT, reason_code)
        self._check_monotonic(recorded_at)
        if assertion_id == other_assertion_id:
            raise LedgerError("una afirmacion no puede contradecirse a si misma")
        first = self._require_current(assertion_id)
        second = self._require_current(other_assertion_id)
        for doc in (first, second):
            check_transition(
                doc["status"], AssertionStatus.CONTRADICTED,
                operation=LedgerOperation.CONTRADICT, assertion_id=doc["assertion_id"],
            )
        entries = []
        for doc, other in ((first, other_assertion_id), (second, assertion_id)):
            version = derive_version(
                doc,
                operation=LedgerOperation.CONTRADICT,
                seq=self._next_seq(),
                recorded_at=recorded_at,
                changes={
                    "status": AssertionStatus.CONTRADICTED.value,
                    "epistemic_status": "CONFLICTED",
                },
                produced=["status", "epistemic_status"],
                engine_version=doc["engine_version"],
            )
            entries.append(
                self._append(
                    operation=LedgerOperation.CONTRADICT,
                    doc=version,
                    recorded_at=recorded_at,
                    reason_code=reason_code,
                    related=(other,),
                )
            )
        return entries[0], entries[1]

    # -- RETRACT -----------------------------------------------------------
    def retract(
        self,
        assertion_id: str,
        *,
        recorded_at: str,
        reason_code: str,
    ) -> LedgerEntry:
        """Retira una afirmacion. El motivo es OBLIGATORIO y canonico.

        Retractar no borra: la afirmacion y todas sus revisiones siguen en el
        ledger. Lo que cambia es que deja de contar como conocimiento vigente.
        """
        check_reason(LedgerOperation.RETRACT, reason_code)
        self._check_monotonic(recorded_at)
        previous = self._require_current(assertion_id)
        check_transition(
            previous["status"], AssertionStatus.RETRACTED,
            operation=LedgerOperation.RETRACT, assertion_id=assertion_id,
        )
        doc = derive_version(
            previous,
            operation=LedgerOperation.RETRACT,
            seq=self._next_seq(),
            recorded_at=recorded_at,
            changes={"status": AssertionStatus.RETRACTED.value},
            produced=["status"],
            engine_version=previous["engine_version"],
        )
        return self._append(
            operation=LedgerOperation.RETRACT,
            doc=doc,
            recorded_at=recorded_at,
            reason_code=reason_code,
        )


__all__ = [
    "IDENTITY_FIELDS",
    "TemporalLedger",
    "V3ContractError",
    "is_live",
    "logical_identity",
]
