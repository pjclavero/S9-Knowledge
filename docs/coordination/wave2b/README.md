# OLA 2B — Pipeline funcional de relaciones (coordinación)

Base: `main@a0ffc21`. RC6 congelada en `release/rc6-candidate = 15ae1d4` (no se toca).

## Objetivo

Convertir el contrato de relaciones ya integrado (`data-engine/app/relations/contracts.py`,
`relation-candidate/internal-v1`) en un **pipeline funcional, seguro, auditable y
exclusivamente dry-run**:

```
segmentos + entidades → pares deterministas → señales heurísticas →
análisis sintáctico opcional → prompts RPG versionados → LLM local (sombra) →
IA externa/NVIDIA (sombra) → consenso → candidatos auditables → benchmark
```

**Cero escritura en Neo4j. Cero autoaprobación. Cero red por defecto.**

## Principios

1. **Extender, no duplicar.** Ya existe scaffolding: `external_ai/consensus.py`
   (consenso — R7 lo reutiliza), `external_ai/openai_compatible.py` (LLM local — R5),
   `external_ai/nvidia_nim.py` (NVIDIA — R6), `external_ai/prompts.py` (R4 referencia),
   estados `external_ai/models.py`. NO crear un segundo sistema de consenso.
2. **Contratos de OLA 2A congelados.** No modificar `relations/contracts.py`,
   `export_import/contract.py`, `media/multimedia_contract.py` salvo bloqueo
   arquitectónico documentado (→ punto de parada).
3. **Pruebas reales** contra el producto; sin copias de implementaciones en tests;
   sin skips injustificados; determinismo obligatorio.
4. **RK-05 (P7):** el default del viewer a Neo4j prod se corrige a fail-closed en un
   PR independiente, sin mezclar con relaciones.
5. **Modelos reales (Ollama/NVIDIA):** interfaces por configuración explícita; la
   prueba real queda `NOT_EXECUTED` salvo autorización.

## Documentos

- [program-board.md](program-board.md) — tablero de tareas y estados.
- [ownership-map.md](ownership-map.md) — propiedad de ficheros por agente.
- [dependency-graph.md](dependency-graph.md) — DAG de dependencias.
- [integration-order.md](integration-order.md) — orden de integración.
- [risk-register.md](risk-register.md) — riesgos P0–P3 de OLA 2B.
- [quality-gates.md](quality-gates.md) — gates (2 revisiones + 12 mutaciones).

## Límites absolutos

No VM105 · no Neo4j prod · no conexiones prod · no auth.db/jobs.db · no corpus
privado · no ingesta real · no `S9K_ALLOW_REAL_INGEST` · no tag/Release/despliegue
RC6 · no tocar `release/rc6-candidate` · no import APPLY · no descargar modelos.
