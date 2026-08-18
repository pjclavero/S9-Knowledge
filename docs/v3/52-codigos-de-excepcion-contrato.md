# Códigos de excepción: contrato observable del RC

**Estado**: introducido en el carril 3 de V3.1 (rama
`feat/v31-carril3-csrf-y-codigos-de-excepcion`, PR #198). **No fusionado.**

## Qué se declara aquí

Los códigos de rechazo de las excepciones que sostienen garantías del RC
**forman parte del contrato observable**, igual que un código de estado HTTP.
Se pueden reescribir sus mensajes; **no** se pueden cambiar sus códigos ni sus
tipos sin cambiar el contrato.

El motivo es un defecto medido: una comprobación `pytest.raises(X, match="…")`
mide la **redacción**. Se pone roja si alguien reescribe el texto sin tocar
nada, y se queda **verde** si otra rama del código lanza el mismo tipo con un
mensaje parecido. Demostrado sobre `aaf9695`: reescribir sólo el texto de tres
excepciones, sin cambiar ninguna conducta, ponía rojas 4 pruebas.

Regla: **donde una excepción sostenga una garantía del RC, se comprueba tipo +
código.** Si no tiene código estable, se le da.

## Superficies con código estable

| Módulo | Garantía RC | Contrato |
|---|---|---|
| `viewer/app/auth/security.py` | fail-closed de arranque con auth activa | `SecurityProblem(code, message)`; `AuthSecurityError.codes` (tupla: varias causas a la vez) |
| `viewer/app/auth/schema_compat.py` | REFUSE TO START fuera del rango de esquema | `SchemaCompatibilityError.code` + `.schema_version` |
| `viewer/app/services/v3_review.py` | identidad durable de la historia append-only, unicidad de `request_id`, obsolescencia, paquetes corruptos | `ReviewError.code` (heredado por `HistoryIntegrityError` y `StaleReviewError`) |

Los códigos son **constantes de módulo**, construidas en el sitio del `raise`:
ninguno se deriva del mensaje, ni por concatenación ni por parseo.

### `app.auth.security`

`CSRF_SECRET_EMPTY`, `CSRF_SECRET_DEFAULT`, `CSRF_SECRET_TOO_SHORT`,
`CSRF_SECRET_LOW_ENTROPY`, `PASSWORD_BACKEND_NOT_ALLOWED`,
`AUTH_DB_PATH_EMPTY`, `AUTH_DB_PATH_NOT_ABSOLUTE`, `AUTH_DB_PATH_MISSING`.

**Longitud mínima y entropía mínima del secreto CSRF son dos propiedades
independientes**, con código propio cada una. Antes las cubría un solo caso
(`"corto123"`: 8 caracteres, 7 distintos) que disparaba las dos a la vez, así
que bajar cualquiera de las dos por separado dejaba todo verde.

### `app.auth.schema_compat`

`SCHEMA_DB_UNREADABLE`, `SCHEMA_NOT_SQLITE`, `SCHEMA_VERSION_TABLE_MISSING`,
`SCHEMA_VERSION_TABLE_UNREADABLE`, `SCHEMA_VERSION_TABLE_EMPTY`,
`SCHEMA_VERSION_NOT_NUMERIC`, `SCHEMA_ABOVE_MAX_SUPPORTED`,
`SCHEMA_BELOW_MIN_SUPPORTED`.

### `app.services.v3_review`

`MISSING_FIELD`, `EVIDENCE_OFFSETS_REQUIRED`, `EVIDENCE_OFFSETS_OUT_OF_RANGE`,
`EVIDENCE_LITERAL_MISMATCH`, `PACKAGE_CORRUPT`, `PACKAGE_INVALID`,
`PROPOSAL_INVALID`, `INVALID_HUMAN_DECISION`, `REQUEST_ID_REUSED`,
`PROPOSAL_NOT_FOUND`, `SUPERSEDED_DECISION_MISMATCH`, `NO_ACTIVE_DECISION`,
`STALE_REVIEW`, y para la integridad del historial `HISTORY_ENTRY_NOT_OBJECT`,
`HISTORY_CHAIN_BROKEN`, `HISTORY_HASH_INVALID`, `HISTORY_DUPLICATE_ID`,
`HISTORY_INVALID_JSON`.

`STALE_REVIEW` sigue viviendo **además** como valor de conducta fuera del
mensaje: el `notice` del redirect de `/v3/review`, el evento de auditoría y la
plantilla. Perder el token del texto de la excepción no pierde garantía.

## Cómo se comprueba

`viewer/tests/exception_codes.py::raises_code(tipo, código)`. Cubre las dos
formas (`code` único y pertenencia en `codes`), **rehúsa `code=None`** y
**rehúsa** una excepción que no exponga ninguno de los dos: un verificador que
puede aprobar sin comprobar es el mismo defecto con otra cara. Tiene sus
propios negativos en `viewer/tests/test_exception_codes_instrumento.py`.

## Deuda declarada

Sobre `aaf9695` hay **208** comprobaciones por subcadena (153 `pytest.raises(…
match=)` + 55 `in str(exc…)`), de las que **176** están en
`data-engine/app/tests/**` (ledger V3, safe writer, `supersede_review`,
proveedores, benchmarks). **Varias sostienen garantías del RC** —unicidad e
identidad durable en el ledger, no-escritura del writer en dry-run— y **piden
carril propio**: necesitan códigos en `LedgerError` y en el writer. El detalle
y las exclusiones justificadas están en el docstring de
`viewer/tests/exception_codes.py`.

## Excepción deliberada

`test_schema_mas_nuevo_que_el_codigo_rehusa_arrancar` comprueba **también** el
texto, porque ese mensaje es el runbook que lee un operador de madrugada. La
conducta está medida por código junto a él, así que el texto no le presta rojo
a nada: queda como tripwire de redacción, que es el efecto buscado.
