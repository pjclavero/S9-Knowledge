# Auditoría global S9-Knowledge

**Fecha:** 2026-10-10 · **Tipo:** auditoría global, independiente y adversarial, de solo lectura ·
**Objeto:** repositorio `pjclavero/S9-Knowledge` en `origin/main` = `0cf977c3f7785e5f826417efc94971825782bd9d`
(PR #266, «PR-3 (USABLE-V1): la instalación provisiona y VERIFICA su vía HTTPS»).

> Esta auditoría **no valida**: busca contradicciones, caminos muertos, garantías falsas y
> funcionalidades que solo parecen existir. Cuando una propiedad no pudo observarse se
> escribe UNKNOWN / NOT MEASURED, nunca PASS. «Ausencia» no es «cero»; «skipped» no es
> «verde»; «diseñado» no es «implementado»; «implementado» no es «usable».

## Historial de revisión

| Ronda | Fecha | HEAD auditado (código) | origin/main | Commit del informe | Alcance |
|---|---|---|---|---|---|
| **RONDA 1** | 2026-10-10 | `0cf977c3f7785e5f826417efc94971825782bd9d` | `0cf977c` | `d2c8f91e0ed273fee9f2dc99ef3d1d89f3a3669f` | Estado real del producto (§1–§25) |
| **RONDA 2** | 2026-10-10 / 11 | `AUDIT_R2_HEAD = 0cf977c3f7785e5f826417efc94971825782bd9d` (main **no se movió**) | `0cf977c` | ver el commit que contiene esta fila | Revalidación de H-01..H-42, soluciones fuera de main, recuperabilidad, arqueología de decisiones, seguimiento del plan USABLE-V1 (sección «Ronda 2» al final) |

> Las secciones §1–§25 son el texto de la **ronda 1** y se conservan tal cual, incluidas sus
> cifras y rangos originales. Donde la ronda 2 corrige algo, la corrección vive en la sección
> «Ronda 2» (R2.3 y R2.13) marcada como **CORRECCIÓN RONDA 2**, nunca borrando el original.

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

**82 rutas + 1 mount** enumeradas sobre `app.main.app` (anexo A). 24 POST [CORRECCIÓN RONDA 2: 21 POST, ver R2.3], 0 PUT/DELETE. De
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

Totales: 82 rutas; 24 POST [CORRECCIÓN RONDA 2: 21 POST]; 0 PUT/DELETE; 6 mutaciones de dominio, 1 de laboratorio, 2 sobre la
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


---
---

# Ronda 2 — Recuperación, arqueología y seguimiento del plan

**Fecha:** 2026-10-10 (inicio 17:50 CEST) – 2026-10-11 · **Tipo:** segunda ronda independiente y
adversarial sobre la ronda 1 · **Pregunta añadida:** «¿qué parte de lo que creemos que falta ya
existe en algún lugar del repositorio pero nunca llegó a main?» y «¿estamos cerrando el camino a
USABLE-V1 o produciendo PRs?».

Reglas respetadas: solo lectura del repositorio; ningún `reset/clean/prune/branch -d/stash
pop|drop|apply/rebase/merge/cherry-pick/force-push`; VM110/VM111 no encendidas; producción no
tocada. La única prueba de aplicación de parches se hizo en un **clon desechable** fuera del
repositorio (`git clone --no-hardlinks` bajo el directorio temporal del trabajo). Método: siete
auditores independientes por área más el coordinador; cinco murieron por límite de sesión en su
primer intento y fueron relanzados reutilizando sus artefactos parciales; sus informes y salidas
crudas están en `/home/ia02/.claude/jobs/b0266fc8/tmp/r2-*/` (fuera del repositorio).

## R2.1 Snapshot auditado

| Dato | Valor |
|---|---|
| **AUDIT_R2_HEAD** | `0cf977c3f7785e5f826417efc94971825782bd9d` (= HEAD de la ronda 1) |
| `origin/main` al inicio y al cierre | `0cf977c` · `git rev-list --count 0cf977c..origin/main` = **0** · `git fetch --dry-run` vacío |
| Rama/worktree de trabajo | `audit/global-2026-10-10` @ `d2c8f91` (= `0cf977c` + el informe R1), árbol limpio al inicio (`porcelain` 0) |
| PR abiertos | 10: #267 (PR-4, `MERGEABLE/CLEAN`, 34/34, 0 detrás de main), #149, #146 y 7 de Dependabot; **sin cambios** desde la ronda 1 |
| Referencia histórica del encargo | `b4da16a` = PR-2 (#264); `d2c8f91` = informe R1; ambos verificados |

## R2.2 Cambios desde la ronda 1

**Ninguno en `main`.** Por tanto no hay hallazgo que haya podido pasar a FIXED_IN_MAIN por el paso
del tiempo; toda variación de estado en R2.3 es **de medición o de clasificación**, no de producto.
Sí cambia el conocimiento: la ronda 2 reproduce con ejecución lo que la ronda 1 dejó en lectura,
mide con protocolo lo que la ronda 1 estimó, y busca en todas las refs lo que la ronda 1 no buscó.

## R2.3 Revalidación de H-01..H-42

Estados: OPEN · FIXED_IN_MAIN · PARTIALLY_FIXED · FIX_EXISTS_NOT_INTEGRATED · RECOVERABLE ·
RECOVERABLE_WITH_ADAPTATION · SUPERSEDED · FALSE_POSITIVE · NOT_REPRODUCED · REGRESSED · UNKNOWN.

| ID | Rango R1 | Estado R1 | ¿Reproducido R2? | Estado R2 | Rango R2 | ¿Fix en main? | ¿Fix fuera de main? | Rama/commit/PR | Recuperable | Recomendación | Bloquea USABLE-V1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| H-01 | 1 | BROKEN | Sí (`detect_state` fresh/empty/usable × modo; `deploy.sh:203-209`) | **OPEN, ampliado** (ver H-43) | **1** | no | **no** (búsquedas `EMPTY_STATE`, `--mode fresh`, `s9k_release_id`, `first release`… en 588 refs: vacío) | — | no | IMPLEMENTAR (definir FIRST_RELEASE_PATH) | sí |
| H-02 | 1 | BROKEN | Sí (`--loop` rc=0 en 0 s; `--loop --limit 0` vive; stale-release sin `attempts`; `next_retry_at` ignorado; cancel no cooperativa) | **OPEN** | **1** | no | **no**: nunca existió unidad/timer de worker en ningún ref (`git log --all -- '*worker*.service'` vacío) | — | no | IMPLEMENTAR (corregir `:213`, unidad, venv del motor, test de `--loop`/stale) | sí |
| H-03 | 1 | BROKEN | Sí (reviewer sin concesión: `decide` 303, `undo` 303; 4 filas en `human_decisions`) | **OPEN**, reencuadrado: renuncia **documentada** (`authz/scope.py:78-82`, `docs/81:34`) sin riesgo registrado ni test | **1** | no | **no**; se halló el **origen**: `f6a4f18` (M5a, 2026-08-06) introduce `_scoped() → partida_only()`; ninguna rama lo revierte | `feat/multipartida-m5a-viewer` → #143 | no (INVALID como solución) | IMPLEMENTAR (exigir `allows_workspace` en rutas HTTP de revisión + negativo con dos reviewers) | sí |
| H-04 | 1 | DEBT condicionada | Sí (simulación redeploy: sin variables el motor ve `{}`, rc=0, sin aviso) | **OPEN** | **2 condicionado** (CORRECCIÓN: «fragilidad potencial no mueve la base»; pérdida diferida, recuperable en la retención de 3 releases; si VM105 declara las variables, no hay pérdida — UNKNOWN sin SSH) | no | **parcial**: existe gate correcto `deploy/scripts/preflight_ensayo_rc.py:175-298` **en main** que exige ambas variables y coherencia visor/worker, pero `deploy.sh` no lo invoca | commits `43b9469`, `c14e4c4`, `e56e43e` | RECOVERABLE (enganchar el preflight existente a `deploy.sh` y añadir a `CRITICAL_ENV_VARS`) | sí |
| H-05 | 2 | DEMOSTRADO | Sí; acotado a 3 `url_for` en `chassis_operations.py:1122,1201,1249` y 8/36 `action=` en 5 plantillas `chassis/*`; el resto del visor usa rutas relativas | OPEN | 2 | no | no | — | no | IMPLEMENTAR | sí |
| H-06 | 2 | DEMOSTRADO | Sí (umask 022: `auth.db`, `auth.bak.v0`, `auth.lock`, `jobs.db`, `review.sqlite3` 0644; umask 027: 0640; solo `.csrf_secret` 0600) | OPEN | 2 | no | no (ningún ref hace `chmod` de `auth.db`; C1 solo *comprueba* permisos) | `ops/v3-release-readiness` (comprobador, no corrector) | parcial (idea del comprobador) | IMPLEMENTAR (`UMask=0077` + `chmod 0600` + test) | sí |
| H-07 | 2 | KNOWN DEBT | lectura | OPEN (deuda declarada) | 2 | no | no (`docs/59` en rama es solo diseño) | `docs/panel-rpg-management-design` | no | IMPLEMENTAR (campo de sesión en el alta) | sí |
| H-08 | 2 | OBS | lectura (impacto no ejecutado) | OPEN | **3** (CORRECCIÓN: solo lectura; el cambio de propietario no se reprodujo) | no | no | — | no | IMPLEMENTAR (una sola unidad) | no |
| H-09 | 2 | DEMOSTRADO (grant 422) | **Parcialmente desmentido** | «Formulario roto»: **FALSE_POSITIVE** (CORRECCIÓN: sin catálogo el `<select name="partida_id">` y el botón «Conceder» están en el mismo `{% else %}` de `partidas.html:182-213`; la UI no ofrece el botón; el POST de la R1 fue sintético y devuelve **400** con plantilla, no 422). «Cero superficie web de configuración»: **OPEN** | 2 | no | no (solo diseño `docs/59`) | `docs/panel-rpg-management-design` @ `101cf6d` | no | IMPLEMENTAR (P8–P10) | sí |
| H-10 | 2 | OBS | lectura (`grep 'panel/resultado' templates` = 0 enlaces); crawler R2 59 URL: 0 entrantes | OPEN | **3** | no | no (`s1-resultado-sin-enlace-muerto` = #250 ya en main) | — | no | IMPLEMENTAR (P13) | sí (ergonomía E2E) |
| H-11 | 2 | OBS | lectura `ci.yml`: 8 calibradores con 0 menciones; `knowledge-visibility` fuera de testpaths | OPEN | 2 | no | no | — | no | IMPLEMENTAR (ver H-48) | sí (gate) |
| H-12 | 2 | OBS | lectura; `check_docs_consistency` verde por decisión (PR #218) | OPEN | **3** (la decisión está documentada; las guías no) | no | `docs/sync-project-state-2026-08` (OBSOLETE, 30 ficheros de agosto) | `bf03ca7` | no | IMPLEMENTAR (P17; ver H-47) | no |
| H-13 | 2 | OBS | **Mitad NOT_REPRODUCED**: con TODAS las `S9K_*` de rutas a tmp y cwd fuera, 0 escrituras en el árbol (`sys.addaudithook`). **OPEN** para los *defaults*: sin variables, el middleware CSRF crea `viewer/state/.csrf_secret` en la **primera petición**, `GET /setup/admin` crea `auth.db`, y `ReviewService()` crea `viewer/output/reviews-v3/review.sqlite3`. La suite deja ficheros por 4 tests concretos (`test_s3_env_gobierna_paneles.py::test_caso_de_fabrica_248…`, `test_chassis_mount_contract.py` ×2, `test_panel_operations_alta_fuente.py::test_la_ingesta_corre_de_verdad…`) | OPEN (reformulado) | **3** | no | no | — | no | IMPLEMENTAR (defaults fuera del árbol; fijar rutas en los 4 tests) | no |
| H-14 | 2 | OBS | lectura dirigida: `gate.py:51-55` vs `v3_apply.py:1098-1102` (decisión consciente que contradice el gate); `sealed_plans` no persiste documento de rollback; `cli_rollback.py:557` lo exige → **rollback de un apply web imposible** con lo persistido | OPEN (confirmado) | 2 | no | no (todas las ramas `*rollback*` ya mergeadas) | — | no | IMPLEMENTAR | sí |
| H-15 | 2 | OBS | lectura: `ci.yml:1618-1628` prohíbe `S9K_PANEL_*` justificado; `gate.py:226-238` 3/39 vs 6/48 | OPEN | **3** (matiz: `/panel/*` se monta siempre, el flag actúa por petición) | no | no | — | no | TERMINAR (actualizar justificación; censo con paneles encendidos) | no |
| H-16 | 3 | OBS | no revalidado | UNKNOWN | 3 | no | no (0 código multimodal fuera de main) | — | no | POSPONER (Fase B) | no |
| H-17 | 2 | OBS | grep: `visibility` una sola vez en `ingest_v3.py:498` (docstring) | OPEN | **3** (seguro por defecto `SECRET`) | no | no | — | no | TERMINAR | no |
| H-18 | 2 | OBS | **DEMOSTRADO**: ruta inexistente → `{}` sin error; fichero ilegible → error | OPEN; encadenado con H-04 (es lo que vuelve invisible la pérdida) | 2 | no | no | — | no | IMPLEMENTAR (fail-closed: ausencia ≠ cero) | sí |
| H-19 | 2 | OBS | **DEMOSTRADO**: tras `claim_for_apply`, segundo claim `claimed=False`; `aplicar()` → `PLAN_APPLY_IN_FLIGHT`; el camino de excepción sí cierra (`record_apply_result(ok=False)`); hueco solo crash/kill | OPEN | 2 | no | no | — | no | IMPLEMENTAR (reconciliación de `applying` huérfanos) | no |
| H-20 | 3 | DEMOSTRADO | Sí | OPEN | 3 | no | no | — | no | IMPLEMENTAR | no |
| H-21 | 3 | DEMOSTRADO | Sí; `admin.py:56` tiene NFKC+casefold **solo para labels**; `cli/auth.py` solo `strip()` | OPEN | 3 | no | no | — | no | IMPLEMENTAR (reutilizar el normalizador existente) | no |
| H-22 | 3 | KNOWN DEBT | n/a | OPEN | 3 | no | n/a | — | — | INVESTIGAR (lectura autorizada de VM105) | no |
| H-23 | 3 | OBS | Sí (147/435/3 confirmados) | OPEN | **4** | no | n/a | — | — | decisión del operador (no limpiar en auditoría) | no |
| H-24 | 3 | OBS | lectura confirmada | OPEN | 3 | no | no | — | no | IMPLEMENTAR (mantenimiento) | no |
| H-25 | 4 | OBS | `timeout-minutes` 1/17 | OPEN | 4 | no | no | — | — | POSPONER | no |
| H-26 | 3 | OBS | **Sí** (9 ERROR, rc=1); causa: `launch()` falla con texto ausente de `_CHROMIUM_NO_DISPONIBLE` (`browser/conftest.py:96-99`) y fixture propia con `sync_playwright`; **el docstring del test lo declara** (l.52-56) | OPEN | **4** (CORRECCIÓN: ya documentado) | no | no | — | no | TERMINAR | no |
| H-27 | 4 | OBS | 19 `.bak` confirmados | OPEN | 4 | no | n/a | — | — | DESCARTAR (retirar) | no |
| H-28 | 3 | OBS («base URL fija 8088») | **CORRECCIÓN**: no es fija; `runner.py:79` lee `S9K_HEALTH_VIEWER_URL` (default 8088, declarada en `deploy/config/viewer.env.example:82`). Queda: `/admin/health` fuera del menú y falsa alarma en instalaciones no systemd | PARTIALLY (reformulado) | **4** | no | C2 `feat/admin-operations-dashboard` (SUPERSEDED/EXPERIMENT: segunda autoridad de salud) | `5742af9` | no | TERMINAR (enlace en menú) | no |
| H-29 | 3 | OBS | lectura confirmada (`HTR_TEXT` en `multimodal/base.py:46`, `ocr_render.py:36`, no en `MEDIA_TYPES`) | OPEN | 3 | no | no | — | no | IMPLEMENTAR (test de paridad de enums) | no |
| H-30 | 3 | OBS | — | OPEN | 3 | no | no | — | no | IMPLEMENTAR (P14/P17) | no (UX) |
| H-31 | 3 | OBS | **Sí**: vistas sin `auth_user`: `jobs_view` (`main.py:786`), `job_detail_view` (808), `reviews_view` (822), `reviews_detail_view` (893), `entity_view` (756); `base.html:25` oculta con `is defined` | OPEN | 3 | no | no (`feat/review-console-v2-readonly` añadiría una quinta pantalla: NO USAR) | — | no | IMPLEMENTAR (P13/P14) | sí (navegación) |
| H-32 | 4 | OBS | no revalidado | UNKNOWN | 4 | — | — | #149, #146 | — | DESCARTAR (#149 superseded por `docs/89`; #146 parcialmente por 51/54/58) | no |
| H-33 | 3 | OBS | lectura: `providers.env` solo en `roles/systemd/tasks/main.yml:8-20`; nadie lo consume | OPEN | 3 | no | no | — | no | TERMINAR (retirar o cablear) | no |
| H-34 | 3 | OBS | **Sí (git)**: `docs/15` nació en `ebb0df3`, **renombrado** (R100) a `docs/archivados/` en `1553665`; `jobs.html:13` lo cita en `<code>`, no es `<a href>` | OPEN | **4** (CORRECCIÓN: referencia caduca en texto, no enlace muerto; el doc describe el layout legacy de H-02) | no | el destino existe en main | `docs/archivados/15-jobs-worker-panel.md` | RECOVERABLE (trivial) | TERMINAR (retirar la frase o apuntar a `deploy/README.md §worker`) | no |
| H-35 | 3 | OBS | lectura (`security.py:179-181` solo avisa; `setup_admin.html:28` culpa a Safari); **R2 UX**: con `.env.example` literal el setup devuelve 403 por HTTP → ver H-44 | OPEN | 3 | no | no | — | no | IMPLEMENTAR (P4/P11: mensaje y preflight) | sí (vía H-44) |
| H-36 | 4 | OBS | lectura: 10 calibradores con `.replace(…,1)` | OPEN; se solapa con H-11 | 4 | no | no | — | no | POSPONER (migrar a `localizadores`) | no |
| H-37 | 3 | OBS | lectura: `run-jobs-worker.sh:17`, `job_store.py:34`, `deploy.sh:42` (legacy), `deploy.sh:44` + `viewer.env.example:30`; `viewer/app/config.py:113` delega | OPEN | 3 | no | no | — | no | IMPLEMENTAR (una autoridad en `job_store.resolve`) | no |
| H-38 | 3 | OBS | lectura (`neo4j-backup.sh:99 chmod 777`; sin `trap`) | OPEN | 3 | no | no | — | no | IMPLEMENTAR | no |
| H-39 | 3 | OBS | 30 ficheros con IPs confirmados; `docs/current` vs `data-engine/docs` divergen | OPEN | **4** (RK-19 ya declara los históricos) | no | no | — | no | TERMINAR (P17) | no |
| H-40 | 3 | OBS | 11 `mark.xfail` en código; «docs/60 declara 11, hay 7 ACC» | OPEN | **4** | no | no | — | no | TERMINAR | no |
| H-41 | 4 | OBS | — | OPEN | 4 | — | — | — | — | POSPONER | no |
| H-42 | 4 | OBS | **CORRECCIÓN**: `S9K_ENV`/`S9K_LOCAL_BASE_URL` 0 usos (obsoletas); `S9K_LOG_ROOT` y `s9k_release_id` son defaults sin consumidor, no obsoletas | OPEN (reformulado) | 4 | no | no | — | no | TERMINAR | no |

Duplicados y encadenamientos detectados en el propio informe (CORRECCIÓN RONDA 2): el inciso
«formularios con `action` absoluta» de H-31 **es** H-05; §11.2 «Fuga al árbol» y H-13 son el mismo
hallazgo; H-04 y H-18 son un hallazgo con dos efectos (pérdida + silencio); H-11 y H-36 se solapan;
H-05 y H-36 **no** son duplicados (H-36 son anclas textuales en calibradores). Correcciones de
conteo: la ronda 1 dice «24 POST» en §4.2 y Anexo A; el recuento real es **21 POST** (82 entradas
método×ruta + 1 mount, 61 GET, 77 paths únicos), coherente con «21 mutaciones» de §9 y con la
enumeración del propio Anexo A. «9 919 tests», «147 worktrees», «435 ramas», «3 stashes»: confirmados.

## R2.4 Soluciones existentes fuera de main

Universo: 588 refs (`git branch -a`) + 106 tags (8 `rescate/*`, ~80 `legacy/*`) + 267 PRs. Para cada
H-XX se buscó con `git log --all ^origin/main -S/-G/--grep` por nombres actuales e históricos,
rutas, símbolos y conceptos. Filtro decisivo: la inmensa mayoría de los ~300 commits «fuera de
main» son **historia pre-squash de PRs ya fusionados** (#238–#266, carriles H–M, 6B-2, S-1/S-3):
historia huérfana, no trabajo perdido.

**Resultado: de 42 hallazgos, ninguno tiene una solución completa olvidada fuera de main.** Lo
hallado es pequeño y adyacente:

| Candidato | Problema | Ref | SHA | Edad | Toca ficheros que main cambió después | Test | Negativo | Autoridad compatible | Clasificación | Acción |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 `deploy/release/*` (spec declarativo + `config_check` de permisos/propietario/estado fuera de la release, manifiesto, smoke) | H-04 parcial, H-06 parcial, H-08 parcial, H-28, H-37 | `ops/v3-release-readiness` (local+origin, sin PR) | `c0d2ee6` (2026-08-09) | 62 días (mb `28320bd`) | sí: `deploy/scripts/lib.sh` (5 commits posteriores en main), `pytest.ini` | 27 + calibrador | sí (ausencia crítica → ERROR; estado dentro de la release → ERROR) | **parcial**: `spec.py` = cuarta lista de variables frente a `CRITICAL_ENV_VARS`, `.env.example` y la autoridad S-3b; no conoce `S9K_V3_REVIEW_*` | **RECOVERABLE_WITH_ADAPTATION** | ADAPTAR solo la idea «comprobador de modo/propietario + estado fuera de la release» derivada de la autoridad única; descartar spec propio, manifiesto v2 y smoke |
| C2 Centro de Estado `/admin/ops` | H-28, H-31, H-09 (observación) | `origin/feat/admin-operations-dashboard` (sin PR) | `5742af9`/`7adad70` (2026-08-08/09) | 64 días | no textual, sí **estructural** (nació antes del chasis #166 y del censo fail-closed #184) | 59 | parcial | **no**: lee `auth.db`/`jobs.db` con `sqlite3` directo (`collector.py:569-588`) = segunda autoridad | PARTIAL / EXPERIMENT | NO USAR tal cual; los 59 tests sirven como especificación de umbrales |
| C3 destino de la referencia `docs/15-jobs-worker-panel.md` | H-34 | **en main** (`docs/archivados/15-…`) | `1553665` | — | — | — | — | sí | RECOVERABLE (trivial) | TERMINAR (ojo: el doc describe el layout legacy roto de H-02) |
| C4 `docs/59-PANEL_RPG_MANAGEMENT_DESIGN.md` (706 líneas, «no hay una sola línea implementada») | H-09, H-07 (vocabulario) | `docs/panel-rpg-management-design` (sin PR) | `101cf6d` (2026-08-08) | 64 días | no | ninguno | — | declara reutilizar el registro de 13 dimensiones | EXPERIMENT (diseño) | LEER como insumo de P8/P9 |
| C5 `feat/multipartida-m5a-viewer` | H-03 | local, sin push; variante de #143 | `f6a4f18` | 66 días | todo | suite adversarial | sí | **es el ORIGEN del defecto** (introduce `partida_only()`) | INVALID / SUPERSEDED | NO USAR |
| C6 `worktree-agent-a094729eeeb23213c` (teardown de la suite) | H-26 colateral | local, locked | `e1f2a08`…`f5096fb` (2026-10-08) | 2 días | sí | sí | — | sí | **SUPERSEDED** (absorbido por #264 `b4da16a`: el docstring y `get_provider.cache_clear()` están en `origin/main:viewer/tests/conftest.py:201-225`; two-dot 28+/833−: main va por delante) | NO USAR; worktree desbloqueable |
| C7 PR #267 `feat/pr4-instalacion-completa-tras-bootstrap` | H-01 parcial (verifica, no instala), H-06 (solo comprueba 0600 del fichero de credenciales del preflight, **no** `auth.db`), H-35 | origin, **OPEN**, 34/34 | `e683274` (6 commits) | 0 detrás | no (6 ficheros) | 28 + calibrador `mutaciones_pr4` (usa `localizadores`, sin `.replace(…,1)`) | sí | sí | **RECOVERABLE (en flujo)** | RECUPERAR vía su propio merge; no resuelve `EMPTY_STATE` ni `--mode fresh` |
| C8 `origin/audit/data-contract-health-v1` (comprobador read-only de coherencia del grafo) | H-18 vecino | sin PR; Carril J cerrado por otra rama (#168) | `b4a3477` | 62 días | `scripts/data_health/` no existe en main | 11 | sí (controles positivos reales por `deepcopy`) | anterior a M5b-C/F-2 | EXPERIMENT / RECOVERABLE_WITH_ADAPTATION | única garantía ausente en main (integridad referencial del grafo); exige adaptación |
| C9 `docs/sync-project-state-2026-08` | H-12 | local, sin push | `bf03ca7` | 61 días | sí (todo) | no | — | — | OBSOLETE | NO USAR |
| C10 `revision-corte5*` | H-02 (falso positivo textual) | local | `8ba12ff`, `4a69c00` | 23 días | todo | — | — | — | SUPERSEDED por #243 | NO USAR |
| C11 tags `rescate/2026-08-13-*` (8) | ninguno | tags | varios | 58 días | — | — | — | — | OBSOLETE (4 con `cherry` 0; 4 corresponden a #163/#170/#164/#172 squasheados) | NO USAR |
| C12 PR #149, PR #146 | H-07 contexto | origin, OPEN | — | 64–65 días | docs | no | — | diseño anterior a M1 jerárquico | EXPERIMENT | NO USAR como solución (cerrar #149; rescatar de #146 solo lo que 51/54/58 no tengan) |

**Tests, calibradores y E2E fuera de main** (694 refs analizadas con `git diff origin/main...<ref>`
sobre rutas de test; 277 con diferencias, casi todas copias ya fusionadas por squash): solo **9
ficheros de test en 6 ramas** no existen en main. Relevantes: `test_preflight_setup_admin.py`
(PR #267, RECOVERABLE en flujo); `test_ops_dashboard.py` (59, SUPERSEDED por `health/`);
`test_review_console_v2.py` (33; su ítem «workspace ajeno» es la **única** cobertura de aislamiento
por workspace en una superficie de revisión hallada en cualquier ref, pero sobre rutas que no
existen y **no** cubre `POST /v3/review/decide`); `test_route_contract_map.py` (SUPERSEDED por el
censo AST, salvo dos reglas: «ruta sin test que la nombre» y «plantilla huérfana»);
`test_data_health_gate.py` (C8); `test_release_readiness.py` (C1); tests `legacy/*` de validadores
de referencia (OBSOLETE). **Garantías buscadas en todas las refs y ausentes en todas**: negativo de
H-03 (`allows_workspace` en tests de `decide`), test de `worker.py --loop`, test de permisos de
`auth.db`, Playwright sobre `/panel/*`. **Hay que escribirlas, no rescatarlas.**

**Multimodal fuera de main**: 131 ficheros históricos con nombres OCR/whisper/media/…; **124 existen
en main**; los 7 ausentes son documentos archivados o renombrados. **0 código, 0 tests y 0 fixtures
multimodales solo fuera de main; 0 ficheros reales de audio/vídeo/imagen en todo el historial** (los
dos binarios son sintéticos). La tabla §17 de la ronda 1 sigue siendo la frontera real.

## R2.5 Candidatos recuperables

Solo tres merecen acción, y ninguno es «ya estaba hecho» según el criterio de la sección 29 del
encargo (problema → implementación → autoridad → test → negativo → comportamiento, aplicado sobre
main y resolviendo):

1. **PR #267** (C7): RECUPERAR por su propio merge. Cierra la **medición** de FIRST_ADMIN con
   calibrador correcto; no cierra H-01 ni H-06.
2. **`preflight_ensayo_rc.py` ya en main** (H-04): RECUPERAR como paso de `deploy.sh` + añadir
   `S9K_V3_REVIEW_*` a `CRITICAL_ENV_VARS` y a `deploy/config/viewer.env.example`. Es la vía más
   barata para cerrar H-04/H-18 y ya tiene tests.
3. **Idea de C1** (comprobador de modo/propietario y «estado fuera de la release = ERROR»):
   ADAPTAR derivándola de la autoridad única; **no** recuperar `spec.py`, manifiesto ni smoke.

**Prueba de recuperabilidad ejecutada (sección 8 del encargo)** sobre C1, el único candidato con
código: clon desechable `--no-hardlinks` a `0cf977c` + `git diff origin/main...ops/v3-release-readiness`:

| Paso | Resultado |
|---|---|
| `git apply --check` | **rc=1**: conflictos en `deploy/scripts/lib.sh:438` y `pytest.ini:3` |
| `git apply --3way` | 9 ficheros nuevos aplicados; `lib.sh` y `pytest.ini` en conflicto |
| Resolución mecánica | descartar el cambio de `lib.sh` (main lo hizo de otra forma en #165), añadir solo el marcador `slow` |
| `pytest deploy/tests/test_release_readiness.py` | **rc=1 · 35 passed, 2 failed**: `test_manifiesto_declara_auth_db_en_v3` (el manifiesto declara esquema v3; main está en v4) y `test_la_smoke_suite_pasa_entera` (`job_store=UNKNOWN` → veredicto UNKNOWN exit 1, correcto por construcción) |
| Clasificación | **PATCH_NEEDS_ADAPTATION** |

No se probaron C2/C8 (NO USAR / adaptación fuerte) ni los rango 1 (sin candidatos). Para H-01, H-02,
H-03, H-05, H-06, H-07, H-09, H-14, H-19 **no existe parche que probar**: requieren diseño o código
nuevo y así se declara.

## R2.6 Trabajo parcial / superseded / inválido

Ver C2, C4, C5, C6, C8–C12 en R2.4. Añadir: 22 ramas locales con PR MERGED por squash (contenido en
main; historia local huérfana); 19 ramas `rev-*`/`revision-*`/`pr238-rev*`/`review/*`/`o4rev*`/
`mut-*` que son puntas de revisores; `feat/6b2-editar-nombres-web` **SUPERSEDED por #258**
(`cbc5411`): su commit «reordena la ruta de label al final» no es necesario en main, donde
`admin.py` ya tiene 13 rutas con `label` en l.733 y `label-partida` en l.843 (orden distinto, sin
ensombrecimiento).

## R2.7 Worktrees, ramas y stashes relevantes (remedidos)

| Métrica | R1 | R2 (verificado) |
|---|---|---|
| Worktrees (`--porcelain`, líneas `worktree `) | 147 | **147** · 20 locked · 54 detached · 0 prunables · 0 con ruta inexistente |
| Ramas locales | 435 | **435** (123 en origin; 312 solo locales) |
| Ramas remotas | 149 | **150** + HEAD; **61** no mergeadas en `origin/main` (≥17 son ramas de PR ya squasheados) |
| Ramas locales con commits en NINGUNA ref remota | 45 | **45** (22 PR MERGED por squash · 19 revisiones/scratch · 4 con trabajo genuino, clasificados en R2.4: C6 SUPERSEDED, 6b2 SUPERSEDED, C5 INVALID, C9 OBSOLETE) |
| Stashes | 3 | **3**, intactos: `5dfb01a` (2026-08-13, «contenido ajeno hallado en el worktree antes de medir», 60 ficheros −8374: volcado de un revisor), `041728b` (2026-08-08, 10 líneas de `v3_review.py` sobre review-console-v2), `343ba3b` (2026-07-15, 26 líneas en `job_store.py` del burst) |
| Commits huérfanos (`fsck --unreachable`) | — | **0** |
| Tags `rescate/*` | 8 | 8, OBSOLETE (R2.4 C11) |

**Worktrees con cambios sin commit (DIRTY_UNCOMMITTED)**, todos sobre bases antiguas (`84f9cc7`,
`5f12693`, `8ee7e27`); ninguno contiene una solución a un H-XX, pero son trabajo que se perdería al
borrar el worktree:

| Worktree | Base | Contenido sin commit | Juicio |
|---|---|---|---|
| `agent-a2d4046668baff4d9` | `84f9cc7` | 11 plantillas/CSS/JS modificados + `system.css`, `_identidad.html`, `contrast_audit.py` | pasada de **diseño visual/contraste** nunca publicada; RECOVERABLE_WITH_ADAPTATION si se quiere (no toca autoridades) |
| `agent-a3bfe8ac730956191` | `84f9cc7` | `ingest_cli.py`, `ingest_report.py`, test y `docs/v3/53` **untracked** + `contracts/base.py` modificado | borrador de lo que ya entró en main por otra vía; SUPERSEDED |
| `agent-a2dd137e36fc0ca0e` | `84f9cc7` | `deploy/propuestas/bkp4-banco/` + `test_bkp4_banco_calibracion.py` | banco BKP-4 no publicado; EXPERIMENT (ligado a docs/71) |
| `agent-a2a30322802b23007` | `5f12693` | `prototipo-carril-f/` | prototipo; EXPERIMENT |
| `agent-a0080616a55e68358` | `5f12693` | 5 `.audit-b-*.tsv` | datos de una auditoría anterior |
| `agent-a19f011d6fbc28b15` | `8ee7e27` | 2 JSON de medición (inventario de configuración, procedencia documental) | datos |
| `agent-a44efb4fa8081312e`, `agent-a9c9c6ff4cb92f31a` | — | `artifacts/carril-h/`, `artifacts/auditoria-zero-terminal/` | artefactos de carriles; UNKNOWN si duplican lo versionado |
| `agent-af4575e3a42f92c07` | — | `data-engine/requirements.in` modificado + `astscan.py` | borrador de mantenimiento de deps (H-24) |
| `perf-viewer-scale-v2` (`perf/viewer-scale-baseline-v2`) | 1 ahead | **índice con borrados staged** de `calibra_gate_integrity.py`, `benchmarks/perf/*`, docs/64 y 67, y copias untracked | estado inconsistente de un carril ya mergeado (#170); DIRTY_UNCOMMITTED peligroso si alguien hace `commit -a` ahí |

Checkouts secundarios (`/home/ia02/s9-knowledge` con `origin/main` en `d50c931` de julio;
`/home/ia02/s9-knowledge-jobs` sin `origin/main`; `s9k-pr22/23/review-fix/safe-writer` con 1–4
commits de julio no publicados): sin cambios respecto a R1; no sirven para medir sin fetch.

## R2.8 PRs cerrados/no mergeados relevantes

De 267 PRs: 10 OPEN, ~24 CLOSED sin merge (resto MERGED). Los cerrados sin merge se agrupan en:
(a) **sustituidos explícitamente** por una versión limpia (#16→#19, #18→#20, #162→reconstruido,
#50/#155/#189 Dependabot superseded), (b) **duplicados de algo ya en main** (#7 de #5, #17 por
`e73ef33`, #97 P0 ya en main), (c) **experimentos DO NOT MERGE con veredicto ejecutado** (#98–#102
PR#95 V1–V4, #261 mutante conocido), (d) **informes caducados** (#4, #8). Ninguno contiene una
solución pendiente a un H-XX; #53 (neo4j 6.x, cerrado 2026-07-26 por incompatibilidad de major con el
servidor) es el precedente directo que **#209 reabre sin nueva decisión** (H-24).

## R2.9 Arqueología de decisiones

| DECISION-ID | Problema | Opciones | Elegida (descartadas) | Motivo entonces | Evidencia | Código | ¿Vigente el motivo? | ¿Cambió el contexto? | ¿Código recuperable? | ¿Reabrir? |
|---|---|---|---|---|---|---|---|---|---|---|
| **D-F2** autoridad de workspace | entorno y perfil discrepaban | A perfil manda/entorno fallback · B modelo plural · C entorno manda | **A** (B: «cabe en el singleton») | una autoridad, divergencia visible fail-closed | #244, 5 rondas | `authz/autoridad_workspace.py:300-447` | sí | no | no | **no**, pero `v3_apply.py:822/1105` siguen leyendo `os.environ` (P6) |
| **D-LORE / D-PARTIDA-ONLY** | ¿auth off ⇒ acceso?; ¿qué compara la revisión V3? | permisivo vs denegado; comparar workspace vs «etiqueta de corpus» | **denegado** + `partida_only()` | «auth desactivada ≠ acceso total»; «`workspace` es etiqueta del corpus» | `docs/81:8-20`, `scope.py:78-82`, `f6a4f18` (M5a, 2026-08-06) | `services/v3_review.py:785-793` | la mitad (lore anónimo) sí; la renuncia al workspace **no está justificada** frente a revisores autenticados con concesiones distintas | sí: F-2 hizo canónico el workspace del perfil | no | **sí** (H-03) |
| **D3** Secure estático | HTTP + Secure → bucle 403 | degradar por `request.scheme` vs estático + HTTPS obligatorio | **estático** | no degradar seguridad | #266 M3, #267 M5 | `auth/config.py:57`; sin lectura de scheme | sí | sí: ahora existe preflight HTTPS | no | no; pero el **mensaje** de la pantalla (Safari) y el `.env.example` deben alinearse (H-44) |
| **D-MOCK** | ausencia caía en mock silencioso | mantener · vacío honesto · DEMO explícito | **vacío honesto + mock solo explícito** | falsa confirmación | #264 | `providers/__init__.py:64-67` | sí en código | **`viewer/.env.example:3` sigue en `mock`** | — | **sí**: alinear plantilla (H-44) |
| **D-RC** review-console | consola v1 montada siempre | conectar al motor · retirar · apagar | **apagada por bandera, no desmontada** («decisión del operador») | — | `docs/v3/25:208-235` | `reviews_console.py` | sí | no | — | no (deuda: E2E de `/v3/review`) |
| **D-PANELES** apagados por defecto | paneles vacíos | encender · apagar | **apagados** («hasta que su carril los termine») | — | `viewer/.env.example:58-61` | `chassis.slot_enabled` | **no**: los carriles terminaron (docs/76-80/86) y siguen apagados | sí | — | **sí** (P9/H-09) |
| **D-MAINCOMMIT** | yaml ponía main en rojo tras cada merge | SHA del propio merge · ancestría + verificación | **ancestría + verificación** | autorreferencia imposible | `project-status.yaml:19-63`, #218, #257 | `check_docs_consistency.py` | sí | 233 commits de desfase con gate verde | — | **sí**: el gate ya no informa (H-12) |
| **D-CONTRATOS** congelados sin bump | nuevos campos | bump · contrato adyacente | **adyacente sin bump** (`knowledge-visibility/v1`, `ManifiestoPartida`) | no romper `v3-internal-v1` | `docs/v3/51 §5`, `v3/59:27-35`, #259 | `partida_manifest_contract.py` | sí | M0 preveía bump; ya hay dos satélites y +1 394 líneas (H-29) | — | revisar |
| **D-M5B** NO APPLY legacy | migración sin `known_by` | aplicar · descartar | **descartado en producción** | sin `known_by` no hay semántica | `docs/54`, memoria | plan `12f7278f` | sí | V3 ya en main | — | sí al desplegar V3 |
| **D-ADMINFULL** | tres puertas de bypass | mantener · una autoridad | **una autoridad + auth=true de fábrica** | repo público | `docs/75 §3-4`, #248 | `install_state`, `csrf_bootstrap.py` | sí | — | — | no |
| **D-SQUASH** desde #238 | historia ruidosa | merge · squash | **squash** (0 merges desde `405e1b3`) | **no escrito en ningún doc** | `git log --merges` | — | de facto | — | — | **documentar** (explica 22 ramas «huérfanas» y el método de `_merged_prs`) |
| **D-CSRF** | arranque abortaba sin secreto | fijar a mano · autogenerar 0600 | **autogenerar salvo explícito** | ZERO-TERMINAL | `csrf_bootstrap.py:1-30`, #248 | sí | sí | **`deploy/config/viewer.env.example:43-48` sigue diciendo «debe definirse en el host»** y `validate_deploy.sh` lo exige → DRIFT | — | **sí**: alinear (H-49) |
| **D-ENVCWD** `.env` por cwd | `.env` en otro directorio | ruta absoluta · cwd | **cwd, sin caché** | mismo fichero que pydantic | `config.py:59-76` | sí | causa 3 failed F-2 (#248) y rompe `mutaciones_p0_auth.py` (#256) | — | **sí**: ruta explícita |

## R2.10 Opciones aparcadas

Censo (`-w`, docs sin `audits/`, código no-test): PLANNED 11/7 · DEFERRED 3/9 · FUTURE 3/0 · DRAFT 1/1
· EXPERIMENTAL 1/0 · «fuera de alcance» 16/2 · «Fase B» 5/1 · PENDIENTE 16/13 · POSTPONED / NOT_NOW /
NOT_FOR_V1 / PHASE_B / «aparcado»: 0 · `NotImplementedError` no-test: 14.

| Ítem | Fuente | ¿Sentido? | ¿Implementada indirectamente? | ¿A medias / rama? | Clase | Veredicto |
|---|---|---|---|---|---|---|
| Fase B multimodal (4 métodos `NotImplementedError`) | `external_ai/base.py:42-53` | sí | OCR Tesseract por otra ruta | stubs | FEATURE FUTURA | seguir aparcada hasta USABLE-V1 |
| Burst B2/B3, RERANK | `external_processing/*` | dudoso | no | stub | EXPERIMENTO | aparcada |
| `ingest_code.py`, `import_graphify.py` | docstrings | no | no | — | TRABAJO ABANDONADO | retirar |
| Motor relaciones v2 (`relations/`, ~18,5 k líneas) | docs/MOTOR_RELACIONES | no (0.81→0.24) | no | — | TRABAJO ABANDONADO | archivar |
| Ensayo RC N1–N12 | `deploy/README.md:157-196`, docs/91, #267 N8–N12 | **bloqueante** | no | guion sí, ejecución no | DEUDA | ejecutar (VM110/111 apagadas: autorización del operador) |
| TOCTOU/D4 en labels 6B-2 | #258/#259 | sí | no | declarada | DEUDA | aceptar documentada |
| `include_decided` en `/v3/review` | #241 | sí | existe, no expuesta | a medias | DISEÑO INCOMPLETO | corte pequeño |
| Autoridad dual CLI/web en altas | #240, docs/92 | sí | no | — | DEUDA | corte |
| `get_default_workspace` en `entities.py` | #254 | sí | no | a medias | BUG latente | corte |
| 500 sin proveedor en pantallas de datos | #264 | sí | no | — | BUG | corte (P3) |
| Sesión de revelación en el alta | `docs/90 §9` | sí | no | — | DISEÑO INCOMPLETO | H-07 |
| Lote 4/5, encargos D–H, contexto episódico | ROADMAP | sí | no | — | FEATURE FUTURA | aparcadas |
| `USO FUTURO` en `auth/identity.py:6` | código | ? | — | — | DISEÑO INCOMPLETO | revisar |
| Reducción de revisión humana | yaml blockers | circular | no | — | EXPERIMENTO | aparcada |
| `docs/50-deploy-state-continuity.md` | `viewer.env.example:41` | — | **no existe** | — | DEUDA documental | corregir (H-53) |
| Centro de Estado `/admin/ops`, diseño `docs/59`, release kit `deploy/release/*`, data-health | ramas sin PR (R2.4) | parcial | sustituidos o nunca integrados | ramas | EXPERIMENTO / SUPERSEDED | leer como insumo; no recuperar tal cual |

## R2.11 Seguimiento del plan USABLE-V1

**El plan P0–P17 no está escrito en ningún artefacto del repositorio.** `USABLE-V1` aparece 45 veces,
todas en código/tests/CI/docs de PR-1..PR-3; `ZERO-TERMINAL` **0 veces**. La única formulación
completa vive fuera del repo (el encargo del operador). Los cuerpos de PR referencian el plan por
partes («PR-3 del programa USABLE-V1 · primer corte del Bloque 2», «USABLE-V1-E2E-REVIEW») con
numeraciones **PR-N / S-N / Corte-N / 6A-6B / F-2** que no se corresponden con P0–P17. La matriz
siguiente es, por tanto, **reconstruida** (PR-1≈P2, PR-2≈P3, PR-3≈P4, PR-4≈P5).

| Hito | Objetivo | Main (PR, SHA) | Fuera de main | Test | Calibrador | CI | E2E | Doc | Estado | Falta / DRIFT |
|---|---|---|---|---|---|---|---|---|---|---|
| P0 nombres humanos | workspace y partida editables por web | #255 `928b893`, #258 `cbc5411`, #259 `4b08a15` | — | sí | 4/4, 10/10, 10/10 | ✅ | no | solo PR | **DONE** | TOCTOU declarada; la identidad de partida sigue siendo la carpeta |
| P1 sanear calibradores | que muerdan y CI los exija | #260 `21f0ef8` | — | sí | 92 mutaciones | ✅ | n/a | PR | **PARTIAL** | 9 calibradores fuera de CI, F-2 e instalación de fábrica incluidos (H-48) |
| P2 retirar /review-console | fuera de instalaciones normales | #263 `b6852ce` | — | sí | 3/3 | ✅ | solo la consola lab | v3/25, 76 | **DONE** | ruta sigue montada (decisión D-RC) |
| P3 sin mock como conocimiento | vacío honesto; mock solo DEMO | #264 `b4da16a` | — | 28 | 7/7 | ✅ | no | viewer/README | **PARTIAL** | `viewer/.env.example:3 = mock` (H-44); DEMO no en API y cubre datos reales (H-45); 500 preexistente |
| P4 HTTPS sin degradar Secure | instalación verifica su vía | #266 `0cf977c` | — | 28 TLS | 8/8 | ✅ | **RC-E2E PENDING** | deploy/README | **DONE código / E2E PENDING** | bash/Ansible sin mutación |
| P5 bootstrap primer admin verificado | admin se crea, entra y persiste | #247 `a58e137`, #248 `bcd9e59` | **#267 OPEN** (+2 416 líneas) | 19 + 28 | #248 **no en CI**; PR-4 10/10 | PR-4 verde | PENDING | docs/75 §4 | **IN_PROGRESS** | con `.env.example` literal el setup es imposible por HTTP (H-44) |
| P6 escritores por autoridad efectiva | sin `os.environ` paralelo | #249, #252, #264 parciales (lado visor) | — | — | — | — | — | — | **NOT_STARTED** | `v3_apply.py:822/1105`, `gate.py:100`, `driver_neo4j.py:73`, `ingest_cli.py:426` leen `os.environ` (H-50) |
| P7 configuración persistente como fuente | environment > .env > persisted > default | — | — | — | — | — | — | — | **NOT_STARTED** | precursor: `effective_env_value` |
| P8 web de configuración efectiva | ver qué está en vigor | — | C2 (`/admin/ops`, EXPERIMENT) | — | — | — | — | — | **NOT_STARTED** | `/api/status` publica provider; 0 rutas `config|settings` |
| P9 control web de paneles | encender/apagar por web | #249 `f762cf6` (por `.env`) | — | sí | sí | ✅ | — | `.env.example` | **NOT_STARTED** (REPLACED por `.env`) | D-PANELES caducada |
| P10 configuración web de providers | — | — | — | — | — | — | — | — | **NOT_STARTED** | — |
| P11 continuidad del primer arranque | estado persistente | #248 parcial (CSRF 0600 junto a `auth.db`) | — | sí | no en CI | — | — | `docs/50` **inexistente** | **PARTIAL** | estado en `viewer/state/` por defecto (H-13) |
| P12 profile por package validado | admin no diseña ontología | — | — | — | — | — | — | — | **NOT_STARTED** | `sources_catalog.py:93-101` carga por ruta de fichero |
| P13 navegación huérfanas | sin callejones | #239 `15092ff`, #250 `9110b67` | — | sí | sí | ✅ | no | PR | **PARTIAL** | `/panel/resultado` sin entrada y apagado; `/admin/health`, `/quality` huérfanas |
| P14 guardas/higiene | — | #242 `a7d3cab`, #254 `5f12693`, #256 `8ee7e27` | — | sí | sí | ✅ | `curl -L` | — | **PARTIAL** | H-05, H-13, H-31 abiertos |
| P15 E2E ZERO-TERMINAL real | recorrido completo sin terminal | guion `deploy/README.md:157` | — | — | — | — | **PENDING** | sí | **NOT_STARTED** | VM110/111 apagadas; 0 ejecuciones |
| P16 cerrar garantías congeladas | — | — | — | — | — | — | — | — | **UNKNOWN** (no definido en ningún texto) | — |
| P17 documentación final | README/guías | #257 (solo yaml) | C9 OBSOLETE | — | — | — | — | — | **NOT_STARTED** | H-12, H-47 |
| Fase B multimodal | — | — | 0 fuera de main | — | — | — | — | v3/02 | **NOT_STARTED (DISEÑADO)** | README promete multimodal |

**Cuenta**: DONE 3 · PARTIAL 6 · IN_PROGRESS 1 · NOT_STARTED 7 · UNKNOWN 1. **E2E real ejecutado: 0/17.**

**PR #238–#267 (30)**: 28 MERGED, #261 CLOSED a propósito, #267 OPEN; todos por squash. **16 PR
tocan hitos** del plan (239, 242, 247, 248, 249, 250, 252, 253, 254, 255, 258, 259, 260, 263, 264,
266; 17 con #267) frente a **13 laterales** (238, 240, 241, 243, 244, 245, 246, 251, 256, 257,
261, 262, 265: Slice 2/veracidad, seguridad de dependencias, EXP-1, estado documental). Cronología:
#238–#246 (19–23 sep) saneamiento de Slice 2 con solo dos sobre hitos; desde #247 (24 sep) el
trabajo gira al camino de instalación. Deuda que cada PR declara: «RC-E2E PENDING» (#266, #267),
«no medido contra infra real» (#239, #244), «3 failed F-2 por cwd» (#248), «500 preexistente» (#264).

## R2.12 Drift respecto al plan

1. **Patrón metodológico**: cada PR cierra «en la capa usable desde el producto» con calibración
   densa (job de CI de ~77 min) y traslada la verificación real a un PENDING que nadie ejecuta. La
   distancia a USABLE-V1 **sí se reduce** desde #247, pero **no se cierra**: 0/17 hitos con E2E.
2. **Bloque de configuración por web (P6–P10, P12) sin diseño escrito ni código**: son los hitos
   que definen ZERO-TERMINAL.
3. **Tres contradicciones documentales abiertas dentro de la propia serie**: `viewer/.env.example`
   en `mock` tras PR-2; `deploy/config/viewer.env.example` exigiendo CSRF a mano tras #248;
   `.env.example:60-61` «paneles vacíos» cuando los carriles terminaron.
4. **Garantías declaradas como «exigidas» que CI no exige**: F-2 (16/16) e instalación de fábrica,
   citadas en cinco PR como calibradas, corren solo en local (H-48).
5. **Numeraciones incoherentes** (PR-N, S-N, Corte-N, 6A/6B, F-2, P-N) sin tabla de correspondencia.

## R2.13 Nuevos hallazgos

| ID | Rango | Título | Área | Evidencia | Reproducción | Impacto | Autoridad afectada | ¿Documentado? | Recomendación | Bloquea USABLE-V1 |
|---|---|---|---|---|---|---|---|---|---|---|
| **H-43** | **2** | `deploy.sh` bloquea también el **upgrade** cuando `jobs.db` está ausente o vacía | deploy | `detect_state._usable(jobs)` exige `jobs>0` (`detect_state.py:50-51`) y `global_state = max(severidad)` (`:109`); `deploy.sh:206` usa `GLOBAL_STATE` e ignora `decision`; contradice el comentario `detect_state.py:83-85` («jobs puede estar legítimamente vacía… EMPTY no bloquea») | `h01_variante_jobs.py`: auth usable + jobs.db ausente → `global=EMPTY_STATE decision=PROCEED` → `deploy.sh:206` DIE; con 1 job → `NEW_STATE`, sigue | un host sano que nunca encoló un job o purgó la cola **no puede actualizarse** | `deploy.sh` (dos autoridades: `decision` vs `global_state`) | NO (ningún test ejecuta el paso 4 de `deploy.sh`) | IMPLEMENTAR: usar `decision` o excluir `jobs` de la severidad global; test del paso 4 | sí (variante de H-01) |
| **H-44** | **2** | Con la plantilla literal `viewer/.env.example` el primer administrador **no puede crearse por HTTP** (403 CSRF por cookie `Secure`), y la misma plantilla arranca en `mock` | instalación / P3-P4-P5 | `.env.example:33 S9K_SESSION_SECURE=true`, `:3 S9K_GRAPH_PROVIDER=mock`; `setup.py:76`; mensaje «Recarga la pagina» sin causa | recorrido (a) uvicorn real: `POST /setup/admin` → **403** HTML; `Set-Cookie: _s9k_setup_csrf=…; Secure` | 0/9 pasos alcanzables desde la plantilla; contradice D-MOCK (#264) y la honestidad de P3 | plantilla `viewer/.env.example` vs `deploy/config/viewer.env.example` (dos plantillas con defaults distintos) | parcial (`deploy/README.md` documenta el bucle 403; la plantilla no) | TERMINAR: alinear plantillas con #264/#248; mensaje de error que nombre la causa (HTTP sin TLS); no degradar Secure (D3) | sí |
| **H-45** | 3 | El banner DEMO cubre **datos reales** y la API no marca `mock` | P3 veracidad | `_aviso_proveedor.html:18-20` pinta DEMO en 50/50 HTML; `/panel/operations` y `/jobs` muestran el job real `pending` bajo «datos de muestra»; `/api/status`, `/api/entities`, `/api/graph` devuelven `"provider":"mock"` sin marca | recorrido (b) | falsa confirmación inversa (lo real parece demo) y API sin señal | `provider_banner` deriva de un solo proveedor pero jobs no son del proveedor | NO | TERMINAR: banner por origen de datos; marca en API | no |
| **H-46** | 3 | `/panel/review` enlazada desde el **menú** devuelve 503 cuando el almacén de propuestas no existe | navegación / P13 | `PROPOSALS_STORE_MISSING` (HTML 503) tras encender el panel C sin que el worker haya creado el almacén; `/v3/review` y `glossary-candidates` igual | recorrido (b) paso 5 | un ítem de menú lleva a error de servidor | — | parcial (#264 cita «503 `/panel/review`») | TERMINAR: estado vacío honesto en vez de 503 | sí (navegación) |
| **H-47** | 3 | El plan USABLE-V1 / ZERO-TERMINAL (P0–P17) **no existe en el repositorio** y las numeraciones de PR no se corresponden | documentación / gobierno | 45 apariciones de `USABLE-V1` todas en código/CI; 0 de `ZERO-TERMINAL`; PR-N vs P-N | grep | imposible seguir el programa desde el repo; H-12 agravado | — | NO | IMPLEMENTAR (P17): `docs/` con P0–P17, mapeo PR↔P, criterio de cierre por hito | sí (gobierno del programa) |
| **H-48** | **2** | Calibradores declarados «exigidos» en cinco PR (**F-2 16/16**, instalación de fábrica #248) **no están en CI** | gates | `f2_autoridad_workspace.py` y `mutaciones_instalacion_fabrica.py` con 0 menciones en `ci.yml`; cuerpos de #260/#263/#264/#265/#266 los citan como exigidos | `comm` repo/ci | falsa confirmación de gate: una regresión en la autoridad de workspace o en la instalación de fábrica no enrojece CI | — | NO | IMPLEMENTAR: pasos required con guardia anti-cero (extiende H-11) | sí (gate) |
| **H-49** | 3 | `deploy/config/viewer.env.example` contradice #248 (CSRF «debe definirse en el host; el código NO soporta fichero») y **no declara** `S9K_V3_REVIEW_*` | deploy / docs | `viewer.env.example:43-48`; `grep S9K_V3_REVIEW viewer.env.example` = 0; `validate_deploy.sh:45-81` exige el secreto explícito | lectura | la plantilla productiva induce H-04 y anula la autogeneración de #248 | plantilla vs código | NO | TERMINAR: alinear plantilla y `validate_deploy.sh` con la autogeneración; añadir las rutas de revisión | sí (vía H-04) |
| **H-50** | **2** | La ruta de **apply web** lee `os.environ` directamente, no la autoridad efectiva (P6): `S9K_ALLOW_REAL_INGEST=1` escrito solo en `.env` **no habilita el apply** | configuración / autoridad | `v3_apply.py:822 entorno = os.environ`, `:1105 env=dict(os.environ)`; `gate.py:100`, `driver_neo4j.py:73`, `cli_rollback.py:633`, `ingest_cli.py:426`; pydantic no exporta a `os.environ`; 20 lecturas directas en `viewer/app`, 167 en `data-engine/app` | lectura dirigida | dos autoridades de configuración; un operador que sigue `.env.example` cree haber habilitado el apply y recibe `APPLY_FAILED` | `effective_env_value` (S-3) vs `os.environ` | NO | IMPLEMENTAR (primer corte de P6) | sí |
| **H-51** | 4 | Worktrees con trabajo **sin commit** sobre bases antiguas, incluido un índice con borrados staged (`perf-viewer-scale-v2`) | higiene | R2.7 | `git -C <wt> status --porcelain` | pérdida silenciosa al limpiar; riesgo de `commit -a` accidental | — | NO | decisión del operador: commitear en rama de rescate o descartar explícitamente | no |
| **H-52** | 4 | `GET /jobs/noexiste` devuelve **200** HTML «job_not_found» | UX | crawler (b) | 200 que debería ser 404 | — | NO | TERMINAR | no |
| **H-53** | 4 | `docs/50-deploy-state-continuity.md` referenciado en `viewer.env.example:41` **no existe** | docs | grep | referencia muerta | — | NO | TERMINAR | no |

## R2.14 Métricas de usabilidad R1 vs R2

Protocolo R2 (reproducible): «instalación técnica terminada» = viewer en uvicorn real con copia
byte a byte de `viewer/.env.example` + directorio de fuentes con un `.md`; objetivo material →
ingesta → revisión → aplicar → conocimiento → evidencia → logout/login → reinicio → persistencia
**solo por HTTP**; cada bloqueo = una intervención tipada. Dos recorridos: (a) plantilla literal;
(b) mínimos cambios de fichero para avanzar al máximo. Sin Neo4j ni worker (son parte de la medición).

| Métrica | Baseline R1 | Valor R2 | Delta | Causa del delta |
|---|---|---|---|---|
| Pasos alcanzables con la plantilla literal (a) | no medido (R1 arrancó con `Secure=false`) | **0/9** (403 CSRF en el setup) | n/a | **CORRECCIÓN**: R1 anotó `Secure` como ⚠️; es bloqueante total (H-44) |
| TERMINAL post-instalación (b) | «≥5» (cota que mezclaba comandos y ediciones) | **2 reinicios + 1 comando inevitable (worker) + 1 reinicio de protocolo** | medición exacta | main no se movió; R1 no separó comandos de ediciones |
| CONFIG_FILE_EDITS (b) | dentro de «≥5» | **6** (4 claves de `.env`: `SESSION_SECURE`, `PANEL_{B,C,F,G}`, `PANEL_RESULTADO`, `INGEST_SOURCES_DIR`; 2 JSON creados: `perfil-operador.json`, `catalogo-workspace.json`) | exacto | — |
| Total terminal + fichero | ≥5 | **8** (9 con el worker) | +3 sobre la cota | CORRECCIÓN cota → valor |
| INTERNAL_IDS exigidos | 5 | **4** (ruta absoluta, nombre de workspace, UUID del job, `apply_id`) + **7 claves `S9K_*`** a conocer | −1 / +7 | R1 contaba CLI y partidas; R2 solo el camino material→evidencia |
| INTERNAL_CONCEPTS distintos en pantalla | «~14» | **41** | +27 | **CORRECCIÓN**: R1 listó ejemplos, no contó (lista completa en el informe del auditor UX R2, §5) |
| DEAD_END | 11 ❌ en §7.1 | **6** (setup-HTTP, `SOURCE_PACKAGE_INVALID`, jobs/worker, review 503, partidas sin bóveda, resultado) | −5 | R1 marcaba ❌ también UNCONFIGURED y MISSING_LINK |
| UNCONFIGURED_STATE sin salida web | no desglosado | **4** (material, bóveda, almacén de propuestas, job_store/ollama/rclone/neo4j) | n/a | nueva |
| MOCK_FALSE_CONFIRMATION | «honesta (sin mock)» | con `mock` de fábrica: DEMO en 50/50 HTML; **0** marca en `/api/status`, `/api/entities`, `/api/graph`; banner **falso** sobre datos reales en `/panel/operations` y `/jobs` → **2** incidencias | n/a | R1 no usó la plantilla literal (H-44, H-45) |
| MISSING_E2E_LINK | 1–2 (H-10) | **3** (`/panel/resultado` sin entrada; fila del job sin enlace a `/jobs/<id>`; `/jobs/<id>` sin vuelta a la ingesta) | +1 | medición |
| Huérfanas 200 HTML | 3 | **3** (`/quality`, `/admin/health`, `/v3/review/glossary-candidates`) | 0 | main no se movió |
| Menús distintos | «inconsistente» | **2** (15 ítems vs 5 ítems en 21 páginas) | 0 | `base.html:21` |
| Enlaces de menú a error | no medido | **1** (`/panel/review` → 503) | n/a | nueva (H-46) |
| Errores de navegador en JSON | «solo `/reviews` HTML» | 404/401 JSON en 9 rutas; `/jobs/noexiste` → **200** HTML | 0 (+1) | H-52 |
| Datos escritos en el árbol de código (plantilla literal) | no medido | 4 ficheros (`viewer/state/auth.db`, `.csrf_secret`, `viewer/output/reviews-v3/review.sqlite3`, `data-engine/state/jobs.db`) | n/a | `S9K_AUTH_DB_PATH=` en blanco en `.env.example:25` → default dentro del repo (H-13 reformulado) |

Hasta dónde se llegó por web en (b): material listado ✅ · ingesta solicitada ✅ (tras 6 ediciones)
· progreso ❌ (`pending` indefinido) · revisión ❌ (503) · aplicar ❌ · conocimiento = datos demo ·
evidencia ❌ · logout/login ✅ · reinicio/persistencia ✅. **Delta de producto = 0** (mismo `0cf977c`).

## R2.15 Recomendaciones de recuperación

| Acción | Objeto | Decisión |
|---|---|---|
| RECUPERAR | PR #267 (vía su propio merge) | sí: cierra la medición de FIRST_ADMIN; no declarar instalación completa |
| RECUPERAR | `preflight_ensayo_rc.py` (ya en main) como paso de `deploy.sh` + `S9K_V3_REVIEW_*` en `CRITICAL_ENV_VARS` y en la plantilla productiva | sí: vía más barata para H-04/H-18/H-49 |
| RECUPERAR (trivial) | destino de la referencia de `jobs.html:13` | sí, o retirar la frase |
| ADAPTAR | idea del comprobador de modo/propietario y «estado fuera de la release = ERROR» (C1), derivada de la autoridad única | sí; no el spec propio, ni manifiesto, ni smoke |
| ADAPTAR | regla «workspace ajeno → 404» de `test_review_console_v2.py` como **negativo** para `/panel/review/item/{id}` y, sobre todo, para `POST /v3/review/decide` | sí (H-03) — pero es test nuevo, no rescate |
| LEER | `docs/59` (C4) y los 59 tests de C2 como especificación | insumo para P8/P9 |
| NO USAR | C2 tal cual, C5, C6, C8 tal cual, C9, C10, C11, `feat/6b2-editar-nombres-web`, `feat/review-console-v2-readonly`, validadores `legacy/*` | crean autoridad paralela o están superseded |
| DECISIÓN DEL OPERADOR | 9 worktrees DIRTY_UNCOMMITTED (R2.7), 3 stashes, 45 ramas solo locales, 61 remotas no mergeadas, #149/#146/#209 | commitear en rama de rescate o descartar explícitamente; nunca desde una auditoría |

## R2.16 Orden de trabajo revisado

Criterios: 1 seguridad/aislamiento · 2 integridad/pérdida · 3 bloqueantes USABLE-V1 · 4 trabajo
existente recuperable · 5 navegación/configuración · 6 garantías · 7 documentación · 8 deuda ·
9 futuras · 10 multimodal.

| # | Pendiente | Decisión | Por qué aquí |
|---|---|---|---|
| 1 | H-03 aislamiento por workspace en `/v3/review*` + negativo con dos reviewers | IMPLEMENTAR | seguridad; la decisión `partida_only` (2026-08-06) precede a F-2 y nunca se revisó |
| 2 | H-05 Host → `Location` relativo o TrustedHost · H-06 `UMask`/`chmod` de `auth.db` | IMPLEMENTAR | seguridad; cortes pequeños y demostrados |
| 3 | H-04/H-18/H-49: enganchar `preflight_ensayo_rc.py` a `deploy.sh`, `CRITICAL_ENV_VARS`, plantilla; motor fail-closed ante BD ausente | RECUPERAR + IMPLEMENTAR | integridad; la mitad ya existe |
| 4 | H-01/H-43: FIRST_RELEASE_PATH y `deploy.sh` que respete `decision` | IMPLEMENTAR (diseño previo) | bloqueante; sin candidato |
| 5 | H-02: `worker.py:213`, unidad systemd, venv del motor, test de `--loop`/stale/retry/cancel | IMPLEMENTAR | bloqueante; nunca existió unidad |
| 6 | PR #267 | RECUPERAR (merge) | medición de FIRST_ADMIN con calibrador correcto |
| 7 | H-44: alinear `viewer/.env.example` (Secure/mock) y mensaje del setup; H-48: F-2 e instalación de fábrica en CI | TERMINAR | plantilla de fábrica honesta; gates que dicen lo que hacen |
| 8 | H-50: `v3_apply.py`/`gate.py` por `effective_env_value` (primer corte P6) | IMPLEMENTAR | autoridad única antes de P7 |
| 9 | H-47 + H-12: documento del plan P0–P17 con mapeo PR↔P y criterio de cierre; README/ROADMAP al día | IMPLEMENTAR (P17 parcial, ahora) | gobierno: sin él no se puede medir el programa |
| 10 | Ensayo RC N1–N12 en VM110/111 (autorización del operador) | TERMINAR | 0/17 hitos con E2E; todo lo demás es «PENDING» |
| 11 | H-09/P8–P10: diseño de configuración por web (biblioteca, proveedor, juego, paneles) sobre `effective_env_value` + fuente persistida (P7) | IMPLEMENTAR (diseño primero; `docs/59` como insumo) | núcleo de ZERO-TERMINAL |
| 12 | H-07 campo de sesión · H-10/H-46/H-31/H-52 navegación · H-14 rollback web · H-19 reconciliación `applying` | IMPLEMENTAR | bloqueantes de recorrido |
| 13 | H-11/H-36 calibradores a CI y a `localizadores`; `knowledge-visibility` en testpaths; negativos Unicode/sys.path | TERMINAR | garantías |
| 14 | H-13 defaults fuera del árbol y 4 tests con rutas fijas; H-37 un default de `jobs.db`; H-17; H-20/H-21; H-29; H-33; H-38 | IMPLEMENTAR | deuda |
| 15 | H-24 deps; #209 decisión de driver; cerrar #149; decidir #146; H-23/H-51 higiene | decisión del operador | mantenimiento |
| 16 | Multimodal (H-16, Fase B) | POSPONER | solo tras P15 |

## R2.17 Techos / desconocidos

| Ítem | Estado | Cómo cerrarlo |
|---|---|---|
| Estado real de VM105 (si declara `S9K_V3_REVIEW_*`, nginx y `Host`, healthcheck, backups) | UNKNOWN (sin SSH por regla de la auditoría) | lectura autorizada con acta; decide el rango definitivo de H-04 |
| Aislamiento entre dos bóvedas reales en Neo4j | UNKNOWN | test con Neo4j efímero y dos workspaces con concesiones distintas |
| HTTPS, Secure, permisos de servicio y unidades en máquina real | NOT MEASURED | ensayo RC (VM110/111 apagadas) |
| Candidatos C2/C8 | no probados en clon | adaptación fuerte; no merece prueba sin decisión |
| H-16 (procedencia multimodal) y H-32 (#149/#146) | no revalidados | — |
| H-08, H-17, H-28 | confirmados por lectura, no por ejecución | — |
| Contenido de los dos `.docx` | no parseado | — |
| Artefactos de worktrees sucios (`artifacts/carril-h/`, `auditoria-zero-terminal/`) | UNKNOWN si duplican lo versionado | `diff` contra `artifacts/` de main |
| Limitación metodológica | cinco auditores de la ronda 2 murieron por límite de sesión y fueron relanzados reutilizando artefactos parciales; sus salidas se conservan en el directorio temporal del trabajo | — |

## R2.18 Veredicto actualizado

| Dimensión | R1 | R2 | Cambio |
|---|---|---|---|
| ARQUITECTURA | VERIFICADO con DRIFT | VERIFICADO con DRIFT | sin cambio; se añade D-PARTIDA-ONLY como decisión no revisada |
| FUNCIONALIDAD | FUNCIONAL CON LIMITACIONES | FUNCIONAL CON LIMITACIONES | H-43 amplía la rotura de `deploy.sh` al upgrade |
| INTEGRACIÓN | PARCIAL | PARCIAL | 0/17 hitos con E2E |
| USABILIDAD | PARCIAL | PARCIAL (medida) | 8–9 intervenciones, 41 conceptos, 6 callejones |
| ZERO-TERMINAL | BLOQUEADO | BLOQUEADO | con la plantilla literal, 0/9 pasos (H-44) |
| INSTALACIÓN | BLOQUEADO | BLOQUEADO | H-01 + H-43; sin candidato fuera de main |
| SEGURIDAD | PARCIAL | PARCIAL | H-03 confinado y con origen fechado; H-05/H-06 acotados |
| INTEGRIDAD DE DATOS | FUNCIONAL CON LIMITACIONES | FUNCIONAL CON LIMITACIONES | H-04 pasa a rango 2 condicionado con gate recuperable |
| TESTS | VERIFICADO con techo | VERIFICADO con techo | H-13 reformulado: fugas atribuidas a 4 tests concretos |
| CALIBRADORES | FUNCIONAL CON LIMITACIONES | FUNCIONAL CON LIMITACIONES | H-48: dos declarados «exigidos» no están en CI |
| CI | VERIFICADO | VERIFICADO | sin cambio |
| DOCUMENTACIÓN | PARCIAL | PARCIAL | H-47: el plan no existe en el repo; tres contradicciones dentro de la serie |
| OPERABILIDAD | PARCIAL | PARCIAL | H-28 corregido (URL configurable) |
| MANTENIBILIDAD | PARCIAL | PARCIAL | inventario Git verificado; 9 worktrees sucios |
| PREPARACIÓN USABLE-V1 | BLOQUEADO | **BLOQUEADO** | nada recuperable cierra un rango 1; lo recuperable es medición y un gate ya en main |
| PREPARACIÓN ENTREGA EXTERNA | NO IMPLEMENTADO | NO IMPLEMENTADO | — |

**Respuesta a la pregunta de la ronda 2.** Lo que creemos que falta **no existe en ningún lugar del
repositorio**: ninguno de los 42 hallazgos tiene solución olvidada; lo recuperable son el PR #267, un
preflight que ya está en main pero `deploy.sh` no ejecuta, y la idea de un comprobador de permisos.
El trabajo reciente va en la dirección correcta desde #247, pero produce PRs de calidad cuya
verificación real queda siempre en PENDING, el plan que debería gobernarlos no está escrito, y los
hitos que definen ZERO-TERMINAL (configuración por web) no han empezado. **No hay que volver a
programar nada que ya exista; sí hay que programar lo que nunca existió: la primera release, el
worker como servicio, el aislamiento por workspace en la revisión y la configuración por web.**
