# Diseño de importación segura (v1) — solo documento

Agente: **P5 (OLA 2B, Lote 2)**. Alcance: **exclusivamente documentación**. Este
documento describe el flujo FUTURO de importación segura de paquetes internos
`s9-knowledge-export/internal-v1`. No implementa ni activa nada.

> **APPLY DESHABILITADO — SOLO DISEÑO.** En este lote y en TODA la OLA 2B la fase
> APPLY (creación/actualización/enlazado real en Neo4j o en disco) permanece
> deshabilitada. El único comportamiento existente y permitido es el
> **dry-run** ya presente en `data-engine/app/export_import/contract.py`
> (`dry_run_import`, invariante `DryRunReport.applied == False`). Este documento
> es un plano; no habilita escritura.

Base de lectura (modo lectura, sin modificar): `data-engine/app/export_import/contract.py`.
Ese módulo es DECLARATIVO y de VALIDACIÓN: nunca escribe en Neo4j, nunca aplica
una importación. Todo lo descrito aquí se apoya en sus tipos y validadores ya
existentes y NO propone tocarlos (contratos de OLA 2A congelados; ver
`README.md` de wave2b).

---

## 1. Principios rectores

1. **Fail-closed.** Ante cualquier duda, ambigüedad o error, la importación se
   detiene sin aplicar nada. El estado por defecto es "no importar".
2. **Dry-run primero.** Ninguna escritura ocurre sin un dry-run previo completo,
   revisado y aprobado. En OLA 2B el flujo TERMINA en el dry-run: APPLY no se
   ejecuta.
3. **Nunca confiar en el paquete.** IDs, rutas, tamaños, hashes y contenidos del
   paquete son entradas hostiles hasta que se validan. Los IDs externos se
   remapean de forma determinista (`remap_external_id`), nunca se usan tal cual.
4. **Aislamiento por workspace.** Un paquete solo puede afectar a su propio
   workspace. Cualquier registro de otro workspace es un CONFLICT.
5. **Separación de funciones.** Quien genera/sube el paquete, quien revisa el
   dry-run y quien (en el futuro) autorizaría el APPLY son roles distintos.
6. **Auditable y reproducible.** Toda decisión queda registrada; el mismo paquete
   produce el mismo dry-run (determinismo obligatorio).
7. **Sin red por defecto.** La validación y el dry-run no requieren red ni acceso
   a producción.

---

## 2. Flujo de fases

```
VALIDATE → PLAN → PREVIEW → STAGE → APPLY(DESHABILITADO) → VERIFY → ROLLBACK
```

Estado de cada fase en OLA 2B:

| Fase      | Estado en OLA 2B        | Escribe en Neo4j |
| --------- | ----------------------- | ---------------- |
| VALIDATE  | Existe (validadores)    | No               |
| PLAN      | Diseñado (dry-run base) | No               |
| PREVIEW   | Diseñado (dry-run base) | No               |
| STAGE     | Diseñado (solo doc)     | No               |
| APPLY     | **DESHABILITADO**       | (no se ejecuta)  |
| VERIFY    | Diseñado (solo doc)     | (no se ejecuta)  |
| ROLLBACK  | Diseñado (solo doc)     | (no se ejecuta)  |

VALIDATE, PLAN y PREVIEW se corresponden con capacidades ya presentes en
`contract.py` (validadores atómicos + `dry_run_import`). STAGE, APPLY, VERIFY y
ROLLBACK se describen aquí como diseño futuro; **ninguna se implementa en este
lote**.

### 2.1 VALIDATE

Objetivo: rechazar paquetes malformados u hostiles antes de razonar sobre su
contenido. Reutiliza los validadores existentes:

- `validate_zip_metadata` — inspecciona SOLO la metadata del directorio central
  del ZIP (nombres, `compress_size`, `file_size`) sin descomprimir. Defensa
  anti zip-bomb por RATIO declarado (`Limits.max_compression_ratio`) y por
  tamaño descomprimido total (`Limits.max_uncompressed_bytes`).
- `validate_safe_path` — rechaza rutas absolutas, path traversal (`..`), raíces
  de unidad Windows (`C:\`), separadores backslash y bytes nulos.
- `validate_manifest` — format/version reconocidos (`CONTRACT_FORMAT`,
  `SUPPORTED_VERSIONS`), workspace presente y coincidente, hashes sha256 por
  fichero, schema obligatorio, coherencia `file_count` vs nº de hashes, límites
  de cardinalidad, categorías prohibidas.
- `validate_sha256` — formato y, con datos, coincidencia del contenido.
- `validate_json` / `validate_jsonl` / `validate_csv` — formato y límites de
  tamaño/registros.
- `validate_graphml_declared` — comprueba que el GraphML está DECLARADO (no lo
  parsea; el parser XML con defensa XXE / billion-laughs queda fuera de alcance,
  documentado a propósito en `contract.py`).

Resultado: `ImportState.VALID` solo si no hay ningún error. Cualquier error =>
`INVALID` y parada fail-closed.

### 2.2 PLAN

Objetivo: computar, sin aplicar, qué haría cada registro. Se apoya en
`dry_run_import`, que asigna a cada registro un estado hipotético:
`WOULD_CREATE`, `WOULD_UPDATE`, `WOULD_LINK`, `DUPLICATE`, `CONFLICT`,
`DEFERRED` o `INVALID`. El plan NO escribe: describe lo que PASARÍA.

Reglas del plan (ya codificadas en `dry_run_import`):

- Manifest inválido => no se procesan registros (fail-closed).
- Registro de otro workspace => CONFLICT.
- IDs externos remapeados de forma determinista y aislada por workspace.
- Duplicado intra-lote (mismo internal_id) => DUPLICATE.
- Registro con secretos/sesiones/credenciales (por `_FORBIDDEN_KEY_HINTS`) =>
  INVALID.
- `record_type` no exportable => INVALID.
- Relación con extremos aún no presentes => DEFERRED (resoluble más tarde, no es
  un fallo duro).

### 2.3 PREVIEW

Objetivo: presentar el plan a un revisor humano de forma legible y auditable.
Reutiliza `DryRunReport.to_dict()` y `DryRunReport.summary` (conteo por estado)
y `rejected_any`. El revisor decide si el plan sería aceptable. En OLA 2B el
flujo se detiene aquí: PREVIEW es el punto de salida, no hay continuación a
escritura.

### 2.4 STAGE (diseño futuro, no implementado)

Objetivo (futuro): materializar los cambios propuestos en un área de ensayo
AISLADA de producción (por ejemplo, un grafo/espacio temporal por workspace),
nunca sobre los datos vivos. STAGE permitiría comprobar el plan de forma
tangible sin tocar producción. Propiedades de diseño:

- El área de staging es efímera, etiquetada por `workspace` y por un
  identificador de operación de import.
- STAGE nunca comparte identidad de nodos con producción: los `internal_id`
  provienen de `remap_external_id`, deterministas y aislados por workspace.
- STAGE es descartable sin efectos: su limpieza no requiere ROLLBACK sobre
  producción.
- **No se implementa en este lote.** Aquí solo se documenta.

### 2.5 APPLY (DESHABILITADO en OLA 2B)

Objetivo (futuro, fuera de alcance): promover un plan aprobado a los datos
vivos. **NO se implementa ni se habilita.** Requisitos de diseño que APPLY
tendría que satisfacer ANTES de existir:

- Autorización explícita y separación de funciones (sección 3).
- Idempotencia demostrada (sección 5).
- Transaccionalidad y punto de recuperación (sección 8).
- Auditoría completa (sección 11).

En `contract.py` el invariante es duro: `DryRunReport.applied` es SIEMPRE
`False`. Este diseño respeta ese invariante y no introduce ninguna ruta de
código que lo viole.

### 2.6 VERIFY (diseño futuro, no implementado)

Objetivo (futuro): tras un hipotético APPLY, comprobar que el estado resultante
coincide con el plan aprobado (conteos por estado, hashes de los registros
escritos, ausencia de categorías prohibidas). Una discrepancia dispararía
ROLLBACK. No se implementa en este lote.

### 2.7 ROLLBACK (diseño futuro, no implementado)

Objetivo (futuro): revertir un APPLY parcial o fallido a un punto de
recuperación consistente. Diseño: cada operación de APPLY definiría un savepoint
por lote; un fallo a mitad revierte hasta el último savepoint íntegro sin dejar
datos huérfanos. No se implementa en este lote (no hay APPLY que revertir).

---

## 3. Autorización y separación de funciones

- **Generador/subidor**: produce el paquete y lo entrega. No tiene poder para
  aprobar ni aplicar.
- **Revisor**: examina el `DryRunReport` (PREVIEW). Aprueba o rechaza el plan.
- **Operador de APPLY** (rol futuro): sería el único autorizado a promover un
  plan aprobado. En OLA 2B este rol **no existe operativamente** porque APPLY
  está deshabilitado.

Ningún agente automático se autoaprueba. La autorización de un APPLY futuro
tendría que ser una acción humana explícita, distinta de quien generó el
paquete, y registrada en auditoría. Coherente con la regla del proyecto: ningún
agente modifica producción sin aprobación explícita previa.

---

## 4. Aislamiento por workspace

- El `Manifest.workspace` es obligatorio (`validate_manifest`).
- `validate_manifest(expected_workspace=...)` rechaza un paquete de otro
  workspace.
- En `dry_run_import`, cualquier registro con `workspace` distinto del
  `target_workspace` => CONFLICT.
- `remap_external_id(external_id, workspace)` deriva IDs internos de forma
  determinista pero AISLADA: el mismo par (workspace, external_id) produce
  siempre el mismo interno, y dos workspaces distintos NUNCA colisionan (el
  workspace entra en el sha256).

Un paquete jamás puede alcanzar, leer o pisar datos de otro workspace.

---

## 5. Idempotencia, duplicados y conflictos

- **Idempotencia**: los `internal_id` son deterministas
  (`remap_external_id`). Reimportar el mismo paquete produciría el mismo plan;
  un registro ya existente sería `WOULD_UPDATE` (no un segundo `WOULD_CREATE`).
  Un hipotético APPLY tendría que ser idempotente por diseño (upsert por
  `internal_id`), pero no se implementa aquí.
- **Duplicados intra-lote**: mismo `internal_id` dos veces en el lote =>
  `DUPLICATE` (segunda aparición rechazada).
- **Duplicados contra el estado existente**: `existing_internal_ids` =>
  `WOULD_UPDATE`.
- **Conflictos**: registro de otro workspace => `CONFLICT`. Es un rechazo
  seguro (`_REJECTING_STATES`), nunca una fusión silenciosa.

---

## 6. Compatibilidad de contrato

- `format` debe ser exactamente `s9-knowledge-export/internal-v1`
  (`CONTRACT_FORMAT`).
- `version` debe estar en `SUPPORTED_VERSIONS` (`{"1.0"}`).
- Un paquete con versión no soportada => INVALID (no se intenta "adivinar" ni
  migrar). Las migraciones entre versiones de contrato serían un diseño aparte,
  también dry-run primero, fuera del alcance de OLA 2B.

---

## 7. Archivos hostiles

- **Zip bomb**: `validate_zip_metadata` no descomprime; rechaza por ratio
  declarado (`file_size/compress_size > max_compression_ratio`), por
  `compress_size=0` con `file_size>0` (ratio infinito), por tamaño descomprimido
  total y por nº de entradas. Los `Limits` por defecto son conservadores y el
  llamador puede endurecerlos.
- **Path traversal**: `validate_safe_path` rechaza `..`, rutas absolutas, raíz
  Windows, backslash y bytes nulos. Se aplica a cada nombre de fichero del
  manifest y de las entradas del ZIP.
- **Bytes nulos / nombres no textuales**: rechazados en `validate_safe_path`.
- **Categorías prohibidas** (`FORBIDDEN_EXPORT_CATEGORIES`: passwords, sessions,
  credentials, tokens, internal_paths, sensitive_config, neo4j_dump, secrets):
  su presencia en el manifest o en un registro => rechazo. Los `neo4j_dump`
  internos NO son contrato de usuario.
- **Claves sospechosas dentro de registros** (`_FORBIDDEN_KEY_HINTS`:
  password, secret, token, credential, session, cookie, api_key, private_key,
  bolt_uri, neo4j_uri, …) => registro INVALID (defensa en profundidad).
- **GraphML hostil (XXE / billion-laughs)**: por diseño NO se parsea el XML en
  este contrato; solo se valida la DECLARACIÓN. El parser seguro con defensa XXE
  queda fuera de alcance (documentado en `contract.py`).

---

## 8. Transacciones, staging, rollback y recuperación (diseño futuro)

Ninguna de estas capacidades se implementa en OLA 2B; se documentan como
requisitos que un APPLY futuro tendría que cumplir:

- **Transaccionalidad**: cada lote se aplicaría dentro de una transacción; un
  error aborta el lote completo sin dejar escritura parcial.
- **Staging aislado**: los cambios se ensayan en un área efímera por workspace
  antes de cualquier promoción a datos vivos.
- **Savepoints por lote**: puntos de recuperación que permiten revertir un APPLY
  parcial al último estado íntegro.
- **Rollback**: revertir a un savepoint consistente ante fallo o discrepancia en
  VERIFY.
- **Recuperación**: un import interrumpido no deja el grafo en estado
  intermedio; o se aplicó el lote completo o no se aplicó nada.

---

## 9. Import parcial, fallo a mitad y reanudación (diseño futuro)

- **Import parcial planificado**: el dry-run ya distingue registros que se
  aplicarían (`WOULD_*`) de los que no (`INVALID`, `CONFLICT`, `DUPLICATE`,
  `DEFERRED`). Un APPLY futuro solo promovería los `WOULD_*`; los `DEFERRED`
  (p. ej. relaciones cuyos extremos aún no existen) se reintentarían en un
  segundo paso una vez presentes sus extremos.
- **Fallo a mitad**: con transacciones por lote, un fallo revierte el lote en
  curso; los lotes previos ya confirmados quedan íntegros y auditados.
- **Reanudación**: un import se reanudaría de forma idempotente. Como los
  `internal_id` son deterministas, reprocesar registros ya aplicados los
  clasificaría como `WOULD_UPDATE`/no-op, sin duplicar. El diseño de reanudación
  se apoyaría en un identificador de operación de import + los savepoints de la
  sección 8.
- **Nada de esto se implementa en este lote.**

---

## 10. Hashes y manifest

- El manifest declara un `sha256` por fichero de datos (`Manifest.hashes`);
  `file_count` debe coincidir con el nº de hashes.
- `validate_sha256(value, data)` valida formato y, con el contenido, la
  coincidencia real: un fichero cuyo contenido no case con su hash declarado se
  rechaza.
- La política de redacción (`redaction_policy`) referencia la reutilización de
  `review.export_import` (`sanitize_value`/`sanitize_text`); la lógica de
  redacción NO se duplica.
- El manifest también acota límites (`Limits`) y declara compresión, schemas y
  filtros, todo validado en VALIDATE.

---

## 11. Auditoría

- Cada dry-run produce un `DryRunReport` serializable (`to_dict`) con:
  `workspace`, `applied` (siempre False), `manifest_state`, `manifest_errors`,
  `summary` (conteo por estado) y el detalle por registro (`DryRunRecord`:
  índice, tipo, id externo/interno, estado, motivos).
- Este informe es la evidencia auditable de PREVIEW. Un APPLY futuro tendría que
  registrar además: quién autorizó, cuándo, sobre qué plan (hash del report), y
  el resultado de VERIFY. En OLA 2B solo existe el registro del dry-run.

---

## 12. Límites

- `Limits` (frozen): `max_file_count=512`, `max_records=200000`,
  `max_uncompressed_bytes=512 MiB`, `max_manifest_bytes=8 MiB`,
  `max_compression_ratio=100.0`. Son conservadores por defecto y endurecibles
  por el llamador.
- Se aplican en VALIDATE (ZIP, manifest, JSON/JSONL/CSV) y en PLAN (nº de
  registros del lote).

---

## 13. Alcance de este lote (explícito)

- **Solo documentación.** El único fichero nuevo es este documento.
- No se toca producto, persistencia, viewer ni `.github`.
- No se modifica `data-engine/app/export_import/contract.py` (leído en modo
  lectura).
- **APPLY no se implementa ni se habilita** en este lote ni en toda la OLA 2B.
- Si en el futuro se necesitaran pruebas, serían pruebas de contrato
  DESACOPLADAS del APPLY (validando el dry-run existente), pero para este lote
  se prefiere **solo documento**.

> **Confirmación: APPLY deshabilitado; solo diseño.**
