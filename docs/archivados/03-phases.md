# 03 · Fases

> **Estado vigente (2026-07-18):** producción en **RC5.1** (`deploy-v0.3.0-rc5.1`,
> `47bc314`), login propio del visor (Basic Auth retirada), healthcheck con timer
> horario, Neo4j 199/140, 0 ingestas. El estado autoritativo está en
> [02 · Estado actual](02-current-state.md) y [project-status.yaml](project-status.yaml).
> Este documento describe la **secuencia de fases**; para el estado real prevalece
> el canónico.

> Relacionado: IA externa NVIDIA en modo sombra (revisión/consenso/calibración) — ver [docs/42](42-external-ai-calibration-and-burst-processing.md). Nada externo escribe en Neo4j.

Resumen de fases del proyecto. Detalle vivo en `../ROADMAP.md`.

| Fase | Descripción | Estado |
|---|---|---|
| 0 | Motor de datos (extracción → Neo4j, schema 1.5.0, prompt 1.4.0) | HECHO |
| 1 | Orden y versionado (este repositorio Git) | EN CURSO |
| 2 | Fuentes externas (cola, audio, YouTube, web) | DISEÑADO / parcial |
| 3 | Acceso: usuarios, personajes, permisos | BASE IMPLEMENTADA |
| 4 | Visor web (solo lectura, filtros de visibilidad) | PENDIENTE |
| 5 | Panel de gestión (fuentes / usuarios / visibilidad) | PENDIENTE |
| 6 | Acceso externo controlado | PENDIENTE |

## Criterio de "hecho"

Una fase se considera HECHA cuando: el código compila, sus pruebas pasan, existe
documentación, y hay una prueba mínima reproducible. Nada se marca como resuelto
sin prueba real (ver `09-audit-before-work.md`).
