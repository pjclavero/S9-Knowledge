# 49 — Diseño: separación de partidas por ámbitos (multi-partida)

> **AVISO DE VIGENCIA (2026-08-09).** Este documento es el **diseño** del
> programa y se conserva como tal. Varias de sus afirmaciones de estado han
> quedado atrás: donde diga que M5b «no existe», «sigue sin implementar» o
> «es el hueco más grande del programa», léase **superado**. M5b se
> implementó y cerró en `main` (PRs #147, #150–#153); el contrato canónico
> está en [51](51-m5b0-knowledge-visibility-contrato.md) y la ejecución en
> [docs/54](../54-migracion-visibilidad-m5b.md),
> [55](../55-m5c-cierre-ambito-y-serializadores.md) y
> [58](../58-m5b-c-cadena-de-autorizacion.md).
>
> Lo que **sigue vigente** de este documento: el modelo de ámbitos, los
> invariantes 1 y 2, y que **M6** es housekeeping operativo con aprobación
> explícita del operador. Estado autoritativo:
> [`docs/project-status.yaml`](../project-status.yaml).

Estado: DISEÑO, sin código de producción. **La Puerta 6 está CERRADA y
ratificada** (`main` `cbf461d`, ver `docs/v3/46-gate6-cierre-programa.md` y la
ratificación del operador) — la implementación de este programa **ya no está
gateada** a su cierre; puede arrancar cuando el operador lo autorice. Sigue
vigente, no obstante, la advertencia de no tocar `extraction/`, `engine/`
(factividad, shadow, temporal, negación, decisión) ni `eval/gate6_*` (§5): esa
superficie sigue siendo del programa de extracción, no de este. Además existe
un **piloto en curso del acuerdo determinista∧NVIDIA ratificado**
(`docs/v3/47`, `docs/v3/48-acuerdo-eval2.md`): si algún bloque de este
programa (p. ej. M1, mapeo de ingesta) llega a tocar el camino de ingesta real,
debe verificarse contra ese diseño para no colisionar con él — ninguno de los
bloques M0-M5b tal como están descompuestos lo toca hoy.

Autor: AGENTE-DISEÑADOR. Base original: `main` 37f8341. Revisión con
decisiones del operador: `main` cbf461d (renumerado de `docs/v3/44` a
`docs/v3/49`; el 44 fue tomado por `gate6-B1` en main mientras esta rama
estaba abierta).

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
  nombres de carpeta es una decisión operativa, no de este diseño, pero el
  *mecanismo* de mapeo entra en `SourceAsset` como campo nuevo `partida_id:
  Optional[str]`, transportado igual que `workspace` por toda la cadena
  (`source_asset_id → episode → claim → plan`, ver `provider_trace`/
  `produced_by_step` que ya viajan documento a documento en `contracts/base.py`).

  **Prerequisito de M1 — plantilla de bóveda pendiente de lectura.** Entre las
  5 bóvedas montadas por rclone en VM105 (`leyenda`, `mundo de tinieblas`,
  `trudbang`, `vampiro carcasone`, **`plantilla bovedas`**) existe una
  plantilla explícita para la estructura de carpetas
  (`docs/archivados/24-vm105-baseline-and-verification.md:344`), pero
  **Nextcloud está caído** en el momento de este diseño: no se ha podido leer
  su contenido real. Lo único documentado sobre estructura de carpetas son (a)
  un diseño futuro no implementado,
  `00_fuentes / 10_transcripciones / 20_glosario / 30_pipeline / 40_exports /
  50_informes / 90_archivo` (`docs/archivados/22-installation-and-replicability.md:61-62`,
  explícitamente marcado "NO implementado aún"), y (b) la ruta real usada hoy
  en el runbook de ingesta controlada, plana por bóveda sin distinción de
  partida: `/mnt/nextcloud-rol/leyenda/transcripciones/FICHERO.mp3`
  (`docs/archivados/27-controlled-ingest-runbook.md:101`). Ninguna de las dos
  fuentes confirma si existe ya una subcarpeta por partida dentro de una
  bóveda de juego. **M1 queda formalmente bloqueado a leer `plantilla
  bovedas` en cuanto Nextcloud vuelva** — es lo que fija la convención real
  carpeta→(`workspace`,`partida_id`); hasta entonces M1 puede avanzar en el
  mecanismo de mapeo (código genérico, parametrizable) pero no en la
  convención de nombres concreta.
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

### 2.6 Visor — M5a: selector de partida + aislamiento entre partidas (`viewer/app/`)

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
  **El modelo "usuario → partidas permitidas" queda resuelto** (decisión del
  operador, §7 punto 4): es `user_character_link`
  (`data-engine/app/access/access_store.py`), extendido con `partida_id` —
  las partidas visibles para un usuario logueado son aquellas donde tiene un
  enlace de personaje activo (`is_active_for_workspace` análogo, ahora por
  `(workspace, partida_id)`) o, para el admin/narrador, las que
  `user_workspace_permission` habilite explícitamente sin personaje. Detalle
  completo del reaprovechamiento en §2.7.
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
  una fuente adicional. **Cerrado por decisión del operador (§7 punto 3): no
  hay crossovers** — una partida pertenece exactamente a un juego, nunca al
  revés, así que esta forma de filtrado (workspace único + sub-filtro de
  partida) es la definitiva, no una limitación de v1 a revisar más tarde.

### 2.7 Visor — M5b: visibilidad por conocimiento de personaje dentro de la partida (fog of war)

Ampliación grande del operador (§7 punto 4): dentro de una partida ya
aislada por M5a, cada usuario no ve todo lo de esa partida — ve **la partida
donde tiene personaje, y dentro de ella lo que su personaje sabe o el grupo
de jugadores**. Existe un diseño previo completo de la era v1/v2 para esto
que **se recupera**, no se reinventa:
`docs/archivados/00-vision.md` ("Modelar el conocimiento por personaje"),
`docs/archivados/07-users-permissions.md`,
`docs/current/USERS_CHARACTERS_DESIGN.md` y
`docs/current/KNOWLEDGE_VISIBILITY_DESIGN.md`, con una implementación parcial
real en `data-engine/app/access/access_store.py` (SQLite, selftest OK).

**Modelo recuperado, en dos piezas independientes:**

1. **Usuario ↔ personaje y permisos por bóveda** (quién es quién):
   `user_character_link` (tabla intermedia, estados
   `pending/approved/rejected/revoked/assigned`, un activo por
   usuario+workspace) y `user_workspace_permission` (permisos por bóveda:
   tipos de entidad visibles, `max_visible_session`, flags de
   secret/narrator/future/reference).
2. **Visibilidad en dos niveles** (qué ve, una vez sabido quién es): nivel 1
   por sesión/campaña (público/grupo hasta la sesión visible — esto es
   literalmente el mismo nivel que ya implementa
   `VisibilityPolicy.can_view` puntos 3-5 en `viewer/app/policies/engine.py`);
   nivel 2 por conocimiento de personaje (solo entidades que el personaje
   conoce/presenció/le contaron, vía relaciones `KNOWS_ABOUT`, `HAS_SEEN`,
   `HAS_FOUGHT`, `TELLS`/`TELLS_ABOUT`, `SHARED_WITH`, etc. — nunca
   `secret`/`narrator`/`future` sin permiso explícito).

**Veredicto de reutilización — evidencia leída, no supuesta:**

- **`access_store.py` (pieza 1, usuario↔personaje↔permisos) es reutilizable
  tal cual, con una extensión mínima.** Es un almacén SQLite independiente
  del grafo: sus tablas (`user_character_link`,
  `user_workspace_permission`, `access_audit_log`) están todas indexadas por
  `(username, workspace)` como cadena plana (`access_store.py:62,84,116` y
  el `UNIQUE(username, workspace)` de la línea 106) — no conocen Neo4j, no
  conocen `partida_id` porque no existían partidas cuando se escribió. La
  extensión necesaria es mecánica y de la misma forma que el resto de este
  documento: añadir una columna `partida_id` (nullable) a
  `user_character_link` y `user_workspace_permission`, y cambiar la clave
  única de `(username, workspace)` a `(username, workspace, partida_id)` —
  mismo patrón "ortogonal, columna nueva, sin tocar semántica existente" que
  el resto del programa. Ningún rediseño de esta pieza.
- **Las propiedades de grafo que el diseño de visibilidad (pieza 2) da por
  existentes NO existen en V3 — esto NO es "conectar filtros que ya
  están", requiere trabajo de escritura nuevo.** El propio
  `docs/archivados/07-users-permissions.md` dice literalmente: "el grafo ya
  guarda las propiedades necesarias (`known_by_scope`, `knowledge_quality`,
  `known_from_session`, `visibility`, etc.)" — eso era cierto para el
  pipeline legacy (`rpg_schema.py` 1.4+), pero **se comprobó en el código V3
  actual que no lo es**: `ClaimProposal`
  (`data-engine/app/knowledge_v3/contracts/claim.py`) no tiene ningún campo
  `known_by_scope`, `party`, `visibility`, `session_index` ni relaciones de
  conocimiento (`KNOWS_ABOUT`/`HAS_SEEN`/...); `writer/cypher.py` escribe
  props genéricos (`create_entity`/`create_assertion` aceptan un `dict`
  arbitrario, así que técnicamente *podría* llevar esas propiedades) pero
  **nada en el pipeline V3 actual las produce** — ni extracción ni el motor
  local derivan relaciones de "quién sabe qué" de un claim. `grep` de
  `known_by_scope|known_from_session|visibility|party` en
  `contracts/*.py` y `writer/schema.py` no devuelve nada.
- **Lo curioso, y una buena noticia parcial: el visor YA tiene media pieza 2
  construida, de forma independiente.** `viewer/app/policies/engine.py` y
  `policies/models.py` (slice "RC6 E2") ya implementan un motor de
  visibilidad con esta forma casi exacta: `ViewerContext` ya trae
  `allowed_workspaces`, `party_membership`, `character_knowledge`,
  `max_visible_session`, `can_view_secret/future/reference`, `admin_full`,
  `session_public`; `VisibilityPolicy.can_view` ya evalúa `node["visibility"]`
  (`player/narrator/secret/reference`), `node["party"]`, `node["session_index"]`
  y `node["known_by"]`/`known_by_characters` en cascada deny-by-default. Es
  el motor de decisión de la pieza 2 del diseño legacy, ya escrito y
  probado — pero **nada en el writer V3 escribe esas propiedades en los
  nodos reales**, así que hoy evalúa siempre sobre nodos donde
  `visibility`/`party`/`session_index`/`known_by` están ausentes (deny/allow
  por defecto genérico, nunca por conocimiento real de personaje). Confirma
  la frase de `07-users-permissions.md`: "aplicación real de los filtros:
  pendiente".

**Conclusión de M5b**: no es "activar un interruptor". Se divide en tres
piezas de trabajo reales:

(a) Extender `access_store.py` con `partida_id` (mecánico, bajo riesgo, ya
evaluado arriba).

(b) Extender los contratos V3 (`ClaimProposal`, `GraphMutationPlan`/props de
`create_entity`/`create_assertion`) con las propiedades que
`VisibilityPolicy` ya sabe leer (`visibility`, `party`, `session_index`,
`known_by`/`known_by_characters`) — mismo mecanismo de "campo opcional nuevo,
hashea gratis en la firma" que `partida_id` en M0.

(c) La pieza que **no existe en ningún sitio todavía**: lógica de extracción
o del motor local que **derive** esas propiedades de conocimiento a partir
del texto/claims (quién presenció qué, quién se lo contó a quién — la tabla
de patrones de `KNOWLEDGE_VISIBILITY_DESIGN.md §12` es la especificación de
referencia, pero no hay código V3 que la implemente). Esto es trabajo de
extracción nuevo, de superficie comparable a un carril de extracción propio
— es el motivo de que M5b se mantenga como bloque separado y de riesgo alto,
no una tarea menor colgada de M5a.

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

## 4. Plan de migración — SIMPLIFICADO (decisión del operador, ver §7)

**Ya no hay plan de migración real.** El operador ha confirmado que el
contenido que hoy vive en el grafo es **de prueba**: no representa partidas
reales que deban preservarse con un mapeo cuidadoso a `juego`/`partida`. Las
dos opciones A/B que barajaba la versión anterior de este documento (todo a
capa juego vs. todo a una partida legacy, con sus riesgos de mezclar hechos de
sesión con lore) quedan descartadas por innecesarias: no hay contenido de
producción real que migrar hoy.

Lo que sí hace falta, al desplegar V3 con `partida_id` activo, es una decisión
operativa simple y de una sola vía — **limpiar o marcar el contenido de
prueba**:

- **Limpiar**: borrar el contenido de prueba existente antes de activar
  ingesta real con ámbito de partida, dejando el grafo vacío para arrancar
  limpio con `workspace`/`partida_id` bien formados desde el primer documento
  real.
- **Marcar**: dejarlo pero etiquetado explícitamente como ámbito de prueba
  (p. ej. `partida_id="partida:test"` bajo un `workspace` de prueba, o un flag
  dedicado), para que nunca se confunda con contenido real de una partida ni
  contamine catálogos/resolutor de partidas reales.

Cualquiera de las dos requiere **aprobación explícita del operador antes de
ejecutarse** (política ya vigente: "ningún cambio en prod sin confirmar") y
sigue el mismo patrón técnico que cualquier escritura masiva del sistema:
script de una sola pasada con `dry-run` obligatorio primero. No se ejecuta
como parte de ningún bloque de implementación de este programa; es una
operación aparte, gateada a esa aprobación (ver M6 simplificado en §5).

## 5. Descomposición en bloques implementables

Cada bloque cierra con el ciclo impl → tests → revisor, es mergeable de forma
independiente, y dejar el sistema en estado consistente (sin ámbito nuevo activo
hasta que el visor y el writer lo entiendan ambos).

| Bloque | Contenido | Riesgo |
|---|---|---|
| **M0** | Contratos: `partida_id` en `SourceAsset`/`ClaimProposal`/`GraphMutationPlan` + bloque `scope`; bump de `contract_version`; JSON Schema congelado actualizado; sin lógica que lo use aún (campo opcional, todo el código existente sigue funcionando con `partida_id=None` en todas partes). | Bajo. Solo contratos + fixtures de test. |
| **M1** | Ingesta: mapeo carpeta→(`workspace`,`partida_id`) en el punto de construcción de `SourceAsset` (camino V3 real, `pipeline/sources.py` y su equivalente de producción fuera de `pipeline/`, no en `ingest_rpg.py` salvo el flag de carpeta). **Bloqueado a leer `plantilla bovedas` en Nextcloud** para fijar la convención de nombres real (§2.1); el mecanismo genérico de mapeo sí puede implementarse antes. Ya no lleva script de migración (§4 simplificado — se elimina de este bloque). | Medio. Toca el único punto de entrada de procedencia; depende de un prerequisito externo (Nextcloud arriba) fuera del control del programa. |
| **M2** | Resolutor: `filter_partida_scope`, `CascadeContext.partida_scope`, doble cerradura en `history_entry_allowed`, `CatalogEntity.partida_id`. Tests del Invariante 1 (§3). | Medio-alto. Es el núcleo del Invariante 1; requiere no romper ninguno de los tests existentes de `discarded_other_workspace` (deben seguir pasando sin `partida_id`). |
| **M3** | Writer: `admission.py` (punto de ámbito, código `PLAN_SCOPE_CROSS_PARTIDA`), `cypher.py` (props + lectura con `partida_id`), `schema.py` (índice). Tests del Invariante 2 (§3, primeros dos). **No** incluye supersesión local todavía. | Alto. Es la puerta física al grafo; cualquier fallo aquí es el que el operador más teme (escritura fuera de ámbito). Revisor debe verificar fail-closed explícitamente en cada rama nueva. |
| **M4** | Supersesión local: campo `local_override_of`, razón `LOCAL_DIVERGENCE`, lógica de enmascarado en lectura (provider). Test `test_local_override_does_not_mutate_game_layer`. | Alto. Semántica nueva no derivable mecánicamente de lo existente (§2.5); mayor superficie de error humano en el diseño de la propuesta concreta de operación de escritura. |
| **M5a** | Visor — aislamiento entre partidas: `ViewerContext.allowed_partida_ids`/`active_partida`, regla nueva en `VisibilityPolicy.can_view` (barrera dura, §2.6), selector de partida (UI + endpoint) poblado desde `user_character_link` extendido con `partida_id` (§2.7), `PolicyFilteredProvider` aplicando el sub-filtro. Test permanente "cero claims cross-partida" en `tests/integration/`. | Medio. Reutiliza casi al pie de la letra el patrón `allowed_workspaces` ya probado. El modelo "usuario → partidas permitidas" ya no es una decisión abierta (§7 punto 4: `user_character_link`), así que el riesgo que tenía este bloque en la versión anterior del diseño queda cerrado. |
| **M5b** | Visor — fog of war (visibilidad por conocimiento de personaje dentro de la partida, §2.7): (a) extender `access_store.py` con `partida_id`; (b) extender contratos V3 con `visibility`/`party`/`session_index`/`known_by`(`_characters`) que `VisibilityPolicy` ya sabe evaluar; (c) lógica de extracción/motor que **derive** esas propiedades y relaciones de conocimiento (`KNOWS_ABOUT`, `HAS_SEEN`, `TELLS`, ...) de los claims — no existe hoy en V3, es la pieza nueva real de este bloque. | Alto. (a) y (b) son mecánicos y de bajo riesgo (mismo patrón que M0); (c) es superficie de extracción nueva comparable a un carril propio, con riesgo de falsos negativos (personaje "no sabe" algo que debería) y falsos positivos (fuga de información que el personaje no debería tener) si la derivación es imprecisa. Debe tratarse como su propio sub-programa con criterios de aceptación explícitos, no como una tarea dentro de M5a. |
| **M6** | Limpieza u marcado del contenido de prueba existente en el grafo (§4 simplificado) — ya no es "migración" de datos reales, es housekeeping antes de activar `partida_id` en serio. Opción limpiar vs. marcar, decisión operativa simple. | Operativo, no de código. Requiere aprobación explícita previa (política ya vigente: "ningún cambio en prod sin confirmar"). Riesgo bajo — no hay contenido real que se pueda perder por definición (es contenido de prueba), pero sigue exigiendo confirmación antes de tocar producción. |

**Qué NO tocar hasta que Puerta 6 cierre:** todo lo que vive bajo
`data-engine/app/knowledge_v3/extraction/`, `engine/` (factivity, shadow,
temporal, negation, decision) y `eval/gate6_*` — es exactamente la superficie
donde Puerta 6 está en obra. M0-M5 tal como están descompuestos no tocan esos
módulos (el diseño de ámbito es ortogonal a la extracción/factividad), pero el
revisor de cada bloque debe verificar en el diff que ningún bloque se acerca a
esos directorios antes de que Puerta 6 cierre.

## 6. Riesgos y huecos que quedan abiertos

Las seis decisiones abiertas de la versión anterior de este documento han
sido resueltas por el operador (§7). Lo que queda no son decisiones
pendientes de arquitectura sino **riesgos operativos y huecos de
información** — cosas que este diseño no puede cerrar por sí solo:

1. **Convención real de carpeta Nextcloud (M1), pendiente de leer.** No es ya
   una decisión de diseño abierta: es un hueco de información bloqueado a que
   Nextcloud vuelva y se pueda leer `plantilla bovedas` (§2.1). El *mecanismo*
   de mapeo carpeta→ámbito está diseñado; el *patrón de nombres* concreto no
   se puede fijar sin esa lectura.
2. **Coste de `PolicyFilteredProvider` materializando en memoria.** El patrón
   actual ya trae *todo* el workspace a memoria antes de filtrar y paginar
   (`_ALL = 10_000_000`). Añadir el sub-filtro de partida (M5a) y, sobre todo,
   el filtro de conocimiento de personaje (M5b, potencialmente evaluado por
   entidad y por usuario) no cambia el orden de magnitud del problema, pero si
   el volumen de contenido por juego crece (varias partidas activas, cada una
   generando su propio volumen de hechos locales y de relaciones de
   conocimiento), este diseño puede necesitar empujar los filtros a la query
   base de Neo4j en vez de solo a la capa de política — optimización de
   rendimiento fuera de alcance de v1 pero señalada aquí porque el propio
   comentario del código ya advierte del coste ("el filtro debe ocurrir sobre
   el conjunto completo, no sobre una página ya recortada").
3. **M5b (c) es el hueco más grande del programa: no existe diseño de
   extracción para derivar conocimiento de personaje.** El documento legacy
   (`KNOWLEDGE_VISIBILITY_DESIGN.md §12`) da patrones lingüísticos de ejemplo
   ("Asuka vio al Oni" → `HAS_SEEN`), pero no hay código V3 ni especificación
   de contrato para esa derivación — ni un `ClaimProposal` con campo de
   "relación de conocimiento", ni un extractor dedicado. Antes de implementar
   M5b (c) hace falta una ronda de diseño propia (fuera del alcance de esta
   actualización) que decida si se extrae automáticamente, se marca a mano
   desde un panel (`/control/visibility`, ya especificado en el diseño
   legacy §11), o ambos con automático como sugerencia y manual como
   confirmación.
4. **Volumen y forma exacta del panel de administración** (`/control/users`,
   `/control/visibility` en el diseño legacy): quedan como especificación de
   referencia recuperada, no auditados contra el código actual del visor V3
   más allá de `policies/engine.py`/`models.py` — puede haber piezas de UI a
   construir desde cero que este documento no dimensiona (es diseño de datos
   y de motor de política, no de interfaz).

## 7. Decisiones del operador resueltas (2026-08-04/05)

Todas las decisiones abiertas de la versión anterior de este documento
(`docs/v3/44-multipartida-diseno.md` original) han sido resueltas
explícitamente por el operador. Se listan aquí con su efecto en el diseño:

1. **Migración.** El contenido actual del grafo es de prueba, no producción
   real. No hay plan de migración A/B (§4 de la versión anterior queda
   descartado). M6 se simplifica a limpiar o marcar el contenido de prueba al
   desplegar V3, con aprobación explícita del operador — ver §4 y §5 (M6)
   actuales.
2. **Documentos mixtos.** No existen: en Nextcloud el lore va por un lado y
   las notas de partida por otro. Se elimina la decisión abierta
   correspondiente (antes punto 2 de §6): M1 no necesita partición
   automática de una fuente entre dos ámbitos.
3. **Crossovers.** No — un juego puede tener varias partidas, pero una
   partida nunca pertenece a más de un juego. Cierra la decisión abierta
   (antes punto 3 de §6): el diseño asume, de forma definitiva y no
   provisional, workspace único por partida (§2.6).
4. **Visibilidad por usuario — ampliación grande.** El operador quiere que
   cada usuario vea la partida donde tiene personaje y, dentro de ella, solo
   lo que su personaje sabe o el grupo de jugadores. Se recupera el diseño
   v1/v2 (`docs/archivados/00-vision.md`, `07-users-permissions.md`,
   `docs/current/USERS_CHARACTERS_DESIGN.md`,
   `docs/current/KNOWLEDGE_VISIBILITY_DESIGN.md`,
   `data-engine/app/access/access_store.py`). Efecto en este documento: M5 se
   divide en M5a (selector de partida + aislamiento entre partidas, §2.6) y
   M5b (fog of war por conocimiento de personaje, §2.7); el modelo
   "usuario → partidas permitidas" (antes punto 4 de §6) queda resuelto con
   `user_character_link` extendido con `partida_id`. Veredicto de
   reutilización de `access_store.py` con evidencia de código: ver §2.7.
5. **Plantilla Nextcloud.** Existe la bóveda "plantilla bovedas" entre las 5
   montadas en VM105. Nextcloud está caído en el momento de este diseño: se
   deja el mapeo carpeta→ámbito (M1) atado a leerla en cuanto Nextcloud
   vuelva, con lo que se sabe hoy de estructura de carpetas por los docs
   archivados citado en §2.1.
6. **Estado de gates.** Puerta 6 cerrada y ratificada (`main` `cbf461d`): la
   implementación multi-partida ya no está gateada a su cierre (ver
   encabezado del documento). Se señala el piloto del acuerdo ratificado
   (`docs/v3/48`) para que ningún bloque que toque ingesta colisione con él.

## 8. M0 implementado

Rama `feat/multipartida-m0-contracts`. Alcance ejecutado, deliberadamente
ceñido a "contratos" (§5, tabla M0: "sin lógica que lo use aún"): NO se ha
tocado `pipeline/`, `engine/`, `extraction/`, `writer/` ni `resolution/` —
eso es M1-M4. El campo viaja porque los tres contratos que lo declaran son
exactamente los que forman la cadena de procedencia (`SourceAsset` →
`ClaimProposal` → `GraphMutationPlan`), no porque se haya cableado ningún
constructor intermedio.

**Ficheros tocados:**

- `contracts/knowledge-v3/v1/_common-v3.schema.json`: defs nuevas
  `partida_id`, `partida_id_or_null`, `mutation_plan_scope`,
  `mutation_plan_scope_or_null`. `partida_id` usa el patrón de `stable_id`
  (admite `:`, como `partida:Y`), no el de `workspace` — es un identificador
  lógico, no un nombre de bóveda.
- `contracts/knowledge-v3/v1/source-asset-v3.schema.json`,
  `claim-proposal-v3.schema.json`, `graph-mutation-plan-v3.schema.json`:
  propiedad `partida_id` (y `scope` solo en el plan) añadida a `properties`,
  **fuera** de `required` — aditiva, `additionalProperties: false` se
  mantiene intacto.
- `contracts/knowledge-v3/v1/tests/generate_examples.py` (ejecutado, no
  editado): regenerados los 21 ejemplos tras el primer intento de cambio de
  `validator.py` y de nuevo tras revertirlo; el estado final es
  byte-idéntico al de `main` (`git status` sobre `examples/` limpio).
- `data-engine/app/knowledge_v3/contracts/source_asset.py`, `claim.py`,
  `mutation_plan.py`: campo `partida_id: Optional[str] = None` (y `scope:
  Optional[dict] = None` en `GraphMutationPlan`), añadido a `OMIT_IF_NONE`
  en cada clase (mismo patrón que `metadata`) para que el material existente
  serialice byte a byte igual.
- `data-engine/app/knowledge_v3/contracts/base.py`: sin cambio funcional —
  se evaluó bumpear `CONTRACT_VERSION` y se revirtió (ver decisión de
  versión más abajo); queda un comentario explicando por qué.
- `data-engine/app/tests/test_knowledge_v3_contracts.py`: 9 tests nuevos
  (prefijo `test_m0_`) — retrocompatibilidad, viaje del campo, comparación
  de `plan_hash` y `decision_hash`.
- `data-engine/app/tests/test_knowledge_v3_handwritten_transcription.py`:
  `frozen_ref` de `test_19_contratos_congelados_mantienen_su_hash` movido de
  `v3-contracts-frozen-1.0.0` a `v3-contracts-frozen-1.0.0-m0` (ver más
  abajo — es el único test que sí se ha movido a propósito, y por qué).

**Decisión de evolución de schema v1 — aditiva, sin bump de versión:**

El diseño (§2.2) sugería un bump MAYOR de `contract_version` razonando que
`partida_id` sería "un campo nuevo obligatorio en el esquema JSON Schema
congelado". Se comprobó contra el código real y se optó por la variante más
conservadora, ya prevista como alternativa por la propia tabla de bloques
(§5, M0: "campo opcional, todo el código existente sigue funcionando con
`partida_id=None` en todas partes"):

- `partida_id`/`scope` son propiedades añadidas a `properties`, **fuera**
  de `required`, en los tres schemas. `additionalProperties: false` sigue
  rechazando claves de verdad desconocidas.
- `_check_major_version` (`validator.py`) solo compara el dígito mayor —
  cualquier `1.x.y` pasa igual, con o sin el campo. No hacía falta bump para
  que el mecanismo de versión siguiese protegiendo contra planes
  incompatibles.
- Bumpear `CONTRACT_VERSION` (base.py) de `"1.0.0"` a `"1.1.0"` se probó y
  se revirtió: rompía `test_contract_version_is_the_v1_of_the_v3_family`
  (exige que TODAS las fixtures declaren literalmente la constante viva) y
  habría obligado a regenerar 264+ ficheros de fixtures/goldens sin ganar
  ninguna garantía adicional — mover un test existente sin necesidad
  semántica está prohibido para este bloque.
- Conclusión: **campo opcional con default `null`**, sin bump de versión.
  Documentos que declaren `partida_id` siguen anunciando `contract_version:
  "1.0.0"` legítimamente; el esquema ya lo admite.

**Verificación del hash del plan (comprobada, no asumida):**

El diseño afirmaba que `partida_id`/`scope` quedarían "cubiertos gratis" por
el hash existente. Se verificó que el `GraphMutationPlan` tiene **dos**
hashes con cobertura distinta:

- `plan_hash` (`compute_plan_hash`) SÍ los cubre gratis: es el sha256 del
  documento completo salvo el propio `plan_hash`, así que cualquier campo
  nuevo presente en el dict entra automáticamente. Confirmado con test:
  `test_m0_two_plans_differing_only_in_partida_id_have_different_plan_hash`
  y su equivalente de `scope`.
- `local_approval.decision_hash` (`compute_decision_hash`) NO los cubre:
  `DECISION_HASH_FIELDS` es una lista curada y cerrada de campos de primer
  nivel, no "el documento completo" — un campo nuevo no entra ahí solo por
  existir. Este es el agujero que el diseño advertía que había que
  verificar: dos planes que solo difieren en `partida_id`/`scope` tienen
  `plan_hash` distinto pero el mismo `decision_hash`.
- Se intentó cerrar el agujero añadiendo `"partida_id"` y `"scope"` a
  `DECISION_HASH_FIELDS`. Se revirtió de inmediato: `compute_decision_hash`
  hace `plan.get(k)` para cada campo de la tupla, así que añadir una clave
  nueva mete `"partida_id": None, "scope": None` en el cuerpo de todo plan
  existente (los que jamás declaran el campo incluidos), lo que cambia el
  `decision_hash` esperado de todos los `GraphMutationPlan` ya sellados en
  los datasets `heldout`/`negation-battery`/`benchmarks` — literales
  congelados que este bloque tiene prohibido tocar. La suite completa lo
  confirmó: con el cambio, `test_knowledge_v3_heldout_dataset.py`,
  `test_knowledge_v3_negation_battery.py` y
  `test_knowledge_v3_benchmarks_dataset.py` empezaban a fallar.
- Decisión final: revertido y documentado, no cerrado. El agujero queda
  anotado en `validator.py` (junto a `DECISION_HASH_FIELDS`) y en
  `mutation_plan.py` (junto a los campos nuevos) como pendiente explícito de
  M3, que es donde vive la lógica de admisión que de verdad decide si un
  plan cruza de ámbito — ese es el momento natural para decidir si conviene
  regenerar los datasets gold/held-out a la vez que se cierra el hueco.

**El freeze de contratos v1 (`test_19_contratos_congelados_mantienen_su_hash`):**

Hallazgo no anticipado por el diseño: `data-engine/app/tests/test_knowledge_v3_handwritten_transcription.py`
tiene un test que hashea el contenido byte a byte de todo
`contracts/knowledge-v3/v1/` y `data-engine/app/knowledge_v3/contracts/`
contra el tag git `v3-contracts-frozen-1.0.0`, y falla ante cualquier
modificación de esos ficheros — es, literalmente, el freeze que 13+
documentos citan como base de todo el programa de extracción/resolución/
motor local. M0 modifica exactamente esos ficheros a propósito (es su
objetivo declarado). Se creó un tag nuevo `v3-contracts-frozen-1.0.0-m0`
apuntando al commit de este bloque y se actualizó `frozen_ref` en ese único
test para apuntar a él — el tag original `v3-contracts-frozen-1.0.0` no se
toca ni se borra, sigue siendo válido para cualquier rama que ancle contra
el estado pre-M0. Esta es la única modificación deliberada de un test
existente en este bloque: no es señal de cambio de comportamiento, es la
actualización explícita del punto de congelación para reflejar una
evolución aditiva sancionada por el propio diseño (§5, M0). A partir de M0
el punto de referencia vigente para "contratos congelados" es
`v3-contracts-frozen-1.0.0-m0`, no el original.

**Recuento de suite:** `python3 -m pytest -p no:randomly -q` desde la raíz:
**6365 passed, 51 skipped, 3 xfailed, 0 failed** (incluye los 9 tests nuevos
de M0; ningún test existente se movió salvo el `frozen_ref` de test 19,
justificado arriba).

**Decisiones discutibles para revisión:**

1. No tocar `DECISION_HASH_FIELDS` deja un hueco real y documentado
   (`decision_hash` no distingue ámbito) durante todo el tiempo que pase
   hasta M3. Es un hueco de integridad de decisión, no de plan: `plan_hash`
   sí detecta manipulación del campo; lo que no detecta `decision_hash` es
   que el cuerpo que el writer usa para decidir si aplica sea indistinguible
   entre ámbitos — pero en M0 nada consume `partida_id`/`scope` para decidir
   nada todavía, así que no hay writer real expuesto a este hueco hasta M3,
   que es precisamente donde se cierra.
2. `scope` se modeló como `dict` en el dataclass (no una clase propia) —
   mismo nivel de tipado laxo que `local_approval`/`payload` en el mismo
   contrato; una clase dedicada es evaluable en M3 si la lógica de admisión
   lo pide.
3. El freeze `v3-contracts-frozen-1.0.0-m0` es un tag nuevo, no una rama:
   cualquier bloque posterior (M1+) que vuelva a tocar estos ficheros deberá
   repetir el mismo patrón (nuevo tag, nuevo `frozen_ref`) en vez de mover
   este de nuevo.

## 9. Política de versión de contratos v1 del programa

Recomendación del revisor de M0, formalizada aquí porque M2 ya la necesita
(vuelve a tocar `contracts/knowledge-v3/v1/` y `data-engine/app/knowledge_v3/
contracts/`, esta vez en `EntityMention`/`EntityResolution`). No es una regla
nueva: es la que M0 aplicó dos veces (schema + freeze) escrita para que M3 y
sucesivos no tengan que redescubrirla.

**Criterio aditivo-sin-bump vs. bump-mayor.** Un cambio a un contrato
`v3-internal-v1` **NO** necesita bump de `CONTRACT_VERSION` (`base.py`,
sigue en `"1.0.0"`) cuando se cumplen las tres condiciones a la vez:

1. El campo nuevo se añade a `properties` **fuera** de `required`, con
   `default=None` en el dataclass Python y en `OMIT_IF_NONE` — el material
   existente (`partida_id` ausente) serializa byte a byte igual que antes.
2. `additionalProperties: false` se mantiene intacto salvo por la clave
   nueva: no se relaja la cerradura del contrato para nada más.
3. Ningún dato ya sellado (fixture, ejemplo congelado, dataset
   `heldout`/`negation-battery`/`benchmarks`) necesita regenerarse para
   seguir validando. Si regenerar 264+ ficheros es el precio de un bump, el
   bump no compensa (M0, §8) — la variante aditiva es preferible mientras
   exista.

Un bump **MAYOR** (`1.0.0` → `2.0.0`) solo procede cuando el campo nuevo pasa
a ser **obligatorio** en `required`, o cuando `additionalProperties` deja de
poder proteger el contrato sin el campo (p. ej. una regla semántica que exige
`partida_id` para action=`CREATE_*` dentro de una partida). Eso es una
decisión de M3 (admisión: `layer`/`partida_id` coherentes), no de M0 ni de
M2 — ninguno de los dos bloques introduce una regla de rechazo por su
ausencia.

**Patrón de tags de freeze.** `test_19_contratos_congelados_mantienen_su_hash`
(`test_knowledge_v3_handwritten_transcription.py`) hashea byte a byte
`contracts/knowledge-v3/v1/` + `data-engine/app/knowledge_v3/contracts/`
contra un tag git fijo (`frozen_ref`). Cualquier bloque que modifique esos
ficheros de forma aditiva y sancionada debe:

1. Completar el cambio y su commit en la rama del bloque.
2. Crear un tag anotado nuevo `v3-contracts-frozen-1.0.0-m<N>` (`<N>` = número
   de bloque, p. ej. `-m0`, `-m2`) apuntando a ese commit, con mensaje
   `Freeze checkpoint post-M<N> (docs/v3/49): <resumen de una línea>`.
3. Actualizar `frozen_ref` en `test_19_contratos_congelados_mantienen_su_hash`
   al tag nuevo, con un comentario que explique qué cambió y por qué es
   aditivo.
4. **Nunca** borrar ni mover un tag de freeze anterior: cada uno sigue siendo
   un ancla válida para quien necesite reproducir el estado exacto de ese
   punto del programa. La cadena de tags (`...-1.0.0` → `...-1.0.0-m0` →
   `...-1.0.0-m2` → …) es, en sí misma, el historial de evolución aditiva del
   contrato.
5. Es la **única** modificación de test existente que este patrón autoriza
   sin que cuente como "test movido": el valor de la constante cambia, la
   aserción y su intención (congelación byte a byte) no.

**Cuándo M3 podrá tocar datasets congelados.** M0 dejó abierto y documentado
(§8, decisión discutible 1) que `local_approval.decision_hash`
(`DECISION_HASH_FIELDS`, `validator.py`) no distingue `partida_id`/`scope`
aunque `plan_hash` sí. Cerrar ese hueco añadiendo esas claves a
`DECISION_HASH_FIELDS` cambia el `decision_hash` esperado de **todo**
`GraphMutationPlan` ya sellado en `heldout`/`negation-battery`/`benchmarks` —
literales congelados que M0 y M2 tienen prohibido tocar. La condición para que
M3 pueda hacerlo es que exista ya un **consumidor real** de `partida_id`/
`scope` en la lógica de admisión (el propio M3: rechazo en admisión de planes
con ámbito incoherente, §2.2) — hasta entonces cerrar el hueco no compra
ninguna garantía porque nada decide todavía en función del campo. Cuando M3
llegue a ese punto, regenerar los datasets es una operación explícita y
aparte (no un efecto colateral de tocar `validator.py`), con su propio tag de
freeze de datasets si el programa lo pide.

## 10. M2 implementado

Rama `feat/multipartida-m2-resolver`, sobre `main` con M0 ya mergeado
(`ccf0fe4`). Alcance: el resolutor de identidad (`resolution/`) hace cumplir
el Invariante 1 también para `partida_id`, con el mismo patrón de doble
cerradura que ya sostenía `workspace`. M1 (mapeo de carpetas) sigue bloqueado
por Nextcloud y no hace falta para M2: basta con que `partida_id` llegue por
el contrato, no con que nadie lo derive todavía de una ruta real.

**Hallazgo previo al diseño de la solución:** `partida_id` (M0) llegaba hasta
`SourceAsset`/`ClaimProposal`/`GraphMutationPlan`, pero **no** hasta
`EntityMention` ni `EntityResolution` — el resolutor vive entre esos dos
contratos y ninguno de los dos lo declaraba. Fue necesario propagarlo un tramo
más, de la misma forma aditiva (ver §9): campo opcional, `OMIT_IF_NONE`, sin
bump de `CONTRACT_VERSION`.

**Ficheros tocados:**

- `contracts/knowledge-v3/v1/entity-mention-v3.schema.json`,
  `entity-resolution-v3.schema.json`: propiedad `partida_id` (reutilizando
  `partida_id_or_null` de `_common-v3.schema.json`, ya definido por M0) fuera
  de `required`.
- `data-engine/app/knowledge_v3/contracts/mention.py`, `resolution.py`: campo
  `partida_id: Optional[str] = None`, añadido a `OMIT_IF_NONE`.
- `data-engine/app/knowledge_v3/resolution/catalog.py`: `CatalogEntity` gana
  `partida_id: str | None = None` (validación simétrica a `workspace`:
  rechaza `""`, admite `None`). `EntityCatalog.entities()`/`get()` ganan
  `partida_scope: str | None = None` — visible ⟺ `partida_id is None` o
  `partida_id == partida_scope`; por defecto (`partida_scope=None`) el
  comportamiento es **idéntico** al de antes de M2 porque todo el material
  existente tiene `partida_id=None`. `InMemoryEntityCatalog.get()` queda
  **deliberadamente sin filtrar** por `partida_scope` (ver su docstring): lo
  necesita la segunda cerradura del historial para conocer la propiedad real
  de un `entity_id` ya conocido, no la vista recortada de la cascada.
- `data-engine/app/knowledge_v3/resolution/history.py`: `HistoryEntry` gana
  `partida_id`; la clave del índice pasa de `(workspace, superficie)` a
  `(workspace, partida_id, superficie)` (con `""` como representación
  ordenable de `None` — ver `_key`). Sin esto, dos partidas mencionando la
  misma superficie compartirían ranura de historial y la segunda heredaría
  silenciosamente la identidad de la primera: un camino de fuga que el propio
  catálogo no cubre. `lookup()` combina dos claves (ámbito propio + capa
  juego) con dirección única (ver más abajo).
- `data-engine/app/knowledge_v3/resolution/cascade.py`: `filter_partida_scope`
  (gemela de `filter_workspace`), aplicada en `run_cascade` justo después del
  filtro de workspace. `CascadeContext.partida_scope`. `history_entry_allowed`
  gana dos comprobaciones nuevas (además de las dos de workspace ya
  existentes): que la entrada declare una partida visible, y que el catálogo,
  si conoce la entidad, no la atribuya a una partida ajena — la cerradura
  gemela exacta que el diseño pedía. Nuevo código de razón
  `PARTIDA_ISOLATED` y campo `CascadeResult.discarded_other_partida`.
- `data-engine/app/knowledge_v3/resolution/resolver.py`: `_read_envelope`
  exige `partida_id` uniforme en el grupo de menciones (igual que ya exigía
  `workspace`); `_build_context` propaga `partida_scope`;
  `catalog.entities(...)`/`history.record(...)` reciben el ámbito; la
  `EntityResolution` emitida declara `partida_id` heredado de las menciones.
- Tests: `test_knowledge_v3_resolution.py` (`TestCatalogo`, `TestHistorial`,
  `TestPartida` nueva), `test_knowledge_v3_resolution_fixtures.py`
  (`PARTIDA_A`/`PARTIDA_B`/`PARTIDA_ENTITIES`/`catalog_with_partidas`, y
  `partida_id` en el fixture `mention()`), `test_knowledge_v3_resolution_
  mutations.py` (`TestMutacionPartida`, gemela completa de
  `TestMutacionWorkspace`, incluido `test_invariante_resolutor_ciego_entre_
  partidas`). Las firmas de `LeakyCatalog.entities`/`LeakyHistory.lookup`/
  `ReversedCatalog.entities` (mocks de test, no producción) se actualizaron
  para aceptar el `partida_scope` nuevo — mecánico, no cambia qué prueban.

**La dirección única del Invariante 1 (la sutileza del bloque):** una mención
de la partida Y ve la capa juego (`partida_id=None`) además de sus propias
entidades — es el propósito de la capa compartida. Una mención de la capa
juego (`partida_id=None`, p. ej. ingesta de lore) **NO** ve ninguna entidad de
ninguna partida, ni siquiera con nombre idéntico: el lore no puede "capturar"
una entidad de mesa. Implementado en tres sitios independientes y probado en
cada uno (`filter_partida_scope`, `EntityCatalog.entities`, `ResolutionHistory.
lookup`): los tres tratan `partida_scope=None` como "solo capa juego", nunca
como comodín.

**Caminos del resolutor cubiertos por el invariante (adversariales
propios):** catálogo (`filter_partida_scope`, defensa en profundidad sobre lo
que `entities()` ya debería haber filtrado — probado con `LeakyCatalog`, que
ignora `partida_scope` a propósito), historial (`history_entry_allowed`,
doble comprobación: valor de la entrada + verdad del catálogo — probado con
`LeakyHistory` y con una entrada que MIENTE su `partida_id` apuntando a una
entidad de otra partida), y la dirección juego→partida en los tres puntos de
filtrado a la vez. El glosario no necesita filtro propio: no emite
identidades, solo traduce superficie a término canónico, y el término se
contrasta contra `ctx.entities`, que ya llega acotado.

**Recuento de suite:** `python3 -m pytest -p no:randomly -q` desde la raíz:
**6423 passed, 51 skipped, 4 xfailed, 0 failed** (incluye 36 tests nuevos de
M2: 178 en el subsistema de resolución frente a los 142 de antes de M2, más
`test_19` re-anclado). Segunda modificación deliberada de un test existente
autorizada por §9 (`frozen_ref` → `v3-contracts-frozen-1.0.0-m2`); ningún
otro test existente se movió.

**Decisiones discutibles para revisión:**

1. `InMemoryEntityCatalog.get()` ignora `partida_scope` a propósito (búsqueda
   directa por id, sin restringir ámbito) porque lo necesita la segunda
   cerradura del historial para conocer la verdad completa de un `entity_id`
   ya conocido. Es coherente con el mismo patrón que `EntityCatalog.locate()`
   (no filtra por workspace tampoco, con el mismo razonamiento), pero es una
   asimetría respecto a `entities()` que vale la pena que un revisor
   confirme explícitamente.
2. `ResolutionHistory.lookup()` con ámbito de partida devuelve la entrada
   PROPIA de la partida si existe, y si no, cae a la de capa juego — nunca
   las dos a la vez ni un tercer estado de "ambiguo entre las dos". Es una
   simplificación deliberada (el historial es una señal barata, no la
   decisión final; un empate real entre capa juego y partida para la misma
   superficie es un caso raro no cubierto explícitamente por este bloque) y
   queda anotado para si M3/M4 lo encuentran en corpus real.
3. No se ha tocado `writer/`, `admission.py` ni `policies/`: siguen siendo
   M3/M4, según el diseño original. M2 es estrictamente el resolutor.

## 11. M3 implementado

Rama `feat/multipartida-m3-writer`, sobre `main` con M0+M2 ya mergeados
(`90507c0`). Alcance: el writer (`data-engine/app/knowledge_v3/writer/`)
hace cumplir el Invariante 2 — cruce de ámbito en el writer es error duro,
nunca warning — y cierra/re-decide los cuatro pendientes heredados de M0/M2.

**Ficheros tocados:** `writer/admission.py` (código nuevo
`PLAN_SCOPE_CROSS_PARTIDA`, punto "9.5. Ámbito del plan"), `writer/codes.py`
(`PLAN_SCOPE_CROSS_PARTIDA`, `EXEC_SCOPE_MISMATCH`), `writer/view.py`
(`SignedView.partida_id`, resuelto de `scope.partida_id` con fallback a la
raíz), `writer/cypher.py` (estampado de `partida_id` en creación,
`_scoped_match`/`_visible_predicate` para lectura y relaciones acotadas por
ámbito en `WHERE`, nunca en Python; `read_*_any_scope` para diagnóstico de
drift; `partida_id` añadido a `RESERVED_PROPS`), `writer/executor.py`
(`_check_expected_state` acotado + distinción `EXEC_TARGET_MISSING` vs
`EXEC_SCOPE_MISMATCH`; `_assert_absent` deliberadamente SIN filtro de
ámbito), `writer/schema.py` (índices `v3_entity_partida_id_index`/
`v3_assertion_partida_id_index`, no constraint), `writer/__init__.py`
(exports nuevos), `docs/v3/09-writer.md` (tabla de códigos), más los
ficheros de contrato (`contracts/knowledge-v3/v1/validator.py`,
`data-engine/app/knowledge_v3/contracts/mutation_plan.py`) con la
justificación escrita de las dos decisiones de "no cerrar" (ver abajo). NO
se ha tocado `pipeline/`, `resolution/`, `extraction/`, `engine/`,
`eval/gate6_*` ni `policies/` — eso sigue siendo M1/M4/M5.

### Diseño de la validación de admisión

`admission.py` distingue, por construcción, los DOS filos del Invariante 2:

1. **Coherencia INTERNA del ámbito declarado** (`_scope_incoherence`,
   estructural, sin tocar Neo4j — admisión "no escribe ni consulta nada"):
   - `scope` ausente + `partida_id` raíz presente → rechazo (M3 exige el
     ámbito ESTAMPADO explícitamente, no un `partida_id` suelto).
   - `scope.layer` fuera de `{GAME, PARTIDA}` → rechazo (además cazado antes
     por el `enum` del JSON Schema si el documento pasó por
     `GraphMutationPlan.from_dict`, que ya lo valida; la comprobación del
     writer es una segunda red para quien construya el dataclass a mano).
   - `layer=PARTIDA` sin `scope.partida_id` → rechazo ("partida sin ámbito").
   - `layer=GAME` con `scope.partida_id` no nulo → rechazo ("partida
     colándose en la capa juego" — el cruce indebido que el diseño llama
     "partida→juego").
   - `scope.game_id` distinto de `plan.workspace` → rechazo.
   - `partida_id` raíz y `scope.partida_id`, si ambos están presentes,
     deben coincidir → rechazo si no ("partida contra partida"). **Esto
     cierra el gap de M0** (`test_scope_partida_id_can_disagree_with_root_
     partida_id_undetected`, ahora `..._is_rejected_by_m3` en
     `test_m0_partida_id_adversarial.py`).
   - Los tres ejes pedidos por el encargo ("partida≠partida",
     "partida→juego indebido", "scope incoherente") están cubiertos, cada
     uno con su propio test en `test_knowledge_v3_writer.py` sección "1.5".
2. **Cruce contra el ESTADO real** (una entidad/aserción ya escrita bajo
   OTRO ámbito): no es decidible en admisión por construcción (no toca el
   grafo). Se cierra en `executor.py`, en lectura: `_check_expected_state`
   lee acotado por `partida_id` (Cypher, `_scoped_match`); si no encuentra
   nada, una segunda consulta SIN filtro de ámbito (`read_*_any_scope`)
   distingue "no existe" (`EXEC_TARGET_MISSING`) de "existe, en otro
   ámbito" (`EXEC_SCOPE_MISMATCH`, nuevo). Ambos abortan el plan ENTERO
   (`WriterAbort`), nunca una aplicación parcial.

`SignedView.partida_id` resuelve el ámbito EFECTIVO una sola vez
(`scope.partida_id` si existe, si no la raíz `partida_id`): admisión ya
garantizó que, cuando ambos están presentes, coinciden, así que el resto
del writer no vuelve a mirar `scope` en ningún otro sitio.

### Diseño del estampado Cypher

Disciplina del diseño respetada al pie de la letra: **el filtrado de ámbito
vive en Cypher, nunca en Python**, exactamente como ya hacía `workspace`.
Dos primitivas nuevas en `cypher.py`:

- `_scoped_match(label, id_field, id, workspace, partida_id)`: precondición
  EXACTA sobre un objetivo concreto. `partida_id=None` compila a
  `WHERE n.partida_id IS NULL` (Neo4j nunca compara `= null` como
  verdadero, así que un valor `null` en el patrón de mapa sería
  silenciosamente falso siempre); `partida_id="partida:Y"` compila a
  `{..., partida_id: $partida_id}` en el propio patrón. Usada por
  `read_entity_state`/`read_assertion_state`/`close_*_validity`.
- `_visible_predicate(alias, partida_id)`: predicado de VISIBILIDAD (capa
  juego + partida propia), no de identidad — usado en los dos extremos de
  `create_relation`. Misma dirección única que el resolutor de M2: un plan
  de partida Y puede enlazar capa juego o su propia partida, nunca otra
  partida; un plan de capa juego solo enlaza capa juego.

Creación (`create_entity`/`create_assertion`/`create_relation`) siempre
mete `"partida_id": partida_id` en el dict de propiedades que se manda al
driver. Verificado (no asumido): Neo4j omite las claves con valor `null` al
crear un nodo/relación con `CREATE (n $props)`, así que un `partida_id=None`
dejaAL nodo EXACTAMENTE igual que antes de M3 — sin la propiedad presente en
absoluto, no con un `null` explícito. Retrocompatibilidad byte a byte con
material `None`/`None` verificada con test
(`test_apply_de_capa_juego_no_estampa_partida_id`).

`_assert_absent` (CREATE-only, ¿ya existe este id?) es **deliberadamente
SIN** filtro de ámbito: un `entity_id`/`assertion_id` es único en TODO el
workspace, cruzando capa juego y todas sus partidas — dos ámbitos jamás
comparten el mismo id, con el mismo razonamiento que ya aplica a
`idempotency_key` dentro de un workspace.

### Las cuatro decisiones heredadas

1. **Coherencia raíz vs scope (test de M0).** CERRADO. Ver arriba: ahora es
   `PLAN_SCOPE_CROSS_PARTIDA` en admisión, con test convertido (no borrado)
   en `test_m0_partida_id_adversarial.py`.
2. **`decision_hash` (hueco de M0).** NO CERRADO, decisión explícita según
   la condición de §9: aunque ya existe consumidor real
   (`PLAN_SCOPE_CROSS_PARTIDA`), se verificó — con `grep`, no supuesto —
   que **ningún** plan de `heldout`/`negation-battery`/`benchmarks` declara
   `partida_id`/`scope` hoy, así que el riesgo real de la ambigüedad es
   cero en los datasets congelados. Cerrarlo exigiría regenerar 264+
   ficheros por una garantía que nada consume todavía en esos datasets.
   Documentado con la misma extensión en `validator.py` junto a
   `DECISION_HASH_FIELDS` y en `mutation_plan.py`.
3. **`idempotency_key` (mismo rigor que `decision_hash`, pedido por el
   encargo de M3).** NO CERRADO, pero por una razón distinta y más fuerte:
   `IDEMPOTENCY_KEY_FIELDS` tampoco distingue ámbito (verificado con test:
   dos planes de partidas distintas con la misma identidad lógica de
   operación producen la MISMA `idempotency_key`), pero esto **no es un
   agujero de corrupción**: `execute_plan` reclama la clave dentro de la
   misma transacción (`claim_applied_operation`) y, si ya está tomada por
   un `plan_hash`/`operation_id` distinto, aborta con
   `EXEC_IDEMPOTENCY_CONFLICT` — fail-closed por construcción, nunca una
   fusión silenciosa de operaciones de dos partidas. A diferencia de
   `decision_hash` (un hueco de *auditabilidad*), aquí no hay hueco de
   *seguridad* que cerrar. Test:
   `test_dos_partidas_con_operacion_identica_comparten_idempotency_key_pero_no_corrompen`.
4. **Observabilidad del descarte cross-partida (P2 de M2).** DECIDIDO: NO
   se implementa en el writer. `writer/admission.py` juzga un documento de
   plan ya sellado; nunca ve la lista de candidatos que el resolutor
   descartó para llegar a esa decisión — esa información (`PARTIDA_
   ISOLATED`, `discarded_other_partida`) vive y muere dentro de
   `CascadeResult`, varios pasos antes de que exista un plan que sellar.
   Cerrarlo exigiría transportar el descarte hasta el contrato del plan
   (campo nuevo en `ClaimProposal`/`GraphMutationPlan`, con su propio
   bump/tag de freeze) — cirugía de contrato, no de admisión, fuera de
   alcance de M3. El marcador de M2
   (`test_HALLAZGO_partida_isolated_NO_aparece_en_el_camino_honesto`) se
   reforzó con un comentario explícito apuntando a esta decisión, sin
   moverlo ni convertirlo en xfail (no hay nada que falle: documenta un
   comportamiento aceptado).

### Retrocompatibilidad verificada

Material `partida_id=None` sobre entidades `partida_id=None` produce
exactamente el mismo comportamiento que antes de M3: mismo Cypher salvo por
la cláusula `WHERE n.partida_id IS NULL` (semánticamente un no-op sobre
nodos que nunca tuvieron la propiedad), mismas propiedades escritas (la
clave `partida_id` no aparece en absoluto, igual que hoy). Ningún test
existente de `test_knowledge_v3_writer.py`/`test_knowledge_v3_writer_
mutation.py`/`test_knowledge_v3_writer_neo4j_real.py` se modificó de
comportamiento; el único ajuste fue extender el driver falso compartido
(`FakeTx.run`) para honrar el filtro de ámbito que el propio Cypher generado
ya declara (mecánico, no cambia qué prueban los tests existentes).

**Recuento de suite:** `python3 -m pytest -p no:randomly -q` desde la raíz:
**6489 passed, 51 skipped, 4 xfailed, 0 failed** (incluye los tests nuevos
de M3: 126 en `test_knowledge_v3_writer.py`, más el test M0 convertido en
`test_m0_partida_id_adversarial.py` y el refuerzo de comentario en
`test_m2_partida_isolation_adversarial.py`). Dos modificaciones
deliberadas de tests existentes, ambas autorizadas explícitamente:
`frozen_ref` → `v3-contracts-frozen-1.0.0-m3` (tercera vez que se aplica el
patrón de §9; comentarios aditivos en `validator.py`/`mutation_plan.py`
mueven el hash byte a byte) y la conversión del test M0 sobre coherencia
raíz/scope de "gap documentado" a "rechazo verificado" (documentaba
exactamente el hueco que este bloque cierra). Ningún otro test existente
se movió ni cambió de comportamiento.

**Decisiones discutibles para revisión:**

1. `AdmissionContext` NO ganó un campo `partida_scope` (writer pineado a
   una única partida, análogo a `workspace`). El diseño (§2.4) lo sugiere
   como "análogo a `workspace`", pero el resto del documento (R3: "un
   writer por workspace") nunca pide "un writer por partida" — un mismo
   writer de workspace debe poder aplicar planes de distintas partidas del
   mismo juego. Añadir el campo habría sido género no pedido; se dejó fuera
   y queda anotado por si un despliegue real lo necesita.
2. `EXEC_SCOPE_MISMATCH` cuesta una consulta extra a Neo4j (la de
   diagnóstico sin filtro) SOLO en el camino ya-de-por-sí-raro de un
   `EXEC_TARGET_MISSING`/drift — nunca en el camino feliz. Coste aceptado a
   cambio de un código de error distinguible; alternativa más barata
   (fusionar ambos bajo `EXEC_TARGET_MISSING`) se descartó por perder
   señal de diagnóstico real (¿bug de contenido o carrera de ámbito?).
3. `create_relation` ahora exige visibilidad de AMBOS extremos
   (`_visible_predicate` en `a` y `b`), no solo del sujeto (que ya tenía su
   propio chequeo de concurrencia optimista vía `_check_expected_state`).
   Esto es más estricto que el código pre-M3 (que solo comprobaba
   `workspace` en el `MATCH`, nunca ámbito de partida en el objeto) — es
   intencional (Invariante 2), pero un revisor debe confirmar que ningún
   camino de producción legítimo enlazaba antes con un objeto "invisible"
   que ahora dejaría de aplicar.
4. La cobertura de "objeto de la relación en otro ámbito" solo se
   demuestra con tests puros de `cypher.py` (Cypher/params generados) y con
   el test real de Neo4j ya existente (gated,
   `test_knowledge_v3_writer_neo4j_real.py`): el driver falso compartido
   (`FakeTx`) nunca modeló el fallo de un `MATCH` sobre el objeto de una
   relación (limitación preexistente a M3, no introducida por este
   bloque), así que el camino "objeto invisible aborta con
   `EXEC_TARGET_MISSING`" no tiene un test mockeado dedicado end-to-end.

### Ronda de revisión: CONFORME CON OBSERVACIONES → corrección acotada

Dictamen del revisor: el Invariante 2 queda validado (incluidos ataques
propios del revisor), y la decisión de `_assert_absent` sin filtro de
ámbito se confirmó **necesaria con ejecución real**: `derive_entity_id` no
incluye `partida_id` en el hash de identidad, así que dos mesas con un
personaje homónimo colisionan hoy en el mismo `entity_id` — demostrado por
el revisor, no solo argumentado. Queda anotado para que un bloque futuro
valore incorporar `partida_id` al hash de identidad en origen (fuera de
alcance de M3: eso es superficie de `resolution`/generación de ids, no del
writer).

**Corrección aplicada — asimetría en `_scope_incoherence` (`admission.py`):**
la regla "`partida_id` raíz sin bloque `scope` → rechazo" no tenía su
espejo: un `scope.layer=PARTIDA` con `scope.partida_id` declarado mientras
la raíz (`plan.partida_id`) estaba AUSENTE pasaba admisión sin protesta (el
código solo comparaba raíz contra `scope.partida_id` cuando ambos estaban
presentes). El revisor verificó que no existe ningún generador legado que
produzca esa combinación — el campo raíz y el bloque `scope` nacieron
juntos en M0 — así que no hay retrocompatibilidad real que proteger.
Añadida la rama simétrica en `_scope_incoherence`: `layer=PARTIDA` +
`scope.partida_id` truthy + `root_partida is None` → `PLAN_SCOPE_CROSS_
PARTIDA`. Test `test_scope_de_partida_sin_partida_id_de_raiz_NO_se_rechaza_
asimetria` (que documentaba el gap como comportamiento actual) renombrado a
`test_scope_de_partida_sin_partida_id_de_raiz_se_rechaza_simetria` e
invertido: ahora afirma el rechazo, no la admisión.

**Recomendación no bloqueante aplicada — verificación real diferida:**
`test_knowledge_v3_writer_neo4j_real.py` gana dos tests nuevos (gated por
Docker, `skipped` en esta suite): `test_m3_create_entity_de_capa_juego_
no_escribe_la_propiedad_partida_id` (un `CREATE` con `partida_id=None`
deja el nodo SIN la propiedad presente en absoluto — comprobado con `"clave"
not in props`, no con `props.get(...) is None`, que no distinguiría
ausencia de `null` explícito) y su gemelo en positivo,
`test_m3_create_entity_de_partida_estampa_partida_id_real`. Se activarán
solas contra un Neo4j real (`S9K_WRITER_NEO4J_REAL=1`, p. ej. el despliegue
V3 en VM105) sin depender de que alguien se acuerde de añadirlas en ese
momento.

**Recuento de suite tras la corrección:** `python3 -m pytest -p no:randomly
-q` desde la raíz, en primer plano: **6496 passed, 53 skipped, 4 xfailed, 0
failed** (+2 skipped respecto al recuento anterior de M3, por los dos tests
reales nuevos gated; el resto del delta es el test renombrado/invertido, sin
cambio de cardinalidad neta en `passed`).

## 12. M4 implementado

Rama `feat/multipartida-m4-override`, sobre `main` con M0+M2+M3 ya mergeados
(`7c8c286`). Alcance: supersesión LOCAL (`local_override_of`) — el hecho de
partida diverge del lore de capa juego sin mutarlo jamás. NO se ha tocado
`pipeline/`, `resolution/`, `extraction/`, `engine/` ni `eval/gate6_*`: como
en M3, la superficie que Puerta 6 tiene en obra queda intacta. En particular,
**no** se ha tocado `engine/planner.py` (que hoy construye el `FactAssertion`
real vía la matriz de supersesión temporal, `ledger/supersession.py`,
`close_validity`) — el diseño original (§2.5) señalaba ese módulo como el
lugar "más delicado"; la implementación real evita tocarlo del todo
manteniendo `local_override_of` como un campo puramente aditivo (default
`None`) que ningún generador existente necesita poblar para seguir
funcionando exactamente igual que antes.

**Ficheros tocados:**

- `data-engine/app/knowledge_v3/contracts/assertion.py`: `FactAssertion` gana
  `local_override_of: Optional[str] = None`, añadido a `OMIT_IF_NONE` (mismo
  patrón aditivo que `calendar_id`/`metadata`).
- `contracts/knowledge-v3/v1/fact-assertion-v3.schema.json`: propiedad
  `local_override_of` (reutilizando `stable_id_or_null` de
  `_common-v3.schema.json`), fuera de `required`.
- `contracts/knowledge-v3/v1/validator.py`: chequeo semántico de
  autoreferencia (`local_override_of` no puede apuntar a la propia
  afirmación), gemelo del que ya existía para `supersedes`/`superseded_by`.
- `data-engine/app/knowledge_v3/ledger/supersession.py`: nuevo motivo
  canónico `LOCAL_DIVERGENCE` en `CANONICAL_REASONS[LedgerOperation.ASSERT]`
  — la afirmación de partida que diverge nace como un `ASSERT` normal, no
  como un `SUPERSEDE` (el hecho de capa juego no se sustituye).
- `data-engine/app/knowledge_v3/writer/codes.py`: `PLAN_LOCAL_OVERRIDE_FROM_
  GAME_LAYER` (admisión), `EXEC_LOCAL_OVERRIDE_TARGET_MISSING`,
  `EXEC_LOCAL_OVERRIDE_TARGET_NOT_GAME_LAYER`,
  `EXEC_LOCAL_OVERRIDE_REASON_INVALID` (ejecución).
- `data-engine/app/knowledge_v3/writer/admission.py`: `_local_override_
  incoherence` (punto "9.6. Divergencia local"), estructural, sin tocar
  Neo4j — gemela de `_scope_incoherence` (M3).
- `data-engine/app/knowledge_v3/writer/executor.py`: `_check_local_override`,
  invocada dentro de la rama `CREATE_ASSERTION` de `execute_operation`;
  import de `ledger.supersession.CANONICAL_REASONS`/`LedgerOperation` para
  compartir una única fuente de verdad del motivo canónico con el ledger
  local (en vez de duplicar la cadena `"LOCAL_DIVERGENCE"` sin verificación
  cruzada).
- `data-engine/app/knowledge_v3/writer/cypher.py`: `list_visible_assertions_
  query` — nueva función de LISTADO (las demás funciones de `cypher.py` son
  de un único objetivo, orientadas a `_single()`).
- `data-engine/app/knowledge_v3/writer/reads.py` (nuevo): `list_visible_
  assertions`, envoltorio de solo lectura sobre la consulta anterior.
  Exportado desde `writer/__init__.py`.
- `docs/v3/09-writer.md`: tabla de códigos ampliada con los siete códigos
  nuevos.
- `data-engine/app/tests/test_knowledge_v3_writer_local_override.py`
  (nuevo): 19 tests.
- `data-engine/app/tests/test_knowledge_v3_handwritten_transcription.py`:
  `frozen_ref` movido de `v3-contracts-frozen-1.0.0-m3` a
  `v3-contracts-frozen-1.0.0-m4` (mismo patrón de §9, cuarta vez que se
  aplica).

### Por qué el puntero es una PROPIEDAD, no una relación de grafo

El diseño (§2.5) dejaba abierto si `local_override_of` se estampa "como
relación o propiedad". Se eligió **propiedad plana** en el nodo
`V3Assertion` nuevo, por el mismo criterio que ya usa `superseded_by` en el
propio contrato (`fact-assertion/v3-internal-v1`): un `assertion_id` en
texto, no una arista. Razones:

1. **Coherencia con lo existente.** `superseded_by`/`supersedes` ya son
   propiedades, no relaciones, en el mismo nodo. Introducir una relación
   real solo para `local_override_of` habría creado dos representaciones
   distintas del mismo tipo de puntero ("esta afirmación se relaciona con
   esa otra") dentro del mismo contrato, sin necesidad semántica.
2. **Coste de escritura.** Una propiedad se escribe en el mismo `CREATE`
   que ya crea el nodo (cero consultas adicionales); una relación exigiría
   un `MATCH` extra sobre el objetivo antes de poder crear la arista —
   exactamente el coste que `create_relation` ya paga por los DOS extremos
   de una relación de entidades, pero que aquí no hace falta duplicar,
   porque el chequeo de "el objetivo es de capa juego" (`_check_local_
   override`) ya hace ese `MATCH` con otro propósito (la validación del
   Invariante 2) y puede reutilizarse en vez de escribir un segundo builder
   Cypher solo para la arista.
3. **Coste de lectura.** `list_visible_assertions_query` puede resolver el
   enmascarado con una comparación de propiedades (`o.local_override_of =
   n.assertion_id`) dentro de un `EXISTS {}` correlacionado, sin necesitar
   atravesar una arista. Si en el futuro se necesita navegación nativa de
   grafo sobre la cadena de overrides (p. ej. para un panel de
   administración que liste "todas las divergencias de esta partida" de
   forma eficiente sobre volumen alto), añadir una relación proyectada
   además de la propiedad es un cambio aditivo puro — no exige deshacer
   esta decisión, solo complementarla.

**Coste explícito de la lectura enmascarada (decisión pedida por el
encargo):** `list_visible_assertions_query` resuelve el enmascarado con
`WHERE NOT EXISTS { MATCH (o:V3Assertion) WHERE o.workspace = $ws AND
o.partida_id = $partida_id AND o.local_override_of = n.assertion_id }`, es
decir, un filtro que vive en Cypher, evaluado por fila, acotado a
`workspace`+`partida_id` (los mismos dos campos que ya indexa
`writer/schema.py` para `_scoped_match`, M3). Se descartó explícitamente la
alternativa de traer todo el conjunto visible a Python y filtrar ahí — el
patrón que ya usa `PolicyFilteredProvider` en el visor, con su propio
comentario de coste conocido (`_ALL = 10_000_000`, §6 punto 2 de este mismo
documento) — porque esa alternativa duplicaría en Python una regla que el
propio Cypher ya expresa con una comparación de igualdad, y multiplicaría el
tráfico de red por cada asercion candidata en vez de una sola subconsulta
indexada. El trade-off aceptado: el coste crece con el número de
`local_override_of` declarados POR PARTIDA (no con el tamaño total del
ámbito), que se espera pequeño porque una partida diverge del lore en puntos
concretos, no en bloque; si esa suposición deja de sostenerse en producción,
el punto de escalar es un índice compuesto
`(workspace, partida_id, local_override_of)`, no mover el filtro a Python.

### Semántica de cadenas de override (decisión explícita, requisito 5.d)

**Elegida: sin cadenas.** Un `local_override_of` debe apuntar SIEMPRE
directamente a una afirmación de CAPA JUEGO (`partida_id IS NULL`). Intentar
overridear una afirmación que ya es en sí misma un override (o cualquier
afirmación de partida, propia o ajena) se rechaza con el mismo código que
cualquier otro objetivo no-capa-juego: `EXEC_LOCAL_OVERRIDE_TARGET_NOT_GAME_
LAYER` — no hay un código distinto para "cadena" porque, para el writer, una
cadena es simplemente un caso más de "el objetivo no es de capa juego".

Se descartaron las otras dos opciones que planteaba el encargo:

- **"Colapsar al original"** (seguir la cadena de overrides hasta encontrar
  la capa juego y apuntar ahí en su lugar) exigiría que el writer
  recorriera un grafo de punteros ANTES de decidir una escritura — el tipo
  de inferencia que este módulo evita a propósito (fail-closed simple,
  nunca "arregla" un plan). Además desplazaría a Neo4j una decisión que hoy
  toma el motor local (quién es el destino real de la divergencia), lo que
  contradice el principio general del writer: "no interpreta, no corrige".
- **"Resolver al último de la cadena"** tiene el mismo problema de fondo, y
  añade el riesgo de un ciclo (`chain_from`, en `ledger/supersession.py`,
  ya tiene que defenderse explícitamente de ciclos en la cadena de
  `superseded_by` — abrir una segunda cadena, la de `local_override_of`,
  reintroduciría ese mismo riesgo sin necesidad).

La consecuencia práctica: quien quiera corregir una divergencia local YA
escrita no encadena un segundo override sobre el primero — actúa sobre ESA
afirmación de partida con su ciclo de vida normal (confirmar, contradecir o
retractar, vía `CONFIRM`/`CONTRADICT`/`RETRACT` del ledger local). El hecho
de capa juego, mientras tanto, sigue disponible sin límite como objetivo
válido de un nuevo `CREATE_ASSERTION` con override, si la partida necesita
reafirmar una divergencia distinta sobre el mismo hecho de lore.

### Matriz de rechazos en admisión/ejecución

| Caso | Dónde se decide | Código | Test |
|---|---|---|---|
| Capa juego declara `local_override_of` | Admisión (estructural) | `PLAN_LOCAL_OVERRIDE_FROM_GAME_LAYER` | `test_admision_rechaza_override_declarado_desde_capa_juego`, `test_admision_rechaza_override_sin_scope_declarado_ni_partida_id` |
| Partida declara `local_override_of` (coherente en sí mismo) | Admisión (estructural) | admitido | `test_admision_admite_override_declarado_desde_partida` |
| Objetivo no existe en ningún ámbito | Ejecución (lectura) | `EXEC_LOCAL_OVERRIDE_TARGET_MISSING` | `test_override_a_objetivo_inexistente_aborta_target_missing` |
| Objetivo existe, pertenece a OTRA partida (cross-partida) | Ejecución (lectura) | `EXEC_LOCAL_OVERRIDE_TARGET_NOT_GAME_LAYER` | `test_override_a_objetivo_de_otra_partida_cross_partida_rechazado` |
| Objetivo existe, pertenece a la PROPIA partida (juego←partida indebido) | Ejecución (lectura) | `EXEC_LOCAL_OVERRIDE_TARGET_NOT_GAME_LAYER` | `test_override_a_objetivo_de_la_propia_partida_juego_indebido_rechazado` |
| Objetivo es a su vez un override (cadena) | Ejecución (lectura) | `EXEC_LOCAL_OVERRIDE_TARGET_NOT_GAME_LAYER` | `test_override_de_un_override_ya_existente_es_rechazado_como_no_capa_juego` |
| `reason_code` ausente | Ejecución | `EXEC_LOCAL_OVERRIDE_REASON_INVALID` | `test_override_sin_reason_code_canonico_rechazado` |
| `reason_code` presente pero no `LOCAL_DIVERGENCE` | Ejecución | `EXEC_LOCAL_OVERRIDE_REASON_INVALID` | `test_override_con_reason_code_incorrecto_rechazado` |
| Objetivo de capa juego, `reason_code` correcto, partida coherente | Ejecución | aplicado, sin tocar el hecho de juego | `test_override_partida_a_capa_juego_aplica_y_no_toca_el_hecho_de_juego` |

### Revisión humana (`review_required`)

El encargo de M4 pide que la propuesta de override llegue con
`review_required=True` por defecto — campo que ya existe en `ClaimProposal`
(`contracts/claim.py`, desde antes de M0) y que el flujo de revisión
existente ya consume. **No se ha tocado ningún generador de
`ClaimProposal`** (eso vive en `extraction/`/`engine/`, fuera de alcance de
M4): la verificación de este bloque es que el campo y el flujo de revisión
ya existen y no necesitan UI nueva para mostrar una razón `LOCAL_DIVERGENCE`
— `review_required` es un booleano genérico del contrato, no interpreta el
valor de `reason_codes`, así que una propuesta de divergencia local pasa por
el mismo camino de revisión que cualquier otra propuesta marcada para
revisión humana, sin caso especial. Construir un panel dedicado que explique
"¿divergencia real de mesa o error de extracción?" al revisor es,
explícitamente, trabajo de M5 (fuera de alcance de M4).

### Retrocompatibilidad verificada

Material sin `local_override_of` (el 100% del material anterior a M4)
produce exactamente el mismo comportamiento que antes: `_check_local_
override` retorna inmediatamente (`if not target: return`) sin tocar el
driver, sin leer nada, sin cambiar ninguna consulta ya generada. Ningún test
existente de `test_knowledge_v3_writer.py`/`test_knowledge_v3_writer_
mutation.py`/`test_knowledge_v3_contracts.py` se modificó de comportamiento;
el único cambio deliberado de un test ya existente es, otra vez, el
`frozen_ref` de `test_19_contratos_congelados_mantienen_su_hash` (patrón de
§9, cuarta vez).

**Recuento de suite:** `python3 -m pytest -p no:randomly -q` desde la raíz,
en primer plano — ver cifra exacta al cierre de este bloque en el commit
correspondiente (19 tests nuevos en `test_knowledge_v3_writer_local_
override.py`; ningún otro test existente cambió de resultado salvo el
`frozen_ref` re-anclado).

**Decisiones discutibles para revisión:**

1. `writer/reads.py` es una API de solo lectura que HOY no consume ningún
   camino de producción (ni `execute_plan`, ni `admission.py`): existe para
   demostrar el enmascarado con un test y para que M5 (el visor) tenga un
   lugar del que copiar la disciplina "filtrado en Cypher", no una
   dependencia que M5 esté obligado a usar tal cual. Un revisor podría
   preferir no añadir código de producción sin consumidor real; se optó por
   añadirlo de todos modos porque el encargo pedía explícitamente demostrar
   el enmascarado de lectura, y no hacerlo habría dejado ese requisito sin
   ninguna prueba ejecutable contra una superficie de listado real.
2. `_check_local_override` reutiliza `read_assertion_state`/`read_
   assertion_state_any_scope` (M3) en vez de un builder Cypher dedicado. En
   el camino feliz (objetivo de capa juego, todo correcto) esto cuesta UNA
   lectura extra (la acotada a capa juego, que ya basta para confirmar el
   éxito); solo el camino de rechazo paga la segunda lectura `any_scope`
   para distinguir `TARGET_MISSING` de `NOT_GAME_LAYER` — mismo reparto de
   coste que `EXEC_SCOPE_MISMATCH` en M3 (la lectura de diagnóstico solo se
   paga cuando algo ya iba a abortar). Queda anotado por si el volumen de
   creación de overrides en producción hace conveniente fusionar la lectura
   feliz con la escritura en una sola ida a Neo4j.
3. El catálogo de motivos (`LOCAL_DIVERGENCE`) vive en
   `ledger/supersession.py`, no en `writer/codes.py` ni en
   `contracts/knowledge-v3/v1/validator.py` (`CANONICAL_REASON_CODES`, que
   gobierna los `reason_codes` de las DECISIONES del plan, un catálogo
   distinto y ya existente). Son dos catálogos de motivos con propósitos
   diferentes (motivo de una decisión del motor vs. motivo de una
   transición del ledger); mezclarlos habría sido más confuso que tener dos
   catálogos pequeños y bien nombrados. Un revisor debe confirmar que esta
   distinción está justificada y no es una duplicación accidental.

### Ronda de revisión: NO CONFORME → rework (3 P1 + 1 exigencia mínima)

La promesa central de M4 (**el lore jamás se escribe**) quedó verificada en la
revisión. Lo que no se sostenía eran cuatro cosas, corregidas aquí. Ninguna
cambia el diseño de §2.5; todas lo endurecen.

**1. Bypass por *falsy* (`local_override_of=""`).** Tanto la admisión
(`_local_override_incoherence`) como la ejecución (`_check_local_override`)
comprobaban *truthiness* — `if payload.get("local_override_of")` y
`if not target: return`. La cadena vacía es falsy en Python exactamente igual
que `None` o que la clave ausente, así que un plan de **capa juego** con
`local_override_of=""` se admitía, pasaba ejecución sin ninguna validación
contra el estado real, y la cadena vacía quedaba escrita en un nodo de lore
**sin exigir `reason_code`**. La frontera se normaliza ahora en **un solo
sitio**, `admission.declares_local_override(payload)` (`... is not None`),
compartido por los dos módulos. Dirección **fail-closed**: declarar el campo
con cualquier valor cuenta como intención de declarar divergencia. El vacío
**no** se normaliza a "ausente" —eso lo dejaría pasar *y escrito*—: se trata
como declaración inválida y muere donde corresponda (estructural desde capa
juego, `EXEC_LOCAL_OVERRIDE_TARGET_MISSING` desde partida, o
`EXEC_LOCAL_OVERRIDE_REASON_INVALID` si además falta el motivo).

**2. Unicidad por partida.** Nada impedía que la MISMA partida creara dos
aserciones con `local_override_of` apuntando al mismo hecho de lore: las dos
quedaban visibles a la vez, sin criterio de desempate. Ahora hay unicidad
estricta `(workspace, partida_id, local_override_of)`, resuelta en Cypher
(`cypher.find_local_override`, `MATCH … LIMIT 1`) y aplicada en la rama
`CREATE_ASSERTION` de `execute_operation`, junto al `_assert_absent` con el
que comparte criterio: **CREATE-only estricto**, el segundo intento es un
conflicto duro (`EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED`), nunca una fusión ni
una cadena. La unicidad es POR PARTIDA, no global: que `partida A` haya
divergido de un hecho del lore no impide que `partida B` diverja del mismo
hecho (lo contrario sería el acoplamiento entre partidas que el Invariante 1
prohíbe).

**3. Vigencia en la vista.** `list_visible_assertions_query` prometía
"visible" y no filtraba `status` en absoluto: devolvía también lo
`SUPERSEDED`/`RETRACTED`, es decir, hechos ya superados presentados como
vigentes. Se añade la cláusula `n.status IN $live_statuses` al `WHERE`, con el
catálogo **del ledger** (`ledger.supersession.LIVE_STATUSES`), no una copia a
mano: `SUPERSEDED`/`RETRACTED` fuera, `CONTRADICTED` dentro (una contradicción
marca, no destruye). Mismo criterio de siempre: la visibilidad se resuelve en
Cypher, jamás en Python.

**Semántica elegida — enmascarado con un override no vigente.** El `NOT
EXISTS` mira el **puntero**, no el `status` del override: un override
`SUPERSEDED` **sigue enmascarando** el hecho de lore al que apunta. Es lo
único coherente con la unicidad del punto 2: la partida declara su divergencia
sobre ese hecho de lore **una vez**, y lo que evoluciona después es el
*contenido* de la divergencia, por el ciclo de vida normal de la afirmación de
partida (supersesión temporal A→B dentro de la partida). Si el enmascarado
dependiera del `status`, supersedir A haría **reaparecer** el lore junto a B
—dos hechos del mismo sujeto en la misma vista— y además no habría forma de
volver a ocultarlo, porque la unicidad impide declarar un segundo override
sobre el mismo objetivo. Con la semántica elegida, esa partida ve **B y solo
B**, y el lore sigue intacto y visible para todos los demás ámbitos. Probado
en `test_override_superseded_dentro_de_la_partida_deja_lore_enmascarado_y_
solo_B_visible`.

**4. Marca de revisión en el resultado.** Cada escritura con
`local_override_of` deja ahora una marca explícita y consultable en el
**resultado** de la operación: `LOCAL_DIVERGENCE_PENDING_REVIEW`, con
`operation_id`, `assertion_id`, `local_override_of` y `partida_id`. Viaja por
`AppliedOperation.review_marks` → `ExecutionOutcome.review_marks` →
`WriteResult.review_marks` (y a `to_dict()`), y se copia al `detail` del
registro de auditoría del desenlace. También la emite el **dry-run**: quien
simula antes de aplicar puede ver que ESE plan trae una divergencia, sin
aplicarlo. Tres límites deliberados: (a) **no bloquea** la escritura esperando
aprobación —el circuito de aprobación humana es M5—; (b) **no es un rechazo**,
no contamina `rejections` ni el desenlace; (c) **no se engancha en
`engine/decision.py`**, que es la capa de *claims* de extracción y no la de
planes. Su razón de ser es que la auditoría encuentre lo que hay que mirar sin
tener que saber buscar `local_override_of IS NOT NULL` en el grafo.

Los dos P2 que el dictamen aceptó **no se han tocado**: la autorreferencia
sigue rechazándose por efecto colateral (`EXEC_LOCAL_OVERRIDE_TARGET_MISSING`,
porque el `CREATE` aún no existe cuando se comprueba), y `SUPERSEDE_ASSERTION`
sobre un hecho de lore con overrides colgando sigue permitido —comportamiento
defendible: M4 nunca borra, el puntero sigue apuntando a un nodo que existe.

**Ficheros tocados en el rework:** `writer/admission.py` (frontera
`declares_local_override`, exportada), `writer/executor.py` (uso de la
frontera, unicidad, `review_marks` en `AppliedOperation`/`ExecutionOutcome`,
marca también en `simulate_plan`), `writer/cypher.py` (`find_local_override`,
`LIVE_STATUS_VALUES`, filtro de vigencia), `writer/codes.py`
(`EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED`, `LOCAL_DIVERGENCE_PENDING_REVIEW` +
`REVIEW_MARK_CODES`), `writer/writer.py` (`WriteResult.review_marks` y su
paso al rastro), `docs/v3/09-writer.md` (código nuevo en la tabla),
`tests/test_knowledge_v3_writer.py` (el `FakeTx` aprende a responder la
consulta de unicidad como LECTURA, incluyendo lo escrito antes en la misma
transacción —igual que Neo4j—), y los dos ficheros de tests de M4.

**Tests invertidos/ajustados, con causa:**

| Test | Antes | Ahora | Causa |
|---|---|---|---|
| `test_override_vacio_bypassa_el_rechazo_estructural_de_capa_juego` → `…_ya_no_bypassa_…` | se admitía | `PLAN_LOCAL_OVERRIDE_FROM_GAME_LAYER` | P1 nº1 corregido |
| `test_override_vacio_bypassa_tambien_el_chequeo_de_ejecucion_y_se_escribe` → `…_desde_capa_juego_no_llega_a_escribirse` | se escribía `""` en capa juego | muere en admisión, `driver.writes == []` | P1 nº1 corregido |
| `test_misma_partida_dos_overrides_del_mismo_lore_ambos_visibles_sin_desempate` → `…_se_rechaza_el_segundo` | ambos aplicados y visibles | `EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED`, plan abortado | P1 nº2 corregido |
| `test_hecho_de_capa_juego_ya_superseded_sigue_visible_porque_la_query_no_filtra_status` → `…_deja_de_estar_visible` | lo `SUPERSEDED` aparecía | solo aparece la versión vigente | P1 nº3 corregido |
| `test_override_superseded_dentro_de_la_partida_…_ambas_versiones_visibles` → `…_solo_B_visible` | A y B visibles a la vez | lore enmascarado, solo B visible | P1 nº3 + semántica elegida |

### Límite conocido de M4: RETRACTAR una divergencia deja zona muerta (→ M5)

Aceptado y documentado en el dictamen final (CONFORME CON OBSERVACIONES), **no
se corrige en M4**. Con `{lore: ASSERTED, override_A: RETRACTED}`:

- `list_visible_assertions` devuelve **conjunto vacío** para esa partida: el
  override ya no es vigente (filtro de status) pero **sigue enmascarando** el
  lore, porque el `NOT EXISTS` mira el puntero y no el status.
- `find_local_override` tampoco filtra status, así que la partida **no puede
  declarar un override nuevo** sobre ese hecho: choca contra el registro
  retractado (`EXEC_LOCAL_OVERRIDE_ALREADY_DECLARED`).

Quien retracta su divergencia deja de ver *nada* de ese hecho, para siempre.
La causa es que M4 trata igual dos cosas que semánticamente no lo son:
**RETRACTAR** es "retiro mi divergencia" —el lore debería reaparecer y la
unicidad debería liberarse— mientras que **SUPERSEDER** es "sigo divergiendo,
con otro contenido" —enmascarado correcto, y la unicidad debe seguir cerrada,
que es justo la semántica elegida arriba—. La distinción exige el ciclo de
vida completo de la divergencia (qué hace cada transición del ledger con el
puntero y con la unicidad), y eso es **M5**, no un parche aquí.

Semántica esperada para M5, para que quede fijada antes de implementarla:
`RETRACTED` levanta el enmascarado (el lore vuelve a verse en esa partida) y
libera la unicidad (la partida puede volver a divergir de ese hecho);
`SUPERSEDED` no hace ninguna de las dos cosas. Mientras tanto el estado actual
queda **fijado por un test** —
`test_LIMITE_retracted_deja_zona_muerta_lore_enmascarado_y_sin_reoverride`—
para que nadie lo "arregle" por accidente sin esa decisión de diseño.

**Tests nuevos del rework (11, uno de ellos el del límite anterior):** los dos filos del vacío desde PARTIDA
(objetivo inexistente y `reason_code`), la unicidad en un plan posterior y su
carácter por-partida, la consulta de unicidad y el filtro de vigencia a nivel
de Cypher, `CONTRADICTED` que sigue visible frente a `RETRACTED` que no, y las
tres de la marca de revisión (aplicada, ausente en una creación normal, y
anunciada en dry-run).

**Recuento exacto de suite** (`python3 -m pytest -p no:randomly -q` desde la
raíz del worktree, primer plano): **6537 passed, 53 skipped, 4 xfailed,
0 failed** (11 tests nuevos netos sobre los 6526 de la ronda anterior;
5 invertidos en el sitio).

## 13. M5a implementado

Rama `feat/multipartida-m5a-viewer` (worktree aislado), base `main` 6148a1c
(M0+M2+M3+M4). Objetivo: selector de partida en el visor + aislamiento entre
partidas en TODA consulta del visor, sin implementar el fog of war por
conocimiento de personaje (M5b, fuera de alcance, no imposibilitado).

### Decisión: modelo usuario -> partidas permitidas

El diseño (§2.6) dejaba abierto extender `data-engine/app/access/
access_store.py` (`user_character_link`) con `partida_id`, según lo previsto
en la revisión del operador. **Se decidió NO usarlo y crear en su lugar una
tabla nueva en la propia base de auth del visor** (`viewer/app/auth/db.py`,
`auth.db`, migración a `SCHEMA_VERSION = 2`): `partida_access(id, user_id,
workspace, partida_id, granted_by, granted_at)`, `UNIQUE(user_id, workspace,
partida_id)`.

Motivo, verificado en el código antes de decidir (no supuesto): el visor
**ya tiene su propia fuente de verdad de autorización** — `auth.db` con
`users`/`sessions`/`audit_events` — y **nunca ha leído ni escrito**
`access_store.py`. Son dos procesos distintos (viewer FastAPI vs. CLI/
data-engine), dos bases de datos distintas, dos ciclos de vida distintos, sin
ningún acoplamiento hoy. Añadir aquí `partida_access` sigue exactamente el
patrón de las tablas ya existentes (misma base, mismas convenciones de
migración con `ALTER TABLE ... ADD COLUMN` guardado con `try/except` sobre
`sqlite3.OperationalError` para idempotencia, mismo `auth.audit` para
trazabilidad) y **no introduce una segunda fuente de verdad**: sigue
habiendo una sola tabla que decide qué puede seleccionar un usuario en el
visor (`partida_access`), igual que sigue habiendo una sola tabla que decide
su rol (`users`). Conectar el visor a `access_store.py` habría sido acoplar
dos procesos que hoy no se conocen, por una pieza (M5b, conocimiento de
personaje) que este bloque no implementa — se revisará si M5b lo necesita.

Reglas del modelo: asignación exclusivamente por un admin desde
`/admin/partidas` (sin auto-alta); un usuario puede tener varias partidas
asignadas (varias filas); mesa **activa** por sesión (`sessions.
active_partida`, columna nueva) — un usuario con dos partidas asignadas ve,
en cada momento, solo una (más la capa juego), nunca las dos a la vez; sin
ninguna asignación, o sin partida activa seleccionada, ve únicamente la capa
juego (`partida_id IS NULL` o ausente).

### Motor de política: una regla más, en el sitio exacto que preveía el diseño

`viewer/app/policies/models.py`: `ViewerContext` gana `active_partida:
Optional[str]` y `allowed_partida_ids: frozenset[str]` (en la práctica, esta
última contiene como máximo un elemento — la partida activa — no todas las
asignadas: seleccionar una partida sustituye la vista, no la añade).

`viewer/app/policies/engine.py`, `VisibilityPolicy.can_view`, regla 2b (entre
workspace y nivel de visibilidad, exactamente donde decía el diseño):

```python
pid = node.get("partida_id")
if pid is not None and pid not in ctx.allowed_partida_ids:
    return VisibilityDecision(False, "partida_not_allowed")
```

Con `admin_full` (regla 1) evaluada antes, la barrera de partida —igual que
la de workspace— **nunca se salta por conocimiento de personaje ni por
pertenencia a party**: un nodo sin `partida_id` (ausente o `None`) es capa
juego y siempre visible dentro de su workspace; retrocompatibilidad total con
el material actual (comprobado por test: `test_material_legado_sin_clave_
partida_id_visible_igual_que_hoy`).

### Por qué esto cubre TODA ruta sin tocarlas una a una

`viewer/app/authz/filtered_provider.py::PolicyFilteredProvider` ya envuelve
**todos** los métodos del `GraphProvider` (`list_entities`, `entity`,
`graph`, `search`, `counts`, `entity_types`, `list_sources`,
`source_detail`, `quality_metrics`, `relations_for_entity`) con
`VisibilityPolicy.filter_nodes`/`can_view`/`filter_edges`; y **todas** las
rutas HTML y de API (`routers/readonly.py`, `routers/reviews_console.py`,
`routers/v3_review.py`, `api/entities.py`, `api/graph.py`) obtienen su
provider vía `Depends(get_filtered_provider)`. Añadir la regla 2b al motor
de política y poblar `active_partida`/`allowed_partida_ids` en
`app.authz.dependencies.get_visibility_context` (leído de
`request.state.session.active_partida`) basta para que el aislamiento
alcance cada ruta existente y cualquier ruta nueva que use el mismo
provider filtrado — no hay un `if` suelto por endpoint.

**Rutas cubiertas** (todas pasan por `get_filtered_provider`):
`/entities`, `/entities/{id}`, `/api/entities`, `/api/entities/{id}`,
`/graph`, `/api/graph`, `/sources`, `/sources/{id}`, `/api/sources`,
`/api/sources/{id}`, `/quality`, `/api/quality`, `/reviews*` (consola de
revisión), `/v3/review*`. Verificado con tests de nivel API (JSON), no solo
plantillas.

**No cubierto / fuera de alcance deliberado**: `jobs`/`status` (no leen del
`GraphProvider`, no hay material de grafo que aislar); simulación "ver como
personaje" (`context_for_simulated_character`) no recibe partida activa —
queda restringida a capa juego durante la simulación, comportamiento
conservador, no una omisión; el propio fog of war por conocimiento de
personaje (M5b) sigue sin implementar, como pedía el encargo.

### Selector de partida

Nuevo router `viewer/app/routers/partida.py`: `POST /partida/select`
(formulario `partida_id` + CSRF), autenticado, escribe `sessions.
active_partida` (`""` o ausente = limpiar -> volver a capa juego). Un
usuario no-admin solo puede seleccionar una partida de las que tiene
asignadas (`auth_db.user_allowed_partidas`); intentarlo con otra -> 403,
auditado igual que el resto de acciones de auth
(`audit.PARTIDA_SELECTED`).

UI: dropdown en `base.html` (nav superior), poblado desde
`request.state.user_partidas` — calculado una vez por petición en
`AuthMiddleware.dispatch` (mismo punto donde ya se resolvían `user`/
`session`), para no tener que acordarse de pasarlo en el contexto de cada
plantilla de cada router. Al elegir, el `<select>` se auto-envía
(`onchange="this.form.submit()"`, con `<noscript>` de respaldo).

Efecto colateral corregido: el token CSRF del formulario de logout y del
nuevo selector dependían de que cada ruta pasara `csrf_token` explícitamente
al contexto de plantilla — cierto en `admin`/`reviews_console`/`v3_review`,
pero **no** en `readonly.py` (`/entities`, `/sources`, `/quality`), donde ya
era un hueco preexistente (logout roto en esas páginas). Se añadió
`request.state.csrf_token`, calculado una vez en el middleware igual que
`csrf_raw`, y `base.html` usa `csrf_token | default(request.state.csrf_token,
true)`: la variable de contexto explícita gana si existe, si no cae al valor
del middleware. Corrige el hueco preexistente de logout como efecto
colateral positivo, no como objetivo del bloque.

### Panel admin

`GET/POST /admin/partidas` (`viewer/app/routers/admin.py`, plantilla nueva
`auth/admin/partidas.html`): listar todas las asignaciones, conceder
(usuario + workspace + partida_id) y revocar, con auditoría
(`audit.PARTIDA_ACCESS_GRANTED`/`PARTIDA_ACCESS_REVOKED`). Enlazado desde
`/admin/users` y desde la nav de admin.

### Tests

`viewer/tests/test_multipartida_isolation.py` (motor puro +
`PolicyFilteredProvider` sobre `viewer/tests/fixtures/
multipartida_graph.json`, fixture nueva con 2 partidas + capa juego +
material "legado" sin la clave `partida_id` en absoluto): capa juego visible
sin partida activa; partida ajena oculta; partida propia visible con ella
activa; nunca cruce entre `partida:uno` y `partida:dos`; `admin_full` salta
la barrera; conocimiento de personaje NO la salta; listado/conteo/grafo/
acceso-por-id/búsqueda todos filtran igual.

`viewer/tests/test_multipartida_e2e.py` (HTTP real: login, cookie de sesión,
DB de auth real, sin overrides de dependencia): usuario sin asignación ve
solo capa juego; selector cambia la vista y aísla partidas de verdad a
través de `/api/entities`; seleccionar una partida no asignada -> 403 y la
vista no cambia; admin gestiona asignaciones (conceder/revocar) con
auditoría verificada en `audit_events`; no-admin no accede a
`/admin/partidas` (403); admin ve ambas partidas a la vez sin selector
(bypass de `admin_full`, coherente con el resto del programa).

Ninguna suite existente del viewer se movió. Recuento del viewer solo:
446 passed, 1 skipped.

**Recuento exacto de suite completa** (`python3 -m pytest -p no:randomly -q`
desde la raíz, primer plano): **6558 passed, 53 skipped, 4 xfailed,
0 failed** (21 tests nuevos netos sobre los 6537 anteriores).

### Decisiones discutibles

1. **`allowed_partida_ids` como conjunto de a lo sumo un elemento** (la
   partida activa), no todas las asignadas al usuario. Alternativa
   descartada: mostrar la unión de todas sus partidas asignadas a la vez.
   Se eligió la vista de una sola partida activa porque es lo que pide el
   encargo ("cambia la partida activa de la sesión") y porque mezclar dos
   partidas en una misma vista sin fog of war (M5b) haría más fácil
   confundir origen del material — decisión reversible si un caso de uso
   real pide ver varias a la vez.
2. **Tabla propia en `auth.db` en vez de extender `access_store.py`**,
   pese a que el diseño (§2.6) preveía esto último como ya "resuelto por el
   operador". Documentado arriba con el razonamiento completo; si M5b
   necesita después leer `access_store.py` (para `user_character_link`/
   `user_workspace_permission`, que sí son necesarios para el conocimiento
   de personaje), esa integración se revisará entonces — no se adelantó
   aquí porque M5a no la necesita y el diseño original identifica que ni
   siquiera el grafo V3 escribe hoy las propiedades que esa pieza
   consumiría (§2.7).
3. **Admin no está sujeto a `allowed_partida_ids`** (bypass total vía
   `admin_full`, igual que ya ocurre con workspace/secret/narrator/future):
   un admin ve las dos partidas simultáneamente sin selector. Coherente con
   el resto del motor de política, pero significa que el panel admin no
   sirve hoy para que un narrador "vea como" una partida concreta —
   eso ya existe como función separada (`context_for_simulated_character`,
   "ver como personaje") y no se ha conectado a partida activa porque es
   una simulación de M5b (personaje), no de M5a (partida).

### 13.1 Rework de seguridad de M5a (ronda adversarial)

La suite adversarial de M5a encontró tres huecos P0 en superficies que **no
pasan por `PolicyFilteredProvider`** y en el ciclo de vida del acceso. Los tres
están corregidos; la suite adversarial verifica ahora el comportamiento
corregido (no hay tests rojos ni tests que documenten un agujero vigente).

**Mecanismo central nuevo: `viewer/app/authz/scope.py` (`VisibilityScope`).**
No es un `if` por ruta: es el punto único donde el material que no viene del
`GraphProvider` (contratos de revisión v1, propuestas y glosario V3, cola de
jobs) se contrasta con el MISMO motor `VisibilityPolicy.can_view`, normalizando
cada registro a las dos barreras que nunca se saltan (workspace, partida). Se
inyecta como dependencia FastAPI (`get_visibility_scope`) igual que
`get_filtered_provider`, y los servicios lo reciben como parámetro `scope`, de
modo que el filtro se aplica **en la capa de datos**, antes de listar, contar o
entregar por id.

1. **P0-1 — `/review-console` (v1) y `/v3/review` no filtraban por partida.**
   Ambos filtraban solo por `workspace`. Ahora:
   - `review_console.list_source_summaries/get_source_summary/list_candidates/
     get_candidate/get_ingest_plan/plan_preview/submit_decision` aceptan
     `scope` y filtran; una fuente fuera de ámbito responde **404**
     (indistinguible de inexistente, mismo contrato que
     `PolicyFilteredProvider.entity`), y `submit_decision` **rechaza** decidir
     sobre un candidato ajeno aunque se conozcan su id y su hash.
   - `ReviewService.workspaces/queue/record/undo_last/glossary_candidates`
     aceptan `scope`. El filtro se aplica antes de calcular `total`/`remaining`
     (un conteo también delata material invisible). Los candidatos de glosario
     nacidos de una propuesta de partida quedan **estampados** con su
     `partida_id` para que hereden el mismo aislamiento.
   - Los documentos v1 son cerrados (`additionalProperties: false`) salvo
     `metadata`: ahí es donde declaran su partida, y `VisibilityScope` la busca
     también en esa ruta.

2. **P0-2 — `/api/jobs` sin filtro de ámbito ni recorte de detalle.** La
   dependencia `require_api_authenticated_user` ya estaba en el
   `include_router`, pero la consulta de la cola no aplicaba las barreras de
   ámbito ni recortaba el detalle operativo por rol. Ahora `/api/jobs`, `/api/jobs/counts`,
   `/api/jobs/{id}`, `/jobs` y `/jobs/{id}` (HTML) pasan por el ámbito
   (`jobs_client.scoped_jobs/scoped_job/scoped_counts`): lo que no es visible no
   se lista, no se cuenta y por id responde `job_not_found`. Además, para quien
   no es admin el job se **recorta** a campos operativos inocuos (estado,
   tiempos, contadores) más `has_error`: sin `payload`, sin `result`, sin
   `error_message`, sin rutas.

   > **Endurecimiento pendiente en la versión desplegada.** Este endurecimiento
   > no es exclusivo de la rama de multipartida: conviene incorporarlo también a
   > la línea desplegada. Los detalles operativos y la prioridad quedan fuera de
   > este documento; el operador los tiene registrados aparte para planificar el
   > despliegue de V3.

3. **P0-3 — revocar el acceso no invalidaba la sesión activa.**
   `get_visibility_context` construía `allowed_partida_ids` desde
   `session.active_partida` sin volver a comprobar `partida_access`. Ahora
   `authz/dependencies.py` re-verifica **en cada petición** (una consulta a
   `auth.db`, SQLite local con índice único) y, si el acceso ya no existe,
   degrada a capa juego y **limpia** `sessions.active_partida`. Fail-closed si
   la comprobación no se puede hacer. Volver a conceder el acceso no reactiva
   sola la partida: hay que seleccionarla de nuevo.

4. **P1 — validaciones baratas.** Un admin ya no puede fijar una partida
   inexistente (`partida_exists`, 400); `partida_id` en blanco tiene semántica
   explícita y fail-closed en los dos sentidos: un nodo con `partida_id: ""`
   (dato corrupto: el esquema knowledge-v3 lo rechaza desde M2) **nunca** es
   visible (`partida_id_blank`), y un `active_partida` en blanco se normaliza a
   capa juego, nunca a un comodín. Seleccionar la cadena vacía en el selector
   significa "salir de la partida" y se almacena como `NULL`.

**Recuento exacto de suite completa** (`python3 -m pytest -p no:randomly -q`
desde la raíz, primer plano): **6585 passed, 53 skipped, 4 xfailed, 0 failed**
(antes del rework: 6569 passed + 1 failed, el canario en rojo).

### Decisiones discutibles del rework

4. **Los corpus de revisión se filtran por partida, no por workspace.** El
   campo `workspace` de un documento v1 / de una propuesta V3 es una etiqueta
   del corpus de laboratorio, no un workspace del visor (hoy
   `allowed_workspaces` es siempre `{S9K_DEFAULT_WORKSPACE}`). Compararlos
   habría dejado los dos paneles de revisión en blanco para todo revisor con
   auth activada, sin ganancia para el aislamiento que M5a persigue. Por eso
   `VisibilityScope.partida_only()` es lo que usan esos servicios, mientras que
   la cola de jobs —que sí es material operativo de este despliegue— aplica las
   dos barreras. Revisable cuando exista un modelo real de "usuario → varios
   workspaces".
5. **Re-verificación por petición con una consulta a SQLite.** Se eligió
   corrección inmediata frente a coste: una lectura indexada por petición sobre
   una base local. Si algún día el volumen lo pide, la alternativa es una caché
   con TTL corto o invalidación por evento de revocación — pero eso reintroduce
   una ventana de exposición, que es justo lo que este P0 corrige.
6. **Recorte del detalle de jobs por rol, no por partida.** Un revisor con su
   partida activa ve QUÉ hay en su cola y cómo va, pero no el `payload` ni el
   `error_message` crudos, porque ambos pueden contener rutas del servidor u
   otra información de operación. El detalle completo queda para admin.
   Alternativa descartada: sanear el payload campo a campo (frágil, y falla
   abierto en cuanto el data-engine añade una clave nueva).
