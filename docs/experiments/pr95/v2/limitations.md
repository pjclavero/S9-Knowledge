# V2 · Limitaciones, rollback y veredicto

**Base SHA:** `92583f4`

## 1. Limitaciones conocidas

- **Solo texto determinista.** No hay recuperación semántica (ni embeddings ni LLM). Una
  paráfrasis fuerte con vocabulario distinto no se recupera **por diseño** (y no debe).
- **Dependiente del hint para desambiguar repeticiones.** Sin offsets propuestos por el
  modelo, dos ocurrencias equivalentes se rechazan por ambigüedad (fail-closed). Es la
  decisión segura, pero puede rechazar casos que un humano resolvería por contexto.
- **Umbral fijo global.** `REALIGN_SCORE_THRESHOLD = 0.82` es un único valor calibrado
  sobre fixtures sintéticos; no se ajusta por longitud de evidencia ni por idioma. Un
  corpus real podría sugerir recalibrarlo (queda como trabajo futuro, con banco A/B).
- **Fuzzy basado en `difflib`.** El score (ratio de secuencia) es una heurística de forma,
  no de significado. Es adecuado para variaciones tipográficas y erratas, no para
  reordenamientos amplios.
- **Banco A/B sintético.** Las métricas provienen de fixtures parafraseados que **imitan**
  respuestas típicas de modelo, no de un proveedor real (el corpus B1 va sin proveedor).
  Los números son reales sobre ese banco, pero su representatividad frente a producción es
  limitada hasta medir con tráfico real (en modo sombra).
- **`realignment_success_rate = 0.50`** mide recuperados sobre *todos* los rechazados-OFF,
  que incluyen 4 negativos verdaderos que no deben recuperarse; sobre los casos
  legítimamente recuperables la tasa es 4/4. Ver [results.md](results.md).

## 2. No incluido (fuera de alcance V2, por consigna)

- No se toca el anclaje heurístico (V1), fragment IDs (V3) ni el parser (V4).
- No se generan pares, no cambia la review policy, no se bajan thresholds base.
- Sin red, sin escritura Neo4j, sin activar ingesta.

## 3. Rollback

- **Inmediato:** dejar `realignment_enabled=False` (default). El comportamiento es
  **exactamente** el de la base `92583f4` (verificado por los tests de no-regresión).
- **Total:** eliminar `relations/evidence_realignment.py` y revertir el enhebrado en
  `relations/external_ai_shadow.py` (el flag en la dataclass, el parámetro y bloque de
  realineamiento en `_validate_verdict`, y las 3 claves de trazabilidad del verdicto
  saneado). Sin migraciones, sin estado persistente, sin efectos externos.

## 4. Veredicto propuesto

**CONFORME.**

Justificación:
- Escalera determinista y acotada implementada con mapa reversible, umbral predeclarado y
  rechazo por ambigüedad fail-closed.
- Invariante duro cumplido: la evidencia final es siempre rodaja literal del documento
  real con offsets coherentes (`literal_evidence_rate = 1.0` en OFF y ON).
- Default OFF ⇒ base intacta (no regresión: 1028 / 48 / 13 verdes; 27 nuevos verdes).
- Seguridad demostrada: prompt injection, false alignment, Bidi y payload grande cubiertos
  y probados; el realineamiento no puede introducir evidencia inventada.
- Anti-gaming: 2 mutaciones provocan fallos reales; revert sin residuo; sin skip/xfail.

Reserva: la calibración del umbral y la representatividad del banco A/B deben revalidarse
con tráfico real en modo sombra antes de considerar activar el flag en producción (acción
gateada a confirmación explícita del operador; despliegue por s9-sysadmin).
