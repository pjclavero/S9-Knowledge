"""M5b-0 — frontera UNICA entre el contrato canonico `knowledge-visibility/v1`
(``contracts/knowledge-visibility/v1/model.py``) y el motor de politica YA
implementado y probado (``app.policies.engine.VisibilityPolicy``).

``V3VisibilityPolicyAdapter`` traduce ESTRUCTURA, no significado: no
reinterpreta ``visibility``/``known_by``, solo los coloca en la forma de dict
que ``VisibilityPolicy.can_view`` ya sabe leer (``node['visibility']``,
``node['known_by']``), igual que hoy hace cualquier nodo del grafo. El motor
(``viewer/app/policies/engine.py``) NO se toca.

Caso especial obligatorio: ``deny``. El motor actual (`player | narrator |
secret | reference`, ver ``app.policies.models.ALL_LEVELS``) no conoce este
valor -- es NUEVO en el contrato, no en el motor. Si se dejara pasar como
``node['visibility'] = 'deny'`` al motor, la regla 1 (``admin_full`` ->
bypass total) lo haria visible para cualquier admin, violando la decision del
operador ("deny es absoluto: ni admin, ni narrador, ni can_view_secret lo
saltan"). Por eso este adaptador intercepta ``deny`` ANTES de invocar al
motor, incondicionalmente, sin excepcion alguna -- ni siquiera para
``admin_full``.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.policies.engine import VisibilityPolicy, POLICY
from app.policies.models import VisibilityDecision, ViewerContext

# --- Carga del modulo ligero del contrato, por ruta relativa al repo -------
# Mismo patron que data-engine/app/knowledge_v3/contracts/base.py: se carga
# por ruta de fichero, nunca por un paquete instalado, para que el contrato
# siga viviendo fuera de cualquier arbol de paquetes de app (viewer o
# data-engine) y ambos lo compartan sin duplicarlo.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTRACT_DIR = _REPO_ROOT / "contracts" / "knowledge-visibility" / "v1"
_MODEL_PATH = _CONTRACT_DIR / "model.py"

_MODULE_NAME = "s9k_knowledge_visibility_v1_model"
if _MODULE_NAME in sys.modules:  # pragma: no cover - cache entre imports
    kv_model = sys.modules[_MODULE_NAME]
else:
    _spec = importlib.util.spec_from_file_location(_MODULE_NAME, _MODEL_PATH)
    if _spec is None or _spec.loader is None:  # pragma: no cover
        raise ImportError(f"no se pudo cargar el contrato knowledge-visibility/v1 en {_MODEL_PATH}")
    kv_model = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = kv_model
    _spec.loader.exec_module(kv_model)

KnowledgeVisibilityV1 = kv_model.KnowledgeVisibilityV1
VisibilityLevel = kv_model.VisibilityLevel

_DENY = VisibilityDecision(False, "deny_absolute")


@dataclass(frozen=True)
class V3VisibilityPolicyAdapter:
    """Traduce ``KnowledgeVisibilityV1`` + contexto de peticion (``ViewerContext``)
    a la decision del motor probado, sin cambiar su comportamiento.

    ``extra_node_fields`` cubre las dimensiones del motor que NO forman parte
    del contrato persistido (``party``, ``session_index``, ``is_public``,
    ``workspace``, ``partida_id``...): siguen siendo responsabilidad de quien
    construye el nodo del grafo, exactamente igual que hoy. Este adaptador
    solo anade las DOS claves que M5b-0 estandariza (``visibility``,
    ``known_by``); no inventa las demas.
    """

    policy: VisibilityPolicy = POLICY

    def to_engine_node(
        self,
        contract: "KnowledgeVisibilityV1",
        extra_node_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Construye el dict de nodo que ``VisibilityPolicy.can_view`` espera.

        Estructura, no significado: ``contract.visibility.value`` va tal cual
        a ``node['visibility']``, ``contract.known_by`` tal cual a
        ``node['known_by']`` (el motor ya sabe leer ambas claves, ver
        ``ViewerContext.knows`` y regla 3 de ``VisibilityPolicy.can_view``).
        """
        node: dict[str, Any] = dict(extra_node_fields or {})
        node["visibility"] = contract.visibility.value
        node["known_by"] = list(contract.known_by)
        return node

    def can_view(
        self,
        contract: "KnowledgeVisibilityV1",
        ctx: ViewerContext,
        extra_node_fields: dict[str, Any] | None = None,
    ) -> VisibilityDecision:
        """Decision final para un hecho `knowledge-visibility/v1`.

        `deny` es absoluto: se decide AQUI, sin invocar al motor, para que
        ningun bypass del motor (admin_full, can_view_secret...) pueda
        alcanzarlo. Para cualquier otro valor, la decision es exactamente la
        que ya tomaria el motor sobre el nodo equivalente -- ninguna regla
        nueva, ninguna reinterpretacion.
        """
        if contract.visibility is VisibilityLevel.DENY:
            return _DENY
        node = self.to_engine_node(contract, extra_node_fields)
        return self.policy.can_view(node, ctx)


#: Instancia compartida sin estado (misma convencion que `POLICY` en
#: `app.policies.engine`).
ADAPTER = V3VisibilityPolicyAdapter()
