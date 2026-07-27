# -*- coding: utf-8 -*-
"""Capa de proveedores de S9-Knowledge V3.

Un proveedor **propone**. Nunca aprueba, nunca firma, nunca escribe (prompt
maestro §2). Este paquete existe para que esa frase sea una propiedad del
codigo y no una nota en un documento:

* `router.ProviderRouter` es la unica puerta de entrada, y su salida es un
  `ProviderOutcome` — un resultado etiquetado, jamas una decision.
* `proposals` solo sabe construir tres contratos: `EvidenceFragment`,
  `EntityMention` y `ClaimProposal`. No hay ninguna funcion en este paquete
  capaz de devolver un `GraphMutationPlan`.
* `guards.assert_not_a_decision` rechaza cualquier respuesta de proveedor que
  traiga campos de decision o de firma, incluso bien formados.

Reutiliza sin duplicar: el dispatcher, el circuit breaker, las capacidades y el
validador de resultados viven en `external_processing/` desde la fase B1 y aqui
se envuelven, no se reescriben.
"""
from __future__ import annotations

from knowledge_v3.providers.capability import (  # noqa: F401
    PROPOSAL_CAPABILITIES,
    TO_PROVIDER_CAPABILITY,
    TO_TASK_TYPE,
    V3Capability,
    to_provider_capability,
    to_task_type,
)
from knowledge_v3.providers.guards import (  # noqa: F401
    FORBIDDEN_CONTRACT_IDS,
    FORBIDDEN_KEYS,
    ForbiddenContractError,
    GuardError,
    assert_not_a_decision,
    assert_size,
    guard_provider_result,
    parse_strict_object,
    scan_injection,
)
from knowledge_v3.providers.policy import (  # noqa: F401
    TIER_ORDER,
    Budget,
    RoutingDecision,
    RoutingError,
    RoutingPolicy,
    Tier,
)
from knowledge_v3.providers.proposals import (  # noqa: F401
    ALLOWED_ENTITY_TYPES,
    LocalAnchor,
    ProposalError,
    ProviderAttribution,
    claims_from_extraction,
    evidence_fragment_from_text,
    mentions_from_extraction,
    normalize_text,
)
from knowledge_v3.providers.router import (  # noqa: F401
    ProviderOutcome,
    ProviderRouter,
    RegisteredProvider,
    default_router,
)

__all__ = [
    "ALLOWED_ENTITY_TYPES",
    "Budget",
    "FORBIDDEN_CONTRACT_IDS",
    "FORBIDDEN_KEYS",
    "ForbiddenContractError",
    "GuardError",
    "LocalAnchor",
    "PROPOSAL_CAPABILITIES",
    "ProposalError",
    "ProviderAttribution",
    "ProviderOutcome",
    "ProviderRouter",
    "RegisteredProvider",
    "RoutingDecision",
    "RoutingError",
    "RoutingPolicy",
    "TIER_ORDER",
    "TO_PROVIDER_CAPABILITY",
    "TO_TASK_TYPE",
    "Tier",
    "V3Capability",
    "assert_not_a_decision",
    "assert_size",
    "claims_from_extraction",
    "default_router",
    "evidence_fragment_from_text",
    "guard_provider_result",
    "mentions_from_extraction",
    "normalize_text",
    "parse_strict_object",
    "scan_injection",
    "to_provider_capability",
    "to_task_type",
]
