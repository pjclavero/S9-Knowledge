"""Ámbito visible (workspace + partida) para datos que NO vienen del grafo.

``PolicyFilteredProvider`` cubre todo lo que se lee a través de un
``GraphProvider``. Pero el visor sirve además material que vive fuera de Neo4j:

  - los documentos de contrato del panel de revisión v1 (``/review-console``),
  - las propuestas/candidatos de glosario del panel V3 (``/v3/review``),
  - la cola de trabajos del data-engine (``/jobs``, ``/api/jobs``).

Todo eso es material de una partida concreta (o de la capa juego compartida) y
debe respetar EL MISMO aislamiento. Este módulo es el punto único donde ese
material se contrasta con la política: no reimplementa reglas, delega en
``VisibilityPolicy.can_view`` normalizando cada registro a las dos barreras que
nunca se saltan (regla 2 workspace, regla 2b partida). Así el criterio vive en
un solo sitio y no en un ``if`` por ruta.

Deny-by-default: si un registro no declara workspace se considera capa juego
del workspace permitido (visible), pero si declara uno ajeno o una partida que
no es la activa, no se entrega — ni en listados, ni en conteos, ni por ID.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, TypeVar

from app.authz.context import build_internal_context
from app.policies.engine import POLICY, VisibilityPolicy
from app.policies.models import PLAYER, ViewerContext

T = TypeVar("T", bound=Mapping[str, Any])

# Lugares donde un documento puede declarar su partida, en orden de prioridad.
# El primero que exista manda; ninguno = capa juego (lore compartido).
_PARTIDA_PATHS: tuple[tuple[str, ...], ...] = (
    ("partida_id",),
    # Los contratos review-ingest v1 son cerrados (additionalProperties: false)
    # salvo `metadata`: ahí es donde un documento v1 declara su partida.
    ("metadata", "partida_id"),
    ("scope", "partida_id"),
    ("provenance", "partida_id"),
    ("payload", "partida_id"),
)
_WORKSPACE_PATHS: tuple[tuple[str, ...], ...] = (
    ("workspace",),
    ("scope", "workspace"),
    ("payload", "workspace"),
)


def _dig(record: Mapping[str, Any], path: Sequence[str]) -> Any:
    cur: Any = record
    for key in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _first(record: Mapping[str, Any], paths: Iterable[Sequence[str]]) -> Optional[str]:
    for path in paths:
        value = _dig(record, path)
        if value is not None:
            return value if isinstance(value, str) else str(value)
    return None


@dataclass(frozen=True)
class VisibilityScope:
    """Ámbito visible de la petición aplicado a registros arbitrarios.

    Se construye desde el mismo ``ViewerContext`` que usa el provider filtrado,
    de modo que un admin (``admin_full``) ve lo mismo en ambos caminos y un
    usuario con partida activa ve, en ambos, su partida más la capa juego.
    """

    ctx: ViewerContext
    policy: VisibilityPolicy = POLICY
    #: Si el `workspace` del registro es comparable con los workspaces del
    #: visor. Es cierto para los datos operativos de este despliegue (cola de
    #: jobs) y, desde B1 (H-03), para las propuestas V3 (ver
    #: `para_corpus_de_revision`). Sigue sin serlo para los contratos de
    #: revisión v1 (`/review-console`, laboratorio), cuyo `workspace` es una
    #: etiqueta del corpus: allí la barrera aplicable es la de partida.
    enforce_workspace: bool = True
    #: Si un registro SIN workspace declarado se deniega en vez de leerse como
    #: «capa juego del workspace permitido». Sólo lo activa
    #: `para_corpus_de_revision`: el resto de consumidores no cambia.
    workspace_obligatorio: bool = False

    def partida_only(self) -> "VisibilityScope":
        """Mismo ámbito, sin comparar workspaces ajenos al modelo del visor."""
        return VisibilityScope(self.ctx, self.policy, enforce_workspace=False)

    def para_corpus_de_revision(self) -> "VisibilityScope":
        """Ámbito de la revisión V3: workspace COMPARADO y OBLIGATORIO + partida.

        B1 (USABLE-V1) · H-03. La revisión V3 se acotaba con `partida_only()`
        (M5a, `f6a4f18`, 2026-08-06) porque entonces el `workspace` de una
        propuesta se tenía por «etiqueta del corpus de laboratorio». Desde F-2
        (#244) eso es falso: el perfil de la bóveda es la AUTORIDAD CANÓNICA
        del workspace (`autoridad_workspace`), y el MISMO valor viaja perfil ->
        ámbito de la fuente -> paquete de propuestas -> `/v3/review` -> apply
        -> writer. Con la comparación apagada, un revisor con concesión sólo en
        `leyenda` veía y APROBABA propuestas de `bench-dev` eligiendo el
        `workspace` del formulario.

        EQUIVALENCIA DECLARADA (único sitio): el `workspace` de una propuesta
        V3, de su decisión humana y de su candidato de glosario ES el
        identificador canónico del workspace, y se compara por IGUALDAD
        literal con `ctx.allowed_workspaces`. No hay tabla de alias: si algún
        día la etiqueta del corpus y el workspace canónico divergen, la
        traducción vive AQUÍ, no en una ruta.

        FAIL-CLOSED: un registro de revisión sin workspace (o en blanco) se
        deniega; no es «capa juego». `admin_full` sigue viéndolo todo. La
        barrera de partida (docs/81, lore anónimo denegado) se conserva tal
        cual: este método AÑADE la de workspace, no sustituye nada.

        Se construye desde el contexto, no desde `self`: un ámbito que llegue
        ya relajado (`partida_only()`) NO relaja la revisión.
        """
        return VisibilityScope(
            self.ctx, self.policy, enforce_workspace=True, workspace_obligatorio=True
        )

    # -- decisiones elementales ------------------------------------------------
    def allows_workspace(self, workspace: Optional[str]) -> bool:
        if self.ctx.admin_full or not self.enforce_workspace:
            return True
        if workspace is None or (isinstance(workspace, str) and not workspace.strip()):
            return not self.workspace_obligatorio
        return workspace in self.ctx.allowed_workspaces

    #: Estas funciones no preguntan "¿puede verse este contenido?" sino "¿cae
    #: esto dentro de mi ámbito?". Hasta M5c lo resolvían fabricando un nodo
    #: sintético y pasándolo por `can_view`, lo que obligó a que la sonda
    #: declarase una visibilidad propia (`player`) para no denegarse a sí misma.
    #: Funcionaba, pero mantenía viva la confusión de fondo: un objeto que no es
    #: contenido recorriendo el evaluador de contenido.
    #:
    #: Ahora se pregunta directamente por la dimensión de ámbito
    #: (`POLICY.partida_in_scope`). No queda ningún nodo sintético que alguien
    #: pueda volver a pasar al evaluador de contenido, ni ninguna visibilidad
    #: de conveniencia que otro objeto pudiera imitar.
    def allows_partida(self, partida_id: Optional[str]) -> bool:
        return self.policy.partida_in_scope(partida_id, self.ctx)

    def allows(self, record: Mapping[str, Any]) -> bool:
        """True si el registro pertenece al ámbito visible (workspace+partida)."""
        if not self.allows_workspace(_first(record, _WORKSPACE_PATHS)):
            return False
        return self.allows_partida(_first(record, _PARTIDA_PATHS))

    # -- helpers de conjunto ---------------------------------------------------
    def filter(self, records: Iterable[T]) -> list[T]:
        return [r for r in records if self.allows(r)]

    def filter_workspaces(self, workspaces: Iterable[str]) -> list[str]:
        return [w for w in workspaces if self.allows_workspace(w)]

    # -- recorte de detalle ----------------------------------------------------
    @property
    def sees_operational_detail(self) -> bool:
        """Solo admin ve el detalle operativo (rutas de fichero, payloads).

        Un revisor necesita saber QUÉ hay en cola de su ámbito, no dónde vive el
        fichero en el disco del servidor.

        P0-AUTH: aquí vivía ``or self.ctx.role == "admin"``, una SEGUNDA vía a
        la misma potestad de bypass total, evaluada de nuevo fuera del
        constructor de contexto. Que el rol conceda es correcto; que lo conceda
        DOS VECES, en dos sitios, no lo es: el día que se revoque el bypass en
        el constructor, esta línea lo seguiría concediendo, y la revocación
        habría quedado incompleta sin que nada se pusiera rojo. El rol es
        ENTRADA del constructor; el resultado del constructor es ``admin_full``,
        y esa es la única forma de la potestad que se lee aguas abajo.
        """
        return bool(self.ctx.admin_full)


#: Ámbito sin restricciones, para llamadores internos/programáticos (CLI, tests
#: de servicio) que no representan a un usuario del visor.
#:
#: P0-AUTH: era `VisibilityScope(ViewerContext(role="admin", admin_full=True))`,
#: es decir un contexto de potestad total FABRICADO A MANO, esquivando el
#: productor. Ahora se pide al productor, como cualquier otro.
UNRESTRICTED = VisibilityScope(
    build_internal_context(motivo="llamador interno sin usuario (CLI/servicios)")
)
