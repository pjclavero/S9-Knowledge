# -*- coding: utf-8 -*-
"""Codigos de salida de los mandos del writer. **Los `rc` son API.**

POR QUE EXISTE ESTE MODULO
--------------------------
Un runner desatendido no lee actas: lee `rc`. Hasta ahora cada mando decidia
el suyo por su cuenta y `pipeline.ingest_cli` salia **0 sobre un APPLY que el
gate habia BLOQUEADO** -- 0 operaciones, grafo intacto, y el automatismo leia
exito. Peor: quitar `--operador` daba `rc=2`, asi que la inconsistencia era
interna al mismo mando.

Aqui vive la UNICA tabla, y la frase humana se deriva del MISMO desenlace que
el codigo. Ese es el arreglo de raiz del segundo defecto: el acta decia
"dry-run: no se abrio ningun driver" incluso con driver abierto y con
`--apply`, porque la frase se construia aparte del resultado. Una frase que no
depende del desenlace es una frase que puede mentir.

TABLA (estable; reutiliza los codigos que el producto ya usaba)
---------------------------------------------------------------
======  ======================================================  =============
``rc``  significado                                             desenlaces
======  ======================================================  =============
``0``   desenlace correcto y limpio                             APPLIED,
                                                                SIMULATED
``1``   el desenlace NO es correcto: no se escribio lo que un    BLOCKED,
        exito afirmaria                                         REJECTED,
                                                                ABORTED,
                                                                INCONSISTENT,
                                                                ATTEMPTED
``2``   error de USO o de configuracion del mando (argparse ya   --
        usa 2), o desenlace correcto pero con codigos que un
        runner no puede leer como limpio (p.ej.
        ``AUDIT_APPEND_FAILED``)
``3``   hay altas de entidad sin aprobar: no se escribe          --
======  ======================================================  =============

``1`` no se ha inventado: ``writer.cli`` ya devolvia ``1`` para
``not result.ok``. Lo que se hace es EXTENDERLO a ``pipeline.ingest_cli``,
donde ``1`` estaba libre, de modo que BLOCKED queda distinguible del ``2`` de
argparse y del ``3`` de las altas.

COLISION CONOCIDA, DECLARADA
----------------------------
``2`` significa cosas distintas segun el mando: en ``writer.cli`` es "salio
bien pero con codigos"; en ``pipeline.ingest_cli`` es "error de uso". Ambas
son "no lo leas como exito limpio", asi que la regla de automatizacion
``rc == 0`` <-> exito se sostiene, pero un runner NO debe interpretar el 2
identicamente entre mandos. Se documenta en vez de renumerar: renumerar
romperia el historico de los runners existentes.

PARA MANDOS NUEVOS (equipo 4B, rollback)
----------------------------------------
Importa de aqui y no inventes numeros::

    from knowledge_v3.writer.exit_codes import (
        EXIT_OK, EXIT_OUTCOME_NOT_OK, EXIT_USAGE,
        exit_code_for_outcome, describe_outcome,
    )

    return exit_code_for_outcome(result.outcome, result.codes)
"""
from __future__ import annotations

from typing import Iterable, Optional

#: Desenlace correcto y limpio. Lo unico que un runner puede leer como exito.
EXIT_OK = 0
#: El desenlace NO es correcto. El grafo no sostiene lo que un exito afirmaria.
EXIT_OUTCOME_NOT_OK = 1
#: Error de uso/configuracion del mando, o desenlace correcto pero con codigos.
EXIT_USAGE = 2
#: Altas de entidad sin aprobar: falla CERRADO antes de escribir.
EXIT_ALTAS_NOT_APPROVED = 3

#: Los unicos dos desenlaces que valen `rc = 0`. Es la MISMA definicion que
#: `WriteResult.ok`; se replica aqui como tupla de cadenas para que un mando
#: pueda decidir su `rc` a partir de un informe JSON, sin objeto vivo.
OUTCOMES_OK = ("APPLIED", "SIMULATED")

#: Los unicos dos desenlaces del mando de REVERSION que valen `rc = 0`, y por
#: la misma razon que `OUTCOMES_OK`: `ROLLED_BACK` es el `APPLIED` de la
#: reversion (se ejecuto y no quedo nada) y `DRY_RUN` es su `SIMULATED` (se
#: enumero y no se toco nada). `INCOMPLETE`, `BLOCKED` y `ERROR` no estan aqui.
ROLLBACK_OUTCOMES_OK = ("ROLLED_BACK", "DRY_RUN")

__all__ = [
    "EXIT_OK",
    "EXIT_OUTCOME_NOT_OK",
    "EXIT_USAGE",
    "EXIT_ALTAS_NOT_APPROVED",
    "OUTCOMES_OK",
    "ROLLBACK_OUTCOMES_OK",
    "outcome_is_ok",
    "exit_code_for_rollback",
    "exit_code_for_outcome",
    "describe_outcome",
]


def outcome_is_ok(outcome: Optional[str]) -> bool:
    """¿Este desenlace es de los que un runner puede leer como exito?

    ``None`` NO es exito: significa que no hubo resultado de escritura, y
    afirmar lo contrario es justo la clase de mentira que este modulo existe
    para impedir.
    """
    return outcome in OUTCOMES_OK


def exit_code_for_outcome(
    outcome: Optional[str],
    codes: Iterable[str] = (),
    *,
    mode: Optional[str] = None,
) -> int:
    """`rc` de un desenlace de escritura. La tabla del docstring, ejecutable.

    `codes` son los codigos de rechazo/aviso que acompañan al resultado. Un
    desenlace correcto CON codigos (p.ej. `AUDIT_APPEND_FAILED`: se aplico,
    pero sin dejar linea de rastro) no es un exito limpio y sale `2`.

    `mode` cierra un hueco que hoy no se da pero que seria una mentira si se
    diera: un ``SIMULATED`` cuando el operador pidio ``APPLY`` significa "me
    pediste escribir y solo simule". Eso NO es `0`. Se comprueba aqui y no en
    cada mando para que ninguno pueda olvidarlo.
    """
    lista = [c for c in codes]
    if not outcome_is_ok(outcome):
        return EXIT_OUTCOME_NOT_OK
    if mode == "APPLY" and outcome != "APPLIED":
        return EXIT_OUTCOME_NOT_OK
    if lista:
        return EXIT_USAGE
    return EXIT_OK


def describe_outcome(
    outcome: Optional[str],
    *,
    mode: Optional[str] = None,
    applied_operations: int = 0,
    codes: Iterable[str] = (),
    driver_opened: bool = False,
) -> dict:
    """La FRASE humana, derivada del mismo desenlace que el `rc`.

    Devuelve ``{"code": ..., "detail": ...}``, la forma de una carencia del
    acta. Cada afirmacion de la frase sale de un dato observado:

    * "se abrio driver" / "no se abrio ningun driver" sale de `driver_opened`,
      no de suponer que sin `--apply` no hay conexion -- `--desde-grafo` abre
      driver para LEER el catalogo.
    * "dry-run" solo se dice cuando el desenlace es SIMULATED.
    * "no se escribio" es lo cierto en dry-run; "no se toco Neo4j" no lo es.

    ``None`` como desenlace es un caso propio: el writer ni llego a correr.

    Junto a la prosa viajan los HECHOS estructurados de los que esa prosa sale
    (`outcome`, `driver_opened`, `wrote_anything`, `was_dry_run`,
    `applied_operations`, `codes`). Quien quiera comprobar que el acta no
    miente compara ESOS campos, no busca subcadenas en la frase: contar texto
    da falsos negativos en cuanto alguien reescribe una palabra.
    """
    lista = sorted({c for c in codes})
    conexion = (
        "se abrio driver y se consulto Neo4j"
        if driver_opened
        else "no se abrio ningun driver"
    )

    hechos = {
        "outcome": outcome,
        "mode": mode,
        "driver_opened": bool(driver_opened),
        "applied_operations": int(applied_operations or 0),
        "codes": lista,
        # Lo que de verdad ocurrio, en dos booleanos que no admiten matiz.
        "wrote_anything": outcome == "APPLIED" and int(applied_operations or 0) > 0,
        "was_dry_run": outcome == "SIMULATED",
    }

    if outcome is None:
        falta = {
            "code": "SIN_RESULTADO_DE_ESCRITURA",
            "detail": (
                f"la cadena no produjo resultado de escritura ({conexion}). "
                "No hay desenlace que informar: no se afirma ni que se "
                "escribiera ni que se simulara"
            ),
        }
    elif outcome == "APPLIED":
        falta = {
            "code": "ESCRITURA_APLICADA",
            "detail": (
                f"APPLIED: {hechos['applied_operations']} operaciones escritas "
                f"en Neo4j ({conexion}). Esto NO es una carencia: se declara "
                "aqui para que el acta no pueda afirmar lo contrario"
            ),
        }
    elif outcome == "SIMULATED":
        falta = {
            "code": "SIN_ESCRITURA",
            "detail": (
                f"dry-run: no se escribio nada en Neo4j ({conexion}). El plan "
                "se simulo entero; para escribir hace falta --apply y el gate "
                "del writer"
            ),
        }
    elif outcome == "BLOCKED":
        falta = {
            "code": "ESCRITURA_BLOQUEADA",
            "detail": (
                "BLOCKED: el gate del writer rechazo el APPLY y no se escribio "
                f"nada ({conexion}). Codigos: {', '.join(lista) or 'sin codigo'}"
            ),
        }
    else:
        falta = {
            "code": "ESCRITURA_NO_COMPLETADA",
            "detail": (
                f"{outcome}: la escritura no termino correctamente y el grafo "
                f"no sostiene lo que un exito afirmaria ({conexion}). "
                f"Codigos: {', '.join(lista) or 'sin codigo'}"
            ),
        }

    falta["hechos"] = hechos
    return falta


def exit_code_for_rollback(
    outcome: Optional[str],
    *,
    usage_error: bool = False,
) -> int:
    """`rc` del mando de REVERSION, con LA MISMA tabla de este modulo.

    El mando de rollback (equipo 4B) nacio antes de que esta tabla existiera y
    traia numeros propios (``INCOMPLETE=3``, ``BLOCKED=4``) que chocaban con
    ella: aqui ``3`` ya significaba "altas sin aprobar" y ``4`` no significaba
    nada. Dos mandos del mismo producto con dos tablas distintas es justo lo
    que este modulo existe para impedir, asi que el mando importa ESTA y no
    conserva las suyas. No se renumera nada de lo ya publicado.

    El mapeo no inventa significados nuevos, reutiliza los de la tabla:

    * ``ROLLED_BACK`` limpio y ``DRY_RUN`` valido -> ``0``. Son los unicos dos.
      Es la misma regla que `OUTCOMES_OK`, aplicada a la operacion inversa.
    * ``INCOMPLETE`` (quedan residuos, procedencia conservada o instrucciones
      no reconstruibles), ``BLOCKED`` (sin la declaracion de operador) y
      ``ERROR`` de ejecucion -> ``1``: *el desenlace NO es correcto, el grafo
      no sostiene lo que un exito afirmaria*. Literalmente la fila ``1``.
    * ``usage_error=True`` -> ``2``: documento ilegible, conexion sin declarar
      o fichero de secreto inservible. Es *error de USO o de configuracion del
      mando*, la fila ``2``, y coincide con el sentido que ``2`` ya tenia en
      ``pipeline.ingest_cli``.

    CONSECUENCIA DECLARADA de unificar: ``INCOMPLETE`` y ``BLOCKED`` ya no se
    distinguen por el `rc` (antes ``3`` y ``4``, ahora ambos ``1``). No es una
    perdida de informacion: quien necesite distinguirlos lee el campo `code`
    del acta (``CLI_ROLLBACK_INCOMPLETE`` / ``CLI_ROLLBACK_NOT_AUTHORIZED`` /
    ``CLI_ROLLBACK_WORKSPACE_MISMATCH``), estable y explicito. Lo que el `rc`
    garantiza -- y es lo que se pidio -- es que **solo un desenlace limpio sale
    0**, con el mismo numero en todos los mandos del producto.
    """
    if usage_error:
        return EXIT_USAGE
    if outcome in ROLLBACK_OUTCOMES_OK:
        return EXIT_OK
    return EXIT_OUTCOME_NOT_OK
