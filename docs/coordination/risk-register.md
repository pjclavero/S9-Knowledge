# Registro de riesgos

Prioridades: **P0** (bloqueante: seguridad, pérdida de datos, fuga entre workspaces,
escritura no autorizada, producción) · **P1** · **P2** · **P3**.

| ID | P | Riesgo | Origen | Mitigación | Estado |
|----|---|--------|--------|------------|--------|
| RK-01 | P0 | Escritura accidental en Neo4j productivo | A/B ejecutando pipelines | `S9K_ALLOW_REAL_INGEST` off + gate APPLY multi-condición + cortafuegos de red (tests/support/prod_block) | Mitigado |
| RK-02 | P0 | Fuga entre workspaces por endpoint nuevo sin filtrar | B (export), A (relaciones) | Todo endpoint de datos usa `get_filtered_provider`; Q audita cada PR; regresión de fuga en CI | Vigilado |
| RK-03 | P0 | Importación hostil (zip bomb, path traversal, JSON gigante) | B (import) | Import siempre dry-run por defecto; validación de schema; límites; suite hostil obligatoria (qa-matrix) | Diseñado |
| RK-04 | P0 | Contaminación entre worktrees (visto en RC6 ETAPA 2) | worktrees compartidos | Worktree exclusivo por equipo; push con refspec+lease explícitos; `set -euo pipefail`; nunca `cd` a placeholder | Regla dura |
| RK-05 | P0 | Config default apunta a Neo4j productivo (`bolt://192.168.1.205:7687` en viewer/app/config.py) | preexistente | Los tests usan mock/lab; en laboratorio nunca se conecta; documentar que la primera ingesta real requiere autorización explícita | Preexistente, vigilado |
| RK-06 | P1 | Duplicar scaffolding existente (external_ai, nvidia, transcriber, export_import) | A/B | ownership-map §scaffolding: extender, no reescribir | Mitigado |
| RK-07 | P1 | Sobrescribir benchmark ya publicado (docs/34/36/37) | A (benchmark relaciones) | Benchmark de relaciones en docs/41,42 NUEVOS; prohibido tocar 33–37 | Regla dura |
| RK-08 | P1 | Regresión de RC6 al integrar A/B | cualquiera | Q corre la suite completa + mutación en cada PR; no-degradación obligatoria | Vigilado |
| RK-09 | P1 | Dependabot mergea un major roto | B-SEC | No auto-merge de major; CI obligatorio; grupos patch/minor separados | Diseñado |
| RK-10 | P1 | Contrato público v1 modificado sin control | A/B | Solo contratos internos hasta promoción a v2 aprobada por Supervisor | Regla dura |
| RK-11 | P2 | Corpus privado/imágenes sin sanitizar en Git | A/B | Solo fixtures sintéticas/sanitizadas + hashes; secret scan en CI; nada de texto privado | Regla dura |
| RK-12 | P2 | Coste/latencia de IA externa (NVIDIA) en benchmark | A | Modo sombra; presupuesto y timeouts registrados; sin cargas pesadas en paralelo en VM105 | Diseñado |
| RK-13 | P3 | Flaky tests por no determinismo LLM | A | 3 ejecuciones + medida de variabilidad; semilla si soportada | Diseñado |

## Notas P0 sobre producción

- knowledge.seccionnueve.duckdns.org / 192.168.1.205 / 100.103.100.105: bloqueados
  por el cortafuegos de la suite (socket/requests/httpx/urllib/DNS/IPv6-mapeada).
- auth.db / jobs.db productivas: nunca se tocan; los tests usan SQLite temporal.
- Ninguna operación de este programa activa `S9K_ALLOW_REAL_INGEST`.
