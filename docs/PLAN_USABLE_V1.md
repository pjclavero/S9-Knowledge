# PLAN_USABLE_V1 — plan canónico del programa USABLE-V1 / ZERO-TERMINAL

**Estado del documento:** CURRENT · **Autoridad:** este fichero es la única fuente del plan del
programa. Si un PR, un commit o un informe contradice a este fichero, manda este fichero y el PR
debe corregirlo o actualizarlo en el mismo cambio. · **Mantenedor:** el organizador del programa
(Fable). · **Base auditada:** `0cf977c3f7785e5f826417efc94971825782bd9d` (auditoría R1+R2 en
`docs/audits/AUDITORIA_GLOBAL_S9_KNOWLEDGE_2026-10-10.md`).

> **Por qué vive aquí y no en `docs/current/`.** La carpeta `docs/current/` contiene seis
> documentos de la era v1/v2 marcados como legacy por su propio banner (auditoría §13.2): ponerlo
> allí lo clasificaría como histórico. El estado vigente del repositorio se publica en la raíz de
> `docs/` (`project-status.yaml`, «fuente de coherencia»); este plan se coloca a su lado. No se
> crea una segunda jerarquía documental; la reorganización de `docs/` es el hito P17.

## 0. Objetivo del programa

Tras la instalación técnica, un administrador normal usa el producto **desde el navegador** sin
terminal, sin editar `.env`/JSON/YAML, sin SQL ni Neo4j Browser, sin IDs internos, sin variables
`S9K_*`, sin conocer Docker, rclone, Neo4j ni la arquitectura. Recorrido completo: instalación →
primer administrador → login → configuración → biblioteca → proveedor → juego → partida →
usuarios/permisos → material → ingestión → progreso → revisión → aprobar/rechazar → sellar/aplicar
→ conocimiento → evidencia → logout/login → reinicio → persistencia. El producto habla en
**biblioteca, juego, partida, proveedor, material, revisión, conocimiento, evidencia**.

## 1. Resumen operativo (se actualiza en cada merge)

| Campo | Valor |
|---|---|
| CURRENT_MAIN | `751995cb5254f985757f726284653c5587890aa7` (squash de #271 B2; #270 = `8d29a00`, #269 = `2dd6d47`, #268 = `8964c36`) |
| CURRENT_PHASE | **B** (cerrar rango 1); Fase A cerrada con #268 |
| CURRENT_HIT | **B3** (H-02 worker desatendido) en PR #273 (revisión independiente pendiente); B1 y B2 cerrados |
| OPEN_R1 | H-02 **VERIFIED (arnés local), RC-E2E PENDING** (#273, sin mergear) · H-01 (+H-43) **VERIFIED (arnés local), RC-E2E PENDING** (#271) · H-03 **VERIFIED** (#269) |
| OPEN_R2_BLOQUEANTES | H-04/H-18 (lado deploy cubierto en #271; el resto, Fase C), H-05, H-06, H-07, H-09, H-11/H-48, H-14, H-19, H-44 (código y arnés local en #271; RC-E2E PENDING), H-50 |
| CURRENT_PR | PR #273 (B3, abierto, base `7841f85`) |
| NEXT_TASK | revisión independiente de #273 (B3); después FASE C |
| BLOCKERS | ninguno técnico; ensayo RC exige autorización del operador para VM110/VM111 |
| DEBT_PARKED | WORKTREE-HYGIENE (147 worktrees, 435 ramas, 3 stashes), DEPENDENCY-MAINTENANCE (7 Dependabot, #209 major), CI-CALIBRATION-PERFORMANCE (job de 77 min serial) |
| E2E_PENDING | P4, P5, B2 completo (RC-E2E PENDING en #266/#267/#271), P15 |
| RC_PENDING | guion N1–N17 de `deploy/README.md` nunca ejecutado (VM110/VM111 apagadas; requiere autorización del operador) |

## 2. Métrica de progreso (no se mide por número de PR)

| Métrica | Baseline (R2, `0cf977c`) | Actual | Delta |
|---|---|---|---|
| Rango 1 abiertos | 3 | **1** (H-02) | −2 (H-03 VERIFIED #269; H-01 VERIFIED en arnés local #271, con RC-E2E PENDING como techo independiente) |
| Rango 2 bloqueantes de USABLE-V1 | 10 | 10 | 0 |
| Terminal post-install (recorrido mínimo) | 2 reinicios + 1 worker (+1 de protocolo) | = | 0 |
| Ediciones manuales de fichero | 6 | = | 0 |
| Conceptos internos en pantalla | 41 | = | 0 |
| IDs internos exigidos | 4 (+7 claves `S9K_*`) | = | 0 |
| Callejones de UI | 6 | = | 0 |
| Estados «no configurado» sin salida web | 4 | = | 0 |
| Hitos con E2E real | 0/17 | = | 0 |
| Hitos DONE | 3/17 (P0, P2, P4-código) | = | 0 |

## 3. Correspondencia de numeraciones

Los PR anteriores usan PR-N, S-N, Corte-N, 6A/6B, F-2. A partir de este plan, cada PR del programa
cita el **ID de hito** de la tabla siguiente y el **H-XX** que cierra.

| Hito | PR previos relacionados |
|---|---|
| P0 | #253 (6A), #255 (6B-1), #258 (6B-2a), #259 (6B-2b) |
| P1 | #260 (microcarril de calibradores) |
| P2 | #263 (PR-1) |
| P3 | #264 (PR-2) |
| P4 | #266 (PR-3) |
| P5 | #247, #248, #267 (PR-4, abierto) |
| P6 | #244 (F-2), #249 (S-3), #252 (S-3b) como precursores del lado visor |
| P13 | #239 (Corte 3), #250 (S-1) |
| P14 | #242, #254, #256 |

## 4. Fases y orden

- **FASE A** — auditoría + plan canónico (este documento; PR de documentación).
- **FASE B** — cerrar rango 1: **B1** H-03 · **B2** H-01/H-43 (familia fresh install) · **B3** H-02 (worker).
- **FASE C** — integridad y seguridad rango 2: H-04/H-18, H-19, H-05, H-06, H-50, H-14, H-17, resto.
- **FASE D** — ZERO-TERMINAL: D1 autoridad única de configuración (P6) · D2 persisted settings
  como fuente (P7) · D3 configuración efectiva (P8) · D4 paneles (P9) · D5 proveedores/servicios
  (P10) · D6 package de juego (P12) · D7 navegación/empty states (P13/P14).
- **FASE E** — E2E real de producto (P15).
- **FASE F** — garantías (P16).
- **FASE G** — documentación (P17).
- **FASE H** — usuario externo (revisión simulada).
- **FASE I** — multimodal (solo después de USABLE-V1).

## 5. Fichas por hito

Estados: NOT_STARTED · IN_PROGRESS · IMPLEMENTED · TESTED · CI_GATED · E2E_PENDING · RC_PENDING ·
VERIFIED · DONE · BLOCKED. **DONE exige el criterio de cierre satisfecho**, incluido el E2E/RC
cuando el criterio lo nombra.

### P0 — Nombres humanos de workspace y partida
- **Hallazgos:** H-30 (parcial). **Autoridad:** `metadata.label` en perfil/manifiesto de la bóveda; `presentacion_etiquetas`. **Dependencias:** —.
- **Estado:** DONE (código) · **PR/SHA:** #255 `928b893`, #258 `cbc5411`, #259 `4b08a15`.
- **Tests:** sí · **Negativo:** sí · **Calibrador:** 4/4, 10/10, 10/10 · **CI:** required · **E2E:** no · **RC:** n/a · **Doc:** solo cuerpos de PR.
- **Techo:** TOCTOU declarada en labels; identidad de partida = carpeta. **Criterio de cierre:** editar nombres por web sin segunda autoridad → cumplido.

### P1 — Sanear calibradores y trinquetes
- **Hallazgos:** H-11, H-36, H-48. **Autoridad:** `ci.yml` + `scripts/calibracion`. **Dependencias:** —.
- **Estado:** IN_PROGRESS · **PR/SHA:** #260 `21f0ef8`.
- **Tests:** sí · **Negativo:** sí · **Calibrador:** 92 mutaciones · **CI:** required · **E2E:** n/a.
- **Techo:** 9 calibradores fuera de CI (F-2, instalación de fábrica, P0-AUTH, M1, corte4, corte5, negación, operador-ámbito); 10 con `.replace(…,1)`; `knowledge-visibility` fuera de testpaths.
- **Criterio de cierre:** todo calibrador citado como «exigido» en un PR corre como paso required con guardia anti-cero; ningún calibrador con ancla no única.

### P2 — Retirar `/review-console` de instalaciones normales
- **Hallazgos:** —. **Estado:** DONE · **PR/SHA:** #263 `b6852ce`. **Calibrador:** 3/3 · **CI:** required.
- **Techo:** la ruta sigue montada tras bandera (decisión D-RC). **Criterio:** 404 por defecto → cumplido.

### P3 — Sin mock como conocimiento real
- **Hallazgos:** H-44, H-45. **Autoridad:** `classify_provider_declaration`. **Estado:** IN_PROGRESS · **PR/SHA:** #264 `b4da16a`.
- **Calibrador:** 7/7 · **CI:** required · **E2E:** no.
- **Techo:** `viewer/.env.example:3` sigue en `mock`; banner DEMO cubre datos reales (jobs); API sin marca; 500 preexistente en pantallas de datos sin proveedor.
- **Criterio de cierre:** plantilla de fábrica = vacío honesto; DEMO solo bajo modo explícito y solo sobre datos del proveedor; API marca el modo.

### P4 — Instalación HTTPS sin degradar Secure
- **Hallazgos:** H-35, H-44. **Autoridad:** `preflight_https.py`, rol `tls`, D3. **Estado:** E2E_PENDING · **PR/SHA:** #266 `0cf977c`.
- **Tests:** 28 TLS reales · **Calibrador:** 8/8 · **CI:** required · **E2E/RC:** PENDING (N1–N7).
- **B2 (#271):** la vía HTTPS se ejerce ahora sobre la plantilla productiva **literal** (`not_configured`, sin CSRF manual, `Secure=true`) dentro del recorrido de primera release; el setup ya no culpa a Safari (H-35). Sigue E2E_PENDING.
- **Criterio de cierre:** ensayo RC con nginx/systemd/CA en máquina limpia con acta.

### P5 — Bootstrap del primer administrador verificado
- **Hallazgos:** H-01 (parcial), H-06, H-35, H-44. **Autoridad:** `install_state`, `csrf_bootstrap`. **Dependencias:** P4.
- **Estado:** CI_GATED (código + arnés local) · E2E_PENDING · **PR/SHA:** #247 `a58e137`, #248 `bcd9e59`; contenido de #267 (`e683274`) **absorbido en B2** (#271) por cherry-pick `-x`.
- **GATE A** implementado (`preflight_setup_admin.py --modo gate-a`, paso 16c de `deploy.sh`) · **GATE B** = recorrido de #267 con credenciales por fichero 0600/stdin · ejecutados en arnés HTTPS local contra el visor real (`deploy/tests/test_b2_primera_release.py`).
- **Calibrador:** #248 fuera de CI; PR-4 10/10; B2 10/10 (M5 = GATE A con `status != 403`) · **E2E/RC:** PENDING (N8–N17).
- **Criterio de cierre:** GATE A (POST inválido con CSRF correcto → respuesta de validación exacta, distinguiendo CSRF funcional de 403 por Secure; 5xx no es PASS) + GATE B (recorrido completo con credenciales de prueba por el mecanismo seguro) ejecutados en máquina limpia.

### P6 — Escritores leen configuración por la autoridad efectiva
- **Hallazgos:** H-50. **Autoridad:** `effective_env_value` (S-3). **Estado:** NOT_STARTED.
- **Techo:** `v3_apply.py:822/1105`, `gate.py:100`, `driver_neo4j.py:73`, `ingest_cli.py:426` leen `os.environ`; 20 lecturas directas en `viewer/app`.
- **Criterio de cierre:** ningún consumidor de producto lee `os.environ` directamente; `S9K_ALLOW_REAL_INGEST=1` en `.env` habilita el apply web; negativo + calibrador en CI.

### P7 — Configuración persistida como fuente del resolver
- **Estado:** NOT_STARTED. **Dependencias:** P6. **Criterio:** precedencia environment > `.env` > persisted > default a través del mismo resolver; sin segunda autoridad.

### P8 — Pantalla de configuración efectiva · P9 — Paneles por web · P10 — Proveedores/servicios por conceptos humanos
- **Hallazgos:** H-09, H-44. **Estado:** NOT_STARTED. **Dependencias:** P6, P7. **Insumos:** `docs/59` (rama `docs/panel-rpg-management-design`), 59 tests de `feat/admin-operations-dashboard` como especificación de umbrales (no el código).
- **Criterio:** biblioteca, proveedor, juego, paneles configurables por web sin exponer `S9K_*`.

### P11 — Continuidad del primer arranque
- **Hallazgos:** H-13. **Estado:** IN_PROGRESS (parcial en #248; B2 #271 lleva el estado de revisión V3 fuera de la release en la plantilla productiva y lo exige en `deploy.sh`). **Criterio:** estado fuera del árbol de código por defecto; `docs/50` referenciada existe o se retira la referencia (H-53, sigue abierto).

### P12 — Juego/perfil por package validado
- **Hallazgos:** H-07 (vocabulario), H-09. **Estado:** NOT_STARTED. **Criterio:** el administrador no edita `perfil-operador.json` ni `catalogo-workspace.json`.

### P13 — Navegación de huérfanas · P14 — Guardas e higiene del recorrido
- **Hallazgos:** H-10, H-31, H-46, H-52, H-05, H-13. **Estado:** IN_PROGRESS (#239, #250, #242, #254, #256). **Criterio:** 0 huérfanas, 0 enlaces de menú a error, errores HTML en rutas de navegador, `Location` relativo.

### P15 — E2E ZERO-TERMINAL real
- **Estado:** NOT_STARTED. **Dependencias:** B1–B3, FASE C, FASE D. **Criterio:** guion completo en entorno limpio sin terminal/fichero/ID tras «instalado»; cada necesidad = gap registrado.

### P16 — Cerrar garantías congeladas
- **Estado:** NOT_STARTED. **Criterio:** toda propiedad crítica con PROPERTY → TEST → NEGATIVE → CALIBRATOR → REQUIRED CI; ningún E2E_PENDING sin fecha.

### P17 — Documentación final
- **Hallazgos:** H-12, H-47, H-49, H-39, H-40, H-53. **Estado:** NOT_STARTED. **Criterio:** README/ROADMAP/CHANGELOG al día; guías de usuario y administrador; estructura `docs/` clasificada.

## 6. Carriles de la FASE B (contratos)

### B1 — H-03 · Aislamiento por workspace en la revisión V3
- **Hallazgos:** H-03 (rango 1). **Hito:** garantía transversal (P14). **Autoridad:** `VisibilityScope` (`authz/scope.py`) y `autoridad_workspace` (F-2); el cliente nunca amplía su scope.
- **Clase a cubrir:** `GET/POST /v3/review*` (`decide`, `undo`, `glossary-candidates`), `/panel/review*`, y toda entrada `workspace`/`partida_id` de cliente en rutas de revisión.
- **Contrato:** revisor con concesión en A actúa sobre A; no puede ver ni actuar sobre B; `workspace` de formulario nunca amplía scope; admin `admin_full` sigue viendo todo.
- **Controles:** positivo (A sobre A), negativo (A sobre B → 404/403 sin registro en `human_decisions`), negativo con `partida_id` ajeno, calibrador que ablaciona la comprobación y enrojece por la causa correcta, paso required en CI.
- **Criterio de cierre:** negativo real con dos workspaces en CI required; `_scoped()` no devuelve `partida_only()` para rutas HTTP; `risk-register` actualizado; auditoría de rutas equivalentes adjunta.
- **Estado:** **VERIFIED** · **PR/SHA:** #269 → `2dd6d47` (squash; HEAD del PR `1ce168b`, base `8964c36`).
- **Demostrado:** aislamiento server-side de workspace en toda la familia Review V3 (`GET /v3/review`, `POST decide`, `POST undo`, `GET glossary-candidates`, `GET /panel/review/`, `/panel/review/item/{id}`) mediante una función única `VisibilityScope.para_corpus_de_revision()`; matriz de autorización 16 casos × 6 rutas con app y auth reales; rechazo A→B = 404 con **cero persistencia** (huella completa del almacén: `human_decisions`, `decision_audit`, `glossary_outbox`, `sealed_plans`, `entity_altas`, `decisions.jsonl`); admin `admin_full` y lore anónimo (docs/81) intactos; 25 tests (`viewer/tests/test_b1_h03_aislamiento_workspace_review.py`), calibrador `mutaciones_b1_h03_aislamiento_workspace.py` 6/6 CALIBRADA por AST (incl. M6 «concesión vacía ⇒ todo visible») en el job required «Calibracion de gates»; 34/34 check-runs `pass` sobre `1ce168b`; revisor independiente APTO CON OBSERVACIONES (ninguna bloqueante); mutaciones propias del revisor X1–X6 y X8 detectadas; `risk-register` RK-21.
- **Hermanos investigados:** `services/v3_apply.py:564` → DIFFERENT_CLASS (el `workspace` sale de `scoped_job` acotado; ruta solo admin); `services/review_console.py` v1 → DIFFERENT_CLASS (laboratorio, sin workspace de cliente, 404 por defecto). No se amplía H-03.
- **Techo independiente (no degrada lo demostrado):** aislamiento E2E entre dos bóvedas reales en Neo4j: **NOT MEASURED**, pendiente del ensayo de integración correspondiente (Fase E). Precondición de despliegue: verificar que las propuestas existentes en producción llevan el `workspace` canónico literal (si no, cola vacía: fail-closed, problema de usabilidad, no de seguridad).
- **Deuda rango 4 registrada:** X7 (`glossary_candidates` sin filtro) solo lo detecta m5a; comentario de `_huella` cita `audit.jsonl` que no se hashea (la tabla `decision_audit` sí); `undo` deshace decisiones de otros revisores dentro del ámbito (preexistente); doble `load_proposals` en `decide`.

### B2 — H-01/H-43 · Familia fresh install
- **Estados explícitos:** DEPLOY_OK → HTTPS_BOOTSTRAP_PATH_VERIFIED → FIRST_ADMIN_PENDING → FIRST_ADMIN_VERIFIED → INSTALLATION_COMPLETE.
- **Piezas existentes a extender (no duplicar):** `deploy.sh`, `detect_state.py` (`decision` vs `global_state`), `preflight_https.py`, `preflight_ensayo_rc.py`, PR #267, plantillas `viewer/.env.example` y `deploy/config/viewer.env.example` (H-44, H-49).
- **Criterio de cierre:** máquina limpia → `current` activo → `/setup/admin` alcanzable por HTTPS → GATE A y GATE B → reinicio → persistencia, sin pasos no documentados; `deploy.sh` respeta `decision`; upgrade con `jobs.db` vacía no bloquea.
- **Estado:** IMPLEMENTED · TESTED · CI_GATED · **RC-E2E PENDING** (nunca DONE sin el ensayo RC) · **PR:** #271 (rama `feat/b2-h01-fresh-install`, base `8d29a00`).
- **Camino elegido:** `deploy.sh --mode fresh` (una sola autoridad que construye releases); Ansible prepara la máquina y avisa de que la primera release no es suya. Documentado en `deploy/README.md` «Primera release».
- **Por hallazgo** (todo **VERIFIED (arnés local)**: ejecutado sobre el texto real de `deploy.sh` y el visor real por TLS local, **no** en máquina limpia; RC-E2E PENDING para todos): H-01 (paso 4 decide por `decision`; fresh procede en máquina limpia y bloquea con usuarios/sello/corrupción, por estado del producto) · H-43 (`jobs.db` ausente/vacía no bloquea) · H-44 (plantillas `not_configured`; el 403 del setup nombra la causa observada; **sigue en OPEN_R2 hasta el RC**) · H-49 (plantilla y `validate_deploy.sh` alineados con #248; `S9K_V3_REVIEW_*` declaradas) · H-35 (texto del setup; `security.py` sin cambios).
- **H-04 · lado deploy** (`CRITICAL_ENV_VARS` + plantilla + `preflight_ensayo_rc --grupo despliegue` en el paso 6): **VERIFIED (arnés local)** · persistencia completa del estado de revisión: **OPEN (Fase C)**.
- **H-18 · lado config/preflight**: **VERIFIED (arnés local)** · consumo/ausencia silenciosa en runtime (`review_decisions` → `{}`): **OPEN (Fase C)**.
- **Estados medibles:** `estado_instalacion.py` (DEPLOY_OK → HTTPS_BOOTSTRAP_PATH_VERIFIED → FIRST_ADMIN_PENDING → FIRST_ADMIN_VERIFIED → INSTALLATION_COMPLETE; `deploy.sh` nunca ANOTA evidencia de gates no observada; en upgrade declara `ESTADO_OBSERVADO=DEPLOY_OK` y, por separado, `ESTADO_DEL_PRODUCTO=` leído de la auth DB (sello + admins)).
- **Tests:** `deploy/tests/test_b2_fresh_install.py` (rápido: pasos 3–4 y 6 REALES de `deploy.sh`, plantillas, GATE A, estados) · `deploy/tests/test_b2_primera_release.py` (visor real por TLS local: máquina limpia → INSTALLATION_COMPLETE; HTTP plano reproduce el 403). **Calibrador:** `mutaciones_b2_fresh_install.py` (10 mutaciones + 7 de la ronda de corrección de la revisión independiente) en el job required «Calibracion de gates».
- **Techo:** clon+venv de la release, systemd (pasos 7–13), nginx, CA real, navegador, VM limpia y reinicio de máquina no ejercidos; venv del motor → B3 (su único consumidor es el worker); H-08 (dos unidades del visor) documentado, no resuelto: **el camino fresh deja el visor como root** (unidad del repo sin `User=`, ahora habilitada); H-06: `auth.db` sale 0644; el registro de estados se reinicia en cada despliegue (corrección R2-a: un upgrade no hereda INSTALLATION_COMPLETE); el reinicio entre GATE B bootstrap y persistencia lo afirma el operador.

- **Deuda registrada por la revisión independiente (rango 4 / CI):** la salida final de `deploy.sh` usa `python3 … | while read` con `pipefail` (un error de `estado_instalacion` tras un despliegue correcto daría rc≠0: el rc final deja de ser fiable); un SQLite ajeno sin tabla `users` se lee como `FIRST_ADMIN_PENDING` (O1); `-w` se comprueba como root, no como el usuario del servicio (H-08); GATE A exige token presente, no token nuevo (MP2c); el job «Calibracion de gates» (~2 h, +11 min por B2) no declara `timeout-minutes` y hereda 360 → deuda CI-CALIBRATION-PERFORMANCE (aparcada; fijar ~180 cuando se toque CI).
- **Revisión independiente:** NO APTO (R2-a falsa confirmación `INSTALLATION_COMPLETE` en upgrade por evidencias heredadas; 6 huecos de detector) → corregido en el mismo PR → APTO CON OBSERVACIONES sobre `97f864c`; CI 17 required × 2 runs `pass`.

### B3 — H-02 · Worker desatendido
- **Cadena:** job → cola → consumer → loop → servicio → ejecución → resultado → error/retry → restart.
- **Criterio de cierre:** unidad de servicio canónica instalada por el despliegue; `--loop` real sin `rc=0` inmediato; stale/retry/cancel con tests; un job creado desde `/panel/operations` se procesa sin intervención manual; error observable en la web.
- **Estado:** IMPLEMENTED · TESTED · CI_GATED · **H-02 VERIFIED (arnés local) · RC-E2E PENDING** · **PR:** #273 (rama `feat/b3-h02-worker-desatendido`, base `7841f85`), revisión independiente pendiente.
- **Reproducido antes:** `--loop` rc=0 al instante; stale ×5 → `attempts=0`; `next_retry_at` futuro reclamado; `cancelled` sobrescrito a `complete`; `heartbeat()` sin llamadores; ninguna unidad de worker en ningún ref; 4 defaults de `jobs.db`. Encontrado por el E2E: la columna «Incidencia» de `/panel/operations` decía «no» a un admin sobre un job `failed`.
- **Demostrado (arnés local, CI required):** web → worker arrancado con los flags de la unidad canónica, su `worker.env` y su `WorkingDirectory` → `jobs.db` + propuestas en el almacén de `review_paths` → `/jobs`, `/panel/operations`, `/panel/review` → reinicio (SIGTERM rc=0) → segundo job procesado solo (`viewer/tests/test_b3_worker_desatendido_e2e.py`); negativos worker parado, error permanente/transitorio acotado, worker matado a mitad, `max_attempts` agotado, `--loop` vivo (rc=124) / `--once` rc=0 (`data-engine/app/tests/test_b3_worker_desatendido.py`); unidad por efecto y pasos 2/7/13 reales de `deploy.sh` (`deploy/tests/test_b3_worker_unidad.py`).
- **Unidad canónica:** `data-engine/systemd/s9-knowledge-worker.service` (única plantilla; `deploy.sh` la instala, habilita y exige `active`; el rol `systemd` copia el mismo fichero). `User=www-data`, `UMask=0077`, `Restart=always`, `--loop --release-stale-seconds 600 --retry-backoff-seconds 30`, intérprete = venv del motor que crea `deploy.sh` (deuda de B2 cerrada).
- **H-37:** VERIFIED (arnés local): `job_store.ruta_de_despliegue` es la autoridad; `deploy.sh` la pide; las plantillas la declaran; `run-jobs-worker.sh` retirado. **H-33:** sigue OPEN (no tocado).
- **Calibrador:** `mutaciones_b3_worker.py` 11/11 CALIBRADA (190 s) en el job required «Calibracion de gates».
- **Techo:** systemd real, usuario del servicio sobre el state root real, propietario de `-wal/-shm` creados por root, reinicio de máquina, Neo4j/apply. H-08 sigue abierto (el visor de `deploy.sh` corre como root).
- **Deuda:** worker sin verificación de identidad de release (solo `is-active` ×3); `worker.env` sigue siendo manual (ahora obligatorio: un upgrade sin él bloquea en el paso 6).

## 7. Registro de cambios del plan

| Fecha | Cambio | Evidencia |
|---|---|---|
| 2026-10-11 | Creación del plan canónico a partir de la auditoría R1+R2 | `docs/audits/AUDITORIA_GLOBAL_S9_KNOWLEDGE_2026-10-10.md` (R2.11, R2.16) |
| 2026-10-11 | Fase A cerrada (#268 → `8964c36`); B1/H-03 VERIFIED (#269 → `2dd6d47`); R1 abiertos 3 → 2; CURRENT_HIT → B2 | PR #268, PR #269, log CI run `38127086116` y runs sobre `1ce168b` (34/34 pass) |
| 2026-10-12 | B3 abierto (#273): H-02 VERIFIED (arnés local), H-37 VERIFIED (arnés local); unidad canónica del worker instalada por `deploy.sh`; calibrador 11/11; RC-E2E PENDING | PR #273 |
| 2026-10-12 | B2 cerrado (#271 → `751995c`): H-01/H-43/H-44/H-49/H-35 VERIFIED (arnés local), H-04/H-18 solo lado deploy; RC-E2E PENDING; R1 abiertos 2 → 1; CURRENT_HIT → B3 | PR #271 (HEAD `97f864c`, 3 rondas de revisión independiente), CI 17×2 pass |
| 2026-10-11 | B2 abierto (#271): H-01/H-43/H-44/H-49 implementados y calibrados; H-04/H-18 solo lado deploy; contenido de #267 absorbido; P5 → CI_GATED; RC-E2E PENDING | PR #271 |
