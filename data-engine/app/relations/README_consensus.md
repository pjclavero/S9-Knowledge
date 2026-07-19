# Consenso de relaciones (`relation-consensus/v1`)

`relations/consensus_adapter.py` COMBINA las fuentes del pipeline de relaciones
sobre un unico candidato y emite un estado de consenso, **reutilizando** la
taxonomia canonica de `external_ai/models.py` sin crear un segundo sistema de
estados.

## Decision arquitectonica: reutilizar vs. adaptar

El motor canonico `external_ai/consensus.py::compute_consensus` **no se reescribe
ni se duplica**. Sin embargo, no puede representar directamente el consenso de
relaciones porque esta especializado en otro caso:

| Necesidad de relaciones | `external_ai.consensus.compute_consensus` |
|---|---|
| Fuentes heterogeneas y de distinto peso (senales R2, sintaxis R3, LLM local R5, IA externa R6) | Exactamente **dos** revisores homogeneos (`ModelReviewResponse`) |
| Vocabulario propio (propose/reject/human sobre relaciones) | Decisiones de **entidad** (accept/edit/use_existing/reject/uncertain) + canonical_name |
| "Proveedor **ausente**" != "voto **negativo**" | La ausencia de decision se trata como `INVALID_RESPONSES` |
| Invalidar **mezcla de workspaces** | No conoce `workspace` |
| Preservar **negacion / temporalidad / estado epistemico** | No modela esos campos |

Conclusion: se crea una **capa especifica (adaptador)** que **delega los estados
comunes** en `external_ai.models` y **no define estados paralelos equivalentes**.

## Estados reutilizados (sin paralelos)

Se importan tal cual de `external_ai.models.CONSENSUS_STATES`:

- `STRONG_CONSENSUS` — dos proveedores presentes, misma polaridad, evidencia y
  estructura plenas.
- `PARTIAL_CONSENSUS` — corroboracion parcial (un solo proveedor presente, o
  ambos coinciden sin soporte pleno, o solo heuristicas fuertes).
- `MODEL_CONFLICT` — polaridades opuestas o contradiccion (negacion/epistemico).
- `INVALID_RESPONSES` — workspace mezclado, contrato invalido, evidencia
  inexistente o proveedor presente invalido.
- `HUMAN_REQUIRED` — tipos incompatibles, todos abstienen o soporte insuficiente.

La **recomendacion** (`propose` / `reject` / `human`) **nunca** aprueba, escribe
ni aplica. `AUTO_APPROVED`/`APPROVED`/`WRITE`/`APPLY` estan prohibidos por un
guard en `RelationConsensus.__post_init__`.

## Politica garantizada (y verificada por tests)

- **Candidato inmutable**: se valida y lee sobre una **copia**; el original nunca
  se muta (se comprueba con una huella JSON antes/despues).
- **Determinista** e **independiente del orden** de las senales de entrada
  (mapa de senales agrupado y campos de salida ordenados).
- **Ausente != rechazo**: un proveedor `None` es abstencion, no un voto negativo.
- **Diferencia** proveedor ausente de voto negativo, y de proveedor presente
  invalido.
- **Penaliza** la evidencia inexistente (invalida el candidato heuristico).
- **Invalida** la mezcla de workspaces.
- **Preserva** negacion, temporalidad y estado epistemico del candidato.
- **Sin red, sin Neo4j, sin escritura, sin LLM.**

## Entradas / salida

```python
from relations.consensus_adapter import compute_relation_consensus

res = compute_relation_consensus(
    candidate,            # RelationCandidate (o dict) — INMUTABLE
    signals=signals,      # R2: senales heuristicas (evidencia, no decisiones)
    syntax=syntax,        # R3: analisis sintactico opcional (estructura)
    local=local_reco,     # R5: recomendacion LLM local opcional
    external=ext_reco,    # R6: recomendacion IA externa opcional
)
res.state           # uno de CONSENSUS_STATES (reutilizado)
res.recommendation  # propose | reject | human (jamas aprueba)
```

## Matriz de mutaciones (6/6)

Cada mutacion rompe al menos un test de `tests/test_relation_consensus.py`:

1. permitir workspace mezclado -> `test_workspace_mismatch_invalidates`.
2. ignorar negacion -> `test_negation_is_preserved` / `test_contradictory_evidence_conflict`.
3. ignorar evidencia -> `test_missing_evidence_penalized`.
4. proveedor ausente == rechazo -> `test_one_provider_absent_is_not_rejection`.
5. permitir autoaprobacion -> `test_recommendation_never_approves` / `test_recommendation_guard_blocks_approval`.
6. resultado dependiente del orden -> `test_signal_order_independence`.
