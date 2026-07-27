# 09 · Auditar antes de trabajar

Regla del proyecto: **antes de programar cualquier cosa nueva, auditar lo que ya
existe.** No repetir trabajo ni pisar lo hecho.

## Checklist previa

- ¿Qué archivos existen ya? (`find data-engine/app -type f -name '*.py'`)
- ¿Qué documentos hay? (`ls docs/ docs/current/`)
- ¿Qué versión de schema y prompt? (`SCHEMA_VERSION`, `PROMPT_VERSION`)
- ¿Qué tests pasan? (`pytest app/tests/ -q`)
- ¿Qué está **implementado** vs solo **diseñado**? (ver `02-current-state.md`)
- ¿Qué **no** debe repetirse? (revisar CHANGELOG y `docs/current/INFORME_ENTREGA.md`)
- ¿Qué es producción y no se toca? (Neo4j, Ollama, SilverBullet, Nextcloud).

## Antes de tocar producción

- Backup del archivo/dato afectado.
- Cambio mínimo y localizado.
- Prueba mínima reproducible.
- No afirmar "resuelto" sin prueba real.
- No procesar lotes hasta pasar una prueba individual.

## Fuentes de verdad

1. El código en `data-engine/app`.
2. `docs/current/INFORME_ENTREGA.md` (qué se hizo y qué queda).
3. Neo4j (estado real del grafo).
4. Este set `docs/00–10` (visión y estado).
