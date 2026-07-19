# Diseno funcional — EXPORTACION del contrato interno (OLA 2B Lote 2) — v1

Diseno funcional de la futura **EXPORTACION** de S9 Knowledge sobre el contrato
interno `s9-knowledge-export/internal-v1` ya integrado. Documento **solo de
coordinacion / diseno**: no cambia producto, persistencia, viewer ni `.github`.

> **Invariante duro de este documento:** aqui NO se implementa exportacion real
> que toque persistencia compartida (Neo4j, disco productivo, ficheros de
> workspace) NI se generan dumps productivos. Es un diseno para una tarea
> posterior gateada. La exportacion real, cuando exista, reutilizara el contrato
> `data-engine/app/export_import/contract.py` y su modulo de redaccion
> `review.export_import`, sin duplicar logica de validacion ni de saneamiento.

## Punto de partida (contrato ya integrado)

El contrato de referencia es
[`data-engine/app/export_import/contract.py`](../../../data-engine/app/export_import/contract.py),
modulo **declarativo y de validacion** que:

- Define `CONTRACT_FORMAT = "s9-knowledge-export/internal-v1"`,
  `CONTRACT_VERSION = "1.0"` y `SUPPORTED_VERSIONS = {"1.0"}`.
- Define el `Manifest` (workspace, format, version, created_at,
  exporter_version, filters, entity_count, relation_count, file_count, schemas,
  hashes, compression, redaction_policy) con `build_manifest`, `to_dict` /
  `from_dict` y `validate_manifest`.
- Enumera los tipos EXPORTABLES en `RecordType` /
  `EXPORTABLE_RECORD_TYPES` (`entities`, `relations`, `aliases`, `provenance`,
  `decisions`, `plans`, `metrics`, `events`) y las categorias PROHIBIDAS en
  `FORBIDDEN_EXPORT_CATEGORIES` (`passwords`, `sessions`, `credentials`,
  `tokens`, `internal_paths`, `sensitive_config`, `neo4j_dump`, `secrets`).
- Aporta validadores atomicos: `validate_safe_path`, `validate_sha256`,
  `remap_external_id`, `validate_manifest`, `validate_zip_metadata`,
  `validate_jsonl`, `validate_json`, `validate_csv`,
  `validate_graphml_declared`.
- Define `Limits` (max_file_count, max_records, max_uncompressed_bytes,
  max_manifest_bytes, max_compression_ratio) y el modelo dry-run
  (`ImportState`, `DryRunRecord`, `DryRunReport`, `dry_run_import`), donde la
  invariante es `applied == False` siempre.
- Reutiliza la redaccion de `review.export_import` (`sanitize_value`,
  `sanitize_text`); NO la duplica.

La exportacion disenada aqui es el **productor** del paquete que esos validadores
ya saben verificar: debe generar exactamente lo que `validate_manifest`,
`validate_zip_metadata` y los validadores de datos aceptan como VALID. El bucle
de simetria es: `export -> paquete -> validate_* -> dry_run_import (VALID)`.

## Objetivos y no-objetivos

**Objetivos del diseno.**

- Especificar como se selecciona el subconjunto exportable (por workspace y por
  documento) y como se materializa en un paquete manifestado, determinista,
  redactado y verificable.
- Alinear cada decision con un simbolo concreto del contrato ya integrado, de
  modo que la implementacion futura no reinvente validacion ni redaccion.

**No-objetivos (explicitos).**

- NO implementar la lectura real de Neo4j ni ningun acceso a persistencia
  compartida en esta tarea.
- NO generar dumps productivos ni `neo4j_dump` (categoria PROHIBIDA por
  contrato).
- NO implementar APPLY de import (fuera de alcance del contrato) ni GraphML
  parseado completo (el contrato solo valida la DECLARACION).

## Vision general del flujo

```
seleccion (workspace / documento)
      |
      v
lectura de origen (read-only)  ── [futuro; gateado; no en esta tarea]
      |
      v
redaccion (review.export_import.sanitize_value / sanitize_text)
      |
      v
serializacion determinista (JSONL por tipo + metadatos)
      |
      v
hashing sha256 por fichero  ──>  build_manifest(...)
      |
      v
empaquetado ZIP (metadatos declarados: name, compress_size, file_size)
      |
      v
validacion posterior (validate_manifest + validate_zip_metadata + validate_jsonl)
      |
      v
auto-verificacion dry-run (dry_run_import -> VALID, applied=False)
```

Todas las etapas previas a "lectura de origen" y la propia lectura quedan
**diseñadas pero no implementadas** en esta tarea. El resto (redaccion,
serializacion, hashing, manifest, validacion) reutiliza el contrato.

## Seleccion por workspace

- El `workspace` es el **eje primario de aislamiento**: un paquete pertenece a
  exactamente un workspace (`Manifest.workspace`, obligatorio). `validate_manifest`
  rechaza `workspace` vacio y, con `expected_workspace`, rechaza workspace ajeno.
- La seleccion por workspace exporta todos los `RecordType` permitidos cuyo
  `workspace` coincide. Ningun registro de otro workspace puede entrar: en
  `dry_run_import` un registro con `workspace` distinto produce `CONFLICT`, por lo
  que el exportador debe filtrarlo en origen (fail-closed antes de escribir).
- Los identificadores externos NO se confian: la correspondencia estable la da
  `remap_external_id(external_id, workspace)`, determinista y aislada por
  workspace (mismo par -> mismo `s9x_<24hex>`; dos workspaces nunca colisionan).

## Seleccion por documento

- Seleccion mas fina: un subconjunto de documentos dentro de un workspace. Se
  expresa como filtros y se registra en `Manifest.filters` (dict libre), por
  ejemplo `{"document_ids": [...], "since": "...", "record_types": [...]}`.
- La seleccion por documento debe **cerrar transitivamente** las dependencias
  minimas para que el paquete sea coherente: si se incluye una `relation`, sus
  extremos (`from`/`to`) deberian incluirse o declararse como ya conocidos; de lo
  contrario `dry_run_import` marca la relacion `DEFERRED` (extremos aun no
  presentes). El diseño prefiere exportar entidades extremo antes que emitir
  relaciones colgantes.
- Orden de emision recomendado: primero `entities` (y demas nodos), luego
  `relations`, para que la verificacion dry-run resuelva extremos dentro del
  lote.
- `Manifest.filters` es la unica fuente declarada de "que se pidio"; permite
  reproducibilidad y auditoria de la seleccion sin volver a la persistencia.

## Manifest

- Se construye con `build_manifest(workspace, filters=..., entity_count=...,
  relation_count=..., schemas=..., hashes=..., compression=...,
  redaction_policy=...)`. `created_at` se fija en UTC ISO-8601; `file_count` se
  **deriva** de `hashes` (un sha256 por fichero de datos) y no se declara a mano.
- `schemas` es OBLIGATORIO y no vacio: mapea cada `record_type` presente a su
  `schema_id/version`. `validate_manifest` rechaza schemas ausente.
- `format`/`version` deben ser exactamente los del contrato; cualquier otro valor
  es INVALID.
- El manifest NO debe declarar categorias prohibidas en `schemas`/`filters`
  (`_forbidden_categories_in`): incluir p.ej. una clave `tokens` o `neo4j_dump`
  invalida el paquete.
- `redaction_policy` por defecto referencia
  `review.export_import.sanitize_value` y la lista de lo que redacta; el
  exportador puede endurecerla pero no relajarla.
- El manifest es el **indice de integridad**: contiene los hashes de todos los
  ficheros de datos, de modo que un consumidor verifica el paquete sin confiar en
  el ZIP.

## JSONL (formato de datos primario)

- El formato de datos primario es **JSONL**: un objeto JSON por linea no vacia,
  validable con `validate_jsonl` (rechaza no-texto, exceso de tamano, exceso de
  registros y lineas mal formadas; exige al menos un registro).
- Particion recomendada: **un fichero JSONL por `RecordType`** (p.ej.
  `entities.jsonl`, `relations.jsonl`, `aliases.jsonl`, ...), cada uno declarado
  en `hashes` y en `schemas`. Esto acota el fallo (una linea corrupta afecta a un
  solo tipo) y facilita el streaming.
- Cada registro lleva al menos `type` e `id`; las relaciones ademas `from`/`to`.
  El `type` admite singular o plural (`_normalize_type`), pero el diseño fija el
  **plural canonico** de `RecordType` para determinismo.
- JSON (`validate_json`), CSV (`validate_csv`) y GraphML DECLARADO
  (`validate_graphml_declared`) son formatos secundarios/auxiliares; el nucleo de
  la exportacion es JSONL. GraphML, si se emite, solo se DECLARA en
  `schemas["graphml"]` con extension `.graphml`; su parser completo (defensa XXE /
  billion-laughs) queda fuera de alcance, como en el contrato.

## Hashes (sha256) e integridad

- Todo fichero de datos lleva un `sha256` hex (64 chars, minusculas) en
  `Manifest.hashes`; el formato lo valida `validate_sha256` y el match contra
  contenido tambien (`validate_sha256(value, data)`).
- El hash se calcula sobre los **bytes exactos** del fichero serializado (tras
  redaccion y con orden determinista), antes de comprimir. La verificacion
  posterior recomputa y compara.
- `file_count` debe igualar `len(hashes)`; `validate_manifest` rechaza la
  discrepancia.

## Firmas / integridad adicional (si procede)

- Integridad basica: hashes sha256 por fichero + coherencia de `file_count`. Es
  el minimo exigido por el contrato y suficiente para deteccion de corrupcion o
  manipulacion accidental.
- **Firma opcional (diseño, no obligatoria):** el manifest completo puede
  ademas cubrirse con un hash-de-manifest y una firma detached (p.ej. un
  `manifest.sha256` y un `.sig`) para autenticidad entre entornos. Se documenta
  como extension futura; **no** se define material criptografico ni claves aqui,
  y en ningun caso una firma incrusta secretos en el paquete.
- La cadena de confianza es: firma (opcional) -> hash del manifest -> hashes por
  fichero -> contenido. Verificar de fuera hacia dentro permite fail-closed
  temprano.

## Orden determinista

- Requisito central para reproducibilidad y para que el mismo hash se obtenga en
  reejecuciones. Reglas:
  - Ficheros ordenados por `RecordType` en un orden fijo (el de declaracion de
    `RecordType`), y registros ordenados por `internal_id`
    (`remap_external_id`) dentro de cada fichero.
  - Serializacion JSON con claves ordenadas y separadores estables (equivalente a
    `sort_keys=True`, sin espacios superfluos), timestamps en UTC ISO-8601.
  - `hashes` y `schemas` del manifest emitidos con claves ordenadas.
- El determinismo hace que `sha256` sea estable y que dos exportaciones de la
  misma seleccion produzcan paquetes byte-identicos (salvo `created_at`, que es
  el unico campo temporal y queda fuera del hash de contenido de datos).

## Streaming

- El diseño asume **generacion en streaming** para no materializar todo en
  memoria: los registros se leen y redactan de a uno, se escriben linea a linea
  en el JSONL correspondiente, y el sha256 se calcula de forma incremental
  (`hashlib` alimentado por chunks).
- El manifest se emite **al final**, cuando ya se conocen todos los hashes y
  contadores (`entity_count`, `relation_count`, `file_count`). Esto exige un
  esquema de dos fases: (1) volcar ficheros de datos calculando hashes; (2)
  construir y escribir el manifest.
- Los validadores del contrato operan sobre texto/entradas ya materializadas;
  para paquetes grandes, la validacion posterior puede hacerse fichero a fichero
  respetando `Limits`.

## Limites de tamano

- Se reutilizan los `Limits` del contrato (valores conservadores, endurecibles
  por el llamador): `max_file_count=512`, `max_records=200_000`,
  `max_uncompressed_bytes=512 MiB`, `max_manifest_bytes=8 MiB`,
  `max_compression_ratio=100.0`.
- El exportador NO debe producir paquetes que superen estos limites: si la
  seleccion excede `max_records` o `max_uncompressed_bytes`, el diseño obliga a
  **paginar/particionar** en varios paquetes (p.ej. por documento o por rango),
  cada uno auto-consistente.
- La defensa anti zip-bomb es por METADATA declarada (`validate_zip_metadata`):
  el ZIP declara `name`, `compress_size`, `file_size` por entrada y el ratio no
  puede superar `max_compression_ratio`. El exportador debe declarar tamaños
  reales.

## Redaccion (sin secretos / sesiones / credenciales)

- La redaccion es **obligatoria y previa** al hashing: se aplica
  `sanitize_value` / `sanitize_text` de `review.export_import` (reutilizado por el
  contrato) a valores y textos antes de serializar. NO se duplica logica de
  redaccion.
- Defensa en profundidad por categorias y claves:
  - `FORBIDDEN_EXPORT_CATEGORIES` nunca se exportan (`passwords`, `sessions`,
    `credentials`, `tokens`, `internal_paths`, `sensitive_config`, `neo4j_dump`,
    `secrets`).
  - Claves sospechosas en un registro (`_FORBIDDEN_KEY_HINTS`: `password`,
    `secret`, `token`, `credential`, `session`, `cookie`, `api_key`,
    `private_key`, `bolt_uri`, `neo4j_uri`, `neo4j_dump`, ...) hacen que
    `dry_run_import` marque el registro INVALID. El exportador debe **no
    emitirlas**; encontrarlas en la verificacion posterior es un fallo del
    exportador, no algo a "arreglar" en import.
- `redaction_policy` del manifest documenta que se redacto; el consumidor la ve
  sin necesidad de reprocesar.
- Regla de oro: **si un dato dudoso no se puede redactar con garantia, no se
  exporta.** Fail-closed.

## Separacion metadatos / contenido

- **Metadatos** (manifest): identidad del contrato, workspace, filtros,
  contadores, schemas, hashes, compresion y politica de redaccion. Van en un
  fichero de manifest separado; describen el paquete sin ser datos de usuario.
- **Contenido** (ficheros de datos): los JSONL/CSV/GraphML por tipo. El manifest
  los referencia por nombre+hash pero no los incrusta.
- Beneficio: un consumidor puede validar el manifest (barato, `max_manifest_bytes`)
  y decidir antes de tocar el contenido; y la integridad del contenido se ancla en
  el manifest.

## Versionado y compatibilidad

- El paquete declara `format` + `version` del contrato (`internal-v1`, `1.0`) y el
  `exporter_version` (`s9-knowledge-export-import/1.0`). El consumidor acepta solo
  `SUPPORTED_VERSIONS`.
- Compatibilidad hacia adelante: nuevas versiones se añaden a `SUPPORTED_VERSIONS`
  en el contrato; el exportador nunca emite una version que los validadores
  vigentes no reconozcan. Cambios incompatibles => nueva `version` (p.ej. `2.0`),
  no mutacion silenciosa de `1.0`.
- `schemas` versiona por tipo de registro (schema_id/version), de modo que un tipo
  puede evolucionar sin romper todo el contrato.
- El diseño NO introduce nuevas versiones en esta tarea; solo describe la politica.

## Errores

- Modelo fail-closed y reutilizando el vocabulario del contrato:
  - Errores de manifest: `validate_manifest` -> `(ImportState.INVALID, [motivos])`.
  - Errores de ZIP declarado: `validate_zip_metadata` -> INVALID con motivos
    (ruta insegura, tamaños negativos, ratio de zip-bomb, exceso de tamaño).
  - Errores de datos: `validate_jsonl` / `validate_json` / `validate_csv` con
    numero de linea y causa.
- El exportador debe abortar (no emitir paquete parcial confiable) si la
  auto-verificacion posterior no da VALID. Un paquete que no se valida a si mismo
  no se entrega.
- Rutas: todo nombre de fichero pasa `validate_safe_path` (sin absolutas, sin
  `..`, sin raiz Windows, sin backslash, sin byte nulo).

## Reanudacion

- Para exportaciones grandes o interrumpidas, el diseño contempla **reanudacion
  por particiones**: como cada fichero JSONL por tipo (o por rango de documento) es
  auto-contenido y su hash se conoce al cerrarlo, una ejecucion interrumpida puede
  retomar desde los ficheros ya cerrados sin rehacer los hashes existentes.
- El manifest, al emitirse al final, actua como **commit**: mientras no exista un
  manifest coherente (`file_count == len(hashes)`, todos los hashes validos), el
  paquete se considera incompleto y no entregable. No hay estado intermedio
  "medio valido".
- La reanudacion NO reabre persistencia compartida en esta tarea (no
  implementada); se describe como propiedad del formato.

## Dry-run

- La exportacion tiene su propio **modo dry-run**: producir el manifest y los
  contadores/hashes **sin escribir** el paquete en disco productivo (p.ej. a un
  buffer efimero), para estimar tamaño, ficheros y cumplimiento de `Limits` antes
  de materializar nada.
- Ademas, la verificacion de simetria usa el dry-run del contrato
  (`dry_run_import`, invariante `applied == False`): el paquete recien generado se
  pasa por `dry_run_import(manifest, records, target_workspace=...)` y debe dar
  estados no-rechazo (`WOULD_CREATE` / `WOULD_UPDATE` / `WOULD_LINK`), nunca
  `INVALID` / `CONFLICT` / `DUPLICATE` (un `DEFERRED` residual indica relaciones
  con extremos fuera del paquete: senal de seleccion incompleta).
- Ningun dry-run toca Neo4j ni aplica nada.

## Validacion posterior (self-check obligatorio)

Antes de considerar entregable un paquete, el exportador ejecuta, en orden:

1. `validate_manifest(manifest, expected_workspace=ws)` -> VALID.
2. `validate_zip_metadata(entries)` -> VALID (rutas, tamaños, ratios).
3. Por cada fichero de datos: `validate_jsonl` / `validate_json` / `validate_csv`
   -> VALID; y `validate_sha256(hash, data)` -> match.
4. `validate_graphml_declared(schemas, file_name=...)` si hay GraphML.
5. `dry_run_import(...)` -> sin estados de rechazo.

Si cualquier paso falla, el paquete se descarta (fail-closed). Este self-check es
la garantia de que la exportacion produce exactamente lo que el import dry-run
del contrato sabe verificar.

## Trazabilidad con el contrato

| Aspecto del diseño | Simbolo del contrato reutilizado |
| --- | --- |
| Identidad del paquete | `CONTRACT_FORMAT`, `CONTRACT_VERSION`, `SUPPORTED_VERSIONS`, `EXPORTER_VERSION` |
| Manifest | `Manifest`, `build_manifest`, `validate_manifest` |
| Tipos exportables | `RecordType`, `EXPORTABLE_RECORD_TYPES` |
| Categorias prohibidas | `FORBIDDEN_EXPORT_CATEGORIES`, `_FORBIDDEN_KEY_HINTS` |
| Limites / anti zip-bomb | `Limits`, `validate_zip_metadata` |
| Datos JSONL/JSON/CSV/GraphML | `validate_jsonl`, `validate_json`, `validate_csv`, `validate_graphml_declared` |
| Hashes e integridad | `validate_sha256`, `Manifest.hashes`, `file_count` |
| Rutas seguras | `validate_safe_path` |
| IDs deterministas | `remap_external_id` |
| Redaccion | `sanitize_value`, `sanitize_text` (`review.export_import`) |
| Self-check / simetria | `dry_run_import`, `DryRunReport`, `ImportState` |

## Declaracion de alcance (recordatorio)

Este documento es **solo diseño**. No implementa exportacion real que toque
persistencia compartida, no lee Neo4j, no genera dumps productivos y no crea
paquetes de datos reales. Cualquier implementacion futura debera reutilizar
`data-engine/app/export_import/contract.py` y `review.export_import`, mantener el
self-check dry-run y quedar gateada por la autorizacion correspondiente antes de
producir cualquier artefacto sobre datos productivos.
