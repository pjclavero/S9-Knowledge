# -*- coding: utf-8 -*-
"""LA ruta canonica de aplicacion de V3. UNA sola definicion de «aplicar».

EL DEFECTO QUE CIERRA
---------------------
Habia DOS mandos que decian aplicar el mismo plan, y no aplicaban lo mismo.
Un supervisor independiente corrio el MISMO plan con el MISMO esquema por los
dos y midio:

===================  ========  ==========  ============
mando                aristas   V3Source    V3Evidence
===================  ========  ==========  ============
``ingest_cli``            18           1             7
``writer.cli``             0           0             0
===================  ========  ==========  ============

`writer.cli` escribia la asercion con ``evidence_fragment_ids:
["ef-d4b8..."]`` apuntando a un fragmento **que no existia**, sin
``SUPPORTED_BY``, y reportaba ``APPLIED`` sin una sola advertencia. Dejaba
referencias colgantes y lo llamaba exito.

POR QUE NO SE ARREGLA «HACIENDO QUE LOS DOS HAGAN LO MISMO»
-----------------------------------------------------------
Porque no pueden, y esa es la parte estructural del defecto: **la procedencia
NO esta en el plan**. El plan CITA ``evidence_fragment_ids``; los documentos
`SourceAsset` / `SourceEpisode` / `EvidenceFragment` que esos ids nombran viven
en la corrida de ingesta, no en el fichero del plan. Un mando al que solo se le
da ``plan.json`` **no tiene con que** persistir procedencia. Mantener dos
implementaciones «equivalentes» era, literalmente, imposible: una de las dos
iba a mentir siempre.

LO QUE HAY EN SU LUGAR
----------------------
Una sola funcion, `apply_v3`, que es LA definicion de aplicar V3::

        apply_v3   <-- ingest_cli (flujo de operador, CON procedencia)
             ^
             +---- writer.cli   (bajo nivel, SIN procedencia salvo que se
                                 le pase el paquete; y entonces lo DICE)

Las dos rutas llaman aqui. No hay una segunda definicion. Lo que las
distingue ya no es *que hacen*, sino *que se les da*: con paquete de
procedencia el resultado es el producto de extremo a extremo; sin el, la
funcion emite `APPLY_PROVENANCE_NOT_PERSISTED` y **enumera las referencias que
quedan colgando**, en vez de callar.

QUE NO SE RELAJA
----------------
Nada del writer. `apply_v3` no toca el gate, no abre conexiones antes de que
el gate autorice, no acepta secretos, no cambia el defecto dry-run y no altera
la condicion de borrado del rollback. Recibe un `GraphWriter` ya construido por
quien tenga derecho a construirlo y le pide exactamente lo que le pedian antes
las dos rutas por separado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from . import writer as writer_mod
from .apply_identity import compute_apply_id
from .gate import OperatorRequest
from .provenance import persist_provenance
from .rollback import add_provenance_sweep

#: La procedencia NO se persistio porque no se aporto el paquete. No es un
#: fallo del grafo: es una ruta de BAJO NIVEL diciendo lo que no hizo. Codigo
#: estable para que un runner lo distinga sin leer prosa.
CODE_PROVENANCE_NOT_PERSISTED = "APPLY_PROVENANCE_NOT_PERSISTED"

#: El volcado se intento y fallo. El conocimiento YA esta escrito: no se
#: propaga la excepcion (deshacerla no es posible aqui y ocultaria el apply).
CODE_PROVENANCE_FAILED = "APPLY_PROVENANCE_FAILED"

#: Se persistio. Se dice tambien en el caso bueno, para que la ausencia del
#: codigo no sea el unico testigo.
CODE_PROVENANCE_PERSISTED = "APPLY_PROVENANCE_PERSISTED"

#: No se pudo componer una identidad de apply completa: el volcado va SIN
#: marca de propiedad y el radio del barrido cae al antiguo ``scope: "run"``.
CODE_APPLY_ID_UNAVAILABLE = "APPLY_ID_UNAVAILABLE"


@dataclass(frozen=True)
class ProvenanceBundle:
    """Lo que el plan NO lleva dentro y sin lo cual la procedencia no existe.

    Es exactamente el material que la ingesta produce y que el fichero de plan
    no puede contener: los documentos que los ``evidence_fragment_ids`` del
    plan nombran, mas sus episodios y su fuente.
    """

    source_asset: Optional[dict] = None
    episodes: tuple = ()
    fragments: tuple = ()

    @classmethod
    def of(
        cls,
        *,
        source_asset: Optional[dict] = None,
        episodes: Iterable[dict] = (),
        fragments: Iterable[dict] = (),
    ) -> "ProvenanceBundle":
        return cls(
            source_asset=dict(source_asset) if source_asset else None,
            episodes=tuple(dict(e) for e in episodes),
            fragments=tuple(dict(f) for f in fragments),
        )

    @property
    def fragment_ids(self) -> tuple:
        return tuple(
            f.get("fragment_id") for f in self.fragments if f.get("fragment_id")
        )

    def to_dict(self) -> dict:
        return {
            "source_asset": self.source_asset,
            "episodes": [dict(e) for e in self.episodes],
            "fragments": [dict(f) for f in self.fragments],
        }

    @classmethod
    def from_dict(cls, doc: dict) -> "ProvenanceBundle":
        if not isinstance(doc, dict):
            raise ValueError("el paquete de procedencia no es un objeto JSON")
        desconocidos = sorted(set(doc) - {"source_asset", "episodes", "fragments"})
        if desconocidos:
            raise ValueError(
                f"paquete de procedencia con campos desconocidos: {desconocidos}"
            )
        return cls.of(
            source_asset=doc.get("source_asset"),
            episodes=doc.get("episodes") or (),
            fragments=doc.get("fragments") or (),
        )


@dataclass
class ApplyOutcome:
    """El desenlace COMPLETO de aplicar: escritura + procedencia + poliza."""

    write_result: Any = None
    provenance_result: Any = None
    apply_id: Optional[str] = None
    #: Referencias de procedencia que el plan CITA y que este apply no
    #: persistio. No vacio = hay aserciones escritas apuntando a la nada.
    dangling_fragment_ids: tuple = ()
    notes: list = field(default_factory=list)

    def note(self, code: str, detail: str = "") -> None:
        self.notes.append({"code": code, "detail": detail})

    @property
    def codes(self) -> list:
        return [n["code"] for n in self.notes]

    @property
    def rollback(self) -> Any:
        return getattr(self.write_result, "rollback", None)

    def to_dict(self) -> dict:
        return {
            "apply_id": self.apply_id,
            "write": self.write_result.to_dict() if self.write_result else None,
            "provenance": (
                self.provenance_result.to_dict() if self.provenance_result else None
            ),
            "dangling_fragment_ids": list(self.dangling_fragment_ids),
            "notes": [dict(n) for n in self.notes],
        }


# --- lecturas del plan, todas defensivas -----------------------------------
def plan_partida_id(plan_doc: Any) -> Optional[str]:
    """Ambito EFECTIVO del plan: el bloque `scope` manda sobre la raiz.

    Mismo criterio que `SignedView.of`, repetido aqui porque esta funcion
    corre ANTES de que la admision construya el view (hace falta para
    componer el `apply_id`) y porque un plan malformado no debe reventar la
    composicion de la identidad: sin ambito legible, `apply_id` sale `None` y
    el volcado va sin marca, que es el degradado seguro.
    """
    if not isinstance(plan_doc, dict):
        return None
    scope = plan_doc.get("scope")
    if isinstance(scope, dict) and scope.get("partida_id") is not None:
        return scope["partida_id"]
    valor = plan_doc.get("partida_id")
    return valor if isinstance(valor, str) else None


def plan_hash_value(plan_doc: Any) -> str:
    if not isinstance(plan_doc, dict):
        return ""
    h = plan_doc.get("plan_hash")
    return h.get("value", "") if isinstance(h, dict) else ""


def plan_assertion_ids(plan_doc: Any) -> list:
    if not isinstance(plan_doc, dict):
        return []
    ops = plan_doc.get("mutation_operations") or []
    return [
        op["assertion_id"]
        for op in ops
        if isinstance(op, dict) and op.get("assertion_id")
    ]


def plan_cited_fragment_ids(plan_doc: Any) -> list:
    """Los `evidence_fragment_ids` que el plan CITA, sin repetir.

    Es el conjunto que un apply SIN paquete de procedencia deja apuntando a la
    nada. Se enumera para que la advertencia sea comprobable y no una frase.
    """
    vistos: list = []
    if not isinstance(plan_doc, dict):
        return vistos
    for op in plan_doc.get("mutation_operations") or []:
        if not isinstance(op, dict):
            continue
        payload = op.get("payload")
        candidatos = []
        if isinstance(payload, dict):
            candidatos = payload.get("evidence_fragment_ids") or []
        if not candidatos:
            candidatos = op.get("evidence_fragment_ids") or []
        for fid in candidatos:
            if isinstance(fid, str) and fid and fid not in vistos:
                vistos.append(fid)
    return vistos


def logical_plan_identity(plan_doc: Any) -> Optional[str]:
    """`plan_id`: el campo CONTRACTUAL de identidad logica del plan.

    Ver la carencia declarada en `apply_identity`/docs: `plan_id` es el unico
    campo del contrato congelado que nombra la identidad logica del plan y es
    el unico que NO depende del reloj, pero el propio contrato lo declara
    NO FIRMADO (`writer/view.py:UNSIGNED_FIELDS`). Por eso se PUBLICA aqui
    --para que el operador pueda reconocer «el mismo plan» entre ejecuciones--
    y NO se usa para decidir nada. Decidir sobre un campo no firmado seria
    decidir sobre algo manipulable sin romper ningun hash.
    """
    if not isinstance(plan_doc, dict):
        return None
    valor = plan_doc.get("plan_id")
    return valor if isinstance(valor, str) and valor else None


def apply_v3(
    plan_doc: Any,
    request: OperatorRequest,
    *,
    writer: Any,
    provenance: Optional[ProvenanceBundle] = None,
    driver: Any = None,
) -> ApplyOutcome:
    """Aplica un plan V3. **Esta funcion es la definicion de «aplicar V3».**

    Hace, en este orden y por este orden:

    1. Compone la identidad durable del apply (`apply_id`) con lo que
       identifica la DECISION --workspace, ambito, snapshot, plan--, nunca con
       el reloj ni con `elementId`.
    2. Entrega el plan al `GraphWriter`. El gate sigue siendo el suyo: esta
       funcion no lo toca, no lo esquiva y no lo adelanta.
    3. Si el APPLY fue real y hay paquete de procedencia, la persiste en su
       PROPIA transaccion --nunca dentro de la del plan: un fallo de
       procedencia no puede revertir conocimiento ya aceptado--.
    4. Si el APPLY fue real y NO hay paquete, lo DICE y enumera las
       referencias colgantes. No se finge un producto de extremo a extremo.
    5. Amplia el documento de rollback con el barrido de procedencia, acotado
       por `apply_id` cuando lo hay.

    `driver` es el driver ya abierto para el paso 3. Si no se pasa, se toma el
    que el writer resolvio DESPUES del gate (`resolved_driver`): asi la
    conexion sigue sin abrirse antes de que el gate autorice.
    """
    out = ApplyOutcome()

    # 1. Identidad del apply. Sin las tres piezas no se inventa una marca:
    #    una propiedad vacia no distingue nada y autorizaria a borrar de mas.
    try:
        out.apply_id = compute_apply_id(
            workspace=request.workspace,
            snapshot_id=request.current_snapshot_id,
            plan_hash=plan_hash_value(plan_doc),
            partida_id=plan_partida_id(plan_doc),
        )
    except ValueError as exc:
        out.apply_id = None
        out.note(CODE_APPLY_ID_UNAVAILABLE, str(exc))

    # 2. El writer. Su gate, sus reglas, su desenlace.
    result = writer.write(plan_doc, request)
    out.write_result = result

    aplicado = (
        getattr(result, "ok", False)
        and getattr(result, "mode", None) == writer_mod.MODE_APPLY
    )
    if not aplicado:
        return out

    conexion = driver if driver is not None else getattr(writer, "resolved_driver", None)

    # 3/4. La procedencia, o la confesion de que no la hay.
    citados = plan_cited_fragment_ids(plan_doc)
    if provenance is None:
        if citados:
            out.dangling_fragment_ids = tuple(citados)
        out.note(
            CODE_PROVENANCE_NOT_PERSISTED,
            "apply sin paquete de procedencia: el conocimiento queda escrito "
            "y NO navegable. "
            + (
                f"{len(citados)} referencia(s) de evidencia citadas por el plan "
                "apuntan a fragmentos que este apply no ha creado: "
                + ", ".join(citados)
                if citados
                else "el plan no cita ninguna evidencia."
            ),
        )
    elif conexion is None:
        out.note(
            CODE_PROVENANCE_FAILED,
            "hay paquete de procedencia pero ningun driver con el que "
            "persistirlo; el conocimiento queda escrito y sin procedencia",
        )
        out.dangling_fragment_ids = tuple(citados)
    else:
        try:
            out.provenance_result = persist_provenance(
                conexion,
                workspace=request.workspace,
                partida_id=plan_partida_id(plan_doc),
                source_asset=provenance.source_asset,
                episodes=list(provenance.episodes),
                fragments=list(provenance.fragments),
                assertion_ids=plan_assertion_ids(plan_doc),
                apply_id=out.apply_id,
            )
            out.note(CODE_PROVENANCE_PERSISTED, "")
            # Lo que el plan cita y el paquete NO trae sigue colgando. Traer
            # paquete no es lo mismo que traer EL paquete correcto, y la
            # diferencia se mide, no se presume.
            traidos = set(provenance.fragment_ids)
            out.dangling_fragment_ids = tuple(f for f in citados if f not in traidos)
        except Exception as exc:  # noqa: BLE001 - se anota, no se traga
            out.note(CODE_PROVENANCE_FAILED, f"{type(exc).__name__}: {exc}")
            out.dangling_fragment_ids = tuple(citados)

    # 5. El barrido, acotado por la marca de propiedad cuando la hay.
    if out.provenance_result is not None and result.rollback is not None:
        add_provenance_sweep(
            result.rollback,
            workspace=request.workspace,
            partida_id=plan_partida_id(plan_doc),
            fragment_ids=(
                [] if out.apply_id else list(provenance.fragment_ids)
            ),
            apply_id=out.apply_id,
        )
    return out


__all__ = [
    "CODE_APPLY_ID_UNAVAILABLE",
    "CODE_PROVENANCE_FAILED",
    "CODE_PROVENANCE_NOT_PERSISTED",
    "CODE_PROVENANCE_PERSISTED",
    "ApplyOutcome",
    "ProvenanceBundle",
    "apply_v3",
    "logical_plan_identity",
    "plan_assertion_ids",
    "plan_cited_fragment_ids",
    "plan_hash_value",
    "plan_partida_id",
]
