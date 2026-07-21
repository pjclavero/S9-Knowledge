# PR#95 V4 — Limitaciones, etapas reales vs diseño, rollback, veredicto

SHA base: `92583f4`.

## Etapas: reales (implementadas y probadas) vs diseño

Las **7 etapas estan implementadas** y son desactivables. Distingo su MADUREZ por
evidencia de efecto:

| # | Etapa | Estado | Efecto medido |
|---|-------|--------|----------------|
| 1 | Ranking / top-k | **REAL, con ablation en corpus** | acota candidatos (52->16); invariante `len <= top_k` probado |
| 3 | Predicado / direccion | **REAL, con ablation en corpus** | strict_f1 0.2075->0, predicate 0.2558->0, direction 0.6279->0.1395 |
| 4 | Evidencia | **REAL, con ablation en corpus** | evidence_correct 0.9070->0.0233, offsets 0.9302->0.8140 |
| 6 | Temporal / epistemica | **REAL, con ablation en corpus** | epistemic_correct 0.8605->0.8140 (seguridad) |
| INT | Inter-frase (cross_sentence) | **REAL, con ablation en corpus** | n_preds 52->144; test intra->inter |
| 5 | Verificacion | **REAL, efecto solo en test unitario** | rechaza cobertura incompleta; sin efecto agregado en B1 con evidencia ON |
| 7 | Consenso | **REAL, efecto solo en test unitario** | consenso -> `None`; no mueve las metricas estructurales de B1 |
| 2 | Hipotesis estructural | **REAL, bajo impacto** | el `score` solo influye en el ranking top-k; no cambia el candidato final |

No hay etapas "solo diseño sin implementar": todas corren. Lo que queda como
**diseño no explotado** es el *proveedor de sintaxis fuerte* (spaCy/stanza) como
fuente alternativa de la etapa estructural: la interfaz lo admite por inyeccion,
pero NO se implementa un adaptador concreto (seguiria siendo opcional y sin
dependencia obligatoria).

## Limitaciones honestas

- **Verificacion y consenso** no tienen efecto medible en las metricas de calidad
  estructural del corpus B1 tal como estan definidas. Su valor se demuestra a
  nivel unitario. No se debe leer la tabla como "estas etapas no sirven", sino
  como "estas metricas no las capturan".
- **Top-k por segmento**: el corpus B1 tiene 1 segmento por fuente, asi que
  `top_k=1` deja 1 candidato por fuente. En documentos multi-segmento el acotado
  es por segmento (no global); un acotado global queda como trabajo futuro.
- **Ranking**: el `score` reutiliza la confianza heuristica `_confidence`; no es un
  ranker aprendido. Suficiente para acotar de forma determinista, no para maximizar
  recall bajo presupuesto.
- **Cross-sentence** aumenta mucho el ruido (precision baja). No debe activarse sin
  una etapa de filtrado adicional (no incluida).

## Rollback

- **Inmediato / sin codigo**: no pasar `hybrid_stages` (o `None`). El pipeline usa
  el camino clasico literal; salida byte-identica a la base. La feature es inerte
  por defecto.
- **Retirada de codigo**: revertir el commit de la rama elimina
  `relations/hybrid/`, los tres campos de `PipelineConfig` y la bifurcacion de
  `_process_segment`. No hay migracion de datos ni estado persistido (dry-run).

## Compatibilidad

- `hybrid_stages=None`: `result_hash` identico a la base.
- `hybrid_stages={}`: results/documents/summary identicos a la base (verificado en
  test y en corpus B1). Solo cambia el bloque de config (eleccion explicita).
- Contrato de 20 campos intacto; consumidores no afectados.

## Veredicto propuesto: **CONFORME**

- Abstracciones + orquestador con flags (compatibilidad byte a byte por defecto): OK.
- Ablation REAL de 5 etapas con efecto medible en corpus + 2 etapas con efecto
  unitario, todas implementadas y honestamente clasificadas.
- Seguridad preservada; etapa sensible endurecida y documentada.
- Suites obligatorias verdes (903 / 48 / 13) + 24 tests nuevos.
- Anti-gaming: 2 mutaciones confirmadas y revertidas, sin skip/xfail/umbral bajado.

Sin acciones sobre produccion. Entrega = commit en la rama; sin push/PR/merge.
