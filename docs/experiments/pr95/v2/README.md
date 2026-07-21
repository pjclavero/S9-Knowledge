# PR#95 · Variante V2 — Realineamiento determinista de la evidencia

**Base SHA:** `92583f4`
**Rama:** `exp/pr95-v2-deterministic-realignment`
**Flag:** `RelationExternalConfig.realignment_enabled` (default **OFF**)

## Hipótesis

La validación estricta del evaluador externo (`relations/external_ai_shadow._validate_verdict`)
rechaza la `evidence_text` del modelo si no es **subcadena literal** del documento real o si
los offsets no casan exactamente. Los modelos parafrasean levemente (NFC/NFD, comillas
tipográficas, colapso de espacios, CRLF vs LF) y caen sin que la relación sea falsa.

**Hipótesis:** un realineamiento **determinista y acotado** (sin semántica) puede recuperar
esa evidencia recomputando offsets sobre el texto **real**, manteniendo la garantía dura de
que la evidencia final es siempre una **rodaja literal** del documento, sin abrir un vector
para aceptar evidencia inventada.

## Qué se entrega

- `relations/evidence_realignment.py` — módulo puro con la escalera de realineamiento
  (mapa reversible, umbral predeclarado, rechazo por ambigüedad, cotas anti-DoS).
- Flag `realignment_enabled` en `RelationExternalConfig` (default OFF) enhebrado hasta
  `_validate_verdict`. **Sin el flag, el comportamiento es idéntico a la base.**
- `tests/test_pr95_v2_deterministic_realignment.py` — 27 tests (unidad + integración +
  seguridad + no-regresión).
- `tests/pr95_v2_ab_benchmark.py` — banco offline A/B con fixtures parafraseados.
- `artifacts/pr95-variants/v2/{ab_metrics.json, ab_rows.json}` — métricas reales.

## Escalera (resumen)

```
exacto  →  normalizado-exacto  →  fuzzy acotado a ventana  →  rechazo (ambigüedad/umbral)  →  vuelta al original
```

Umbral predeclarado: `REALIGN_SCORE_THRESHOLD = 0.82`. Ambigüedad (dos alineamientos
equivalentes ≥ umbral) ⇒ **rechazo fail-closed**.

## Documentos

- [design.md](design.md) — arquitectura de la escalera, mapa reversible, umbrales.
- [test-plan.md](test-plan.md) — matriz de casos y verificación anti-gaming.
- [results.md](results.md) — recuentos de suites y métricas A/B reales.
- [security.md](security.md) — prompt injection, false alignment, Bidi, payload grande.
- [limitations.md](limitations.md) — límites, rollback y veredicto propuesto.

## Rollback

Cambio detrás de flag default OFF. Rollback = no activar el flag (comportamiento base) o
eliminar `evidence_realignment.py` y las tres líneas de enhebrado en
`external_ai_shadow.py`. Sin migraciones, sin estado persistente, sin efectos externos.

## Veredicto propuesto

**CONFORME** (ver [results.md](results.md) y [limitations.md](limitations.md)).
