# ROADMAP — S9 Knowledge

El estado de producción es autoritativo en
[`docs/project-status.yaml`](docs/project-status.yaml). El plan técnico vigente
del repositorio es
[`docs/v3/32-plan-consolidado-extractor-y-nucleo.md`](docs/v3/32-plan-consolidado-extractor-y-nucleo.md).
V3 está en `main`, pero todavía no está desplegada: producción continúa en RC5.1.

## V3 (vigente)

Estados: **COMPLETADO · PENDIENTE DE DECISIÓN · PENDIENTE · GATEADO**.

| Frente | Estado | Resultado / siguiente condición |
|---|---|---|
| Rediseño integral V3 (PR #110) | **COMPLETADO** | `knowledge_v3` mergeado en `main`; contratos congelados `v3-contracts-frozen-1.0.0`. |
| Lote 1 (PR #111) | **COMPLETADO** | Extractor y motor endurecidos sin cambiar la política observable. |
| Lote 3 (PR #112) | **COMPLETADO** | Reconciliador reproducible y validado a escala; D-R recupera 8 claims correctos frente a 0 de D. |
| Lotes 2 y 2b (PR #113) | **COMPLETADOS** | Política graduada de negaciones y temporalidad implementada tras flags **OFF**. |
| Lote 6 (PR #114) | **COMPLETADO** | Replicabilidad reforzada: secretos, despliegue genérico, rollback conjunto, restore periódico y workspaces. |
| Lote 4 | **PENDIENTE DE DECISIÓN** | El operador debe fijar la política común de condicionales. |
| Lote 5 | **PENDIENTE DE DECISIÓN** | El operador debe definir el flujo y los umbrales de creación de entidades antes de relajar `LINK_EXISTING`. |
| Encargos D, E, G y H del doc 30 | **PENDIENTES** | Proveedores con recambio, eje temporal de campaña, observabilidad y registro del bucle humano. |
| Contexto episódico inter-episodio | **PENDIENTE POR DISEÑO** | Se mantiene correferencia intra-episodio; la evidencia aprobable sigue anclada al episodio actual. |
| Activación de política graduada | **GATEADA** | Los flags siguen **OFF** hasta completar medición en sombra y aceptar los criterios de activación. |
| Despliegue V3 | **PENDIENTE** | No se ha desplegado en VM105; RC5.1 continúa activa. |

Las decisiones de producto de los Lotes 4 y 5 no se presuponen. Tampoco se
presenta la implementación de una política tras flags como una autorización para
activarla o escribir en producción.

## Legacy (v1/v2)

La línea v1/v2 explica la release RC5.1 que sigue desplegada, pero ya no es el
camino de desarrollo principal. Quedan como hitos históricos:

- pipeline de review/ingest, benchmarks del extractor híbrido y revisión humana;
- visor, login, roles, despliegue por releases, healthchecks y backup/restore;
- writer con doble guard y primera ingesta real no autorizada;
- external AI en sombra y burst posterior pendiente en aquella arquitectura.

Documentación histórica:

- [Dosier y checklist](docs/archivados/project%20dossier%20and%20checklist.md)
- [Estado de RC5.1](docs/archivados/02-current-state.md)
- [Arquitectura](docs/archivados/01-architecture.md)
- [Fases históricas](docs/archivados/03-phases.md)
- [Índice completo de archivados](docs/archivados/INDEX.md)
