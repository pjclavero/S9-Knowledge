# 51 — ADR: M5b-0, contrato canónico `knowledge-visibility/v1`

Estado: **IMPLEMENTADO** (solo contrato y frontera; sin cambio de
comportamiento en el visor). Autor: AGENTE-IMPLEMENTADOR (sub-bloque M5b-0).
Base: `main` (`fb4a6fe`, tras M5a). Referencias obligatorias:
`docs/v3/49-multipartida-diseno.md` (programa multipartida) y
`docs/v3/50-m5b-niebla-de-guerra-diseno.md` (diseño previo, rama
`feat/m5b-fog-of-war-design`, PR #146, **sin mergear**, referenciado aquí
solo para documentar por qué su vocabulario se descarta).

---

## 1. Contexto

M5a (mergeado) resuelve **a qué partida se puede entrar**. M5b resuelve un
problema posterior: dentro de una partida ya concedida, un personaje no debe
ver conocimiento que su personaje nunca presenció ("niebla de guerra"). M5b
se divide en sub-bloques; **M5b-0 es solo el contrato canónico y la frontera
compartida** — ningún cambio de comportamiento todavía en el visor.

`docs/v3/50` (diseño previo, no mergeado) propuso un vocabulario de tres
campos: `known_by_scope` (8 valores), `visibility_scope` (6 valores),
`visibility_subjects`. El operador **descarta explícitamente** ese
vocabulario para M5b-0: no tiene autoridad, no se implementa, y este ADR dice
por qué se elige un camino distinto.

## 2. Decisión

**Se parte del modelo YA implementado y probado** en
`viewer/app/policies/{models,engine.py}` en vez de construir el vocabulario
`docs/v3/50` desde cero. Motivo: ese motor existe, está probado
(`viewer/tests/test_visibility_policy.py`, 15 tests verdes antes de este
sub-bloque) y ya sabe leer `node['visibility']` / `node['known_by']` — el
vocabulario de `docs/v3/50` habría exigido reescribir un motor nuevo con una
semántica de 8×6 combinaciones jamás ejercitada en producción, duplicando
lógica que ya funciona.

El contrato resultante se llama **`KnowledgeVisibilityV1`**
(`contracts/knowledge-visibility/v1/`):

- `visibility`: enum cerrado `player | narrator | secret | reference | deny`.
  Los primeros cuatro son exactamente los que ya usa el motor
  (`app.policies.models.ALL_LEVELS`). `deny` es un estado terminal **nuevo**,
  explícito, que el motor no conocía — ver §3.
- `known_by`: lista cerrada de `character_id`, mismo campo que
  `ViewerContext.knows()` ya lee de cada nodo (`node.get("known_by")`).

**Fuera del contrato persistido, a propósito**: `party_membership`,
`active_character`, `max_visible_session`, `can_view_secret`. Son contexto de
petición (`ViewerContext`), nunca se escriben junto al hecho. El motor de
políticas los combina con el contrato en tiempo de petición para decidir.

## 3. `deny`: nuevo en el contrato, no en el motor

Se comprobó el motor actual antes de decidir dónde vive `deny`:
`app.policies.models.ALL_LEVELS = (PLAYER, NARRATOR, SECRET, REFERENCE)` —
`deny` **no existe** ahí. Añadirlo al motor habría significado tocar
`policies/engine.py`, lo que el encargo prohíbe salvo necesidad estricta. No
hay necesidad estricta: `deny` se resuelve enteramente en la frontera
(`V3VisibilityPolicyAdapter.can_view`, `viewer/app/authz/visibility_contract.py`),
que lo intercepta **antes** de construir el nodo que se pasaría al motor. Así:

- El motor (`policies/engine.py`) queda **intacto**, cero líneas tocadas.
- `deny` es absoluto: el adaptador lo decide sin invocar `can_view`, así que
  ningún bypass del motor (`admin_full`, `can_view_secret`, conocimiento de
  personaje vía `known_by`) puede alcanzarlo — verificado en
  `viewer/tests/test_visibility_contract_adapter.py`
  (`test_deny_no_visible_para_admin_full`,
  `test_deny_no_visible_pese_a_can_view_secret`,
  `test_deny_no_visible_pese_a_known_by_del_personaje_activo`).

## 4. Un solo vocabulario persistido, ligero

`contracts/knowledge-visibility/v1/model.py` es un módulo con **cero**
dependencias fuera de la librería estándar (`dataclasses`, `enum`, `re`,
`json`) más `jsonschema`/`referencing` (ya compartidas por motor y visor:
las usa `contracts/knowledge-v3/v1/validator.py`). No importa
`pydantic_settings` ni nada de `viewer.app`. Se demuestra con
`data-engine/app/tests/test_knowledge_visibility_contract_import_ligero.py`,
que replica el patrón de
`data-engine/app/tests/test_authz_scope_import_ligero.py` (M5a): un
intérprete aparte, con `pydantic_settings` y `app`/`app.*` bloqueados vía
`sys.meta_path`, importa el módulo y construye/valida un documento —
repetir la dependencia pesada fue exactamente el fallo que rompió CI en
M5a, y este test existe para que no se repita aquí.

El visor conserva su motor actual **intacto** y recibe el contrato por una
frontera única: `KnowledgeVisibilityV1` → `V3VisibilityPolicyAdapter` →
`VisibilityPolicy.can_view` (motor probado). La traducción
(`V3VisibilityPolicyAdapter.to_engine_node`) es de **estructura**, no de
significado: copia `visibility.value` y `known_by` tal cual a las claves que
el motor ya sabe leer.

## 5. Contrato adyacente, no modificación de lo congelado

Se eligió la opción "contrato ADYACENTE": `KnowledgeVisibilityV1` es un
contrato nuevo e independiente, en `contracts/knowledge-visibility/v1/`,
**sin tocar ningún** `.schema.json` de `contracts/knowledge-v3/v1/`. Se enlaza
a la cadena V3 por `claim_id` / `assertion_id` / `plan_id` / `state_hash`.

Verificado contra los schemas reales (no asumido): los tres primeros existen
tal cual (`claim-proposal-v3.schema.json#/properties/claim_id`,
`fact-assertion-v3.schema.json#/properties/assertion_id`,
`graph-mutation-plan-v3.schema.json#/properties/plan_id`). **`state_hash` no
existe literalmente** en la familia `v3-internal-v1`: el campo más próximo en
significado es `decision_hash` (el hash del *cuerpo de decisión* del plan
sellado, `validator.py::DECISION_HASH_FIELDS`), no `plan_hash` (cubre el
documento entero, incluidos metadatos explícitamente fuera de cualquier
decisión de escritura según el propio schema V3). Se documenta esta
discrepancia en vez de inventar un campo inexistente o silenciarla — ver
`contracts/knowledge-visibility/v1/README.md`, sección de correspondencia.

## 6. Character ID

Reutiliza el mismo patrón que `stable_id` en
`contracts/knowledge-v3/v1/_common-v3.schema.json`
(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$`), repetido en vez de importado (el
contrato de visibilidad no depende de la familia V3 para poder validarse de
forma aislada — ver §4). No lleva prefijo: a diferencia de `partida:<id>` o
del `faction:<id>` propuesto en `docs/v3/50`, este contrato **no modela
facciones**; `known_by` es exclusivamente personajes.

## 7. Tabla de decisión y fixtures

`viewer/tests/test_visibility_contract_adapter.py::test_tabla_de_decision`
cruza `visibility` × rol (`admin`/`viewer`/`anonymous`) × personaje activo ×
`party` × `known_by` × `max_visible_session` × `can_view_secret` ×
workspace/partida en 23 casos explícitos (mínimo garantizado por
`test_tabla_de_decision_cubre_al_menos_veinte_casos`), más 9 tests dedicados
para: valor desconocido de `visibility` → excepción en construcción (nunca
llega a evaluarse), campo ausente (`visibility`/`known_by`) → excepción,
`character_id` inválido en `known_by` → excepción, personaje no autorizado →
denegado, workspace/partida incorrectos → denegado incluso con
`visibility=player` o con conocimiento de personaje.

`contracts/knowledge-visibility/v1/examples/{valid,invalid}/` son fixtures
congeladas (6 válidas, 8 inválidas — una mutación documentada por caso
inválido), generadas por `tests/generate_examples.py` desde
`tests/kv_fixtures.py`, verificadas byte a byte contra disco por
`test_contracts_knowledge_visibility.py::test_ejemplos_en_disco_coinciden_con_los_generados`.

## 8. Lo que este sub-bloque NO hace (a propósito)

- No modifica `viewer/app/policies/engine.py` (motor intacto, cero líneas).
- No cambia ningún comportamiento observable del visor: ningún router, ningún
  provider, ningún template se toca.
- No implementa `KNOWLEDGE_GRANT_CANDIDATE`, `PROPOSED_KNOWLEDGE_GRANT`,
  `character_access` ni el ledger `knowledge_grant` — quedan como
  sub-bloques futuros; el contrato está diseñado para no imposibilitarlos
  (`known_by` es una lista cerrada de IDs sin lógica de derivación embebida,
  apta para ser una proyección materializada futura de ese ledger).
- No relaja `local_override_of` (M4): sigue sin poder ampliar visibilidad;
  ese comportamiento vive en el motor, no en este contrato, y no se toca.

## 9. Punto abierto para sub-bloques posteriores

`docs/v3/50` diseñó una propagación end-to-end (episodio →
`ClaimProposal._hint` → `FactAssertion` → `GraphMutationPlan` →
`writer/admission.py` → Neo4j) usando su propio vocabulario de tres campos.
Ese plan de propagación queda **sin vigencia** en cuanto al nombre de los
campos (se descartan `known_by_scope`/`visibility_scope`/
`visibility_subjects`), pero su estructura general — IA propone, motor
determinista decide si el claim vive, el writer decide en admisión si la
visibilidad se sella, el visor solo lee lo sellado — sigue siendo el punto de
partida razonable para el sub-bloque que conecte `KnowledgeVisibilityV1` con
el writer (`data-engine/app/knowledge_v3/writer/admission.py`), no
implementado aquí.
