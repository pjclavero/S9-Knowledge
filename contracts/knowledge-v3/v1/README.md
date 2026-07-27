# Contratos internos S9-Knowledge V3 — familia `v3-internal-v1`

Nueve contratos, un envelope comun, un validador. Mismo patron que
`contracts/review-ingest/v1/`: los `.schema.json` son la fuente de verdad
estructural y `validator.py` anade lo que JSON Schema no puede expresar.

| Fichero | Contrato |
|---|---|
| `_common-v3.schema.json` | envelope, enums, hashes, `provider_trace`, bbox |
| `source-asset-v3.schema.json` | `source-asset/v3-internal-v1` |
| `source-episode-v3.schema.json` | `source-episode/v3-internal-v1` |
| `evidence-fragment-v3.schema.json` | `evidence-fragment/v3-internal-v1` |
| `entity-mention-v3.schema.json` | `entity-mention/v3-internal-v1` |
| `claim-proposal-v3.schema.json` | `claim-proposal/v3-internal-v1` |
| `entity-resolution-v3.schema.json` | `entity-resolution/v3-internal-v1` |
| `fact-assertion-v3.schema.json` | `fact-assertion/v3-internal-v1` |
| `graph-mutation-plan-v3.schema.json` | `graph-mutation-plan/v3-internal-v1` |
| `game-profile-v3.schema.json` | `game-profile/v3-internal-v1` |

## Uso

```python
import validator as V              # desde este directorio
V.validate_document(doc)           # lanza V.ContractV3Error
plan = V.seal_plan(plan)           # calcula decision_hash y plan_hash
```

Desde el motor, mejor por los modelos Python:

```python
from knowledge_v3.contracts import ClaimProposal, GraphMutationPlan, parse_document
```

## Ejemplos

`examples/valid/` y `examples/invalid/` **se generan**, no se editan a mano:

```bash
python contracts/knowledge-v3/v1/tests/generate_examples.py
```

`tests/test_contracts_v3.py` comprueba que lo que hay en disco coincide byte a
byte con lo que producen las fixtures. Cada ejemplo invalido es **una** mutacion
documentada sobre uno valido: si la regla se relaja, el ejemplo pasa a aceptarse
y el gate se pone rojo.

## Lo que NO esta aqui

`relation-candidate/internal-v1` vive en `data-engine/app/relations/contracts.py`
y **no se toca**. El puente es
`data-engine/app/knowledge_v3/adapters/relation_candidate_v1.py`.

Documentacion completa: `docs/v3/01-contracts-v3.md`.
