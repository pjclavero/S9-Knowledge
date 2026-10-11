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
| CURRENT_MAIN | `0cf977c3f7785e5f826417efc94971825782bd9d` |
| CURRENT_PHASE | **A** (auditoría + plan canónico) → B (cerrar rango 1) |
| CURRENT_HIT | B1 (H-03) |
| OPEN_R1 | H-01 (+H-43), H-02, H-03 |
| OPEN_R2_BLOQUEANTES | H-04/H-18, H-05, H-06, H-07, H-09, H-11/H-48, H-14, H-19, H-44, H-50 |
| CURRENT_PR | ninguno de programa (PR #267 abierto, PR-4 anterior al plan) |
| NEXT_TASK | B1: aislamiento por workspace en la revisión V3 |
| BLOCKERS | ninguno técnico; ensayo RC exige autorización del operador para VM110/VM111 |
| DEBT_PARKED | WORKTREE-HYGIENE (147 worktrees, 435 ramas, 3 stashes), DEPENDENCY-MAINTENANCE (7 Dependabot, #209 major), CI-CALIBRATION-PERFORMANCE (job de 77 min serial) |
| E2E_PENDING | P4, P5 (RC-E2E PENDING en #266/#267), P15 |
| RC_PENDING | guion N1–N12 de `deploy/README.md` nunca ejecutado |

## 2. Métrica de progreso (no se mide por número de PR)

| Métrica | Baseline (R2, `0cf977c`) | Actual | Delta |
|---|---|---|---|
| Rango 1 abiertos | 3 | 3 | 0 |
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
- **Criterio de cierre:** ensayo RC con nginx/systemd/CA en máquina limpia con acta.

### P5 — Bootstrap del primer administrador verificado
- **Hallazgos:** H-01 (parcial), H-06, H-35, H-44. **Autoridad:** `install_state`, `csrf_bootstrap`. **Dependencias:** P4.
- **Estado:** IN_PROGRESS · **PR/SHA:** #247 `a58e137`, #248 `bcd9e59`; **#267 abierto** (`e683274`, 34/34).
- **Calibrador:** #248 fuera de CI; PR-4 10/10 · **E2E/RC:** PENDING (N8–N12).
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
- **Hallazgos:** H-13. **Estado:** IN_PROGRESS (parcial en #248). **Criterio:** estado fuera del árbol de código por defecto; `docs/50` referenciada existe o se retira la referencia (H-53).

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
- **Estado:** NOT_STARTED.

### B2 — H-01/H-43 · Familia fresh install
- **Estados explícitos:** DEPLOY_OK → HTTPS_BOOTSTRAP_PATH_VERIFIED → FIRST_ADMIN_PENDING → FIRST_ADMIN_VERIFIED → INSTALLATION_COMPLETE.
- **Piezas existentes a extender (no duplicar):** `deploy.sh`, `detect_state.py` (`decision` vs `global_state`), `preflight_https.py`, `preflight_ensayo_rc.py`, PR #267, plantillas `viewer/.env.example` y `deploy/config/viewer.env.example` (H-44, H-49).
- **Criterio de cierre:** máquina limpia → `current` activo → `/setup/admin` alcanzable por HTTPS → GATE A y GATE B → reinicio → persistencia, sin pasos no documentados; `deploy.sh` respeta `decision`; upgrade con `jobs.db` vacía no bloquea.
- **Estado:** NOT_STARTED.

### B3 — H-02 · Worker desatendido
- **Cadena:** job → cola → consumer → loop → servicio → ejecución → resultado → error/retry → restart.
- **Criterio de cierre:** unidad de servicio canónica instalada por el despliegue; `--loop` real sin `rc=0` inmediato; stale/retry/cancel con tests; un job creado desde `/panel/operations` se procesa sin intervención manual; error observable en la web.
- **Estado:** NOT_STARTED.

## 7. Registro de cambios del plan

| Fecha | Cambio | Evidencia |
|---|---|---|
| 2026-10-11 | Creación del plan canónico a partir de la auditoría R1+R2 | `docs/audits/AUDITORIA_GLOBAL_S9_KNOWLEDGE_2026-10-10.md` (R2.11, R2.16) |
