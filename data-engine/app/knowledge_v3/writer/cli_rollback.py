# -*- coding: utf-8 -*-
"""Mando de operador que EJECUTA un documento de rollback.

POR QUE EXISTE
--------------
La libreria sabia revertir (`rollback_provenance.execute_rollback`) y ningun
mando la exponia. Medido por un supervisor independiente usando el producto
como operador: llego hasta el `apply`, la procedencia se creo de verdad, y para
deshacerla tuvo que escribir Python contra la libreria. El unico mando vecino
--`--forget-applied-keys`-- dice literalmente que «no toca el grafo». Es decir:
**el producto aplicaba y no podia revertir por la ruta de operador.**

Esto lo cierra:

    # aplicar (ya existia) -- genera el documento de rollback
    python -m knowledge_v3.writer.cli plan.json ... --apply \\
        --rollback-out rollback.json

    # revertir (esto) -- lo ejecuta de verdad
    S9K_ALLOW_REAL_INGEST=1 S9K_WRITER_WORKSPACE=leyenda \\
    python -m knowledge_v3.writer.cli_rollback rollback.json \\
        --workspace leyenda --operator pjc --execute \\
        --neo4j-uri "$S9K_NEO4J_URI" --neo4j-user neo4j \\
        --neo4j-password-file /etc/s9k/neo4j.pass

LAS MISMAS REGLAS QUE EL APPLY, SIN AFLOJAR NINGUNA
---------------------------------------------------
* **El secreto nunca por `argv`.** Se declara el CAMINO de un fichero 0600
  (o `-` para stdin) y lo lee `driver_neo4j.read_secret`, que comprueba los
  permisos ANTES de leer (y si no sirve, `CLI_SECRET_FILE_UNUSABLE`). No hay
  opcion que acepte la contrasena.
* **Conexion explicita o nada.** Sin URI/usuario/fichero, `--execute` falla
  CERRADO con `CLI_DRIVER_CONFIG_MISSING`; no se degrada a simulacion, que seria
  decirle «ok» a quien pidio borrar.
* **Autorizacion de operador declarada.** Las MISMAS dos declaraciones que el
  APPLY: `S9K_ALLOW_REAL_INGEST=1` y `S9K_WRITER_WORKSPACE` coincidiendo con
  `--workspace`. No es un gate nuevo: son las declaraciones del gate existente,
  exigidas tambien para la operacion inversa (que borra, y por tanto no puede
  pedir menos que la que escribe).
* **Ambito fail-closed.** No se decide aqui: cada instruccion pasa por
  `rollback.scope_clause`, que es la unica definicion del filtro en todo el
  camino de recuperacion. Ambito ausente o malformado -> la instruccion NO se
  ejecuta y sale como no revertida, y el desenlace deja de ser limpio.

EL DESENLACE NO ES UNA FRASE INDEPENDIENTE
------------------------------------------
La linea humana y el codigo de salida se derivan del MISMO objeto
(`RollbackReport`): si quedan residuos, procedencia huerfana o instrucciones no
reconstruibles, no hay forma de imprimir «revertido» ni de salir con 0. La
regla es literal, y los numeros salen de la tabla UNICA del producto
(`writer.exit_codes`, equipo 4C): este mando ya no tiene tabla propia.

    ROLLED_BACK (nada pendiente)  -> rc = 0  (EXIT_OK)
    DRY_RUN valido                -> rc = 0  (EXIT_OK)
    INCOMPLETE (queda algo)       -> rc = 1  (EXIT_OUTCOME_NOT_OK)
    BLOCKED (sin autorizacion)    -> rc = 1  (EXIT_OUTCOME_NOT_OK)
    ERROR                         -> rc = 1  (EXIT_OUTCOME_NOT_OK)

`2` (EXIT_USAGE) queda para argparse, igual que en `pipeline.ingest_cli`.

Las versiones previas de este mando usaban `3` para INCOMPLETE y `4` para
BLOCKED. Chocaban con la tabla del producto, donde `3` ya significa «altas sin
aprobar»: se adoptan los numeros de la tabla y NO se renumera nada de ella.
INCOMPLETE y BLOCKED dejan de distinguirse por el `rc`; se distinguen por el
campo `code` del acta, que no ha cambiado.

Ejecutarlo DOS VECES es seguro: la segunda pasada no encuentra nada que borrar,
no inventa un exito falso y no corrompe --las consultas son borrados por clave
durable, que sobre un grafo ya limpio devuelven cero filas.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from ..driver_neo4j import (
    ENV_DATABASE,
    ENV_PASSWORD_FILE,
    ENV_URI,
    ENV_USER,
    DriverConfigError,
    build_driver_factory,
    resolve_config,
)
from . import codes, exit_codes
from .gate import ENV_ALLOW_REAL_INGEST, ENV_WRITER_WORKSPACE
from .rollback import RollbackDocument, RollbackInstruction
from .rollback_provenance import RollbackReport, execute_rollback

#: Desenlaces. Misma familia de nombres que el writer, misma disciplina.
OUTCOME_DRY_RUN = "DRY_RUN"
OUTCOME_ROLLED_BACK = "ROLLED_BACK"
OUTCOME_INCOMPLETE = "INCOMPLETE"
OUTCOME_BLOCKED = "BLOCKED"
OUTCOME_ERROR = "ERROR"

# Los `rc` NO se deciden aqui: los da la tabla UNICA del producto
# (`writer.exit_codes`, equipo 4C). Estos nombres se conservan porque son API
# de este mando y hay pruebas que los usan, pero ahora son ALIAS de la tabla,
# no numeros propios. Ver `exit_codes.exit_code_for_rollback` para el mapeo y
# para la consecuencia declarada de unificar (INCOMPLETE y BLOCKED comparten
# `rc`; se distinguen por el campo `code` del acta, que no ha cambiado).
RC_OK = exit_codes.EXIT_OK
RC_ERROR = exit_codes.EXIT_OUTCOME_NOT_OK
RC_INCOMPLETE = exit_codes.EXIT_OUTCOME_NOT_OK
RC_BLOCKED = exit_codes.EXIT_OUTCOME_NOT_OK
# La fila `2` de la tabla (EXIT_USAGE) NO se asigna a mano en este mando: la
# usa argparse por su cuenta ante argumentos invalidos, exactamente igual que
# en `pipeline.ingest_cli`. Asignarla ademas a algun desenlace mezclaria "no
# supiste llamarme" con "no salio bien", que es lo contrario de unificar.


def load_document(path: str) -> RollbackDocument:
    """Documento de rollback en JSON -> objeto. Sin adivinar nada."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("el documento de rollback no es un objeto JSON")
    # Un `informe.json` de la ruta de ingesta trae el documento ANIDADO bajo
    # "rollback". Se acepta esa forma porque es la que el operador tiene en la
    # mano, pero no se adivina mas alla de eso.
    if "instructions" not in raw and isinstance(raw.get("rollback"), dict):
        raw = raw["rollback"]
    faltan = [c for c in ("workspace", "instructions") if c not in raw]
    if faltan:
        raise ValueError(
            f"el documento de rollback no declara {faltan}: no se ejecuta"
        )
    doc = RollbackDocument(
        workspace=str(raw["workspace"]),
        snapshot_id=str(raw.get("snapshot_id") or ""),
        plan_hash=str(raw.get("plan_hash") or ""),
        unrecoverable=list(raw.get("unrecoverable") or []),
    )
    for item in raw["instructions"] or []:
        doc.instructions.append(
            RollbackInstruction(
                operation_id=str(item.get("operation_id") or ""),
                action=str(item.get("action") or ""),
                target_id=item.get("target_id"),
                detail=dict(item.get("detail") or {}),
            )
        )
    return doc


def authorize(
    workspace: str, env: Optional[dict[str, str]]
) -> Optional[dict[str, Any]]:
    """Las dos declaraciones del APPLY, exigidas tambien para la inversa.

    Devuelve `None` si autoriza, o el informe de bloqueo. No lee `os.environ`
    por su cuenta: el entorno llega desde `main`, igual que en el gate.
    """
    environ = env or {}
    if environ.get(ENV_ALLOW_REAL_INGEST) != "1":
        return {
            "code": codes.CLI_ROLLBACK_NOT_AUTHORIZED,
            "error": f"la reversion escribe en el grafo: declara {ENV_ALLOW_REAL_INGEST}=1",
        }
    declarado = environ.get(ENV_WRITER_WORKSPACE)
    if declarado != workspace:
        return {
            "code": codes.CLI_ROLLBACK_NOT_AUTHORIZED,
            "error": f"{ENV_WRITER_WORKSPACE}={declarado!r} no coincide con "
                     f"--workspace={workspace!r}: la doble declaracion no cuadra",
        }
    return None


def describe(outcome: str, report: Optional[RollbackReport]) -> str:
    """La linea humana, DERIVADA del informe. No puede contradecirlo.

    Se construye a partir de los mismos campos que deciden el rc, de modo que
    no exista ninguna redaccion que diga «revertido» sobre un informe con
    residuos.
    """
    if report is None:
        return "no se ejecuto nada."
    borrados = sum(
        len(p.get("deleted_evidence") or []) + len(p.get("deleted_episodes") or [])
        + len(p.get("deleted_sources") or [])
        for p in report.purges
    )
    base = (
        f"{len(report.executed)} instrucciones ejecutadas, "
        f"{len(report.purges)} purgas de procedencia "
        f"({borrados} nodos de procedencia borrados)"
    )
    if outcome == OUTCOME_ROLLED_BACK:
        return f"{base}. No queda nada de esa operacion en el grafo."
    return (
        f"{base}. NO es una reversion limpia: {len(report.residues)} residuos y "
        f"{len(report.unrecoverable)} puntos no revertidos (ver 'unrecoverable')."
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="knowledge_v3.writer.cli_rollback",
        description="Ejecuta un documento de rollback. Simulacion por defecto.",
    )
    p.add_argument("documento", help="ruta del documento de rollback en JSON")
    p.add_argument("--workspace", required=True,
                   help="workspace autorizado (declaracion 1 de 2; la 2 es "
                        f"{ENV_WRITER_WORKSPACE})")
    p.add_argument("--operator", default=None, help="identificador del operador")
    p.add_argument("--execute", action="store_true",
                   help="BORRADO REAL. Sin esto solo se enumera lo que haria.")
    p.add_argument("--doc-out", default=None,
                   help="reescribe el documento con lo NO revertido anotado en "
                        "'unrecoverable', para que diga la verdad al releerlo.")
    p.add_argument("--neo4j-uri", default=None, help=f"URI del servidor ({ENV_URI})")
    p.add_argument("--neo4j-user", default=None, help=f"usuario ({ENV_USER})")
    p.add_argument("--neo4j-password-file", default=None,
                   help=f"CAMINO de un fichero 0600 con la contrasena, o '-' para "
                        f"stdin ({ENV_PASSWORD_FILE}). NUNCA por argv.")
    p.add_argument("--neo4j-database", default=None, help=f"base ({ENV_DATABASE})")
    return p


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(
    argv: Optional[list[str]] = None,
    *,
    driver_factory: Optional[Callable[[], Any]] = None,
    env: Optional[dict[str, str]] = None,
) -> int:
    import os

    args = build_parser().parse_args(argv)
    environ = dict(os.environ) if env is None else dict(env)

    try:
        doc = load_document(args.documento)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _emit({"ok": False, "outcome": OUTCOME_ERROR, "error": str(exc)})
        return RC_ERROR

    if doc.workspace != args.workspace:
        _emit({
            "ok": False,
            "outcome": OUTCOME_BLOCKED,
            "code": codes.CLI_ROLLBACK_WORKSPACE_MISMATCH,
            "error": f"el documento es del workspace {doc.workspace!r} y autorizaste "
                     f"{args.workspace!r}",
        })
        return RC_BLOCKED

    if not args.execute:
        # Simulacion: no resuelve conexion, no lee secreto, no toca nada.
        _emit({
            "ok": True,
            "outcome": OUTCOME_DRY_RUN,
            "code": codes.CLI_ROLLBACK_DRY_RUN,
            "workspace": doc.workspace,
            "would_execute": [
                {"operation_id": i.operation_id, "action": i.action,
                 "target_id": i.target_id}
                for i in doc.instructions
            ],
            "unrecoverable_declared": list(doc.unrecoverable),
            "human": f"simulacion: {len(doc.instructions)} instrucciones. "
                     "Anade --execute para revertir de verdad.",
        })
        return RC_OK

    bloqueo = authorize(args.workspace, environ)
    if bloqueo is not None:
        _emit({"ok": False, "outcome": OUTCOME_BLOCKED, **bloqueo})
        return RC_BLOCKED

    factory = driver_factory
    if factory is None:
        try:
            factory = build_driver_factory(
                resolve_config(
                    uri=args.neo4j_uri,
                    user=args.neo4j_user,
                    password_file=args.neo4j_password_file,
                    database=args.neo4j_database,
                    env=environ,
                )
            )
        except DriverConfigError as exc:
            # Falla CERRADO y sin secreto en el mensaje.
            _emit({
                "ok": False,
                "outcome": OUTCOME_ERROR,
                "code": codes.CLI_DRIVER_CONFIG_MISSING,
                "error": str(exc),
            })
            return RC_ERROR

    try:
        driver = factory()
    except DriverConfigError as exc:
        # El fichero del secreto no sirve (ausente, vacio, o legible por el
        # grupo u otros). Codigo ESTABLE: nadie deberia reconocer esto leyendo
        # la redaccion. El mensaje no lleva el secreto, solo el camino.
        _emit({
            "ok": False, "outcome": OUTCOME_ERROR,
            "code": codes.CLI_SECRET_FILE_UNUSABLE,
            "error": str(exc),
        })
        return RC_ERROR
    except Exception as exc:  # noqa: BLE001 - sin conexion no se revierte nada
        _emit({
            "ok": False, "outcome": OUTCOME_ERROR,
            "error": f"{type(exc).__name__}: {exc}",
        })
        return RC_ERROR

    try:
        with driver.session() as session:
            report = execute_rollback(session, doc, annotate=True)
    except Exception as exc:  # noqa: BLE001
        _emit({
            "ok": False, "outcome": OUTCOME_ERROR,
            "error": f"{type(exc).__name__}: {exc}",
        })
        return RC_ERROR
    finally:
        cerrar = getattr(driver, "close", None)
        if callable(cerrar):
            cerrar()

    if args.doc_out:
        Path(args.doc_out).write_text(
            json.dumps(doc.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # El desenlace sale del informe, no de una decision aparte.
    limpio = report.clean and not report.unrecoverable
    outcome = OUTCOME_ROLLED_BACK if limpio else OUTCOME_INCOMPLETE
    _emit({
        "ok": limpio,
        "outcome": outcome,
        "code": codes.CLI_ROLLBACK_COMPLETE if limpio else codes.CLI_ROLLBACK_INCOMPLETE,
        "operator": args.operator,
        "workspace": doc.workspace,
        "report": report.to_dict(),
        "human": describe(outcome, report),
    })
    # El `rc` sale de la tabla unica a partir del MISMO `outcome` que decide la
    # frase humana, que a su vez se deriva del `RollbackReport`. Los tres no
    # pueden divergir porque los tres cuelgan de `limpio`.
    return exit_codes.exit_code_for_rollback(outcome)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
