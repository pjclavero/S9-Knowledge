# -*- coding: utf-8 -*-
"""Codigos de rechazo del writer. Un rechazo sin codigo no existe.

Tres familias, por el orden en que se evaluan:

  ``PLAN_*``  admision — propiedades del documento; se evaluan SIEMPRE, tambien
              en dry-run, porque un plan inadmisible no debe ni simularse.
  ``GATE_*``  gate de operador — las nueve condiciones que exige una escritura
              real. Solo bloquean cuando se pide APPLY: el dry-run es seguro por
              construccion y no necesita permiso.
  ``EXEC_*``  ejecucion — lo que solo se sabe leyendo el grafo (concurrencia
              optimista, payload inejecutable, fallo del driver).

Los codigos son ESTABLES: entran en el registro de auditoria y en la tabla de
`docs/v3/09-writer.md`. Renombrar uno rompe el historico.
"""
from __future__ import annotations

# --- Admision -------------------------------------------------------------
#: El documento no valida contra el contrato congelado (incluye plan_hash,
#: decision_hash e idempotency_key recalculados por el validador).
PLAN_CONTRACT_INVALID = "PLAN_CONTRACT_INVALID"
#: `contract_version` mayor no soportada por este writer.
PLAN_CONTRACT_VERSION_UNSUPPORTED = "PLAN_CONTRACT_VERSION_UNSUPPORTED"
#: `local_approval.approved` no es true.
PLAN_NOT_APPROVED = "PLAN_NOT_APPROVED"
#: El firmante declarado no es el motor local.
PLAN_NOT_SIGNED_LOCALLY = "PLAN_NOT_SIGNED_LOCALLY"
#: La cadena de validadores esta vacia o tiene alguna entrada que no es PASS.
PLAN_VALIDATOR_CHAIN_NOT_PASS = "PLAN_VALIDATOR_CHAIN_NOT_PASS"
#: `plan_hash` o `decision_hash` no corresponden al contenido (plan manipulado).
PLAN_SIGNATURE_MISMATCH = "PLAN_SIGNATURE_MISMATCH"
#: Alguna `idempotency_key` no deriva de la operacion.
PLAN_IDEMPOTENCY_KEY_UNDERIVED = "PLAN_IDEMPOTENCY_KEY_UNDERIVED"
#: `expires_at` ya paso segun el reloj inyectado.
PLAN_EXPIRED = "PLAN_EXPIRED"
#: `expires_at` no es una fecha ISO-8601 UTC legible.
PLAN_EXPIRY_UNREADABLE = "PLAN_EXPIRY_UNREADABLE"
#: El workspace del plan no es el del writer (R3: un writer por workspace).
PLAN_WORKSPACE_MISMATCH = "PLAN_WORKSPACE_MISMATCH"
#: El `snapshot_id` del plan no es el snapshot vigente declarado (R2).
PLAN_SNAPSHOT_STALE = "PLAN_SNAPSHOT_STALE"
#: El operador no declaro ningun snapshot vigente contra el que contrastar.
PLAN_SNAPSHOT_UNDECLARED = "PLAN_SNAPSHOT_UNDECLARED"
#: Plan aprobado sin operaciones: no hay nada que escribir.
PLAN_NO_OPERATIONS = "PLAN_NO_OPERATIONS"
#: M3 (docs/v3/49 §2.4, Invariante 2): el ambito declarado por el plan
#: (`partida_id` raiz + bloque `scope`) es internamente incoherente, o cruza
#: capa juego/partida de forma indebida. Error duro, nunca warning: un plan
#: cuyo ambito no se sostiene a si mismo no se admite, ni siquiera a dry-run.
PLAN_SCOPE_CROSS_PARTIDA = "PLAN_SCOPE_CROSS_PARTIDA"

#: Orden de evaluacion de la admision (documentado y probado).
ADMISSION_CODES = (
    PLAN_CONTRACT_INVALID,
    PLAN_CONTRACT_VERSION_UNSUPPORTED,
    PLAN_NOT_APPROVED,
    PLAN_NOT_SIGNED_LOCALLY,
    PLAN_VALIDATOR_CHAIN_NOT_PASS,
    PLAN_SIGNATURE_MISMATCH,
    PLAN_IDEMPOTENCY_KEY_UNDERIVED,
    PLAN_EXPIRY_UNREADABLE,
    PLAN_EXPIRED,
    PLAN_WORKSPACE_MISMATCH,
    PLAN_SCOPE_CROSS_PARTIDA,
    PLAN_SNAPSHOT_UNDECLARED,
    PLAN_SNAPSHOT_STALE,
    PLAN_NO_OPERATIONS,
)

# --- Gate de operador (9 condiciones) -------------------------------------
#: `S9K_ALLOW_REAL_INGEST` no vale exactamente "1".
GATE_ENV_NOT_ALLOWED = "GATE_ENV_NOT_ALLOWED"
#: No se pidio APPLY explicitamente. El modo por defecto es dry-run.
GATE_APPLY_NOT_REQUESTED = "GATE_APPLY_NOT_REQUESTED"
#: Falta `operator_id`.
GATE_OPERATOR_MISSING = "GATE_OPERATOR_MISSING"
#: `operator_id` presente pero con forma no admisible.
GATE_OPERATOR_INVALID = "GATE_OPERATOR_INVALID"
#: El operador no confirmo el `plan_hash`, o el que confirmo no coincide.
GATE_PLAN_HASH_NOT_CONFIRMED = "GATE_PLAN_HASH_NOT_CONFIRMED"
#: El plan trae mas operaciones que el limite configurado.
GATE_OPERATION_LIMIT_EXCEEDED = "GATE_OPERATION_LIMIT_EXCEEDED"
#: `S9K_WRITER_WORKSPACE` ausente: el workspace no se declaro dos veces.
GATE_WORKSPACE_NOT_DECLARED = "GATE_WORKSPACE_NOT_DECLARED"
#: El workspace del entorno y el del argumento no coinciden.
GATE_WORKSPACE_DECLARATION_MISMATCH = "GATE_WORKSPACE_DECLARATION_MISMATCH"
#: No hay registro de auditoria utilizable: sin rastro no se escribe.
GATE_AUDIT_UNAVAILABLE = "GATE_AUDIT_UNAVAILABLE"

#: Las nueve condiciones del gate, en orden de evaluacion.
GATE_CODES = (
    GATE_ENV_NOT_ALLOWED,
    GATE_APPLY_NOT_REQUESTED,
    GATE_OPERATOR_MISSING,
    GATE_OPERATOR_INVALID,
    GATE_PLAN_HASH_NOT_CONFIRMED,
    GATE_OPERATION_LIMIT_EXCEEDED,
    GATE_WORKSPACE_NOT_DECLARED,
    GATE_WORKSPACE_DECLARATION_MISMATCH,
    GATE_AUDIT_UNAVAILABLE,
)

# --- Ejecucion ------------------------------------------------------------
#: La version leida del destino no es la esperada (concurrencia optimista).
EXEC_VERSION_MISMATCH = "EXEC_VERSION_MISMATCH"
#: El hash de estado leido del destino no es el esperado.
EXEC_HASH_MISMATCH = "EXEC_HASH_MISMATCH"
#: La operacion apunta a algo que no existe en el grafo.
EXEC_TARGET_MISSING = "EXEC_TARGET_MISSING"
#: La operacion crea algo que ya existe con esa identidad (CREATE-only estricto).
EXEC_TARGET_ALREADY_EXISTS = "EXEC_TARGET_ALREADY_EXISTS"
#: M3 (docs/v3/49 §2.4): el objetivo existe, pero en OTRO ambito de partida
#: que el declarado por el plan. Drift/carrera detectado en lectura, no en
#: admision: aborta el plan entero, nunca una aplicacion parcial.
EXEC_SCOPE_MISMATCH = "EXEC_SCOPE_MISMATCH"
#: Tipo de operacion no soportado por este writer.
EXEC_UNSUPPORTED_OPERATION = "EXEC_UNSUPPORTED_OPERATION"
#: El payload no permite construir una escritura segura (campos, tipos, tokens).
EXEC_UNSUPPORTED_PAYLOAD = "EXEC_UNSUPPORTED_PAYLOAD"
#: Cierre de vigencia sin `reason_code` (R1 del ledger).
EXEC_REASON_CODE_MISSING = "EXEC_REASON_CODE_MISSING"
#: El driver fallo. El plan entero se aborta.
EXEC_DRIVER_FAILURE = "EXEC_DRIVER_FAILURE"
#: La misma clave del workspace pertenece a otro plan u operación.
EXEC_IDEMPOTENCY_CONFLICT = "EXEC_IDEMPOTENCY_CONFLICT"
#: Guardia interna: la consulta generada contenia una construccion destructiva.
EXEC_DESTRUCTIVE_QUERY_BLOCKED = "EXEC_DESTRUCTIVE_QUERY_BLOCKED"

# --- Auditoria ------------------------------------------------------------
#: El sink se declaro disponible pero `append` fallo. No impide que lo ya
#: aplicado este aplicado: avisa de que se aplico SIN dejar esa linea de rastro.
AUDIT_APPEND_FAILED = "AUDIT_APPEND_FAILED"

AUDIT_CODES = (AUDIT_APPEND_FAILED,)

EXECUTION_CODES = (
    EXEC_VERSION_MISMATCH,
    EXEC_HASH_MISMATCH,
    EXEC_TARGET_MISSING,
    EXEC_TARGET_ALREADY_EXISTS,
    EXEC_SCOPE_MISMATCH,
    EXEC_UNSUPPORTED_OPERATION,
    EXEC_UNSUPPORTED_PAYLOAD,
    EXEC_REASON_CODE_MISSING,
    EXEC_DRIVER_FAILURE,
    EXEC_IDEMPOTENCY_CONFLICT,
    EXEC_DESTRUCTIVE_QUERY_BLOCKED,
)

ALL_CODES = ADMISSION_CODES + GATE_CODES + AUDIT_CODES + EXECUTION_CODES

__all__ = [
    "ADMISSION_CODES",
    "GATE_CODES",
    "AUDIT_CODES",
    "EXECUTION_CODES",
    "ALL_CODES",
] + [c for c in ALL_CODES]
