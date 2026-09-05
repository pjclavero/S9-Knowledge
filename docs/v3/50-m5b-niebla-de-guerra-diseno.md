# 50 — Diseño: M5b, niebla de guerra (visibilidad por conocimiento de personaje)

Estado: **DISEÑO, sin código de producción.** Este documento no implementa
nada; propone. Autor: AGENTE-DISEÑADOR (bloque M5b). Base: `main` `fb4a6fe`
(M0, M2, M3, M4, M5a ya mergeados — ver `docs/v3/49-multipartida-diseno.md`
§§8-13, que es la referencia obligatoria de este documento y a la que se
remite constantemente en vez de repetir contenido).

**Regla dura respetada en todo el documento:** no se toca `extraction/`,
`engine/` (factividad, shadow, temporal, negación, decisión) ni
`eval/gate6_*` — sigue vigente la advertencia de `docs/v3/49` §0. Tampoco se
implementa el motor ni se modifica ningún contrato existente: los esquemas
que se muestran más abajo están explícitamente marcados **PROPUESTA** y
viven aparte, en `docs/v3/schemas-propuestos/`. No se incluyen credenciales,
IPs internas, rutas de servidor ni detalles explotables de fallos vigentes.

---

## 1. Resumen y objetivo

M5a (mergeado, `docs/v3/49` §13) resuelve **a qué partida se puede entrar**:
un usuario sin acceso concedido a `partida:Y` no ve nada de esa partida —
aislamiento entre partidas, barrera dura en `VisibilityPolicy.can_view`
(`viewer/app/policies/engine.py`, regla 2b).

M5b resuelve un problema distinto y **posterior**: dentro de una partida ya
concedida, ¿ve el jugador de Bayushi Hisao un hecho que su personaje nunca
presenció? Hoy la respuesta es sí — cualquier miembro de la partida ve todo
el contenido de esa partida más la capa juego, porque `VisibilityPolicy` no
tiene todavía ninguna noción de "conocimiento de personaje" real (ver
evidencia de código, `docs/v3/49` §2.7: "confirma la frase de
`07-users-permissions.md`: aplicación real de los filtros: pendiente").

**Niebla de guerra** = que la vista de un usuario dentro de su partida se
recorte, además, a lo que su personaje activo sabe (o su grupo sabe, o es de
dominio público), ocultando el resto de forma indistinguible de que no
exista — el mismo contrato de "no visible = 404/vacío" que M5a ya adopta
(`viewer/app/authz/scope.py`, docstring: "ni en listados, ni en conteos, ni
por ID").

Relación con M5a: M5b es un filtro **adicional**, dentro del ámbito que M5a
ya delimita. La cadena de barreras que evalúa `VisibilityPolicy.can_view` es
`admin_full` → `workspace` → `partida` (M5a) → **conocimiento de personaje
(M5b, propuesto)** → nivel de visibilidad → sesión futura → party. M5b no
sustituye ninguna regla existente: añade una regla nueva en el mismo motor,
en el mismo sitio donde el motor ya evalúa `visibility`/`party`/
`session_index`/`known_by` (`viewer/app/policies/engine.py`, líneas 66-90 en
`fb4a6fe`) — un motor que, como documenta `docs/v3/49` §2.7, **ya existe y
ya sabe leer estas propiedades**, pero hoy las evalúa siempre sobre nodos
donde no están presentes.

---

## 2. Modelo de datos exacto

Se proponen tres campos, con semántica cerrada y versionada, en los
contratos de la cadena V3 que llevan hasta el nodo/relación final
(`ClaimProposal`, `FactAssertion`/`GraphMutationPlan` — ver §5 para el
mapeo exacto):

### 2.1 `known_by_scope` (enum, closed)

```
GLOBAL | GAME | CAMPAIGN | SESSION | CHARACTER | FACTION | GM_ONLY | UNKNOWN
```

Quién produjo/registró este conocimiento en primera instancia — el ámbito
mínimo en el que nació:

- `GLOBAL` — de dominio público en el mundo ficticio (equivalente a
  `known_publicly=true` del diseño legacy, §4.1 de
  `docs/current/KNOWLEDGE_VISIBILITY_DESIGN.md`).
- `GAME` — lore compartido del juego (capa juego de M0/M5a,
  `partida_id IS NULL`); no confundir con `GLOBAL`: `GAME` puede ser lore
  que ningún personaje conoce todavía dentro de la ficción.
- `CAMPAIGN` — de la partida entera, sin personaje concreto asociado (p. ej.
  un anuncio del narrador leído en voz alta a toda la mesa).
- `SESSION` — nació en una sesión concreta, aplicable a quienes estuvieron
  presentes (ver `visibility_scope=CAMPAIGN`+`session_index`, no un valor
  propio: `SESSION` describe el origen, no el filtro de "hasta qué sesión").
- `CHARACTER` — conocimiento de uno o más personajes concretos (el caso del
  Oni: `Kakita_Asuka`/`Kimi` tras el combate).
- `FACTION` — conocido por una facción/organización, no por personajes
  individuales con nombre (p. ej. "el clan Kakita sabe que...").
- `GM_ONLY` — solo el narrador/GM; nunca visible a jugadores salvo
  `ADMIN_ONLY` explícito en `visibility_scope`.
- `UNKNOWN` — el origen no se ha determinado (ver regla fail-closed abajo).

### 2.2 `visibility_scope` (enum, closed)

```
PUBLIC | WORKSPACE | CAMPAIGN | SUBJECTS | ADMIN_ONLY | DENY
```

A quién se le **permite ver** este dato, independientemente de quién lo
produjo. Es el eje de decisión de acceso, ortogonal a `known_by_scope`:

- `PUBLIC` — cualquiera con acceso a la capa juego lo ve (equivalente a
  `GLOBAL` en la práctica, pero como campo de política, no de origen).
- `WORKSPACE` — cualquiera con acceso al juego, sin necesidad de personaje
  ni partida (uso previsto: material de referencia del juego en sí, reglas).
- `CAMPAIGN` — cualquiera con personaje activo en esa partida concreta (el
  nivel 1 del diseño legacy, §2 de `KNOWLEDGE_VISIBILITY_DESIGN.md`).
- `SUBJECTS` — solo los sujetos explícitos listados en
  `visibility_subjects` (el nivel 2, conocimiento de personaje).
- `ADMIN_ONLY` — solo administrador/narrador (`admin_full`), nunca un
  jugador aunque figure en `visibility_subjects` por error de datos.
- `DENY` — nunca visible a nadie salvo lectura directa por operador con
  herramienta administrativa fuera del visor (uso previsto: dato retirado o
  en revisión, no un valor operativo normal del visor de jugador).

### 2.3 `visibility_subjects` (lista de IDs)

IDs explícitos de personajes y/o facciones autorizados, solo relevante
cuando `visibility_scope=SUBJECTS`. Cada elemento es un ID estable de
personaje (`character_id`, mismo espacio de IDs que
`user_character_link.character_id` en `access_store.py`) o de facción
(`faction:<id>`, prefijo explícito para no confundir espacios de nombres —
mismo patrón que `partida:<id>` de M0). Lista vacía con
`visibility_scope=SUBJECTS` es indistinguible de "nadie": fail-closed (ver
§2.4).

### 2.4 Regla fail-closed cerrada

**`UNKNOWN`, campos ausentes, o cualquier combinación inválida ⇒ SIEMPRE no
visible, nunca público.** En concreto:

| Condición | Resultado |
|---|---|
| `known_by_scope` ausente | tratado como `UNKNOWN` |
| `known_by_scope=UNKNOWN` | nunca contribuye a decidir "conocido por X"; el nodo solo puede ser visible por `visibility_scope=PUBLIC/WORKSPACE`/`ADMIN_ONLY` explícito, nunca por inferencia de conocimiento |
| `visibility_scope` ausente | tratado como `DENY` |
| `visibility_scope=SUBJECTS` con `visibility_subjects` vacía o ausente | `DENY` efectivo (ningún sujeto = nadie autorizado) |
| `visibility_scope` con valor fuera del enum cerrado (dato corrupto) | `DENY` — mismo criterio que `partida_id` en blanco en M5a rework (`docs/v3/49` §13.1 punto 4: "un nodo con `partida_id: ""` ... nunca es visible") |
| combinación incoherente (p. ej. `visibility_scope=PUBLIC` pero `known_by_scope=GM_ONLY`) | se resuelve por `visibility_scope` (es el eje de *acceso*), pero se marca como incoherencia para auditoría — ver §12, no se rechaza en lectura (el visor no corrige datos, solo los filtra) |

Esto es una inversión deliberada de "público por defecto": el sistema hoy
(pre-M5b) trata todo dentro de una partida como visible por defecto una vez
franqueada la barrera de M5a. M5b invierte esa por defecto a **oculto**
salvo declaración explícita — es el cambio de fondo que introduce la niebla
de guerra, y es coherente con el resto del programa (`docs/v3/49` cita
"deny-by-default" como criterio en cada bloque: M2 §10, M3 §11, M5a §13.1).

---

## 3. Matriz de decisión de visibilidad

Contexto de evaluación: usuario autenticado, `workspace` activo, `partida_id`
activo (o ausente = capa juego), personaje activo del usuario en esa
partida (`character_id` o ausente), concesión de partida vigente (M5a,
`partida_access` en `auth.db`), rol (`admin`/jugador).

| `known_by_scope` (origen) | `visibility_scope` (acceso) | `visibility_subjects` | ¿Personaje activo en subjects? | ¿Admin? | Visible |
|---|---|---|---|---|---|
| cualquiera | `PUBLIC` | — | — | — | **Sí**, siempre, para cualquiera con acceso a la capa juego |
| cualquiera | `WORKSPACE` | — | — | — | **Sí**, para cualquiera con acceso al juego (no requiere partida ni personaje) |
| cualquiera | `CAMPAIGN` | — | — | — | **Sí**, si el usuario tiene concesión vigente + partida activa = la partida del dato; **No** en otra partida o sin partida activa |
| `CHARACTER`/`FACTION` | `SUBJECTS` | `[P1, P2]` | Sí | — | **Sí** |
| `CHARACTER`/`FACTION` | `SUBJECTS` | `[P1, P2]` | No | No | **No** |
| cualquiera | `SUBJECTS` | `[]` o ausente | — | No | **No** (fail-closed, §2.4) |
| `GM_ONLY` | `ADMIN_ONLY` | — | — | Sí | **Sí** |
| `GM_ONLY` | `ADMIN_ONLY` | — | — | No | **No** |
| cualquiera | `DENY` | — | — | Sí (admin_full) | Depende de si el visor de jugador aplica `DENY` también a admin — **decisión de diseño: `DENY` es absoluto, ni admin lo ve por el visor normal** (ver §12, hueco de diseño 4) |
| cualquiera | `DENY` | — | — | No | **No** |
| cualquiera | ausente | — | — | No | **No** (tratado como `DENY`, §2.4) |
| `UNKNOWN` | ausente/inválido | — | — | No | **No** |
| cualquiera | válido | — | — | Sí (admin_full) | **Sí**, salvo `DENY` (bypass total, coherente con `docs/v3/49` §13 "Admin no está sujeto a `allowed_partida_ids`") |
| cualquiera | `CAMPAIGN`/`SUBJECTS` | — | — | usuario sin concesión vigente en esa partida (M5a) | **No** — M5a ya lo bloquea antes de llegar a esta regla (fail-fast, la evaluación de M5b nunca se alcanza) |

Nota sobre orden de evaluación: esta matriz asume que las barreras
anteriores (workspace, partida M5a) ya se evaluaron y pasaron — M5b es la
regla siguiente en la cascada, no sustituye ninguna anterior (§4).

---

## 4. Autoridad de los campos: dónde se corta la de los modelos externos

Los tres campos (`known_by_scope`, `visibility_scope`, `visibility_subjects`)
son **decisión de escritura**, no de lectura. El punto de corte de autoridad
de un modelo de IA (NVIDIA, Ollama, cualquier proveedor externo) es exacto y
único: **admisión del `GraphMutationPlan` en el writer**
(`data-engine/app/knowledge_v3/writer/admission.py`), el mismo punto donde
hoy se corta la autoridad de cualquier `ClaimProposal` para decidir si algo
se escribe (`docs/v3/09-writer.md`; ver también el patrón ya establecido en
`docs/v3/47-acuerdo-det-nvidia.md`: NVIDIA opina en sombra, nunca decide).

Cadena de autoridad, explícita:

1. **Un modelo (determinista o NVIDIA/Ollama) puede PROPONER** un valor de
   `known_by_scope`/`visibility_subjects` como parte de una `ClaimProposal`
   — es una hipótesis, con su propio `confidence`, igual que cualquier otro
   campo de `claim.py` (`predicate_candidates`, `epistemic_status_hint`).
   Este es exactamente el "hueco (c)" que `docs/v3/49` §2.7 señala como no
   resuelto: de dónde sale la propuesta de conocimiento (ver §14).
2. **El motor de decisión determinista (`engine/decision.py`, fuera de
   alcance de este documento y de M5b) puede aceptar/rechazar/marcar para
   revisión** la propuesta, con el mismo criterio fail-closed que ya aplica
   a factividad — pero **NO** decide visibilidad por sí solo: solo decide si
   el claim se convierte en `FactAssertion` candidata.
3. **El punto de decisión real de visibilidad es la admisión del
   `GraphMutationPlan`** (`writer/admission.py`): un plan que declare
   `visibility_scope=SUBJECTS` sin `visibility_subjects`, o `GM_ONLY`+
   `PUBLIC` incoherente, se rechaza en admisión con el mismo patrón que
   `PLAN_SCOPE_CROSS_PARTIDA` (M3) o `PLAN_LOCAL_OVERRIDE_FROM_GAME_LAYER`
   (M4) — **estructural, sin tocar Neo4j, fail-closed**.
4. **Por defecto, cualquier plan cuyo origen de `known_by_scope`/
   `visibility_scope` sea una propuesta de IA (no confirmada por un humano)
   entra con `review_required=True`** — mismo campo ya existente en
   `ClaimProposal` (`claim.py`, presente desde antes de M0) y mismo patrón
   que M4 usa para `LOCAL_DIVERGENCE` (`docs/v3/49` §12: "review_required
   por defecto en la propuesta"). Un humano (narrador/revisor en el panel
   `/v3/review` o `/review-console`) confirma o corrige antes de que la
   propuesta se convierta en decisión operativa del writer para casos donde
   el resultado de la propuesta sea `GM_ONLY`→`SUBJECTS`/`PUBLIC` (una fuga
   de secreto es más cara que un falso oculto — ver §11 canales laterales).
5. **El backend (visor) nunca vuelve a preguntar al modelo de IA**: lee
   exclusivamente lo que el writer selló en Neo4j (`known_by_scope`,
   `visibility_scope`, `visibility_subjects` como propiedades planas del
   nodo/relación, mismo patrón que `partida_id`/`visibility`/`party` de hoy).

**Resumen de una línea**: la IA propone dentro de un `ClaimProposal`; el
motor determinista decide si el claim vive; **el writer, en admisión,
decide si la declaración de visibilidad es válida y se sella**; el visor
solo lee lo sellado. Ningún punto de la cadena permite que un modelo externo
escriba directamente una propiedad de visibilidad en Neo4j sin pasar por
admisión.

---

## 5. Plan de propagación end-to-end

Cadena completa y ficheros concretos a tocar en cada eslabón (todo
**PROPUESTA**, ningún fichero se toca en este documento):

| Eslabón | Fichero(s) concreto(s) | Cambio propuesto |
|---|---|---|
| **Fuente** | `data-engine/app/knowledge_v3/contracts/source_asset.py` | Sin cambio — la fuente no declara conocimiento de personaje, solo procedencia. |
| **Episode** | `data-engine/app/knowledge_v3/contracts/episode.py` | Opcional: `participants: list[str] = None` (IDs de personaje presentes/mencionados en el episodio) — es la señal más barata para derivar `known_by_scope=CHARACTER` sin NLP nuevo (ver hueco §14: quién estuvo presente es dato de calendario de sesión, no de extracción de texto). Campo opcional, `OMIT_IF_NONE`, mismo patrón que M0. |
| **EvidenceSpan** | `data-engine/app/knowledge_v3/contracts/evidence.py` | Sin cambio estructural necesario — el span ya referencia el episodio (`episode_id`), de donde M5b puede heredar `participants` sin campo propio. |
| **ClaimProposal** | `data-engine/app/knowledge_v3/contracts/claim.py` | Campos nuevos opcionales: `known_by_scope_hint: Optional[str] = None`, `visibility_scope_hint: Optional[str] = None`, `visibility_subjects_hint: Optional[list[str]] = None` — sufijo `_hint` deliberado: son PROPUESTA de un modelo (§4), no la decisión sellada. Añadidos a `OMIT_IF_NONE` (línea 38 en `fb4a6fe`). Esquema: `contracts/knowledge-v3/v1/claim-proposal-v3.schema.json`. |
| **FactAssertion** | `data-engine/app/knowledge_v3/contracts/assertion.py` | Campos nuevos, ya sin sufijo `_hint` porque en este contrato representan la afirmación decidida (no la propuesta cruda): `known_by_scope: Optional[str] = None`, `visibility_scope: Optional[str] = None`, `visibility_subjects: Optional[list[str]] = None`. Esquema: `contracts/knowledge-v3/v1/fact-assertion-v3.schema.json`. |
| **TemporalLedger** | `data-engine/app/knowledge_v3/ledger/temporal.py`, `data-engine/app/knowledge_v3/ledger/supersession.py` | Nueva razón canónica en `CANONICAL_REASONS` (línea 76+ en `fb4a6fe`), p. ej. `VISIBILITY_EXPANDED` (ver §7) — no muta el hecho, es una transición de metadatos, análoga a `LOCAL_DIVERGENCE` de M4 pero sin puntero de override: cambia `visibility_scope`/`visibility_subjects` en una nueva versión del hecho, dejando traza de cuándo cambió. |
| **GraphMutationPlan** | `data-engine/app/knowledge_v3/contracts/mutation_plan.py`, `data-engine/app/knowledge_v3/writer/admission.py` | Props de creación/actualización llevan `known_by_scope`/`visibility_scope`/`visibility_subjects` como props del nodo/relación (mismo mecanismo genérico de dict que ya acepta `create_entity`/`create_assertion`, `docs/v3/49` §2.7: "`writer/cypher.py` escribe props genéricos... técnicamente *podría* llevar esas propiedades"). `admission.py` gana un punto nuevo de validación estructural (§4 punto 3), código nuevo en `writer/codes.py` p. ej. `PLAN_VISIBILITY_INCOHERENT`. |
| **Writer → Neo4j** | `data-engine/app/knowledge_v3/writer/cypher.py`, `writer/schema.py` | `create_entity`/`create_assertion`/`project_relation` estampan las tres propiedades igual que ya estampan `partida_id` (M3). Índice nuevo (no constraint) sobre `visibility_scope` si el volumen de consulta por ese campo lo justifica — mismo criterio que el índice de `partida_id` de M3 (`docs/v3/49` §11: "no constraint... se añade un índice"). |
| **Servicios backend** | `viewer/app/policies/models.py`, `viewer/app/policies/engine.py` | `ViewerContext` gana `active_character_id: Optional[str]`, `character_faction_ids: frozenset[str]` (poblados desde `access_store.py`/`user_character_link`, ver §15). `VisibilityPolicy.can_view` gana la regla nueva "2c — conocimiento de personaje" **entre** la 2b (partida, M5a) y la 3 (nivel de visibilidad) — mismo lugar en la cascada fail-fast, mismo criterio "nunca se salta". |
| **API** | `viewer/app/api/entities.py`, `viewer/app/api/graph.py`, `viewer/app/api/jobs.py`, `viewer/app/authz/filtered_provider.py` | Sin tocar firma del `GraphProvider` (mismo patrón que M5a, `docs/v3/49` §13: "el provider base sigue devolviendo... `PolicyFilteredProvider` filtra"); `PolicyFilteredProvider` ya envuelve todos los métodos con `VisibilityPolicy`, así que la regla nueva se propaga sin tocar cada endpoint uno a uno. |
| **Visor (rutas no-grafo)** | `viewer/app/authz/scope.py` | `VisibilityScope.allows()` gana la misma comprobación de conocimiento de personaje que `allows_partida()`, para que `/review-console`, `/v3/review` y `/api/jobs` respeten la niebla de guerra igual que ya respetan M5a (mismo mecanismo único, `docs/v3/49` §13.1: "el punto único donde el material... se contrasta con la política"). |
| **Selector de personaje** | `viewer/app/routers/partida.py` (o router nuevo `viewer/app/routers/character.py`) | Endpoint nuevo análogo a `POST /partida/select`: `POST /character/select`, escribe `sessions.active_character_id`, valida contra `access_store.py`/`user_character_link` (ver §8). |
| **Panel admin** | `viewer/app/routers/admin.py` | Extensión de `/admin/partidas` o panel nuevo `/admin/visibility` (recuperando el `/control/visibility` del diseño legacy, `KNOWLEDGE_VISIBILITY_DESIGN.md` §11) para marcar manualmente conocimiento cuando la derivación automática (hueco §14) no cubre un caso. |

---

## 6. Aplicación backend obligatoria en TODAS las rutas

Mismo criterio que M5a (`docs/v3/49` §13: "no hay un `if` suelto por
endpoint"): la regla de conocimiento de personaje se implementa **una vez**
en `VisibilityPolicy.can_view` y **una vez** en `VisibilityScope.allows()`,
y se propaga automáticamente porque:

- **Listas/detalles/recuperación por ID/conteos**: `PolicyFilteredProvider`
  ya envuelve `list_entities`, `entity`, `graph`, `search`, `counts`,
  `entity_types`, `list_sources`, `source_detail`, `quality_metrics`,
  `relations_for_entity` (`docs/v3/49` §13, lista verificada de métodos).
  Ninguno de estos necesita tocarse individualmente para M5b: heredan la
  regla nueva del motor.
- **Búsqueda/autocompletado**: mismo `search()` del provider — un secreto
  buscado por nombre exacto debe devolver **0 resultados**, no un resultado
  con campos vacíos (§11, caso de prueba dedicado).
- **Relaciones/vecinos del grafo**: `filter_edges`/`relations_for_entity`
  exigen que **ambos extremos** sean visibles, mismo criterio que el
  diseño legacy exige para relaciones (`KNOWLEDGE_VISIBILITY_DESIGN.md` §7,
  punto 1) — una assertion oculta conectada a una entidad visible no debe
  aparecer como arista, ni siquiera como "relación desconocida" con conteo.
- **Historial/evidencias/fuentes**: mismo criterio — una fuente cuyo único
  contenido es `GM_ONLY` no debe aparecer en `/sources` para un jugador sin
  ese conocimiento; si la fuente mezcla contenido visible y oculto, se
  muestra solo el visible (recorte parcial, no todo-o-nada por fuente).
- **Sesiones**: el índice de sesión (`session_index`, ya existente en el
  motor) sigue aplicando como hoy (regla 4), en cascada con la regla nueva.
- **Exportación**: cualquier exportador debe consumir el mismo
  `PolicyFilteredProvider`/`VisibilityScope`, nunca leer directamente el
  `GraphProvider` sin filtrar — riesgo señalado explícitamente en §11 (caso
  "exportación").
- **Respuestas de chat / embeddings / Graph RAG futuro**: fuera del código
  actual (no existe todavía en V3), pero el requisito de diseño para
  cualquier futuro consumidor de este tipo es el mismo: debe construirse
  **sobre** `PolicyFilteredProvider`/`VisibilityScope`, nunca sobre el
  `GraphProvider` crudo ni sobre un índice de embeddings que no sepa
  recalcular visibilidad por usuario — un embedding calculado sobre texto
  con conocimiento oculto y expuesto en un RAG sin filtro por consulta es
  una fuga estructural, no reparable después con un filtro de salida sobre
  el texto generado. Este punto queda como **hueco de diseño explícito**
  (§14): la arquitectura de Graph RAG no existe aún, así que este documento
  solo puede fijar el requisito, no el mecanismo.

**Reiteración del contrato de indistinguibilidad** (igual que M5a,
`docs/v3/49` §13.1 P0-1): "no visible" es 404 en recuperación por ID,
colección vacía en listados/búsqueda, y conteo que excluye el registro
oculto **antes** de calcularse — nunca un conteo "total menos visibles"
expuesto al cliente (eso ya delata cuántos hay ocultos, ver §11 canales
laterales).

---

## 7. Descubrimiento posterior y temporalidad

Escenario de referencia (el mismo del diseño legacy, §8 de
`KNOWLEDGE_VISIBILITY_DESIGN.md`): un hecho nace `known_by_scope=GM_ONLY`,
`visibility_scope=ADMIN_ONLY` en la sesión 4. En la sesión 7, el narrador
decide que el grupo lo descubre. El hecho pasa a
`known_by_scope=CHARACTER`, `visibility_scope=SUBJECTS`,
`visibility_subjects=[P1, P2]`.

**Requisito duro: esto NO sobrescribe la historia.** Un jugador que consulta
el estado del grafo "tal como estaba en la sesión 5" debe seguir viendo el
hecho como `ADMIN_ONLY` en ese punto temporal, aunque hoy ya sea visible.

Mecanismo propuesto, reutilizando el `TemporalLedger` y el patrón ya
validado de M4 (`local_override_of`, no destructivo):

1. El cambio de visibilidad se registra como una **transición del ledger**,
   no como una mutación en sitio de la propiedad. Análogo a como M4 nunca
   muta el hecho de capa juego (`docs/v3/49` §2.5 punto 2: "el hecho de la
   capa juego no cambia de status... sigue vivo"), aquí el hecho **sí**
   puede tener una nueva versión de sus propiedades de visibilidad, pero esa
   versión se ata a `valid_from` = momento del descubrimiento (sesión 7),
   nunca reescribiendo `valid_from` original del hecho.
2. Razón canónica nueva en `CANONICAL_REASONS`
   (`ledger/supersession.py`): `VISIBILITY_EXPANDED` (el grupo aprende algo
   que antes no sabía) y su inversa, `VISIBILITY_RESTRICTED` (caso raro pero
   real: el narrador decide que algo se ocultó por error y debe replegarse —
   requiere revisión humana obligatoria, nunca automática).
3. El campo `known_from_session`/`known_from_date` del diseño legacy (§4.1
   de `KNOWLEDGE_VISIBILITY_DESIGN.md`) se recupera como metadato de la
   transición, no de la afirmación en sí: cuándo cambió la visibilidad se
   guarda en el ledger, igual que ya se guarda cuándo cambió el `status` de
   un hecho.
4. `LIVE_STATUSES` (`ledger/supersession.py`, ya existente) sigue
   gobernando qué versión del hecho es la "vigente" para lectura por
   defecto; una consulta temporal explícita ("cómo se veía en sesión N") es
   una capacidad **nueva** que no existe hoy en el visor — este documento no
   la diseña en detalle porque el visor V3 actual no tiene consulta temporal
   de estado histórico general (fuera del alcance verificado de
   `docs/v3/49`); se señala como hueco (§14).
5. Relación con `local_override_of` (M4): son mecanismos **distintos y no
   intercambiables**. `local_override_of` es "esta partida diverge del
   lore compartido, sin tocarlo" (aislamiento entre ámbitos horizontales).
   `VISIBILITY_EXPANDED` es "quién puede ver este hecho cambia con el
   tiempo dentro del mismo ámbito" (evolución vertical de acceso). Un hecho
   puede tener ambos a la vez (una partida diverge del lore Y, dentro de esa
   partida, el descubrimiento del divergente ocurre en sesión 7) — casos
   compuestos quedan fuera de este documento y se listan en §14.

---

## 8. Cambio de personaje del usuario

La autorización de lectura combina, en cascada y todas obligatorias (AND):

1. **Usuario autenticado** (`auth.db`, ya existente).
2. **Workspace activo** (ya existente, capa base del sistema).
3. **Campaña/partida activa** (M5a, `sessions.active_partida`, re-verificado
   en cada petición contra `partida_access` — `docs/v3/49` §13.1 P0-3).
4. **Personaje activo** (M5b, propuesto: `sessions.active_character_id`),
   validado contra la asignación usuario↔personaje vigente
   (`user_character_link.status IN ('approved','assigned')` en
   `access_store.py`, extendido con `partida_id` — ver §15).
5. **Concesión vigente** de ese personaje para esa partida — mismo mecanismo
   de re-verificación por petición que M5a aplicó para `partida_access`
   (§13.1 punto 3): revocar el vínculo usuario↔personaje debe degradar
   inmediatamente la sesión activa, no esperar a que expire una caché.
6. **Visibilidad del recurso** (`known_by_scope`/`visibility_scope`/
   `visibility_subjects` del nodo, evaluados contra el personaje activo del
   punto 4).

Un usuario con **dos personajes en la misma partida** (poco común en RPG de
mesa estándar, pero el modelo de M5a ya admite "varias filas" de asignación,
`docs/v3/49` §13) debe elegir **uno activo a la vez**, mismo patrón que
partida activa: "un usuario con dos partidas asignadas ve... solo una...
nunca las dos a la vez". Aplicado a personaje: ver simultáneamente lo que
saben dos personajes distintos del mismo jugador sería una fuga funcional
(el jugador "sabe" lo que ninguno de sus personajes por separado sabe) —
salvo mecánica de juego explícita que lo autorice, fuera de alcance.

---

## 9. Política de versionado de contratos

Aplicando el criterio de §9 de `docs/v3/49` (política ya usada por M0/M2/M3/
M4/M5a) a los campos propuestos en §5:

**Veredicto: M5b puede ser aditivo, sin bump de `CONTRACT_VERSION`**, con la
misma justificación que M0 estableció y M2-M5a repitieron:

1. `known_by_scope_hint`/`visibility_scope_hint`/`visibility_subjects_hint`
   en `ClaimProposal`, y `known_by_scope`/`visibility_scope`/
   `visibility_subjects` en `FactAssertion`, se añaden a `properties`
   **fuera** de `required`, con `default=None` en el dataclass y en
   `OMIT_IF_NONE` — el material existente (sin estos campos) serializa
   byte a byte igual que hoy. Cumple la condición 1 de `docs/v3/49` §9.
2. `additionalProperties: false` se mantiene intacto salvo por las claves
   nuevas — cumple la condición 2.
3. Ningún dato ya sellado en `heldout`/`negation-battery`/`benchmarks`
   necesita regenerarse: estos campos no participan hoy en ninguna decisión
   de esos datasets (son datasets de factividad/relación, no de
   visibilidad) — cumple la condición 3.

**Razón adicional específica de M5b, no cubierta por M0-M5a:** a diferencia
de `partida_id` (un solo campo, un solo eje binario), M5b introduce **tres**
campos con una relación de coherencia entre sí (§2.4). Esto NO exige bump
de esquema (los tres son opcionales y su ausencia es indistinguible del
estado actual), pero **sí exige** una regla de validación semántica nueva en
`admission.py` (§4 punto 3) — mismo patrón que M3 usó para `scope.layer`
coherente con `partida_id` (`docs/v3/49` §2.2), que tampoco requirió bump.

**Cuándo procedería bump mayor** (criterio de `docs/v3/49` §9, aplicado
aquí): si en una fase posterior estos campos pasan a ser **obligatorios**
para toda `FactAssertion` nueva (p. ej. "ningún hecho se admite sin
declarar `visibility_scope`"), o si `additionalProperties: false` deja de
poder proteger el contrato sin ellos. Eso sería una decisión de un bloque
de implementación futuro (posible M5b-2, ver §13), no de este diseño.

**Si se optara por bump** (documentado por completitud, aunque el veredicto
de arriba es aditivo): haría falta (a) adaptador desde `1.0.0` a `2.0.0` que
rellene `known_by_scope=UNKNOWN`/`visibility_scope=DENY` para todo documento
sin los campos (fail-closed por construcción, coherente con §2.4); (b)
compatibilidad explícita documentada (lector `2.0.0` debe seguir aceptando
`1.0.0` mientras conviva material antiguo); (c) fixture congelada de la
versión anterior (nuevo tag `v3-contracts-frozen-1.0.0-m5b`, si M5b llega a
tocar los ficheros bajo `contracts/knowledge-v3/v1/` — que si el veredicto
final es aditivo, sí los toca, y por tanto **sí** necesita el patrón de tag
de freeze de `docs/v3/49` §9, aunque no necesite bump de versión: aditivo y
"requiere nuevo tag de freeze" no son mutuamente excluyentes, como ya
demostró M2/M3/M4/M5a, todos aditivos y todos con tag nuevo).

---

## 10. Plan de migración

**El contenido actual del grafo es de prueba** (confirmado por el operador,
recogido también en `docs/v3/49` §4 para `partida_id`) — esto simplifica la
migración real de la misma forma que simplificó M6: no hay contenido de
producción con conocimiento de personaje real que deba preservarse con
mapeo cuidadoso.

**Regla dura, aun así: datos antiguos sin los campos NO se asumen
`PUBLIC`.** Aplicando §2.4 al material ya existente en el grafo (todo
material actual carece de `known_by_scope`/`visibility_scope`), el
comportamiento correcto de migración es:

- **Idempotente**: ejecutar el marcado dos veces produce el mismo estado
  (mismo criterio que M5a §13, `partida_id_blank` fail-closed y ya probado
  con `test_migracion_repetida` propuesto en §11).
- **Fail-closed**: material sin campos se marca, no se deja implícito.

Política propuesta por tipo de información, con justificación:

| Tipo de contenido | Marcado propuesto | Justificación |
|---|---|---|
| Contenido de prueba general (la mayoría del grafo actual) | `visibility_scope=WORKSPACE` con **flag de revisión pendiente** (`review_required=true` a nivel de nodo, o etiqueta operativa fuera del contrato de visibilidad) | Es contenido de prueba conocido como tal; bloquearlo del todo (`ADMIN_ONLY`) rompería demos/pruebas manuales sin necesidad — pero no se asume `PUBLIC` sin marca, para no naturalizar "ausente = público" como comportamiento por defecto del sistema real. |
| Afirmaciones de campaña con narrativa de sesión (si existieran datos reales de partida) | `ADMIN_ONLY` con revisión pendiente | Es el contenido con mayor probabilidad de tener spoilers o hechos que un narrador querría controlar antes de exponer — fail-closed más estricto por el coste asimétrico (una fuga de trama es cara; un falso oculto se corrige con un clic en el panel admin). |
| Contenido marcado explícitamente como secreto en el diseño legacy (`known_by_scope=narrator`/`secret`/`admin_only` en datos migrados de v1/v2, si aplica) | `ADMIN_ONLY` sin excepción, sin revisión "urgente" (ya está en el estado más restrictivo posible, no hay prisa) | Mismo criterio que ya aplica el motor legacy (`KNOWLEDGE_VISIBILITY_DESIGN.md` §6: "nunca ve, sin permiso explícito"). |

**Como es contenido de prueba, la operación real recomendada es la misma
que M6 (`docs/v3/49` §4): limpiar o marcar, con aprobación explícita del
operador antes de ejecutarse**, script de una sola pasada con `dry-run`
obligatorio primero. No se ejecuta como parte de un bloque de
implementación; es una operación aparte, gateada a esa aprobación —
igual que M6.

---

## 11. Batería de pruebas

Cada caso se especifica con qué verifica y con qué datos mínimos (fixture
tipo, no literal completo):

1. **Mismo usuario, distinto workspace** — fixture: usuario U con personaje
   P1 en `juego:X`/`partida:Y`, sin ninguna concesión en `juego:Z`. Verifica
   que cambiar de workspace sin concesión no arrastra ningún conocimiento de
   personaje de X: 0 resultados en `juego:Z`, no solo "vista vacía por
   filtro de M5b" sino bloqueada ya en la barrera de workspace (regla
   anterior en la cascada, M5b nunca se alcanza).
2. **Mismo usuario, distinta campaña** — U con P1 en `partida:Y1` y P2 en
   `partida:Y2` (mismo juego). Verifica que con `partida:Y1` activa, ningún
   hecho conocido solo por P2 en `Y2` es visible, aunque ambas partidas
   compartan `workspace`.
3. **Dos personajes del mismo usuario** — U con P1 y P2 en la MISMA
   `partida:Y`. Con P1 activo, hechos `visibility_subjects=[P2]` deben estar
   ocultos aunque el mismo usuario "controle" ambos — verifica que la
   barrera es por personaje activo, no por usuario.
4. **Personaje sin concesión** — U sin fila en `user_character_link` para
   `partida:Y`. Verifica 403/degradación a capa juego, igual que M5a con
   partida sin concesión (`docs/v3/49` §13.1 P0-3).
5. **Concesión revocada** — U tenía P1 aprobado, se revoca a mitad de
   sesión activa. Verifica re-comprobación por petición (mismo patrón P0-3
   de M5a): la siguiente petición ya no ve el conocimiento de P1, sin
   esperar expiración de caché.
6. **Recurso `GM_ONLY`** — hecho con `known_by_scope=GM_ONLY`,
   `visibility_scope=ADMIN_ONLY`. Verifica invisible para cualquier jugador,
   visible solo para `admin_full`.
7. **Recurso compartido con dos personajes** — hecho con
   `visibility_scope=SUBJECTS`, `visibility_subjects=[P1, P2]`. Verifica
   visible con P1 activo, visible con P2 activo, invisible con P3 activo
   (mismo `workspace`/`partida`, personaje distinto no listado).
8. **Objeto visible pero evidencia oculta** — entidad con
   `visibility_scope=PUBLIC`, una de sus `EvidenceSpan` asociadas con
   `visibility_scope=ADMIN_ONLY` (p. ej. el fragmento de texto de origen
   revela algo que el resumen de la entidad no revela). Verifica que la
   ficha de la entidad se sirve pero la evidencia oculta no aparece en la
   lista de evidencias ni se puede recuperar por ID directo.
9. **Assertion oculta conectada a entidad visible** — dos entidades
   visibles, una relación/`FactAssertion` entre ellas con
   `visibility_scope=SUBJECTS` sin el personaje activo en la lista. Verifica
   que la arista NO aparece en `graph()`/`relations_for_entity`, ni como
   "relación desconocida", ni contribuye al conteo de relaciones de ninguna
   de las dos entidades (ver caso 11).
10. **Búsqueda por nombre exacto de un secreto** — buscar el nombre literal
    de una entidad `ADMIN_ONLY` desde una sesión sin ese conocimiento.
    Verifica 0 resultados, no "resultado con campos vacíos" ni "resultado
    con nombre pero sin descripción" (que ya confirmaría la existencia).
11. **Conteo de vecinos** — entidad con 5 vecinos reales, 2 visibles para el
    personaje activo. Verifica que el conteo expuesto es 2, no 5, ni
    "2 de 5" (ver canales laterales).
12. **Recuperación directa por ID** — GET directo al ID de una assertion
    oculta, conocido de antemano (p. ej. por URL compartida o enumeración).
    Verifica 404, no 403 (403 confirmaría existencia; mismo criterio que
    M5a con partida ajena, `docs/v3/49` §13.1 P0-1: "404, indistinguible de
    inexistente").
13. **Exportación** — exportar el grafo/partida completa desde una sesión
    con conocimiento parcial. Verifica que el export contiene exactamente
    el subconjunto visible, no el grafo completo con un flag "oculto" en
    los campos — el propio fichero exportado no debe contener el dato
    oculto en ninguna forma (ni truncado, ni redactado, ausente).
14. **Paginación** — listado de 50 entidades reales, 10 visibles, con
    `page_size=5`. Verifica que la paginación opera sobre el conjunto YA
    filtrado (2 páginas, no 10 con 8 vacías al final) — mismo criterio que
    el comentario ya existente en `filtered_provider.py` sobre filtrar
    antes de paginar (`_ALL = 10_000_000`).
15. **Caché** — si existe cualquier caché de listado/conteo (hoy no
    documentada en el visor V3, pero riesgo genérico), verifica que la
    clave de caché incluye `active_character_id` además de
    `active_partida`/usuario — dos personajes distintos nunca comparten
    entrada de caché.
16. **Historial temporal** — hecho con transición `VISIBILITY_EXPANDED` en
    sesión 7 (§7). Verifica que una consulta "estado en sesión 5" (si esa
    capacidad existe) sigue mostrando `ADMIN_ONLY`, y una consulta "estado
    actual" muestra `SUBJECTS`/visible — sin mutar ni perder la versión
    anterior.
17. **Migración repetida** — ejecutar el script de marcado de §10 dos veces
    sobre el mismo grafo de prueba. Verifica estado idéntico tras la segunda
    pasada (idempotencia), sin duplicar transiciones de ledger ni cambiar
    `visibility_scope` ya marcado explícitamente por un humano.
18. **Dato antiguo sin campos** — nodo real de material actual (sin
    `known_by_scope`/`visibility_scope` en absoluto, no `UNKNOWN`
    explícito). Verifica que el fail-closed de §2.4 se aplica (ausente ⇒
    `DENY`, salvo el marcado de migración de §10 aplicado).
19. **Administrador** — `admin_full` ve todo salvo `DENY` explícito (§3,
    fila de `DENY`), sin necesidad de personaje activo ni concesión.
20. **Sesión anterior a la migración** — un usuario con sesión de visor
    activa (cookie previa) antes de que se ejecute el marcado de §10.
    Verifica que la re-verificación por petición (mismo patrón que P0-3 de
    M5a) recoge el nuevo estado de visibilidad sin necesitar logout/login.
21. **Intento de manipular `visibility_subjects` desde el cliente** — una
    petición HTTP que intente inyectar `visibility_subjects` en un payload
    de escritura desde el visor (si el visor expusiera alguna vía de
    escritura, hoy no lo hace salvo el panel admin). Verifica que el visor
    de jugador es de solo lectura respecto a estos campos: ninguna ruta no
    administrativa acepta ni interpreta un campo de visibilidad enviado por
    el cliente — el backend nunca confía en el cliente para decidir qué es
    visible (principio ya vigente, sin excepción para M5b).

**Canales laterales** (batería transversal, aplicada a cada endpoint
anterior, no solo a los casos con nombre):

- **Lista total**: el conteo "total sin filtrar" nunca se expone junto al
  filtrado (ni siquiera como metadato de depuración) — un `total=47,
  visible=3` ya filtra "hay 44 cosas ocultas aquí".
- **Conteos**: mismo criterio que el caso 11, generalizado a cualquier
  conteo (fuentes, sesiones, tipos de entidad).
- **Tiempo de respuesta**: una consulta que primero comprueba existencia y
  luego visibilidad (dos pasos con tiempos distintos) puede filtrar por
  timing side-channel — el diseño exige un único camino de consulta que
  aplique el filtro en la propia query (Cypher/SQL), no un chequeo posterior
  en Python con early-return medible (mismo criterio que M3 aplicó al
  writer: "la visibilidad se resuelve en Cypher, jamás en Python",
  `docs/v3/49` §12).
- **Errores distintos**: un 403 en vez de 404 para "existe pero no
  autorizado" es un canal lateral (ya corregido explícitamente en M5a,
  §13.1 P0-1, y reiterado aquí como requisito heredado, no nuevo).
- **IDs secuenciales**: si los IDs de assertion/entity son incrementales o
  predecibles, listar públicamente "el ID más alto visible" puede permitir
  inferir cuántos ocultos hay entre medias — no es un problema nuevo de
  M5b, pero M5b no debe introducir ningún endpoint que exponga "siguiente
  ID libre" o rangos.
- **Número de relaciones**: igual que el conteo de vecinos (caso 11), pero
  generalizado a cualquier metadato de grado del grafo expuesto en la UI
  (p. ej. tamaño de nodo proporcional a grado en una visualización).
- **Resultados parciales**: ninguna respuesta debe mezclar "aquí tienes 3
  campos de una entidad oculta, el resto censurado" — o la entidad completa
  visible, o inexistente; no hay estado intermedio salvo el caso 8
  (entidad visible, evidencia específica oculta), que es una relación de
  contención distinta (entidad ↔ evidencia), no un campo censurado dentro
  del mismo documento.

---

## 12. Puerta de cierre de M5b (checklist verificable)

- [ ] Contratos versionados según §9 (aditivo, `OMIT_IF_NONE`, tag de
      freeze nuevo si se tocan ficheros de `contracts/knowledge-v3/v1/`).
- [ ] Propagación end-to-end verificada por los ficheros listados en §5
      (diff del PR no toca `extraction/`/`engine/`/`eval/gate6_*`).
- [ ] Backend fail-closed: todo dato sin `known_by_scope`/`visibility_scope`
      es no-visible por defecto (§2.4), probado (caso 18).
- [ ] Frontend no autoritativo: ninguna ruta de jugador acepta
      `visibility_subjects`/`known_by_scope` desde el cliente (caso 21).
- [ ] Revocación inmediata: re-verificación por petición de concesión de
      personaje, mismo patrón que M5a P0-3 (casos 5, 20).
- [ ] Recuperación por ID protegida: 404 sobre entidad/assertion/evidencia
      oculta, nunca 403 (caso 12).
- [ ] Listas y conteos protegidos: filtrado antes de paginar, conteo del
      subconjunto visible (casos 11, 14).
- [ ] Búsqueda protegida: 0 resultados por nombre exacto de secreto
      (caso 10).
- [ ] Exportación protegida: el fichero exportado no contiene el dato
      oculto en ninguna forma (caso 13).
- [ ] Migración idempotente: dos pasadas producen el mismo estado
      (caso 17).
- [ ] Datos antiguos fail-closed: material sin campos se migra a estado
      restringido, nunca `PUBLIC` implícito (§10, caso 18).
- [ ] 0 fugas cross-partida (heredado de M5a, reverificado con M5b activo:
      el filtro de personaje no debe abrir ninguna rendija en la barrera de
      partida ya cerrada).
- [ ] 0 fugas cross-personaje (nuevo de M5b: caso 3, dos personajes del
      mismo usuario).
- [ ] Batería de canales laterales de §11 con 10/10 checks verdes
      (lista total, conteos, tiempo de respuesta, errores, IDs
      secuenciales, número de relaciones, resultados parciales, y los 3
      restantes de la lista transversal aplicados sistemáticamente a cada
      endpoint, no solo probados una vez).
- [ ] Supervisor CONFORME (revisión adversarial explícita, mismo patrón que
      encontró los P0 de M5a en `docs/v3/49` §13.1 — se espera, por
      precedente, que una ronda adversarial de M5b encuentre huecos
      similares en superficies que no pasan por `PolicyFilteredProvider`;
      el checklist no se da por cerrado sin esa ronda).

---

## 13. División en sub-bloques implementables

| Bloque | Contenido | Depende de | Riesgo |
|---|---|---|---|
| **M5b-0** | Contratos: los seis campos de §5 (`*_hint` en `ClaimProposal`, campos sellados en `FactAssertion`) + esquemas JSON Schema (PROPUESTA, ver ficheros en §15/anexo). Sin lógica que los use — campo opcional, todo el código existente sigue funcionando. Tag de freeze nuevo (`v3-contracts-frozen-1.0.0-m5b0`). | M0-M5a (mergeados) | Bajo — mismo patrón que M0. |
| **M5b-1** | Writer: validación estructural de coherencia en `admission.py` (§4 punto 3, §9), props estampadas en `cypher.py`, código de rechazo nuevo. Sin generación automática todavía — solo acepta/rechaza planes que YA declaren los campos (de origen manual/panel admin). | M5b-0 | Medio — puerta física al grafo, mismo nivel de cuidado que M3. |
| **M5b-2** | Visor: `ViewerContext.active_character_id`, regla 2c en `VisibilityPolicy.can_view`, `VisibilityScope` extendido, selector de personaje (`POST /character/select`), re-verificación por petición. Extensión de `access_store.py` con `partida_id` (§15) O tabla nueva en `auth.db` análoga a `partida_access` (misma decisión que M5a tomó para partida — a resolver con el mismo criterio: ¿el visor ya tiene su propia fuente de verdad de personaje? Hoy no; este es el primer punto donde el visor necesitaría de verdad `access_store.py` o un equivalente propio — ver hueco §14). | M5b-1 | Alto — superficie amplia (todas las rutas), y primera vez que el visor necesita saber "personaje", no solo "partida". |
| **M5b-3** | Panel admin de visibilidad manual (`/admin/visibility` o extensión de `/admin/partidas`), recuperando `/control/visibility` del diseño legacy (§11 de `KNOWLEDGE_VISIBILITY_DESIGN.md`): marcar entidad/relación como conocida por personaje, compartir conocimiento, ocultar manualmente. Necesario porque M5b-4 (derivación automática) es alto riesgo y el panel manual es el mecanismo de respaldo/corrección desde el primer momento. | M5b-2 | Medio — UI nueva, pero motor de decisión ya construido en M5b-1/2. |
| **M5b-4** | Derivación automática de conocimiento desde extracción — el hueco (c) de `docs/v3/49` §2.7 y el hueco grande de §14 de este documento. Requiere su propia ronda de diseño (fuera de alcance de este documento) antes de empezar a implementar. Superficie comparable a un carril de extracción propio. | M5b-2, M5b-3 (como red de seguridad manual antes de confiar en lo automático) | Alto — falsos negativos (personaje "no sabe" algo que debería) y falsos positivos (fuga real de información) si la derivación es imprecisa; no se puede acotar el riesgo sin el diseño previo. |
| **M5b-5** | Temporalidad de visibilidad (§7): razones canónicas nuevas en el ledger, consulta de estado histórico si se decide construirla. | M5b-1 | Medio-alto — requiere decidir primero si el visor necesita consulta temporal general (hueco §14) o si basta con la transición registrada sin UI de consulta retrospectiva. |
| **M5b-6** | Migración/marcado del contenido de prueba existente (§10) — mismo housekeeping que M6, gateado a aprobación explícita del operador. No es parte del código de M5b-0..5, es operativo. | M5b-1 (para que el marcado use el mecanismo real de escritura, no un script que toque Neo4j por fuera del writer) | Operativo, riesgo bajo (contenido de prueba), exige confirmación previa igual que M6. |

Orden recomendado: **M5b-0 → M5b-1 → M5b-2 → M5b-3 → (M5b-5 en paralelo con
M5b-3, ambos dependen solo de M5b-1) → M5b-4 (el más lento y el que más
diseño previo necesita) → M5b-6 al final**, mismo criterio de M5a: cada
bloque cierra con ciclo impl→tests→revisor, mergeable de forma
independiente, sistema en estado consistente entre bloques (M5b-0 a M5b-3
dejan el sistema funcionando exactamente igual que hoy hasta que M5b-2 se
activa; ningún bloque intermedio rompe M5a).

---

## 14. Huecos de diseño explícitos

### 14.1 El hueco grande: ¿de dónde sale "lo que un personaje conoce"?

No está resuelto en V3 hoy, y M5b no puede implementarse completo sin
decidirlo. Tres vías posibles, no mutuamente excluyentes:

**(a) Derivación por presencia en episodio.** Si `Episode` (§5) declara
`participants` (personajes presentes en la sesión/escena que originó el
episodio), cualquier `FactAssertion` cuya `episode_ids` incluya ese episodio
puede heredar `known_by_scope=CHARACTER`/`visibility_subjects=participants`
como valor por defecto **propuesto** (no sellado sin revisión, §4). Es el
mecanismo más barato y menos arriesgado: no requiere NLP nuevo, solo que
alguien (el narrador, al programar la sesión, o un import de calendario de
mesa) declare quién estuvo. Cubre el caso principal del ejemplo del Oni
("Asuka y Kimi combatieron, Hisao no estaba") sin inferencia de texto.
**Limitación**: no distingue "estuvo presente y lo vio" de "estuvo presente
pero de espaldas" — sobreestima conocimiento en escenas con múltiples focos
simultáneos.

**(b) Marcado manual del narrador.** Vía el panel `/admin/visibility`
(M5b-3), el narrador declara explícitamente quién sabe qué, sin depender de
extracción. Es el mecanismo más preciso y el más caro en tiempo humano — no
escala a un volumen alto de sesiones sin apoyo de (a) o (c).

**(c) Inferencia lingüística por un modelo (LLM/NVIDIA/Ollama).** El
diseño legacy (`KNOWLEDGE_VISIBILITY_DESIGN.md` §12) da patrones de ejemplo
("Asuka vio al Oni" → `HAS_SEEN`) pero **no hay código V3 que los
implemente**, ni un extractor dedicado, ni un contrato con campo de
"relación de conocimiento" (verificado, no supuesto: `docs/v3/49` §2.7 hace
el mismo `grep` y confirma 0 resultados). Construir esto es, literalmente,
un carril de extracción nuevo: necesita su propio corpus de evaluación,
su propia medición de precisión/recall (con el mismo rigor que Puerta 4/6
aplicaron a factividad — no vale con "funciona en el ejemplo del Oni"), y
su propio criterio de cuándo abstenerse. Dado el coste asimétrico (fuga de
secreto vs. falso oculto, §4 punto 4), la vía (c) por sí sola sin (a)/(b)
como red de seguridad es la opción de mayor riesgo del programa entero.

**Recomendación de este documento** (no vinculante, es una opinión de
diseño, no una decisión tomada): empezar por (a)+(b) en M5b-3/M5b-2 —
cubre el caso de uso principal sin depender de un carril de extracción
nuevo — y tratar (c) como M5b-4, con su propia ronda de diseño previa
obligatoria, gateada a que (a)+(b) ya estén en producción y hayan mostrado
qué fracción de casos reales quedan sin cubrir por presencia+marcado manual
antes de invertir en inferencia automática.

### 14.2 Otros huecos

1. **Consulta temporal de estado histórico** (§7 punto 4): el visor V3
   actual no tiene, hasta donde se ha verificado, una capacidad general de
   "muéstrame el grafo como se veía en el momento X" — M5b la necesitaría
   para cumplir literalmente "no sobrescribe la historia" de forma
   consultable, no solo "no destruye datos en el ledger". Si esa capacidad
   no existe, M5b puede cumplir la parte de integridad (el ledger no pierde
   la versión anterior) sin cumplir la parte de UX (nadie puede consultarla
   desde el visor) — hueco de alcance a decidir por el operador.
2. **Graph RAG / embeddings futuros** (§6, último punto): sin arquitectura
   aún, el requisito de "construir sobre el filtro, no sobre el grafo
   crudo" está fijado aquí pero el mecanismo de aplicarlo a un índice
   vectorial (que normalmente no se puede filtrar por usuario después de
   calculado sin recalcular) no está diseñado.
3. **Coste de `PolicyFilteredProvider` en memoria** (heredado literalmente
   de `docs/v3/49` §6 punto 2, agravado por M5b): el patrón ya trae todo el
   workspace a memoria antes de filtrar y paginar; añadir un filtro más
   fino (por personaje, potencialmente evaluado por entidad y por usuario)
   no cambia el orden de magnitud pero si el volumen crece, puede exigir
   empujar el filtro a la query base de Neo4j — mismo hueco de rendimiento
   ya señalado, ahora con una capa más.
4. **`DENY` absoluto vs. `DENY` con excepción de operador**: §3 fija que
   `DENY` no lo ve ni siquiera `admin_full` por el visor normal, pero no
   está decidido si debe existir una vía de "romper cristal" para un
   operador (herramienta CLI directa contra Neo4j, fuera del visor) — se
   deja como decisión abierta explícita, no resuelta por este documento.
5. **Casos compuestos `local_override_of` (M4) + visibilidad (M5b)**: no
   diseñados aquí (§7 punto 5); si una partida diverge de un hecho de lore
   y ese hecho divergente tiene su propia visibilidad restringida, el orden
   de aplicación de las dos capas de filtrado (enmascarado de M4 primero,
   visibilidad de M5b después, o al revés) no está especificado.
6. **Volumen y forma exacta del panel `/admin/visibility`**: recuperado
   como referencia del diseño legacy (§11 de `KNOWLEDGE_VISIBILITY_DESIGN.md`)
   pero no auditado contra el código actual del visor V3 más allá de
   `policies/engine.py`/`models.py` — puede haber piezas de UI a construir
   desde cero no dimensionadas aquí (mismo hueco que `docs/v3/49` §6
   punto 4 dejó abierto para M5a, no cerrado por M5a según su propio
   informe de cierre).

**Inconsistencia señalada, no resuelta por este agente**: el encargo pide
un modelo de tres campos (`known_by_scope`/`visibility_scope`/
`visibility_subjects`) con nombres y enum distintos de los que
`viewer/app/policies/engine.py` **ya implementa y ya prueba en producción**
(`visibility` con valores `player/narrator/secret/reference`, `party`,
`session_index`, `known_by`/`character_knowledge`). Los dos modelos son
semánticamente compatibles (mapeo aproximado: `visibility=secret/narrator`
≈ `visibility_scope=ADMIN_ONLY`+`known_by_scope=GM_ONLY`; `party` ≈
`visibility_scope=CAMPAIGN`; `known_by`/`character_knowledge` ≈
`visibility_scope=SUBJECTS`+`visibility_subjects`) pero **no son el mismo
campo con otro nombre**: implementar el modelo de tres campos tal cual pide
el encargo exige o (i) migrar `engine.py` a los tres campos nuevos, tocando
una regla ya en producción y probada (`docs/v3/49` §13, 446 tests del
visor), o (ii) mantener ambos modelos coexistiendo con una capa de mapeo
entre ellos. Este documento no decide cuál — queda como decisión explícita
para el operador antes de M5b-2, porque cambia el alcance real de ese
bloque de forma sustancial.

---

## 15. Reutilización de `access_store.py` (v1) con V3

Igual que M5a hizo esta evaluación para el modelo usuario↔partida
(`docs/v3/49` §13, "Decisión: modelo usuario -> partidas permitidas") y
decidió NO usarlo, M5b necesita la misma evaluación para usuario↔personaje.
Con evidencia de código, no supuesta:

**Reutilizable tal cual, con extensión mecánica:**

- `user_character_link` (`data-engine/app/access/access_store.py`, tabla
  con `username`, `workspace`, `character_id`, `character_name`, `status`
  en `{pending, approved, rejected, revoked, assigned}`,
  `is_active_for_workspace`) es exactamente el modelo usuario↔personaje que
  M5b necesita para el punto 4 de §8 ("personaje activo"). Extensión
  necesaria: columna `partida_id` (nullable), mismo patrón que M5a propuso
  y no llegó a aplicar aquí (`docs/v3/49` §2.6: "el modelo... queda
  resuelto... es `user_character_link`... extendido con `partida_id`").
- `user_workspace_permission` (flags `can_view_secret`/`can_view_narrator`/
  `can_view_future`/`can_view_reference`, `max_visible_session`) es
  literalmente el mismo vocabulario que `ViewerContext` ya expone
  (`can_view_secret`, `can_view_future`, `max_visible_session` en
  `viewer/app/policies/models.py`) — reutilizable como fuente de esos
  valores si se conecta al visor, en vez de duplicarlos.
- `access_audit_log` es reutilizable como modelo de auditoría, aunque el
  visor ya tiene su propio `audit_events` en `auth.db` (M5a) — misma
  pregunta que M5a resolvió para `partida_access` (¿una tabla nueva en
  `auth.db` o extender esta?) se repite aquí, sin resolver por este
  documento (ver decisión pendiente abajo).

**NO reutilizable / no existe:**

- Ninguna propiedad de grafo (`known_by_scope`, `visibility_scope`,
  relaciones `KNOWS_ABOUT`/`HAS_SEEN`/etc.) vive hoy en `access_store.py`:
  es una base SQLite de identidad y permisos, no de contenido del grafo.
  `access_store.py` puede decir **quién es quién** y **qué tipos de
  entidad puede ver en general** (flags `can_view_*`), pero no **qué
  conoce ese personaje en particular** — eso vive exclusivamente en
  `known_by_scope`/`visibility_scope`/`visibility_subjects` como
  propiedades de nodo/relación en Neo4j (§5), fuera del alcance de
  `access_store.py` por diseño.
- El propio `access_store.py` (según su docstring y estructura) es un
  proceso/CLI separado del visor FastAPI (`data-engine/app/access/`, no
  `viewer/app/`), con su propia base (`state/access.db`, ruta relativa al
  módulo) — el mismo desacoplamiento que M5a encontró y por el que decidió
  **no** conectarlo, creando en su lugar `partida_access` en `auth.db`
  (`docs/v3/49` §13: "el visor ya tiene su propia fuente de verdad de
  autorización... y nunca ha leído ni escrito `access_store.py`").

**Decisión pendiente heredada de M5a, ahora ineludible en M5b:** M5a dejó
explícitamente escrito que "si M5b necesita después leer `access_store.py`
... esa integración se revisará entonces" (`docs/v3/49` §13, decisión
discutible 2). M5b sí lo necesita — es exactamente el punto 4 de §8. Este
documento recomienda, sin decidirlo de forma vinculante, repetir el patrón
de M5a: **tabla nueva `character_access` en `auth.db`** (mismo esquema que
`partida_access`: `id, user_id, workspace, partida_id, character_id,
granted_by, granted_at`), en vez de conectar el visor a
`access_store.py` — por la misma razón que M5a documentó (dos procesos que
hoy no se conocen, sin necesidad real de acoplarlos) — dejando
`access_store.py` como lo que ya es: la herramienta de gestión de acceso
del lado data-engine/CLI, no del visor. Si el operador prefiere lo
contrario (unificar en `access_store.py` como única fuente de verdad y que
el visor lo consulte), es una decisión de arquitectura mayor que este
documento señala pero no toma.

---

## Anexo: esquemas propuestos (borrador, no vinculante)

Ver `docs/v3/schemas-propuestos/m5b-visibility-fields.schema.json` para un
fragmento JSON Schema de ejemplo de los tres campos, marcado PROPUESTA. No
sustituye ni modifica ningún esquema real de
`contracts/knowledge-v3/v1/`.
