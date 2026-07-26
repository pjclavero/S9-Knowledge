# Motor de relaciones v2 — Informe de resultados

**Rama:** `feat/relation-engine-v2-hybrid` · **Commit base:** `dcded31` (origin/main) ·
**HEAD:** `1c444a9` · **Estado: NO FUSIONAR.** `main` intacto; sin despliegue, sin ingesta,
sin escritura en Neo4j, sin proveedores reales ejecutados.

> **Léase esto antes que cualquier cifra.** El corpus tiene **n=54 relaciones y dev == test**:
> no hay conjunto reservado. **Todas las cifras de este informe son EN-CORPUS y no son
> estimaciones de producción.** Ver §8.

---

## 1. Identificación

15 commits sobre `dcded31`. 38 ficheros, +10.812 / −77 líneas.

| Bloque | Commits | Qué entregó |
|---|---|---|
| Etapa 1-2 | `733b94a`, `1c82c55` | Auditoría, diseño, arnés único y hashes de corpus |
| **B0** | `781edf7` | Reconciliación GT↔ontología (+9 canónicos) |
| **B1** | `089830b` | `relations/ontology.py` — fuente única |
| **B2** | `a11da8d`, `7ae2f6d`, `a420c16` | Corrección del metro + selector de predicados v2 + purga de sobreajuste |
| **B3** | `9c0ea89` | `relations/direction.py` |
| **B4** | `622fb8c` | `relations/temporal_v2.py` |
| **B5** | `dcc9e1c`, `a9f5121` | Parser opcional tras interfaz + corrección supervisada |
| **B6** | `f601a47`, `fd0b934` | `relations/abstention.py` (consenso/rechazo) + corrección supervisada |
| **B7** | `237c631`, `1c444a9` | IA externa como consultor + corrección tras **NO CONFORME** |

**Módulos nuevos:** `ontology.py`, `predicate_selector.py`, `direction.py`, `temporal_v2.py`,
`abstention.py`, `external_consult.py`, `fragment_protocol.py`, `evidence_realignment.py`.
**Modificados:** `pipeline.py`, `ensemble.py`, `consensus_adapter.py`, `external_ai_shadow.py`,
`syntax.py`, `schemas/rpg_schema.py`, `benchmark/{runner,report,matching,cli}.py`.

**Tests:** 279 funciones nuevas en 8 ficheros `test_relation_v2_b*.py`
(7/16/24/24/29/35/50/94). Suite `data-engine/app/tests`: **2431 passed, 2 skipped**.

---

## 2. Diagnóstico: qué se CONFIRMÓ y qué se REFUTÓ

### 2.1. CONFIRMADO — el cuello era un TECHO MECÁNICO, no "el motor elige mal"

Este es el hallazgo central del programa, y se repitió **dos veces** en sitios distintos:

- **Predicado (B2):** `pipeline._choose_predicate` sólo podía emitir **5 predicados de 113**.
  El ground truth usa 20. **29 de 54 relaciones (53,7%) eran imposibles de acertar por
  construcción.** No es que el motor eligiera mal: *no podía nombrar* más de la mitad de las
  relaciones.
- **Decisión (B6):** el motor **nunca emitía `reject`** en modo offline (33 `human`,
  19 `propose`, **0 `reject`** sobre 52 candidatos). Como el arnés mapea `reject → REJECT`,
  las 5 relaciones REJECT del ground truth eran, otra vez, **imposibles por construcción**.

**Lección:** antes de intentar que un motor "acierte más", hay que comprobar si el acierto
está siquiera en su espacio de salida.

### 2.2. CONFIRMADO — el arnés MEDÍA MAL, y corregirlo empeoró la línea base

`matching.py` medía el predicado con `vocabulary.predicates_match`, que introducía un **doble
sesgo** demostrado sobre el corpus:

- **Sub-contaba ~31%:** 11 canónicos del GT estaban marcados `out_of_vocab`, así que un
  acierto **exacto** (`MENTOR_OF == MENTOR_OF`) puntuaba como fallo porque `None != None`.
- **Sobre-contaba ~13%:** daba crédito por alias que colapsan a otro canónico
  (`LIVES_IN → LOCATED_IN`). Predecir `LOCATED_IN` para un GT `LIVES_IN` **no es acertar**.

Se corrigió a igualdad canónica estricta (B2 Parte A). **Efecto: la línea base BAJÓ de 0.2558
a 0.2093** — es decir, la corrección fue *en contra* del interés del programa, y aun así se
aplicó y se documentó. Todas las cifras de este informe usan el metro corregido.

### 2.3. REFUTADO — "el problema es la capa de IA externa"

Un programa anterior (PR #95-#103) atribuyó el bajo rendimiento a la capa externa. Es cierto
que ahí había un defecto grave (P0, §7.1), pero **el motor propio tenía su propio techo**, y
es el que este programa levantó. Las mejoras de §3 se obtienen **sin ejecutar ni un solo
proveedor externo**.

### 2.4. REFUTADO — "más expresiones léxicas = mejor motor"

El selector v2 alcanzó inicialmente **0.907** enriqueciendo la ontología con expresiones
observadas en el corpus. Una ablación del revisor demostró que **~70% de esa ganancia era
sobreajuste**: base 0.209 / arquitectura sola 0.419 / con expresiones calcadas 0.907. Se
purgaron las expresiones calcadas y la cifra honesta quedó en **0.814**. Ver §8.

---

## 3. Resultados A/B — benchmark final

Corpus B1 congelado, arnés único `relations/benchmark/`, metro corregido, `deterministic=True`
en los cuatro carriles. Artefactos: `tmp/final_{baseline1,ensemble_offline}_{v1,v2}.json`.
`v1` = motor anterior; `v2` = motor v2.

### 3.1. Carril del dictamen (`baseline1`)

| Métrica | v1 | **v2** | Δ | Gate | ¿Pasa? |
|---|--:|--:|--:|:--:|:--:|
| `predicate_correct` | 0.2093 | **0.8140** | +0.6047 | ≥0.50 | ✅ |
| `direction_correct` | 0.6279 | **0.9302** | +0.3023 | ≥0.75 | ✅ |
| `temporal_correct` | 0.4419 | **0.8837** | +0.4418 | ≥0.60 | ✅ |
| `strict_predicate.f1` | 0.1698 | **0.6604** | +0.4906 | ≥0.35 | ✅ |
| `evidence_correct` | 0.9070 | 0.9302 | +0.0232 | no baja | ✅ |
| `offsets_correct` | 0.9302 | 0.9535 | +0.0233 | — | — |
| `decision_correct` | 0.3023 | 0.3488 | +0.0465 | — | ⚠️ |
| `global_existence.f1` (pair_F1) | 0.8113 | 0.8113 | **0.0000** | no baja | ⚠️ |
| **Falsos ACCEPT** | **4** | **0** | **−4** | — | ✅ |

### 3.2. Carril `ensemble_offline`

| Métrica | v1 | **v2** | Δ |
|---|--:|--:|--:|
| `decision_correct` | 0.3953 | **0.4651** | +0.0698 |
| **Falsos ACCEPT** | **2** | **0** | **−2** |
| Resto de métricas | idénticas a §3.1 | idénticas | — |

**Los cuatro gates experimentales se cumplen.** Ningún umbral fue rebajado (§6.3).
Veredicto del arnés: `APTO PARA CONTINUAR EN MODO SOMBRA`, alcance `COMPLETO`.

### 3.3. Matriz de decisión (GT → predicho), `baseline1`

| | ACCEPT | REJECT | REVIEW |
|---|--:|--:|--:|
| **GT ACCEPT** (30) | 9 → **3** | 0 → **0** | 21 → **27** |
| **GT REJECT** (5) | **4 → 0** ✅ | 0 → **4** ✅ | 1 → **1** |
| **GT REVIEW** (8) | 4 → **0** | 0 → **0** | 4 → **8** ✅ |

Lectura honesta: el motor v2 **elimina los falsos ACCEPT y empieza a rechazar lo que debe
rechazar**, pero lo paga **abstiéndose mucho más** (de 30 relaciones que el GT acepta, ahora
sólo propone 3). En modo sombra con un humano detrás el coste es tolerable; **como política de
producción no lo es**.

### 3.4. Distribución de predicados emitidos (v2)

18 predicados distintos frente a los **5** del motor v1: `MEMBER_OF` 9, `RELATED_TO` 11,
`PARTICIPATED_IN` 7, `GUARDS` 4, `OWNS` 4, `LOCATED_IN` 3, `CAUSED` 2, `FOUNDED` 2, y
`ALLIED_WITH`, `CREATED`, `ENEMY_OF`, `LEADS`, `LIVES_IN`, `MARRIED_TO`, `PARENT_OF`,
`SIBLING_OF`, `SUCCEEDED`, `TRUSTS` con 1 cada uno. **El techo mecánico está roto.**

---

## 4. Cambios por módulo

| Módulo | Bloque | Qué hace | Efecto medido |
|---|:--:|---|---|
| `ontology.py` | B1 | Fuente única: 20 canónicos con familia, **dominio/rango**, simetría, inversa, alias, expresiones | Metric-neutral (habilitante) |
| `predicate_selector.py` | B2 | Genera candidatos, **filtra por dominio/rango**, puntúa y **se abstiene** sin margen | predicate 0.209 → 0.814 |
| `direction.py` | B3 | Activa/pasiva/agente/inversa/**simetría**/preposición/correferencia; orden textual sólo como fallback débil | direction 0.628 → 0.930 |
| `temporal_v2.py` | B4 | Estados ACTIVE/ENDED/PLANNED/HYPOTHETICAL/RECURRING/UNKNOWN + vigencia, sin sobrescribir historia | temporal 0.442 → 0.884 |
| `syntax.py` | B5 | Parser fuerte opcional tras interfaz, perezoso, **sin descargas**, fallback seguro, caché LRU | Metric-neutral (infraestructura) |
| `abstention.py` | B6 | Motivos **estructurados** (catálogo cerrado) + veredicto NEUTRAL/ABSTAIN/REJECT | decision +0.047/+0.070; **falsos ACCEPT → 0** |
| `external_consult.py`, `fragment_protocol.py`, `evidence_realignment.py` | B7 | IA externa como **consultor**: techo estructural, fragmentos, unicidad de anclaje | **Δ = 0.0000** (§7.2) |

---

## 5. Rendimiento

Medido por el arnés (16 fuentes, 52 candidatos), sin proveedores:

| Carril | `per_candidate_ms` | `per_doc_ms` | `total_ms` |
|---|--:|--:|--:|
| `baseline1` v1 | 1.052 | 3.419 | 54.7 |
| `baseline1` **v2** | 1.666 | 5.413 | 86.6 |
| `ensemble_offline` v1 | 0.991 | 3.221 | 51.5 |
| `ensemble_offline` **v2** | 1.628 | 5.291 | 84.7 |

El motor v2 cuesta **~1,6× más** por candidato (≈0,6 ms). Es un coste despreciable en
términos absolutos, pero es un coste real y no se oculta. Estas cifras son de un corpus de
juguete: **no extrapolar a producción.**

---

## 6. Seguridad

### 6.1. Garantías verificadas
- **Offline y sombra:** `external_calls = 0` en todos los runs. Ningún proveedor real ejecutado.
- **Sin escritura:** cero escritura en Neo4j; `AUTO_PROPOSABLE` nunca deriva en escritura.
- **Fail-closed:** ausencia o fallo de un proveedor **nunca** equivale a rechazo.
- **Determinismo:** `deterministic=True` en los cuatro carriles.
- **La IA externa es consultor, nunca autoridad** (B7): techo estructural
  `EXTERNAL_MAX_STATE = PARTIAL_CONSENSUS`, aplicado en **ambas** políticas de consenso y en
  los tres puntos de entrada de producción. No puede fabricar `propose`/`reject`, ni elevar
  estado, ni tocar `INVALID_RESPONSES`/`MODEL_CONFLICT`. El revisor lo atacó con un barrido
  adversarial propio de **38.808 combinaciones** en B6 y **3.430** en B7: **cero violaciones**.
- **Literalidad de la evidencia:** toda evidencia aceptada existe literalmente en el documento;
  los offsets los pone el **sistema**, nunca el modelo. Una cita ambigua se **rechaza**, no se
  desambigua.
- **Resistencia a inyección de prompt:** ataques propios del revisor (evidencia inventada,
  campos de autoridad, `verdict: AUTO_APPROVE`, offsets mentirosos, fragmentos malformados):
  ninguno cambió la decisión ni produjo evidencia no literal.
- **Sin descargas ni red en el parser opcional** (B5), verificado sobre el AST y en ejecución
  con los sockets inutilizados.

### 6.2. Trazabilidad
Motivos de decisión **estructurados** (código, severidad, fuente), no cadenas libres.
Procedencia del analizador sintáctico auditable. Esquemas versionados
(`relation-consensus-1.2.0`, `relation-ensemble-1.1.0`).

### 6.3. Umbrales y ground truth
**Ningún umbral fue rebajado**: `review_policy.py` con diff **cero** contra `dcded31`; los
`THRESHOLD` de `report.py` sin tocar (0 coincidencias en el diff). **El corpus y el ground
truth tienen diff cero.**

Dos ficheros del arnés **sí** cambiaron, deliberadamente y documentado:
- `matching.py` (+47): la **corrección del metro** de §2.2, que bajó la línea base.
- `report.py` (+20): la segunda pasada de determinismo no propagaba el selector, lo que
  producía un `deterministic=False` **espurio**. No toca ningún umbral.

---

## 7. Hallazgos que no eran el objetivo del programa

### 7.1. P0 estaba VIVO en el motor v2

El defecto P0 —el evaluador externo recibía el **ID** del segmento como "DOCUMENTO" en vez del
texto, y validaba evidencia y offsets contra él— **seguía presente en esta rama**. El fix
existía sólo en `exp/pr95-compare-base-contract-v1`, y esta rama salió de `main`, que nunca lo
tuvo. Reproducido por el revisor: el "documento" tenía **2 caracteres** (era el ID `"s1"`),
con `offsets_invalidos: fuera de rango [0,2]`. **Si el carril externo se hubiera ejecutado, el
rechazo habría sido del 100%.** Corregido en B7.

### 7.2. B7 cierra puertas; hoy no aporta señal

B7 vive entero en el carril externo, y **offline no hay carril externo**. Además, en producción
`document` no se pasa en los call-sites reales, de modo que la postura `REINFORCE` es
**inalcanzable**: la maquinaria de fragmentos y realineamiento **no puede mover ninguna
decisión**, sólo la traza. Su Δ es **0.0000** en los 8 runs. Es más seguro de lo anunciado,
pero hay que decirlo así: **B7 no mejora métricas, cierra puertas.**

### 7.3. Lección metodológica: tests verdes que no ejercitan la ruta real

Este patrón apareció **dos veces**, y es el hallazgo más transferible del programa:

- **B5:** los tests de pereza afirmaban `"spacy" not in sys.modules` **en un entorno donde
  spaCy no podía estar instalado**. Verdes y vacuos. El escenario que la invariante protegía
  —librería presente— no se ejercitaba. Se corrigió fabricando un paquete falso que explota
  al importarse.
- **B7:** P0 estaba vivo y **la suite no lo veía**, porque los tests metían el *texto* en el
  campo que en producción lleva el *ID*. El defecto sólo existía por el camino real.

A esto se añaden **dos incidentes de suite verde falsa por `.pyc` obsoleto** (mutaciones del
mismo tamaño en el mismo segundo). Desde entonces todo se ejecuta con
`PYTHONDONTWRITEBYTECODE=1` y purga de `__pycache__`.

**Conclusión: un test verde sólo vale si puede ponerse rojo.** Las pruebas de mutación no
fueron un adorno: destaparon 4 huecos en B5, 2 en B6 y 1 en B7 que la suite completa no veía.

---

## 8. Limitaciones y riesgos

1. **n=54 con dev == test.** No hay held-out. **Ninguna cifra de este informe estima el
   rendimiento en producción.**
2. **El 0.8140 de predicado es un TECHO en-corpus.** El rango honesto es **[0.42, 0.81]**: el
   suelo es la arquitectura sin expresiones calcadas, el techo incluye ajuste al corpus. **No
   apoyar decisiones de producción en el 0.81.**
3. **`pair_F1` no se movió** (0.8113). **11 relaciones siguen sin detectarse**, y si el par no
   se genera ninguna mejora posterior puede recuperarlo. **Es el techo real que queda.**
4. **`decision_correct` sigue bajo** (0.3488 / 0.4651) y el motor **se abstiene mucho**: de 30
   relaciones que el GT acepta, sólo propone 3 en `baseline1`.
5. **La precisión de la señal de negación que dispara los rechazos es 4/9 (44%).** Hoy los 5
   falsos positivos los absorbe la guarda de `MODEL_CONFLICT` — **"suerte, no garantía"**.
   **NO promocionar el camino de rechazo más allá de modo sombra** hasta que mejore.
6. **`veto_on_temporal_not_in_force` no dispara ni una vez** en el corpus: su aporte es **NO
   MEDIBLE**. No se le atribuye mérito.
7. **Nunca se ejecutaron proveedores reales en este programa.** Las cifras históricas de NVIDIA
   (52/52, 49/52, 0/52) son de **otro programa y otro motor**: **no se reclaman aquí.**
8. **La comparación con spaCy/Stanza está sin medir** (B5): no están instalados y no se
   descarga nada. No se afirma ninguna mejora.

### Defectos ABIERTOS (no corregidos, deliberadamente listados)

| Id | Gravedad | Defecto |
|---|:--:|---|
| B5-D4 | MEDIA | Retención global de texto crudo en el caché, sin TTL ni API pública de reset; cruza fronteras de documento en un proceso longevo |
| B5-D7 | INFO | El objeto cacheado se comparte por identidad; `object.__setattr__` podría corromperlo para todos los llamadores |
| B6 | MEDIA | Precisión 4/9 de la señal de negación (ver §8.5) |
| B7 | BAJA | La **envolvente de aceptación** de los dos caminos no es idéntica: el peldaño `TIER_NORMALIZED` es inalcanzable en la ruta real. Es fail-closed, pero es deriva futura |
| B7 | BAJA | `validate_external_verdict` **no tiene ningún llamador de producción**: una API de seguridad que nadie ejecuta puede pudrirse sin que nadie lo note |

---

## 9. Próximos pasos recomendados

1. **Atacar `pair_F1`** (las 11 FN). Es el único techo que este programa no tocó y el que más
   limita el resultado final.
2. **Conseguir un corpus con held-out real.** Sin él, ninguna cifra de predicado es defendible
   fuera del banco. Es el prerrequisito de cualquier decisión de producción.
3. **Mejorar la detección de negación** antes de promocionar el camino de rechazo.
4. **Medir con proveedores reales** (doble llave + autorización explícita del operador) para
   saber si los fragmentos baten al realineamiento **en este motor**.
5. **Cerrar B5-D4/D7** antes de que este código salga de sombra.
6. Instalar spaCy/Stanza en un entorno aislado y **medir** el parser fuerte en vez de suponerlo.

---

## DICTAMEN DEL REVISOR:

Dictámenes reales emitidos por los revisores independientes, bloque a bloque:

| Bloque | Dictamen | Nota |
|---|---|---|
| B0 | **CONFORME** | Metric-neutral verificado |
| B1 | **CONFORME** | Confirmó los dos sesgos de medición |
| B2 | **CONFORME** | Su ablación destapó el sobreajuste (0.907 → 0.814) |
| B3 | **CONFORME** | — |
| B4 | **CONFORME** | — |
| B5 | **CONFORME** | Condicionado: 4 mutantes sobrevivían; D1/D2 corregidos, D4/D7 abiertos |
| B6 | **CONFORME** | Condicionado a medir los vetos por separado → destapó el defecto del veto de tipos |
| **B7 (`237c631`)** | **NO CONFORME** | Techo ausente con la política por defecto; falso anclaje vivo en la ruta real; mutante N17 superviviente |
| **B7 (`1c444a9`)** | **CONFORME** | Las tres condiciones cumplidas y verificadas de forma independiente |

Cita literal de la re-auditoría de B7 (`1c444a9`):

> Las tres condiciones se cumplen de verdad, no de palabra: reproduje los dos contraejemplos
> sobre `237c631`, comprobé que desaparecen en `1c444a9`, apliqué N17 yo mismo (sobrevive en
> `237c631` a 2420 tests, muere en `1c444a9` por tres) y no encontré ninguna vía residual por
> la que los offsets del modelo lleguen a la decisión. […] La neutralidad métrica es real
> (Δ=0.0000 en 12 runs propios, `result_hashes` idénticos a `237c631`) y mis 11 mutantes
> murieron todos; los defectos que quedan son de gravedad baja y de documentación […], no de
> autoridad.

---

## DICTAMEN DEL SUPERVISOR:

**APTO COMO EXPERIMENTO. NO APTO PARA PRODUCCIÓN. NO FUSIONAR.**

**Qué doy por demostrado.** El motor v2 supera los cuatro gates experimentales con holgura y
lo hace por la razón correcta: se identificó que el cuello era un **techo mecánico** —el motor
no podía *nombrar* más de la mitad de las relaciones, ni emitir `reject` en absoluto— y se
levantó ese techo. El salto de predicado (0.209 → 0.814), dirección (0.628 → 0.930),
temporalidad (0.442 → 0.884) y strict_F1 (0.170 → 0.660) es real, reproducible y medido con
el mismo arnés en ambos lados. Añado un resultado que valoro por encima de esas cifras: **los
falsos ACCEPT pasan de 4 a 0 sin producir un solo rechazo falso.** Eso es seguridad, no
puntuación.

**Qué NO doy por demostrado, y pesa más que lo anterior.** Con **n=54 y dev == test** no hay
forma de saber si algo de esto generaliza. El 0.814 es un techo en-corpus; el rango honesto es
**[0.42, 0.81]** y ese suelo no es pesimismo, es lo que quedó cuando se purgaron las
expresiones calcadas del corpus. **Cualquiera que use el 0.81 para justificar una decisión de
producción estará usando mal este informe.** A eso se suma que `pair_F1` no se movió: 11
relaciones siguen sin detectarse y ninguna mejora posterior puede recuperarlas.

**Sobre el proceso.** La disciplina de editor + revisor independiente + supervisor se ganó su
coste con creces, y lo digo con casos concretos: la ablación del revisor de B2 destapó que
**~70% de la ganancia inicial era sobreajuste**; la exigencia del revisor de B6 de medir cada
veto por separado destapó que el veto de tipos juzgaba con una ontología mínima e
**informativa** como si fuera autoritativa, vetando el 44% de los candidatos por una laguna de
cobertura; y el **NO CONFORME de B7** impidió que se cerrara un bloque cuya garantía central
—"la IA externa nunca es autoridad"— **no se aplicaba en la configuración por defecto**.
Ninguno de los tres se habría detectado con una suite verde y un editor satisfecho.

Dos decisiones mías que quiero dejar por escrito, por si envejecen mal:

1. En B6 acepté **bajar el resultado publicado** de +0.0698 a +0.0465 al corregir el veto de
   tipos. Prefiero el número más bajo y correcto al más alto apoyado en un defecto.
2. En B7 el revisor ofrecía documentar la limitación **o** cablear el techo en v1. Exigí
   cablearlo, tras verificar que era metric-neutral. Documentar un agujero de seguridad que se
   puede cerrar sin coste habría sido la salida cómoda.

**Condiciones innegociables para cualquier paso más allá de modo sombra:**

- Obtener un corpus con **held-out real**. Es el prerrequisito, no una mejora opcional.
- **No promocionar el camino de rechazo**: la precisión de la señal de negación que lo dispara
  es **4/9**, y hoy los falsos positivos los absorbe una guarda por casualidad, no por diseño.
- Cerrar **B5-D4** (retención global de texto crudo sin TTL) y **B5-D7**.
- No presentar **B7** como una mejora: hoy **cierra puertas y no aporta señal**.

**Lección que me llevo del programa, por encima de cualquier métrica:** apareció **dos veces**
—B5 y B7— el mismo patrón de tests en verde que no ejercitaban la ruta real, y en el segundo
caso ocultaba un defecto que habría producido un **100% de rechazos** si el carril externo se
hubiera ejecutado. **Un test verde sólo vale si puede ponerse rojo**, y las pruebas de mutación
fueron lo único que lo demostró.

Firmado: Supervisor del programa. Sin merge, sin despliegue, sin ingesta. `main` intacto.
