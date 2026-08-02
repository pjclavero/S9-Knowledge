# Validación final V3 — resumen por puertas

Rama `integration/v3-final-core-validation`. Campaña de tres fases: medida →
ciclo de corrección → **re-medida**. Este documento refleja el estado **después**
de la corrección.

Todos los números salen de una corrida real. Ninguno está estimado, y ningún
umbral se ha movido para que un gate saliera verde.

---

## Cuadro de mando

| Puerta | Veredicto | Nota de una línea |
|---|---|---|
| **3 — Endurecimiento del planner** | **CONFORME** | P3-1 corregido; el xfail es hoy regresión verde. |
| **4 — Negaciones E2E en sombra** | **NO CONFORME** | Sin cambios tras la corrección; el techo es cobertura, no política. |
| **5 — Autoridad local** | **CONFORME** | 5/5 gates duros, con un fallo de proveedor real observado en vivo. |
| **6 — No-factividad** | **NO CONFORME** | Mejora real (4→2 violaciones) pero **no generaliza**: 0,231 fuera del corpus. |
| **6B — Revisión humana** | **CONFORME** | Feed real, append-only, glosario intacto. |
| **7 — Neo4j real** | **BLOQUEADA / lista** | Tests implementados; **dos defectos la habrían tumbado**. |

---

## Puerta 4 — Negaciones (NO CONFORME)

Re-medida tras corregir D-G1. **Idéntica, byte a byte.**

| Gate | Umbral | Antes | Ahora | Estado |
|---|---|---|---|---|
| 0 aristas positivas falsas desde negación | 0 | 0 | 0 | **CONFORME** |
| 0 cesaciones falsas desde «no dejó de» | 1.0 | 1.0 | 1.0 | **CONFORME** |
| Evidencia anclada | 1.0 | 1.0 | 1.0 | **CONFORME** |
| Precisión CESSATION destructiva | 1.0 | — | — | **NO EVALUABLE** |
| Precisión de alcance destructivo | 1.0 | — | — | **NO EVALUABLE** |
| Alcance global | ≥ 0.95 | 0.875 | **0.875** | **NO CONFORME** |
| Recall autoaprobación SIMPLE | ≥ 0.75 | 0.10 | **0.10** | **NO CONFORME** |

Que no se moviera era lo esperado: D-G1 añadió vocabulario de rumor e hipótesis,
y el único fallo de alcance no es de vocabulario. Alcance real **7/8 en lo
cubierto** y **7/56 sobre la batería entera (12,5 %)**.

Las dos precisiones destructivas siguen sin población, y ahora sabemos **por
qué**: el hallazgo **F7-1** hace `SUPERSEDE_ASSERTION` inalcanzable desde el
pipeline. No es que al corpus le faltaran casos destructivos; es que el sistema
no puede emitir ninguno por esa ruta.

---

## Puerta 5 — Autoridad local (CONFORME)

| Gate | Observado | Estado |
|---|---|---|
| 0 claims sin evidencia literal | 0 | **CONFORME** |
| 0 predicados fuera de ontología | 0 | **CONFORME** |
| 0 decisiones efectivas alteradas por la sombra | 0 | **CONFORME** |
| 0 operaciones sombra aplicables | 0 | **CONFORME** |
| 0 escrituras decididas por proveedor | 0 | **CONFORME** |

Los dos gates de sombra están respaldados por una garantía **estructural**
verificada con tests: `ShadowDecisionRecord` es `frozen` y solo admite
`str`/`bool`/`tuple[str, ...]`, así que no existe corrida capaz de meter en él
una operación aplicable.

**Evidencia con proveedor real, no inducida:** durante la puerta 6, Ollama se
cayó solo (2 de 4 episodios al *timeout* de 600 s). El sistema emitió
`PROVIDER_UNAVAILABLE`, abstuvo con evidencia anclada, no escribió nada y siguió
con el resto del lote.

Salvedad: la cobertura de la sombra sigue siendo **0 registros** (exige carril
semántico). Está demostrado que **no puede** alterar ni escribir; **no** está
demostrado que la comparación sombra-vs-efectiva sea útil.

---

## Puerta 6 — No-factividad (NO CONFORME)

Re-medida con los cues corregidos. Detalle completo en `gate6-findings.md`.

| | Antes | Después |
|---|---|---|
| Violaciones NVIDIA | 4 | **2** |
| Carril NVIDIA vacuo | sí | **no** (6 hechos en controles) |
| Acuerdo de acción (`det`+`combined`+`nvidia`, 24 frases) | no medible | **79,17 %** |

**Lo que decide el veredicto no es la mejora, sino la sonda de generalización.**
30 frases con marcadores no-factivos ausentes de `cues.py` y de `cases.json`:

- no-factivas leídas como hecho del mundo: **20/26**
- acierto en no-factividad: **0,231**
- controles positivos: **4/4**

De las 4 violaciones desaparecieron **exactamente las 2 cuyas frases literales se
añadieron** al vocabulario. La política de factualidad es una **tabla de frases**,
no una comprensión composicional.

Y el carril de proveedor **no es determinista**: entre las dos corridas cambiaron
7 de 24 casos con entrada idéntica; sólo 2 los explica el parche. **Suelo de
ruido 20,8 % > efecto medido 8,3 %.** Una comparación antes/después de una sola
corrida no puede separar el arreglo del muestreo.

---

## Puerta 6B — Revisión humana (CONFORME)

Feed servido desde propuestas **reales** del pipeline (antes de esta campaña
ningún test ejercitaba `review_proposals_dir`), append-only, control de acceso, y
hash del glosario **idéntico** antes y después del flujo completo, comprobado por
dos vías independientes.

Salvedad **H-1**: `proposal_id` y `proposal_hash` son 1:1, así que un cambio de
contenido da `ReviewError 400` en vez de `STALE_REVIEW`. Sigue siendo seguro —no
escribe—, pero el código no describe la situación.

---

## Puerta 7 — Neo4j real (BLOQUEADA, tests listos)

`data-engine/app/tests/test_knowledge_v3_e2e_neo4j_real.py`, 9 tests tras
`S9K_WRITER_NEO4J_REAL=1`. **No ejecutados aquí** (sin Docker); verificado que
colectan limpiamente.

Cubren E2E-01, E2E-12 y la cesación del encargo: cierre de `valid_to` con
supersesión, historia conservada, idempotencia y bloqueo por hash distinto; más
la negación de cesación (0 cierres).

**Dos defectos encontrados al prepararla** —ambos reproducibles sin Docker— que
la habrían tumbado en VM105:

### F7-2 — el plan del motor no es ejecutable

`planner.py` mete `assertion_id` dentro del payload de `CREATE_ASSERTION`
(`PAYLOAD_FIELDS` empieza por ahí) y `cypher.py` lo rechaza como propiedad
reservada (`RESERVED_PROPS`) → `EXEC_UNSUPPORTED_PAYLOAD`, `OUTCOME_ABORTED`,
cero escrituras.

Por qué sobrevivió a toda la batería: **`simulate_plan` no llama a `safe_props`**,
así que en dry-run el mismo plan sale `SIMULATED` (hay un test de control que lo
demuestra), y todos los tests del writer que *aplican* construyen el payload a
mano **sin** `assertion_id`. Nadie había aplicado nunca un plan del motor.

> Es el patrón «funciona en dry-run, falla en apply». E2E-01 habría fallado en
> VM105 en la primera operación.

### F7-1 — una cesación no puede cerrar nada por la ruta real

`bridge.assertion_from_edge` construye la `SnapshotAssertion` **sin**
`state_hash` —las entidades sí lo derivan, vía `SnapshotEntity.of`— y
`negation.py` se niega, con razón, a cerrar una vigencia sin ancla de
concurrencia: `CESSATION_TARGET_UNANCHORED`, `supersedes=None`.

Reproducción: afirmar y luego cesar sobre el **mismo** pipeline.

---

## Estado de la suite

| Árbol | Resultado |
|---|---|
| `data-engine/app` | **4762 passed, 35 skipped, 5 xfailed, 0 failed** |
| `viewer` | 418 passed, 1 skipped |

**Skips:** 36 en total (35 en `data-engine` + 1 en `viewer`), **0 accidentales**,
auditados por cuatro vías de pérdida silenciosa —no leyendo motivos, que es como
un skip accidental se esconde.

**La mitad exacta de los skips es Neo4j:** 18 de 36 (9 de
`test_knowledge_v3_writer_neo4j_real.py` + 9 de la puerta 7). Dicho sin adornos:
`apply=True`, las transacciones y la idempotencia **contra un grafo de verdad no
se ejecutan en este árbol**. Es justo donde viven F7-2 y F7-1, y no es
casualidad: lo que no se ejecuta es lo que esconde defectos.

Los dos `skip` que este fichero tenía prometiendo «lo ejecuta el coordinador»
han desaparecido: los tests existen. En su lugar queda un test que **sí corre** y
comprueba que las implementaciones siguen ahí, para que la promesa no se pudra.

**Reproducibilidad:** `PYTHONHASHSEED=1,7,42,123`, 12 ejecuciones, cero
variación intra-sonda.
