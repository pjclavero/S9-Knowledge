# PR#95 · Fotografía Git y congelación del baseline (Fase 0)

**Fecha:** 2026-07-21 · **Repo:** `pjclavero/S9-Knowledge`

## SHA de referencia (BASE_SHA aprobado)

- `origin/main` = **`dcded31`** ("Add files via upload").
- Commit previo: `b7a796f` (Bloque 9, #94).
- `dcded31` **solo** añade `INFORME_CONSOLIDADO_PR95_Y_PROMPT_MULTIEQUIPO.md` (1828 líneas).
  **No toca el motor** → el código de relaciones en `dcded31` es idéntico a `b7a796f`.
- **BASE_SHA aprobado por el principal = `dcded31`.**

## Estado de ramas y PR

- **PR #95** — OPEN / draft (`worktree-docs-motor-extraccion-auditoria`), informe del motor (docs/52). Origen del problema.
- **PR #96** — OPEN / draft (limpieza del grafo). No se toca.
- Dependabot #50-57 — no se tocan.
- **Ramas `exp/pr95-*` previas: NINGUNA.** Empezamos limpio.

## Verificación del hecho técnico P0 — **CONFIRMADO**

Cadena reconstruida con código (`dcded31`) y demostrada con proveedor falso end-to-end:

1. `pairs.py:442` → `source_segment = seg["id"]` (el **ID**, no el texto).
2. `pipeline.py:_run_external` → no recibía `seg_text`.
3. `external_ai_shadow.py:254` → muestra `cand.source_segment` como **DOCUMENTO**.
4. `external_ai_shadow.py:319-338` → valida evidencia/offsets contra `cand.source_segment`.

**Demostración (offline):**

| | DOCUMENTO contiene TEXTO real | DOCUMENTO contiene ID |
|---|---|---|
| Antes del fix | ❌ False | ✅ True (bug) |
| Después del fix (base) | ✅ True | ❌ False |

El proveedor externo recibía el **ID del segmento** como "documento" y se le pedía extraer
evidencia literal con offsets dentro de él → imposible → rechazo garantizado. Esta es la
causa **dominante** del 27/27 de rechazos NVIDIA del PR #95, más básica que "anclaje mecánico".

## Garantías del baseline

`main` intacto · ninguna rama existente modificada · sin red · sin escritura Neo4j · sin
ingesta · sin bajar umbrales · dry-run/sombra/fail-closed conservados.
