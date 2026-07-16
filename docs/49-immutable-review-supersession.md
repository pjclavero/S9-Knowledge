# 49 — Flujo de supersesión inmutable de reviews (RC2)

## Propósito
Corregir un `review_recommendations.json` **sin modificar el original**, generando
una versión superseding (`.v2.json`) mediante una transformación **explícita,
auditable y reproducible**. Resuelve conflictos de datos (p. ej. una misma entidad
con dos decisiones contradictorias) antes de cualquier ingesta, manteniendo la
procedencia intacta.

Herramienta: `data-engine/app/review/supersede_review.py` (genérica, sin dependencia
de Neo4j ni de `ingest`). No escribe en la base de grafos, no ejecuta ingesta y no
inventa metadatos de auditoría (`reviewed_by`, `correction_reason` y `created_at`
son obligatorios y se pasan por parámetro).

## Garantías
1. **Original inmutable.** Verifica el `SHA-256` del original contra `--supersedes`
   y aborta si no coincide; comprueba tras la transformación que el original no se
   tocó.
2. **No sobrescritura.** `--in` y `--out` no pueden apuntar al mismo archivo.
3. **Idempotencia / anti-conflicto.** Si `--out` ya existe con el mismo
   `supersedes_sha256`, la operación es idempotente (`ALREADY_DONE`). Si existe con
   un `supersedes_sha256` distinto, aborta (segunda supersesión conflictiva).
4. **Consolidación conservadora.** Fichas duplicadas por `name` (o con
   `match_type=exact` / `resolver=use_existing`) se colapsan en **una** decisión
   `DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE` — nunca `CREATE_NEW`, nunca
   `SET` sobre el nodo existente. El historial de las decisiones originales se
   conserva en `consolidated_from`.
5. **Sin cambios automáticos** de recomendación para fichas únicas: se marcan
   `reviewed=manual` sin alterar su decisión.
6. **Relaciones excluidas** (`relations_authorized = 0`).
7. **Escritura atómica** a `.tmp` + `rename`, permisos `0600`.
8. **Seguridad de rutas:** rechaza path traversal (`..`) y symlinks en `--in`/`--out`.
9. **Unicode:** rechaza caracteres de control / Trojan Source en campos de auditoría.

## Uso
```bash
python3 data-engine/app/review/supersede_review.py \
  --in  <original.json> \
  --supersedes <sha256-del-original> \
  --out output/reviews/<workspace>/<source_id>/review_recommendations.v2.json \
  --reviewed-by "<identidad-del-revisor>" \
  --correction-reason "<razón explícita>"
# --dry-run muestra el resultado sin escribir nada en disco.
```

## Caso aplicado: `leyenda / source_narrative_01`
- Original (intacto): `SHA-256 5ac551136281236d405d0df2c9777a01d42d9aeaa4e7d9bbe44d010c23005540`.
- Salida operativa: `output/reviews/leyenda/source_narrative_01/review_recommendations.v2.json`.
- `Clan Escorpión`: dos decisiones en conflicto (`REJECT` tipo `Clan` inválido +
  `APPROVE_UNCHANGED` como `Faction`, entidad ya existente en el grafo) →
  consolidadas en **una** decisión `DEFERRED_USE_EXISTING_UNTIL_MULTI_SOURCE_PROVENANCE`.
- Buckets resultantes: `APPROVE_UNCHANGED=4`, `USE_EXISTING=1`, `EDIT=2`,
  `DEFERRED_USE_EXISTING…=1`; `relations_authorized=0`.

## Tests
`data-engine/app/tests/test_supersede_review.py` — 25 casos (esquema, hash,
idempotencia, conflicto, atomicidad, permisos, path traversal, symlink, Unicode,
ausencia de Neo4j/ingest). Fixture anonimizado:
`data-engine/app/tests/fixtures/review_supersede/review_anon.json`.

## Estado (RC2 — NO activo)
Este flujo forma parte del candidato **RC2** (rama `release/prepare-v0.3.1-rc2`,
base `d9348a8`). **No está desplegado.** La primera ingesta sigue **sin autorizar**:
generar el review por el flujo oficial y obtener autorización expresa antes de
cualquier escritura real en el grafo.
