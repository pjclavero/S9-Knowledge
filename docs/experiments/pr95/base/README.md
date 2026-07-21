# PR#95 · Base común — corrección del contrato DOCUMENTO/ID (P0)

**Rama:** `exp/pr95-compare-base-contract-v1` · **Base:** `dcded31` (BASE_SHA) ·
**Estado:** EXPERIMENTAL · **DO NOT MERGE** · **NO DEPLOY** · **NO NEO4J WRITE**

Base común de la que derivan las 4 versiones (V1–V4). Corrige **solo** el defecto de
contrato P0; **no** cambia el algoritmo de anclaje, ni realinea, ni introduce fragment
IDs, ni parser, ni generación de pares, ni review policy, ni umbrales.

## P0 — hecho verificado (CONFIRMADO)

El evaluador externo recibía el **ID del segmento** (`cand.source_segment`) como
"DOCUMENTO" y validaba la evidencia/offsets contra él, en vez del **texto real**. Ver
`artifacts/pr95-variants/git-snapshot.md` y la demostración con proveedor falso.

## Cambio (mínimo, retrocompatible)

- `external_ai_shadow.py`:
  - Nueva función `_resolve_document(cand, document_text)`: usa `document_text` si se
    aporta; si no, cae al histórico `cand.source_segment` (compatibilidad).
  - `evaluate_relation_external(..., document_text=None)`, `_build_messages(..., document_text)`
    y `_validate_verdict(..., document_text)` enhebran el texto real.
  - El **DOCUMENTO** del prompt y la validación de evidencia/offsets usan el texto real.
- `pipeline.py`:
  - `_run_external(cand, config, ctx, seg_text)` pasa `document_text=seg_text` (texto real
    del segmento). `source_segment` se conserva **solo como trazabilidad (ID)**.
- **Contrato de 20 campos intacto** (`document_text` es entrada de runtime, no campo del
  candidato). Sin cambios en serialización, umbrales, review policy ni Neo4j.

## Plan de tests (base común)

`tests/test_relation_external_document_contract.py` (13 tests, todos verdes):

- **Regresión P0** (fallan sin el fix, verificado por mutación — 5 caen):
  - `provider_received_document == segment text` y `!= segment id`;
  - end-to-end vía pipeline;
  - evidencia validada contra el texto real (literal aceptada / inventada rechazada).
- **Casos borde:** offsets fuera de rango, documento vacío, CRLF, subcadena repetida
  (offsets desambiguan), Unicode NFC/NFD (literalidad estricta), timeout de proveedor
  aislado, JSON inválido aislado, determinismo (request_hash estable), sin red (proveedor
  falso inyectado).

## Resultados

- `pytest -k "relation or external or benchmark"` → **1039 passed**.
- Invariantes del Bloque 9 → **48 passed**.
- Mutación del fix → **5 tests de regresión fallan** (matan al mutante), revertida limpia.

## Seguridad / límites

Offline, proveedor inyectado (sin red), sin escritura Neo4j, sin ingesta, sin secretos en
logs, fail-closed conservado. `document_text` no se persiste ni altera el contrato público.

## Alcance para las versiones

Desde el commit de esta base (BASE_SHA de versiones) se crean V1–V4. Cada una parte del
mismo commit y no debe leer resultados de las demás antes de cerrar su diseño.
