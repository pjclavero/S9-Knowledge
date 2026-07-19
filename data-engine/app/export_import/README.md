# export_import — Contrato interno `s9-knowledge-export/internal-v1`

Modulo **declarativo y de validacion** del paquete interno de export/import de
S9 Knowledge. Define el MANIFEST, los registros exportables, los estados de
importacion en modo **dry-run** y sus validadores.

## Que NO hace (por diseno)

- **No implementa APPLY de importacion.** El validador de import es SIEMPRE
  dry-run: describe lo que PASARIA, nunca escribe en Neo4j ni en disco.
- **No convierte dumps internos de Neo4j en contrato de usuario.** `neo4j_dump`
  es una categoria prohibida.
- No duplica la logica de redaccion: **reutiliza** `review.export_import`
  (`sanitize_value` / `sanitize_text`).

## MANIFEST

Campos (`Manifest` / `build_manifest`):

`format`, `version`, `created_at`, `exporter_version`, `workspace`, `filters`,
`entity_count`, `relation_count`, `file_count`, `schemas`, `hashes`,
`compression`, `redaction_policy`.

- `format` fijo a `s9-knowledge-export/internal-v1`.
- `hashes`: `{fichero: sha256_hex}` — obligatorio, uno por fichero de datos.
- `file_count` debe cuadrar con el nº de `hashes`.

## Registros soportados

`entities`, `relations`, `aliases`, `provenance`, `decisions` (exportables),
`plans`, `metrics`, `events` (permitidos).

**Nunca exporta**: contrasenas, sesiones, credenciales, tokens, rutas internas,
config sensible, dumps internos de Neo4j (`FORBIDDEN_EXPORT_CATEGORIES`).

## Estados de import (dry-run)

`ImportState`: `VALID`, `INVALID`, `WOULD_CREATE`, `WOULD_UPDATE`,
`WOULD_LINK`, `CONFLICT`, `DUPLICATE`, `DEFERRED`.

`DryRunReport.applied` es **siempre** `False` (invariante).

## Reglas validadas

- **Aislamiento por workspace**: registro/manifest de otro workspace => rechazo.
- **IDs externos no confiables**: remapeo determinista y aislado por workspace
  (`remap_external_id`), estable e imposible de colisionar entre workspaces.
- **Hashes obligatorios** (sha256) con formato y match opcional de contenido.
- **Schema obligatorio** (`manifest.schemas`).
- **Limites** de tamano y nº maximo de registros/ficheros (`Limits`).
- **Rutas seguras**: rechaza `..`, rutas absolutas y raices Windows.
- **Sin secretos/sesiones/credenciales** en registros ni categorias prohibidas.

## Validadores de formato

- `validate_manifest` — MANIFEST completo.
- `validate_zip_metadata` — ZIP por **metadata declarada** (directorio central),
  **sin descomprimir**; defensa anti zip-bomb por ratio declarado.
- `validate_jsonl`, `validate_json`, `validate_csv`.
- `validate_graphml_declared` — valida solo la **declaracion** del GraphML.

### Nota de alcance: GraphML

`validate_graphml_declared` comprueba unicamente que el paquete DECLARA el
GraphML (schema + nombre de fichero seguro). El **parser XML completo** (con
defensa XXE / billion-laughs) queda para otra tarea; documentado a proposito.

## Pruebas hostiles

En `tests/test_export_import_contract.py`: path traversal, zip-bomb simulada por
metadata, hash incorrecto, manifest ausente, version desconocida, IDs
duplicados, workspace ajeno, fichero no declarado, tamano excesivo, JSONL
invalido, secreto en registro, tipo no exportable. Cada una produce
`INVALID`/`CONFLICT`/`DUPLICATE`/`DEFERRED` y **nunca** aplica nada.
