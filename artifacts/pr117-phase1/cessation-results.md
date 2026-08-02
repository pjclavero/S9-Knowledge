# Resultados de cesación

- CES-01: cierre histórico, nueva aserción negativa y replay idempotente: PASS.
- CES-02: negación de cesación, cero supersesiones: PASS.
- CES-03: sin positiva previa, REVIEW y cero supersesiones: PASS.
- CES-04: múltiples activas, cubierto por regresión del planner: PASS.
- CES-05: hash incorrecto, rollback: PASS.
- CES-06: versión incorrecta, rollback: PASS.

Las operaciones vacías eran comportamiento esperado. El defecto estaba en el
test: afirmaba que el caso estaba anclado aunque el snapshot tenía cero
positivas activas, y además inspeccionaba solo el plan efectivo.
