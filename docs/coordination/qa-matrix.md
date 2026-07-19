# Matriz de QA transversal — Equipo Q

El Equipo Q **no corrige producto**: reproduce, asigna severidad, identifica al
equipo propietario, bloquea el gate y propone un PR correctivo separado.

## Dimensiones × carriles

| Dimensión | Equipo A (relaciones) | Equipo B (plataforma) | Equipo R (RC6) |
|-----------|----------------------|-----------------------|----------------|
| Aislamiento por workspace | pares no cruzan workspace | export/import por workspace | regresión de fuga |
| Secret / narrator / futuro / party | relaciones no exponen ocultos | export respeta visibilidad | 34 permisos + 14 legacy |
| Acceso por ID oculto → 404 | — | import no revela por ID | E2E |
| Roles (viewer/reviewer/admin/anon) | — | export según rol | E2E |
| Import/export idempotencia | — | dry-run repetible | — |
| Imágenes hostiles / docs corruptos | — | zip bomb, path traversal, JSON gigante, CSV/GraphML malformado | — |
| Archivos grandes / memoria / timeout | latencia LLM | límites de import/OCR | — |
| Concurrencia / repetición | 3 ejecuciones LLM, variabilidad | dos revisores, stale hash | E2E |
| Rollback / no escritura | 0 escrituras en sombra | import sin APPLY | dry-run 0 escrituras |
| Seguridad de rutas | — | path traversal, `/opt` redacción | secret scan |
| Producción bloqueada | cortafuegos | cortafuegos | 13 tests prod-block |
| Compatibilidad de schemas / migración | contrato interno v1 | export/import compat | contratos v1 |

## Pruebas de mutación obligatorias (deben FALLAR el test)

| Mutación | Test que debe capturarla | Equipo |
|----------|--------------------------|--------|
| desactivar filtro de workspace | acceso a workspace ajeno → 404 | R/Q |
| bypass en "ver como personaje" (admin_full) | view-as-character filtra | R/Q |
| ignorar stale hash | decisión obsoleta rechazada | R/Q |
| permitir host productivo | prod-block | Q |
| simular escritura Neo4j en DRY_RUN | dry-run 0 escrituras | Q |
| exportar un secreto | export no incluye secretos | Q/B |
| importar sin dry-run por defecto | import no aplica por defecto | Q/B |
| aceptar relación sin evidencia | relación sin evidencia no autoaprobada | Q/A |
| aceptar `HAS_FOUGHT` contra Location | validación ontológica rechaza | Q/A |

(Las cinco primeras ya están cubiertas y verificadas en `main@6d6c21f`,
mutación 5/5 en la integración de #41.)

## Muestras hostiles (Equipo B)

zip bomb · path traversal (`../`, rutas absolutas) · JSON gigante · CSV malformado ·
GraphML con entidades externas · hashes incorrectos · schema desconocido · IDs
duplicados · workspace ajeno. Cada una debe **abortar** el import con estado
`INVALID`/`CONFLICT`, nunca alcanzar producción.

## Métricas de Q

mutaciones capturadas · muestras hostiles capturadas · regresiones detectadas ·
flaky tests · falsos positivos · huecos de cobertura. Se reportan por ola.
