# 32 — Plan consolidado: extractor y validación del núcleo V3

Fecha: 2026-07-30 · Estado: **lotes técnicos completados; pendientes decisiones
de producto (Lotes 4 y 5)**

Consolida dos fuentes: la revisión externa del extractor (8 hallazgos, todos
verificados contra `main` línea a línea) y los pendientes de validación del
núcleo V3 (docs 21/22, 18/19, encargos D-H del doc 30).

## Hallazgos verificados de la revisión del extractor

| # | Sev | Hallazgo | Evidencia |
|---|-----|----------|-----------|
| 1 | P0 | Candidatos se recortan y se usa `preds[0]` confiando en el orden del proveedor | `extraction/payload.py:897,930,1064` |
| 2 | P0 | Todo el carril semántico nace `force_review=True` | `semantic.py:343`, `ollama.py:212`, `external.py:241` |
| 3 | P0 | El determinista marca toda negación para revisión | `extraction/deterministic.py:643-649` |
| 4 | P1 | Condicionales: el semántico no emite claim, el determinista emite `HYPOTHETICAL` en revisión | `deterministic.py:623` vs contrato del semántico |
| 5 | P1 | `negation_kind`, `temporal_resolution_required`, `direction_unresolved`, `untrusted_origin` viajan como strings en `metadata` sin frontera tipada | `engine/negation.py:79` y 5 lecturas más |
| 6 | P1 | `LOCAL_ONLY` + `ollama_client` no activa Ollama; "local" se confunde con "determinista sin LLM" | `pipeline/config.py:135-137` |
| 7 | P2 | `self.runs` sin límite y cache de ontología por `id(ctx)` | `extraction/semantic.py:146,158` |
| 8 | P2 | Objeto elegido por proximidad (`before[-1]`/`after[0]`) tras las guardas | `deterministic.py:480-481` |

Nota sobre el 2: `visual.py:125` también fuerza revisión, pero eso es correcto
por diseño (dosier 7.6, `VISUAL_INFERRED` nunca se autoaprueba) y NO entra en
este plan.

## Hallazgos verificados de la revisión del motor (segunda entrega)

| # | Sev | Hallazgo | Evidencia |
|---|-----|----------|-----------|
| 9 | P0 | `negation_kind` desconocido o con typo degrada a `SIMPLE` (tipo escribible) en vez de a revisión | `engine/negation.py:81` |
| 10 | P0 | Cesación con varias positivas vigentes sobre la misma clave: se cierra `min(assertion_id)` y las demás siguen vivas | `engine/negation.py`, `find_active_positive` |
| 11 | P1 | `TEMPORAL_UNRESOLVED_RELATIVE` es WARN y WARN permite ACCEPT, aunque el periodo cambie el significado de la relación | `engine/findings.py:171` |
| 12 | — | Solo `LINK_EXISTING` consolida identidad: el motor no puede completar el descubrimiento de entidades nuevas | `engine/identity.py:32` |

El 12 no es un defecto: es la decisión de producto pendiente. **No se relaja
`LINK_EXISTING`**; hace falta el flujo separado mención nueva → candidato →
deduplicación reforzada → plan `CREATE_ENTITY` independiente → snapshot →
las relaciones posteriores ya pueden aprobarse.

## Lotes

### Lote 1 — COMPLETADO y mergeado (PR #111)

**Resultado:** extractor y motor endurecidos frente a los hallazgos sin cambiar
la política observable; metadata tipada, orden estable, caches acotadas y
negaciones ambiguas en fail-closed.

Hallazgos 1, 5, 6, 7, tests adversariales del 8 (sin cambiar su lógica:
primero fijar el comportamiento, después decidir) **y los dos P0 del motor de
negaciones (9 y 10)**: `negation_kind` desconocido → `UNKNOWN_NEGATION_KIND` →
REVIEW (nunca un tipo escribible por defecto), y cesación con más de una
positiva vigente → `REVIEW_MULTIPLE_ACTIVE_ASSERTIONS` (0 → sin previa, ya
cubierto; 1 → puede cerrarse; >1 → revisión, jamás elegir). Ambos son
endurecimientos sin cambio observable hoy (el freno del extractor los
amortigua) y **obligatorios antes de autoaprobar negaciones**. Criterio: la
ordenación de candidatos es prerequisito de cualquier autoaprobación futura;
la frontera tipada de metadata es prerequisito del Lote 2.

### Lote 2 — COMPLETADO y mergeado (PR #113)

**Resultado:** política graduada implementada en el motor, con métricas y flag
por defecto **OFF**; su activación queda gateada a medición en sombra.

Mover la política del extractor al motor. Los hallazgos 2 y 3 son la misma
puerta: el `force_review=True` del semántico y el `negated or` del determinista
solo se retiran cuando la política graduada esté implementada y medida
(cesaciones en sombra, recall de autoaprobación como quinta métrica, recorrido
real texto → motor → plan). **La línea debe desaparecer cuando la política esté
lista, no antes.**

### Lote 3 — COMPLETADO y mergeado (PR #112)

**Resultado:** reproducibilidad entre `PYTHONHASHSEED`, escala hasta 1.000
propuestas y artefacto de alineación de spans demostrados; D-R conserva 8
claims correctos frente a D=0 (métrica del arnés, `harness_extractor.claims`,
F1 0.421; la métrica de bloque más estricta, `block_metrics.claims`, da 3
frente a 0 — mismo sentido, distinta superficie de emparejamiento).

- corridas con distintos `PYTHONHASHSEED`;
- rendimiento con 10 / 100 / 1.000 propuestas;
- benchmark C1 frente a D (el material C1 está en el worktree `v3-fix-e2e`,
  `docs/v3/measurements/runs/c1-cache.json`, aún sin commitear);
- actualizar el estado del doc 21 («especificado, listo para implementar» →
  implementado y verificado; los 10 tests de `test_knowledge_v3_reconcile.py`
  ya cubren orden de llegada, idempotencia y conservación de los claims del
  semántico).

### Lote 4 — política común de condicionales (decisión de producto)

Propuesta (pendiente de confirmación del operador): alinear el determinista con
el semántico — contrafactual/pregunta/ficción/falsedad no producen claim;
deseo/orden, abstención o solo diagnóstico; hipótesis explícita que interese
conservar, claim epistémico separado, nunca relación del mundo.

### Lote 2b — COMPLETADO y mergeado (PR #113)

**Resultado:** separadas la incertidumbre de cota temporal y la ambigüedad que
cambia el significado, tras flag por defecto **OFF**.

Separar `TEMPORAL_BOUND_UNKNOWN` (WARN: la relación es segura y solo falta la
fecha exacta) de `TEMPORAL_SCOPE_MATERIAL` (REVIEW: el tiempo cambia el
significado — cesaciones, contradicciones, estados sucesivos, relaciones
funcionales, cronologías incompatibles). No toda temporalidad ambigua va a
revisión; sí la que interviene en la decisión.

### Lote 5 — flujo de creación de entidades (hallazgo 12, diseño de producto)

Diseñar el plan `CREATE_ENTITY` independiente antes de tocar `LINK_EXISTING`.
Requiere decisión del operador sobre deduplicación reforzada y umbrales.

### Lote 6 — COMPLETADO y mergeado (PR #114)

**Resultado:** carga segura de secretos, despliegue genérico, rollback conjunto
de aplicación y datos, restore periódico y creación de workspaces incorporados.

El instalador completo, el wizard, la gestión web de workspaces y el modo sin
Nextcloud permanecen fuera de alcance. Completar este lote en el repositorio no
equivale a haber desplegado V3 en producción.

### Fuera de estos lotes (siguen en el doc 30)

Encargos D (proveedores con recambio), E (eje temporal de campaña),
G (observabilidad Telegraf→InfluxDB), H (registro del bucle humano), y el
contexto episódico inter-episodio (hoy solo hay correferencia intra-episodio,
`extraction/coreference.py`, y eso es deliberado: la evidencia aprobable queda
anclada al episodio actual).
