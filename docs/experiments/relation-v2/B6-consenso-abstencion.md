# B6 — Consenso, abstención y rechazo justificado

**Rama:** `feat/relation-engine-v2-hybrid` · **Base del bloque:** `a9f5121` (B5 + corrección
supervisada) · **Ficheros:** `relations/abstention.py` (nuevo), `relations/consensus_adapter.py`,
`relations/pipeline.py`, `relations/ensemble.py`, `relations/direction.py`,
`relations/benchmark/runner.py`, `tests/test_relation_v2_b6_consensus.py`

**Resultado del bloque (carril del dictamen, `baseline1` + selector v2):**
`decision_correct` **0.3023 → 0.3721**, y —lo que de verdad importa— la celda de
**falsos ACCEPT (GT-REJECT → ACCEPT) baja de 3 a 0**, sin fabricar ni un solo rechazo
falso (GT-ACCEPT → REJECT = **0**). El techo mecánico está roto: el motor emite
`reject` por primera vez en modo offline (4 de las 5 relaciones REJECT del GT).

**Resultado en el carril del ensemble (`ensemble_offline` + selector v2): NEGATIVO en
la métrica agregada.** `decision_correct` **baja** de 0.4651 a 0.3721. Se reporta
entero en §5.2, no se esconde: el ensemble venía proponiendo mucho más (16 de 30
GT-ACCEPT acertados) y las abstenciones de B6 mandan 12 de esos aciertos a revisión
humana. A cambio, sus 3 falsos ACCEPT también desaparecen. Es un intercambio de
cobertura por seguridad, y quien decida debe verlo con las dos cifras delante.

> **Caveat permanente del programa:** n=54 con **dev == test**. Cualquier cifra de este
> documento es **EN-CORPUS**, no una estimación de producción. No se debe apoyar
> ninguna decisión de producción en estos números.

---

## 1. Diagnóstico de partida (verificado, no repetido a ciegas)

El diagnóstico del supervisor se reprodujo íntegro sobre `a9f5121` antes de tocar nada
(`--predicate-selector v2`, `baseline1`, sin proveedores, 52 candidatos / 43 emparejados):

- `recommendation`: `human` 33, `propose` 19, **`reject` 0**.
- `consensus_state`: HUMAN_REQUIRED 20, PARTIAL_CONSENSUS 19, MODEL_CONFLICT 13.
- Matriz idéntica a la del diagnóstico (ver §5.1, columna "antes").

Las tres causas raíz, confirmadas leyendo el código:

1. **`reject` inalcanzable sin proveedores.** En `consensus_adapter`, la polaridad
   negativa solo puede nacer de `_LOCAL_POLARITY`/`_EXTERNAL_POLARITY`, es decir de un
   proveedor **presente** que vota en contra. Offline no hay proveedores → `neg_votes`
   siempre 0 → `recommendation` nunca es `reject`. Como el arnés mapea
   `reject → REJECT` (`benchmark/matching.py`, `RECO_TO_DECISION`), las 5 relaciones
   REJECT del ground truth eran **imposibles de acertar por construcción**.
2. **Las señales del motor v2 no llegaban a la decisión.** `review_predicate` (B2) se
   escribía en `validation_flags` y nadie lo leía; la `confidence` de
   `DirectionResult` (B3) se descartaba en `_build_candidate` (`.direction` era lo
   único que sobrevivía); el `TemporalState` de B4 viajaba dentro de la cadena
   `temporal_scope` sin que ningún consumidor lo interpretase.
3. **Incoherencia interna medible:** 7 candidatos con `review_predicate` se
   recomendaban `propose`. El motor proponía relaciones cuyo predicado él mismo había
   declarado dudoso.

---

## 2. Diseño (decidido y medido ANTES de escribir el código de decisión)

### 2.1. Principio
La decisión debe ser **coherente con lo que el motor ya sabe**. B6 **no** añade
inteligencia nueva ni recalibra nada: traduce señales **ya calculadas** en **motivos
estructurados** y en un veredicto que **solo puede degradar** la decisión.

### 2.2. Módulo nuevo: `relations/abstention.py`
Puro, determinista, sin red/disco/reloj/azar. Tres piezas:

- **`DecisionReason(code, severity, source, detail)`** — catálogo **cerrado** de 8
  códigos, 3 severidades (`INFORMATIVE` / `BLOCKING` / `REJECTING`) y 6 fuentes
  (el bloque del motor que produjo la señal). `detail` es traza, **nunca** criterio:
  ningún consumidor debe parsearlo.
- **`assess(candidate, signals, policy) -> Assessment(verdict, reasons)`** con
  veredicto `NEUTRAL` / `ABSTAIN` / `REJECT`.
- **`apply_verdict(state, recommendation, assessment) -> (state, recommendation)`** —
  **la única puerta**, y solo degrada.

| Código | Fuente | Severidad por defecto | Efecto |
|---|---|---|---|
| `predicate_abstained` | B2 selector | BLOCKING | no se puede proponer |
| `direction_low_confidence` | B3 dirección | INFORMATIVE | solo se registra |
| `temporal_not_in_force` (PLANNED/HYPOTHETICAL) | B4 temporal | BLOCKING | no se puede proponer |
| `temporal_ended` (ENDED) | B4 temporal | INFORMATIVE | solo se registra |
| `temporal_unresolved` (UNKNOWN) | B4 temporal | INFORMATIVE | solo se registra |
| `epistemic_not_asserted` | epistémico | BLOCKING | no se puede proponer |
| `negated_relation` | negación | REJECTING | rechazo justificado |
| `type_incompatible` | ontología | BLOCKING | no se puede proponer |

**Precedencia** (documentada y testeada): si el **selector de predicado se abstuvo**,
el veredicto es `ABSTAIN` *aunque* haya motivos rechazantes — no se rechaza una
proposición cuyo predicado el propio motor no sabe formular. Después: `REJECT` >
`ABSTAIN` > `NEUTRAL`.

**Reglas de `apply_verdict`** (verificadas de forma **exhaustiva** sobre las
5×3×3 = 45 combinaciones estado × recomendación × veredicto):

1. `INVALID_RESPONSES` y `MODEL_CONFLICT` son **intocables**. Si las fuentes se
   contradicen entre sí, ni proponer ni rechazar: ya es cosa de un humano.
2. `REJECT` → `(PARTIAL_CONSENSUS, reject)`. **Nunca `STRONG_CONSENSUS`**: sin
   proveedor presente no hay consenso fuerte, y el techo del rechazo no puede superar
   al de la propuesta.
3. `ABSTAIN` → solo actúa si la recomendación era `propose`, y la degrada a
   `(HUMAN_REQUIRED, human)`. Un `reject` previo (voto negativo real de un proveedor)
   **no se ablanda** a humano: seguiría sin escribirse nada y se perdería una señal.
4. `NEUTRAL` → no cambia nada.

### 2.3. Qué se DESCARTÓ, y por qué (medido antes de implementar)

| Regla candidata | Medición en el banco | Decisión |
|---|---|---|
| `reject` si estado temporal **ENDED** | El resolutor v2 marca ENDED todo lo que va en pasado: **18 de las 30** relaciones GT-ACCEPT emparejadas caen ahí. Simulada: fabricaba **13 rechazos falsos** sobre ACCEPT y `decision_correct` bajaba a 0.3256 | **Descartada como default.** La regla existe (`reject_on_temporal_ended`) pero nace **desactivada** |
| Vetar `propose` por **confianza de dirección baja** | La resolución débil (orden textual / predicado genérico, conf. 0.5) dispara en **21 de 43** emparejados y la dirección resultante es **correcta en 18** de esas 21 | **Descartada como veto.** La señal se registra como motivo INFORMATIVO; la regla bloqueante existe (`veto_on_direction`) y nace desactivada |
| Precedencia inversa (rechazar aunque el predicado esté en abstención) | Simulada: 16/43 en vez de 17/43 y **3** rechazos falsos en vez de 2 | Descartada |

Que estas dos reglas queden **desactivadas pero vivas y testeadas** es deliberado:
cuando la confianza de dirección esté calibrada, o el resolutor temporal distinga
"pasado narrativo" de "relación terminada", activarlas será un acto explícito y
medible, no un descubrimiento.

### 2.4. Flag y comportamiento por defecto
`PipelineConfig.consensus_policy` con default **`"auto"`**, resuelto por
`resolve_consensus_policy()`: selector `v1` → consenso **v1 histórico**; selector `v2`
→ consenso v2. Es la **misma convención que B3 y B4** en este programa (ambos viven ya
dentro del `if config.predicate_selector == "v2"` de `_build_candidate`): el flag `v2`
es el interruptor del *motor* v2 completo. Los valores `"v1"`/`"v2"` fuerzan una
política concreta (uso de laboratorio).

**El comportamiento por defecto no cambia**: con el default de `PipelineConfig`
(selector v1) la política es v1 y el resultado es idéntico al de `a9f5121` (§5.3).

`compute_relation_consensus(..., policy="v1")` es el default también a nivel de
librería: ninguna llamada existente cambia de resultado.

### 2.5. Lo que también se cableó
- **`relations/direction.py`**: `LOW_CONFIDENCE_THRESHOLD = 0.7` y
  `REVIEW_DIRECTION_FLAG`. El pipeline (rama v2) marca ahora el candidato cuando la
  dirección sale de un fallback débil: la confianza de B3 deja de perderse.
- **`relations/ensemble.py`**: `combine(..., consensus_policy=...)` aplica la misma
  puerta **después** de sus umbrales, de modo que **ninguna recalibración de pesos o
  umbrales puede saltarse la abstención** (hay test con una config deliberadamente
  permisiva).
- **`relations/benchmark/runner.py`**: la política viaja con la config del pipeline;
  el carril del ensemble la lee del `output` para no poder divergir del carril base.

---

## 3. Qué NO se ha tocado (prohibiciones del bloque)

- `git diff a9f5121 HEAD -- data-engine/app/relations/benchmark/report.py` → **vacío**.
  Igual de vacío: `benchmark/matching.py`, `relations/review_policy.py` y el corpus /
  ground truth completo (`tests/data/relation_benchmark/`).
- **Ningún umbral bajado**: `strong_threshold=0.75`, `partial_threshold=0.45`,
  `conflict_margin=0.15`, `auto_propose_score_threshold=0.90` siguen igual.
- **Sin autoaprobación**: `AUTO_PROPOSABLE` sigue exigiendo `STRONG_CONSENSUS` + ≥1
  proveedor presente; offline es inalcanzable, y B6 **nunca** eleva a `STRONG`.
- Sin red, sin proveedores reales, sin Neo4j, sin ingesta, sin `main`, sin las ramas
  #97–#101. Todo offline y determinista.

---

## 4. Pruebas

`tests/test_relation_v2_b6_consensus.py` — **49 tests, 0 skip, 0 xfail**. Entidades
inventadas (Marcus, Kael, Gorm, Ysera, la Cofradía del Yunque), nunca del corpus.
Cubren: catálogos cerrados y ordenados, rechazo de códigos/severidades/fuentes
inventados, lectura del estado de vigencia (incluido el alcance de v1 y la basura →
`UNKNOWN`, nunca adivinar), una prueba por señal, la precedencia, la barrera
anti-mejora **exhaustiva** (45 combinaciones), la neutralidad del default, la
integración en pipeline y ensemble, determinismo e inmutabilidad del candidato.

### 4.1. Pruebas de mutación — 16 mutantes, **16 muertos, 0 supervivientes**

Cada mutante se aplicó **por separado** sobre el fichero limpio y se restauró siempre
(`git status --porcelain` verificado al final: solo los ficheros del bloque).

| # | Mutación | Resultado |
|---|---|---|
| M1 | `apply_verdict` ignora `INVALID_RESPONSES`/`MODEL_CONFLICT` | MUERTO |
| M2 | La abstención devuelve `propose` en vez de `human` | MUERTO |
| M3 | El rechazo aterriza en `STRONG_CONSENSUS` | MUERTO |
| M4 | La abstención de predicado deja de bloquear el rechazo | MUERTO |
| M5 | `veto_on_predicate_abstention` desactivado por defecto | MUERTO |
| M6 | `reject_on_temporal_ended` activado por defecto | MUERTO |
| M7 | `veto_on_epistemic` desactivado por defecto | MUERTO |
| M8 | `temporal_state_of` adivina `ACTIVE` cuando no consta | MUERTO |
| M9 | La abstención ablanda un `reject` previo | MUERTO |
| M10 | `consensus_adapter` aplica v2 por defecto | MUERTO |
| M11 | Los motivos solo se emiten si la decisión cambia | MUERTO |
| M12 | `resolve_consensus_policy("auto")` devuelve siempre v2 | MUERTO |
| M13 | El pipeline no emite el flag de confianza de dirección | MUERTO |
| M14 | El ensemble calcula el veredicto pero no lo aplica | MUERTO |
| M15 | Un umbral permisivo del ensemble se salta la abstención | MUERTO |
| M16 | `LOW_CONFIDENCE_THRESHOLD` por debajo del fallback débil | MUERTO |

> **Nota de método (incidencia real, no la escondo).** La primera pasada de mutación
> dejó `direction.py` con el mutante M16 activo **en el bytecode**: la mutación
> `0.7 → 0.4` tiene exactamente el mismo tamaño en bytes y ocurrió dentro del mismo
> segundo, así que Python reutilizó el `.pyc` obsoleto y la restauración del fuente no
> tuvo efecto en el proceso siguiente. Resultado: una suite completa que pasó en verde
> con un fichero restaurado y un `.pyc` mutado. Se detectó al repetir la suite, se
> purgó `__pycache__` y **se rehizo la tanda entera de mutación con
> `PYTHONDONTWRITEBYTECODE=1`**: mismos 16 muertos, 0 supervivientes, árbol limpio. Las
> cifras del A/B también se reprodujeron con bytecode limpio (§5). Lección para el
> programa: toda prueba de mutación debe correr con el bytecode desactivado.

### 4.2. Suite completa
`python3 -m pytest tests/ -q` → **1637 passed, 2 skipped** (referencia previa: 1588 + 2;
los 49 nuevos son exactamente la diferencia). Ningún test previo modificado ni
adaptado. `deterministic=True` en los cuatro runs del A/B.

---

## 5. A/B honesto (arnés único, corpus B1 congelado, mismos umbrales)

Comparación contra `a9f5121` mediante un worktree adicional de **solo lectura**
(`git worktree add --detach ... a9f5121`, eliminado al terminar). Ninguna rama tocada.

### 5.1. Carril del dictamen — `baseline1`, `--predicate-selector v2`

| Métrica | Antes (`a9f5121`) | Después (B6) | Δ |
|---|--:|--:|--:|
| `predicate_correct` | 0.8140 | 0.8140 | = |
| `direction_correct` | 0.9302 | 0.9302 | = |
| `direction_orientation_ok` | 0.9535 | 0.9535 | = |
| `types_correct` | 1.0000 | 1.0000 | = |
| `negation_correct` | 0.8837 | 0.8837 | = |
| `temporal_correct` | 0.8837 | 0.8837 | = |
| `epistemic_correct` | 0.8605 | 0.8605 | = |
| `evidence_correct` | 0.9302 | 0.9302 | = |
| `offsets_correct` | 0.9535 | 0.9535 | = |
| `strict_predicate.f1` | 0.6604 | 0.6604 | = |
| `global_existence.f1` (pair_F1) | 0.8113 | 0.8113 | = |
| `global_existence.precision` / `recall` | 0.8269 / 0.7963 | 0.8269 / 0.7963 | = |
| **`decision_correct`** | **0.3023** (13/43) | **0.3721** (16/43) | **+0.0698** |
| `deterministic` | True | True | = |
| `verdict` | APTO PARA CONTINUAR EN MODO SOMBRA | igual | = |

B6 **solo** mueve el eje de decisión, que es exactamente su alcance. Ningún otro eje
se toca (ni para bien ni para mal).

**Matriz de decisión (GT → predicho), 43 emparejados:**

| | ANTES ACCEPT | ANTES REJECT | ANTES REVIEW | | DESPUÉS ACCEPT | DESPUÉS REJECT | DESPUÉS REVIEW |
|---|--:|--:|--:|---|--:|--:|--:|
| **GT ACCEPT** (30) | 9 | 0 | 21 | | **4** | **0** | **26** |
| **GT REJECT** (5) | **3** | 0 | 2 | | **0** | **4** | 1 |
| **GT REVIEW** (8) | 4 | 0 | 4 | | **0** | 0 | **8** |

**Métrica de control — falsos ACCEPT (GT-REJECT → ACCEPT): 3 → 0.** Y sin daño nuevo:
la celda inversa (GT-ACCEPT → REJECT) queda en **0**, no en los 2 que la simulación
previa preveía.

Por qué salió mejor que lo simulado: los 3 candidatos GT-ACCEPT con `negated=True`
espurio no se convierten en rechazo por **dos** mecanismos independientes — 2 están en
`MODEL_CONFLICT` (la sintaxis contradice la señal de negación; regla 1 de
`apply_verdict`) y 1 tiene el predicado en abstención (precedencia). Ese mismo
conservadurismo cuesta **1 acierto**: una relación GT-REJECT también cae en
`MODEL_CONFLICT` y se queda en REVIEW (4 de 5, no 5 de 5).

**Distribución de recomendaciones sobre los 52 candidatos:**

| | `propose` | `human` | `reject` |
|---|--:|--:|--:|
| Antes | 19 | 33 | **0** |
| Después | 6 | 41 | **5** |

Entre los 9 falsos positivos (predicciones sin relación en el GT), los `propose` bajan
de 3 a 2 y aparece 1 `reject`.

### 5.2. Carril del ensemble — `ensemble_offline`, selector v2 (**resultado negativo**)

| Métrica | Antes | Después | Δ |
|---|--:|--:|--:|
| `decision_correct` | **0.4651** (20/43) | **0.3721** (16/43) | **−0.0930** |
| resto de métricas estructurales | idénticas | idénticas | = |

| | ANTES ACCEPT | ANTES REJECT | ANTES REVIEW | | DESPUÉS ACCEPT | DESPUÉS REJECT | DESPUÉS REVIEW |
|---|--:|--:|--:|---|--:|--:|--:|
| **GT ACCEPT** (30) | 16 | 0 | 14 | | 4 | 0 | 26 |
| **GT REJECT** (5) | **3** | 0 | 2 | | **0** | 4 | 1 |
| **GT REVIEW** (8) | 4 | 0 | 4 | | 0 | 0 | 8 |

Lectura honesta: en este carril B6 **empeora la métrica agregada**. El ensemble
acertaba 16 GT-ACCEPT porque proponía mucho más (8 de sus 9 falsos positivos eran
`propose`); las abstenciones mandan 12 de esos aciertos a revisión humana. Lo que
gana: sus 3 falsos ACCEPT desaparecen y 4 REJECT aparecen bien clasificados. **Si el
criterio es "acertar la decisión", B6 es un retroceso aquí; si el criterio es "no
proponer basura al grafo", es una mejora.** El dictamen del arnés se emite sobre
`baseline1`, pero esta cifra no debe ocultarse al decidir.

### 5.3. Neutralidad del default — selector v1 (ambos carriles)

| Métrica | `a9f5121` v1 | B6 v1 | `a9f5121` ens. v1 | B6 ens. v1 |
|---|--:|--:|--:|--:|
| `predicate_correct` | 0.2093 | 0.2093 | 0.2093 | 0.2093 |
| `decision_correct` | 0.3023 | 0.3023 | 0.3953 | 0.3953 |
| `pair_F1` | 0.8113 | 0.8113 | 0.8113 | 0.8113 |
| matriz de decisión | idéntica | idéntica | idéntica | idéntica |
| `deterministic` | True | True | True | True |

**Todas** las métricas de los informes v1 coinciden: el cableado de B6 es
**metric-neutral** con el comportamiento por defecto.

---

## 6. Seguridad

- **Sin autoaprobación.** `apply_verdict` no tiene ninguna rama que devuelva `propose`
  si la entrada no lo era, ni que eleve el estado a `STRONG_CONSENSUS`; se comprueba
  sobre las 45 combinaciones posibles, no con ejemplos. Los `_FORBIDDEN_RECOMMENDATIONS`
  siguen barrados en `__post_init__`.
- **La abstención está por encima de la calibración.** En el ensemble la puerta se
  aplica **después** de los umbrales: ninguna recalibración de pesos puede convertir un
  candidato con el predicado en abstención en una propuesta (test con config permisiva).
- **Fail-closed.** Candidato inválido, flags no iterables, `temporal_scope` basura o
  ausente → `UNKNOWN`/sin motivo, nunca una suposición favorable.
- **Rechazar no es escribir.** `reject` es una recomendación en sombra, igual que
  `propose`. B6 no toca ningún camino de escritura: no existe.
- Determinismo, pureza y no-mutación del candidato verificados por test y por el
  `deterministic=True` de los cuatro runs.

---

## 7. Limitaciones y lo que NO se ha medido

1. **n=54, dev == test.** Todas las cifras son en-corpus. El salto de `decision_correct`
   NO es una estimación de producción, y con 43 emparejados un solo candidato vale
   0.023 de métrica.
2. **La calidad del rechazo depende de la detección de negación**, que no es de este
   bloque: `negation_correct` = 0.8837 en el banco (5 errores). Hoy la guarda de
   `MODEL_CONFLICT` absorbe esos errores, pero es una casualidad afortunada, no una
   garantía: con otro corpus podrían convertirse en rechazos falsos. **Mejorar la
   negación es prerrequisito de cualquier uso serio del camino de rechazo.**
3. **No se ha medido con proveedores reales.** Todo el A/B es offline. Cómo interactúa
   la abstención con un `recommend_reject` de Ollama o un `confirm` de NVIDIA está
   **sin medir**.
4. **La política no es calibrable desde el CLI.** No se ha añadido bandera
   `--consensus-policy` a propósito: `report.determinism_report()` (congelado en este
   bloque) no reenvía ese override a la segunda pasada y produciría un
   `deterministic=False` **espurio**. Con el default `"auto"` no hay divergencia
   posible. Reproducir "política v1 con selector v2" requiere hoy llamar a
   `run_benchmark(..., consensus_policy="v1")` desde librería con
   `check_determinism=False`. Exponerlo en el CLI exige tocar `report.py`: queda para
   otro bloque.
5. **`temporal_ended` y `direction_low_confidence` quedan sin explotar.** Son motivos
   informativos; su valor decisorio está **medido como negativo hoy** y pendiente de que
   B3/B4 mejoren.
6. **Las 11 relaciones no emparejadas (FN) siguen fuera del eje de decisión**: si el
   par no se genera, ninguna política de consenso puede acertarlo. `pair_F1` no se
   mueve en B6, y ese es el techo real que queda.

---

## 8. Estado

**B6 entregado para auditoría independiente.** Rompe el techo mecánico documentado
(`reject` existe y es alcanzable sin proveedores), elimina la incoherencia
`propose`-con-predicado-dudoso, cablea las cuatro señales del motor v2 en la decisión y
convierte la abstención en algo **informativo y estructurado**. Mejora la métrica de
decisión en el carril del dictamen (+0.0698) y **la empeora en el carril del ensemble
(−0.0930)**, con la métrica de control (falsos ACCEPT) a 0 en ambos.

**No me autoapruebo:** el dictamen lo emiten el revisor independiente y el supervisor.

---

## 9. Auditoría independiente y corrección supervisada

El revisor independiente emitió **`DICTAMEN DEL REVISOR: CONFORME`** sobre `f601a47`,
verificando por su cuenta: la garantía de seguridad central con un barrido adversarial
propio de **38.808 combinaciones** (estados × recomendaciones × veredictos × 241
conjuntos de motivos) **sin un solo contraejemplo**; que el banco no está amañado
(`report.py`/`matching.py`/`review_policy.py`/corpus a diferencia cero, y las 44 líneas
de `runner.py` solo propagan un kwarg); y que **todas** las cifras publicadas —incluida
la negativa— se reproducen al dígito.

Pero **condicionó el visto bueno** a medir por separado la contribución de los tres
vetos bloqueantes activados por defecto, y encontró 3 mutantes supervivientes.

### 9.1. Ablación de vetos (supervisor) — lo que exigía el revisor

Medida inyectando cada `AbstentionPolicy` en el banco completo
(`tmp/b6_ablacion.py`; sin red, sin proveedores, sin escritura):

| Regla | Contribución medida | Decisión |
|---|---|---|
| `reject_on_negation` | **+0.093** en ambos carriles; sin ella vuelven 2 falsos ACCEPT | **Activada** — es la que compra la seguridad |
| `veto_on_epistemic` | **+0.047** en ambos carriles | **Activada** |
| `veto_on_predicate_abstention` | **−0.093** en ambos carriles | **Activada pese al coste**: es el objetivo de coherencia declarado del bloque (no proponer lo que el propio selector declara dudoso). Se documenta el precio en vez de ocultarlo |
| `veto_on_temporal_not_in_force` | **0.000** — no dispara ni una vez en el corpus B1 | **Activada pero NO MEDIBLE aquí**. No se afirma que aporte nada |
| `veto_on_type_incompatible` | Ver §9.2 | **Activada tras corregir su fuente** |

### 9.2. DEFECTO DE FONDO encontrado por el supervisor: el veto de tipos usaba la ontología equivocada

`assess` juzgaba la compatibilidad de tipos con `signals.type_compatibility`, calculada
sobre `TYPE_ONTOLOGY` (`signals.py`) — una ontología **deliberadamente mínima** cuya
propia documentación dice literalmente *"NO descarta la relación; solo informa"*, y que
**no contempla el par `(Character, Character)`**: justo el de los predicados familiares
y sociales (`SIBLING_OF`, `PARENT_OF`, `MARRIED_TO`, `MENTOR_OF`, `ALLIED_WITH`) que
**B0 añadió en este mismo programa**. Tratar su lista vacía como "incompatible" convertía
una **laguna de cobertura** en un veto bloqueante.

Medido: disparaba en **23 de 52 candidatos (44%)**, entre ellos 9 pares
`(Character, Character)`. Era la causa **íntegra** del resultado negativo en el carril
del ensemble.

**Corrección:** el veto consulta ahora `relations.ontology` (B1), la fuente autoritativa
del programa, que define dominio/rango **por predicado**. Solo veta cuando hay una
contradicción **demostrable**; predicado desconocido, tipos ausentes o dominio/rango sin
declarar → **no se veta** ("no consta" no es "incompatible"). Tras la corrección dispara
en **10 de 52**, y son violaciones reales de dirección:
`MEMBER_OF (Faction→Character)` ×3, `PARTICIPATED_IN (Event→Faction)` ×2,
`OWNS (Object→Character)`, `GUARDS (Object→Location)`, `CREATED (Object→Faction)`…

### 9.3. Otras correcciones

| Hallazgo | Corrección |
|---|---|
| **N4 (mutante superviviente)**: `predicate_abstention_blocks_reject` estaba **acoplado** a `veto_on_predicate_abstention`, de modo que desactivar el veto de proponer desactivaba **en silencio** la guarda contra rechazos infundados | Desacoplados. Un rechazo suprimido por la guarda queda en **abstención**, no en "todo bien". Test nuevo que muere con el acoplamiento |
| **N14**: el veto de tipos no tenía cobertura por el camino real | Cubierto con 5 aserciones, incluida la de que la señal informativa **no puede vetar por sí sola** |
| Versiones de esquema sin subir pese a cambiar el payload | `relation-consensus-1.1.0`, `relation-ensemble-1.1.0` |
| `deterministic=False` **espurio y silencioso** con `consensus_policy` override (y `report.py` congelado, no se puede corregir ahí) | `run_benchmark` emite ahora un `RuntimeWarning` explícito: la trampa deja de ser silenciosa |
| Docstring afirmaba "nunca eleva el estado", falso para `HUMAN_REQUIRED → PARTIAL_CONSENSUS` | Corregido en la redacción (el código es correcto e inocuo) |

### 9.4. A/B DEFINITIVO tras la corrección

Base = `a9f5121` (pre-B6) con **el mismo selector v2**, medida en worktree de solo
lectura ya eliminado:

| Carril | base `a9f5121` | B6 corregido | Δ | falsos ACCEPT | rechazos falsos |
|---|--:|--:|--:|:--:|:--:|
| `baseline1` (dictamen) | 0.3023 | **0.3488** | **+0.0465** | **3 → 0** | 0 |
| `ensemble_offline` | 0.4651 | **0.4651** | **+0.0000** | **3 → 0** | 0 |

**El resultado negativo desaparece.** Antes de la corrección el carril del ensemble caía
−0.0930; ahora es **neutro**, y en ambos carriles los falsos ACCEPT bajan a 0 sin
producir ni un solo rechazo falso. El resto de métricas sigue intacto
(predicado 0.8140, dirección 0.9302, temporal 0.8837, strict_F1 0.6604, evidencia
0.9302, pair_F1 0.8113, `deterministic=True` en los cuatro runs).

Honestidad sobre el coste: el `+0.0698` que reportó el editor en `baseline1` baja a
`+0.0465`, porque el veto de tipos corregido sí abstiene —con razón— en 10 candidatos
con tipos contradictorios. Se prefiere el número más bajo y correcto al más alto y
apoyado en una laguna.

Suite: **1638 passed, 2 skipped**. Umbrales, arnés de medición y ground truth con
diferencia **cero**.

### 9.5. Lo que sigue ABIERTO

- **La precisión real de la señal que dispara el rechazo es 4/9 (44%)**. De los 9
  candidatos con `negated=True` predicho, solo 4 lo son en el ground truth. Hoy los 5
  falsos positivos los absorbe la guarda de `MODEL_CONFLICT`, lo que el editor calificó
  —con razón— de **"suerte, no garantía"**. El revisor exige, y el supervisor asume,
  **no promocionar el camino de rechazo** más allá del modo sombra hasta que la
  detección de negación mejore.
- `veto_on_temporal_not_in_force` sigue **sin poder medirse** en este corpus.
- n=54 con dev==test: **todo lo anterior es EN-CORPUS**, no una estimación de producción.
