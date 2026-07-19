# Programa multiagente RC6+ — Coordinación

Este directorio contiene los artefactos de coordinación del programa de desarrollo
posterior a la integración de RC6. **No** es documentación de estado productivo ni
histórica: coordina el trabajo paralelo de varios equipos en ramas separadas.

## Principios

1. **RC6 se cierra sobre lo YA integrado en `main`** (`6d6c21f`). No se le añaden
   funciones nuevas. Ver [pre-rc6-audit.md](pre-rc6-audit.md).
2. Las capacidades nuevas (motor de relaciones, multimedia, export/import,
   seguridad de dependencias, observabilidad) se desarrollan en **ramas
   separadas**, nunca dentro de RC6.
3. **Nada toca producción.** RC5.1 sigue activa; Neo4j 199/140; `S9K_ALLOW_REAL_INGEST`
   off; RC6 no creada; primera ingesta no autorizada.
4. Cada equipo trabaja en un **worktree exclusivo**. No se comparten worktrees.
5. Las **áreas compartidas** (contracts/, main.py, deps, workflows, project-status)
   solo las modifica el Organizador vía PR de integración. Ver
   [ownership-map.md](ownership-map.md).
6. **Extender, no duplicar.** Ya existe scaffolding relevante (external_ai,
   external_processing/nvidia, media/transcriber, review_export_import). Ver
   [ownership-map.md](ownership-map.md#scaffolding-existente).

## Documentos

| Documento | Propósito |
|-----------|-----------|
| [program-board.md](program-board.md) | Tablero de ejecución (tareas, estados, gates) |
| [ownership-map.md](ownership-map.md) | Propiedad de ficheros por equipo + áreas compartidas |
| [integration-order.md](integration-order.md) | Orden de PRs y dependencias entre carriles |
| [risk-register.md](risk-register.md) | Riesgos P0–P3 y mitigaciones |
| [quality-gates.md](quality-gates.md) | Gates obligatorios por entrega (2 revisiones) |
| [pre-rc6-audit.md](pre-rc6-audit.md) | Auditoría pre-RC6 del Equipo R (OLA 1) |
| [contract-proposals.md](contract-proposals.md) | Contratos internos propuestos (relaciones, export/import, multimedia) |
| [dependabot-analysis.md](dependabot-analysis.md) | Análisis de Dependabot + supply chain |
| [qa-matrix.md](qa-matrix.md) | Matriz de QA transversal (Equipo Q) |

## Roles

- **Organizador Principal**: administra tareas, ramas, worktrees, alcance,
  integración y las áreas compartidas.
- **Supervisor Técnico Independiente**: audita decisiones, revisa contratos y
  aislamiento, emite dictámenes (CONFORME / CON OBSERVACIONES / NO CONFORME /
  BLOQUEADO). No implementa funcionalidad principal.
- **Equipo R** (RC6 y validación), **Equipo A** (motor/relaciones/calidad),
  **Equipo B** (multimedia/export-import/plataforma), **Equipo Q** (QA transversal
  y seguridad).

## Estado de esta ejecución

OLA 1 iniciada. Sin merges. Sin RC6. Sin despliegue. Ver `program-board.md`.
