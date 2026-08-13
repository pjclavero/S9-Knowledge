# 73 · Inventario y conservación del árbol de trabajo (carril RECONCILIACIÓN)

**Repositorio**: `pjclavero/S9-Knowledge` · **Rama del informe**:
`docs/inventario-conservacion-2026-08` · **HEAD de medida**: `3f3face`
(= `origin/main` en el momento de medir) · **Fecha**: 2026-08-13

Este carril **no borra nada**. Ningún elemento de este documento ha sido
eliminado, descartado ni aplicado sobre el árbol: todo lo que sigue es
observación, y toda retirada queda propuesta al operador al final (§7).

## 0. Método, y por qué importa

Dos lecturas equivocadas anteriores en esta misma ronda vienen del mismo error:
comparar dos ramas de frente. `git diff origin/main <rama>` mezcla los cambios
**de main** invertidos con los de la rama, y hace atribuir a la rama ficheros
que nunca tocó. Aquí todo se mide **contra el punto de divergencia**
(`origin/main...<rama>`, tres puntos) y, para el veredicto de contenido, se
compara **blob a blob** el fichero en la punta de la rama contra el mismo
fichero en `origin/main`.

Tres reglas más, usadas en todo el documento:

- **El mensaje de un stash es el título de su commit base, no su contenido.**
  El veredicto sale de `git stash show --stat/-p`, nunca del rótulo.
- **Publicado se comprueba, no se supone**: `git branch -a --contains <sha>`.
- **Contenido reproducible ≠ contenido único.** Antes de declarar que algo se
  perdería, se busca su blob exacto en toda la historia (`git log --all` por
  fichero) y en el reflog. Un fichero cuyo blob ya existe en un commit
  alcanzable no es trabajo en riesgo: es una copia.

Aviso de método: `git rev-parse <rev>:<ruta>` **imprime el argumento literal**
cuando la ruta no existe en esa revisión, en vez de fallar en silencio. Usarlo
sin `--verify -q` produce "difiere" donde en realidad hay "no existe". La
primera pasada de este inventario cayó en eso y se rehízo entera; las tablas de
abajo están medidas con `--verify -q` (o con `git cat-file -s`).

## 1. Resumen ejecutivo

| Elemento | Cantidad | Veredicto |
|---|---|---|
| Stashes | 3 | **Ninguno contiene trabajo único.** Los 3 son reproducibles desde la historia |
| Worktrees | 52 | 50 con el árbol exactamente en su HEAD; **2 con cambios sin commitear** |
| Commits en HEAD separado no alcanzables desde ninguna rama | **7** | El worktree es su única sujeción fuerte |
| Ramas locales no fusionadas en `origin/main` | 32 | 8 de ellas **sin equivalente en el remoto** |
| Ramas remotas no fusionadas | 23 | Publicadas: no se pierden con una limpieza local |
| Directorio `.recovery/` en el checkout principal | 16 ficheros | **Superado por `main`**: 14 idénticos, 2 con `main` estrictamente más nuevo |

**Respuesta a la pregunta que motiva el carril** (§6): con una limpieza de
worktrees **no se pierde ningún trabajo terminado**, pero **sí se perdería**
(a) el trabajo vivo sin commitear de un agente en curso y (b) **siete commits
que hoy sólo sujeta el worktree**, todos ellos iteraciones anteriores de trabajo
ya superado por `main` — recuperables por reflog mientras nadie ejecute `gc`.

## 2. Stashes

`git stash list` devuelve exactamente 3. No hay más.

### `stash@{0}` — «revisor: contenido ajeno hallado en el worktree antes de medir 02b0514»

- **Base**: `02b0514` (`docs: remedidas main_commit/latest_merged_pr…`).
- **Contenido medido**: 60 ficheros, `411 insertions(+), 8374 deletions(-)`.
  Es decir: el árbol guardado era **más viejo** que su propia base. No es
  contenido "ajeno" añadido, es un checkout rezagado.
- **Procedencia, fichero a fichero**: los 50 ficheros presentes en el stash
  tienen un blob **idéntico a una versión histórica de `origin/main`**
  (`git log origin/main -- <fichero>`, comparando blob a blob): `328177a`,
  `1553665`, `304024f`, `15ae1d4`, `cb874fe`, `5fe67f5`… Ninguno queda sin
  coincidencia. *(Cuidado con un falso positivo fácil: `git log --all` incluye
  los propios commits del stash, y `stash@{0}^2` es `53fe788`. Buscar ahí "prueba"
  que el stash se reproduce desde sí mismo. La medición de arriba está
  restringida a la historia de `origin/main`.)*
  Los 10 restantes **no están en el stash en absoluto**: son borrados puros
  (`git cat-file -s stash@{0}:<f>` → ausente; en `02b0514` y en `main` existen).
  Entre ellos `docs/66-calidad-de-datos-v2.md`, `contracts/review-status/v1/model.py`
  y `viewer/tests/test_calidad_de_datos_v2.py`.
- **Sin untracked**: `stash@{0}^3` existe pero está vacío.
- **Clasificación**: **INTEGRADO / SUPERSEDIDO**. Cero bytes únicos. `main`
  contiene una versión posterior de los 50, y los 10 "borrados" existen en `main`.

### `stash@{1}` — «WIP on (no branch): 41f8688 feat(review-console-v2)…»

- **Base**: `41f8688`, que **sí está publicado** (`git branch -a --contains`
  → `feat/review-console-v2-readonly` y `origin/feat/review-console-v2-readonly`).
- **Contenido real**: `viewer/app/routers/v3_review.py | 10 ----------`.
  **Diez líneas borradas y nada más.** Concretamente, quita el `import` del
  módulo `review_console_v2` y la línea `router.include_router(_console_v2.router)`,
  con sus comentarios. Es **el desmontaje** de la consola, no la consola.
- **Clasificación**: **INTEGRADO** (por complemento). Es el inverso exacto de
  seis líneas que viven en `41f8688`, un commit publicado. Nada que conservar.
- Este stash es el origen documentado de la lectura equivocada anterior: el
  rótulo nombra la consola porque es el título del commit base.

### `stash@{2}` — «WIP on feat/external-burst-orchestrator: 9523602…»

- **Contenido**: `data-engine/app/jobs/job_store.py` (+26 líneas: las columnas
  `batch_id`, `processing_mode`, `provider`, `model`, `task_type`, `chunk_json`,
  `progress`, `attempt_burst`, `next_retry_at`, `latency_ms`, `error_code`, en
  el `CREATE TABLE` y en `_MIGRATION_COLUMNS`) y `docs/INDEX.md` (+1 línea).
  Nota: **`docs/INDEX.md` ya ni siquiera existe en `main`**.
- **Medición**: esas columnas **ya están en `origin/main`**
  (`job_store.py` líneas 123, 129, 149, 155…). La línea de `docs/INDEX.md`
  apunta a `docs/43-external-burst-orchestrator.md`, fichero que **fue renombrado
  a `docs/45`** en `8e593d8` (`docs: rename burst doc to docs/45…`).
- **Clasificación**: **INTEGRADO** el código; **OBSOLETO** la línea de índice
  (destino renombrado a `docs/45` y fichero de índice desaparecido: aplicarla
  recrearía un índice muerto con un enlace roto).

## 3. `.recovery/` en el checkout principal (`/home/ia02/S9-Knowledge`)

No es un worktree ni un stash: es un directorio **no rastreado** en el checkout
principal, con 16 ficheros (1767 líneas) más tres ficheros de rescate
(`contaminated-worktree-{staged,unstaged}.patch`, `…-untracked.txt`; el `staged`
está vacío). Contiene una consola de revisión completa: `routers/reviews_console.py`,
`services/review_console.py`, 11 fixtures JSON, `static/css/reviews.css`,
2 plantillas y `tests/test_reviews_console.py`.

Medición por hash de blob contra `origin/main`:

- **14 de 16 ficheros: byte a byte idénticos a `main`.**
- **2 difieren**, y en ambos **`main` es estrictamente posterior**:
  `routers/reviews_console.py` y `services/review_console.py`. La diferencia es
  exactamente la introducción del ámbito de visibilidad — `main` añade
  `Depends(get_visibility_scope)`, `scope: VisibilityScope` y lo propaga a
  `rc.list_source_summaries/get_source_summary/list_candidates/plan_preview`,
  con el contrato de 404 indistinguible para material fuera de ámbito. La copia
  de `.recovery/` es la versión **previa a la política**.
- **Clasificación**: **SUPERSEDIDO** por `main` (`3f3face`). Cero contenido único.
  Conservar esta copia como "por si acaso" es conservar la versión sin política
  de visibilidad, que es justamente la que no se quiere que nadie reinstale.

## 4. Worktrees (52)

Estado del árbol medido comparando el hash de cada fichero del árbol contra el
blob del `HEAD` del propio worktree (no se ejecutó `git` dentro de ellos).

**50 de 52 tienen el árbol exactamente en su HEAD.** Lo único "extra" que
aparece son artefactos de ejecución sin valor: `viewer/state/health/last_report.json`,
`viewer/output/reviews-v3/review.sqlite3` y similares.

Las dos excepciones:

### 4.1 `agent-aa02be923507cc117` — `feat/viewer-parcialidad-declarada` @ `3f3face` — **locked**

Seis ficheros modificados sin commitear, más uno nuevo:

```
MOD viewer/app/serializers.py          MOD viewer/app/api/graph.py
MOD viewer/app/static/js/graph-core.js MOD viewer/app/templates/graph.html
MOD viewer/app/static/js/graph.js      MOD viewer/app/static/css/app.css
NUEVO viewer/app/graph_view.py
```

Worktree **bloqueado y sobre el HEAD actual de `main`**: es un agente **vivo**,
no un resto. **CONTIENE TRABAJO ÚNICO**, por definición: son cambios sin
commitear que no existen en ningún objeto de Git. Se pierde con cualquier
limpieza, y también con un `checkout` descuidado dentro de ese worktree.
**No tocar.** Es el único elemento de todo el inventario cuyo trabajo no está
respaldado por nada.

### 4.2 `perf-viewer-scale-v2` — `perf/viewer-scale-baseline-v2` @ `f515c8b`

11 ficheros modificados y 2 borrados respecto de su HEAD
(`.github/scripts/calibra_gate_integrity.py` y `docs/64-integridad-de-gates.md`
borrados; `benchmarks/perf/*`, `docs/67`, `.github/workflows/ci.yml`,
`.github/scripts/check_ci_config.py`, `tests/e2e/conftest.py` modificados).

Parece trabajo pendiente. **No lo es**: los 11 ficheros del árbol son
**byte a byte iguales a `33d758f`**, un commit anterior de esa misma rama que
sigue en el reflog (`perf/viewer-scale-baseline-v2@{1}`) y ya no está en ninguna
rama. El árbol es la **v2.0** del laboratorio de rendimiento; el HEAD `f515c8b`
es la **v2.1**, que corrige cinco agujeros documentados del propio instrumento
(umbral inventado de 0.5 llamadas/elemento, huella de caché que no cubría el
fichero, doble de driver fuera del hash, calibración sin fijar el commit del
sistema medido, y C2 pasando por el motivo equivocado). El árbol también
**revierte las guardias anti-cero de `ci.yml`** y **resucita la fixture
`require_playwright`** que el carril L retiró.

**Clasificación**: **SUPERSEDIDO** por su propio HEAD. Restaurarlo sería una
regresión de CI. Es el único sitio del inventario donde `git checkout .` es
inofensivo — pero, por la regla del carril, tampoco se hace aquí.

### 4.3 Commits en HEAD separado que **sólo sujeta el worktree**

13 worktrees están en HEAD separado. Seis apuntan a commits ya en `main`.
De los otros siete, **ninguno es alcanzable desde ninguna rama local ni remota**
(`git branch -a --contains` → 0 ramas; comprobado además contra las 142 refs):

| Commit | Worktree | Fecha | Qué es | Clasificación |
|---|---|---|---|---|
| `a995395` | `agent-a79bd2bbb11d96b54` | 08-13 11:11 | chasis: un anónimo no puede enumerar paneles encendidos | **INTEGRADO** — los 16 ficheros son idénticos a `main` |
| `d1e9f76` | `agent-ad4fb22436e8c1058` | 08-13 11:17 | Carril K (Q4/Q5) | **INTEGRADO** — 21/21 idénticos a `main`; además la rama `audit/route-contract-map-v2` lo contiene |
| `7dddece` | `agent-a2c493ed6407cb49d` | 08-13 09:36 | chasis medido contra tabla + apagado de paneles | **SUPERSEDIDO** — 13/16 idénticos; difieren `docs/69`, `chassis_slot.py`, `test_chassis_mount_contract.py`, con `main` posterior |
| `7cc4d35` | `agent-a734beaa4ad4e9ace` | 08-13 09:44 | recalibración perf sobre `e2e8214` | **SUPERSEDIDO** — 7/13 idénticos; difieren los 6 de `benchmarks/perf` y `docs/67` |
| `eeafc81` | `agent-a4971d7a15a98a526` y `agent-a627f07a1b16bf48c` (2 worktrees, mismo commit) | 08-12 12:17 | Carril J: ninguna razón se declara por el nombre de un test | **SUPERSEDIDO** — 14/18 idénticos; difieren `ci.yml`, `mutaciones_calidad_datos.py` y 2 tests |
| `c10be77` | `agent-a7a61c45d4ee7e145` | 08-12 11:52 | ops: el discriminante es el DESENLACE, no la forma del `if` | **SUPERSEDIDO** — 5/11 idénticos; el resto vive en `ops/environment-reproducibility-v1` |
| `06c4565` | `rev-verify` | 08-11 23:13 | estado verificado contra Git y CI, calibración ejecutable | **SUPERSEDIDO** — 25/31 idénticos; difieren `CHANGELOG`, `README`, `project-status.yaml`, `check_docs_consistency.py` y 2 más |
| `7d014f2` | `/home/ia02/.claude/jobs/2c6f0079/tmp/wtB` | 08-11 11:04 | diseño BKP-4 off-host | **SUPERSEDIDO** — `docs/71` con versión posterior en `main`; además hay `origin/docs/bkp4-off-host-limpio` |

Ninguno aporta **un solo fichero que no exista en `main`**. Lo que se perdería
al retirar sus worktrees son *versiones intermedias*, no piezas.

## 5. Ramas

### 5.1 Locales no fusionadas y **sin remoto** — lo único que sólo vive aquí

Ocho ramas locales no están en `origin/main` **ni tienen equivalente en el
remoto**. Una limpieza de *worktrees* no las toca (borrar un worktree no borra
su rama), pero un `branch -D` sí:

| Rama | Commits sobre `main` | Contenido vs `main` |
|---|---|---|
| `work-carril-a` | 8 | 11 ficheros iguales, 8 difieren. Misma familia que `cierre/carril-a` (publicada, 15 commits) |
| `fix/graph-ux-v2-h1h2h4` | 6 | 8 iguales, 10 difieren. Familia Graph UX V2 |
| `work-a` | 5 | 6 iguales, 10 difieren. Familia Graph UX V2 |
| `feat/multipartida-m5a-viewer` | 4 | 7 iguales, 20 difieren. Precursora de `feat/multipartida-m5a-visor`, ya fusionada (PR #143) |
| `worktree-agent-a418b1238eb52e3f8` | 3 | 7 iguales, 8 difieren. Familia Graph UX V2, nombre autogenerado |
| `docs-estado-verificado` | 2 | 5 difieren. Misma familia que `06c4565` y `worktree-agent-a887e73f51873274f` |
| `docs/sync-project-state-2026-08` | 1 | 24 iguales, 6 difieren |
| `docs/review-phase2-rebased` | 1 | 1 difiere (`docs/71-bkp4-destino-off-host.md`) |

Ninguna aporta un fichero inexistente en `main`: todas son iteraciones de
trabajo cuya versión posterior ya está en `main` o en una rama publicada.
**Clasificación: SUPERSEDIDO**, con valor de **REFERENCIA** en el caso de
`work-a`/`work-carril-a`/`fix/graph-ux-v2-h1h2h4`, que conservan variantes de
`viewer/app/static/js/graph-core.js` y de las pruebas de navegador.

### 5.2 Ramas (locales o remotas) con ficheros que **no existen en `main`**

Aquí está el material realmente no integrado. Todas están **publicadas en
`origin`**, así que no dependen del disco local:

| Rama | Ficheros que no existen en `main` | Clasificación |
|---|---|---|
| `feat/review-console-v2-readonly` | 6 (consola V2 completa) | **REFERENCIA** — ver §8 |
| `audit/data-contract-health-v1` | 9 (`scripts/data_health/*`, fixture y test de integración) | **CONTIENE TRABAJO ÚNICO** — no hay nada equivalente en `main` |
| `feat/admin-operations-dashboard` | 8 (`viewer/app/ops/*`, router, plantilla, test) | **CONTIENE TRABAJO ÚNICO**, pero pisado por el diseño: `main` reserva el hueco **B = Operations** del chasis |
| `ops/v3-release-readiness` | 9 (`deploy/release/*`, `docs/61-release-manifest-y-rollback.md`) | **CONTIENE TRABAJO ÚNICO** — `main` sólo tiene `docs/65-preparacion-de-release.md` |
| `perf/viewer-scale-baseline-v1` | 7 (`bench_navegador.py`, `calibrar_n_mas_1.py`, resultados, `tablas.py`, `docs/61-perf-…`) | **SUPERSEDIDO** por el laboratorio v2 de `main` |
| `audit/viewer-route-contract-map` | 6 (`viewer/tests/route_contract/*`) | **SUPERSEDIDO** por `audit/route-contract-map-v2`, cuyo contenido **ya es idéntico a `main`** (21/21) |
| `feat/m5b-fog-of-war-design` | 2 (diseño + esquema propuesto) | **REFERENCIA** (diseño, no código) |
| `docs/bovedas-esquema-carpetas` | 1 (`docs/53-bovedas-esquema-carpetas.md`) | **REFERENCIA**; ojo: `main` ya usa el número 53 para otro documento |
| `docs/panel-rpg-management-design` | 1 (`docs/59-PANEL_RPG_MANAGEMENT_DESIGN.md`) | **REFERENCIA** — el 59 sigue libre en `main` |
| `chore/docs-numbering` | 1 (`tests/test_docs_numbering.py`) | **REFERENCIA** útil: `main` tiene hoy **dos documentos numerados 72** |

Dos ramas están **INTEGRADAS** por contenido aunque Git no las dé por
fusionadas: `audit/route-contract-map-v2` (21/21 ficheros idénticos a `main`) y
`chore/backup-manual-y-propuesta-timer` (7/7 idénticos).

## 6. ¿Se perdería algo si mañana se limpiaran los worktrees?

**Sí, tres cosas, y sólo tres.** En orden de gravedad:

1. **Trabajo vivo sin commitear**: los 6 ficheros modificados y el fichero nuevo
   de `agent-aa02be923507cc117` (`feat/viewer-parcialidad-declarada`). No existe
   copia en ningún objeto de Git. Es un agente **en curso** y el worktree está
   **bloqueado**: retirarlo sería destruir trabajo en marcha. **Riesgo real.**
2. **Siete commits sin rama** (§4.3). Retirar el worktree suelta la única
   referencia fuerte; sobreviven en el reflog (caducidad por defecto 90 días) y
   mueren con el primer `gc --prune`. Ninguno contiene un fichero ausente de
   `main`, así que la pérdida es de **historia**, no de funcionalidad.
   Coste de conservarlos: un `git tag` por commit.
3. **El árbol v2.0 de `perf-viewer-scale-v2`**: idéntico a `33d758f`, que hoy
   sólo vive en el reflog de la rama. Superado por su propio HEAD, y su
   restauración sería una regresión de CI. Pérdida sin consecuencia.

**No se perdería nada más.** En particular **no** se pierden: los 3 stashes
(reproducibles al bit), `.recovery/` (superado por `main`, y además vive en el
checkout principal, que ninguna limpieza de worktrees toca), ni las 32 ramas
locales no fusionadas — borrar un worktree **no** borra su rama.

## 7. Recomendaciones al operador (ninguna ejecutada)

**Conservar sin discusión**

1. `agent-aa02be923507cc117`: no tocar mientras el worktree siga bloqueado.
   Si el agente ha terminado, lo correcto es que **él** commitee, no otro carril.
2. Las 4 ramas con trabajo único publicado: `audit/data-contract-health-v1`,
   `feat/admin-operations-dashboard`, `ops/v3-release-readiness`,
   `feat/review-console-v2-readonly`. Están en `origin`: seguras.

**Conservar barato, decidir después**

3. Antes de retirar los 7 worktrees de §4.3, **etiquetar** sus commits
   (`git tag archivo/<nombre> <sha>`) para que dejen de depender del reflog. Un
   tag cuesta 50 bytes; recuperar un commit purgado cuesta no poder.
   Los dos ya integrados (`a995395`, `d1e9f76`) no necesitan ni eso.
4. Igual con `33d758f` si se quiere trazabilidad del laboratorio perf v2.0.

**Se puede retirar, con su razón**

5. **`stash@{0}`, `stash@{1}` y `stash@{2}`**: los tres son reproducibles al bit
   desde commits alcanzables (§2). Aplicar cualquiera de ellos sería una
   regresión. Recomendación: retirar los tres. *Decide el operador.*
6. **`.recovery/`**: superado por `main`; su único delta es la ausencia del
   control de visibilidad. Retirarlo elimina la copia sin política. Antes,
   conviene confirmar que ningún proceso lo cita como respaldo.
7. **`audit/route-contract-map-v2`** y **`chore/backup-manual-y-propuesta-timer`**:
   contenido idéntico a `main`. Se pueden cerrar como fusionadas de hecho.
8. **`audit/viewer-route-contract-map`** y **`perf/viewer-scale-baseline-v1`**:
   superadas por sus v2. Están publicadas: retirar la copia local no pierde nada.
9. Los ~40 worktrees cuyo HEAD **está en `main`** y con el árbol limpio: no
   sujetan nada. Retirarlos es puro espacio en disco.

**Deuda que este inventario destapa, ajena al carril**

10. `main` tiene **dos documentos numerados 72**
    (`72-autoridad-unica-admin-full.md` y `72-saturacion-del-grafo-diagnostico.md`).
    La rama `chore/docs-numbering` trae precisamente el test que lo impide.
11. `docs/53` está ocupado en `main`; `docs/bovedas-esquema-carpetas` reclama
    ese mismo número y habría que renumerarla al integrarla.

**Sin incidencia de seguridad**: se rastrearon `.recovery/` y los ficheros de
`41f8688` buscando contraseñas, tokens, claves y URLs con secreto. Los únicos
aciertos son literales de prueba (`"TestPass_1234567890!"`,
`"alguna_clave_larga_123"`) y nombres de variables (`S9K_CSRF_SECRET`). Nada
que reportar.

## 8. Arqueología diferencial: `origin/feat/review-console-v2-readonly` vs `main` `3f3face`

**Material de referencia, nunca base de rebase ni de desarrollo** (decisión del
operador). El carril C nuevo nace de `main`. Lo que sigue existe para que C no
se escriba dos veces ni olvide una pieza que el primer intento ya tenía.

Un commit, `41f8688`, sobre `d169052`; 7 ficheros, 1757 líneas, todas altas.

**El hallazgo que más cambia el plan**: entre `d169052` y `main` los dos módulos
de los que depende la consola —`viewer/app/services/v3_review.py` y
`viewer/app/routers/v3_review.py`— **no han cambiado ni un byte**. Lo único que
se movió bajo sus pies es `viewer/app/main.py` y `viewer/app/templates/base.html`
(montaje del chasis y navegación por registro). Es decir: **la incompatibilidad
de esta rama es de montaje y de encuadre, no de lógica.** `reason_label`,
`ReviewService.workspaces(scope=)`, `queue(..., include_decided=, scope=)` y
`present()` siguen exactamente donde estaban y con la misma forma.

### 8.1 Pieza por pieza

| Pieza | Líneas | Clasificación contra `main 3f3face` |
|---|---|---|
| `viewer/app/services/review_console_v2.py` | 517 | **VÁLIDO, y es la joya.** Lógica pura de presentación, sin FastAPI ni E/S: `row_view`, `parse_filters`, `apply_filters`, orden por prioridad (`REVIEW` > `ABSTAIN` > `REJECT_INVALID`), paginación *después* de filtrar, facetas, `neighbours`, `review_explanation`, normalización sin acentos, `_clean()` que traduce el marcador `not_available` a ausencia en vez de mostrarlo. No importa nada del chasis ni de autorización. Reutilizable **tal cual** |
| `viewer/app/routers/review_console_v2.py` | 175 | **CONFLICTIVO CON EL CHASIS.** La lógica del handler es válida; el encuadre no. Declara `APIRouter(prefix="/console")` y se monta colgando del router de la cola. El chasis exige `prefix="/panel/review"`, `route_name="chassis_review"`, `role="reviewer"`, `template="chassis/review.html"` y montaje vía `build_slot_router(SLOT)` con `S9K_PANEL_C_ENABLED` (`true`/`1`, apagado por defecto). Hay que reencuadrarlo, no reescribirlo |
| `viewer/app/routers/v3_review.py` (+10) | 10 | **OBSOLETO, y era ya un parche declarado como tal.** El `import` y el `router.include_router(_console_v2.router)` metidos dentro del router de la cola «porque `main.py` tiene otros propietarios». El chasis existe precisamente para eliminar ese apaño: hoy el montaje es un dato en `FEATURE_SLOTS`. **No portar.** (Es también, invertido, el contenido de `stash@{1}`) |
| `viewer/app/templates/review_console_v2.html` | 210 | **VÁLIDO CON RETOQUES.** Extiende `base.html` (que sigue existiendo, con la navegación ahora generada por `chassis_nav`) y trae su CSS en un `<style>` embebido. **Pero fija la URL a mano**: `action="/v3/review/console"`. Enlaces literales a rutas es exactamente el fallo nº 2 que el chasis declara impedir: hay que resolver por **nombre** de ruta |
| `viewer/app/templates/review_console_v2_item.html` | 142 | Igual que la anterior: contenido válido, URLs literales que hay que sustituir |
| `viewer/tests/test_review_console_v2.py` | 529 | **VÁLIDO EN SU MITAD DE LÓGICA, SUPERADO EN SU MITAD DE MONTAJE.** 33 tests. Los de filtrado, orden, paginación, facetas, vecinos y ausencias explícitas se conservan enteros. Los ~18 que llaman a `/v3/review/console…` cambian de URL. Dos merecen conservarse casi literales por lo que prueban: `test_console_exposes_no_write_methods` (POST/PUT/PATCH/DELETE → 404/405) y `test_console_never_writes_the_decision_ledger` (comprueba que `decisions.jsonl` **no llega a existir**). Falta un test nuevo, que en 41f8688 no podía existir: **que con `S9K_PANEL_C_ENABLED` ausente el panel no se sirve** |
| `docs/55-review-console-v2-solo-lectura.md` | 174 | **OBSOLETO como documento, REFERENCIA como contenido.** Colisión de número: `main` ya usa `docs/55` (`55-m5c-cierre-ambito-y-serializadores.md`). Describe el montaje viejo (`/v3/review/console`) y avisa de que «el montaje depende de `app/routers/v3_review.py`». Su §"Limitaciones y datos que el backend NO expone" **sí se conserva**: es inventario medido de lo que el exportador del motor no da (los umbrales del motor, entre otros) |

### 8.2 Lo que el P0 de autorización rompe, y lo que no

La rama **no** contiene ningún `admin_full`, ni bypass, ni vocabulario paralelo
de permisos: delega en `get_visibility_scope` y en el `_guard` de la cola. Esas
dos piezas siguen existiendo en `main` con la misma firma. **Ninguno de los 33
tests afirma «sin auth se ve todo»**, así que ninguno se pone rojo por el P0.

Pero hay un cambio de comportamiento **silencioso** que quien porte el código
debe saber: con `S9K_AUTH_ENABLED=false`, `get_visibility_context` construye hoy
un contexto **anónimo, de mínimo privilegio** (antes decía `admin_full`). El
`_guard` de la cola sigue devolviendo `None` —deja pasar— pero el **ámbito** ya
no concede nada. Resultado: en un banco de pruebas sin auth, la consola
**entra y no muestra nada**, donde antes lo mostraba todo. Eso no es un defecto:
es el diseño nuevo. Lo peligroso sería leer la pantalla vacía como «la consola
está rota» y "arreglarla" reabriendo la vía cerrada por el P0.

### 8.3 Piezas que el segundo C no debe olvidar

Enumeradas porque son lo que se pierde si C se rescribe desde cero mirando sólo
el chasis:

1. **Primero filtrar, después paginar** — con los contadores calculados sobre el
   conjunto filtrado, no sobre la página. Es un error clásico y ya está resuelto.
2. **Acuerdo/desacuerdo motor↔sombra sólo cuando existen las dos partes.**
   Sin sombra el valor es `None`, **no** «acuerdo». Confundirlo fabrica una
   métrica de acuerdo inflada.
3. **`not_available` es ausencia**, no un valor a pintar.
4. **Orden por prioridad de revisión** (`REVIEW` > `ABSTAIN` > `REJECT_INVALID`).
5. **Navegación anterior/siguiente dentro del orden filtrado** (`neighbours`),
   con posición y total.
6. **404 indistinguible** para propuesta inexistente, fuera de ámbito o excluida
   por filtro — mismo contrato que `PolicyFilteredProvider.entity`.
7. **Paquete de propuestas ilegible → 503 con mensaje propio**, sin volcar rutas
   ni trazas.
8. **Umbral de baja confianza (`DEFAULT_LOW_CONFIDENCE = 0.6`) declarado como
   criterio de presentación**, no como umbral del motor. El motor no exporta los
   suyos, y el documento lo dice.
9. **Solo lectura comprobada por enumeración de métodos**, no prometida en prosa.
