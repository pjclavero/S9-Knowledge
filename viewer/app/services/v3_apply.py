# -*- coding: utf-8 -*-
"""SELLAR y APLICAR desde la consola del operador. El llamador que faltaba.

QUÉ ESTABA ROTO
---------------
`apply_v3(...)` —la única definición de «aplicar V3», con `compute_apply_id` y
`compute_ownership_id` dentro— estaba completa y tenía CERO llamadores desde
`viewer/`. Una función completa sin llamador en el recorrido real del operador
es capacidad NO USABLE: desde el producto, aprobar una propuesta no escribía
nunca nada en el grafo, y nada lo decía.

EL CONTRATO QUE ESTE MÓDULO IMPLEMENTA
--------------------------------------
    ingest run -> propuestas -> decisiones en review.sqlite3
               -> SELLAR PLAN  (snapshot inmutable en review.sqlite3)
               -> APPLY consume ESE snapshot
               -> apply_id

El plan NO se recalcula en el momento de aplicar. Aunque el pipeline fuese
determinista hoy, aplicar un plan recalculado sería aplicar algo distinto de lo
que la persona revisó. Aquí se carga el snapshot sellado y se le entrega TAL
CUAL al núcleo. La mutación que sustituye esa carga por una regeneración del
plan tiene su control negativo en la suite, y se pone roja.

`plan_id` es identidad INTERNA. No se le pide al operador, no se le enseña y no
viaja en ninguna URL: la acción se dirige a la CORRIDA, que es lo que él sí
conoce porque el acuse de la ingesta se la nombró.

QUÉ NO HACE
-----------
No toca rollback, no crea una segunda cola, no crea un segundo almacén de
decisiones y no abre conexión a Neo4j antes de que el gate autorice — para eso
se le pasa `driver_factory` al `GraphWriter`, que es su contrato.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.services.v3_review import (
    ReviewError,
    ReviewService,
    _active_decisions,
    _proposal_id,
    load_proposals,
)
from app.services.v3_review_store import (
    AuditChainBroken,
    SealConflict,
    active_decision_ids,
)

log = logging.getLogger("panel.apply")

__all__ = [
    "ApplyError",
    "EstadoDelPlan",
    "ReviewApplyService",
    "CODIGOS",
    "ENV_ALLOW_REAL_INGEST",
    "ENV_WRITER_WORKSPACE",
]

#: Las DOS declaraciones que el gate del writer exige para escribir de verdad.
#: Se nombran aquí para que el panel pueda decir «no está habilitado» sin
#: llamar al writer, y para que el invariante de despliegue sea enumerable.
ENV_ALLOW_REAL_INGEST = "S9K_ALLOW_REAL_INGEST"
ENV_WRITER_WORKSPACE = "S9K_WRITER_WORKSPACE"

#: Códigos ESTABLES de esta capacidad. Son los que el panel convierte en frase;
#: ninguno lleva ruta, traza ni identidad interna.
CODIGOS = (
    "REVIEW_STORE_UNAVAILABLE",
    "NO_APPROVED_PROPOSALS",
    "NO_APPLICABLE_PROPOSALS",
    "SEAL_CONFLICT",
    "PLAN_NOT_SEALED",
    "PLAN_ALREADY_APPLIED",
    "PLAN_APPLY_IN_FLIGHT",
    "AUDIT_CHAIN_BROKEN",
    "PLAN_SUPERSEDED",
    "APPLY_NOT_ENABLED",
    "GRAPH_UNAVAILABLE",
    "APPLY_REJECTED",
    "APPLY_FAILED",
)


class ApplyError(RuntimeError):
    """Fallo EXPRESADO PARA UN OPERADOR: un código estable y nada más.

    El detalle técnico no cabe aquí a propósito — no hay campo donde meterlo.
    Va al log del servidor, que es donde tiene que estar: el repositorio es
    público y una traza en pantalla es una ruta interna publicada.
    """

    def __init__(self, code: str, detail: str = ""):
        assert code in CODIGOS, f"código no declarado: {code}"
        self.code = code
        super().__init__(code)
        if detail:
            log.error("apply: %s | %s", code, detail)


class EstadoDelPlan:
    """Lo que la pantalla puede decir de la corrida. Sin conocimiento interno.

    NO lleva `plan_id`, ni `workspace`, ni `snapshot_id`, ni rutas, ni
    comandos: son identidades del servidor. Lleva lo que el operador necesita
    para decidir qué hacer y para entender qué pasó.
    """

    __slots__ = (
        "estado", "aprobadas", "pendientes", "en_el_plan", "excluidas",
        "afirmaciones_escritas", "habilitado", "avisos",
    )

    def __init__(
        self,
        *,
        estado: str,
        aprobadas: int = 0,
        pendientes: int = 0,
        en_el_plan: int = 0,
        excluidas: tuple = (),
        afirmaciones_escritas: Optional[int] = None,
        habilitado: bool = False,
        avisos: tuple = (),
    ):
        self.estado = estado
        self.aprobadas = aprobadas
        self.pendientes = pendientes
        self.en_el_plan = en_el_plan
        self.excluidas = excluidas
        self.afirmaciones_escritas = afirmaciones_escritas
        self.habilitado = habilitado
        self.avisos = avisos

    @property
    def sellable(self) -> bool:
        """¿Se puede ofrecer el botón de sellar? Sin aprobadas, NO.

        Requisito 8: sin plan aprobado no se habilita ni se finge la acción.
        """
        return self.estado in ("sin_plan", "superseded") and self.aprobadas > 0

    @property
    def aplicable(self) -> bool:
        return self.estado == "sealed" and self.en_el_plan > 0

    def to_dict(self) -> dict:
        return {
            "estado": self.estado,
            "aprobadas": self.aprobadas,
            "pendientes": self.pendientes,
            "en_el_plan": self.en_el_plan,
            "excluidas": [dict(e) for e in self.excluidas],
            "afirmaciones_escritas": self.afirmaciones_escritas,
            "habilitado": self.habilitado,
            "sellable": self.sellable,
            "aplicable": self.aplicable,
            "avisos": list(self.avisos),
        }


_PUENTE = threading.Lock()


def _motor():
    """El paquete del MOTOR, por el mismo puente que ya usa `jobs_client`.

    Visor -> motor es la única dirección posible (los dos publican un paquete
    `app` distinto) y ya está en uso para `jobs.job_store`. No se copia ni un
    símbolo: se importa la definición canónica.
    """
    with _PUENTE:
        raiz = Path(__file__).resolve().parents[3] / "data-engine" / "app"
        if raiz.is_dir() and str(raiz) not in sys.path:
            sys.path.insert(0, str(raiz))
    from knowledge_v3 import review_plan as review_plan_mod  # noqa: PLC0415
    from knowledge_v3.writer.apply import apply_v3  # noqa: PLC0415
    from knowledge_v3.writer.gate import OperatorRequest  # noqa: PLC0415
    from knowledge_v3.writer.writer import GraphWriter, MODE_APPLY  # noqa: PLC0415

    return review_plan_mod, apply_v3, OperatorRequest, GraphWriter, MODE_APPLY


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ReviewApplyService:
    """Sella y aplica el plan de UNA corrida. Una instancia, un almacén."""

    def __init__(self, review: Optional[ReviewService] = None) -> None:
        self.review = review or ReviewService()

    @property
    def store(self):
        return self.review.store

    # -- lectura -----------------------------------------------------------

    def _aprobadas(self, workspace: str, job_id: str) -> tuple[list, dict, int, list]:
        """Propuestas de ESTA corrida con decisión humana activa `APPROVE`.

        Devuelve ADEMÁS las `decision_id` activas del workspace DERIVADAS DE LA
        MISMA LECTURA (B1). No es un extra de comodidad: es lo único que hace
        cierta la garantía. Volver a leerlas después, en otra conexión, hacía
        que la guarda del sellado comparase la segunda lectura contra la
        tercera y NUNCA la primera contra la tercera — y un cambio de decisión
        en esa ventana quedaba invisible.

        `load_proposals` LEVANTA ante almacén ausente o ilegible (Corte 4). Se
        llama desde aquí, así que este consumidor lo cubre: la excepción se
        traduce a un código estable y NO se degrada a «no hay nada aprobado»,
        que es justo la confusión que aquel corte cerró.
        """
        try:
            todas = load_proposals(self.review.proposals_dir)
        except ReviewError as exc:
            raise ApplyError("REVIEW_STORE_UNAVAILABLE", str(exc)) from exc
        # UNA SOLA LECTURA. De aquí salen las dos cosas.
        registros = self.store.decisions()
        esperadas = active_decision_ids(registros, workspace)
        activas = _active_decisions(registros)
        de_la_corrida = [
            p for p in todas
            if p.get("workspace") == workspace and job_id in (p.get("package_runs") or ())
        ]
        aprobadas: list = []
        decision_ids: dict = {}
        pendientes = 0
        for propuesta in de_la_corrida:
            identificador = _proposal_id(propuesta)
            decision = activas.get(identificador)
            if decision is None:
                pendientes += 1
                continue
            if decision.get("human_decision") == "APPROVE":
                aprobadas.append(propuesta)
                decision_ids[identificador] = str(decision.get("decision_id") or "")
        return aprobadas, decision_ids, pendientes, esperadas

    def estado(self, *, workspace: str, job_id: str) -> EstadoDelPlan:
        """El estado de la corrida, para pintar la pantalla. Nunca sella nada."""
        habilitado = self._habilitado(workspace)
        try:
            aprobadas, _, pendientes, _ = self._aprobadas(workspace, job_id)
        except ApplyError as exc:
            return EstadoDelPlan(estado="no_disponible", habilitado=habilitado,
                                 avisos=(exc.code,))
        ultimo = self.store.last_plan(workspace=workspace, job_id=job_id)
        if ultimo is None:
            return EstadoDelPlan(
                estado="sin_plan", aprobadas=len(aprobadas), pendientes=pendientes,
                habilitado=habilitado,
            )
        try:
            documento = json.loads(ultimo["plan_json"])
            operaciones = len(documento.get("mutation_operations") or [])
        except (TypeError, ValueError):  # pragma: no cover - fila corrupta
            operaciones = 0
        estado = ultimo["state"]
        # LO ESCRITO SE LEE DE LO QUE EL WRITER DIJO, NO DEL PLAN (B2).
        # Derivarlo de `len(mutation_operations)` no distingue un apply hecho
        # de uno abortado: una fila marcada y un proceso muerto producían
        # «1 afirmación añadida» con el grafo vacío.
        escritas = ultimo["applied_operations"] if estado == "applied" else None
        try:
            notas = tuple(json.loads(ultimo["apply_notes_json"] or "[]"))
        except (TypeError, ValueError):  # pragma: no cover - fila corrupta
            notas = ()
        return EstadoDelPlan(
            estado=estado,
            aprobadas=len(aprobadas),
            pendientes=pendientes,
            en_el_plan=operaciones,
            afirmaciones_escritas=escritas,
            habilitado=habilitado,
            avisos=notas,
        )

    def _habilitado(self, workspace: str) -> bool:
        """¿Está este despliegue autorizado a escribir en el grafo?

        Se lee la MISMA declaración que el gate del writer exige, no una
        variable propia: una segunda declaración podría decir «sí» mientras el
        gate dice «no», y el operador vería un botón que nunca funciona.
        """
        entorno = os.environ
        return (
            entorno.get(ENV_ALLOW_REAL_INGEST) == "1"
            and bool(entorno.get(ENV_WRITER_WORKSPACE))
            and entorno.get(ENV_WRITER_WORKSPACE) == workspace
        )

    # -- sellado -----------------------------------------------------------

    def sellar(self, *, workspace: str, job_id: str) -> dict:
        """Sella el plan de la corrida desde propuestas + decisiones persistidas.

        No se ejecuta ni un paso del pipeline. Lo único que entra es lo que ya
        está guardado.
        """
        review_plan_mod = _motor()[0]
        aprobadas, decision_ids, _, esperadas = self._aprobadas(workspace, job_id)
        if not aprobadas:
            raise ApplyError("NO_APPROVED_PROPOSALS")
        ahora = _ahora()
        try:
            construido = review_plan_mod.seal_review_plan(
                workspace=workspace,
                job_id=job_id,
                revision=self._siguiente_revision(workspace, job_id),
                approved=aprobadas,
                decision_ids=decision_ids,
                now=ahora,
            )
        except review_plan_mod.ReviewPlanError as exc:
            raise ApplyError("NO_APPLICABLE_PROPOSALS", str(exc)) from exc

        documento = construido.plan_doc
        # LO QUE SE PASA AQUÍ ES, LITERALMENTE, LO QUE SE LEYÓ (B1).
        #
        # `esperadas` viene de la MISMA lectura con la que se construyó el plan.
        # El almacén la vuelve a derivar dentro de `BEGIN IMMEDIATE` y compara;
        # si alguien decidió, deshizo o corrigió en cualquier momento desde que
        # empezamos a componer este plan, no se sella nada.
        #
        # Antes había aquí una SEGUNDA lectura, en otra conexión, y era la que
        # se pasaba: la guarda comparaba esa segunda contra la tercera, así que
        # la ventana entre la primera y la segunda no la vigilaba nadie.
        try:
            fila = self.store.seal_plan(
                workspace=workspace,
                job_id=job_id,
                plan_id=documento["plan_id"],
                plan_json=json.dumps(documento, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")),
                plan_hash=documento["plan_hash"]["value"],
                decision_ids=list(construido.decision_ids),
                proposal_ids=list(construido.included_proposal_ids),
                sealed_at=ahora,
                expected_decision_ids=esperadas,
            )
        except SealConflict as exc:
            raise ApplyError("SEAL_CONFLICT", str(exc)) from exc
        except AuditChainBroken as exc:
            raise ApplyError("AUDIT_CHAIN_BROKEN", str(exc)) from exc
        if construido.excluded:
            # NINGUNA EXCLUSIÓN EN SILENCIO. El código se traduce con la tabla
            # cerrada del motor (`SEAL_CODES`), que es también quien impide que
            # se emita un motivo que nadie declaró.
            log.warning(
                "sellado con exclusiones (%s): %s",
                job_id,
                "; ".join(
                    f"{e.code}: {review_plan_mod.SEAL_CODES.get(e.code, '')}"
                    for e in construido.excluded
                ),
            )
        return {
            "en_el_plan": len(documento["mutation_operations"]),
            "excluidas": tuple(e.to_dict() for e in construido.excluded),
            "revision": fila["revision"] if fila else None,
        }

    def _siguiente_revision(self, workspace: str, job_id: str) -> int:
        ultimo = self.store.last_plan(workspace=workspace, job_id=job_id)
        return (int(ultimo["revision"]) if ultimo else 0) + 1

    # -- aplicación --------------------------------------------------------

    def aplicar(self, *, workspace: str, job_id: str, operator_id: str) -> dict:
        """Aplica el snapshot sellado vigente. NO regenera el plan.

        El desenlace se CONFIRMA antes de devolver nada: lo que decide si esto
        fue un éxito es `write_result.mode == APPLY` y `ok`, no que la llamada
        no reventara.
        """
        review_plan_mod, apply_v3, OperatorRequest, GraphWriter, MODE_APPLY = _motor()
        del review_plan_mod

        vigente = self.store.sealed_plan(workspace=workspace, job_id=job_id)
        if vigente is None:
            ultimo = self.store.last_plan(workspace=workspace, job_id=job_id)
            if ultimo is None:
                raise ApplyError("PLAN_NOT_SEALED")
            if ultimo["state"] == self.store.ESTADO_APLICADO:
                raise ApplyError("PLAN_ALREADY_APPLIED")
            if ultimo["state"] == self.store.ESTADO_EN_VUELO:
                # NO SE REINTENTA A CIEGAS. Se tomó y no consta el desenlace:
                # puede haber escrito. Reaplicar sería arriesgar la duplicación
                # que esta capacidad existe para impedir.
                raise ApplyError("PLAN_APPLY_IN_FLIGHT")
            raise ApplyError("PLAN_SUPERSEDED")

        if not self._habilitado(workspace):
            # NO ES CULPA DEL OPERADOR: el despliegue no declara permiso de
            # escritura. Se dice antes de tomar el plan, para no dejarlo
            # marcado por una condición que ya se conocía.
            raise ApplyError("APPLY_NOT_ENABLED")

        plan_id = vigente["plan_id"]
        tomado = self.store.claim_for_apply(plan_id=plan_id, now=_ahora())
        if not tomado["claimed"]:
            # Otro clic llegó primero y el plan ya está tomado. Desenlace
            # EXPLÍCITO: cero duplicación semántica, y se dice.
            raise ApplyError("PLAN_ALREADY_APPLIED")

        # EL SNAPSHOT, TAL CUAL SE SELLÓ. Aquí es donde un recálculo del plan
        # sería el defecto: lo que se aplica es lo que se leyó de la fila.
        documento = json.loads(tomado["plan"]["plan_json"])

        aplicado = False
        apply_id = None
        try:
            writer = GraphWriter(
                workspace=workspace,
                driver_factory=self._driver_factory(),
                max_operations=len(documento["mutation_operations"]),
            )
            peticion = OperatorRequest(
                apply=True,
                operator_id=operator_id,
                workspace=workspace,
                # El hash se toma del SNAPSHOT PERSISTIDO, que es el artefacto
                # que el operador autorizó al sellar. No se recalcula desde el
                # documento en memoria: entonces confirmaría lo que sea que
                # haya ahora, que es no confirmar nada.
                expected_plan_hash=tomado["plan"]["plan_hash"],
                max_operations=len(documento["mutation_operations"]),
                current_snapshot_id=documento["snapshot_id"],
                env=dict(os.environ),
            )
            salida = apply_v3(documento, peticion, writer=writer)
            resultado = salida.write_result
            aplicado = bool(
                getattr(resultado, "ok", False)
                and getattr(resultado, "mode", None) == MODE_APPLY
            )
            apply_id = salida.apply_id
            escritas = int(getattr(resultado, "applied_operations", 0) or 0)
            noop = int(getattr(resultado, "noop_operations", 0) or 0)
            rechazos = [r.code for r in (getattr(resultado, "rejections", None) or [])]
        except Exception as exc:  # noqa: BLE001 - se traduce, no se propaga
            self.store.record_apply_result(
                plan_id=plan_id, apply_id=None, ok=False, now=_ahora(),
                notes=["APPLY_FAILED"],
            )
            log.exception("apply fallido para la corrida %s", job_id)
            raise ApplyError("APPLY_FAILED", type(exc).__name__) from exc

        # SÓLO AHORA se sabe qué pasó. El estado se corrige con el desenlace
        # REAL —recuento del writer y sus códigos incluidos— antes de contestar
        # nada al operador.
        notas = [n["code"] for n in salida.notes]
        self.store.record_apply_result(
            plan_id=plan_id, apply_id=apply_id, ok=aplicado, now=_ahora(),
            applied_operations=escritas, notes=notas,
        )
        if not aplicado:
            log.error("apply rechazado para %s: %s", job_id, rechazos)
            raise ApplyError("APPLY_REJECTED", ",".join(rechazos))
        return {
            "afirmaciones_escritas": escritas,
            "sin_cambios": noop,
            "notas": notas,
        }

    def _driver_factory(self):
        """Fábrica de driver que el writer invoca DESPUÉS del gate.

        Pasarla en vez de un driver ya abierto es lo que impide gastar
        credenciales y una sesión en un APPLY que el gate todavía puede
        bloquear. Es el contrato del propio `GraphWriter`.
        """
        def abrir():
            from app.config import get_settings  # noqa: PLC0415

            try:
                import neo4j  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover - dependencia ausente
                raise ApplyError("GRAPH_UNAVAILABLE", "sin driver neo4j") from exc
            ajustes = get_settings()
            try:
                return neo4j.GraphDatabase.driver(
                    ajustes.S9K_NEO4J_URI,
                    auth=(ajustes.S9K_NEO4J_USER, ajustes.neo4j_password),
                )
            except Exception as exc:  # noqa: BLE001
                raise ApplyError("GRAPH_UNAVAILABLE", type(exc).__name__) from exc

        return abrir
