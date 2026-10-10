# Auditoría global S9-Knowledge

**Fecha:** 2026-10-10 · **Tipo:** auditoría global, independiente y adversarial, de solo lectura ·
**Objeto:** repositorio `pjclavero/S9-Knowledge` en `origin/main` = `0cf977c3f7785e5f826417efc94971825782bd9d`
(PR #266, «PR-3 (USABLE-V1): la instalación provisiona y VERIFICA su vía HTTPS»).

> Esta auditoría **no valida**: busca contradicciones, caminos muertos, garantías falsas y
> funcionalidades que solo parecen existir. Cuando una propiedad no pudo observarse se
> escribe UNKNOWN / NOT MEASURED, nunca PASS. «Ausencia» no es «cero»; «skipped» no es
> «verde»; «diseñado» no es «implementado»; «implementado» no es «usable».

Convenciones usadas en todo el documento:

| Marca | Significado |
|---|---|
| **OBS** | observado directamente (código con `ruta:línea`, comando con rc, petición HTTP con código) |
| **DEMOSTRADO** | reproducido ejecutando la aplicación o un test en esta auditoría |
| **TEÓRICO** | leído en código, no ejercitado |
| **UNKNOWN / NOT MEASURED** | no se pudo determinar con los medios de la auditoría |
| **KNOWN DEBT / CONFIRMED** | ya estaba declarado en el repositorio; esta auditoría lo confirma |

---

## 0. Mapa de realidad

Veintitrés capacidades principales. Columnas: **Diseño** (hay documento o contrato), **Código**
(hay implementación alcanzable), **Test** (hay tests que la ejercitan, con negativo si se indica),
**CI** (CI la ejecuta y es *required*), **Web** (un administrador la ejerce desde el navegador sin
conocer internals), **E2E** (recorrido real completo demostrado), **Docs** (documentada para quien
la usa). Leyenda: ✅ sí · ⚠️ parcial/con límites · ❌ no · ❓ UNKNOWN.

| # | Capacidad | Diseño | Código | Test | CI | Web | E2E | Docs |
|---|---|---|---|---|---|---|---|---|
| 1 | Instalación en máquina limpia (fresh → `current` → servicio vivo) | ⚠️ | ❌ roto (§8) | ⚠️ syntax/shellcheck | ⚠️ | ❌ | ❌ | ⚠️ |
| 2 | Vía HTTPS verificada por efecto (PR-3) | ✅ | ✅ | ✅ con negativos | ✅ | n/a | ❌ RC-E2E PENDING | ✅ |
| 3 | Bootstrap web del primer administrador (`/setup/admin`, sello, CSRF) | ✅ | ✅ | ✅ concurrencia | ✅ | ✅ | ⚠️ local sí; VM no | ✅ |
| 4 | Login/sesión/logout, Secure/HttpOnly/SameSite | ✅ | ✅ | ✅ + Playwright | ✅ | ✅ (JS obligatorio) | ⚠️ | ✅ |
| 5 | Gestión de usuarios, roles, auditoría (`/admin/users`, `/admin/audit`) | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ |
| 6 | Concesión de acceso a partidas (`/admin/partidas/grant`) | ✅ | ✅ | ✅ | ✅ | ❌ formulario devuelve 422 | ❌ | ⚠️ |
| 7 | Nombres humanos de workspace y partida (6B-1/6B-2) | ✅ | ✅ | ✅ calibrado | ✅ | ✅ | ⚠️ | ⚠️ |
| 8 | Autoridad canónica de workspace (perfil de bóveda, F-2) | ✅ | ✅ | ✅ | ⚠️ calibrador fuera de CI | ❌ exige `.env`/JSON | ⚠️ | ⚠️ |
| 9 | Configuración del producto por web (proveedor, almacenamiento, paneles, grafo) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 10 | Catálogo de material (plano o bóveda jerárquica M1) | ✅ | ✅ | ✅ | ⚠️ calibrador M1 fuera de CI | ⚠️ exige JSON junto a la fuente | ❌ Nextcloud real ❓ | ⚠️ |
| 11 | Solicitud de ingesta desde `/panel/operations` | ✅ | ✅ | ✅ | ✅ | ⚠️ panel apagado por defecto | ⚠️ | ⚠️ |
| 12 | Ejecución de la ingesta (worker de jobs) | ⚠️ | ⚠️ `--loop` roto, sin unidad | ⚠️ 34 passed, sin crash/loop | ⚠️ | ❌ | ❌ | ⚠️ |
| 13 | Ingesta de material de **partida** (sesión de revelación) | ✅ | ❌ por web | ✅ (negativo declarado) | ✅ | ❌ | ❌ | ✅ declarado |
| 14 | Revisión humana de propuestas (`/v3/review`, `/panel/review`) | ✅ | ✅ | ✅ | ✅ | ⚠️ 4 pantallas; aislamiento por workspace roto | ⚠️ | ⚠️ |
| 15 | Sellado y aplicación al grafo con gate (writer, 9 condiciones) | ✅ | ✅ | ✅ Neo4j efímero | ✅ | ⚠️ hash autorreferente en web | ✅ por CLI (doc 53) | ✅ |
| 16 | Resultado y evidencia navegable (`/panel/resultado`) | ✅ | ✅ | ✅ | ✅ | ❌ sin enlace de entrada | ❌ | ⚠️ |
| 17 | Rollback de una aplicación | ✅ | ✅ CLI | ✅ | ✅ | ❌ | ✅ CLI | ✅ |
| 18 | Aislamiento juego/partida en grafo y visor (M2-M5) | ✅ | ✅ | ✅ invariantes | ✅ | ✅ selector | ❌ no desplegado | ✅ |
| 19 | Niebla de guerra `known_by` / visibilidad declarada (M5b) | ✅ | ✅ | ✅ (suite fuera de CI) | ❌ | ✅ | ❌ NO APPLY legacy | ✅ |
| 20 | Multimodal: PDF/OCR/HTR/imagen/audio/vídeo | ✅ | ⚠️ stubs y envoltorios | ⚠️ mocks/sintético | ⚠️ 18 tests nunca corren | ❌ solo `.md/.txt` | ❌ | ⚠️ sobrevendido |
| 21 | Proveedores IA (Ollama/NVIDIA) en la ruta de producto | ✅ | ❌ no cableados | ⚠️ mocks | ❌ | ❌ | ❌ | ⚠️ `providers.env` sin efecto |
| 22 | Salud y operabilidad (`/admin/health`, healthcheck) | ✅ | ✅ | ✅ | ✅ | ⚠️ huérfana; 2 falsas alarmas | ❌ | ⚠️ |
| 23 | Backup/restore y copia fuera del chasis | ⚠️ BKP-4 diseño | ⚠️ scripts manuales | ⚠️ | ⚠️ | ❌ | ⚠️ restore VM ensayado ago-2026 | ✅ honesto |

Lectura rápida: el **núcleo de cuenta y revisión** existe, está testado y gateado; la **instalación de
fábrica, la ejecución desatendida de la ingesta, la configuración por web y la evidencia navegable**
no son usables hoy; **multimodal e IA externa** son diseño y stubs, no producto.

---

## 1. Resumen ejecutivo

S9-Knowledge en `0cf977c` es un repositorio **técnicamente denso y honesto en su mayor parte**
(muchos defectos están declarados por escrito, con calibradores que ponen rojo lo que vigilan), pero
**el producto que un administrador puede usar desde el navegador es mucho más pequeño que el que el
código sugiere**. El objetivo inmediato USABLE-V1 / ZERO-TERMINAL no está alcanzado y **no tiene
documento de programa en el repositorio**.

Lo que está **demostrado**:

- autenticación, sesión, CSRF en las 21 mutaciones censadas, bootstrap atómico del primer
  administrador, instalación «cerrada de fábrica» (`S9K_AUTH_ENABLED=true` por defecto), bypass
  `admin_full` por auth apagada eliminado y declarado;
- recorrido fuente → ingesta → revisión → sellado → apply → procedencia **por CLI** con Neo4j real
  (acta `docs/v3/53`), e invariantes anti-mezcla juego/partida en resolutor, writer y visor;
- CI con **17 jobs, los 17 required**, sin `continue-on-error`, con calibradores de mutación
  para PR-1/2/3, censo de rutas, métodos de escritura y reproducibilidad;
- persistencia tras reinicio del proceso (admin, sesiones, cierre del setup, cola de jobs).

Lo que está **roto o no es usable** (detalle en §18):

- **H-01** no existe camino de instalación en máquina limpia: Ansible exige `current`, `deploy.sh`
  exige `auth.db` con usuarios, nadie crea la primera release y `--mode fresh` está muerto;
- **H-02** el worker de jobs no tiene unidad systemd, su lanzador apunta al layout legacy y
  `--loop` termina al instante (reproducido): la ingesta pedida por web se queda `pending` para siempre;
- **H-03** un revisor sin concesiones en la bóveda B **aprueba** propuestas V3 de B eligiendo el
  `workspace` en el formulario (reproducido): el aislamiento por workspace no se aplica en la
  única superficie de revisión que escribe;
- **H-04** el estado de revisión vive por defecto dentro de la release y no está entre las
  variables críticas del despliegue: un redeploy con los defaults lo pierde;
- configuración por web: **inexistente**. Un administrador necesita como mínimo **5
  intervenciones de terminal/fichero** tras instalar y manejar **~14 conceptos internos**;
- la evidencia (`/panel/resultado`) no tiene ningún enlace de entrada; el formulario de acceso a
  partidas devuelve 422 desde su propio botón; el panel de operaciones está apagado por defecto y
  nada en la web lo revela.

**Documentación**: README, ROADMAP y CHANGELOG describen un repositorio de agosto–septiembre
(233 commits y toda la serie USABLE-V1 ausentes); el gate documental está **verde** con ese
desfase por decisión propia. No hay guía de usuario ni de administrador. Enlaces rotos reales: 0.

**Veredicto global** (§25): arquitectura VERIFICADA con DRIFT; funcionalidad FUNCIONAL CON
LIMITACIONES; integración PARCIAL; zero-terminal BLOQUEADO; instalación BLOQUEADA; seguridad
PARCIAL (1 aislamiento roto demostrado); preparación USABLE-V1 **BLOQUEADA**; entrega externa
**NO**.

---

## 2. Alcance y techo de la auditoría

**Dentro del alcance**: todo el árbol de `0cf977c` (2 023 ficheros versionados), historia Git,
ramas y worktrees locales del checkout `/home/ia02/S9-Knowledge`, PRs y branch protection vía `gh`,
ejecución local de la suite de tests y de la aplicación (TestClient y uvicorn en `127.0.0.1`) con
datos temporales fuera del repositorio.

**Fuera del alcance (techo declarado)**:

| Techo | Consecuencia |
|---|---|
| No se tocó producción (VM105) ni el laboratorio RC (VM110/VM111, apagadas) | Todo lo relativo a estado desplegado es `PENDING_VERIFICATION` desde 2026-08-06, como el propio repo declara |
| Sin Neo4j local ni Docker utilizado para pruebas | 157 tests «sin Neo4j efímero» y ~172 «Neo4j real» quedaron **skipped** localmente; CI sí los ejecuta |
| Sin Chromium utilizable | 175 tests de navegador skipped; 9 ERROR de arnés (§11) |
| Sin Ollama, NVIDIA, Tesseract, spaCy/Stanza, ffmpeg, faster-whisper | 18 tests se saltan aquí **y también en CI** |
| Sin nginx/systemd/DNS/CA real | HTTPS, cookie Secure en TLS real y permisos de servicio: TEÓRICO |
| Calibradores que hacen `git checkout` o escriben el árbol | analizados estáticamente, no ejecutados |
| Los dos `.docx` de la raíz | no parseados |
| Sincronización remota | `git fetch --dry-run` vacío al cierre; nada nuevo en origin durante la auditoría |

La auditoría la realizó un coordinador con ocho auditores independientes por área (documentación,
instalación/zero-terminal, motor y multimodal, rutas y autoridades, seguridad, tests y CI, Git y
PRs, recorridos de usuario). Cinco de ellos murieron por límite de sesión en su primera ejecución y
fueron relanzados; sus informes finales son los consolidados aquí. Salidas crudas en
`/home/ia02/.claude/jobs/b0266fc8/tmp/*-agent/` (fuera del repositorio).

---

## 3. Estado Git exacto auditado

| Dato | Valor |
|---|---|
| Remoto | `https://github.com/pjclavero/S9-Knowledge.git` |
| **HEAD auditado** | `0cf977c3f7785e5f826417efc94971825782bd9d` |
| **origin/main auditado** | `0cf977c3f7785e5f826417efc94971825782bd9d` (idénticos) |
| Último commit | 2026-10-10 04:09 +0200 · «PR-3 (USABLE-V1): la instalación provisiona y VERIFICA su vía HTTPS (#266)» |
| Worktree de auditoría | `/home/ia02/S9-Knowledge/.claude/worktrees/audit-global-2026-10-10`, creado desde `origin/main`, árbol limpio (`git status --porcelain` = 0) al inicio y al cierre |
| Checkout compartido `/home/ia02/S9-Knowledge` | rama `main` @ `730a749`, **415 commits por detrás** de origin/main, 0 por delante; untracked: `.claude/`, `.claude_watch.sh`, `.recovery/` |
| Worktrees | **147** (20 locked, 54 detached, 0 prunables) |
| Ramas locales / remotas | **435** locales (312 solo locales) / 149 remotas (59 no mergeadas en main, de las que ≥17 ya entraron por squash) |
| Stashes | 3 (2026-07-15, 2026-08-08, 2026-08-13), residuos de agentes |
| Tags | 106 locales = 106 remotos; **0 releases de GitHub** |
| Tag de producción | `deploy-v0.3.0-rc5.1` → `47bc314` (2026-07-18), ancestro de main, **84 días y ~230 PR por detrás** |
| Referencia histórica del encargo | `b4da16a` existe: es PR-2 (#264, 2026-10-09), **no** es la punta actual; PR #267 (PR-4) está abierto |
| Branch protection `main` | 17 required status checks, `strict: true` |

Desde #238 (2026-09-19) los PR entran por **squash**; antes, por merge commit. Esto explica que 22
ramas locales con SHAs «no publicados» tengan su contenido en main (§14).

---

## 4. Arquitectura reconstruida

### 4.1 Lo que el proyecto declara

- **Componentes** (`README.md:179-192`): `data-engine/`, `viewer/`, `shared/ (FUTURO)`,
  `deployments/`, `scripts/`, `examples/`. **Omite** `deploy/`, `contracts/`, `tests/`,
  `benchmarks/`, `artifacts/`, que existen. No hay `worker/`: el worker es
  `data-engine/app/jobs/worker.py` + `scripts/run-jobs-worker.sh`, mencionado en `deploy/README.md`
  pero no en el README raíz. `shared/` contiene solo `.gitkeep`. `contracts/` no tiene README.
- **Flujo V3** (`README.md:165-176`, `docs/v3/60:90-91`, `docs/92:142`):
  fuentes → data-engine → extractor → reconciliador → motor local → ledger → plan sellado →
  gate del operador → Neo4j → procedencia → rollback.
- **Superficies** (`docs/69` chasis; `docs/76-80`; `docs/86`; `docs/v3/25`): `/panel/*` es la
  consola canónica con cuatro huecos (B operations, C review, F sources, G entities) más
  `resultado`; `/v3/review` es la superficie operativa de decisión; `/review-console` es
  laboratorio y desde PR-1 no se monta por defecto; `/setup/admin` bootstrap; `/admin/*` cuenta.
- **Producción** (`docs/project-status.yaml`): desacoplada de `main` desde PR #110; VM105 en RC5.1.

### 4.2 Lo que el código ejecuta (OBS)

**82 rutas + 1 mount** enumeradas sobre `app.main.app` (anexo A). 24 POST, 0 PUT/DELETE. De
dominio: 4 en `/panel/operations/*` (ingestas, planes, aplicaciones, altas) y 2 en `/v3/review`
(decide, undo); 1 de laboratorio (`/review-console/.../decide`); 2 sobre la bóveda (labels); el
resto cuenta/admin.

Cadena productiva real, más corta que la declarada (`data-engine/app/knowledge_v3/pipeline/ingest_cli.py:385-428`):

```
.md/.txt/.note en S9K_INGEST_SOURCES_DIR o S9K_VAULT_ROOT
 → POST /panel/operations/ingestas (admin+CSRF) → jobs.db (SQLite)
 → scripts/run-jobs-worker.sh --once → handlers/ingest_v3 → run_ingest(apply=False)
     normalizer → adaptador texto/markdown → extractor determinista (+tabla, temporal, correferencia)
     → reconcile → resolution → engine (ACCEPT/REVIEW/ABSTAIN) → planner (plan sellado)
     → export_review_package (JSON inmutable en proposals/)
 → /v3/review decide/undo → human_decisions (review.sqlite3, visor)
 → POST /panel/operations/planes → sealed_plans
 → POST /panel/operations/aplicaciones → GraphWriter (gate 9 condiciones) → Neo4j
 → persist_provenance → /panel/resultado/{apply_id}
```

Hechos medidos: **cero llamadas a proveedores IA** en la ruta de producto (`provider_calls: 0` en
dry-run local sobre `examples/ingesta-v3/nota-cofradia-de-ambar.md`, rc=0); solo entran por el
producto `.md .markdown .txt .text .note` (`viewer/app/sources_catalog.py:141-146`); la ingesta
web es siempre dry-run y la escritura real ocurre en `viewer/app/services/v3_apply.py:1007-1180`
importando el writer del motor en proceso.

### 4.3 DRIFT entre lo declarado y lo ejecutado

| Declarado | Ejecutado | Fuente |
|---|---|---|
| `docs/69:3-6`: los cuatro paneles «aún no existen» | existen y B escribe (docs/76-80, 86) | prosa SUPERSEDED no marcada |
| `chassis_operations.py:16-19`: «exactamente UNA capacidad de escritura» | `chassis.py:655-738` declara CUATRO | contradicción interna |
| `jobs_client.py:1083` «SOLO LECTURA» | `_load_job_store()` crea jobs (`chassis_operations.py:1087-1092`) | prosa vs código |
| `deploy/README.md:205-221`: `providers.env` configura proveedores | solo lo carga la unidad del visor; el worker usa `worker.env`; `ingest_cli` no construye proveedores | `providers.env` sin efecto |
| M1 «BLOQUEADO por Nextcloud» (README, ROADMAP, yaml) | M1 **mergeado** (#234, `docs/90`, `vault_scope.py`) | estado desactualizado |
| Carril D: 11 xfail ACC | 7 ACC + 2 nav | `docs/60` desfasado |
| Censo CI: «3 muertas / 39 huérfanas, falsos positivos» (`gate.py:228-236`) | hoy 6 / 48 | justificación caducada |
| `KNOWN_JOB_TYPES` | no incluye `ingest_v3`, el único tipo que se usa | `job_store.py:72-76` |

---

## 5. Autoridades y fuentes de verdad

| Concepto | Autoridad canónica | Lectores | Escritores | Derivados / caches | Riesgos | Contradicciones |
|---|---|---|---|---|---|---|
| Usuarios, roles | `auth.db` tabla `users` (`S9K_AUTH_DB_PATH`) | middleware, `require_*` | `/admin/users*`, `/setup/admin`, **CLI `cli/auth.py`** | `User.is_admin()` | **dos escritores** sin coordinación (incidente histórico: reset CLI sobrescribió password) | `can_manage_access`/`can_edit_context_label` derivan de `is_admin`; capacidad declarada sin sistema que la asigne |
| Workspace (bóveda) | `perfil-operador.json` de la bóveda (`autoridad_workspace.py`, F-2); `S9K_DEFAULT_WORKSPACE` es fallback declarado | `existencia.workspace_canonico()`, visibilidad | operador (fichero) | `allowed_workspaces` | formularios aún aceptan `workspace` libre (`jobs.html:28`, `entities.html:8`, `v3_review.html:70`) | `graph.js:16` conserva `"leyenda"` literal |
| Partida y su existencia | **no existe autoridad única** (`authz/existencia.py:19-40`, reconocido): `partida_access` + propiedad en grafo + carpeta en bóveda | `partida_existe`, selector | grants web, ingesta | sesión `active_partida` | conceder ≈ crear | 3 criterios sin reconciliar |
| Nombres humanos | `metadata.label` en perfil y manifiesto de partida (bóveda) | globals Jinja | `POST /admin/partidas/label`, `/label-partida` | ninguno | el visor **escribe en la bóveda** con `os.replace` sin cerrojo (`vault_writer.py:80-88`) | fallback silencioso al ID crudo (`presentacion_etiquetas.py:294-319`) |
| Grants de partida/personaje | `partida_access` (auth.db) | policies | solo web | — | — | CLI no los gestiona |
| Configuración | `.env` del **cwd** + entorno (`config.py:24,47`) | todo | operador | `get_settings()` cacheado vs flags por petición | dos tiempos de lectura; `.env` relativo al cwd | `S9K_REVIEW_CONSOLE_ENABLED`, `S9K_V3_REVIEW_DATABASE_PATH` no están en `.env.example` |
| Secretos | `S9K_CSRF_SECRET`, `S9K_NEO4J_PASSWORD[_FILE]` | auth, provider | operador | — | `validate_deploy.sh` exige secreto explícito → la autogeneración queda fuera en despliegue | — |
| Jobs | `jobs.db` | `/jobs`, `/api/jobs*`, panel | worker externo + `POST /panel/operations/ingestas` | — | **4 rutas por defecto distintas** (`job_store.py:34`, `run-jobs-worker.sh:17`, `deploy.sh:44`, `viewer.env.example:30`) | cliente «solo lectura» que crea |
| Estado de Review | `review.sqlite3` tabla `human_decisions` (visor); `decisions.jsonl` degradado a export | `/v3/review`, `/panel/review`, motor en `ro` | `/v3/review/decide|undo` | — | default **dentro del árbol del repo**; motor devuelve `{}` en silencio si no la encuentra (`review_decisions.py:130-133`) | lab `/review-console` escribe otro JSONL en `/tmp` |
| Sealed plans / apply | `review.sqlite3` (`sealed_plans`) → `apply_v3` | panel, resultado | `POST /planes`, `/aplicaciones` | — | `applying` queda `PLAN_APPLY_IN_FLIGHT` para siempre si el proceso muere (`v3_apply.py:1031-1035`) | hash «teclado por el operador» (`gate.py:51-55`) se lee de la misma fila en la ruta web |
| Grafo | Neo4j vía `GraphProvider`; `S9K_GRAPH_PROVIDER` default `mock` | todo | solo `apply_v3` | `PolicyFilteredProvider` | mock por defecto, marcado DEMO desde PR-2 | — |
| Procedencia | nodos `V3Source/V3Episode/V3Evidence` | `/panel/resultado` | writer | — | sin contrato congelado (declarado, `provenance.py:28-33`) | el writer descarta `bbox`, `speaker`, `table`, `metadata` |
| Providers IA | `S9K_NVIDIA_*`, `S9K_OLLAMA_*`, `S9K_V3_EXTERNAL_*` | solo CLIs y health | — | — | tres familias de nombres Ollama | `NvidiaProcessingProvider` no consulta bandera: basta la API key |
| Almacenamiento | `S9K_VAULT_ROOT`/`S9K_RCLONE_MOUNT` o `S9K_INGEST_SOURCES_DIR` | catálogo, health | operador | — | nadie monta rclone en el repo | `S9K_BACKUP_ROOT` vs `S9K_BACKUP_DIR` |
| Flags de panel | `S9K_PANEL_{B,C,F,G,RESULTADO}_ENABLED`, `S9K_REVIEW_CONSOLE_ENABLED`; `{"true","1"}` fail-closed (`chassis.py:177`) | `slot_enabled` | operador | — | **ninguno encendido en CI** | sin UI para encenderlos |

**IDs de cliente**: revalidados en `/partida/select`, `/admin/partidas/*`, `/panel/operations/*`
(`scoped_job`), `GET /v3/review`. **No revalidado contra concesiones**: `workspace` en
`POST /v3/review/decide|undo` (§9, H-03).

**Autorización distinta para el mismo objeto**: usuarios (web con rol vs CLI sin auth); cola de
revisión en tres pantallas (`/v3/review`, `/panel/review`, `/reviews` legacy); entidades en dos
(`/entities`, `/panel/entities`).

---

## 6. Inventario funcional

Estados: DESIGNED · IMPLEMENTED · TESTED · CALIBRATED · CI-GATED · WEB-USABLE · E2E-MEASURED ·
RC-MEASURED · DOCUMENTED · LIMITED · BROKEN · DRIFT · DEBT · POSTPONED · SUPERSEDED · HISTORICAL · UNKNOWN.

| Función | Usuario | Entrada → salida | Autoridad | UI | API/CLI | Tests · calibrador · CI | Docs | Estados |
|---|---|---|---|---|---|---|---|---|
| Despliegue de release (`deploy.sh`) | operador | repo → `releases/<id>` + symlink + restart + verify | manifest + checksum | — | shell | syntax/shellcheck/validate.sh · sin calibrador · CI required | `deploy/README.md` | IMPLEMENTED, CI-GATED, **BROKEN en fresh**, DOCUMENTED |
| Provisión Ansible (common, data_engine, viewer, systemd, tls, healthchecks) | operador | inventario → host | roles | — | `ansible-playbook` | `--syntax-check` en CI | `deploy/README.md` | IMPLEMENTED, LIMITED (no crea `current`, `.env`, certificados) |
| Preflight HTTPS (PR-3) | operador | URL pública + CA → 7 causas discriminantes | `preflight_https.py` | — | CLI | tests con TLS local, calibrado, CI | sí | TESTED, CALIBRATED, CI-GATED, RC-PENDING |
| Bootstrap primer admin | admin | GET/POST `/setup/admin` → sello + usuario | `auth.db install_state` | ✅ | — | suite + concurrencia 6 POST → 1 admin (DEMOSTRADO) | sí | WEB-USABLE, TESTED, CI-GATED |
| Login / logout / cuenta | todos | formulario (JS obligatorio) → cookie | `auth.db sessions` | ✅ | CLI auth | suite + Playwright | sí | WEB-USABLE, CI-GATED |
| Usuarios y auditoría | admin | `/admin/users*`, `/admin/audit` | `auth.db` | ✅ | CLI (segundo escritor) | suite | parcial | WEB-USABLE, DEBT (dos escritores) |
| Acceso a partidas | admin | `/admin/partidas/grant|revoke` | `partida_access` | ⚠️ POST desde el formulario → **422** (DEMOSTRADO) | — | suite | parcial | IMPLEMENTED, **BROKEN en UI** |
| Nombres humanos | admin | `/admin/partidas/label*` → perfil/manifiesto | bóveda | ✅ | — | suite + calibradores 6B | docs/86-92 | WEB-USABLE, CALIBRATED |
| Catálogo de fuentes | admin | directorio/bóveda → `FuenteDisponible` | perfil de bóveda | ✅ lista | — | suite (M1) · calibrador M1 **fuera de CI** | docs/89-90 | IMPLEMENTED, LIMITED (exige `perfil-operador.json` + `catalogo-workspace.json` junto a la fuente) |
| Solicitud de ingesta | admin | selector → job `ingest_v3` | `jobs.db` | ✅ si `S9K_PANEL_B_ENABLED=true` | CLI jobs | suite | docs/86 | WEB-USABLE condicionado, CI-GATED |
| Worker de jobs | operador | `jobs.db` → handler | — | ❌ | `run-jobs-worker.sh --once` | 34 passed; **ningún test de `--loop`, crash, stale** | `deploy/README.md:369` «NADIE lo provisiona» | IMPLEMENTED, **BROKEN (`--loop`)**, DEBT |
| Extracción determinista + reconciliación + motor + planner | sistema | episodios → plan sellado | contratos v3-internal-v1 | — | `ingest_cli` | amplia; Neo4j efímero en CI | docs/v3 | TESTED, CI-GATED, E2E-MEASURED (texto, CLI) |
| Revisión humana V3 | reviewer | `/v3/review` decide/undo/correct | `review.sqlite3` | ✅ | — | suite | docs/v3/25 | WEB-USABLE, **LIMITED (sin aislamiento por workspace)** |
| Sellado y apply | admin | `/panel/operations/planes|aplicaciones` | `sealed_plans` + gate | ✅ | `ingest_cli --apply`, `writer/cli.py` | suite + Neo4j efímero | docs/v3/60 | IMPLEMENTED, CI-GATED, LIMITED (hash autorreferente, sin rollback persistido en web) |
| Rollback | operador | `rollback.json` → Neo4j | fichero | ❌ | CLI | suite | docs 56/58 | IMPLEMENTED (CLI), E2E-MEASURED (CLI) |
| Resultado y evidencia | reviewer | `/panel/resultado/{apply_id}` | grafo | ⚠️ sin entrada | — | suite | docs/v3/64 | IMPLEMENTED, **no WEB-USABLE** |
| Visor de grafo/entidades | todos | `/graph`, `/entities`, `/panel/entities` | grafo filtrado | ✅ | `/api/graph` | suite + Playwright | docs/61 | WEB-USABLE, DEBT (saturación `/api/graph` declarada «no se arregla») |
| Multi-partida (M0-M5) | sistema | `partida_id`, `scope`, `known_by` | contratos | selector | — | invariantes; suite visibilidad **fuera de CI** | docs/v3/49-51 | IMPLEMENTED, TESTED, no desplegado |
| Health | admin | `/admin/health`, CLI, timer | `health.json` | ⚠️ huérfana | CLI | suite | sí | IMPLEMENTED, LIMITED (base URL fija 8088; falsas alarmas) |
| Backup Neo4j / restore | operador | scripts manuales | — | ❌ | shell | tests parciales | docs/52-53/71 | IMPLEMENTED (manual), DEBT P0 off-host |
| Proveedores IA (Ollama/NVIDIA/burst) | — | — | — | ❌ | CLIs | mocks; 18 tests nunca ejecutados | docs/v3 | DESIGNED/IMPLEMENTED aislado, **no conectado al producto** |
| Multimodal no-texto | — | ver §17 | — | ❌ | `--source-kind` | mocks/sintético | docs/v3/02,26,29,31 | DESIGNED, LIMITED |
| Review console (lab) | reviewer | fixtures demo → JSONL en `/tmp` | — | 404 por defecto | — | suite | docs/76 | HISTORICAL/LAB, apagada |
| Motores v1/v2, relations, external_ai | — | — | — | — | CLIs huérfanas | solo tests | docs/archivados | SUPERSEDED / HISTORICAL (~35 k líneas) |

---

## 7. Recorridos de usuario

Ejecutados con **uvicorn real** en `127.0.0.1` (puertos efímeros), sin Neo4j, datos en directorio
temporal; una instancia con paneles apagados (defecto) y otra con `S9K_PANEL_*_ENABLED=true`.

### 7.1 Administrador desde cero

| # | Paso | Web | Terminal | Fichero | ID interno | Resultado observado | Siguiente paso claro |
|---|---|---|---|---|---|---|---|
| 1 | Raíz | ✅ | — | — | — | `GET / → 302 /login → 303 /setup/admin` | ✅ |
| 2 | Primer admin | ✅ | ⚠️ | `.env` (`S9K_SESSION_SECURE=false` si no hay TLS) | — | `POST → 303 /login?message=bootstrap_ok`; después `404` JSON | ✅ |
| 3 | Login | ✅* | — | — | — | `302 /`; *«Este formulario necesita JavaScript» (`login.html:85`) | ✅ |
| 4 | ¿Qué falta configurar? | ⚠️ | — | — | «not_configured» | portada: «Base de conocimiento todavía no configurada. Pide a quien administra… o activa el modo de demostración» — **el admin soy yo y no hay pantalla de configuración** | ❌ callejón |
| 5 | Almacenamiento | ❌ | ✅ | `.env` | rclone, bóveda, `S9K_VAULT_ROOT` | `/admin/partidas` manda a «configuración de S9K_VAULT_ROOT» (`partidas.html:153`) | ❌ |
| 6 | Proveedor IA | ❌ | — | — | ollama, «modo sombra», «mock disponible» | solo filas en `/admin/health` | ❌ |
| 7 | Juego/contexto | ❌ | — | `.env` + `perfil-operador.json` | workspace, perfil de bóveda | banner `WORKSPACE_AUTHORITY_DIVERGENT… (S9K_DEFAULT_WORKSPACE=)` | ❌ |
| 8 | Partida | ❌ | — | manifiesto | partida_id | formulario `/admin/partidas/grant` sin campo partida → **`422 Field required partida_id`** | ❌ acción falsa |
| 9 | Usuarios | ✅ | — | — | roles en inglés | crear/editar/revocar/auditoría | ✅ |
| 10 | Material | ⚠️ | ✅ copiar | `.md` + **2 JSON** | perfil, catálogo | con solo el `.md`: `SOURCE_PACKAGE_INVALID` «El paquete de la fuente no es valido» sin decir qué falta (`sources_catalog.py:152-153`) | ❌ |
| 11 | Ingesta (panel apagado) | ❌ | ✅ reiniciar | `.env` `S9K_PANEL_B_ENABLED` | panel B | `GET /panel/operations → 404 "El panel Operations está apagado"`; **sin enlace en el menú** | ❌ |
| 12 | Ingesta (panel encendido) | ✅ | — | — | «catalogo-plano-sin-boveda», `data-ambito="None"` | `303 ?solicitado=<uuid>`; trabajo `pending` | ✅ |
| 13 | Progreso | ⚠️ | ✅ worker | — | `ingest_v3`, payload JSON con rutas absolutas | `pending` para siempre; antes del encolado: «jobs_db_not_found… ver docs/15-jobs-worker-panel.md» → **fichero inexistente** (`jobs.html:13`) | ❌ |
| 14 | Revisión | ❌ | — | — | workspace | `/v3/review?workspace=… → 404 "Workspace no encontrado"` (sin Neo4j no hay workspaces) | ❌ |
| 15 | Aprobar/rechazar | no alcanzable sin worker | | | proposal_id | `/panel/review` honesto: «Sin propuestas visibles» | — |
| 16 | Sellar/aplicar | no alcanzable | | | apply_id | por código `GRAPH_UNAVAILABLE` → `?aviso=APPLY_FAILED` | — |
| 17 | Conocimiento | ✅ vacío | — | — | — | `/entities`, `/graph`, `/quality` con banner honesto | — |
| 18 | Evidencia | ❌ | — | `.env` `S9K_PANEL_RESULTADO_ENABLED` | apply_id | apagado 404; encendido `RESULT_NOT_FOUND`; **ningún enlace de entrada** | ❌ huérfana |
| 19 | Logout → login | ✅ | — | — | — | `302`; anónimo en `/admin/users → 401` JSON | ✅ |
| 20 | Reinicio del proceso | — | ✅ | — | — | sesión válida, 3 usuarios, setup cerrado, job pending **persisten** | ✅ |

**Salud**: `/admin/health` reporta `viewer UNHEALTHY ConnectError` (base URL fija `http://127.0.0.1:8088`,
`health/checks.py:60`) y `systemd UNHEALTHY` mientras la propia página responde: dos falsas alarmas
ininterpretables para el admin.

### 7.2 Otros recorridos

- **Viewer (`lector`)**: menú reducido correcto; por URL `/admin/*`, `/v3/review`, `/sources`,
  `/quality` → 403 **JSON**; solo `/reviews` devuelve HTML con «Ir al inicio». 1 de 7 denegaciones
  es una página.
- **Reviewer**: ve las pantallas de revisión; sin workspace resoluble todo acaba en 404 JSON.
- **Sin bóveda**: `/admin/partidas` explica bien el porqué, pero la solución es editar `.env`/montar rclone.
- **Instalación sin configurar**: honesta (sin mock), sin ruta de salida desde la web; remite a un
  «modo de demostración» que no es activable desde la web.
- **Parcialmente configurada** (fuentes sí, grafo no): la ingesta se encola y la revisión es
  inalcanzable; `pending` indefinido sin explicación.

### 7.3 Crawler autenticado (26 GET, 11 formularios)

Sin 500. 404: `/panel/*` apagados (sin enlace, sin UI para encender); `/panel/resultado*`
(huérfana); `/review-console` (bandera no documentada); `/v3/review?workspace=…` y
`/panel/{review,sources}/?workspace=…` (resultado de enviar el propio formulario); `grant` → 422;
`docs/15-jobs-worker-panel.md` (referencia muerta). **Huérfanas GET 200**: `/quality`,
`/admin/health`, `/v3/review/glossary-candidates`. **Menú inconsistente**: en `/admin/*`, `/jobs`,
`/reviews`, `/account` el menú pierde Fuentes/Reviews/Revisión V3/Admin/Partidas
(`base.html:21` recibe `auth_user` indefinido). `/jobs/{id}` y `/admin/audit` sin vuelta.
Formularios con `action` **absoluta** (`http://127.0.0.1:18766/...`): romperán tras un proxy.

### 7.4 Momentos en que un administrador nuevo tuvo que salir de la web (16)

1. Saber `S9K_SESSION_SECURE=false` para que el setup funcione sobre HTTP. 2. Leer
`viewer/.env.example`; `S9K_V3_REVIEW_DATABASE_PATH` solo está en código. 3. Descubrir que `.env`
se lee del cwd. 4. Descubrir que existen `/panel/*` y qué los enciende. 5. Reiniciar el proceso.
6. Interpretar «Base de conocimiento no configurada» como «falta `S9K_GRAPH_PROVIDER`».
7. Interpretar `SOURCE_PACKAGE_INVALID` leyendo código y copiar dos JSON. 8. Interpretar
`WORKSPACE_AUTHORITY_DIVERGENT`. 9. Saber qué es un worker y cómo arrancarlo (la web remite a un
doc inexistente). 10. Interpretar el 422 de `partida_id`. 11. Saber que «Workspace no encontrado»
= «no hay Neo4j». 12. Conocer el UUID del job. 13. Entender los falsos UNHEALTHY. 14. Descubrir
`S9K_REVIEW_CONSOLE_ENABLED`. 15. Descubrir `/quality`, `/admin/health`, `glossary-candidates`.
16. Diagnosticar que el «modo de demostración» no es activable.

---

## 8. Instalación y ZERO-TERMINAL

### 8.1 Hitos

| Hito | Estado en `main` | PR #267 (abierto) |
|---|---|---|
| DEPLOY_OK | **solo en UPGRADE** sobre host con `auth.db` ≥1 usuario; en máquina limpia `deploy.sh` muere (§8.2) | nada |
| HTTPS_PATH_VERIFIED | implementado y calibrado contra TLS local; **RC-E2E PENDING** declarado | nada |
| FIRST_ADMIN_PENDING | soportado (`/setup/admin`, sello, CSRF autogenerado 0600) | preflight `preflight_setup_admin.py` que recorre GET→cookie→POST→303→sello→login→restart contra uvicorn+TLS local; no es paso de `deploy.sh` |
| FIRST_ADMIN_VERIFIED | no hay herramienta | sí, solo en arnés local (sin nginx/systemd/VM/navegador) |
| INSTALLATION_COMPLETE | **NO**: ninguna fila del guion RC (`deploy/README.md`, `docs/91`) ejecutada; VM110/VM111 apagadas | añade filas N8–N12; sigue PENDING |

### 8.2 Camino de máquina limpia: indefinido (OBS)

1. Ansible (`roles/common`, `data_engine`, `viewer`, `systemd`, `tls`, `healthchecks`) crea
   directorios, clona a `.repo-cache`, instala unidades y vhost, pero **no crea `releases/<id>` ni
   `current`** (`grep -rn current deploy/ansible` → solo `stat`/`AssertPathExists`); `s9k_release_id`
   está definido y **no se usa**; `deploy.env`/`viewer.env` **no se crean** (solo `debug` de aviso).
2. `deploy.sh` paso 4: `EMPTY_STATE|CONFLICTING_STATE|CORRUPT_STATE) die …` (`deploy.sh:206`) **no
   consulta `MODE`**; `detect_state._usable` exige `counts.users > 0`. `--mode fresh` devuelve
   PROCEED en el paso 3 y muere en el 4: **opción muerta**. Verificado:
   `detect_state.py … --mode fresh → PROCEED rc=0`; `--mode upgrade → rc=3`.
3. El visor no arranca vía systemd sin `current` (`AssertPathExists`) → no crea `auth.db` → no hay
   usuarios → `deploy.sh` sigue bloqueado.

`deployments/local-vm105/README.md` (histórico, «no ejecutado») es el único texto que describe crear
venv y `.env` a mano, en el layout legacy. **FIRST_RELEASE_PATH = UNDEFINED.**

### 8.3 TLS, cookies, CSRF, proxy, permisos, atomicidad

- **TLS**: `roles/tls` escribe el vhost (80→308, TLS 1.2/1.3, HSTS, `X-Forwarded-Proto https`),
  **no genera certificados**; sin ACME ni renovación en el repo; `s9k_tls_verify: false` apaga la
  verificación sin aviso.
- **Secure**: solo por `S9K_SESSION_SECURE` (default `True`, `auth/config.py:62`); no mira scheme
  ni `X-Forwarded-Proto` (decisión D3). HTTP + Secure = bucle 403 en `/setup/admin`; la plantilla lo
  achaca a «Safari». `false` **solo avisa** (`security.py:179-183`).
- **Host**: sin `TrustedHostMiddleware`; `url_for` compone redirecciones absolutas (§9, H-05).
- **CSRF**: double-submit firmado en login/setup; token por sesión en el resto; validación
  **por handler** (no middleware); `validate_deploy.sh` exige `S9K_CSRF_SECRET` explícito ≥32.
- **Permisos**: validados fichero de contraseña Neo4j, clave TLS, `providers.env`, informe de salud;
  **no** validados `viewer.env`, ni `auth.db` (se crea 0644, §9 H-06).
- **Dos unidades systemd del visor**: `roles/systemd/templates/s9-knowledge-viewer.service.j2`
  (User/Group www-data, assert de `providers.env`) frente a `viewer/systemd/s9-knowledge-viewer.service`
  (sin `User=` → root). `deploy.sh` instala **la del repo** sobre la de Ansible; alternarlos cambia el
  propietario de `.csrf_secret`/`auth.db-wal`.
- **Atomicidad**: `auth.db` WAL + transacción única en bootstrap; `jobs.db` `BEGIN IMMEDIATE`;
  `review.sqlite3` `BEGIN IMMEDIATE`; JSON con `os.replace`; propuestas `mkstemp+fsync+replace`;
  symlink `current` atómico. **No atómicos**: salidas CLI (`write_text`), ledger JSONL, `media/store.py`.
- **Rollback**: `deploy.sh` revierte symlink+restart en 14 y 16; `rollback-*.sh` **no restauran SQLite**;
  `neo4j-backup.sh` hace `chmod 777` del directorio y no tiene `trap`.

### 8.4 Inventario de configuración (resumen; anexo B con las 161 variables de código)

| Clase | Nº | Superficie web | Ejemplos |
|---|---|---|---|
| PRODUCT CONFIG | ~35 | **ninguna** | `S9K_DEFAULT_WORKSPACE`, `S9K_VAULT_ROOT`, `S9K_INGEST_SOURCES_DIR`, `S9K_PANEL_*_ENABLED`, `S9K_ALLOW_REAL_INGEST`, `S9K_V3_REVIEW_*`, `S9K_OLLAMA_*`, `S9K_NVIDIA_*`, `S9K_TESSERACT_CMD` |
| DEPLOYMENT CONFIG | ~45 | ninguna | `S9K_PUBLIC_BASE_URL`, `S9K_SESSION_*`, `S9K_AUTH_*`, `S9K_CSRF_SECRET`, `S9K_NEO4J_*`, `S9K_AUTH_DB_PATH`, `S9K_JOBS_DB`, `S9K_HEALTH_*`, `S9K_BACKUP_*` |
| INTERNAL/DEBUG/CI | ~55 | n/a | `S9K_CI_ORACLE`, `S9K_BENCH_*`, `S9K_ROUTE_PROBE_OUT`, `S9K_WRITER_NEO4J_REAL` |
| AUTODETECTABLE/DERIVABLE | ~10 | n/a | `S9K_HEALTH_VIEWER_URL`, `S9K_PUBLIC_BASE_URL` (de `s9k_public_host`), `S9K_AUTH_DB_PATH` |
| OBSOLETE | 4 | — | `S9K_ENV`, `S9K_LOCAL_BASE_URL`, `S9K_LOG_ROOT`, `s9k_release_id` |
| UNKNOWN | 1 | — | `S9K_SCANNER_STATE_PATH` («pendiente de que el escáner exista») |

Ficheros manuales: `/etc/s9-knowledge/{deploy,viewer,providers,worker,ensayo-rc}.env`,
`inventory.ini`, `workspace.json` (CLI), `perfil-operador.json`, `catalogo-workspace.json`,
manifiesto de partida. **Ninguna pantalla escribe configuración.**

### 8.5 Qué impide hoy los tres ceros

| Objetivo | Impedimentos concretos en `main` |
|---|---|
| TERMINAL POST-INSTALL = 0 | primera release (§8.2); `deploy.env`/`viewer.env`/secreto CSRF/fichero 0600 Neo4j; certificado + `inventory.ini` + `ansible-playbook`; `providers.env` + restart; `.env` para bóveda/fuentes; `create_workspace.py` + 3 variables; **worker** (sin unidad, venv del motor que ningún script instala); cuenta Neo4j de solo lectura (imposible en Community); Cypher manual para nodos sin `state_hash`; `systemctl enable --now` de timers; paneles por `.env` + restart |
| MANUAL CONFIG FILE EDITING = 0 | todo lo anterior salvo usuarios/grants/labels; `perfil-operador.json` y `catalogo-workspace.json` junto a cada fuente |
| INTERNAL IDS REQUIRED = 0 | `workspace` tecleado (`partidas.html:135`), `character_id` con formato `pc:ana` (`:208`), `job_id` en URL, `claim_id`/`entity_id`/`plan_hash` en CLI, `apply_id` en URL |

---

## 9. Seguridad e integridad

| ID | Rango | Hallazgo | Tipo | ¿Documentado? |
|---|---|---|---|---|
| H-03 (SEC-02) | **1** | Un reviewer con concesiones solo en `leyenda` ve y **aprueba** propuestas V3 de otro corpus eligiendo `workspace` en el formulario. `_scoped()` devuelve `scope.partida_only()` («`workspace` como etiqueta del corpus», `services/v3_review.py:785-793`); `record()` solo exige `item["workspace"] == workspace`. **DEMOSTRADO**: `rev1 GET /api/workspaces → ["leyenda"]`; `rev1 POST /v3/review/decide workspace=bench-dev → 303`; 1 decisión registrada. En `/reviews` y `/api/entities` el parámetro sí se ignora. | DEMOSTRADO | parcial (`partida_only` escrito como barrera anti lore anónimo, `docs/81`; el cruce entre revisores no está en `risk-register.md`) |
| H-05 (SEC-01) | 2 | `Host` controla la URL absoluta de los redirects del panel (`request.url_for`, `chassis_operations.py:1122,1201,1249`); sin `TrustedHostMiddleware`; uvicorn sin `--proxy-headers`. **DEMOSTRADO**: `POST /panel/operations/ingestas Host: evil.example → 303 Location: https://evil.example/panel/operations/?aviso=…`. Formularios también con `action` absoluta (§7.3). | DEMOSTRADO | NO |
| H-06 (SEC-03) | 2 | `auth.db` se crea **0644** (hashes de contraseña y de sesión legibles por cualquier usuario local); sin `chmod`/`umask` en `auth/db.py`, `bootstrap.py`, `cli/auth.py`; la unidad del visor no fija `UMask=` (la de healthcheck sí). **DEMOSTRADO** con `umask 022`. | DEMOSTRADO | NO |
| H-20 (SEC-04) | 3 | Bloqueo por cuenta sin límite por IP: 5 POST anónimos bloquean al admin 15 min; con un solo admin, desbloqueo solo por CLI. **DEMOSTRADO**. | DEMOSTRADO | NO |
| H-21 (SEC-05) | 3 | Nombres de usuario confusables aceptados: `аdmin` (U+0430), `admin ` (inalcanzable: el login hace `strip()`), `Admin`, `<b>admin</b>`. **DEMOSTRADO**. | DEMOSTRADO | NO |
| SEC-06 | 3 | `X-Forwarded-For` confiado sin lista de proxies si `S9K_AUTH_TRUST_PROXY_HEADERS=true` (solo `ip_hash`). | TEÓRICO | NO |
| SEC-07 | 3 | `str(exc)` de dominio en `detail` de rutas admin (sin trazas). | TEÓRICO | NO |
| SEC-08 | 4 | 6 sitios interpolan `request.url.path` en `/login?next=` sin codificar (revalidado después). | TEÓRICO | KNOWN DEBT (`next_url.py`) |
| SEC-09 | 4 | `.env` relativo al cwd. | TEÓRICO | declarado en el módulo |
| H-35 | 3 | `S9K_SESSION_SECURE=false` solo avisa; HTTP+Secure = bucle 403; la plantilla culpa a Safari. | OBS | parcial (`deploy/README.md`) |

**Controles verificados (funcionan)**: CSRF en las 21 mutaciones (`/partida/select`, `/logout`,
`/admin/users/new` sin token → 422; `/panel/operations/ingestas` → 403); cookie
`HttpOnly; Secure; SameSite=lax; Max-Age=43200`; sesión regenerada en login y revocada en logout;
Argon2id con `enforce_auth_security` que aborta con PBKDF2 o secreto débil; `/docs` 404 con auth;
bootstrap concurrente 6 POST → `[404,404,303,404,404,404]`, un admin; `_safe_next` por componentes
rechaza `//`, `\`, esquemas, no-ASCII, `..`; autoescape Jinja sin `|safe`, `esc()` antes de
`innerHTML`; traversal en fuentes cerrado (`../leyenda` → 404); Cypher parametrizado con allowlist de
orden; `subprocess` solo `systemctl is-active` con lista fija; `admin_full` deriva únicamente de
`role=="admin"` y la instalación de fábrica trae `S9K_AUTH_ENABLED=true` (PR #248 confirmado);
visibilidad: viewer/reviewer → 404 en `secret`/`narrator`.

**Integridad**: escrituras atómicas donde importa (§8.3); `PLAN_APPLY_IN_FLIGHT` sin herramienta de
reconciliación tras un crash (H-19); decisiones humanas ignoradas en silencio si el motor no
encuentra `review.sqlite3` (H-18); `visibility` del payload de ingesta es un campo muerto y todo lo
escrito por la web sale `SECRET` por defecto (H-17, seguro pero silencioso); hashes de plan sin
clave (cualquiera puede resellar: documentado).

**UNKNOWN**: aislamiento entre dos bóvedas reales en Neo4j (el mock solo trae `leyenda`);
comportamiento del nginx de VM105 respecto a `Host`.

---

## 10. Datos, persistencia, backup/restore

| Almacén | Autoridad / formato | Atomicidad | Persistencia | Backup | Restore demostrado | Riesgo |
|---|---|---|---|---|---|---|
| Neo4j (grafo) | contenedor Community 5.26 externo al repo | transacciones del writer; rollback por apply | volumen host | `scripts/backup/neo4j-backup.sh` manual; timer propuesto NO activado | dump restaurado en contenedor aislado (docs/52); restore de VM 8,2 min sobre VMID 900 sin validar contenido (docs/53); **ambos en el mismo chasis** | off-host **inexistente** (docs/71: 0/23 garantías calibradas) |
| `auth.db` | SQLite WAL esquema v4 | transacción sello+admin | `/var/lib/s9-knowledge/auth` (deploy) o `viewer/state` (plantilla) | copia manual docs/52 | ensayo en dir aislado | 0644; `rollback-*.sh` no restauran SQLite |
| `.csrf_secret` | fichero 0600 | `mkstemp+os.link` | junto a auth.db | **no inventariado** | — | perderlo invalida todas las sesiones |
| `jobs.db` | SQLite WAL | `BEGIN IMMEDIATE` | `/var/lib/s9-knowledge/jobs` | docs/52 | — | 4 defaults distintos; `running` huérfano sin `--release-stale-seconds` |
| `review.sqlite3` + propuestas | SQLite + JSON inmutable | `BEGIN IMMEDIATE`; `mkstemp+fsync+replace` | **default dentro de la release** (`viewer/output/reviews-v3`); no en `CRITICAL_ENV_VARS` | no explícito | no | **pérdida silenciosa en redeploy** (H-04); `applying` eterno tras crash |
| Ledger temporal | JSONL append | no | por workspace | no | no | sin uso productivo (`InMemoryLedgerStore` en pipeline) |
| Procedencia | nodos del grafo | CREATE-only | Neo4j | con el grafo | — | sin contrato congelado |
| Applied-keys / audit del writer | CLI: JSONL sin fsync; **web: en memoria** | no | — | — | — | auditoría del apply web no persiste |
| Health report | JSON 0600 `os.replace` | sí | `S9K_HEALTH_REPORT_PATH` | efímero | n/a | — |
| Releases | `releases/<id>` + manifest + checksum | symlink atómico | retención 3 | n/a | rollback de symlink en tests | — |

**Tras reiniciar**: nada se pierde si las rutas están fuera de la release (DEMOSTRADO localmente).
**Tras actualizar** con los defaults de `viewer/.env.example`: `review.sqlite3`, propuestas,
`.csrf_secret`, health report; `auth.db`/`jobs.db` solo si no se declararon (están en
`CRITICAL_ENV_VARS`). **Migraciones**: no existe `data-engine/migrations`; solo aditivas ad hoc
(`job_store._migrate_schema`, `v3_review_store._migrar`, `migrate_sqlite.py`, `schema_compat`).
**Restore probado**: Neo4j (dump) y VM completa, agosto 2026, mismo chasis; SQLite solo copia manual.

---

## 11. Tests, calibradores y CI

### 11.1 CI y protección de rama (OBS, parseado con PyYAML)

16 jobs en `ci.yml` + 1 en `supply-chain.yml` = **17 contextos, mapeo 1:1 con los 17 required**.
Cero `needs`, cero `if`, cero `continue-on-error`; las 5 apariciones de `|| true` son comentarios
que dicen «Sin `|| true`». Solo `deployment-validation` tiene `timeout-minutes` (15); los demás
heredan 360.

Run `push` de `0cf977c`: CI 38015906379 y supply-chain 38015906411, ambos `success`. Duraciones:
**Calibracion de gates 4 616 s (77 min)** en un único job serial de 35 pasos
(`calibra_ejecucion_real` 1 806 s, `calibra_suite_inventory` 1 238 s, `calibra_registro_xfail`
329 s); Data Engine 620 s; Metodos de escritura 583 s; Combined 475 s; Censo 292 s; Playwright
290 s; Viewer 276 s; Authz 198 s; resto ≤73 s. `viewer/tests` se ejecuta íntegro 3–4 veces por run.

### 11.2 Inventario y ejecución (SHA `0cf977c`, árbol limpio sí)

| Medición | Comando | rc | Resultado | Techo |
|---|---|---|---|---|
| Colección | `python3 -m pytest --collect-only -q -p no:cacheprovider` | 0 | **9 919 tests, 0 errores** | — |
| Suite completa | `python3 -m pytest -q -rs -p no:cacheprovider -o cache_dir=<tmp> > full.txt 2>&1` | **1** | `9378 passed, 525 skipped, 7 xfailed, 9 errors` en 562 s | sin Neo4j/Chromium/Ollama/NVIDIA/Tesseract |
| Todo salvo data-engine | ídem acotado | 1 | `3802 passed, 363 skipped, 5 xfailed, 9 errors` | ídem |
| Contratos visibilidad (fuera de CI) | `pytest contracts/knowledge-visibility/v1/tests` | 0 | 22 passed | juntos con knowledge-v3: **1 failed** por colisión de `generate_examples` en `sys.path` |
| Jobs/worker/media | `pytest` 6 ficheros | 0 | 34 passed | ningún test de `--loop`, crash, stale |
| `worker.py --loop` | `timeout 10 python3 … --loop --sleep-seconds 1 --db <tmp>` | **0 inmediato** (esperado 124) | «Jobs procesados: 0» | causa: `--limit` default 1 entra en `if once or limit` (`worker.py:213-218,239`) |
| `check_docs_consistency.py` | `python3 scripts/check_docs_consistency.py` | 0 | «DOCUMENTACION COHERENTE (DESFASADA: main_commit 233 commits por detras; 9 PR fusionados despues del declarado)»; `latest_ci` NO contrastado (sin `S9K_CI_ORACLE`) | con `-I` falla por `yaml` en user-site |
| Censo de rutas | `scripts/route_map/route_map.py --skip-probe` | 3 (esperado sin sonda) | definidas 78 / montadas 82; muertas 6 (falsos positivos) / huérfanas 48 / sin guardián estático 1 / sin auth 0 | la puerta solo bloquea hallazgos duros |

Los **9 errors** son `ERROR at setup` por `playwright TargetClosedError` en
`test_browser_next_calibracion.py` (6) y `test_browser_next_open_redirect.py` (3): fixture propia
que esquiva la guarda `pytest.skip("chromium no disponible")` de `browser/conftest.py:99`. rc=1
local por causa ajena al producto; en CI no ocurre.

**Skips agrupados**: 157 «sin Neo4j efímero», 175 «chromium no disponible», ~172 «Neo4j real»,
8 Tesseract, 5 Ollama, 3 NVIDIA, 2 spaCy/Stanza. Neo4j y navegador se cubren en CI (service, pasos
«Cobertura Neo4j REAL» con descubrimiento AST y guarda anti-skipped). **Ollama/NVIDIA/Tesseract/
spaCy/Stanza (18 tests) se saltan también en CI: nunca se ejecutan en ningún sitio.**

**Fuga al árbol**: la suite deja `viewer/output/reviews-v3/` y `viewer/state/auth.db` (49 KB) +
`auth.bak.v0` dentro del repositorio (gitignorados). También importar `app.main` abre
`viewer/output/reviews-v3/review.sqlite3` por defecto (`services/v3_review.py:476-483`) aunque las
variables apunten fuera (H-13).

### 11.3 Calibradores y gates

**Sólido**: `check_ci_config.py` parsea YAML (`safe_load`) y solo aplica regex al shell de cada
`run:`; `check_suite_inventory.py` usa AST (79 usos) y toma la base con `git show <merge-base>:ruta`
sin fallback al árbol; `--sin-base` solo explícito y medido; `registro_xfail.py` lee de git; el
censo lee la puerta de la base por AST; `mutaciones_p0_auth.py` mide ablación + suficiencia con
`collected>0`; `localizadores.py` sustituye `replace(…,1)` por localización AST con ambigüedad ⇒
DETECTOR ROTO. Guardias anti-cero y anti-skipped en todos los pasos pytest.

**Fragilidades (regla 19: el orden como contrato)**: `calibra_gate_integrity.py` muta `ci.yml` con
`texto.replace(viejo, nuevo, 1)` (l.168) y `texto.index("\n  test-neo4j-authz:")` (278-279);
`check_env_reproducibility_calibration.py` ancla con `index(f"  {nombre}:\n")` y
`replace("node-version: '20'", …)`; la mayoría de `mutaciones_*.py` en CI siguen con `.replace(…,1)`
(corte1 ×3, corte6a/6b1/6b2b, pr3, s1_selector, topologia, workspace_autoridad, calidad_datos ×2);
solo p0_auth usa `localizadores`.

**Calibradores que existen y CI no exige** (0 menciones en `ci.yml`): `mutaciones_p0_auth.py`
(**P0-AUTH admin_full**), `mutaciones_m1_ambito_boveda.py`, `f2_autoridad_workspace.py`,
`mutaciones_instalacion_fabrica.py`, `negacion_a_distancia.py`, `mutaciones_corte4_revision.py`,
`mutaciones_corte5_signo_y_causa.py`, `medida_operador_ambito.py`. Sus suites corren; la prueba de
«rojo por la causa correcta» es histórica, no vigilada.

**Sin negativo ni calibrador**: `check_unicode.py` (Trojan Source) y `check-imports`
(regex `sys\.path\.(insert|append)\s*\(.*['\"]\/opt`, no ve `sys.path[0:0]=` ni rutas construidas).

**Instrumentos que se miden a sí mismos**: ejemplos de contratos knowledge-v3 generados por
`v3_fixtures.py` y sellados con el mismo validador (compensado parcialmente por «roundtrip +
mutación»); `compute_plan_hash`/`compute_decision_hash` sin segunda implementación ni known-answer.

**Playwright**: uvicorn real, `S9K_AUTH_ENABLED=true`, SQLite y CSRF reales; superficie: login,
entidades, admin/users, graph, `next=`, accesibilidad, backend caído, filtros V3. Nunca con Neo4j.

**Flakiness**: sin `rerun`/`retry`/`continue-on-error`; últimos 3 runs de main success; un falso
rojo histórico resuelto afinando el gate.

### 11.4 Rendimiento de CI (separado de defectos funcionales)

Job de calibración 77 min serial (ruta crítica; los otros 16 acaban en ≤10 min); sin
`timeout-minutes` en 16/17; `viewer/tests` repetido 3–4 veces; control negativo de métodos de
escritura O(endpoints) 554 s. Partir el job en 3–4 o usar matrix bajaría el wall-clock a ~30 min,
pero exige actualizar branch protection y los anclajes por nombre de job en `calibra_gate_integrity.py`.

---

## 12. UX y lenguaje de producto

«workspace» aparece **200+ veces** en plantillas; `etiqueta_workspace` resuelve el *valor* pero el
*concepto* sigue llamándose workspace en rótulos. Casos representativos (fichero:línea · texto →
debería):

| Pantalla | Término visto | Debería decir |
|---|---|---|
| `/`, `/status` (`index.html:10`, `status.html:14`) | «Workspace: leyenda», «Neo4j conectado: False», «Proveedor actual: not_configured» | «Juego», «Conexión con la base: correcta/sin conectar»; ocultar Neo4j |
| `/` | «activa el modo de demostración» | enlace a dónde, o retirar (no activable por web) |
| `/admin/partidas` (`partidas.html:21,46,153`) | «Nombre del workspace», «bóveda resoluble», «S9K_VAULT_ROOT», «circularidad» | «Nombre del juego», «Carpeta de biblioteca no conectada → Configuración ▸ Biblioteca» |
| `/admin/health` | viewer/neo4j/ollama/nextcloud_rclone/job_store/external_ai/burst/systemd, «modo sombra», «mock disponible», `{'active_admins': 1}` | nombres funcionales; sin diccionarios Python |
| `/panel/operations` (`operations.html:526,590,668`) | `WORKSPACE_AUTHORITY_DIVERGENT`, `S9K_DEFAULT_WORKSPACE=`, «catalogo-plano-sin-boveda», «secret», `data-ambito="None"`, estados `complete/completed/extracting/needs_metadata` | mensajes humanos; «Privado»; estados en castellano sin duplicar |
| `/panel/operations` error | «El paquete de la fuente no es valido.» | «Falta el perfil del juego junto a la fuente» |
| `/jobs`, `/jobs/{id}` (`jobs.html:13,28,51`) | «jobs_db_not_found», «worker», «CLI de jobs», «docs/15…», payload JSON con rutas absolutas, `ingest_v3`, «intentos 0/3» | «Cola de trabajos no iniciada»; ocultar payload |
| `/v3/review` (`v3_review.html:65,141,149`) | «Selecciona un workspace», `source_id` crudo, `engine_decision` crudo | «Selecciona un juego», nombre de fuente, etiquetas |
| `/review-console*` | «almacén de laboratorio. No se escribe en Neo4j», `plan_id`, chips WOULD_CREATE/LINK_EXISTING/DEFER/CONFLICT | pantalla lab, no debería existir en producto |
| `/admin/audit` | LOGIN_SUCCESS… CONTEXT_LABEL_UPDATED, success/failure/info | castellano |
| `/setup/admin` | «Es Safari…» | «Esta instalación no usa HTTPS» |
| `graph.html:92-93`, `graph.js:16`, `graph-core.js` | `window.S9K_WORKSPACE`, `"leyenda"` literal, «Neo4j» ×2 | sin nombres de variables ni literales de ejemplo |
| `error.html:17`, `_aviso_autoridad_workspace.html:29` | «declaración `S9K_DEFAULT_WORKSPACE` del `.env`» | texto para operador, no para usuario |
| Errores 401/403/404/422 de rutas de navegador | `{"detail": …}` JSON | página con menú y vuelta (solo `/reviews` lo hace) |

Buen ejemplo: `v3_review.html:255-256` «Negada / Afirmativa»; `operations.html:553` «todo el juego».

---

## 13. Documentación

### 13.1 Inventario

285 ficheros en `docs/` (246 `.md`): `docs/` 41 · `docs/v3/` 116 · `docs/archivados/` 57 ·
`docs/coordination/` 49 · `docs/current/` 6 · `docs/experiments/` 7 · `docs/measurements/` 8 (6 `.py`
+ 1 `.js`: **código dentro de docs**) · `docs/releases/` 1 · `docs/futuras mejoras/` 1. Raíz: README
(git 2026-09-29), ROADMAP (2026-08-12), CHANGELOG (última entrada 2026-09-05), 2 `.docx`
(2026-09-28, no parseados). `deploy/README.md` (2026-10-10) y `viewer/README.md` (2026-10-09).
**No existen** `data-engine/README`, `contracts/README`, `shared/README`, `docs/audits/` (creado por
esta auditoría).

### 13.2 Clasificación

| Documento / grupo | Clase | Evidencia |
|---|---|---|
| README.md | CURRENT **desfasado** | l.11 «2026-08-09», l.20 «commit 84f9cc7, PR #256»; real 0cf977c/#266, 233 commits |
| ROADMAP.md | CURRENT **desfasado** | nada posterior a PR #157 |
| CHANGELOG.md | HISTORICAL de facto | 60 PR (#207–#266) sin entrada |
| docs/project-status.yaml | CURRENT parcial | `main_commit: 84f9cc7`, `latest_merged_pr: 256`, `tests.stale: true`, producción `last_verified_at 2026-08-06` |
| docs/releases/BASE_RC_V3_1_ACTA.md | DECISION (acta) | f725bd8 |
| docs/52, 53, 91 | OPERATION | actas y guion RC (91 no ejecutado) |
| docs/54–58, 60–68, 70, 72–88, 90, 92 | DEVELOPER / GENERATED (informes de carril/corte) | con SHA base |
| docs/69 | REFERENCE con prosa SUPERSEDED | «aún no existen» |
| docs/71 | DRAFT/DISEÑO | «NADA DE ESTO ESTÁ INSTALADO» |
| docs/89 | DECISION | esquema de bóvedas |
| docs/v3/00–51 | DEVELOPER/DECISION indexados | v3/README cubre hasta 51 |
| docs/v3/52–65 | DEVELOPER **no indexados** | 14 docs |
| docs/v3/*DOSIER*, *PROMPT MULTIAGENTE (1).md | HISTORICAL/DRAFT | nombre con « (1)» |
| docs/S9_KNOWLEDGE_DOCUMENTACION_CONSOLIDADA.md | REFERENCE legacy | variables inexistentes sin marcar |
| docs/archivados/* (57), docs/coordination/* (49), docs/experiments/* | HISTORICAL (declarado) | — |
| docs/current/* (6) | **HISTORICAL** con banner «era v1/v2 (legacy)»: el nombre `current` contradice su contenido | — |
| docs/futuras mejoras/ | DRAFT / FEATURE FUTURA | sin fecha |
| viewer/README.md | ADMIN GUIDE parcial | l.4 «Desplegado en producción» sin matiz; árbol de estructura obsoleto; rutas Windows personales |
| deploy/README.md | ADMIN/OPERATION | honesto: `RC-E2E PENDING` |

### 13.3 Contradicciones y huecos

1. Los tres documentos de entrada describen agosto–septiembre; el gate de coherencia está **verde**
   con 233 commits de desfase por decisión documentada (PR #218): el estado publicado es
   falso-por-antiguo en verde.
2. **USABLE-V1** solo aparece en 3 ficheros (`docs/76:15`, `docs/v3/25:208,221`,
   `viewer/README.md:38`); **ZERO-TERMINAL no existe en el repositorio**. No hay documento de
   programa (objetivo, alcance, PR-N). UNKNOWN cuántos PR componen la serie.
3. M1 «BLOQUEADO» en README/ROADMAP/yaml/v3-README frente a `docs/90` y código mergeado.
4. `docs/69` «no existen» vs docs/76-80/86; `docs/80` «solo lectura» describe estado anterior.
5. Numeración: huecos 59/62/63/79 en docs/, 13/23/45/50 en v3; `docs/75` lleva título «# 72 —».
6. 3 ficheros de `data-engine/docs/` homónimos de `docs/current/` **difieren** (`cmp` rc≠0): la
   copia de data-engine recibió EXP-1 y la de `docs/current/` no (`EXTERNAL_SOURCES_DESIGN.md:8`
   conserva una IP interna). 30 ficheros documentales siguen con `192.168.1.x` tras EXP-1; «zona
   publicable» no está definida en ningún doc.
7. Variables `S9K_*`: 147 en docs, 209 en código. Solo-en-docs: 11, todas en históricos (pero la
   CONSOLIDADA no las marca). Solo-en-código operativas sin documentar: `S9K_HEALTH_*`,
   `S9K_BACKUP_*`, `S9K_RETENTION_*`, `S9K_ENVIRONMENT`, `S9K_WORKER_ENV`, `S9K_LEGACY_*_DB`,
   `S9K_NEO4J_CA_FILE`, `S9K_SESSION_HTTPONLY`, `S9K_CHUNK_*`, `S9K_REVIEW_CONSOLE_ENABLED`,
   `S9K_V3_REVIEW_DATABASE_PATH`.
8. **Enlaces rotos reales: 0** (281 enlaces relativos en 347 `.md`; 2 falsos positivos dentro de
   bloques de código). Referencia muerta desde la **UI**: `docs/15-jobs-worker-panel.md` (`jobs.html:13`).
9. **No existe guía de usuario ni de administrador**; la administración vive en informes de corte.
   No hay CONTRIBUTING ni carpeta ADR; las decisiones están dispersas (81, 87, 89, 75, acta RC).

### 13.4 Lo que un ajeno puede responder

| Pregunta | Dónde | Estado |
|---|---|---|
| Qué es / qué hace | README l.1-9 | OBS, breve |
| Estado actual | README §Estado, yaml | desfasado 2 meses |
| Instalar | `docs/v3/28`, `deploy/README.md`, `viewer/README.md` | fragmentado, RC PENDING, sin camino fresh |
| Configurar | `.env.example`, `deploy/config/*.env.example` | sin referencia única de variables |
| Usar (jugador/DJ) | **ausente** | — |
| Administrar | docs/69, 76, 86-88, 92, v3/25, v3/60 | informes, no guía |
| Internals | docs/v3/00-12, 60, 64 | sin doc unificado vigente |
| Desarrollar/testear | docs/70, 64, 83, 84, ci.yml | parcial |
| Decisiones | dispersas | parcial |
| Pendiente | ROADMAP (desfasado), yaml `gated_or_pending` | parcial |

### 13.5 Estilo

Idioma mixto en nombres de fichero (archivados 34 EN / coordination 29 EN / v3 24 ES); 66 ficheros
con nombre en un idioma y H1 en otro; 29 docs sin tildes junto a otros acentuados; separadores de
título `—` / `·` / ninguno; `test_docs_numbering.py` solo exige guion y no-duplicados.

### 13.6 Estructura recomendada (NO aplicada)

El árbol actual mezcla informes de carril numerados, históricos y referencia en el mismo nivel.
Propuesta de destino, evaluada sobre lo que ya existe:

| Carpeta | Contenido actual que iría |
|---|---|
| `docs/index.md` | nuevo; sustituye `v3/README` + `archivados/INDEX` como entrada única |
| `install/` | v3/28, deploy/README (Ansible/HTTPS), viewer/README §instalación |
| `admin/` | nuevo; destilar de 69, 75, 76, 86-88, 92, v3/25, v3/60, v3/65, 90 |
| `user/` | nuevo (visor, partidas, fichas); hoy inexistente |
| `operations/` | 52, 53, 91, deploy/README §ensayo RC |
| `architecture/` | README §Arquitectura, v3/00-12, v3/49, v3/51, 69, 68, 89 |
| `development/` | 70, 83, 84, 64 |
| `testing/` | 60, 82, 66, 67, 72, measurements/ |
| `reference/` | project-status.yaml, contracts/ (README nuevo), tabla `S9K_*` (nueva), 68 |
| `decisions/` | 81, 87, 75, 89, releases/ACTA, 54, v3/14, 18, 34 |
| `history/` | archivados/, coordination/, current/ (renombrar), experiments/, CONSOLIDADA, MOTOR_RELACIONES, DOSIER, PROMPT (1) |
| `audits/` | 74, 56-58, v3/00, archivados/09, 24, 29, 30 y este informe |

---

## 14. Sincronización local/remoto

| Trabajo | committed | pushed | rama en origin | en origin/main |
|---|---|---|---|---|
| USABLE-V1 PR-1/2/3 (#263/#264/#266) | sí | sí | sí | **sí** (`b6852ce`, `b4da16a`, `0cf977c`) |
| USABLE-V1 PR-4 (#267) | sí (6 commits) | sí (`e683274`) | sí | **no**: abierto, `MERGEABLE/CLEAN`, 34/34 checks, 0 detrás de main |
| Fixes de teardown de la suite del visor (`worktree-agent-a094729eeeb23213c`, 4 commits 2026-10-08, locked) | sí | **no** | no | no — verificar si #264 los absorbió |
| `feat/6b2-editar-nombres-web` (variante de 6B-2a, 5 commits) | sí | no | no | contenido probable vía #258; 1 commit de reordenación de ruta dudoso |
| `feat/multipartida-m5a-viewer` (4 commits, 2026-08-06) | sí | no | no | no (la variante `-visor` sí) |
| `docs/sync-project-state-2026-08` (30 ficheros) | sí | no | no | no |
| 22 ramas feat/fix/audit con PR MERGED por squash | sí | — | — | **sí** (historia local huérfana, no trabajo perdido) |
| 19 ramas rev-*/revision-*/pr238-rev*/review/*/o4rev*/mut-* | sí | no | no | revisiones de PR ya mergeados; desechables |
| 3 stashes | — | no | no | residuos de agentes (jul–ago 2026) |
| Worktrees `s9k-pr22/pr23/review-fix/safe-writer` (julio) | sí | no | no | revisiones/carril B de julio |
| Seguridad deps (#233 #236 #262 #265) | sí | sí | sí | sí |
| Producción `deploy-v0.3.0-rc5.1` (`47bc314`) | — | — | sí | ancestro, **84 días / ~230 PR por detrás** |

Checkouts secundarios: `/home/ia02/s9-knowledge` (`fix/pr117-…`, su `origin/main` en `d50c931`
de julio: **rancio**); `/home/ia02/s9-knowledge-jobs` (`feat/jobs-worker-panel`, **sin `origin/main`
local**); `/home/ia02/.claude/jobs/2c6f0079/tmp/wtB` (detached `7d014f2`, salvado en tag
`rescate/…`). No sirven para medir nada sin fetch.

**Higiene** (no alterada): 147 worktrees, 435 ramas locales (312 solo locales), 92 ramas remotas ya
mergeadas, 3 stashes. Nada de esto rompe nada, pero convierte cualquier «ausencia» medida desde un
checkout equivocado en una afirmación poco fiable.

---

## 15. Dependencias y mantenimiento

- `viewer/requirements.txt`: 12–13 paquetes con rangos `>=,<`, **sin lock**; incluye `pytest` y
  `httpx` en producción; `jsonschema` declarado con **0 imports** en viewer; `bcrypt` importado y
  **no declarado** (fallback); `python-multipart` implícito correcto.
- `data-engine/requirements.in` → `requirements.lock` (82 pins). **Declarados y no usados**:
  `llama-index-core`, `llama-index-graph-stores-neo4j`, `llama-index-llms-ollama`,
  `llama-index-embeddings-ollama`, `markdownify`, `tenacity` — arrastran `nltk` (CVE con excepción
  `GHSA-8mgp-746c-j5xp` atada al pin 3.10.3), `SQLAlchemy`, `aiohttp`, `tiktoken`, `networkx`,
  `numpy`. **Usados y no declarados**: `pillow` (import a nivel de módulo en `providers/tesseract.py:15`,
  `pipeline/ocr_render.py:30`), `httpx`, **`faster-whisper`** (ni en `.in` ni en lock).
- Dependabot: pip semanal `/data-engine` y `/viewer`, actions semanal. `supply-chain.yml`: pip-audit
  push/PR/cron. Advisories en el árbol: `GHSA-8mgp-746c-j5xp` (única excepción), `PYSEC-2026-1845`,
  `CVE-2026-59881`, `PYSEC-2026-3740`, `CVE-2026-81726`; cerradas vía lock: anyio, soupsieve, pypdf,
  urllib3, multidict, banks.
- Actions: `checkout@v7` ×17, `setup-python@v7` ×16, **`upload-artifact@v4` ×2** (#201),
  **`setup-node@v4` ×2** (#188).

PRs de mantenimiento abiertos (todos BEHIND; sus checks son sobre un main de agosto–septiembre):

| PR | Paquete | Salto | Checks | Observación |
|---|---|---|---|---|
| #209 | neo4j (viewer) `<6.0` → `>=6.3.1,<7.0` | **major** | 2 fail «Reproducibilidad» | desalinearía viewer 6.x con data-engine `neo4j==5.28.4` sobre el mismo Neo4j |
| #202 | uvicorn `>=0.52.4` | no | 32/32 | subir el suelo |
| #201 | upload-artifact 4→7 | major | 34/34 | — |
| #191 | starlette `>=1.6.0` | 0.x→1.x | 30/30 | fastapi ya arrastra 1.x; el pin declarado es el obsoleto |
| #190 | pydantic-settings `>=2.15.0` | no | **CONFLICTING** | rebase o cerrar |
| #188 | setup-node 4→7 | major | 2 fail «Reproducibilidad» | — |
| #156 | python-multipart `>=0.0.32` | no | 4 fail | — |

PRs funcionales abiertos: **#149** superseded por `docs/89` (cerrar); **#146** parcialmente
superseded por `docs/v3/51`, `docs/54`, `docs/58`, con CI roja de hace 65 días. #261 cerrado sin
merge a propósito (mutante conocido). `data-engine` no tiene PRs dependabot: su lock se mantiene a
mano por PRs de seguridad.

---

## 16. Funcionalidades futuras / pospuestas

| Ítem | Tipo | Fuente |
|---|---|---|
| Lote 4 (condicionales), Lote 5 (creación de entidades / `LINK_EXISTING`) | POSPUESTO (decisión de producto) | ROADMAP l.19-20 |
| Encargos D/E/G/H del doc 30 (proveedores con recambio, eje temporal, observabilidad, bucle humano) | FEATURE FUTURA | ROADMAP l.21 |
| Contexto episódico inter-episodio | DISEÑO INCOMPLETO | ROADMAP l.22 |
| Políticas graduadas de negación/temporalidad (flags OFF sin nadie que los encienda) | POSPUESTO gateado | `EngineConfig`; ROADMAP l.23 |
| Despliegue V3 en VM105; M6 housekeeping; M5b en visor productivo | POSPUESTO (operativo) | ROADMAP; yaml blockers; `docs/v3/49:508` |
| Ensayo RC de instalación (`RC-E2E PENDING`, filas N1–N12) | POSPUESTO, nunca ejecutado | deploy/README; docs/91; PR #267 |
| Campo de sesión de revelación en el alta de producto | DISEÑO INCOMPLETO | `docs/90 §9:299-319` |
| Copia off-host (P0), backup automático | DEUDA P0 | ROADMAP §Recuperación; docs/71 |
| External AI Fase B (`transcribe_audio`, `process_image`, `perform_ocr`, `extract_candidates` → `NotImplementedError`) | DISEÑADO | `external_ai/base.py:15,42-53` |
| Burst B2/B3 (proveedores reales, producción); RERANK | DISEÑADO | `external_processing/*`, `nvidia.py:16` |
| Keyframes/escenas/OCR de pantalla en vídeo; páginas escaneadas de PDF → OCR; proveedor DESCRIPTION | DISEÑADO (stubs) | `transcript.py:440-445`, `pdf.py:11,39`, `visual.py:496` |
| `whisper.cpp`, `external` transcriber; `GlossaryStoreSource`; `EmbeddingProvider` | DISEÑADO | `media/transcriber.py:171,185`; `glossary.py:137`; `similarity.py:137` |
| `ingest_code.py`, `import_graphify.py` | ABANDONADO (stubs v1) | — |
| Motor de relaciones v2 (`relations/`, ~18,5 k líneas) | ABANDONADO (no generaliza 0.81→0.24) | `docs/MOTOR_RELACIONES`, experiments/ |
| RC6 / programa coordination | SUPERSEDED por V3 | coordination/README |
| Reducción de revisión humana (acuerdo det∧NVIDIA) | POSPUESTO (circular: exige V3 desplegada) | yaml blockers |
| Puerta 4 recall 0.10 < 0.70 | BUG de calidad (PARCIAL declarado) | docs/v3/42 |
| 7 defectos ACC `xfail(strict)` | BUG abiertos | docs/60 (dice 11) |
| Saturación de `/api/graph` («no se arregla») | DEUDA declarada | docs/73 |
| Deudas en `ingest_cli.py` (altas duplicadas CLI/web) | DEUDA | docs/92, docs/86 |

---

## 17. Multimodal

Dependencias efectivas en el repo: `pypdf` y Pillow (esta última solo transitiva); **faster-whisper
no declarado**; Tesseract/ffmpeg binarios externos. Binarios reales versionados: **dos**, sintéticos
(`benchmarks/datasets/multimodal/sources/bruma-native.pdf` 983 B y `bruma-scan.png`); ningún
wav/mp3/mp4/jpg.

| Tipo | Diseñado | Código | Provider | Test | Archivo real E2E | Provenance conservada hasta UI | UI | Docs | Estado |
|---|---|---|---|---|---|---|---|---|---|
| Texto plano | v3/02 | `adapters/text.py` | local | unit + bruma.txt | doc 53 (nota real) | `start/end` por episodio → grafo → posición en UI | ✅ | ✅ | **E2E** |
| Markdown | v3/02 | `adapters/markdown.py` | local | unit | doc 53 | ídem; `heading_path` se pierde | ✅ | ✅ | **E2E** |
| PDF digital | v3/02 | `adapters/pdf.py` pypdf por página | pypdf | sintético 1 pág. | **ninguno de usuario** | `page`, `start/end`; `bbox=None` | página | ✅ | TESTED |
| Libro largo | no | sin streaming ni troceo; `maxLength` 200 000/episodio → un párrafo de 250 000 chars **rechaza el documento entero** (verificado) | — | no | no | — | — | no | **no diseñado** |
| PDF escaneado | promesa en `pdf.py:4-15` | página sin texto → episodio IMAGE «pendiente»; **nadie consume `NO_NATIVE_TEXT`** | ninguno | sintético | no | 0 fragmentos | — | sí | **DISEÑADO (hueco)** |
| Imagen OCR | v3/26, 39, 28 | `providers/tesseract.py` tsv con bbox por línea | binario externo | 8 tests **skipped aquí y en CI**; fake en `ocr_lane` | doc 26: PNG **sintético** en Windows; doc 28 «verificado en VM105» sin acta | OCR_TEXT con bbox → **el writer descarta `bbox`** (`provenance.py:146-178`) | no bbox | sí | E2E solo fixture sintética |
| Manuscrito/HTR | v3/29, 31 | `multimodal/transcription.py` cascada 2 VLM | NVIDIA **no cableado** en registry ni `ingest_cli` | mocks | **no** (doc 31:149-156) | `start/end` del texto; envía imagen completa aunque haya región | — | sí | TESTED (mock) |
| Imagen descripción / dibujo / diagrama / mapa | v3/02 | adaptadores stub; sin proveedor DESCRIPTION | ninguno | fakes | no | se perderían en grafo | — | sí | DISEÑADO |
| Tabla | v3/02 | `adapters/table.py` CSV | stdlib | sintético | no | `episode.table` sí; fragmento sin fila/col; **`table` se pierde en el grafo** | — | sí | TESTED |
| Audio/ASR | v3/02; archivados 13/24/40 | `adapters/transcript.py` **envuelve** un payload ya transcrito; `S9K_MEDIA_TRANSCRIBER=stub` por defecto | faster-whisper lazy, no declarado | sintético | solo legado v1/v2 (doc 40, VM105, sin V3) | `time_start/end`, `speaker` → grafo conserva tiempos, **pierde speaker**; UI lee tiempos **y no los muestra** | no | sí | TESTED (envoltorio) |
| Vídeo | v3/02 | ídem; `frame_id` nunca se rellena | ffmpeg | sintético | no | tiempos sí; frame no | no | sí | TESTED (envoltorio) |
| YouTube | v3/02 | `fetch_youtube.py` devuelve **texto plano** (VTT→texto) | yt-dlp | sintético | no en V3 | **sin timecodes** (`NO_TIMECODES` declarado) | no | sí | TESTED (pérdida declarada) |
| Documentos mixtos | no | imágenes de PDF **ignoradas en silencio** (`pdf.py:86-88`); TIFF multipágina = frame 0; docx/html `UNSUPPORTED_SOURCE_KIND` | — | no | no | — | — | no | no implementado |
| Embeddings | dosier; v3/07 | `EmbeddingProvider` ABC sin implementación | ninguno | ablación «sin embeddings» | no | — | — | sí | DISEÑADO |

Reglas «ASR sin timecodes / OCR sin bbox se rechaza» viven **solo en el validador Python**
(`validator.py:468-471`), no en el JSON Schema. Imagen/SVG/escaneo «tienen éxito» con 0 fragmentos
(`pending_provider_episodes`): no siempre fail-closed. `extraction/visual.py:1-22` declara que no
produce claims visuales aunque hubiera proveedor. `audio_utils.py:66-81` inventa hablantes por
pausas >2 s, contradiciendo `transcript.py:22-27`.

**Conclusión**: el único soporte multimodal **funcional E2E** es texto/markdown. El README
(«documentos, audios, webs, vídeos de YouTube») describe la ambición v1/v2 y los adaptadores, no lo
que el producto V3 ingiere hoy.

---

## 18. Hallazgos priorizados

Escala: **RANGO 1** seguridad, pérdida/corrupción de datos, falsa confirmación crítica, aislamiento
roto o imposibilidad de completar una función básica · **RANGO 2** bloquea USABLE-V1 o invalida un
gate · **RANGO 3** deuda real, defecto UX/doc/mantenimiento · **RANGO 4** mejora.

### RANGO 1

**H-01 · Camino de instalación en máquina limpia indefinido** · Área: deploy ·
Evidencia: `deploy.sh:206` (`case` sin `MODE`), `detect_state._usable` (`users>0`), Ansible sin
creador de `current`/`.env` (`roles/viewer` `when: _current_stat.stat.exists`), `s9k_release_id` sin
uso · Reproducción: `detect_state.py --mode fresh → PROCEED rc=0` y a continuación el paso 4 de
`deploy.sh` muere por `EMPTY_STATE` · Impacto: la única instalación posible es un upgrade sobre un
host ya poblado; una máquina nueva exige pasos manuales no documentados · Autoridad: `deploy.sh`,
roles Ansible · Estado: BROKEN · Recomendación: definir y calibrar FIRST_RELEASE_PATH (Ansible crea
la primera release o `deploy.sh --mode fresh` tolera `EMPTY_STATE` y cede el alta a `/setup/admin`) ·
Dependencias: ninguna · Bloquea USABLE-V1: **sí** · Documentado: **NO** (contradice «instalación
cerrada de fábrica»).

**H-02 · El worker de jobs no es operable desatendido** · Área: data-engine/jobs, deploy ·
Evidencia: sin unidad systemd (`deploy/README.md:369` «NADIE»), `run-jobs-worker.sh:14,57` layout
legacy y sin `--release-stale-seconds`, `heartbeat()` sin llamadores, `next_retry_at` sin consulta,
cancelación no cooperativa (`job_store.py:513-521,568`) · Reproducción: `timeout 10 worker.py --loop
--sleep-seconds 1 → rc=0 inmediato, 0 jobs` (`worker.py:213-218,239`) · Impacto: toda ingesta pedida
desde la web queda `pending` indefinidamente; un job que mate al proceso puede bucle infinito si se
activa el stale-release · Autoridad: `jobs.db` · Estado: BROKEN · Recomendación: corregir `--loop`,
unidad systemd + venv del motor en deploy, heartbeat y backoff, tests de crash→stale→re-claim ·
Bloquea USABLE-V1: **sí** · Documentado: parcial (ausencia de unidad sí; `--loop` roto **NO**).

**H-03 · Aislamiento por workspace roto en la revisión V3** · Área: autorización · Evidencia y
reproducción: §9 (SEC-02), `services/v3_review.py:785-793`, `routers/v3_review.py:272` · Impacto: un
revisor decide sobre material de una bóveda a la que no tiene acceso, y esa decisión alimenta
`apply` · Autoridad: `ReviewService.record/undo_last/queue/workspaces` · Estado: BROKEN ·
Recomendación: mapear etiqueta de corpus ↔ workspace del visor y exigir `allows_workspace` en
`_scoped` para rutas HTTP; test negativo con dos workspaces y dos reviewers; añadir a `risk-register` ·
Bloquea USABLE-V1: sí (garantía de aislamiento) · Documentado: parcial (`partida_only` como barrera
anti lore anónimo, no como renuncia al aislamiento entre revisores).

**H-04 · Estado de revisión fuera de las variables críticas: pérdida en redeploy** · Área: deploy,
persistencia · Evidencia: `S9K_V3_REVIEW_DATABASE_PATH`/`PROPOSALS_DIR` por defecto en
`viewer/output/reviews-v3` (dentro de la release); no están en `CRITICAL_ENV_VARS` de `deploy.sh`
(sí `S9K_AUTH_DB_PATH`/`S9K_JOBS_DB`) · Impacto: con los defaults de plantilla, el siguiente
`deploy.sh` activa otra `releases/<id>` y las decisiones humanas, planes sellados y propuestas dejan de
ser visibles (el motor devuelve `{}` en silencio si no encuentra la BD, H-18) · Estado: DEBT con
pérdida de datos condicionada · Recomendación: añadir ambas a `CRITICAL_ENV_VARS` y mover el default
fuera del árbol · Bloquea USABLE-V1: sí · Documentado: advertido en prosa del README; **ningún gate**.

### RANGO 2

**H-05 · Redirecciones absolutas gobernadas por `Host`** (SEC-01) · DEMOSTRADO · Recomendación:
`Location` relativo o `TrustedHostMiddleware` + documentar `proxy_set_header Host` · Documentado: NO.

**H-06 · `auth.db` 0644** (SEC-03) · DEMOSTRADO · Recomendación: `UMask=0077` en la unidad +
`chmod 0600` tras crear, con test · Documentado: NO.

**H-07 · Ingesta de partida imposible desde la web** · `chassis_operations.py:1176` manda
`partida_id`; sin campo de sesión de revelación; `run_ingest` lanza `PLAN_SESION_NO_DECLARADA` →
error permanente (`ingest_v3.py:155-159,573`) · Fail-closed correcto, pero M1 jerárquico solo sirve
para capa juego · Documentado: **sí** (`docs/90 §9`, test `test_panel_operations_alta_fuente.py:1052`)
→ KNOWN DEBT / CONFIRMED.

**H-08 · Dos unidades systemd divergentes del visor** · `roles/systemd/templates/*.j2` (www-data)
vs `viewer/systemd/*.service` (root); `deploy.sh` sobrescribe la de Ansible · Impacto: propietario de
`auth.db-wal`/`.csrf_secret` cambia al alternar → `AUTH_STORE_UNAVAILABLE` · Documentado: NO.

**H-09 · Cero superficie web de configuración y formulario de partidas roto** · §7, §8.4–8.5 ·
`/admin/partidas/grant` → 422 desde su propio formulario (DEMOSTRADO); paneles apagados sin UI ni
pista; «modo de demostración» no activable; `SOURCE_PACKAGE_INVALID` sin decir qué falta · Bloquea
USABLE-V1: sí · Documentado: parcialmente (slice 2 reconoce EXISTE≠USABLE).

**H-10 · Evidencia inalcanzable por web** · `/panel/resultado/*` sin ningún enlace de entrada;
flag apagado por defecto («techo declarado» en `.env.example`); `/jobs/{id}` sin enlace a la
ingesta · Documentado: parcial.

**H-11 · Garantías sin vigilancia** · 8 calibradores no exigidos por CI (incl. **P0-AUTH**
`admin_full`), `contracts/knowledge-visibility` (22 tests) fuera de testpaths/CI y rota por orden
de carga junto a knowledge-v3, `check_unicode`/`check-imports` sin negativo (regex incompleta), 18
tests de proveedores que nunca se ejecutan, sin arnés que ablacione las 9 condiciones del gate de
apply una a una · Documentado: NO (salvo visibilidad fuera de CI, ya anotado en memoria del proyecto).

**H-12 · Documentación de entrada desfasada con gate verde** · README/ROADMAP/CHANGELOG vs 233
commits; `latest_merged_pr: 256` vs #266; `latest_ci` sin oráculo; USABLE-V1 sin documento;
ZERO-TERMINAL inexistente; sin guía de usuario/administrador · Documentado: la decisión de que el
desfase sea aviso sí (PR #218); el hueco de guías NO.

**H-13 · La aplicación escribe dentro del árbol del repositorio** · `services/v3_review.py:469-483`
abre `viewer/output/reviews-v3/review.sqlite3` por defecto en import; `run_ingest` exporta siempre
a `default_proposals_dir()` aunque haya `--out-dir`; la suite deja `viewer/state/auth.db` ·
Impacto: un censo/CI/import «de solo lectura» muta el checkout; mediciones contaminadas ·
Documentado: NO.

**H-14 · Apply web: confirmación autorreferente y sin rollback persistido** · `gate.py:51-55`
exige hash «teclado»; `v3_apply.py:~1060` lo lee de la misma fila; el panel no persiste
`rollback.json` ni auditoría del writer (en memoria, `writer.py:169-170`) · Documentado: parcial
(`v3_apply.py:31` «no toca rollback»).

**H-15 · El censo de rutas de CI nunca mide los paneles encendidos** · `ci.yml:1623-1625`; 20
rutas `/panel/*` figuran como huérfanas por construcción; justificación de `gate.py:228-236`
desfasada (3/39 → 6/48) · Documentado: parcial (el MD del censo avisa).

**H-17 · `visibility` del payload de ingesta es un campo muerto** · `chassis_operations.py:1179` lo
deriva; `ingest_v3.py:498` solo lo nombra; `run_ingest` sin parámetro → todo `SECRET` por defecto ·
Seguro pero silencioso · Documentado: NO.

**H-18 · Decisiones humanas ignoradas en silencio** · `review_decisions.py:130-133,219-221`
devuelve `{}` si no encuentra `review.sqlite3` (worker en otra máquina) · Documentado: NO.

**H-19 · `PLAN_APPLY_IN_FLIGHT` eterno tras un crash** · `v3_apply.py:1031-1035`; sin herramienta
de reconciliación · Documentado: NO.

### RANGO 3

**H-16** Procedencia multimodal degradada en el grafo (`bbox`, `speaker`, `table`, `metadata`
descartados; tiempos leídos y no mostrados) y soporte multimodal sobrevendido en README (§17) ·
**H-20** bloqueo de cuenta por tercero (SEC-04) · **H-21** nombres confusables (SEC-05) · **H-22**
producción 84 días detrás, healthcheck `PENDING_VERIFICATION`, backups rancios (KNOWN DEBT) ·
**H-23** higiene Git: 147 worktrees, 435 ramas, 3 stashes, 2 checkouts rancios; 4 ramas con trabajo
genuino sin PR (§14) · **H-24** dependencias: 6 paquetes huérfanos que arrastran la excepción nltk,
`pillow`/`bcrypt`/`faster-whisper` no declarados, `pytest`/`httpx` en producción, #209 major
desalineado · **H-26** suite local rc=1 por 9 ERROR de fixture de navegador que esquiva la guarda
skip · **H-28** `/admin/health` con base URL fija 8088 y chequeo systemd: falsas alarmas; huérfana
en el menú · **H-29** contratos «congelados» con +1 394 líneas sin bump de versión, enums
Python/Schema desincronizados (`MEDIA_TYPES` sin `HTR_TEXT`), instrumento autorreferente,
reader/writer de visibilidad interpretan distinto (`strip().lower()` vs rechazo) · **H-30** lenguaje
interno en UI (§12) y errores JSON en rutas de navegador · **H-31** menú inconsistente, 4 pantallas
de «review», 2 de entidades, formularios con `action` absoluta · **H-33** `providers.env` sin
efecto, 3 familias de variables Ollama, `NvidiaProcessingProvider` sin bandera · **H-34** enlace
muerto `docs/15-jobs-worker-panel.md` desde `/jobs` · **H-35** `S9K_SESSION_SECURE=false` solo
avisa; plantilla culpa a Safari · **H-37** 4 defaults distintos para `jobs.db` · **H-38**
`neo4j-backup.sh` con `chmod 777` y sin `trap`; `.csrf_secret` fuera de todo inventario de backup ·
**H-39** `docs/current/` es legacy; `data-engine/docs` vs `docs/current` divergen; 30 ficheros con
IPs internas tras EXP-1 · **H-40** `docs/60` declara 11 xfail, hay 7; `test_release_checksum`
sensible al entorno.

### RANGO 4

**H-25** job de calibración 77 min serial, sin `timeout-minutes` en 16/17, `viewer/tests` ×3–4 ·
**H-27** ~35 k líneas no productivas (relations ~18,5 k, review v2 ~7,5 k, external_* ~5,6 k, v1
~3,8 k) y **19 `.bak` versionados** · **H-32** PR #149 superseded, #146 stale; 92 ramas remotas
mergeadas · **H-36** anclas `.replace(…,1)`/`index()` en calibradores (orden como contrato) ·
**H-41** idioma/estilo documental mixto · **H-42** `S9K_ENV`, `S9K_LOCAL_BASE_URL`, `S9K_LOG_ROOT`,
`s9k_release_id` obsoletas.

---

## 19. Matriz de garantías

| Propiedad | Diseñada | Implementada | Test | Negativo | Calibrador | CI | Required | E2E | RC | Doc | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Autenticación obligatoria por defecto | ✅ | ✅ | ✅ | ✅ | `mutaciones_instalacion_fabrica` **fuera de CI** | ✅ suite | ✅ | ⚠️ local | ❌ | ✅ | TESTED, CI-GATED |
| Bypass `admin_full`/auth off eliminado | ✅ | ✅ | ✅ | ✅ | `mutaciones_p0_auth` **fuera de CI** | ✅ suite | ✅ | — | ❌ | ✅ | TESTED; calibrador no vigilado |
| CSRF en toda mutación | ✅ | ✅ 21/21 | ✅ | ✅ | «Metodos de escritura» (parcial) | ✅ | ✅ | ⚠️ | ❌ | ✅ | CI-GATED |
| Cookie Secure/HttpOnly/SameSite | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | ⚠️ TLS local (PR-3) | ❌ | ✅ | TESTED |
| Bootstrap primer admin atómico | ✅ | ✅ | ✅ | ✅ concurrencia | ✅ (PR-4 en #267) | ✅ | ✅ | ⚠️ local | ❌ | ✅ | CI-GATED, RC PENDING |
| HTTPS verificada por efecto | ✅ | ✅ | ✅ | ✅ 7 causas | ✅ `mutaciones_pr3` | ✅ | ✅ | ❌ | ❌ | ✅ | CALIBRATED, RC PENDING |
| Instalación en máquina limpia | ⚠️ | ❌ | ❌ | ❌ | ❌ | syntax only | ✅ | ❌ | ❌ | ⚠️ | **BROKEN** |
| Aislamiento por partida (resolutor, writer, visor) | ✅ | ✅ | ✅ | ✅ | ✅ authz | ✅ Neo4j efímero | ✅ | ❌ prod | ❌ | ✅ | CI-GATED |
| Aislamiento por workspace entre revisores | ✅ | ❌ en `/v3/review` | ❌ | ❌ | ❌ | — | — | — | — | ⚠️ | **BROKEN** |
| Autorización por objeto (partida/job/label) | ✅ | ✅ | ✅ | ✅ | p0_auth fuera de CI | ✅ | ✅ | — | ❌ | ✅ | TESTED |
| Fail-closed del apply (9 condiciones) | ✅ | ✅ | ✅ | ⚠️ parcial | ❌ sin ablación una a una | ✅ | ✅ | ✅ CLI | ❌ | ✅ | TESTED |
| No datos mock presentados como reales (PR-2) | ✅ | ✅ | ✅ | ✅ | ✅ `mutaciones_proveedor_no_configurado` | ✅ | ✅ | ✅ local | ❌ | ✅ | CALIBRATED |
| `/review-console` apagada por defecto (PR-1) | ✅ | ✅ | ✅ | ✅ | ✅ `mutaciones_pr1` | ✅ | ✅ | ✅ local | ❌ | ✅ | CALIBRATED |
| Censo de rutas sin escrituras no declaradas | ✅ | ✅ | ✅ | ✅ | ✅ (base por AST) | ✅ | ✅ | ⚠️ paneles apagados | ❌ | ✅ | CI-GATED con techo |
| Contratos congelados v3 | ✅ | ✅ | ✅ | ⚠️ roundtrip+mutación | autorreferente | ✅ | ✅ | — | — | ✅ | TESTED; «congelado» con deriva |
| Contrato de visibilidad | ✅ | ✅ | ✅ 22 | ⚠️ | ❌ | **❌** | ❌ | — | — | ✅ | fuera de CI |
| Reproducibilidad de entorno | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — | — | ✅ | CI-GATED (anclas textuales) |
| Trojan Source / sys.path | ✅ | ✅ | ✅ | **❌** | ❌ | ✅ | ✅ | — | — | ⚠️ | existe, no calibrado |
| Cobertura Neo4j real en CI | ✅ | ✅ | ✅ | ✅ anti-skipped | ✅ AST | ✅ | ✅ | — | — | ✅ | CI-GATED |
| Documentación coherente | ✅ | ✅ | ✅ | ✅ 11 reglas | ✅ | ✅ | ✅ | — | — | ✅ | verde con 233 commits de desfase |
| Worker desatendido | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ | — | ❌ | ❌ | ⚠️ | **BROKEN** |
| Backup off-host / restore SQLite | ✅ diseño | ❌ | ❌ | ❌ | 0/23 | ❌ | — | ⚠️ ago-2026 mismo chasis | ❌ | ✅ | DESIGNED, DEBT P0 |
| Multimodal no-texto | ✅ | ⚠️ stubs | ⚠️ mocks | — | ❌ | ⚠️ skipped | — | ❌ | ❌ | ⚠️ | DESIGNED |

---

## 20. Qué falta para USABLE-V1

Criterio: un administrador normal trabaja desde el navegador tras la instalación técnica sin
terminal, sin editar ficheros, sin IDs internos ni variables `S9K_*`.

1. **H-01** un camino de instalación de fábrica que termine en `/setup/admin` sin pasos no documentados.
2. **H-02** worker operable desatendido (unidad, `--loop` corregido, venv del motor instalado por deploy).
3. **H-03** aislamiento por workspace en `/v3/review` (es una garantía, precede a la ergonomía).
4. **H-04** estado de revisión en ruta persistente y crítica.
5. **H-09** superficie web de configuración por conceptos de producto: biblioteca/almacenamiento,
   proveedor, juego/contexto, partida (formulario `grant` funcional), paneles encendidos de serie o
   gobernados por web; el paquete de fuente (perfil + catálogo) generado desde la web.
6. **H-07** campo de sesión de revelación en el alta de material de partida.
7. **H-10** enlace de entrada a la evidencia desde «aplicado» y desde el job; ruta de vuelta.
8. **H-05/H-06/H-08** Host, permisos de `auth.db`, unidad única del visor.
9. **H-12** documento de programa USABLE-V1/ZERO-TERMINAL y guías de usuario y administrador.
10. **H-30/H-31** lenguaje de producto en rótulos, errores HTML en rutas de navegador, menú estable.

Lo que PR #267 aporta es **medición** del hito FIRST_ADMIN, no instalación: no cierra ningún punto
de esta lista.

## 21. Qué falta para entrega externa

Además de §20: ensayo RC real sobre máquina limpia con nginx/systemd/CA (N1–N12) con acta;
backup off-host y restore de SQLite probados; H-11 (calibradores exigidos por CI, suite de
visibilidad en CI, negativos de Unicode/sys.path); H-13 (la app no escribe en el árbol); H-14
(rollback persistido desde la web); versión y configuración efectiva visibles para el operador;
salud sin falsas alarmas; dependencias saneadas (H-24) y decisión sobre neo4j 6.x; limpieza de
código superseded y `.bak`; documentación reorganizada (§13.6) con README que describa el producto
que existe; decisión explícita y escrita sobre qué multimodal se promete (hoy: solo texto).

## 22. Roadmap derivado

| Bloque | Elemento | Depende de | Razón / evidencia | Criterio de cierre |
|---|---|---|---|---|
| **Bloqueantes USABLE-V1** | FIRST_RELEASE_PATH (H-01) | — | §8.2 | `deploy.sh --mode fresh` o Ansible dejan `current` activo y `/setup/admin` abierto en VM limpia; calibrado |
| | Worker desatendido (H-02) | H-01 | `--loop` rc=0 inmediato | test de `--loop` y crash→stale→re-claim; unidad systemd instalada por deploy |
| | Aislamiento workspace en revisión (H-03) | — | SEC-02 demostrado | test negativo dos reviewers/dos workspaces rojo→verde; `risk-register` |
| | Estado de revisión persistente (H-04) | — | `CRITICAL_ENV_VARS` | gate rojo si falta la variable; default fuera del árbol |
| | Configuración por web (H-09) | H-01 | §7 pasos 4–8, 11 | recorrido admin §7.1 sin terminal/fichero tras instalar |
| | Sesión de revelación en alta (H-07) | — | `docs/90 §9` | ingesta de partida desde el panel llega a Review |
| | Evidencia enlazada (H-10) | — | crawler §7.3 | `/panel/resultado` alcanzable desde «aplicado» y desde el job |
| **Antes de entrega externa** | Host/permisos/unidad (H-05, H-06, H-08) | — | §9 | TrustedHost o Location relativo; `auth.db` 0600 con test; una sola unidad |
| | Ensayo RC real | H-01, H-02 | deploy/README N1–N12 | acta con VM limpia, nginx, systemd, navegador |
| | Calibradores en CI (H-11) | — | 8 no exigidos | cada uno con paso required y guardia anti-cero |
| | App no escribe en el árbol (H-13) | — | §11.2 | import/censo/suite dejan `git status --ignored` sin novedades |
| | Rollback web (H-14) | — | `v3_apply.py:31` | documento de rollback persistido por apply web |
| | Backup off-host + restore SQLite | — | docs/71, `rollback-*.sh` | restore probado desde destino externo |
| **Deuda técnica** | H-17, H-18, H-19, H-28, H-29, H-33, H-37, H-38 | — | §9–§11 | cada uno con test que falle antes del arreglo |
| **Documentación** | H-12, H-34, H-39, H-40, §13.6 | — | §13 | README/ROADMAP/CHANGELOG al día; `docs/index.md`; guías user/admin; doc de programa USABLE-V1 |
| **Mantenimiento** | H-23, H-24, H-32, #190 conflicto, #209 decisión | — | §14–§15 | worktrees/ramas inventariados y decididos por el operador; `.in` sin huérfanos; `pillow`/`faster-whisper` declarados |
| **Multimodal / fase posterior** | H-16, PDF escaneado→OCR, provider DESCRIPTION, ASR real, libro largo | decisión de producto | §17 | un fichero real por tipo con acta y procedencia conservada hasta UI |
| **Mejoras UX** | H-30, H-31, H-35 | H-09 | §12 | glosario de producto aplicado a rótulos; errores HTML |
| **Optimizaciones** | H-25, H-27, H-36 | — | §11.4 | job de calibración <30 min; `.bak` fuera; anclas AST |

## 23. Deuda registrada

Confirmada como ya declarada en el repositorio (KNOWN DEBT / CONFIRMED): ausencia de unidad del
worker; `partida_only` en `/v3/review`; sesión de revelación pendiente (docs/90); saturación de
`/api/graph` (docs/73); 7 ACC `xfail(strict)`; off-host inexistente (docs/71); `s9k_tls_verify`
apaga sin aviso; `.env` por cwd; `next=` sin `urlencode`; healthcheck lee `os.environ`; EXISTE≠USABLE
(slice 2); desfase de `main_commit` como aviso (PR #218); deudas de `ingest_cli.py` (docs/86, 92);
`providers.env` «quién provisiona esto hoy: NADIE»; M6 operativo; VM105 sin releer desde 2026-08-06.

Deuda **nueva** registrada por esta auditoría: H-01, H-02 (`--loop`), H-04 (sin gate), H-05, H-06,
H-08, H-11, H-13, H-14 (hash autorreferente), H-15 (justificación caducada), H-17, H-18, H-19,
H-20, H-21, H-24, H-26, H-28, H-29, H-33, H-37, H-38, H-39.

## 24. Desconocidos / evidencia pendiente

| Ítem | Estado | Cómo cerrarlo |
|---|---|---|
| Estado real de VM105 (servicio, grafo, healthcheck, backups) | PENDING_VERIFICATION desde 2026-08-06 | lectura autorizada por SSH, con acta |
| Comportamiento del nginx de VM105 respecto a `Host` | UNKNOWN | leer el vhost real |
| Aislamiento entre dos bóvedas reales en Neo4j | UNKNOWN (mock solo `leyenda`) | test con Neo4j efímero y dos workspaces con concesiones distintas |
| HTTPS, Secure y permisos de servicio en máquina real | NOT MEASURED | ensayo RC |
| Nextcloud/rclone real para M1 | UNKNOWN | montaje real y acta |
| OCR/HTR/ASR con material real | NOT MEASURED en V3 | fixtures reales + proveedores |
| ¿#264 absorbió los 4 fixes de teardown de `worktree-agent-a094729…`? | UNKNOWN | `git log` comparativo |
| Si existe un job que ejecute el censo con paneles encendidos | UNKNOWN (no hallado) | — |
| `latest_ci` del yaml | NO VERIFICADO (sin oráculo) | ejecutar el gate con `S9K_CI_ORACLE` |
| Contenido de los dos `.docx` | no parseado | — |
| `S9K_SCANNER_STATE_PATH` | UNKNOWN («pendiente de que el escáner exista») | — |

## 25. Veredicto final

| Dimensión | Valoración | Por qué |
|---|---|---|
| ARQUITECTURA | VERIFICADO con DRIFT | chasis, contratos y flujo V3 reales y coherentes; README omite componentes, docs/69 y `KNOWN_JOB_TYPES` desfasados, `providers.env` sin efecto |
| FUNCIONALIDAD | FUNCIONAL CON LIMITACIONES | cuenta, revisión, sellado, apply y procedencia funcionan; worker, instalación fresh y partida desde web rotos |
| INTEGRACIÓN | PARCIAL | E2E completo solo por CLI con Neo4j (doc 53); por web se rompe en worker/Neo4j/evidencia |
| USABILIDAD | PARCIAL | solo usuarios/roles/auditoría y la solicitud de ingesta son usables sin internals; 16 salidas de la web en el recorrido |
| ZERO-TERMINAL | BLOQUEADO | ≥5 intervenciones de terminal/fichero, ~14 conceptos internos, 0 pantallas de configuración |
| INSTALACIÓN | BLOQUEADO | FIRST_RELEASE_PATH indefinido; RC-E2E PENDING; VM apagadas |
| SEGURIDAD | PARCIAL | controles base verificados (CSRF, cookies, Argon2id, bootstrap, redirect `next`, traversal, Cypher); **1 aislamiento roto demostrado**, Host y permisos de `auth.db` |
| INTEGRIDAD DE DATOS | FUNCIONAL CON LIMITACIONES | atomicidad correcta en los almacenes clave; pérdida condicionada en redeploy, `applying` eterno, decisiones ignoradas en silencio, off-host inexistente |
| TESTS | VERIFICADO con techo | 9 919 recolectados, 9 378 passed; rc=1 local por arnés de navegador; 18 tests nunca ejecutados; fuga al árbol |
| CALIBRADORES | FUNCIONAL CON LIMITACIONES | los que corren son serios (AST, base por git, anti-cero); 8 no exigidos, 2 propiedades sin negativo, anclas textuales |
| CI | VERIFICADO | 17/17 required, sin escapes, verde en `0cf977c`; 77 min de calibración serial |
| DOCUMENTACIÓN | PARCIAL | exhaustiva y honesta en informes de carril; entrada desfasada 233 commits; sin guías; USABLE-V1 sin documento |
| OPERABILIDAD | PARCIAL | salud y cola visibles; versión, configuración efectiva, reintento y causa de `pending` invisibles; falsas alarmas |
| MANTENIBILIDAD | PARCIAL | ~35 k líneas no productivas, 19 `.bak`, 147 worktrees, dependencias huérfanas y no declaradas |
| PREPARACIÓN USABLE-V1 | **BLOQUEADO** | §20: 10 condiciones, 4 de rango 1 |
| PREPARACIÓN ENTREGA EXTERNA | **NO IMPLEMENTADO** | §21 |

---

## Anexo A — Rutas montadas (82 + mount), medidas sobre `app.main.app`

```
MOUNT  /static                                           main            static
GET    /api/status                                       api.status      api_user
GET    /api/workspaces | /api/entity-types | /api/search api.entities    api_user; visibility_scope
GET    /api/entity/{entity_id}                           api.entities    api_user
GET    /api/graph                                        api.graph       api_user; visibility_scope   [JS]
GET    /api/jobs | /api/jobs/counts | /api/jobs/{job_id} api.jobs        api_user; visibility_scope
GET    /login                                            routers.auth    —
POST   /login                                            routers.auth    login-CSRF propio            [W]
POST   /logout                                           routers.auth    sesión + CSRF                [W]
GET    /account | /account/change-password               routers.auth    require_authenticated_user
POST   /account/change-password                          routers.auth    + CSRF                       [W]
GET    /setup/admin                                      routers.setup   _guarda (404 si sello/auth off)
POST   /setup/admin                                      routers.setup   + CSRF                       [W cuenta]
GET    /admin/users | /new | /{user_id}                  routers.admin   require_admin                [NAV]
POST   /admin/users/new | /{user_id} | /unlock | /revoke-sessions  routers.admin  require_admin + CSRF [W cuenta]
GET    /admin/audit                                      routers.admin   require_admin
GET    /admin/partidas                                   routers.admin   require_admin                [NAV]
POST   /admin/partidas/grant | /{access_id}/revoke       routers.admin   require_manage_access + CSRF [W cuenta]
POST   /admin/partidas/label | /label-partida            routers.admin   require_edit_context_label + CSRF [W bóveda]
GET    /api/admin/health                                 health_admin    require_api_role(admin)
GET    /admin/health                                     health_admin    require_admin                [huérfana]
POST   /admin/health/snapshot                            health_admin    require_admin + CSRF         [W admin]
GET    /api/entities | /api/entities/{entity_id}         readonly        api_user
GET    /entities | /entities/{entity_id}                 readonly        html_guard                   [NAV]
GET    /api/sources | /api/sources/{source_id}           readonly        reviewer
GET    /sources | /sources/{source_id}                   readonly        reviewer                     [NAV]
GET    /api/quality | /quality                           readonly        reviewer                     [huérfanas]
POST   /partida/select                                   routers.partida require_authenticated_user + CSRF [W cuenta]
GET    /review-console | / | /source/{source_id}         reviews_console reviewer → 404 si S9K_REVIEW_CONSOLE_ENABLED off
POST   /review-console/source/{source_id}/decide         reviews_console + CSRF                       [W lab]
GET    /v3/review/glossary-candidates                    v3_review       reviewer
GET    /v3/review | /v3/review/                          v3_review       reviewer                     [NAV]
POST   /v3/review/decide | /v3/review/undo               v3_review       + CSRF                       [W dominio]
GET    /panel/resultado/{apply_id} | /hecho/{assertion_id} resultado     reviewer; S9K_PANEL_RESULTADO_ENABLED
GET    /panel/review | / | /item/{proposal_id}           chassis_review  reviewer; S9K_PANEL_C_ENABLED [NAV]
GET    /panel/operations | /                             chassis_ops     admin; S9K_PANEL_B_ENABLED   [NAV]
POST   /panel/operations/ingestas | /planes | /aplicaciones | /altas  chassis_ops  admin + CSRF; declaradas [W dominio]
GET    /panel/operations/altas                           chassis_ops     admin
GET    /panel/sources | / | /ficha/{handle}              chassis_sources reviewer; S9K_PANEL_F_ENABLED [NAV]
GET    /panel/entities | / | /item/{entity_id}           chassis_entities viewer; S9K_PANEL_G_ENABLED  [NAV]
GET    /openapi.json | /docs | /redoc                    main            404 salvo S9K_AUTH_EXPOSE_DOCS + admin
GET    / | /graph | /status | /entity/{entity_id} | /jobs | /jobs/{job_id}  main  usuario           [NAV]
GET    /reviews | /reviews/{source_id}                   main            reviewer                     [NAV]
```

Totales: 82 rutas; 24 POST; 0 PUT/DELETE; 6 mutaciones de dominio, 1 de laboratorio, 2 sobre la
bóveda, resto cuenta/admin. Censo oficial sobre este HEAD (`--skip-probe`): definidas 78 / montadas
82; muertas 6 (falsos positivos del AST con `prefix=SLOT.prefix`); huérfanas 48; sin guardián
estático 1; sin auth 0; enlaces rotos 0.

## Anexo B — Variables `S9K_*` en código no-test (161) por clase

**PRODUCT CONFIG (sin superficie web):** S9K_ALLOW_REAL_INGEST, S9K_ALLOW_RELATION_AUTOAPPROVAL,
S9K_ALLOW_GRAPH_MIGRATION, S9K_DEFAULT_WORKSPACE, S9K_WRITER_WORKSPACE, S9K_WORKSPACE (JS),
S9K_VAULT_ROOT, S9K_VAULT_REQUIRE_MOUNT, S9K_INGEST_SOURCES_DIR, S9K_PANEL_B/C/F/G/RESULTADO_ENABLED,
S9K_REVIEW_CONSOLE_ENABLED, S9K_V3_REVIEW_DATABASE_PATH, S9K_V3_REVIEW_DECISIONS_PATH,
S9K_V3_REVIEW_PROPOSALS_DIR, S9K_V3_GLOSSARY_CANDIDATES_DIR, S9K_GLOSSARY_DB, S9K_REVIEW_POLICY,
S9K_REVIEW_EXTRACTOR, S9K_PROCESSING_MODE, S9K_OLLAMA_URL, S9K_OLLAMA_BASE_URL, S9K_OLLAMA_MODEL,
S9K_OLLAMA_VISION_MODEL, S9K_OLLAMA_EMBEDDING_MODEL, S9K_OLLAMA_TIMEOUT(_SECONDS),
S9K_OLLAMA_RETRIES/MAX_RETRIES, S9K_NVIDIA_ENABLED, S9K_NVIDIA_API_KEY, S9K_NVIDIA_BASE_URL,
S9K_NVIDIA_REVIEW_MODELS, S9K_NVIDIA_ADJUDICATOR_MODEL, S9K_NVIDIA_TIMEOUT_SECONDS,
S9K_NVIDIA_MAX_RETRIES, S9K_NVIDIA_MAX_CONCURRENCY, S9K_NVIDIA_CACHE_ENABLED, S9K_EXTERNAL_AI_ENABLED,
S9K_EXTERNAL_AI_ALLOW_PRIVATE_CONTENT, S9K_EXTERNAL_MAX_CONCURRENCY, S9K_EXTERNAL_PROCESSING_ENABLED,
S9K_EXTERNAL_PROCESSING_CACHE_ENABLED, S9K_V3_EXTERNAL_ENABLED, S9K_V3_EXTERNAL_CAPABILITIES,
S9K_V3_EXTERNAL_MIN_UNITS, S9K_V3_EXTERNAL_MAX_CALLS, S9K_V3_EXTERNAL_MAX_COST_UNITS,
S9K_TESSERACT_CMD, S9K_FASTER_WHISPER_MODEL/DEVICE/COMPUTE_TYPE, S9K_MEDIA_* (AUDIO_DIR,
DEFAULT_WORKSPACE, DRY_RUN, JOBSTORE_BRIDGE, LANGUAGE, LOG_DIR, MAX_DURATION_SECONDS, OUTPUT_DIR,
STAGING_DIR, TRANSCRIBER, TRANSCRIPT_DIR, WORKER_LIMIT), S9K_LOCAL_MAX_*, S9K_BURST_MIN_*, S9K_CHUNK_*.

**DEPLOYMENT CONFIG:** S9K_VIEWER_HOST, S9K_VIEWER_PORT, S9K_PUBLIC_BASE_URL, S9K_TLS_CA_FILE,
S9K_SESSION_COOKIE_NAME/TTL_HOURS/IDLE_MINUTES/SECURE/SAMESITE/HTTPONLY, S9K_AUTH_ENABLED,
S9K_AUTH_DB_PATH, S9K_AUTH_MAX_FAILED_ATTEMPTS, S9K_AUTH_LOCK_MINUTES, S9K_AUTH_EXPOSE_DOCS,
S9K_AUTH_TRUST_PROXY_HEADERS, S9K_CSRF_SECRET, S9K_GRAPH_PROVIDER, S9K_GRAPH_LIMIT,
S9K_NEO4J_URI/USER/PASSWORD/PASSWORD_FILE/DATABASE/CA_FILE, S9K_JOBS_DB, S9K_STATE_ROOT, S9K_ROOT,
S9K_CONFIG_ROOT, S9K_REPO_URL, S9K_REPO_ROOT, S9K_ENVIRONMENT, S9K_LEGACY_AUTH_DB, S9K_LEGACY_JOBS_DB,
S9K_WORKER_ENV, S9K_WORKER_LIMIT, S9K_RELEASES_TO_KEEP, S9K_DEPLOY_STATE_FILE, S9K_HEALTH_VIEWER_URL,
S9K_HEALTH_REPORT_PATH, S9K_HEALTH_UNITS, S9K_HEALTH_DISK_PATH, S9K_BACKUP_ROOT, S9K_BACKUP_DIR,
S9K_BACKUP_WARN_AGE_HOURS, S9K_BACKUP_MAX_AGE_HOURS, S9K_BACKUP_MAX_SCAN_DEPTH, S9K_NEO4J_BACKUP_ROOT,
S9K_RESTORE_MAX_AGE_DAYS, S9K_RCLONE_MOUNT, S9K_VIEWER_URL, S9K_VIEWER_DEFAULT_PAGE_SIZE/
MAX_PAGE_SIZE/QUERY_TIMEOUT_SECONDS/MAX_SEARCH_LENGTH.

**INTERNAL/DEBUG/CI/benchmark:** S9K_CI_ORACLE, S9K_LIVE_OLLAMA, S9K_LLM_SEED,
S9K_BENCH_MANIFEST_HMAC_KEY, S9K_BENCH_OLLAMA_ENDPOINT, S9K_BENCH_OLLAMA_MODEL, S9K_BENCH_PROVIDERS,
S9K_ROUTE_PROBE_OUT, S9K_REVIEW_LAB_DIR, S9K_SAMPLE_GRAPH_PATH, S9K_ENSAYO_COMMIT,
S9K_EXPECTED_RELEASE, S9K_RETENTION_APPLY, S9K_CHECKSUM_ALGO/EXCLUDE_DIRS/EXCLUDE_GLOBS,
S9K_NEO4J_RESTORE_SCRIPT, S9K_ROLLBACK_RELEASE_SCRIPT, S9K_VERIFY_DEPLOYMENT_SCRIPT,
S9K_WRITER_NEO4J_REAL; controles negativos de calibración: S9K_PANEL_C_ENABLE, S9K_PANELC_ENABLED,
S9K_PANEL_Z_ENABLED.

**AUTODETECTABLE/DERIVABLE:** S9K_HEALTH_VIEWER_URL, S9K_HEALTH_UNITS, S9K_HEALTH_DISK_PATH,
S9K_PUBLIC_BASE_URL, S9K_AUTH_DB_PATH, S9K_JOBS_DB, S9K_VIEWER_URL.
**OBSOLETE:** S9K_ENV, S9K_LOCAL_BASE_URL, S9K_LOG_ROOT. **UNKNOWN:** S9K_SCANNER_STATE_PATH.

## Anexo C — Mediciones ejecutadas (resumen)

Todas sobre SHA `0cf977c`, árbol limpio (`git status --porcelain` = 0 antes y después; únicos
efectos: rutas gitignoradas `viewer/output/`, `viewer/state/`, `__pycache__`, eliminadas al cierre).

| Medición | rc | Resultado |
|---|---|---|
| `pytest --collect-only -q` | 0 | 9 919 tests, 0 errores de colección |
| `pytest -q -rs` suite completa | 1 | 9 378 passed · 525 skipped · 7 xfailed · 9 errors (fixture navegador) |
| `pytest` contratos knowledge-visibility | 0 | 22 passed (fuera de CI) |
| `pytest` jobs/worker/media | 0 | 34 passed |
| `worker.py --loop` bajo `timeout 10` | 0 | termina al instante |
| `ingest_cli` dry-run sobre nota de ejemplo | 0 | `provider_calls: 0`; 5 claims → 1/2/2; plan de 2 operaciones |
| `check_docs_consistency.py` | 0 | COHERENTE (DESFASADA 233 commits; CI no verificada) |
| `route_map.py --skip-probe` | 3 | 78/82; muertas 6; huérfanas 48; sin auth 0 |
| `detect_state.py --mode fresh` / `upgrade` | 0 / 3 | PROCEED / BLOCK (y `deploy.sh:206` muere igual) |
| Enlaces relativos en 347 `.md` | — | 281 enlaces, 0 rotos reales |
| TestClient: bootstrap concurrente 6 POST | — | `[404,404,303,404,404,404]`, 1 admin |
| TestClient: `Host: evil.example` en `/panel/operations/ingestas` | — | `303 Location: https://evil.example/...` |
| TestClient: reviewer sin concesiones decide en `bench-dev` | — | `303`, 1 decisión registrada |
| TestClient: `umask 022` + bootstrap | — | `auth.db` 0644 |
| TestClient: 5 fallos anónimos contra `admin` | — | admin bloqueado con contraseña correcta |
| uvicorn real: recorrido admin §7.1 y crawler 26 GET / 11 formularios | — | sin 500; 422 en `grant`; persistencia tras kill/rearranque |
| `gh`: run push `0cf977c` | — | CI + supply-chain `success`; calibración 4 616 s |
| `gh`: branch protection | — | 17 contextos required, `strict` |
| `git`: worktrees/ramas/stashes del checkout compartido | — | 147 / 435 / 3; main local 415 detrás |
