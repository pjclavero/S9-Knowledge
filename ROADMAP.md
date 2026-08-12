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

## Puertas de calidad V3 y programa multi-partida

| Frente | Estado | Resultado / siguiente condición |
|---|---|---|
| Puerta 4 — cobertura del extractor (PRs #124-#130) | **CERRADA — PARCIAL** | Cobertura E2E dev 0.607 (≥0.60, conforme); recall autoaprobación SIMPLE 0.10 (≥0.70, no conforme); invariantes de precisión intactos. Ver `docs/v3/42-gate4-cierre-programa.md`. |
| Puerta 6 — factividad composicional (PRs #131-#133, #136) | **CERRADA — CONFORME CON RESERVAS** | Ratificado por el operador el 2026-08-05. Ver `docs/v3/46-gate6-cierre-programa.md`. |
| Acuerdo determinista∧NVIDIA (PRs #134-#135) | **MEDIDO** | Acuerdo activo 27/27 y 1.000 en corpus ampliado; piloto controlado aprobado, con auditoría humana 100%, gateado al despliegue de V3 y a la primera ingesta autorizada. |
| Multi-partida M0/M2/M3/M4/M5a (PRs #138, #140-#143) | **MERGEADOS** | Contratos, resolutor ciego, writer con ámbito estampado, divergencias locales del lore y selector de partida en el visor. |
| Multi-partida M1 | **BLOQUEADO** | Mapeo de ingesta Nextcloud→ámbito a la espera de que Nextcloud vuelva a estar disponible. |
| Multi-partida **M5b** (PRs #147, #150-#153) | **CERRADO EN `main` — NO DESPLEGADO** | Contrato `knowledge-visibility/v1`, estampado en el writer, migración fail-closed, cierre del defecto permisivo, M5c y cadena de autorización de extremo a extremo, tras siete rondas de revisión adversarial. Sobre el grafo legacy: **NO APPLY** (`docs/54-migracion-visibilidad-m5b.md`). Despliegue en el visor productivo **no autorizado**. |
| Multi-partida **M6** | **PENDIENTE** | *Housekeeping* del contenido de prueba del grafo. Es **operativo**, no de código: exige aprobación explícita del operador y se ejecuta al desplegar V3. |
| Carril D — QA y E2E de navegador (PR #154) | **COMPLETADO** | 148 pruebas Playwright en un check requerido; deja **11 defectos de aplicación abiertos** como `xfail(strict=True)` (`docs/60-qa-browser-e2e-visor.md`). Son defectos de código, no de documentación. |
| Saneamiento de fixtures (PR #157) | **COMPLETADO** | Dos nodos entregables nombraban en texto libre a un nodo `secret`; se corrigió el **dato**, no la barrera, con gate de regresión propio. |

Ninguno de estos programas implica despliegue en VM105: son estado de `main`
(bloque `development` de `docs/project-status.yaml`), no de producción.
**Estar mergeado en `main` no es estar desplegado.**

## Recuperación y credenciales

| Frente | Estado | Resultado / siguiente condición |
|---|---|---|
| Rotación de la credencial de Neo4j (2026-08-08) | **HECHA Y VERIFICADA** | La nueva autentica, la anterior no; grafo intacto (199/140). Ver `docs/53-recuperacion-y-credenciales-2026-08.md`. |
| Restore real de VM105 desde `vzdump` (2026-08-08) | **ENSAYADO** | Copia del 2026-08-02 restaurada a VMID de prueba sin red: `zstd` OK, 70 GiB en **8,2 min**, `e2fsck` limpio, arranque en 23 s, `auth.db` íntegro. **No** se validó el contenido semántico del grafo ni la validez funcional de los secretos. |
| RTO hasta servicio | **SIN MEDIR** | 8,2 min es la fase de restore, no el tiempo hasta volver a dar servicio. |
| Copia fuera del chasis | **NO EXISTE — P0 abierto** | Las copias viven en el mismo servidor físico que protegen. El hipervisor de la VM **no** es off-host. |
| Backup automático | **PROPUESTO, SIN ACTIVAR** | `deploy/propuestas/backup-automatico/`; su puerta exige ensayo de fallos destructivos y una segunda ejecución idempotente. |

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
