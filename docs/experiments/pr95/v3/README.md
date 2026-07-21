# PR#95 · Variante V3 — Selección por fragmentos

- **SHA base:** `92583f4` (`exp(pr95-base): corrige contrato DOCUMENTO/ID del evaluador externo (P0)`)
- **Rama:** `exp/pr95-v3-fragment-selection`
- **Capa:** EXPERIMENTAL, con flag `RelationExternalConfig.fragment_protocol_enabled` (default **OFF**).
- **Protocolo versionado:** `FRAGMENT_PROTOCOL_VERSION = "v1"`.

## Hipótesis

El protocolo clásico exige que el modelo externo devuelva `evidence_text` + offsets
exactos. Los LLM manejan mal esa tarea (parafrasean la cita, desalinean los offsets),
lo que provoca rechazos por `evidencia_inexistente` u `offsets_invalidos` aunque el
juicio sea correcto. **Si en vez de pedir offsets libres el sistema fragmenta el
documento en frases estables con IDs y el modelo solo ELIGE fragmentos por ID, la
literalidad de la evidencia queda garantizada por construcción y la tasa de rechazo
por offsets cae a cero.**

## Qué hace V3

1. **Fragmenta** el documento real en frases estables (`f-001`, `f-002`, …), IDs
   estables ante normalizaciones triviales, reutilizando `signals._sentence_bounds`.
2. **Presenta** los fragmentos con sus IDs en el prompt y pide un protocolo
   versionado: `{"candidate_id","fragment_ids","verdict","confidence"}`.
3. **Reconstruye** los offsets a partir de los `fragment_ids` elegidos (mapeo
   `fragment_id → (start,end)` sobre el documento real).
4. **Valida literalidad:** la evidencia reconstruida es subcadena literal del
   documento, con offsets coherentes.

## Ficheros

- `data-engine/app/relations/fragment_protocol.py` — módulo puro y determinista.
- `data-engine/app/relations/external_ai_shadow.py` — enhebrado del flag (prompt +
  validación alternativos cuando el flag está ON).
- `data-engine/app/tests/test_pr95_v3_fragment_selection.py` — 20 tests.
- `artifacts/pr95-variants/v3/` — benchmark A/B offline y resultados.

## Cómo activar (solo experimental)

```python
cfg = RelationExternalConfig(model="…", fragment_protocol_enabled=True)
evaluate_relation_external(cand, config=cfg, document_text=DOC)
```

Con el flag OFF (default) el comportamiento es **idéntico a la base**.

## Veredicto propuesto

**CONFORME** (ver `results.md`).
