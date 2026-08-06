# Contrato `knowledge-visibility/v1` (M5b-0)

Vocabulario CANONICO, unico y persistido de visibilidad de conocimiento por
personaje ("niebla de guerra"). Ver `docs/v3/51-m5b0-knowledge-visibility-contrato.md`
(ADR) para la decision completa y `docs/v3/49-multipartida-diseno.md` para el
programa multipartida en el que se enmarca.

## Que es y que NO es

Este contrato extrae la semantica YA implementada y probada en
`viewer/app/policies/{models,engine}.py` (campos `visibility` y `known_by`
que el motor ya lee) a un modulo compartido, ligero, versionado. **No inventa
significado nuevo.** Se descarta explicitamente el vocabulario propuesto en
`docs/v3/50-m5b-niebla-de-guerra-diseno.md` (rama sin mergear
`feat/m5b-fog-of-war-design`, PR #146): `known_by_scope` /
`visibility_scope` / `visibility_subjects` no tienen autoridad y no se
implementan.

## Campos

| Campo | Tipo | Persistido / contexto |
|---|---|---|
| `visibility` | enum cerrado `player \| narrator \| secret \| reference \| deny` | **persistido** |
| `known_by` | lista cerrada de `character_id` | **persistido** |
| `claim_id`, `assertion_id`, `plan_id`, `state_hash` | IDs/hash opcionales | enlace a V3 (ver abajo) |
| `metadata` | objeto libre | auditoria, nunca consumido para decidir |

**Fuera de este contrato a proposito** (viven en el contexto de peticion,
`viewer/app/policies/models.py::ViewerContext`): `party_membership`,
`active_character`, `max_visible_session`, `can_view_secret`. Estos NO se
persisten junto al hecho — el motor los combina con `visibility`/`known_by`
en tiempo de peticion.

`deny` es un estado terminal NUEVO en el contrato, ausente hoy del motor
(`app.policies.models.ALL_LEVELS` solo tiene `player|narrator|secret|reference`).
Es absoluto: ni admin, ni narrador, ni `can_view_secret` lo saltan. El
adaptador (`viewer/app/authz/visibility_contract.py`) lo intercepta ANTES de
invocar al motor — el motor en si NO se modifica.

## Correspondencia con la familia `v3-internal-v1` (contrato ADYACENTE)

`knowledge-visibility/v1` es un contrato nuevo e independiente — **ningun**
schema de `contracts/knowledge-v3/v1/` se toca. Se enlaza a esa familia por
IDs de referencia:

| Campo aqui | Campo real en V3 | Fichero |
|---|---|---|
| `claim_id` | `claim_id` | `contracts/knowledge-v3/v1/claim-proposal-v3.schema.json` |
| `assertion_id` | `assertion_id` | `contracts/knowledge-v3/v1/fact-assertion-v3.schema.json` |
| `plan_id` | `plan_id` | `contracts/knowledge-v3/v1/graph-mutation-plan-v3.schema.json` |
| `state_hash` | **sin correspondencia exacta** — el campo mas proximo es `decision_hash` | `contracts/knowledge-v3/v1/graph-mutation-plan-v3.schema.json` (`validator.py::DECISION_HASH_FIELDS`) |

Discrepancia honesta: no existe en la familia V3 un campo llamado
literalmente `state_hash`. El encargo pidio ese nombre explicitamente para el
enlace; se mantiene aqui bajo ese nombre y se documenta que un consumidor que
quiera verificarlo debe comparar contra `decision_hash` del
`graph-mutation-plan/v3-internal-v1` referenciado por `plan_id` — es el hash
que cubre el CUERPO DE DECISION del plan sellado (no `plan_hash`, que cubre
el documento entero incluyendo metadatos no decisorios, explicitamente fuera
de cualquier decision de escritura segun el propio schema V3).

## Ficheros

- `knowledge-visibility-v1.schema.json` — JSON Schema, fuente de verdad
  estructural.
- `model.py` — modelo Python ligero (`dataclasses`/`enum`/`re`, sin
  `pydantic_settings` ni nada de `viewer.app`). Importable de forma aislada
  (ver `data-engine/app/tests/test_knowledge_visibility_contract_import_ligero.py`).
- `examples/valid/`, `examples/invalid/` — fixtures congeladas, generadas por
  `tests/generate_examples.py` desde `tests/kv_fixtures.py`. No se editan a
  mano.
- `tests/test_contracts_knowledge_visibility.py` — valida que disco == lo
  generado y que cada ejemplo valido/invalido se comporta como se espera.

## Frontera de uso: `V3VisibilityPolicyAdapter`

`viewer/app/authz/visibility_contract.py` es el UNICO punto donde este
contrato se traduce a llamadas del motor probado
(`app.policies.engine.VisibilityPolicy`). La traduccion es de estructura, no
de significado: `visibility`/`known_by` van tal cual a
`node['visibility']`/`node['known_by']`, las demas dimensiones del motor
(`party`, `session_index`, `workspace`, `partida_id`...) siguen siendo
responsabilidad de quien construye el nodo, exactamente igual que hoy.

## Huecos dejados abiertos a proposito (sub-bloques futuros, NO implementados aqui)

- La presencia en un episodio no concede conocimiento por si sola — solo
  puede producir en el futuro un `KNOWLEDGE_GRANT_CANDIDATE`.
- La IA solo podra PROPONER (`PROPOSED_KNOWLEDGE_GRANT`), nunca escribir
  `known_by` directamente.
- `local_override_of` (M4) nunca amplia visibilidad: gana siempre la politica
  mas restrictiva entre original y override.
- `known_by` esta pensado para acabar siendo una proyeccion materializada de
  un futuro ledger `knowledge_grant` (con `character_access` decidiendo quien
  controla que personaje) — el contrato no impide esa evolucion porque
  `known_by` es, deliberadamente, solo una lista cerrada de IDs sin logica de
  derivacion embebida.
