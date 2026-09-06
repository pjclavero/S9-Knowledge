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

TABLA DE CORRIDA (equipo 5C). Misma numeracion, desenlaces de la corrida
entera -- incluidos los que ocurren cuando el writer NO llega a correr::

    APPLIED                     -> 0   escribio
    NOOP_IDEMPOTENT             -> 0   nada que cambiar; ya estaba escrito
    SIMULATED                   -> 0   si se pidio dry-run
    NO_WRITE_REQUESTED          -> 0   si se pidio dry-run

    NO_WRITE_PATH               -> 1   se pidio --apply y no se llego al writer
    BLOCKED / REJECTED / ...    -> 1   el desenlace del writer no es correcto
    <cualquier desenlace nuevo> -> 1   falla CERRADO: lo desconocido no es exito

`resolve_run_outcome` nombra el desenlace UNA vez; `exit_code_for_run` da el
numero y `describe_outcome` da la frase a partir de ESA misma cadena.

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

# ---------------------------------------------------------------------------
# VOCABULARIO DE DESENLACES DE LA REVERSION (consolidado en la INTEGRACION 5).
# ---------------------------------------------------------------------------
# El equipo 5B pregunto explicitamente al integrador donde debian vivir las
# frases de `NO_OPERATOR` / `NO_AUDIT` / `UNEXPECTED_RESIDUE`, y razono que
# `describe_outcome`/`RUN_OUTCOMES_OK` son de la CORRIDA DE INGESTA mientras
# que el rollback tiene su propia tabla. Lo primero es cierto; la conclusion
# no se sigue, y lo que decide es un hecho observable del arbol ya integrado:
#
#   la tabla de `rc` del rollback YA VIVIA AQUI  -> `ROLLBACK_OUTCOMES_OK`
#                                                   `exit_code_for_rollback`
#   los NOMBRES y las FRASES vivian en `cli_rollback`
#
# Es decir, el vocabulario del rollback ya estaba PARTIDO en dos ficheros: dar
# de alta un desenlace nuevo obligaba a tocar los dos, y quien tocase solo uno
# obtendria un desenlace con `rc` pero sin frase, o con frase pero colandose
# por la lista blanca. Eso es exactamente el "dos sitios donde tocar para lo
# mismo" que hay que evitar, y es la razon de que se consolide AQUI y no en
# `cli_rollback`: este modulo es, por su propia cabecera, la casa de los
# desenlaces de LOS MANDOS DEL WRITER (en plural), y ya alberga dos tablas
# distintas conviviendo -- la de operacion (`OUTCOMES_OK`) y la de corrida
# (`RUN_OUTCOMES_OK`). El rollback es la tercera, no una excepcion.
#
# Lo que NO se hace: mezclar las tablas. `RUN_*` sigue siendo de la ingesta y
# `ROLLBACK_*` de la reversion; son vecinas, no la misma. `cli_rollback`
# reexporta estos nombres para no romper su API ni las pruebas que la usan.

#: Se pidio borrar sin `--operator`. Un borrado anonimo no es auditable.
ROLLBACK_NO_OPERATOR = "NO_OPERATOR"

#: Se pidio borrar sin registro de auditoria UTILIZABLE (ausente, o declarado
#: pero no escribible). Sin rastro no se borra.
ROLLBACK_NO_AUDIT = "NO_AUDIT"

#: La reversion corrio y el grafo NO sostiene lo que un exito afirmaria.
#: Sustituye a `INCOMPLETE` a secas, que se conserva como alias historico.
ROLLBACK_UNEXPECTED_RESIDUE = "UNEXPECTED_RESIDUE"

#: Frases de los desenlaces del rollback que NO dependen del informe. Viven
#: junto a la lista blanca que les da el `rc`, de modo que el nombre, el `rc` y
#: la frase se dan de alta en UN solo sitio. Los desenlaces cuya frase SI
#: depende de los hechos medidos (`ROLLED_BACK`/`UNEXPECTED_RESIDUE`) no
#: pueden ser una constante: los redacta `cli_rollback.describe` a partir de
#: `rollback_facts`, que es lo que impide que la frase contradiga al grafo.
ROLLBACK_PHRASES: dict[str, str] = {
    ROLLBACK_NO_OPERATOR: (
        "BLOQUEADO sin --operator: no se borro nada y no se llego a abrir "
        "sesion contra el grafo. La reversion borra, y un borrado anonimo "
        "no es atribuible ni auditable."
    ),
    ROLLBACK_NO_AUDIT: (
        "BLOQUEADO sin registro de auditoria utilizable: no se borro nada "
        "y no se llego a abrir sesion contra el grafo. Sin rastro no se "
        "borra, igual que en el apply."
    ),
}


def describe_rollback_outcome(outcome: str) -> Optional[str]:
    """La frase fija de ese desenlace de reversion, o `None` si no la tiene.

    `None` NO significa "no hay frase": significa "esta frase se DERIVA de los
    hechos medidos", y quien pregunta debe redactarla desde el informe. Se
    devuelve `None` en vez de una cadena generica a proposito, para que un
    desenlace nuevo sin frase no se disfrace de desenlace descrito.
    """
    return ROLLBACK_PHRASES.get(outcome)


# ---------------------------------------------------------------------------
# TABLA DE DESENLACES DE CORRIDA (equipo 5C). PUBLICA: importadla, no la
# reinventeis.
# ---------------------------------------------------------------------------
# Los desenlaces de ARRIBA (`OUTCOMES_OK`) son los del WRITER: lo que el writer
# devuelve cuando corre. Esta segunda tabla es la de la CORRIDA ENTERA, que es
# lo que un runner desatendido observa, y existe porque hay desenlaces que el
# writer no puede nombrar: **los que ocurren cuando el writer no llega a
# correr**.
#
# DEFECTO MEDIDO QUE CIERRA ESTA TABLA
# ------------------------------------
# `pipeline.ingest_cli` salia `0` en un `--apply` que no habia escrito nada,
# porque razonaba "sin bloque `write` no hubo writer, luego fue una ingesta
# normal, luego exito". Eso es cierto en dry-run y FALSO bajo `--apply`: si el
# operador pidio escribir y la cadena paro antes del writer (`SIN_PLAN`,
# `CADENA_DETENIDA`), el acta lo declaraba con honestidad y el `rc` decia 0.
# Una clase entera de APPLY fallidos era indistinguible de un APPLY aplicado.
#
# LA TRAMPA QUE ESTA TABLA NO PISA
# --------------------------------
# "0 operaciones" NO es "fallo". Un `--apply` repetido sobre conocimiento que
# ya esta escrito devuelve `APPLIED` con `applied_operations == 0` y
# `noop_operations > 0`: es el NO-OP IDEMPOTENTE, y es un EXITO. Por eso la
# regla NO es `operaciones == 0 -> error`, que romperia la idempotencia; la
# regla es que manda **el desenlace**, y el recuento solo sirve para NOMBRAR
# ese desenlace (`APPLIED` con 0 escrituras y algun no-op respaldado es
# `NOOP_IDEMPOTENT`, no un APPLY vacio).

#: El operador pidio `--apply` y el writer NUNCA llego a correr: la cadena paro
#: antes (sin plan, sin claims, etapa detenida) o se configuro sin writer. No
#: hay desenlace de escritura que informar, y por eso mismo no puede ser 0.
RUN_NO_WRITE_PATH = "NO_WRITE_PATH"
#: `--apply` que no tenia nada semantico que cambiar: el conocimiento ya estaba
#: escrito. Es `APPLIED` con 0 operaciones nuevas y no-ops respaldados por el
#: grafo. **Exito**, y el desenlace que ninguna regla simplista debe romper.
RUN_NOOP_IDEMPOTENT = "NOOP_IDEMPOTENT"
#: No se pidio escribir y no se escribio: ingesta en dry-run cuya cadena no
#: llego al writer. El usuario pidio dry-run y obtuvo dry-run. Exito.
RUN_NO_WRITE_REQUESTED = "NO_WRITE_REQUESTED"

#: Los UNICOS desenlaces de corrida que valen `rc = 0`. Todo lo demas -- lo que
#: ya existe y **lo que otros equipos añadan** -- sale distinto de 0 sin tocar
#: este modulo. Eso es deliberado: la tabla falla CERRADA, asi que un desenlace
#: nuevo (p.ej. el `CONSTRAINTS_MISSING` que el equipo 5A va a introducir, o
#: los `NO_OPERATOR` / `NO_AUDIT` / `UNEXPECTED_RESIDUE` del 5B) es no-cero por
#: omision y solo se añade aqui si de verdad es un exito limpio.
RUN_OUTCOMES_OK = (
    "APPLIED",
    "SIMULATED",
    RUN_NOOP_IDEMPOTENT,
    RUN_NO_WRITE_REQUESTED,
)

__all__ = [
    "RUN_NO_WRITE_PATH",
    "RUN_NOOP_IDEMPOTENT",
    "RUN_NO_WRITE_REQUESTED",
    "RUN_OUTCOMES_OK",
    "resolve_run_outcome",
    "exit_code_for_run",
    "EXIT_OK",
    "EXIT_OUTCOME_NOT_OK",
    "EXIT_USAGE",
    "EXIT_ALTAS_NOT_APPROVED",
    "OUTCOMES_OK",
    "ROLLBACK_OUTCOMES_OK",
    "ROLLBACK_NO_OPERATOR",
    "ROLLBACK_NO_AUDIT",
    "ROLLBACK_UNEXPECTED_RESIDUE",
    "ROLLBACK_PHRASES",
    "describe_rollback_outcome",
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
        # ¿Llego a correr el writer? `NO_WRITE_PATH` y `NO_WRITE_REQUESTED`
        # son justo los dos desenlaces en que NO corrio, y distinguirlos del
        # resto es lo que permite a un lector saber si el silencio del acta es
        # esperado (dry-run) o un fallo (apply sin camino al writer).
        "reached_writer": outcome not in (
            None, RUN_NO_WRITE_PATH, RUN_NO_WRITE_REQUESTED,
        ),
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
    elif outcome == RUN_NO_WRITE_PATH:
        falta = {
            "code": "APPLY_SIN_CAMINO_AL_WRITER",
            "detail": (
                "se pidio --apply y la cadena NO llego al writer: no hubo "
                f"intento de escritura y el grafo esta como estaba ({conexion}). "
                "Esto NO es una ingesta correcta: lo que se pidio -- escribir -- "
                "no se intento siquiera. Mira las carencias previas (SIN_PLAN, "
                "SIN_CLAIMS, CADENA_DETENIDA) para saber donde paro"
            ),
        }
    elif outcome == RUN_NOOP_IDEMPOTENT:
        falta = {
            "code": "SIN_CAMBIOS_IDEMPOTENTE",
            "detail": (
                f"APPLY idempotente: no habia nada semantico que cambiar "
                f"({conexion}). Las operaciones del plan ya estaban aplicadas y "
                "el writer comprobo que el grafo las sostiene. Se escribieron 0 "
                "operaciones nuevas y eso es el resultado CORRECTO, no un fallo"
            ),
        }
    elif outcome == RUN_NO_WRITE_REQUESTED:
        falta = {
            "code": "SIN_ESCRITURA",
            "detail": (
                f"no se pidio escribir y no se escribio nada ({conexion}). La "
                "cadena no llego al writer y en dry-run eso es lo esperado: "
                "para escribir hace falta --apply"
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


def resolve_run_outcome(
    requested_mode: Optional[str],
    write_block: Optional[dict],
) -> str:
    """El DESENLACE de la corrida entera, a partir de lo OBSERVADO.

    Un solo sitio decide que paso de verdad, y despues `exit_code_for_run` da
    el numero y `describe_outcome` da la frase **a partir de esta misma
    cadena**. Ese es el invariante que impide que texto y codigo divergan: si
    se construyesen por separado volveria el agujero que la tanda anterior ya
    cerro un piso mas abajo.

    `requested_mode` es lo que el USUARIO pidio (`"APPLY"` / `"DRY_RUN"`), no
    lo que el writer hizo. La distincion es el nucleo del arreglo: sin ella no
    se puede separar "no se escribio porque no me lo pediste" de "no se
    escribio aunque me lo pediste".

    `write_block` es el bloque `write` del informe, o ``None`` si el writer no
    llego a correr.
    """
    pedido_apply = requested_mode == "APPLY"

    if not write_block:
        # El writer NUNCA corrio. En dry-run eso es lo esperado; bajo --apply
        # es un fallo, y es exactamente el caso que salia 0.
        return RUN_NO_WRITE_PATH if pedido_apply else RUN_NO_WRITE_REQUESTED

    outcome = write_block.get("outcome")
    aplicadas = int(write_block.get("applied_operations") or 0)
    noop = int(write_block.get("noop_operations") or 0)

    # NO-OP IDEMPOTENTE. Se nombra aparte de `APPLIED` porque son cosas
    # distintas que merecen frases distintas, pero AMBAS valen 0: el writer ya
    # comprobo (`EXEC_NOOP_WITHOUT_GRAPH_EVIDENCE`) que cada no-op tiene
    # respaldo en el grafo, asi que "0 escrituras" aqui significa "ya estaba",
    # no "no se pudo".
    if outcome == "APPLIED" and aplicadas == 0 and noop > 0:
        return RUN_NOOP_IDEMPOTENT

    # Cualquier otro desenlace se pasa TAL CUAL: los del writer que ya existen
    # y los que otros equipos añadan. `exit_code_for_run` falla cerrado sobre
    # los que no reconoce, asi que un desenlace nuevo no puede colarse como 0.
    return outcome if outcome is not None else RUN_NO_WRITE_PATH


def exit_code_for_run(
    outcome: Optional[str],
    codes: Iterable[str] = (),
    *,
    requested_mode: Optional[str] = None,
) -> int:
    """`rc` de la CORRIDA entera. Misma tabla, aplicada al desenlace resuelto.

    Falla CERRADO: lo que no este en `RUN_OUTCOMES_OK` sale distinto de 0,
    incluido cualquier desenlace que un equipo añada mañana sin tocar este
    modulo. Un desenlace desconocido no es un exito.

    `requested_mode` cierra la misma mentira que cierra `exit_code_for_outcome`
    un piso mas abajo: un `SIMULATED` cuando el operador pidio `APPLY` es "me
    pediste escribir y solo simule", y eso no es 0.
    """
    lista = [c for c in codes]
    if outcome not in RUN_OUTCOMES_OK:
        return EXIT_OUTCOME_NOT_OK
    if requested_mode == "APPLY" and outcome in ("SIMULATED", RUN_NO_WRITE_REQUESTED):
        return EXIT_OUTCOME_NOT_OK
    if lista:
        return EXIT_USAGE
    return EXIT_OK


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
