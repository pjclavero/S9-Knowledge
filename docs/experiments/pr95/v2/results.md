# V2 · Resultados

**Base SHA:** `92583f4` · Python `3.13.5` · todo OFFLINE (proveedor falso, sin red, sin escritura).

## 1. Suites (recuentos reales)

| Suite | Comando | Resultado |
|-------|---------|-----------|
| relation/external (regresión global) | `pytest tests/ -k "relation or external" -q` | **1028 passed**, 440 deselected |
| calibración Bloque 9 | `pytest tests/test_relation_calibration_final_quality_block9.py -q` | **48 passed** |
| contrato documento externo | `pytest tests/test_relation_external_document_contract.py -q` | **13 passed** |
| **V2 realineamiento (nueva)** | `pytest tests/test_pr95_v2_deterministic_realignment.py -q` | **27 passed** |

La suite base (`-k "relation or external"`) mantiene **1028 passed** igual que antes del
cambio (los 27 tests V2 quedan fuera de ese filtro por el nombre del fichero; se ejecutan
aparte). No hay regresión.

## 2. Anti-gaming (mutación + revert)

| Mutación | Cambio | Tests que fallan | Tras revert |
|----------|--------|------------------|-------------|
| 1 · umbral | `REALIGN_SCORE_THRESHOLD` 0.82 → 0.05 | 4 (paráfrasis fuerte, inyección, false alignment, integración fuerte) | 27 passed |
| 2 · ambigüedad | desactivar rechazo por empate | 2 (repetición sin hint, ambigüedad equidistante) | 27 passed |

Revert verificado por `grep`: `REALIGN_SCORE_THRESHOLD = 0.82` y reglas de ambigüedad
intactas. Sin residuo.

## 3. Métricas A/B (offline, reales)

Fuente: `artifacts/pr95-variants/v2/ab_metrics.json` (11 fixtures parafraseados).
Generado por `tests/pr95_v2_ab_benchmark.py`.

| Métrica | OFF (base) | ON (realineamiento) |
|---------|-----------:|--------------------:|
| Aceptados | 3 / 11 (0.2727) | 7 / 11 (0.6364) |
| `literal_evidence_rate` (de los aceptados) | **1.0** | **1.0** |
| `realignment_success_rate` | — | **0.50** (4 recuperados / 8 rechazados-OFF) |
| `ambiguous_realignment_rate` | — | **0.0909** (1 / 11) |

Casos **recuperados** por el realineamiento (rechazados con OFF, aceptados con ON):
`nfd_acentos`, `comillas_tipograficas`, `espacios_tab`, `parafrasis_leve`.

### Lectura honesta

- El invariante de literalidad se mantiene en **1.0** en ambos modos: el realineamiento
  **nunca** introduce evidencia que no sea rodaja literal del documento real.
- De los 8 casos rechazados con OFF, 4 son **recuperables legítimamente** (variaciones de
  forma) y se recuperan; los otros 4 (`parafrasis_fuerte`, `falso_alineamiento`,
  `ambiguo_equidistante`, `inyeccion_prompt`) **deben** seguir rechazados por diseño y así
  ocurre. Por eso `realignment_success_rate = 0.50`: la mitad del conjunto "rechazado-OFF"
  son negativos verdaderos que no deben recuperarse. La tasa de recuperación sobre los
  casos *legítimamente recuperables* (4) es **4/4 = 1.0**.
- No hay falsos positivos: ningún caso hostil o de paráfrasis fuerte pasa la puerta con ON.

## 4. Reproducir

```
cd data-engine/app
python3 -m pytest tests/test_pr95_v2_deterministic_realignment.py -q
python3 tests/pr95_v2_ab_benchmark.py   # regenera artifacts/pr95-variants/v2/*.json
```
