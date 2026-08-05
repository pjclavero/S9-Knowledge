# -*- coding: utf-8 -*-
"""Admision del plan: fail-closed, con codigo por cada motivo.

La admision responde a una sola pregunta: *¿este documento es un plan que el
motor local sello para ESTE writer, sobre ESTE estado, y todavia vale?*

Se evalua SIEMPRE, tambien en dry-run: simular un plan inadmisible seria darle
una apariencia de legitimidad que no tiene, y el informe de simulacion es
exactamente lo que un operador lee antes de autorizar.

Fail-closed de verdad: se acumulan TODOS los motivos y basta uno para no admitir.
No hay ruta que devuelva «admitido» por omision — `admitted` es
`not rejections`, nunca un valor por defecto.

Ninguna comprobacion de aqui lee los cuatro campos informativos que el contrato
deja fuera del `decision_hash`: la salida es un `SignedView`, que sencillamente
no los contiene (la lista y el motivo, en `view.py`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..contracts import GraphMutationPlan, V3ContractError
from ..contracts.base import compute_idempotency_key
from . import codes
from .errors import Rejection
from .view import SignedView

#: Version mayor de `contract_version` que este writer sabe ejecutar.
SUPPORTED_CONTRACT_MAJOR = 1

#: `\Z` y no `$`: `$` casa tambien antes de un `\n` final.
_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z\Z")


def utc_now() -> datetime:
    """Reloj por defecto. Se inyecta en los tests; nunca se lee de otro sitio."""
    return datetime.now(timezone.utc)


def parse_iso_utc(value: str) -> datetime:
    """Parsea un ISO-8601 UTC terminado en Z. Lanza ValueError si no lo es."""
    if not isinstance(value, str) or not _ISO_UTC.match(value):
        raise ValueError(f"instante no ISO-8601 UTC: {value!r}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class AdmissionContext:
    """Lo que el writer sabe del mundo cuando juzga un plan.

    `current_snapshot_id` es el TESTIGO EXTERNO del requisito R2 del ledger: lo
    declara el operador desde fuera del fichero del ledger, y es lo unico que
    delata un truncado del final o la sustitucion del ultimo eslabon.
    """

    workspace: str
    current_snapshot_id: Optional[str]
    clock: Callable[[], datetime] = utc_now


@dataclass
class AdmissionResult:
    rejections: list[Rejection] = field(default_factory=list)
    view: Optional[SignedView] = None

    @property
    def admitted(self) -> bool:
        return not self.rejections

    @property
    def codes(self) -> list[str]:
        return [r.code for r in self.rejections]


def _reject(out: list[Rejection], code: str, message: str, **detail: Any) -> None:
    out.append(Rejection(code=code, message=message, detail=detail))


def _major(version: str) -> int:
    try:
        return int(str(version).split(".", 1)[0])
    except (TypeError, ValueError):
        return -1


#: Valores admisibles de `scope.layer` (docs/v3/49 §2.2).
_VALID_SCOPE_LAYERS = frozenset({"GAME", "PARTIDA"})


def _scope_incoherence(plan: GraphMutationPlan) -> Optional[tuple[str, dict[str, Any]]]:
    """Coherencia INTERNA del ambito declarado (Invariante 2, M3, estructural).

    Admision «no escribe ni consulta nada»: esto NUNCA lee el grafo ni el
    catalogo del resolutor. Lo que aqui se juzga es si el propio documento
    del plan se contradice a si mismo sobre su ambito -- capa juego vs
    partida, raiz vs bloque `scope`, `game_id` vs `workspace`.

    El otro filo del Invariante 2 -- que el plan cruce con el ESTADO real de
    una entidad/asercion ya escrita en otro ambito -- no es decidible aqui
    por construccion (admision no toca Neo4j): se cierra en el executor, en
    lectura (`EXEC_SCOPE_MISMATCH`, `writer/executor.py`), tal como pide el
    diseno (docs/v3/49 §2.4, segundo punto: "las lecturas ... deben ademas
    comprobar que el nodo leido tiene el `partida_id` que el plan declara").

    Devuelve `None` si el ambito es coherente (incluye el caso legado:
    `partida_id` ausente y `scope` ausente, exactamente como antes de M3).
    """
    scope = plan.scope
    root_partida = plan.partida_id

    if scope is None:
        if root_partida is not None:
            return (
                "partida_id declarado sin bloque scope: el ambito de un plan "
                "de partida debe declararse explicitamente (Invariante 2)",
                {"partida_id": root_partida},
            )
        return None

    if not isinstance(scope, dict):
        return "scope no es un objeto", {"scope": repr(scope)}

    layer = scope.get("layer")
    scope_partida = scope.get("partida_id")
    game_id = scope.get("game_id")

    if layer not in _VALID_SCOPE_LAYERS:
        return "scope.layer no es GAME ni PARTIDA: ambito incoherente", {"layer": layer}

    if layer == "PARTIDA" and not scope_partida:
        return (
            "scope.layer=PARTIDA exige scope.partida_id: ambito incoherente",
            {"layer": layer, "scope_partida_id": scope_partida},
        )

    if layer == "GAME" and scope_partida is not None:
        return (
            "scope.layer=GAME no admite scope.partida_id: partida colandose "
            "en la capa juego (cruce indebido)",
            {"layer": layer, "scope_partida_id": scope_partida},
        )

    if game_id is not None and game_id != plan.workspace:
        return (
            "scope.game_id no coincide con el workspace del plan",
            {"game_id": game_id, "workspace": plan.workspace},
        )

    if (
        root_partida is not None
        and scope_partida is not None
        and root_partida != scope_partida
    ):
        return (
            "partida_id de raiz y scope.partida_id no coinciden: "
            "incoherencia de ambito (partida contra partida)",
            {"root_partida_id": root_partida, "scope_partida_id": scope_partida},
        )

    return None


def admit(plan_doc: dict[str, Any], ctx: AdmissionContext) -> AdmissionResult:
    """Juzga un documento como plan admisible. No escribe ni consulta nada."""
    rejections: list[Rejection] = []

    # 1. Contrato congelado. El validador recalcula plan_hash, decision_hash e
    #    idempotency_key: manipular el plan sin resellarlo muere aqui.
    try:
        plan = GraphMutationPlan.from_dict(plan_doc)
    except V3ContractError as exc:
        _reject(
            rejections,
            codes.PLAN_CONTRACT_INVALID,
            "el documento no valida contra graph-mutation-plan/v3-internal-v1",
            error=str(exc),
        )
        return AdmissionResult(rejections=rejections)
    except Exception as exc:  # pragma: no cover - defensa: nunca admitir por error raro
        _reject(
            rejections,
            codes.PLAN_CONTRACT_INVALID,
            "fallo inesperado validando el plan",
            error=repr(exc),
        )
        return AdmissionResult(rejections=rejections)

    doc = plan.to_dict()

    # 2. Version de contrato soportada.
    if _major(plan.contract_version) != SUPPORTED_CONTRACT_MAJOR:
        _reject(
            rejections,
            codes.PLAN_CONTRACT_VERSION_UNSUPPORTED,
            "version mayor de contrato no soportada por este writer",
            contract_version=plan.contract_version,
            supported_major=SUPPORTED_CONTRACT_MAJOR,
        )

    # 3. Aprobado.
    if not plan.approved:
        _reject(
            rejections,
            codes.PLAN_NOT_APPROVED,
            "local_approval.approved != true",
        )

    # 4. Firmante declarado local. No autentica a nadie (los hashes son sha256
    #    sin clave); descarta un plan que se declare firmado por un externo.
    if not plan.signed_locally():
        _reject(
            rejections,
            codes.PLAN_NOT_SIGNED_LOCALLY,
            "el aprobador declarado no es el motor local",
            provider=plan.local_approval.get("approved_by", {}).get("provider"),
        )

    # 5. Cadena de validadores completa y en PASS.
    chain = plan.local_approval.get("validator_chain") or []
    not_pass = [v.get("validator") for v in chain if v.get("result") != "PASS"]
    if not chain or not_pass:
        _reject(
            rejections,
            codes.PLAN_VALIDATOR_CHAIN_NOT_PASS,
            "cadena de validadores vacia o con resultados distintos de PASS",
            not_pass=not_pass,
        )

    # 6. Firma intacta. Redundante con el validador a proposito: si un dia el
    #    validador afloja, el writer no.
    if not plan.signature_is_intact():
        _reject(
            rejections,
            codes.PLAN_SIGNATURE_MISMATCH,
            "plan_hash o decision_hash no corresponden al contenido del plan",
        )

    # 7. Claves de idempotencia derivadas, no inventadas.
    undermined = [
        o["operation_id"]
        for o in plan.mutation_operations
        if o.get("idempotency_key") != compute_idempotency_key(doc, o)
    ]
    if undermined:
        _reject(
            rejections,
            codes.PLAN_IDEMPOTENCY_KEY_UNDERIVED,
            "hay claves de idempotencia que no derivan de su operacion",
            operations=undermined,
        )

    # 8. Caducidad, con reloj inyectado.
    try:
        expires = parse_iso_utc(plan.expires_at)
    except ValueError as exc:
        _reject(
            rejections,
            codes.PLAN_EXPIRY_UNREADABLE,
            "expires_at ilegible",
            error=str(exc),
        )
    else:
        now = ctx.clock()
        if now.tzinfo is None:  # pragma: no cover - reloj mal inyectado
            now = now.replace(tzinfo=timezone.utc)
        if now >= expires:
            _reject(
                rejections,
                codes.PLAN_EXPIRED,
                "el plan caduco; una firma correcta no lo resucita",
                expires_at=plan.expires_at,
                now=now.isoformat(),
            )

    # 9. Workspace del writer (R3: un unico escritor por workspace).
    if plan.workspace != ctx.workspace:
        _reject(
            rejections,
            codes.PLAN_WORKSPACE_MISMATCH,
            "el plan es de otro workspace: este writer no lo escribe",
            plan_workspace=plan.workspace,
            writer_workspace=ctx.workspace,
        )

    # 9.5. Ambito del plan (Invariante 2, M3: docs/v3/49 §2.2/§2.4). Error
    #      duro, nunca warning: un plan cuyo ambito no se sostiene a si mismo
    #      no se admite.
    scope_issue = _scope_incoherence(plan)
    if scope_issue is not None:
        message, detail = scope_issue
        _reject(rejections, codes.PLAN_SCOPE_CROSS_PARTIDA, message, **detail)

    # 10. Snapshot vigente declarado por el operador (R2: testigo externo).
    if not ctx.current_snapshot_id:
        _reject(
            rejections,
            codes.PLAN_SNAPSHOT_UNDECLARED,
            "el operador no declaro el snapshot vigente; sin testigo externo no se escribe",
        )
    elif plan.snapshot_id != ctx.current_snapshot_id:
        _reject(
            rejections,
            codes.PLAN_SNAPSHOT_STALE,
            "el plan se calculo sobre un snapshot que ya no es el vigente",
            plan_snapshot=plan.snapshot_id,
            current_snapshot=ctx.current_snapshot_id,
        )

    # 11. Un plan aprobado sin operaciones no escribe nada.
    if not plan.mutation_operations:
        _reject(
            rejections,
            codes.PLAN_NO_OPERATIONS,
            "el plan no tiene operaciones",
        )

    if rejections:
        return AdmissionResult(rejections=rejections)
    return AdmissionResult(rejections=[], view=SignedView.of(doc))


__all__ = [
    "AdmissionContext",
    "AdmissionResult",
    "admit",
    "parse_iso_utc",
    "utc_now",
    "SUPPORTED_CONTRACT_MAJOR",
]
