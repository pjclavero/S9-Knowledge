# 44 — Diseño: separación de partidas por ámbitos (multi-partida)

Estado: DISEÑO, sin código de producción. Arranque de implementación gateado al
cierre del programa Puerta 6 (rama `feat/...` en curso sobre `factivity`/`gate6`,
no tocada por este documento). Autor: AGENTE-DISEÑADOR. Base: `main` 37f8341.

## 0. Resumen ejecutivo

El sistema **ya tiene** un mecanismo de aislamiento de una sola capa: `workspace`
(string plano) es una propiedad de nodo, un filtro obligatorio en el resolutor
("INVARIANTE 1" en `resolution/cascade.py`), la clave del catálogo
(`resolution/catalog.py`), la clave física en Neo4j (`writer/cypher.py`), un
campo firmado del plan de escritura (`contracts/mutation_plan.py`), y ya existe
como `frozenset` de ámbitos permitidos en el visor
(`ViewerContext.allowed_workspaces`, `viewer/app/policies/models.py`).

Lo que falta no es "añadir ámbitos": es partir ese único eje en **dos capas
jerárquicas** (`juego:X` compartida, `partida:Y` privada) sin romper ninguna de
las garantías que ya cuelgan de `workspace` siendo un valor atómico y opaco.

**Decisión de representación** (justificada en §1): `workspace` sigue siendo el
identificador del **juego** (`juego:X`) tal cual hoy — cero migración de su
semántica, cero cambios en constraints de unicidad de Neo4j. Se añade una
propiedad nueva, **`partida_id`** (nullable), ortogonal:

- `partida_id IS NULL` → nodo/relación de la capa **juego** (lore compartido).
- `partida_id = "partida:Y"` → nodo/relación **privado de esa partida**.

Visibilidad de una partida Y del juego X: `workspace = "juego:X"` AND
(`partida_id IS NULL` OR `partida_id = "partida:Y"`). Esto es literalmente el
mismo patrón "filtro duro + defensa en profundidad" que el código ya aplica a
`workspace` (`filter_workspace` en catálogo + `history_entry_allowed` en
historial): se añade un segundo filtro con la misma forma, no se sustituye el
primero.

## 1. Por qué `workspace` = juego y `partida_id` nuevo (y no al revés, ni un nodo `Scope`)

Se consideraron tres representaciones, mirando las consultas reales del visor
(`viewer/app/authz/filtered_provider.py`, `viewer/app/policies/engine.py`) y del
motor (`resolution/cascade.py`, `writer/cypher.py`):

**A. `workspace` = partida, capa juego como "otro workspace especial"** —
descartada. Rompería la semántica de `filter_workspace`/`WORKSPACE_ISOLATED`: el
resolutor tendría que aceptar *dos* valores de `workspace` como coincidencia
simultáneamente, y todas las queries de `writer/cypher.py`
(`MATCH (n {workspace: $ws})`) tendrían que convertirse en `IN [$ws1, $ws2]` en
cada punto de escritura Y lectura. Máxima cirugía, mínimo beneficio.

**B. Nodo `Scope` intermedio con relación `(:Entity)-[:IN_SCOPE]->(:Scope)`** —
descartada para v1. Es la solución "más pura" de grafo, pero **ninguna** query
actual del visor (`PolicyFilteredProvider._visible_nodes`,
`VisibilityPolicy.can_view`) navega una arista para decidir visibilidad: todas
leen una propiedad plana del nodo (`node.get("workspace")`, `node.get("party")`,
`node.get("visibility")`). Forzar un JOIN adicional por nodo en cada listado,
conteo y búsqueda (que ya se materializan enteros en memoria antes de paginar,
ver comentario `_ALL = 10_000_000` en `filtered_provider.py`) es coste real por
una expresividad que no se necesita: el ámbito de una entidad no cambia con el
tiempo de forma independiente de su propia versión (a diferencia de `party`, que
sí es dinámico y por eso él sí vive mejor sin propiedad-espejo). Si en el futuro
un juego necesita más de dos niveles de ámbito, se reconsidera.

**C (elegida). Propiedad plana `partida_id` nullable, ortogonal a `workspace`.**
Encaja en el patrón exacto que ya existe: es lo mismo que `workspace`, `party`,
`visibility`, `session_index` — todo propiedades planas que
`VisibilityPolicy.can_view` (líneas 37-73 de `viewer/app/policies/engine.py`)
evalúa en cascada de reglas deny-by-default. Cero coste de JOIN. Compatible con
constraints existentes de Neo4j (`writer/schema.py:18`,
`REQUIRE (op.workspace, op.idempotency_key) IS UNIQUE` — no toca `partida_id`,
no requiere migración de esa constraint). El resolutor ya tiene el molde exacto
(`filter_workspace`, doble cerradura en `history_entry_allowed`) para clonar un
segundo filtro con la misma forma.

## 2. Cambios por componente

### 2.1 Ingesta: mapeo carpeta Nextcloud → ámbito

Hoy el único punto real donde nace `workspace` para una fuente es
`SourceAsset.workspace` (`data-engine/app/knowledge_v3/contracts/source_asset.py:51`,
`collection_id` en la misma línea 56), poblado por quien construye el asset —
en el camino V3 real eso es `pipeline/sources.py:from_raw`/`from_episodes`
(usa `asset["workspace"]`, `asset["collection_id"]`, línea ~184). El camino
legacy `data-engine/app/ingest_rpg.py` recibe `--workspace` como flag de CLI
manual y lee de `NEXTCLOUD_BASE = "/mnt/nextcloud-rol"` (línea ~73) — es "camino
A", ya marcado en el propio código como legacy y gateado tras
`S9K_ALLOW_REAL_INGEST` (líneas 30-56); **no** se toca en este programa salvo
para el mapeo de carpeta (ver bloque M1).

Cambio necesario: el punto de entrada de ingesta (sea el camino real V3 vía
`cli/data_review.py` + `pipeline.py`, sea el legado) necesita derivar **dos**
valores de la ruta de carpeta en vez de uno:

- `workspace` (= `juego:X`): de la carpeta raíz del juego.
- `partida_id` (nullable): de la subcarpeta, si la estructura común de Nextcloud
  distingue "reglas/lore compartido" de "partida concreta" (p.ej.
  `Juego-X/00-Reglas-y-Lore/...` → `partida_id=None`;
  `Juego-X/Partida-Y/...` → `partida_id="partida:Y"`). La convención exacta de
  nombres de carpeta es una decisión operativa (§4), no de este diseño, pero el
  *mecanismo* de mapeo entra en `SourceAsset` como campo nuevo `partida_id:
  Optional[str]`, transportado igual que `workspace` por toda la cadena
  (`source_asset_id → episode → claim → plan`, ver `provider_trace`/
  `produced_by_step` que ya viajan documento a documento en `contracts/base.py`).
- El `GameProfile` (`contracts/game_profile.py`) sigue siendo por `workspace`
  (= por juego): reglas y ontología del juego se comparten entre todas sus
  partidas por diseño, coherente con el requisito "comparten libros de reglas y
  lore inicial".

### 2.2 Contratos (`data-engine/app/knowledge_v3/contracts/`)

- `SourceAsset`, `ClaimProposal`, `GraphMutationPlan`: añadir `partida_id:
  Optional[str] = None` junto a `workspace` en cada uno. Es un campo más del
  documento firmado — `compute_plan_hash`/`compute_decision_hash`
  (`contracts/base.py`, usados por `mutation_plan.py:42-46`) ya hashean el
  documento completo, así que `partida_id` entra en la firma **gratis**, sin
  tocar la lógica de sellado. Bump de `contract_version` (mayor) porque es un
  campo nuevo obligatorio en el esquema JSON Schema congelado — el propio
  contrato dice "mayor no soportada = rechazo" (`mutation_plan.py:25`), así que
  el propio mecanismo de versión protege contra planes viejos sin ámbito
  colándose sin más en un writer nuevo.
- `GraphMutationPlan` necesita además un bloque explícito de **ámbito
  declarado** (no solo `partida_id` suelto): `scope: {"layer": "GAME"|
  "PARTIDA", "game_id": ..., "partida_id": ...|null}`. Motivo: el writer debe
  poder rechazar en **admisión** (no en el gate de operador) un plan cuya
  `layer` sea `PARTIDA` sin `partida_id`, o `GAME` con `partida_id` no nulo —
  eso es precisamente el "cruce de ámbitos = error duro" del Invariante 2, y
  admisión (`writer/admission.py`) es donde hoy vive el chequeo estructural
  equivalente para `workspace` (línea 202: "9. Workspace del writer").

### 2.3 Resolutor (`data-engine/app/knowledge_v3/resolution/`)

- `catalog.py`: `CatalogEntity` gana `partida_id: str | None = None`
  (`__post_init__`, línea ~50, ya valida `workspace` vacío — se añade
  validación simétrica de forma, sin exigir no-vacío porque `None` es legítimo).
  `EntityCatalog.entities(workspace)` pasa a `entities(workspace, *,
  partida_scope: str | None)` y filtra `partida_id in (None, partida_scope)` —
  mismo criterio de "vista, no fuente de verdad" ya documentado en el docstring
  del módulo (líneas 8-13).
- `cascade.py`: junto a `filter_workspace` (línea 175) se añade
  `filter_partida_scope(entities, partida_scope)` con el mismo criterio de
  "un candidato fuera de ámbito jamás entra" (**Invariante 1** tal cual lo pide
  el operador: la entidad nacida en partida Y nunca se fusiona con nada de
  partida Z). `CascadeContext` (línea 126) gana el campo `partida_scope: str |
  None`. `history_entry_allowed` (línea 188, ya es la "segunda cerradura" del
  historial para `workspace`) gana la comprobación gemela para `partida_id`,
  exactamente con el mismo razonamiento que ya está escrito en su docstring
  (líneas 191-199): "una garantía que depende de que nadie se equivoque aguas
  arriba no es una garantía".
- Regla de mezcla explícita: un candidato de la capa juego (`partida_id=None`)
  **sí** puede unificarse con una mención de cualquier partida de ese juego —
  es exactamente el propósito de la capa compartida. Un candidato de
  `partida:Z` nunca es candidato al resolver menciones de `partida:Y`, aunque
  compartan `workspace`.

### 2.4 Writer (`data-engine/app/knowledge_v3/writer/`)

- `cypher.py`: cada `Query` que hoy fija `{workspace: $ws}` en el `MATCH`/`SET`
  (líneas 162-283: `read_entity_state`, `read_assertion_state`,
  `create_entity`, `create_assertion`, `project_relation`,
  `close_entity_validity`, `close_assertion_validity`) añade `partida_id` a
  props en creación, y a la cláusula de lectura cuando el plan opera dentro de
  ámbito de partida. Las lecturas (`read_*_state`) para verificar
  `expected_version`/`expected_hash` deben además comprobar que el nodo leído
  tiene el `partida_id` que el plan declara — leer un nodo de otra partida y
  operarlo sería el propio Invariante 2 violado en el writer, no solo en el
  resolutor.
- `admission.py`: junto al punto 9 (workspace, línea 202) se añade un punto
  nuevo "Ámbito del plan" que valida el bloque `scope` (ver §2.2) contra
  `AdmissionContext` — que gana un campo `partida_scope` opcional, análogo a
  `workspace`. Un plan con `scope.layer=PARTIDA` que declare `game_id` distinto
  del `workspace` del writer, o cuyas operaciones mezclen `partida_id` de dos
  partidas distintas dentro del mismo plan, se **rechaza en admisión** — antes
  de dry-run, con el mismo criterio ya documentado en el módulo: "un plan
  inadmisible no se simula".
- `codes.py`: nuevo código de rechazo, p.ej. `PLAN_SCOPE_CROSS_PARTIDA`, junto a
  los existentes `PLAN_WORKSPACE_MISMATCH` — mismo nivel, mismo tratamiento
  (fail-closed, sin warning).
- `schema.py`: se añade un índice sobre `partida_id` (no una constraint de
  unicidad — la unicidad de idempotencia sigue siendo por `(workspace,
  idempotency_key)`, y ya cubre ámbito porque `idempotency_key` se deriva del
  plan completo, que incluye `scope`).

### 2.5 Motor / supersesión local (`data-engine/app/knowledge_v3/ledger/supersession.py`)

Este es el punto más delicado y **no** es una reutilización directa de
`close_validity` (línea 206). `close_validity` **muta el registro superado**
(`status → SUPERSEDED`, `superseded_by`, cierra `valid_to`) porque en el modelo
actual solo hay una línea de tiempo por afirmación. Aplicarlo tal cual a un
hecho de la capa juego cuando lo que llega es una divergencia de una sola
partida sería exactamente lo que el operador prohíbe: "el lore intacto".

Diseño de la supersesión LOCAL, reutilizando lo que **sí** es reutilizable
(matriz de transiciones, `CANONICAL_REASONS`, `ledger_step`/`provider_trace`,
noción de cadena con `chain_from`):

1. La afirmación de partida Y se crea como una `CREATE_ASSERTION` normal, con
   `partida_id="partida:Y"` — vive en su propia línea de vida, con su propio
   `status` (`PROVISIONAL`→...), su propia matriz de transiciones (sin tocar
   `STATUS_TRANSITIONS`, que ya es genérica).
2. Se añade un puntero nuevo, no destructivo:
   `local_override_of: <assertion_id de la capa juego>` en la afirmación de
   partida (campo de contrato nuevo en `fact-assertion`, análogo a
   `superseded_by` pero *sin* mutar el nodo apuntado). El hecho de la capa
   juego **no cambia de status, no gana `superseded_by`, no cierra
   `valid_to`** — sigue "vivo" para cualquier otra partida del mismo juego.
3. Nueva razón canónica en `CANONICAL_REASONS` (línea 76 en adelante), p.ej.
   `LOCAL_DIVERGENCE`, distinta de `SUPERSEDED_BY_NEWER` — semánticamente es
   "esta partida diverge del lore", no "esta versión sustituye a la anterior
   globalmente". `review_required=True` por defecto en la propuesta (el
   contrato `ClaimProposal` ya tiene ese campo, línea 60 de `claim.py`) porque
   el propio requisito dice "puede requerir revisión humana".
4. Lectura (visor): al listar hechos de una entidad/tema en el contexto de
   partida Y, si existe una afirmación con `local_override_of` apuntando a un
   hecho visible de la capa juego, el hecho de capa juego se **enmascara**
   (se muestra el de partida en su lugar, con indicación de que es una
   divergencia local) — lógica nueva en `PolicyFilteredProvider` o en la capa
   de provider base, no en `VisibilityPolicy` (que decide visible/no visible,
   no "cuál de dos versiones mostrar"). Cualquier otra partida sigue viendo el
   hecho de capa juego intacto, tal como pide el requisito.
5. `chain_from` (línea 254) NO se usa para esto: la cadena de supersesión que
   ya existe sigue sirviendo solo para sustituciones dentro del mismo ámbito
   (partida sustituye a partida, o juego sustituye a juego). La relación
   juego→partida es un puntero de "override", una relación distinta.

### 2.6 Visor (`viewer/app/`)

- `policies/models.py`: `ViewerContext` gana `active_partida: str | None` y
  `allowed_partida_ids: frozenset[str]` (patrón idéntico a
  `allowed_workspaces`/`party_membership` ya presentes). Un viewer de partida Y
  tiene `allowed_workspaces={"juego:X"}` (como hoy) y
  `allowed_partida_ids={"partida:Y"}`.
- `policies/engine.py`: `VisibilityPolicy.can_view` gana una regla nueva entre
  la 2 (workspace) y la 3 (nivel de visibilidad) — mismo lugar en el orden
  fail-fast, porque el ámbito de partida es, como el de workspace, una barrera
  que "nunca se salta, ni por conocimiento" (comentario ya presente en línea
  15): si `partida_id` del nodo no es `None` ni está en
  `ctx.allowed_partida_ids` → `VisibilityDecision(False, "partida_not_allowed")`.
- `authz/context.py`: `build_viewer_context` gana parámetros `active_partida`/
  `allowed_partida_ids`, poblados desde el selector de partida (ver siguiente
  punto) en vez de (o además de) `default_workspace`.
- **Selector de partida**: hoy no existe — el router (`routers/readonly.py`,
  `routers/v3_review.py`) resuelve un único `workspace` por query param con
  fallback a `settings.S9K_DEFAULT_WORKSPACE`. Se necesita: (a) un endpoint/UI
  para que el usuario logueado elija partida entre las que su rol permite; (b)
  esa elección puebla `active_partida` en el contexto de sesión (igual que hoy
  se resuelve `role` desde `request.state.user`, `authz/dependencies.py:26`).
  Las partidas visibles para un usuario son metadato de autorización nuevo
  (fuera del alcance de este documento definir el modelo de "usuario → partidas
  permitidas"; se apunta como bloque M4/decisión abierta).
- `authz/filtered_provider.py`: los métodos que hoy toman un único `workspace`
  (`graph`, `list_entities`, `search`, `counts`, `quality_metrics`...) necesitan
  operar sobre la **unión** de la capa juego + la capa de la partida activa. La
  forma más simple sin tocar la firma del `GraphProvider` base: el provider
  base sigue devolviendo por `workspace` (sin cambios en su contrato), y
  `PolicyFilteredProvider` filtra también por `partida_id` vía la regla nueva
  de `VisibilityPolicy` — como ya filtra hoy en memoria tras traer todo el
  workspace (`_ALL = 10_000_000`, comentario explícito de que el filtro debe
  ocurrir sobre el conjunto completo antes de paginar). Esto funciona sin tocar
  `GraphProvider.graph(workspace)` porque el ámbito de juego sigue siendo
  `workspace` — la partida es un sub-filtro dentro de ese mismo workspace, no
  una fuente adicional. **Válido en v1 mientras "un juego = un `workspace`"
  siga siendo cierto** (ver decisión abierta §4 sobre múltiples juegos).

## 3. Los dos invariantes como tests concretos

### Invariante 1 — el resolutor jamás fusiona entre partidas

- `test_knowledge_v3_resolution.py::test_cascade_discards_other_partida` (nuevo,
  junto a los tests existentes de `discarded_other_workspace`): dos entidades
  con mismo `workspace`, `partida_id` distinto, mismo nombre exacto → 0
  candidatos con `R_EXACT_NAME` cruzando partida; el descarte se refleja en un
  contador nuevo `discarded_other_partida` en `CascadeResult` (espejo de
  `discarded_other_workspace`, línea 156 de `cascade.py`).
- `test_knowledge_v3_resolution_fixtures.py::test_history_entry_denies_cross_partida`:
  entrada de historial con `partida_id` distinto al contexto → `False` en
  `history_entry_allowed`, aunque el catálogo no la conozca (mismo caso límite
  que hoy cubre el chequeo de `catalog is not None` para workspace, línea 210).
- **Test permanente de suite** (el que pide el operador explícitamente,
  "cero claims cross-partida"): `tests/integration/test_multipartida_isolation.py`
  (nuevo) — arma dos partidas del mismo juego con entidades homónimas
  deliberadas, corre el pipeline completo (`pipeline/pipeline.py`) para ambas, y
  afirma que **ningún** `entity_id` ni `assertion_id` creado para partida Y
  aparece en el catálogo/grafo resultante de partida Z, y que ninguna
  `ClaimProposal`/`GraphMutationPlan` de un ámbito referencia un
  `entity_id`/`assertion_id` nacido en otro ámbito de partida. Corre en cada
  PR (mismo nivel que los tests de aislamiento de workspace ya existentes).

### Invariante 2 — cruce de ámbito en el writer es error duro

- `test_knowledge_v3_writer.py::test_admission_rejects_cross_partida_scope`
  (nuevo, junto a los tests de `PLAN_WORKSPACE_MISMATCH`): un
  `GraphMutationPlan` con `scope.layer=PARTIDA` y una `mutation_operation` cuyo
  `entity_id`/`assertion_id` objetivo pertenece a otra partida → `admit()`
  devuelve `admitted=False` con el código nuevo `PLAN_SCOPE_CROSS_PARTIDA`,
  **no** un warning ni un `ABSTAIN`.
- `test_knowledge_v3_writer_mutation.py::test_apply_rejects_scope_mismatch_at_read`:
  plan bien formado en admisión pero que en `read_entity_state`/
  `read_assertion_state` encuentra que el nodo real en Neo4j tiene distinto
  `partida_id` del declarado (caso de carrera/drift) → `WriterAbort`, no
  aplicación parcial (coherente con "transacción, todo o nada",
  `writer.py:14`).
- `test_knowledge_v3_ledger_mutation.py::test_local_override_does_not_mutate_game_layer`:
  aplicar una supersesión local sobre un hecho de la capa juego y comprobar que
  el `status`/`valid_to`/`superseded_by` del hecho de capa juego **no cambian**
  — solo aparece el nuevo puntero `local_override_of` en la afirmación de
  partida.

## 4. Plan de migración

El contenido actual no tiene `partida_id` (campo inexistente = `NULL`
implícito). Dos opciones para el operador, mutuamente excluyentes, aplicables
por *workspace* existente (no hace falta decidir una sola vez para todo el
grafo si conviven varios juegos con distinto criterio):

- **Opción A — todo a capa juego.** No se toca ningún nodo/relación existente
  (`partida_id` ya es `NULL` por ausencia). Efecto: todo lo ingerido hasta hoy
  pasa a ser lore compartido, visible por cualquier partida futura de ese
  `workspace`. Riesgo: si en el contenido actual hay hechos que en realidad
  pertenecían a una sesión de juego concreta (no a reglas/lore), esos hechos
  quedan compartidos con partidas nuevas que no deberían verlos.
- **Opción B — todo a una partida legacy.** Migración explícita: `UPDATE` que
  fija `partida_id="partida:legacy"` en todo nodo/relación de ese `workspace`
  creado antes del corte. Efecto: el contenido actual queda aislado como si
  fuera una partida más; ninguna partida nueva lo ve automáticamente. Requiere
  decidir aparte qué, si acaso, se "sube" manualmente a capa juego (reglas,
  perfiles de personaje reutilizables).

Mecanismo técnico (independiente de la opción, bloque M1, ver §5): script de
migración de una sola pasada sobre Neo4j, `SET n.partida_id = ...` condicionado
por `workspace` y fecha de creación (`created_at`/`ingested_at`), con
`dry-run` obligatorio primero (mismo patrón que ya usa el resto del sistema:
todo camino de escritura tiene dry-run antes de apply). El script en sí requiere
aprobación operativa explícita de producción — no se ejecuta como parte de
ningún bloque de este programa.

## 5. Descomposición en bloques implementables

Cada bloque cierra con el ciclo impl → tests → revisor, es mergeable de forma
independiente, y dejar el sistema en estado consistente (sin ámbito nuevo activo
hasta que el visor y el writer lo entiendan ambos).

| Bloque | Contenido | Riesgo |
|---|---|---|
| **M0** | Contratos: `partida_id` en `SourceAsset`/`ClaimProposal`/`GraphMutationPlan` + bloque `scope`; bump de `contract_version`; JSON Schema congelado actualizado; sin lógica que lo use aún (campo opcional, todo el código existente sigue funcionando con `partida_id=None` en todas partes). | Bajo. Solo contratos + fixtures de test. |
| **M1** | Ingesta: mapeo carpeta→(`workspace`,`partida_id`) en el punto de construcción de `SourceAsset` (camino V3 real, `pipeline/sources.py` y su equivalente de producción fuera de `pipeline/`, no en `ingest_rpg.py` salvo el flag de carpeta). Script de migración (dry-run) para Opción A/B, sin ejecutarlo. | Medio. Toca el único punto de entrada de procedencia; requiere fixtures nuevas de carpeta Nextcloud. |
| **M2** | Resolutor: `filter_partida_scope`, `CascadeContext.partida_scope`, doble cerradura en `history_entry_allowed`, `CatalogEntity.partida_id`. Tests del Invariante 1 (§3). | Medio-alto. Es el núcleo del Invariante 1; requiere no romper ninguno de los tests existentes de `discarded_other_workspace` (deben seguir pasando sin `partida_id`). |
| **M3** | Writer: `admission.py` (punto de ámbito, código `PLAN_SCOPE_CROSS_PARTIDA`), `cypher.py` (props + lectura con `partida_id`), `schema.py` (índice). Tests del Invariante 2 (§3, primeros dos). **No** incluye supersesión local todavía. | Alto. Es la puerta física al grafo; cualquier fallo aquí es el que el operador más teme (escritura fuera de ámbito). Revisor debe verificar fail-closed explícitamente en cada rama nueva. |
| **M4** | Supersesión local: campo `local_override_of`, razón `LOCAL_DIVERGENCE`, lógica de enmascarado en lectura (provider). Test `test_local_override_does_not_mutate_game_layer`. | Alto. Semántica nueva no derivable mecánicamente de lo existente (§2.5); mayor superficie de error humano en el diseño de la propuesta concreta de operación de escritura. |
| **M5** | Visor: `ViewerContext.allowed_partida_ids`/`active_partida`, regla nueva en `VisibilityPolicy.can_view`, selector de partida (UI + endpoint), `PolicyFilteredProvider` aplicando el sub-filtro. Test permanente "cero claims cross-partida" en `tests/integration/`. | Medio. Reutiliza casi al pie de la letra el patrón `allowed_workspaces` ya probado; el riesgo real es el modelo "usuario → partidas permitidas" (decisión abierta, no resuelta aquí). |
| **M6** | Migración real ejecutada en producción (Opción A o B, según decisión del operador) + cierre de la brecha de compatibilidad (planes/fuentes sin `contract_version` nuevo dejan de admitirse). | Operativo, no de código. Requiere aprobación explícita previa (política ya vigente: "ningún cambio en prod sin confirmar"). |

**Qué NO tocar hasta que Puerta 6 cierre:** todo lo que vive bajo
`data-engine/app/knowledge_v3/extraction/`, `engine/` (factivity, shadow,
temporal, negation, decision) y `eval/gate6_*` — es exactamente la superficie
donde Puerta 6 está en obra. M0-M5 tal como están descompuestos no tocan esos
módulos (el diseño de ámbito es ortogonal a la extracción/factividad), pero el
revisor de cada bloque debe verificar en el diff que ningún bloque se acerca a
esos directorios antes de que Puerta 6 cierre.

## 6. Riesgos y decisiones abiertas para el operador

1. **Ámbito por defecto de la migración (Opción A vs B, §4)** — decisión
   explícita pendiente, posiblemente distinta por `workspace` si conviven
   varios juegos con historiales de contenido distintos.
2. **Fuentes ya ingeridas que mezclan juego y partida en el mismo documento**
   (p.ej. un PDF de sesión que también reafirma reglas del manual): el mapeo
   carpeta→ámbito (M1) es por fuente completa, no por fragmento/episodio. Si
   existen documentos así, hace falta o (a) trocearlos manualmente en Nextcloud
   antes de re-ingerir, o (b) aceptar que quedan enteros en un ámbito y vivir
   con la imprecisión. No hay mecanismo de partición automática de una fuente
   entre dos ámbitos en este diseño.
3. **¿La capa juego admite más de un juego desde el día 1?** Sí, técnicamente
   — `workspace` ya es el identificador de juego y ya soporta N valores
   distintos hoy (`writer/schema.py`, catálogo, etc. son todos genéricos en
   `workspace`). Lo que **no** está resuelto es si una partida puede pertenecer
   a más de un juego simultáneamente (crossover) — el diseño actual asume
   partida → exactamente un juego (`workspace` único por partida). Si el
   operador quiere crossovers, `ViewerContext.allowed_workspaces` ya es un
   `frozenset` (soporta varios), pero el resolutor (`CascadeContext.workspace`,
   singular) y el writer (`GraphWriter.__init__`: "un writer, un workspace")
   NO lo soportan hoy y requerirían rediseño adicional fuera de este documento.
4. **Modelo "usuario → partidas permitidas"** (bloque M5): este documento
   asume que existe o existirá una fuente de verdad para qué partidas puede
   seleccionar cada usuario logueado, pero no la diseña — el visor "ya tiene
   login/usuarios/admin" según el encargo, pero la tabla de pertenencia
   usuario↔partida no se ha localizado en el código auditado y puede no
   existir todavía. Bloqueante real para M5 si no existe.
5. **Coste de `PolicyFilteredProvider` materializando en memoria.** El patrón
   actual ya trae *todo* el workspace a memoria antes de filtrar y paginar
   (`_ALL = 10_000_000`). Añadir el sub-filtro de partida no cambia el orden de
   magnitud del problema, pero si el volumen de contenido por juego crece
   (varias partidas activas sobre el mismo juego, cada una generando su propio
   volumen de hechos locales), este diseño puede necesitar empujar el filtro de
   `partida_id` a la query base de Neo4j en vez de solo a la capa de política —
   optimización de rendimiento fuera de alcance de v1 pero señalada aquí porque
   el propio comentario del código ya advierte del coste ("el filtro debe
   ocurrir sobre el conjunto completo, no sobre una página ya recortada").
6. **Nombre y forma exacta de la convención de carpeta Nextcloud** (M1): este
   documento no fija el patrón de nombres (`Juego-X/00-Reglas/...` vs. otra
   convención); es una decisión operativa a acordar con quien organiza
   Nextcloud, no una decisión de arquitectura de datos.
