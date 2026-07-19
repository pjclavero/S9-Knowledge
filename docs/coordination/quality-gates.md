# Gates de calidad

Toda entrega pasa **dos** revisiones del Supervisor. Estar en verde **no** basta.

## Revisión 1 — antes del PR (arquitectura)

- [ ] alcance acotado y aislado (diff previsible por ownership-map)
- [ ] contrato interno definido y versionado
- [ ] riesgos identificados (risk-register)
- [ ] estrategia de pruebas (unitario + regresión + hostil donde aplique)
- [ ] no toca áreas compartidas sin PR de integración
- [ ] modo sombra / dry-run (sin producción)

## Revisión 2 — antes del merge (evidencia)

- [ ] diff real coincide con el alcance declarado (0 ficheros fuera)
- [ ] resultados reproducibles (no solo "verde"): métricas adjuntas
- [ ] seguridad: sin base-provider en rutas protegidas, sin fuga de workspace,
      sin secretos, sin URLs productivas, sin escritura real
- [ ] regresión: suite completa + mutación; no degradación de RC6 ni de otras fuentes
- [ ] contaminación: 0 ficheros de otro equipo
- [ ] CI verde del **head exacto** (no reutilizar checks previos)
- [ ] dictamen: CONFORME / CON OBSERVACIONES / NO CONFORME / BLOQUEADO

## Gates específicos por equipo

### Equipo A (relaciones)
- contratos internos revisados · tests unitarios + regresión · benchmark
  reproducible (docs/41,42) · **no degradación de entidades** · ensemble en sombra ·
  casos obligatorios: negación (`Akodo no pertenece…` → no MEMBER_OF), rumor
  (`Se dice que…` → no hecho), temporalidad (`Fue vasallo… antes de…` → ámbito).

### Equipo B (plataforma)
- contrato + seguridad + límites · idempotencia · dry-run por defecto (import sin
  APPLY) · ejemplos **sanitizados** · suite hostil (zip bomb, path traversal, JSON
  gigante, CSV/GraphML malformado, hashes incorrectos, workspace ajeno) · export
  reproducible con manifest+hashes · **no exporta** contraseñas/sesiones/secretos/rutas.

### Equipo R (RC6)
- suite global verde · dry-run 0 escrituras · docs de estado coherentes · dictamen
  pre-RC6 · **no crea RC6**.

### Equipo Q (QA)
- mutación (los tests deben fallar al introducir un defecto conocido) · muestras
  hostiles capturadas · sin flaky sin justificar · cobertura de aislamiento
  workspace/secret/ID/roles/import-export/producción-bloqueada.

## Criterio de autoaprobación (heredado del motor, congelado)

- Precisión de candidatos autoaprobados ≥ 0.95 · relaciones inválidas
  autoaprobadas = 0 · candidatos sin evidencia autoaprobados = 0.
- No se autoriza ingesta real aunque el conjunto global supere umbrales si los
  autoaprobados no cumplen. **Primera ingesta: no autorizada en este programa.**
