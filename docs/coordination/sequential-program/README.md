# Programa Secuencial de Calibración de Relaciones — Coordinación

Este directorio define el **programa de ejecución secuencial multiagente con puertas de
calidad** para la calibración de la extracción de relaciones de S9 Knowledge. Es
documentación de coordinación: **no contiene código funcional** y no altera producción.

## Propósito

Coordinar una secuencia de bloques **completamente independientes**, cada uno con su propia
rama, worktree, agentes, pruebas, Supervisor, PR, merge y validación posterior en `main`.
Ningún bloque agrupa a otro en la misma rama o PR.

## Estado autoritativo de partida (verificado 2026-07-19)

| Referencia | SHA | Nota |
|---|---|---|
| `origin/main` | `424a0358ae321a254a6acc38d683b991d5cb80fe` | CI verde (CI + Supply Chain Security) |
| `release/rc6-candidate` | `15ae1d4f364b19e601bbe32a5e3904e889c8bf65` | **INMUTABLE** — no se toca |

Producción: RC5.1 activa en VM105 · Neo4j 199 nodos / 140 relaciones · `S9K_ALLOW_REAL_INGEST=off`.
**Intacta y de solo lectura para todo el programa.**

## Flujo obligatorio de cada bloque

```text
Auditoría → diseño → implementación → tests → Supervisor independiente
→ PR → CI de la PR → merge → CI post-merge de main → informe → checkpoint
→ autorización del siguiente bloque
```

El siguiente bloque solo comienza cuando **todas** estas condiciones se cumplen:

1. Supervisor emite `CONFORME`;
2. la PR está fusionada;
3. el CI de `main` posterior al merge está completamente verde;
4. la suite específica del bloque pasa desde un worktree limpio basado en `origin/main`;
5. producción no ha sido afectada;
6. el Organizador publica el checkpoint del bloque.

Nunca se continúa "por inercia". Ante cualquier fallo: detener, corregir, repetir.

## Índice de documentos

| Documento | Contenido |
|---|---|
| [`program-board.md`](program-board.md) | Tablero de estado de los 10 bloques y `AUTHORIZED_BLOCK` |
| [`block-state-machine.md`](block-state-machine.md) | Máquina de estados y transiciones permitidas |
| [`ownership-map.md`](ownership-map.md) | Propiedad de rutas y áreas compartidas |
| [`quality-gates.md`](quality-gates.md) | Puertas A–H obligatorias |
| [`checkpoint-template.md`](checkpoint-template.md) | Plantilla de checkpoint por bloque |
| [`risk-register.md`](risk-register.md) | Registro de riesgos y mitigaciones |
| [`integration-order.md`](integration-order.md) | Orden y dependencias de integración |

## Roles

- **Organizador**: única autoridad para iniciar/cerrar bloques, autorizar el siguiente,
  gestionar áreas compartidas y emitir checkpoints. No implementa cambios funcionales grandes.
- **Auditor**: inspecciona, define alcance y tests. No implementa.
- **Implementador**: trabaja en rama y worktree exclusivos, dentro del alcance.
- **Agente de pruebas**: pruebas negativas/hostiles, determinismo, aislamiento, mutaciones.
- **Supervisor independiente**: revisa el diff completo y emite dictamen. No puede ser el
  auditor, implementador ni tester del mismo bloque. Solo `CONFORME` permite el merge.

## Prohibiciones absolutas del programa

Modificar VM105 · Neo4j productivo · `auth.db` · `jobs.db` · reiniciar servicios · desplegar ·
ingesta real · crear tag/Release RC6 · modificar `release/rc6-candidate` · importación `APPLY` ·
procesar corpus privado sin autorización · imprimir secretos · usar endpoints productivos por defecto.
