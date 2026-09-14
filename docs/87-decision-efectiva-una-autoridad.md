# 87 · La decisión del operador cambia el motor — una sola autoridad

**Slice 2 · Corte 2.** Base: `origin/main` = `3d601524`.

Cierra el bloqueante **B-1** registrado en `docs/86`.

## El defecto

```
operador pulsa Aprobar
   -> el visor guarda la decisión
   -> data-engine NO la consume
   -> la pantalla parece confirmar éxito
   -> el producto NO cambia
```

Un **falso éxito de producto**: la decisión existía, era durable, y no cambiaba
nada. Sin un solo aviso.

## El trazado, antes de tocar

| | Escribe | Lee |
|---|---|---|
| `/v3/review/decide` | tabla `human_decisions` del SQLite del visor **y** `decisions.jsonl` | — |
| `ReviewService.queue` | — | `human_decisions` (vía `_active_decisions`) |
| `export_review_package` | `proposals/*.json` | nada del visor |
| `ingest_cli --apply` | `decisiones.json` | `decisiones.json` |
| `ingest_approved` | — | `output/reviews/<ws>/<src>/approved_payload.json` |

Dos hechos que decidieron el corte:

1. **El motor no tenía almacén para esta decisión.** `decisiones.json` son
   decisiones de **identidad de entidad** (`pipeline/entity_decisions.py`), otro
   objeto. `approved_payload.json` es la salida del **auto-decisor v2**, una
   decisión de máquina. Ninguno expresa «un humano aprobó esta propuesta».
2. **Dentro del visor la autoridad ya era única.** La cola filtra leyendo
   SQLite, y `decisions.jsonl` está degradado *en el propio código* a
   exportación de auditoría: *«JSONL remains a compatibility/audit export,
   never the authority»*.

## La autoridad elegida

> La tabla **`human_decisions`** del SQLite del visor.

No se aplica la preferencia por «el almacén que ya usa el motor» porque el motor
**no tenía ninguno** para este objeto. El motor pasa a ser **lector** de la
autoridad que ya existía; la UI no cambia de almacén.

No se crea almacén nuevo, no se sincroniza nada, no se copia ninguna decisión de
un fichero a otro. **El motor no lee `decisions.jsonl`**: leerlo «por
compatibilidad» sería exactamente la segunda autoridad que este corte elimina.

## El cambio

- **`data-engine/app/knowledge_v3/review_decisions.py`** (nuevo) — el **único**
  camino de lectura del motor. Mismo contrato de ruta que el visor
  (`S9K_V3_REVIEW_DATABASE_PATH`). Semántica de decisión activa idéntica a la
  del visor: la última gana, una supersedida no cuenta, y `undo` devuelve la
  propuesta a pendiente. **Falla cerrado**: un almacén ilegible levanta
  `ReviewDecisionsError`, porque un almacén que no se puede leer no es un
  almacén vacío.
- **`review_export.py`** — antes de publicar, toda propuesta ya resuelta por una
  persona (`APPROVE`/`REJECT`) deja de presentarse como reclamación pendiente y
  queda anotada en `resolved` con la decisión que la resolvió.

## `undo`

Entra en el corte porque es el **mismo modelo de decisión**: `undo_last()` es un
`record()` con `supersedes_decision_id` y `correction.undo`. Leer las decisiones
activas sin respetarlo haría que deshacer no deshiciera nada para el motor. No
toca apply ni rollback de conocimiento, que quedan fuera (B-2 y B-3 siguen
abiertos).

## El orden importa

El `303` de «decisión guardada» se emite **después** de que la autoridad haya
confirmado la persistencia. Si el almacén falla, el operador ve un error; nunca
«Aprobado» seguido de nada. Hay un caso que lo fija rompiendo el almacén a
propósito.

## Lo que NO se tocó

Apply, rollback de conocimiento, rediseño visual, `authz/`, `policies/`,
producción y VM105. No se añadió ninguna capacidad a
`chassis.WRITE_CAPABILITIES`: la escritura sigue viviendo donde ya vivía
(`/v3/review/decide`), fuera del espacio de URL de los paneles.
