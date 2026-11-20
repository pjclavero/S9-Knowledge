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
| CURRENT_MAIN | `007790e` (#292 documentación de la RC-E2E 1, `docs/93`; sin código) ← `864041d` (**sujeto de la RC-E2E final**; #291 credencial veraz: `GRAPH_CREDENTIAL_UNUSABLE` con `error_code`, y documentación de RC1-02 y RC1-G04) ← `31935e6` (#290 parada verificada y validación antes de parar) ← `7982f6d` (#288 lectura de secretos) ← `bb7f3c9` (#287 deudas de salud) ← `e2063bc` (#289 CI en `ubuntu-latest`) ← #286 ← `b4e396d` (sujeto de la RC-E2E 1) ← `f7057b7` (squash de #285 H-06 + H-08); anteriores: (#285 H-06 + H-08; #284 = `4916e90` plan; #283 = `4f186fd` H-05 corte B; #281 = `11b67d1` H-05 corte A, #282 = `f06431d`, #279 = `2cf2361` C1; #274 = `a401e45`, #277 = `d35f863` MAIN_CI_MIGRATED_SHA, #278 = `b137aa9`, #276 = `4eb442a`, #275 = `284758c`, #273 = `70b823a`; #272 = `7841f85`, #271 = `751995c`, #270 = `8d29a00`, #269 = `2dd6d47`, #268 = `8964c36`) |
| CURRENT_PHASE | **C** (integridad y seguridad rango 2); Fase B cerrada con #273 (R1 abiertos = 0 en el alcance demostrado; RC-E2E PENDING como techo independiente de B2/B3) |
| CURRENT_HIT | **RC-E2E final (segunda ronda) EJECUTADA: NO VERIFIED** (2026-11-20, sujeto `864041d`, resultados en `docs/94-rc-e2e-final-resultados.md`): revisión adversarial independiente **NO APTO**; los dos P1 de la RC-1 corregidos por efecto **en el laboratorio**, pero regresiones 1 (mitad CLI), 9, 13 y 15 de `docs/93` §8 no cumplidas o no ejecutadas; 4 hallazgos P3 abiertos (RC2-01 a RC2-04) con corrección **sin mergear** (#293 en draft); ningún escenario cerrado como PASS completo; ningún hito pasa a VERIFIED de RC; producción sin tocar · **RC-E2E 1 (diagnóstica) EJECUTADA** (2026-11-18/19, sujeto `b4e396d`, resultados en `docs/93-rc-e2e-1-resultados.md`): 2 P1 (RC1-G01, RC1-06) y 4 P2 confirmados por ejecución; corregidos en #288 y #290 y #291 (`864041d`); **las correcciones NO estaban verificadas por efecto** al cerrar esa ronda (lo medido después está en `docs/94` §5); ningún escenario cerrado como PASS completo · **H-06 + H-08 CERRADO** (#285 → `f7057b7`, HEAD `44c35ac`): **VERIFIED (arnés local + laboratorio), RC-E2E PENDING**; sin VERIFIED de producción · siguiente: resto de Fase C · **H-05 CERRADO**: corte A (#281 → `11b67d1`) y corte B (#283 → `4f186fd`) **VERIFIED (arnés local), RC-E2E PENDING** · C1 CERRADO (#279) |
| OPEN_R1 | **ninguno** · H-02 **VERIFIED (arnés local), RC-E2E PENDING** (#273 → `70b823a`) · H-01 (+H-43) **VERIFIED (arnés local), RC-E2E PENDING** (#271) · H-03 **VERIFIED** (#269) |
| OPEN_R2_BLOQUEANTES | H-07, H-09, H-11/H-48, H-14, H-19, H-44 (código y arnés local en #271; RC-E2E PENDING), H-50 |
| CURRENT_PR | documentación de la RC-E2E final (rama `docs/rc-e2e-final-resultados`, sin PR abierto todavía); **#293 en draft, sin mergear** (RC2-01, RC2-03, RC2-04); #292 ya mergeado → `007790e` |
| NEXT_TASK | **cerrar y mergear las correcciones de la RC-E2E final** (#293; decisión sobre RC2-02; la rama de la estabilidad del mutante M1 del calibrador B3 y los hallazgos de E8, aún sin PR) y, con ellas en `main`, **tercera ronda de RC-E2E** (`docs/94` §10); después, resto de Fase C: H-19, H-50/P6, H-14, H-07, H-09, H-11/H-48 (orden a fijar al abrir el carril); después Fase D zero-terminal |
| BLOCKERS | **decisión del operador sobre Neo4j en el laboratorio**: no se vuelve a arrancar sin ella (incidente RC2-E3: 4 de 5 episodios de presión del hipervisor tras un arranque de Neo4j; correlación, no causalidad demostrada; `docs/94` §11). Además, la tercera ronda sigue necesitando navegador y, si se quiere probar una legacy real, autorización del operador |
| DEBT_PARKED | WORKTREE-HYGIENE (147 worktrees, 435 ramas, 3 stashes), DEPENDENCY-MAINTENANCE (7 Dependabot, #209 major), CI-CALIBRATION-PERFORMANCE (job de 77 min serial) |
| E2E_PENDING | P4, P5, B2 completo (RC-E2E PENDING en #266/#267/#271), P15. La RC-E2E 1 **ejerció parte** de B2/B3/C1/H-05/H-06+H-08 (ver cada ficha) pero no cierra ninguna: fue diagnóstica y con fallos |
| RC_PENDING | guion N1–N17 de `deploy/README.md`: **ejecutado en parte por la RC-E2E 1** (diagnóstica; las filas automatizables sobre una máquina de laboratorio; N8, N10, N11 manuales sin ejecutar; N12 no producible; sin navegador). **RC-E2E final ejecutada sobre `864041d` con veredicto NO VERIFIED** (`docs/94`): N8, N10 y N11 siguen sin ejecutar, N12 no producible, sin navegador. **Pendiente una tercera ronda** con lo de `docs/94` §10. Producción sin tocar |

## 2. Métrica de progreso (no se mide por número de PR)

| Métrica | Baseline (R2, `0cf977c`) | Actual | Delta |
|---|---|---|---|
| Rango 1 abiertos | 3 | **0** | −3 (H-03 VERIFIED #269; H-01 y H-02 VERIFIED en arnés local #271/#273, con RC-E2E PENDING como techo independiente) |
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
- **Hallazgos:** H-50. **Autoridad:** `effective_env_value` (S-3). **Estado:** NOT_STARTED (C1 solo unifica la resolución de `S9K_V3_REVIEW_DATABASE_PATH` en `review_paths`; no toca `effective_env_value` ni las demás lecturas directas).
- **Techo:** `v3_apply.py:822/1105`, `gate.py:100`, `driver_neo4j.py:73`, `ingest_cli.py:426` leen `os.environ`; 20 lecturas directas en `viewer/app`.
- **Criterio de cierre:** ningún consumidor de producto lee `os.environ` directamente; `S9K_ALLOW_REAL_INGEST=1` en `.env` habilita el apply web; negativo + calibrador en CI.

### P7 — Configuración persistida como fuente del resolver
- **Estado:** NOT_STARTED. **Dependencias:** P6. **Criterio:** precedencia environment > `.env` > persisted > default a través del mismo resolver; sin segunda autoridad.

### P8 — Pantalla de configuración efectiva · P9 — Paneles por web · P10 — Proveedores/servicios por conceptos humanos
- **Hallazgos:** H-09, H-44. **Estado:** NOT_STARTED. **Dependencias:** P6, P7. **Insumos:** `docs/59` (rama `docs/panel-rpg-management-design`), 59 tests de `feat/admin-operations-dashboard` como especificación de umbrales (no el código).
- **Criterio:** biblioteca, proveedor, juego, paneles configurables por web sin exponer `S9K_*`.

### P11 — Continuidad del primer arranque
- **Hallazgos:** H-13. **Estado:** IN_PROGRESS (parcial en #248; B2 #271 lleva el estado de revisión V3 fuera de la release en la plantilla productiva y lo exige en `deploy.sh`; C1 hace que `review.sqlite3` lo cree el despliegue y que un upgrade lo exija existente). **Criterio:** estado fuera del árbol de código por defecto; `docs/50` referenciada existe o se retira la referencia (H-53, sigue abierto).

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
- **H-04 · lado deploy** (`CRITICAL_ENV_VARS` + plantilla + `preflight_ensayo_rc --grupo despliegue` en el paso 6): **VERIFIED (arnés local)** · persistencia completa del estado de revisión: **VERIFIED (arnés local), RC-E2E PENDING** (C1, #279 → `2cf2361`).
- **H-18 · lado config/preflight**: **VERIFIED (arnés local)** · consumo/ausencia silenciosa en runtime (`review_decisions` → `{}`): **VERIFIED (arnés local), RC-E2E PENDING** (C1: con ruta declarada la ausencia falla cerrado; sin declarar = techo documentado).
- **Estados medibles:** `estado_instalacion.py` (DEPLOY_OK → HTTPS_BOOTSTRAP_PATH_VERIFIED → FIRST_ADMIN_PENDING → FIRST_ADMIN_VERIFIED → INSTALLATION_COMPLETE; `deploy.sh` nunca ANOTA evidencia de gates no observada; en upgrade declara `ESTADO_OBSERVADO=DEPLOY_OK` y, por separado, `ESTADO_DEL_PRODUCTO=` leído de la auth DB (sello + admins)).
- **Tests:** `deploy/tests/test_b2_fresh_install.py` (rápido: pasos 3–4 y 6 REALES de `deploy.sh`, plantillas, GATE A, estados) · `deploy/tests/test_b2_primera_release.py` (visor real por TLS local: máquina limpia → INSTALLATION_COMPLETE; HTTP plano reproduce el 403). **Calibrador:** `mutaciones_b2_fresh_install.py` (10 mutaciones + 7 de la ronda de corrección de la revisión independiente) en el job required «Calibracion de gates».
- **Techo:** clon+venv de la release, systemd (pasos 7–13), nginx, CA real, navegador, VM limpia y reinicio de máquina no ejercidos; venv del motor → B3 (su único consumidor es el worker); H-08 (dos unidades del visor) documentado, no resuelto: **el camino fresh deja el visor como root** (unidad del repo sin `User=`, ahora habilitada); H-06: `auth.db` sale 0644; el registro de estados se reinicia en cada despliegue (corrección R2-a: un upgrade no hereda INSTALLATION_COMPLETE); el reinicio entre GATE B bootstrap y persistencia lo afirma el operador.

- **Deuda registrada por la revisión independiente (rango 4 / CI):** la salida final de `deploy.sh` usa `python3 … | while read` con `pipefail` (un error de `estado_instalacion` tras un despliegue correcto daría rc≠0: el rc final deja de ser fiable); un SQLite ajeno sin tabla `users` se lee como `FIRST_ADMIN_PENDING` (O1); `-w` se comprueba como root, no como el usuario del servicio (H-08); GATE A exige token presente, no token nuevo (MP2c); el job «Calibracion de gates» (~2 h, +11 min por B2) no declara `timeout-minutes` y hereda 360 → deuda CI-CALIBRATION-PERFORMANCE (aparcada; fijar ~180 cuando se toque CI).
- **RC-E2E 1 (diagnóstica) — ejercido / pendiente:** ejercido sobre `b4e396d` con HTTPS, nginx y CA reales: primera release `--mode fresh` en producción hasta GATE A real (16c) y N17 (E1 PARCIAL), GATE B real hasta `INSTALLATION_COMPLETE` (E7 12/0), N9, N13–N16 y persistencia tras reinicio de máquina (E14, 14/0 en el segundo intento; el primero falló por el entorno). **Falló:** `preflight.sh` bloquea una máquina limpia (RC1-01, P3, abierto) y los STOP de configuración llegaban tras parar (RC1-03/05). **Pendiente:** navegador, Ansible, N8/N10/N11 manuales, N12 no producible. No cierra el RC-E2E de B2.
- **Revisión independiente:** NO APTO (R2-a falsa confirmación `INSTALLATION_COMPLETE` en upgrade por evidencias heredadas; 6 huecos de detector) → corregido en el mismo PR → APTO CON OBSERVACIONES sobre `97f864c`; CI 17 required × 2 runs `pass`.

### B3 — H-02 · Worker desatendido
- **Cadena:** job → cola → consumer → loop → servicio → ejecución → resultado → error/retry → restart.
- **Criterio de cierre:** unidad de servicio canónica instalada por el despliegue; `--loop` real sin `rc=0` inmediato; stale/retry/cancel con tests; un job creado desde `/panel/operations` se procesa sin intervención manual; error observable en la web.
- **Estado:** IMPLEMENTED · TESTED · CI_GATED · **H-02 VERIFIED (arnés local) · RC-E2E PENDING** · **PR:** #273 → `70b823a` (HEAD `76d6da4`, base `7841f85`); revisión independiente: NO APTO (r1) → APTO CON OBS (r2, r3: solo rango 4) → APTO para B14 (r4); CI 17 required × 2 runs `pass`.
- **Ronda CI (B14):** el cambio de `has_error` movió el ancla de B14 de `calibrar_panel_operations.py` (CI rojo en `4c2ec8f`); re-anclado por AST en `76d6da4` sin debilitar la mutación (revisor: rojo por `'/srv/secreto' not in …`); `_fila` no publica `error_message`. Origen de la **PRE-PUSH CALIBRATION RULE** (§8).
- **Reproducido antes:** `--loop` rc=0 al instante; stale ×5 → `attempts=0`; `next_retry_at` futuro reclamado; `cancelled` sobrescrito a `complete`; `heartbeat()` sin llamadores; ninguna unidad de worker en ningún ref; 4 defaults de `jobs.db`. Encontrado por el E2E: la columna «Incidencia» de `/panel/operations` decía «no» a un admin sobre un job `failed`.
- **Demostrado (arnés local, CI required):** web → worker arrancado con los flags de la unidad canónica, su `worker.env` y su `WorkingDirectory` → `jobs.db` + propuestas en el almacén de `review_paths` → `/jobs`, `/panel/operations`, `/panel/review` → reinicio (SIGTERM rc=0) → segundo job procesado solo (`viewer/tests/test_b3_worker_desatendido_e2e.py`); negativos worker parado, error permanente/transitorio acotado, worker matado a mitad, `max_attempts` agotado, `--loop` vivo (rc=124) / `--once` rc=0 (`data-engine/app/tests/test_b3_worker_desatendido.py`); unidad por efecto y pasos 2/7/13 reales de `deploy.sh` (`deploy/tests/test_b3_worker_unidad.py`).
- **Unidad canónica:** `data-engine/systemd/s9-knowledge-worker.service` (única plantilla; `deploy.sh` la instala, habilita y exige `active`; el rol `systemd` copia el mismo fichero). `User=www-data`, `UMask=0077`, `Restart=always`, `--loop --release-stale-seconds 600 --retry-backoff-seconds 30`, intérprete = venv del motor que crea `deploy.sh` (deuda de B2 cerrada).
- **H-37:** VERIFIED (arnés local): `job_store.ruta_de_despliegue` es la autoridad; `deploy.sh` la pide; las plantillas la declaran; `run-jobs-worker.sh` retirado. **H-33:** sigue OPEN (no tocado).
- **Calibrador:** `mutaciones_b3_worker.py` 25/25 CALIBRADA (346 s) en el job required «Calibracion de gates» (11 iniciales + 10 de la ronda de corrección + 4 de la ronda final: MN/MS el llamador cierra sin `locked_by`, MP sonda con COMMIT, MQ contador sin reinicio). Ronda final (APTO CON OBSERVACIONES): secreto vacío bloquea en `validate_secret_file`.
- **Revisión independiente (ronda 1): NO APTO, corregido en #273:** F1 receta de primera release sin `worker.env` (añadida + testigo); F2 cola de solo lectura/corrupta = daemon `active` en silencio (sonda de escritura al arrancar y `rc=3` tras 5 vueltas fallidas seguidas); F3 rollback sin revertir el worker (`lib.sh::revertir_worker`: `disable --now` si la release previa no tiene venv); F5 `S9K_V3_REVIEW_DATABASE_PATH` en `worker.env.example` e igualdad con `viewer.env`; F7/F8 testigos y mutaciones ME/MC/MD/MA/MF; F13 `complete` limpia `error_message`.
- **Techo:** systemd real, usuario del servicio sobre el state root real, propietario de `-wal/-shm` creados por root, reinicio de máquina, Neo4j/apply. H-08 sigue abierto (el visor de `deploy.sh` corre como root). **F6:** sin tiempo máximo por trabajo: un handler colgado sigue latiendo y bloquea la cola. **F10:** con `TimeoutStopSec=120` un trabajo más largo lo mata systemd al parar (queda huérfano y se libera gastando un intento).
- **RC-E2E 1 (diagnóstica) — ejercido / pendiente:** la unidad del worker arrancó, se reinició y se recuperó de SIGKILL con `Restart=always` (E5, 18/0), y recogió un job en unos 4 s. **Falló:** el job terminó `failed` con `GRAPH_OBSERVATION_UNCONFIGURED` porque el worker no podía leer su secreto (RC1-G01, P1; corregido en #288) y el mensaje al operador atribuía mal la causa y dejaba `error_code` vacío (RC1-G02, P2; #291 → `864041d`). Un job que cierre el ciclo completo (ingesta, propuestas, revisión, APPLY) **no se ha visto nunca por efecto**. **Pendiente:** job creado desde `/panel/operations`, ciclo completo contra Neo4j real y reinicio de máquina con el worker final. No cierra el RC-E2E de B3.
- **Deuda:** worker sin verificación de identidad de release (solo `is-active` ×3); `worker.env` sigue siendo manual (ahora obligatorio: un upgrade sin él bloquea en el paso 6). **F4:** la cancelación es solo del ESTADO: el paquete de propuestas que el handler ya escribió sigue visible en `/panel/review`.

### C1 — H-04 + H-18 · Persistencia de decisiones humanas (`review.sqlite3`)
- **Estado:** **MERGED** (#279 → `2cf2361`, base `a401e45`; HEAD final `4236331`) · CI_GATED (calibrador 23/23 en el job required «Calibracion de gates»; 34/34 check-runs, 17/17 required, sin relanzamientos en el SHA final) · revisión independiente final **APTO CON OBSERVACIONES** · **H-04/H-18: VERIFIED (arnés local), RC-E2E PENDING**.
- **Contrato del operador:** *deploy* es la autoridad que decide y prepara el almacén; el *runtime* (visor y motor) lo consume y lo verifica y, con la ruta declarada, **nunca lo crea** ni lo sustituye por `{}`. Fresh crea y verifica por efecto; upgrade exige uno válido y lo preserva (vacío ≠ ausente); upgrade sin almacén = STOP por defecto, con excepción explícita `--autorizar-creacion-review-db` (solo con ausencia real y sin candidata legacy con decisiones; **no es un `--force`**).
- **Una sola resolución** (`review_paths.default_review_db`) para visor, motor y preflight; `ReviewService(database_path=…)` sustituye a la derivación D4. Variable declarada vacía / espacios / relativa / directorio / con `#`, `?`, `%` o control (N19): rechazo con la causa real en `validate_viewer_env` y en el runtime. Toda URI `file:` del almacén sale de **una** función, `review_paths.sqlite_uri` (escapa la ruta; solo `ro`/`rw`, nunca `rwc`), que usan la inspección, el almacén del visor y la lectura del motor.
- **Worker:** `ingest_v3` con la ruta declarada ausente termina `FAILED` (`REVIEW_STORE_UNAVAILABLE` / `REVIEW_STORE_PERMISSIONS`) sin publicar paquete; `preparar_estado_del_worker` deja el directorio y los `-wal/-shm` de la revisión al worker.
- **Cambio de contrato declarado:** `test_sin_almacen_el_motor_se_comporta_como_siempre` → con ruta declarada la ausencia levanta `ReviewDecisionsError`; sin variable declarada (desarrollo) se conserva el defecto del repo como **techo declarado**, con test propio.
- **Demostrado (arnés local, CI required):** matriz P1–P3 / N1–N19 en `deploy/tests/test_c1_revision_deploy.py`, `viewer/tests/test_c1_revision_runtime.py` y `viewer/tests/test_c1_n3_rutas_consumidoras.py` (N3 ampliado: inventario ESTRUCTURAL de las 14 rutas consumidoras derivado del router, POST con CSRF válido); E2E local fresh → decisión → upgrade con dos releases exportadas del árbol; calibrador `mutaciones_c1_persistencia_revision.py` 23/23 (M17–M20 añadidos en el cierre del P1-2).
- **Techo independiente:** systemd real, `chown` a `www-data`, propietario de `-wal/-shm` creados por root (H-08), VM limpia y reinicio de máquina: RC-E2E PENDING. No se migra ninguna BD legacy ni se toca `decisions.jsonl`.
- **Revisión independiente:** NO APTO por P1-1 (`/v3/review/glossary-candidates` abría el almacén de decisiones fuera del `try` → 500 con ruta ausente), corregido en el mismo PR con test que recorre todas las rutas del visor y el mutante M16. Revisión final: NO APTO por **P1-2** (las URIs `file:{ruta}?mode=…` del almacén del visor y de `_records` no escapaban la ruta: con `#`/`?` SQLite la cortaba, perdía `mode=` y el runtime CREABA otro fichero del que leía 0 decisiones / `{}`, mientras el despliegue, que sí escapaba, lo aceptaba). **Cerrado** en el mismo PR: una sola `sqlite_uri` compartida + rechazo N19 en despliegue y runtime; testigos por efecto y mutantes M17 (URI sin escapar), M18 (`validar_declaracion` admite), M19 (`validate_review_db_var` admite). **D9 cerrado:** el N3 manual (POST muertos en 403 por CSRF inventado, rutas del Apply sin cubrir) pasa a derivación estructural; sellar/aplicar/aprobar alta con el almacén ausente ya no dicen `APPLY_FAILED` sino `REVIEW_STORE_UNAVAILABLE` (mutante M20), y el catálogo del panel deja de tener esa clave duplicada (la segunda pisaba a la primera).
- **RC-E2E 1 (diagnóstica) — ejercido / pendiente:** ejercido en el laboratorio: upgrade sin almacén (STOP correcto con `--autorizar-creacion-review-db` posterior; E2 13/0: identidad, filas y sha preservados), N16 (ausente PASS; `jobs.db` de 0 bytes = BLOCK `CORRUPT_STATE`), fresh que crea y verifica el almacén. **Falló:** el STOP «sin almacén» llegaba con el servicio parado y el estado migrado (RC1-04, P2; #290) y el BLOCK de estado se aplicaba tras parar (RC1-05, P2; #290). **Pendiente:** decisión humana real preservada a través de un upgrade de producción, navegador y copia de producción. No cierra el RC-E2E de C1.
- **Deuda documentada C1** (rango 4, sin abrir carril):
  - **D1** El censo AST de N18 solo ve el literal `S9K_V3_REVIEW_DATABASE_PATH` y solo en `viewer/app` + `data-engine/app`: un alias o una concatenación no se detectan (techo declarado).
  - **D2** No hay testigo de que `export_review_package` no se trague un `ReviewDecisionsError`.
  - **D3** Un symlink colgante en la ruta declarada: fresh/autorizado crea en el destino, posiblemente fuera del state root (el juicio de ubicación es léxico).
  - **D4** Inspeccionar una candidata legacy en WAL crea su `-shm`, también en dry-run.
  - ~~**D5**~~ **CERRADA (P1-2):** las URIs del almacén salen de `review_paths.sqlite_uri` y la declaración con `#`/`?`/`%`/control se rechaza (N19). Fuera del almacén de revisión siguen URIs a mano (auth.db, jobs.db en `health/checks.py`, `auth/db.py`, `auth/schema_compat.py`, `detect_state.py`, `migrate_sqlite.py`): otro almacén, otro contrato; censo registrado, sin carril.
  - **D6** Directorio no escribible: `OperationalError` crudo en el visor y `REVIEW_STORE_UNAVAILABLE` (no PERMISSIONS) en el worker.
  - **D7** Quitar `--usuario-servicio` del preflight del paso 6 (o la exigencia de escritura) no pone nada rojo hasta el paso 13, ya con la release activada.
  - **D8** Orden: en el paso 6 `review_store preparar` crea antes de `preflight` y `validate_worker_env`; si estos mueren, queda la BD creada.
  - **D10** `review_paths.sqlite_uri` acepta `immutable=True` con `mode="rw"` (ningún llamador lo usa).
  - **D11** (detector) El inventario estructural de N3 no ve un consumidor importado con alias (`import ReviewService as X`) ni uno alcanzado vía función de otro módulo (techo declarado).
  - Flakies conocidos, ajenos a C1: Authz (`…identificador_fisico…CAMBIO`, reutilización de id en Neo4j) y Viewer (`test_si_el_proceso_muere_tras_reservar…`, «This portal is not running»); se relanza solo el job cuando la firma coincide.
  - Deuda restante D1–D4, D6–D8, D10–D11: documentada, **no bloquea** el cierre de C1.

### H-06 + H-08 — Usuario de servicio dedicado y estado privado

- **Estado:** **MERGED** (#285 → `f7057b7`, base `4916e90`, HEAD final `44c35ac`) · CI_GATED (34/34 check-runs, 17/17 required, CLEAN) · **VERIFIED (arnés local + laboratorio)** · **RC-E2E PENDING** (no se ha tocado producción; sin VERIFIED de producción). Revisión independiente: NO APTO → NO APTO → APTO CON OBSERVACIONES (rondas 2/2b) → NO APTO (B-1) → APTO CON OBSERVACIONES → APTO (dependencias). Historia: `IMPLEMENTED / TESTED` (arnés local) y **laboratorio** (fresh, upgrade legacy, negativos, otro usuario, healthcheck, CLIs como root real, secretos y bóveda); **ronda 2** tras una revisión NO APTO (P1 H-1: CLIs como root sembraban estado root-owned; P1 H-2: la escritura en la bóveda se apropiaba del perfil del operador; defectos de contrato C-1…C-7; testigos de los mutantes supervivientes R2/R3/R8/R10/R12/R13/R14), pendiente de revisión acotada; **`VERIFIED (arnés local)` solo al mergear con CI required verde y revisión independiente**; **RC-E2E PENDING** (no se ha tocado producción; sin VERIFIED de producción). Rama `feat/h06-h08-service-user-state-permissions`, base `4916e90`.
- **Hallazgos:** H-06 (`auth.db` y compañeros `0644`; `review.sqlite3` `0660`; ≥3 políticas de modo) y H-08 (visor como root; dos unidades del visor: la de `deploy.sh` sin `User=` y la plantilla Ansible con `www-data`).
- **Decisión D1:** usuario de sistema dedicado `s9knowledge` (no `www-data`) para visor, worker y healthcheck; nginx conserva el suyo; root solo instala y administra.
- **Autoridad única:** `data-engine/app/knowledge_v3/service_state.py` (usuario/grupo, state root, modo de fichero `0600`, modo de directorio `0700`, rutas efectivas, inspección y arranque fail-closed). Las unidades systemd y `group_vars/all.yml` se cruzan contra ella con un test estructural (M12); se eliminó la plantilla Jinja del visor y las cuatro copias de `s9k_service_user`.
- **Migración automática en `deploy.sh`:** pasos 3b (identidad + parada verificada) y 5b (inspección, movimiento con hash del estado mutable de la release al state root, propietario, modos, verificación por efecto con `runuser`); procesos vivos como `s9knowledge` (14a); cualquier fallo → STOP sin activar la release y con el original conservado. Resuelve la incoherencia paso 6 / paso 13 / README (una sola política).
- **Bóveda externa (criterios del operador 2026-11-15, decisión EXTERNAL OPERATOR CONTENT cerrada):** el **administrador** prepara dueño/grupo/modo de `S9K_VAULT_ROOT` y de `perfil-operador.json` para que `s9knowledge` pueda escribir; si no, 409 específico y salud **VAULT READ_ONLY**; S9-Knowledge **nunca** repara permisos de la bóveda (ni chmod/chown, ni root, ni la crea si falta: `S9K_VAULT_ROOT` inexistente → 404 nombrado, VAULT UNAVAILABLE, sin árbol nuevo). Componente de salud `vault` (AVAILABLE/READ_ONLY/UNAVAILABLE/UNMEASURABLE, opcional: nunca UNHEALTHY; UNMEASURABLE desde el sandbox del timer, B-1) junto a `state_validation` (STATE_VALIDATION: validación de arranque activa) y `state_runtime` (STATE_RUNTIME: inspección real en ejecución, UNKNOWN si no medible). Borrar/restaurar/recrear el STATE ROOT no altera la bóveda ni la recorre (aunque sea hermana); el backup/restore del STATE ROOT NO contiene la bóveda externa. Tests `viewer/tests/test_h06_h08_vault_criterios.py` y `deploy/tests/test_h06_h08_vault_state.py`; calibrador M56–M60; escenario H del laboratorio (H.7 state root borrado y restaurado con bóveda hermana, H.8 salud `vault`). Ver `deploy/README.md` «Bóveda externa: responsabilidad del administrador».
- **C1 intacto:** `review_store.py` cambia propietario/modos, no la semántica (regresión con los 54 casos de C1 y su calibrador).
- **Tests:** `deploy/tests/test_h06_h08_servicio_y_estado.py`, `…_inventario_escrituras.py`, `…_autoridad_y_worker.py`, `…_cli_root.py` (ronda 2: gate estructural de CLIs + root rechazado por efecto), `…_ronda2_contrato.py` (C-1…C-7, R2, R3), `viewer/tests/test_h06_h08_estado_privado.py`, `viewer/tests/test_h06_h08_vault_no_escribible.py`; calibrador `scripts/calibracion/mutaciones_h06_h08_servicio_y_estado.py` (M1–M55; `viewer/tests/test_h06_h08_vault_respaldo.py`); laboratorio `deploy/tests/lab/` (A–H).
- **Techo:** ACL/capacidades/SELinux no se interpretan (se detecta la presencia de ACL POSIX); el gate de CLIs sigue el cierre ESTÁTICO de importaciones (no `importlib` por ruta ni `subprocess`); `become_user` de Ansible y reinicio de máquina → RC-E2E. Deudas: TD-H06-01 (propuesta de backup como root, reducida), TD-H06-02 **cerrada** (bóveda = EXTERNAL OPERATOR CONTENT; ronda 2: sin apropiación), TD-H06-03 **cerrada**, TD-H06-04 (ACL). Deuda declarada en la ronda 2 (sin carril): secretos no validados al arrancar (P3); `.migrando-*` huérfano tras SIGKILL al crear el temporal; restore de backup sin guion; Ansible `become_user`; E2E en subproceso heredan la excepción de tests; y las cuatro preexistentes (AUTH_ORDER_FLAKY, handwritten 19/19b, 3 `test_f2` desde el cwd `viewer/`, B3 M1 por tiempos).
- **Deuda del cierre (sin carril):** D-1 (P2) `state_runtime` puede dar un UNHEALTHY falso si un sidecar de SQLite (`-wal`/`-shm`) desaparece entre el listado y el `stat` (reproducido por simulación; la unidad del timer quedaría `failed` en esa pasada, sin reinicios ni bloqueo de despliegues); D-2 (P3) la declaración de «no medible» no se rechaza en `viewer.env` ni en el entorno efectivo del visor; D-3 (P3) `state_runtime` recorre el state root en cada consulta del panel; `os.access` puede colgarse en un NFS caído o ser optimista con inmutable/FUSE (P3); el gate D6 compara solo major.minor del mínimo de Python (P3); `refuse_root_state_write` es defensa en profundidad; el gate de unidad no lee drop-ins (lo para el paso 14a).
- **Dependencias incluidas en #285 (ajenas al hito):** `pip-audit` salió rojo por avisos del 13–14 de noviembre; lock del motor con `nltk` 3.10.4 y `soupsieve` 4.0, excepción `GHSA-8mgp-746c-j5xp` retirada de `supply-chain.yml`, y `preflight.sh` exige Python ≥ 3.11.5.
- **Precondiciones del primer upgrade de producción:** (1) Python **≥ 3.12** en el host (el lock del motor exige ≥ 3.12 por numpy 2.5.1; producción, laboratorio y CI usan la serie 3.13; el preflight lo comprueba desde #288); (2) `S9K_PUBLIC_BASE_URL` válida (H-05 B); (3) `<state>/backups` sin contenido y `S9K_BACKUP_ROOT`/`S9K_BACKUP_DIR` fuera del state root (los backups viven en `/var/backups/s9-knowledge`; mientras sigan dentro, `state_runtime` dará UNHEALTHY verdadero); (4) state root dedicado; (5) estado legacy en un solo sitio o idéntico; (6) sin `S9K_STATE_VALIDATION`/`S9K_STATE_ENFORCE` en entornos, unidades ni drop-ins; (7) permisos de la bóveda externa preparados por el administrador.
- **CORRECCIÓN (2026-11-20, RC-E2E 1): dos afirmaciones de esta ficha resultaron FALSAS.** (a) La frase, tal como se escribió en #285/#284, de que las precondiciones del primer upgrade «las comprueba `deploy.sh`/`preflight.sh` y paran sin tocar nada» era **falsa** para la mayoría: antes de #290 la URL pública, `worker.env`, los secretos y el almacén de revisión se validaban **después** de parar los servicios y migrar el estado (RC1-03, RC1-04, RC1-05: visor y worker quedaban parados). Sólo las variables de `CRITICAL_ENV_VARS` paraban en 2b con el servicio vivo. Corregido en #290 (bloque 2c y decisión antes de parar), **no verificado por efecto contra systemd real**. (b) La precondición «Python ≥ 3.11.5» (y la mención de `preflight.sh` en «Dependencias incluidas en #285») era **falsa**: la exigencia real es **≥ 3.12**; el preflight la comprueba desde #288.
- **RC-E2E 1 (diagnóstica) — qué EJERCIÓ de este hito y qué sigue pendiente:** ejercido en el laboratorio sobre `b4e396d`: identidad y permisos del servicio, secretos y ACL (E4, 30/0 y escenario D 32/0), migración de una legacy sintética (E2, con identidad, filas y sha preservados), bóveda externa (escenario H, 58 comprobaciones) y healthcheck real (E6). **Falló:** RC1-G01 (el worker no podía leer el secreto `0640` que este hito deja: P1, corregido en #288), RC1-06 (parada falsa con un servicio en bucle: P1, #290) y RC1-03/04/05. **Sigue pendiente (RC-E2E final):** parada contra systemd real con el código corregido, lectura del secreto por el worker contra Neo4j, healthcheck UNMEASURABLE desde el sandbox y reinicio de máquina con el código final. **No cambia a VERIFIED de RC.**

### RC-E2E 1 (diagnóstica)

- **Estado:** **EJECUTADA, con fallos** (2026-11-18/19). **No** es VERIFIED de RC para ningún hito: fue diagnóstica; la que puede cerrar es la RC-E2E final. Detalle completo, tabla de los 14 escenarios y evidencia resumida en [`docs/93-rc-e2e-1-resultados.md`](93-rc-e2e-1-resultados.md).
- **Sujeto:** `b4e396d` (`main` tras #285 y #286), sin modificar durante la prueba. **Entorno:** laboratorio de una sola máquina restaurada a disco limpio (Debian 13, Python 3.13.5, 4 vCPU, 4,9 GB, sin swap), TLS y nginx con CA propia, Neo4j 5.26 **Community** sólo para el bloque de grafo; sin Ansible, sin navegador. Producción sin tocar.
- **Resultado:** E4, E5 y E14 PASS automáticos (sin navegador); E1, E2, E3, E6, E7, E8, E9, E10, E11, E12 y E13 **PARCIAL**. E8 y E9 con un FAIL real del producto (RC1-G01). Lo dependiente de la cuenta de sólo lectura del worker quedó **PENDING por edición** (Community): el operador no aceptó la licencia de evaluación de Enterprise.
- **Hallazgos → corrección (todo MERGEADO, #291 incluido; ninguno verificado por efecto):**

| Hallazgo | Sev. | PR → SHA |
|---|---|---|
| RC1-G01 (= H-L01) el worker no lee el secreto `root:s9knowledge 0640` | **P1** | #288 → `7982f6d` |
| RC1-06 la «parada verificada» da por parado un servicio en bucle de reinicios | **P1** | #290 → `31935e6` (`lib.sh::parar_y_verificar_servicios`: `stop` siempre sobre cada unidad existente y 3 lecturas seguidas inactive/failed sin PID) |
| RC1-03, RC1-04, RC1-05 validación de configuración, almacén y BLOCK de estado después de parar y migrar | P2 | #290 → `31935e6` (paso 2c de `deploy.sh`; `exigir_decision_de_estado` antes de parar) |
| RC1-G03 (= H-L02) `preflight_ensayo_rc` exige 0600 donde el despliegue deja 0640 | P2 | #288 → `7982f6d` (política única `service_state.inspect_secret_for_reading`: propio `0600` o `root:s9knowledge` `0640`) |
| RC1-G02 mensaje que atribuye mal la causa; `error_code` vacío (código nuevo `GRAPH_CREDENTIAL_UNUSABLE`, permanente, con la ruta y el motivo y `error_code` coherente) | P2 | #291 → `864041d` |
| D-1, D-4 (deudas de salud, no salieron de la RC) | — | #287 → `bb7f3c9` |
| D-2 (declaración «no medible» sólo legítima en la unidad del healthcheck con sandbox), D-6 (el gate de intérprete compara la tupla completa contra el `Requires-Python` de los locks; `PY_MINIMO="3.12.0"` en el preflight), D-8 (restos `.migrando-*`: se retiran sólo si se demuestra que son propios y redundantes, o STOP `RESTO_DE_MIGRACION`) | #288 → `7982f6d` |
| RC1-01, RC1-02, RC1-G04 y los H-L de lectura | P3 | abiertos; RC1-02 (`deploy/README.md`, CA bajo verificación X.509 estricta) y RC1-G04 (`docs/91`, intérprete del venv de la release) documentados en #291 → `864041d`; `arbol.declarado` PENDIENTE sin `S9K_ENSAYO_COMMIT` en la plantilla de producción sigue abierto |

- **Verificación de las correcciones:** cada PR 34/34 check-runs (17 required) y revisión independiente APTO CON OBSERVACIONES; en laboratorio, calibrador H-06/H-08 completo 90/90 e inventario de suites confirmado con la herramienta. **No verificado todavía por efecto:** parada contra systemd real con el código corregido, lectura del secreto `0640` por el worker de extremo a extremo contra Neo4j, todo lo de navegador.
- **Infraestructura:** desde #289 (`e2063bc`) la CI corre en runners de GitHub (`ubuntu-latest`); el runner propio queda apagado y registrado como respaldo.
- **Deuda nueva (P3):** la ruta del fichero de credencial aparece en el `error_message` del job (decidir qué roles la ven); `set_status` sin mensaje conserva el error previo; un `ESTALE` permanente se etiqueta como indisponibilidad; ningún gate vigila que un calibrador siga cableado en CI; el despliegue tarda ~8 s más por la verificación de parada; `push` y `pull_request` duplican los jobs de CI (cuota).
- **Entorno (no son defectos del producto):** presión intermitente del hipervisor con bloqueos breves de CPU en una máquina de producción vecina coincidentes con E/S de laboratorio o de CI (causalidad no demostrada); la imagen de Neo4j Community envía telemetría en su primer arranque si no se desactiva.
- **Laboratorio para la RC final:** restaurado a una base limpia preparada (sin producto), con Neo4j 5.26 **Enterprise** con licencia de evaluación aceptada por el operador; sujeto de la RC final `864041d`.
- **Criterio de cierre de la RC-E2E final:** los puntos de `docs/93` §8, con evidencia por efecto, en máquina limpia, con navegador y con el código que se va a desplegar.

### RC-E2E final (segunda ronda)

- **Estado:** **EJECUTADA — NO VERIFIED** (2026-11-20). La revisión adversarial independiente dio **NO APTO**. No es VERIFIED de RC para ningún hito, ni siquiera VERIFIED de laboratorio para la RC en su conjunto: sólo hay puntos concretos demostrados por efecto. Detalle, tabla de los 14 escenarios y de las 17 regresiones en [`docs/94-rc-e2e-final-resultados.md`](94-rc-e2e-final-resultados.md).
- **Sujeto:** `864041d` (`main` tras #287, #288, #290 y #291), sin modificar durante la prueba. **Entorno:** el mismo laboratorio de una sola máquina, restaurado a base limpia (Debian 13.7, Python 3.13.5, 4 vCPU, 4923 MB sin swap), TLS y nginx con CA propia, Neo4j `5.26-enterprise` con licencia de evaluación aceptada por el operador; sin Ansible, sin navegador, legacy sintética. Producción sin tocar.
- **PR integrados desde el sujeto de la RC-1 (`b4e396d`):** #289 `e2063bc`, #287 `bb7f3c9`, #288 `7982f6d`, #290 `31935e6`, #291 `864041d` (sujeto) y #292 `007790e` (documentación de la RC-1, posterior al sujeto y sin código).
- **Resultado:** E3, E4, E9, E12 y E14 PASS por efecto en lo automatizable (sin navegador); E1, E2, E5, E6, E7, E8, E10, E11 y E13 **PARCIAL** (numeración del informe de la RC final; equivalencia con el contrato en `docs/94` §4). Ningún escenario se cierra como PASS completo.
- **Demostrado por efecto en el laboratorio:** el worker real lee el secreto `root:s9knowledge 0640` y autentica; `GRAPH_CREDENTIAL_UNUSABLE` con `error_code`; job recuperado sin `error_code` rancio; STOP y BLOCK antes de parar, con los mismos PID; SIGKILL durante la migración converge; la cuenta de sólo lectura del worker recibe `Forbidden` al escribir; reinicio de la máquina al primer intento; RC1-06 con systemd real (medida corta, 30 s). Los dos P1 de la RC-1 (RC1-G01, RC1-06) quedan corregidos por efecto en el laboratorio.
- **No cumplido o no ejecutado:** regresión 1 en su mitad de CLI (`writer-schema verify` rc 2), regresión 9, regresión 13, regresión 15 (navegador); grafo restaurado de E11 sin verificar; aislamiento 8.M9, N8, N10, N11 y varios pasos HTTP sin ejecutar; las decisiones de E8 se enviaron con una sonda HTTP defectuosa; relaciones añadidas 0 en E8 (sellado bajo presión del hipervisor, sin repetir).
- **Hallazgos abiertos (ninguna corrección mergeada):**

| Hallazgo | Sev. | PR |
|---|---|---|
| RC2-01 (reaparición de RC1-01) `preflight.sh` bloquea una máquina limpia | P3 | #293, **draft** |
| RC2-02 (nuevo) `writer-schema verify` por el camino canónico no puede dar rc 0 con el rol de sólo lectura documentado | P3 | sin PR; decisión pendiente (ampliar el rol o documentar que `verify` usa la cuenta del writer) |
| RC2-03 (reaparición de RC1-G04) `preflight_ensayo_rc` no carga el catálogo ni con el intérprete de la release; la corrección de #291 fue documental | P3 | #293, **draft** |
| RC2-04 (nuevo) `fuentes.pobladas` mide el catálogo plano e ignora la raíz de bóvedas (rojo falso) | P3 | #293, **draft** |
| Estabilidad del mutante M1 del calibrador B3 y hallazgos de E8 | — | rama aparte, **sin PR todavía** |

- **Entorno (no es defecto del producto) — incidente RC2-E3:** 4 de 5 episodios de presión del hipervisor empezaron a los pocos minutos de un arranque de Neo4j en el laboratorio; el último coincidió con 2 soft lockups en otra máquina del mismo hipervisor. **Correlación, no causalidad demostrada.** Consecuencia: no se vuelve a arrancar Neo4j en el laboratorio sin decisión del operador.
- **Lo que queda para una tercera ronda** (con las correcciones mergeadas y sobre el `main` resultante): regresiones 1 (CLI), 9, 13 y 15; E8 de extremo a extremo con sonda correcta o navegador, sellado en calma con relaciones y aislamiento 8.M9; verificación del grafo restaurado de E11; N8, N10, N11, inactividad de sesión, web de la bóveda, tope de 5 s del sondeo de bóveda y un Python anterior a 3.12 real; y las decisiones del operador (Neo4j en el laboratorio, navegador, Ansible, copia de producción como legacy). Lista completa en `docs/94` §10.

## 8. Reglas del programa (vigentes para todo carril)

- **PRE-PUSH CALIBRATION RULE.** Si el diff modifica un símbolo vigilado, un fichero vigilado, una
  estructura usada como ancla o una propiedad cubierta por un calibrador, el implementador debe:
  (1) identificar los calibradores afectados; (2) ejecutarlos localmente; (3) demostrar que siguen
  calibrados; (4) registrar resultado y RC en la entrega (tabla «fichero tocado → calibrador → N/N → rc»).
  No basta con tests verdes, suite verde ni calibradores nuevos verdes. El organizador contrasta la
  tabla antes de llamar al revisor.
- **DETECTOR ROTO ≠ DEFECTO DE PRODUCTO.** Una regresión plausible que los testigos no detectan se
  corrige en tests/calibrador/inventario con 0 líneas de producto; el organizador verifica ese cero.
- **Demostrado / Techo independiente.** Al cerrar un hito se separan ambos; un techo de integración
  (RC, Neo4j real, systemd real) no degrada la garantía medida ni se convierte en DONE.
- **CI:** dos runs sobre el mismo SHA no se cancelan; se cuentan conclusiones por SHA; merge solo con
  17/17 required `pass` + `CLEAN` + revisor APTO.

## 9. Insumos para la Fase C (análisis READ-ONLY del 2026-10-15/19, sin código)

- **PRE-C (H-04 + H-18):** PARTIAL_OVERLAP. Misma raíz (default silencioso en el árbol y tres
  derivaciones de la ruta de `review.sqlite3`: visor `default_database_path`, motor
  `default_decisions_db`, preflight «esperada»); remedios distintos. Hallazgos nuevos: **falso verde del
  preflight en upgrade con ruta nueva bajo el state root** («APTO: el estado sobrevive» mientras las
  decisiones quedan huérfanas y el visor crea una BD vacía); `VAR=""` pasa `validate_viewer_env`;
  `.env` ignorado por el default (clase H-50); `decisions.jsonl`/`audit.jsonl` siguen dentro de la
  release. Unidad de control propuesta: «todo almacén de estado humano se resuelve por una única
  función compartida por visor, motor y preflight; distingue no-configurado / vacío / inexistente /
  existente; en producción falla cerrado ante todo lo que no sea existente o creación autorizada en
  primera instalación». Recomendación: **un carril C1** tras B3; investigación previa (PRE-C1) sobre la
  señal fresh/upgrade que gobierne la creación de la BD sin heredar O1; si no hay señal fiable, C-a
  (motor fail-closed + gates) y C-b (creación condicionada del visor). Cambia el contrato del test
  `test_v3_decision_efectiva.py::test_sin_almacen_el_motor_se_comporta_como_siempre`.
- **H-05 (Host):** reproducido; además del 303, 35 `url_for` en 10 plantillas emiten URLs absolutas
  gobernadas por `Host`. Cambio mínimo A (Location relativo en `_fallo`/`_vuelta`/1201 de
  `chassis_operations.py`) + B (`TrustedHostMiddleware` derivado de `S9K_PUBLIC_BASE_URL` por la
  autoridad efectiva, sin variable nueva). Calibradores afectados: `calibrar_panel_operations` (B15),
  `f2_autoridad_workspace` (firma de `_fallo`). Carril propio.
  **Corte A (Location relativo): MERGED** (#281 → `11b67d1`) · **VERIFIED (arnés local), RC-E2E
  PENDING**. Los 3 `url_for` de
  `chassis_operations.py` pasan a `request.app.url_path_for` (path + query); tests
  `test_h05a_location_relativo.py` (4 rutas × fallo/éxito × Host hostil con y sin puerto,
  seguimiento de la redirección, control positivo, censo AST); calibrador
  `mutaciones_h05a_location.py` 5/5 en el job required «Calibracion de gates».
  **Techo explícito: siguen ABIERTAS** las 35 URLs absolutas de plantillas (`action=`/`href=` con
  el `Host` del cliente) y la ausencia de `TrustedHostMiddleware` = **corte B**, pendiente de
  decisiones del operador; `root_path` no cubierto (el visor no se monta bajo prefijo).
  **Revisión independiente de A: APTO CON OBSERVACIONES.** O1: el `redirect_slashes` de Starlette
  emite 307 con el `Host` del cliente en 22 rutas (ya en main; lo cierra el corte B con el 400;
  techo de A). O2: `url_path_for` no antepone `root_path` → regresión aceptada (el visor no se
  monta bajo prefijo). O3: query sin urlencode en `trabajo`/`job_id`/`codigo` (preexistente,
  rango 3). O4: el chequeo «MENSAJE contiene evil.example» del calibrador es poco discriminante y
  el censo AST no ve alias (deuda).
  **Corte B (autoridad única de host público + frontera de host 400): MERGED** (#283 →
  `4f186fd`) · **VERIFIED (arnés local), RC-E2E PENDING**. Cadena única `S9K_PUBLIC_BASE_URL` (leída por `effective_env_value`, **sin variable
  nueva**) → hostname canónico → hosts de confianza, en `viewer/app/public_endpoint.py`
  (`interpretar_url_publica`, `resolve_public_endpoint`, `resolve_trusted_hosts`; sólo stdlib). El visor
  registra `PublicHostMiddleware` el último (= más externo, antes de Auth, rutas, almacenes y
  `redirect_slashes`): Host no declarado → **400**; sin URL válida → el arranque aborta (y cada petición
  da 503, nunca «permitir todo»). Lista = hostname público + `localhost` + `127.0.0.1` + `::1`; sin
  comodín, sin autodetección; placeholder `cambiar.por.el.nombre.real` rechazado aunque sea URL válida.
  `testserver` sólo por la costura de tests `HOSTS_EXTRA_DE_PRUEBAS` (vacía en producción). **No se usa
  `TrustedHostMiddleware` de Starlette** (medido en 1.3.1 y 1.10.0: `[::1]:8088` → host `[` y punto final
  rechazado; en 1.3.1 además distingue casing; `*` por defecto). Despliegue: `preflight_https`, `preflight_setup_admin` y
  `validate_deploy.sh::validate_https_contract` cargan la MISMA interpretación (por ruta) y bloquean
  antes de declarar la instalación completa. Cierra **O1** de la revisión de A (307 de `redirect_slashes`
  con Host del cliente: ahora 400). Tests `test_h05b_trusted_host.py` (190) +
  `deploy/tests/test_h05b_endpoint_publico_despliegue.py` (19); calibrador
  `mutaciones_h05b_trusted_host.py` 9/9 (M9 = guarda ASCII, `ß`→`ss`) en «Calibracion de gates»; gate AST de unicidad.
  **Techo B:** gate AST sólo sobre `viewer/app` (ciego a `Settings` pydantic paralelas con otro nombre
  de campo, `URL(...).hostname` de Starlette, `split` manual, nombres concatenados,
  `socket.gethostname()` e IP LAN hardcodeada, aliasing dinámico; `deploy/` y `scripts/` no
  vigilados; lo cubren el comportamiento y el calibrador M1–M9); frontera sobre la cabecera `Host` (detrás de un proxy que la reescriba manda el valor
  reescrito); `root_path` y las 35 URLs absolutas de plantillas siguen abiertos (con Host validado ya no
  los gobierna el cliente); O3 (query sin urlencode) y O4 (precisión del calibrador A) = deuda.
  **Deuda de despliegue:** una instalación existente sin `S9K_PUBLIC_BASE_URL` declarada (o con el
  placeholder) deja de arrancar: declararla ANTES de desplegar B. Hosts adicionales = corte futuro.
  Inventario de ejemplos de URL pública (clasificados): `deploy/config/viewer.env.example:109`
  placeholder (rechazado) · `.env.example:15` vacío = ausente (rechazado, comentario añadido) ·
  `viewer.env.example:117` y `lib.sh`/`runner.py` `http://127.0.0.1:8088` = loopback (permitido, otro
  concepto) · Ansible `s9k_public_host` (`inventory.example`, `roles/tls`) = origen de
  `s9k_public_base_url` (misma cadena, no segunda autoridad) · `deploy/README.md:309`
  `knowledge.example.net` = ejemplo válido · `README.md:235` `knowledge.seccionnueve.duckdns.org` =
  documentación del despliegue real (no tocada) · `.env.example:14` `S9K_LOCAL_BASE_URL` = obsoleta
  (H-42, 0 usos) · tests: `public.example`, `knowledge.tests.example`, `perf-lab.example` = fixtures.
- **RC-E2E 1 (diagnóstica) — ejercido / pendiente de H-05:** ejercido: `Host` hostil → 400 con la URL pública declarada y nginx con `proxy_set_header Host $host` (E6), y los negativos de URL pública ausente o `http://` (RC1-03: la causa se nombraba bien, pero el STOP llegaba tras parar; corregido en #290, sin verificar por efecto). **Pendiente:** navegador; las 35 URLs absolutas de plantillas siguen abiertas como techo. No cierra el RC-E2E de H-05.
- **H-06 (auth.db 0644):** reproducido (auth.db, lock, bak, `jobs.db*`, `review.sqlite3` en 0644;
  solo `.csrf_secret` 0600). Autoridad única: `UMask=0077` en las dos unidades del visor (como el
  healthcheck y el worker de B3) + `chmod` puntual en Ansible; `chmod` en código no cubre WAL/SHM.
  **No desplegable con el visor como root** → junto con H-08.

## 7. Registro de cambios del plan

| Fecha | Cambio | Evidencia |
|---|---|---|
| 2026-10-11 | Creación del plan canónico a partir de la auditoría R1+R2 | `docs/audits/AUDITORIA_GLOBAL_S9_KNOWLEDGE_2026-10-10.md` (R2.11, R2.16) |
| 2026-10-11 | Fase A cerrada (#268 → `8964c36`); B1/H-03 VERIFIED (#269 → `2dd6d47`); R1 abiertos 3 → 2; CURRENT_HIT → B2 | PR #268, PR #269, log CI run `38127086116` y runs sobre `1ce168b` (34/34 pass) |
| 2026-10-11 | B2 abierto (#271): H-01/H-43/H-44/H-49 implementados y calibrados; H-04/H-18 solo lado deploy; contenido de #267 absorbido; P5 → CI_GATED; RC-E2E PENDING | PR #271 |
| 2026-10-12 | B2 cerrado (#271 → `751995c`): H-01/H-43/H-44/H-49/H-35 VERIFIED (arnés local), H-04/H-18 solo lado deploy; RC-E2E PENDING; R1 abiertos 2 → 1; CURRENT_HIT → B3 | PR #271 (HEAD `97f864c`, 3 rondas de revisión independiente), CI 17×2 pass |
| 2026-10-19 | B3 cerrado (#273 → `70b823a`): H-02 VERIFIED (arnés local), H-37 VERIFIED, RC-E2E PENDING; **R1 abiertos 1 → 0**; CURRENT_PHASE → C; PR #267 cerrado (absorbido en #271); reglas del programa (§8) e insumos de Fase C (§9) | PR #273 (HEAD `76d6da4`, 4 rondas de revisión), CI 17×2 pass; PRE-C, H-05/H-06 read-only |
| 2026-10-26 | Infraestructura: CI migrada a COMMONS-CI (el runner propio) por #276/#278 (pip-audit) y #277 → **MAIN_CI_MIGRATED_SHA = `d35f863`**; 16 jobs self-hosted, `Data Engine Tests` sigue en `ubuntu-latest` (PENDING_RESOURCE_FIT por OOM medido); 17 contextos required sin cambios; calibradores de CI re-anclados a identidad `id+name`; deuda documentada en `docs/ci/MIGRACION_COMMONS_CI.md` §11; ~17 h de CI por SHA en serie | PR #277 (revisión OPUS independiente: P1 shellcheck corregido en `6edf0fe`), `docs/ci/MIGRACION_COMMONS_CI.md` |
| 2026-10-27 | C1 abierto (draft): H-04 + H-18 como unidad; `review.sqlite3` lo crea el despliegue y el runtime lo consume y verifica; resolución única en `review_paths`; calibrador 18/18; RC-E2E PENDING | PR C1 (draft, rama `feat/c1-persistencia-decisiones-revision`) |
| 2026-10-29 | C1 · cierre del P1-2 (URI sin escapar → el runtime creaba otro fichero): `sqlite_uri` única + N19 en despliegue y runtime; D9 cerrado (N3 estructural, 14 rutas, POST con CSRF válido; Apply nombra el almacén); README con la receta de inspección/propietario/modo del primer upgrade; calibrador 23/23; sigue draft, RC-E2E PENDING | PR #279 (draft) |
| 2026-11-01 | **C1 CERRADO** (#279 → `2cf2361`): H-04/H-18 → VERIFIED (arnés local), RC-E2E PENDING; deploy única autoridad de creación (fresh crea y verifica; upgrade preserva; autorización explícita no sobrescribe), runtime nunca crea y falla cerrado con causa, `review_paths` + `sqlite_uri` únicas, N1–N19, calibrador 23/23, N3 estructural 14 rutas; revisión independiente: NO APTO (P1-1) → NO APTO (P1-2) → APTO CON OBSERVACIONES; deuda D1–D4, D6–D8, D10–D11; CURRENT_HIT → PRE-H05 | PR #279 (34/34, 17/17 required), `docs/PLAN_USABLE_V1.md` §5 C1 |
| 2026-11-11 | **H-05 CERRADO**: corte A (#281 → `11b67d1`, `Location` relativo en `/panel/operations`) y corte B (#283 → `4f186fd`, autoridad única `S9K_PUBLIC_BASE_URL` → `PublicHostMiddleware` 400, arranque fail-closed, sin comodín ni autodetección, `testserver` solo en tests, N1–N19, calibrador 9/9); revisión independiente de B: NO APTO (H1: `casefold` plegaba `ß`→`ss`) → corregido → APTO CON OBSERVACIONES; VERIFIED (arnés local), RC-E2E PENDING. **Aviso de despliegue:** con B el visor no arranca sin `S9K_PUBLIC_BASE_URL` válida (tampoco en lab ni con el placeholder); receta en `deploy/README.md`. Infraestructura: el runner de COMMONS-CI se autoactualizó (2.338.0 → 2.338.2) y el hook lo trató como residuo; corregido fuera del repo. Flakies conocidos relanzados por firma: Authz id físico, Viewer «portal is not running», B3 MF por tiempos, `test_caso_de_fabrica_248…` (uvicorn). CURRENT_HIT → PRE-H06/H08 | PR #281, PR #283 (34/34, 17/17 required en el SHA final), PR #282 |
| 2026-10-12 | B3 abierto (#273): H-02 VERIFIED (arnés local), H-37 VERIFIED (arnés local); unidad canónica del worker instalada por `deploy.sh`; calibrador 25/25 tras dos rondas de corrección (NO APTO → F1–F9; APTO CON OBSERVACIONES → ronda final); RC-E2E PENDING | PR #273 |
| 2026-11-11 | H-06 + H-08 implementados en local (sin publicar): usuario de sistema `s9knowledge` para visor, worker y healthcheck; autoridad única `service_state.py`; estado `0700`/`0600` fuera de la release; migración automática con parada verificada, hash y STOP; CLI de auth rechaza root; unidad única del visor; calibrador M1–M12; fresh/upgrade reales en el laboratorio PENDING, RC-E2E PENDING | rama `feat/h06-h08-service-user-state-permissions`; `deploy/README.md` «Usuario de servicio dedicado y estado privado» |
| 2026-11-01 | H-05 corte A abierto (draft): `Location` relativo en las redirecciones de `/panel/operations` (3 sitios de `chassis_operations.py`); tests + calibrador 5/5; techo: 35 URLs absolutas de plantillas y TrustedHost (corte B) abiertos | PR draft `feat/h05a-location-relativo`; informe PRE-H05 |
| 2026-11-01 | H-05 corte B implementado en local (sin publicar): autoridad única `S9K_PUBLIC_BASE_URL` → hostname → hosts de confianza, `PublicHostMiddleware` (400) más externo, arranque fail-closed, preflight/deploy con la misma interpretación; tests 190+19, calibrador 9/9, gate AST de unicidad; techo: aliasing dinámico, proxy que reescribe Host, `root_path`, 35 URLs de plantillas | rama `feat/h05b-trusted-host` (sobre `feat/h05a-location-relativo`) |
| 2026-11-12 | H-06 + H-08 **ronda 2** (tras revisión NO APTO): H-1 (guarda canónica de root `reject_root_cli` en toda CLI que alcanza estado, gate estructural, escritores que rechazan root bajo el state root, modos exactos de la autoridad con cualquier umask, envoltorio `s9k-cli.sh`), H-2 (bóveda: reemplazo atómico conservando modo/grupo o escritura en el sitio con respaldo y restauración; sin apropiación), C-1…C-7 y testigos R2/R3/R8/R10/R12/R13/R14; calibrador M1–M45; laboratorio repetido; sin push, RC-E2E PENDING | rama `feat/h06-h08-service-user-state-permissions`; `deploy/README.md` «Usuario de servicio dedicado y estado privado» |
| 2026-11-12 | H-06 + H-08 **ronda 2b** (revisión acotada NO APTO por H-R2-1): respaldo de la bóveda publicado atómicamente y con la identidad de la operación (original/nuevo + sha); nunca se restaura a ciegas (edición del operador o respaldo no fiable → 409); `lost+found` de un FS dedicado admitido con sus atributos exactos; testigos X2/X3/X4/X6 y «restauración a ciegas» (calibrador M1–M51); sin push, RC-E2E PENDING | rama `feat/h06-h08-service-user-state-permissions` |
| 2026-11-12 | H-06 + H-08 revisión acotada de la ronda 2b: APTO CON OBSERVACIONES; cerrados los P2 H-R2b-1 (un corte durante la restauración del respaldo se reintenta) y los testigos Y1/Y2/Y3 (M52–M55, calibrador M1–M55); P3 documentados; sin push, RC-E2E PENDING | rama `feat/h06-h08-service-user-state-permissions` |
| 2026-11-15 | H-06 + H-08 PR #285 (draft): tres checks required en verde (SC2034 con shellcheck 0.11.0; el censo y la espec de escritura declaran la excepción de estado de tests; los calibradores copian la autoridad de estado) y **criterios del operador para la bóveda externa** (1–8 + documentación: componente de salud `vault`, state root borrado/restaurado sin tocar la bóveda, el backup no la contiene, responsabilidad del administrador); calibrador M1–M60; sin push, RC-E2E PENDING | PR #285; `deploy/README.md` «Bóveda externa: responsabilidad del administrador» |
| 2026-11-17 | **H-06 + H-08 CERRADO** (#285 → `f7057b7`): usuario de sistema `s9knowledge`, estado privado `0700`/`0600`, migración automática con STOP, bóveda como contenido externo del operador y semántica de salud STATE_VALIDATION / STATE_RUNTIME / VAULT_HEALTH (con UNMEASURABLE desde el sandbox del healthcheck, B-1) → **VERIFIED (arnés local + laboratorio), RC-E2E PENDING**; el mismo PR incluye el arreglo de dependencias que exigía `pip-audit` (`nltk` 3.10.4, `soupsieve` 4.0, preflight Python ≥ 3.11.5); CURRENT_HIT → resto de Fase C | PR #285 (HEAD `44c35ac`; 34/34 check-runs, 17/17 required; revisión independiente APTO CON OBSERVACIONES y APTO del delta de dependencias) |
| 2026-11-20 | **RC-E2E 1 (diagnóstica) documentada** (sujeto `b4e396d`, 2026-11-18/19): 14 escenarios (3 PASS automáticos, 11 PARCIAL, ninguno completo; sin navegador, Neo4j Community, sin Ansible); 2 P1 (RC1-G01 secreto 0640 ilegible para el worker, RC1-06 parada falsa de un servicio en bucle) y 4 P2 reproducidos; **ninguna corrección verificada por efecto**; producción sin tocar | `docs/93-rc-e2e-1-resultados.md` |
| 2026-11-20 | Correcciones tras la RC-E2E 1 mergeadas: #289 `e2063bc` (CI en `ubuntu-latest`), #287 `bb7f3c9` (D-1, D-4), #288 `7982f6d` (RC1-G01, RC1-G03, D-2, D-6, D-8), #290 `31935e6` (RC1-03/04/05/06); #291 `864041d` (RC1-G02 y documentación de RC1-02/RC1-G04; contrastado con el contenido real de `main`); cada PR 34/34 check-runs (17 required) y revisión APTO CON OBSERVACIONES; CURRENT_HIT → RC-E2E final | PR #287, #288, #289, #290, #291 |
| 2026-11-20 | **Corrección de dos afirmaciones falsas de la ficha H-06 + H-08:** (a) las precondiciones del primer upgrade NO paraban «sin tocar nada» (se validaban tras parar y migrar hasta #290); (b) la precondición de Python es **≥ 3.12**, no ≥ 3.11.5 (las filas del 2026-11-17 que citan 3.11.5 quedan como historia, corregidas por esta) | RC1-03/04/05, `docs/93-rc-e2e-1-resultados.md` §5 |
| 2026-11-20 | **RC-E2E final (segunda ronda) documentada: NO VERIFIED** (sujeto `864041d`; revisión adversarial independiente NO APTO): 14 escenarios (5 PASS por efecto en lo automatizable, 9 PARCIAL, ninguno completo; Neo4j 5.26 Enterprise, sin navegador, sin Ansible); RC1-G01 y RC1-06 corregidos por efecto en el laboratorio; regresiones 1 (CLI), 9, 13 y 15 no cumplidas o no ejecutadas; hallazgos RC2-01 a RC2-04 (P3) abiertos, #293 en draft sin mergear; incidente de entorno RC2-E3 (correlación, no causalidad): Neo4j no se vuelve a arrancar en el laboratorio sin decisión del operador; producción sin tocar; CURRENT_HIT → correcciones y tercera ronda | `docs/94-rc-e2e-final-resultados.md` |
