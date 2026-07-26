# Held-out H1 — medición del motor ACTUAL (checkpoint CP-0)

**Fecha:** 2026-07-26 · **Rama:** `work/rel-v2e-b02-heldout` · **Base:** `origin/main` = `8fc7c8d`
**`code_sha` del motor medido:** `8fc7c8d45b2a03be92b7935f9d9b9c2bd32390bb` · `relation-pipeline-1.0.0`
**Arnés:** `data-engine/app/relations/benchmark/` (el único) · **Corpus:** `tests/data/relation_heldout` (H1 v1.0.0)
**Proveedores:** `local=NOT_EXECUTED`, `external=NOT_EXECUTED`, 0 llamadas · sin red, sin Neo4j, sin ingesta
**Determinismo:** `deterministic=True` en los 4 perfiles

> **Esto es la primera cifra de este programa medida fuera del corpus de desarrollo.** Se
> publica tal como salió. El corpus **no se ha modificado después de verla** (regla R5/R6 de
> `HELDOUT_POLICY.md`); sus hashes son los mismos que se sellaron antes de ejecutar.

---

## 1. Resumen en una frase

**`predicate_correct` cae de 0.8140 (B1) a 0.5385 (held-out)** — 0.5676 si se excluyen las
filas inacertables por construcción. **El sobreajuste que la ablación insinuaba es real y es
grande**, pero **la mejora del motor v2 también es real**: en el mismo corpus reservado, v2
casi cuadruplica a v1 (0.1538 → 0.5385) y mantiene **0 falsos ACCEPT**.

---

## 2. Tabla completa — carril del dictamen (`baseline1`)

| Métrica | B1 v1 | B1 **v2** | H1 v1 | H1 **v2** | Δ v2: H1 − B1 |
|---|--:|--:|--:|--:|--:|
| `predicate_correct` | 0.2093 | **0.8140** | 0.1538 | **0.5385** | **−0.2755** |
| `predicate_correct` *(sin filas inacertables)* | 0.2093 | 0.8140 | 0.1622 | **0.5676** | **−0.2464** |
| `direction_correct` | 0.6279 | **0.9302** | 0.8462 | **0.8974** | −0.0328 |
| `temporal_correct` | 0.4419 | **0.8837** | 0.4103 | **0.5641** | **−0.3196** |
| `strict_predicate.f1` | 0.1698 | **0.6604** | 0.1304 | **0.4565** | **−0.2039** |
| `evidence_correct` | 0.9070 | 0.9302 | 0.8718 | 0.8462 | −0.0840 |
| `offsets_correct` | 0.9302 | 0.9535 | 1.0000 | **1.0000** | +0.0465 |
| `decision_correct` | 0.3023 | 0.3488 | 0.3590 | **0.2564** | −0.0924 |
| `global_existence.f1` (**pair_F1**) | 0.8113 | 0.8113 | 0.8478 | **0.8478** | **+0.0365** |
| `global_existence` P / R | 0.827 / 0.796 | 0.827 / 0.796 | 0.830 / 0.867 | 0.830 / 0.867 | — |
| TP / FP / FN | 43 / 9 / 11 | 43 / 9 / 11 | 39 / 8 / 6 | 39 / 8 / 6 | — |
| `epistemic_correct` | 0.8605 | 0.8605 | 0.8974 | 0.8974 | +0.0369 |
| `negation_correct` | 0.9070 | 0.8837 | 0.8974 | 0.8974 | +0.0137 |
| `types_correct` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 |
| **Falsos ACCEPT** (GT `REJECT` → `ACCEPT`) | **4** | **0** | **6** | **0** | **0** |
| Falsos ACCEPT en sentido amplio (GT `REJECT` o `REVIEW` → `ACCEPT`) | 8 | **0** | 11 | **0** | 0 |
| n emparejadas (denominador estructural) | 43 | 43 | 39 | 39 | — |
| Relaciones de ground truth | 54 | 54 | 45 | 45 | — |

## 3. Carril `ensemble_offline`

| Métrica | B1 v1 | B1 **v2** | H1 v1 | H1 **v2** |
|---|--:|--:|--:|--:|
| `decision_correct` | 0.3953 | **0.4651** | 0.4615 | **0.3590** |
| **Falsos ACCEPT** (GT `REJECT` → `ACCEPT`) | **2** | **0** | **4** | **0** |
| Falsos ACCEPT en sentido amplio | 6 | **0** | 5 | **0** |
| Resto de métricas | = §2 | = §2 | = §2 | = §2 |

El `ensemble_offline` sólo mueve la decisión de consenso; predicado, dirección, temporalidad,
evidencia y `pair_F1` son idénticos al carril `baseline1` en ambos corpus.

## 4. Subconjunto sin fuentes de ruido (`baseline1`, sin `src-09` y `src-30`)

| Métrica | H1 v1 | H1 **v2** |
|---|--:|--:|
| `predicate_correct` | 0.1579 | **0.5526** |
| `temporal_correct` | 0.4211 | **0.5789** |
| `strict_predicate.f1` | 0.1364 | **0.4773** |
| `pair_F1` | 0.8636 | **0.8636** |
| `decision_correct` | 0.3684 | **0.2632** |
| Falsos ACCEPT (sentido amplio) | 10 | **0** |

Quitar el ruido **no salva la cifra**: el predicado sube de 0.5385 a 0.5526. La caída respecto
a B1 no la causan los casos de ruido.

## 5. Gates del arnés (umbrales **sin tocar**, los mismos de B1)

| Gate | Umbral | B1 v2 | H1 **v2** | H1 v1 |
|---|--:|--:|--:|--:|
| `predicate_structural` | ≥ 0.50 | 0.8140 ✅ | **0.5385 ✅ (por 0.04)** | 0.1538 ❌ |
| `temporality` | ≥ 0.60 | 0.9600 ✅ | **0.7200 ✅** | 0.6400 ✅ |
| `evidence` | ≥ 0.80 | 0.9302 ✅ | 0.8462 ✅ | 0.8718 ✅ |
| `offsets` | ≥ 0.90 | 0.9535 ✅ | 1.0000 ✅ | 1.0000 ✅ |
| `negation` | ≥ 0.80 | 1.0000 ✅ | 1.0000 ✅ | 1.0000 ✅ |
| `rumors` | ≥ 0.60 | 1.0000 ✅ | **0.0000 ❌** | 0.0000 ❌ |
| `simple_relations` | ≥ 0.80 | 0.9333 ✅ | 0.9565 ✅ | 0.9565 ✅ |
| `determinism` / `workspace_contamination` | duro | ✅ | ✅ | ✅ |

**Veredicto del arnés:** B1 v2 = `APTO PARA CONTINUAR EN MODO SOMBRA`; **H1 v2 = `APTO CON
REVISIÓN DE CASOS CONFLICTIVOS`**. El held-out **degrada el veredicto** del propio arnés, sin
que se haya movido ni un umbral.

`rumors` cae a 0/2: los dos rumores de H1 (`src-03`, `src-23`) se clasifican mal. Es n=2, así
que **no soporta ninguna conclusión fuerte** — pero en B1 era 2/2, y esa cifra tampoco la
soportaba. Es exactamente el tipo de métrica que un corpus de 54 relaciones hace parecer
resuelta.

## 6. Matriz de decisión (GT → predicho), `baseline1` v2

| | ACCEPT | REJECT | REVIEW |
|---|--:|--:|--:|
| **GT ACCEPT** (23 emparejadas) | **0** | 1 | 22 |
| **GT REJECT** (7 emparejadas) | **0** | 2 | 5 |
| **GT REVIEW** (9 emparejadas) | **0** | 1 | 8 |

Con `ensemble_offline` la fila ACCEPT pasa a `4 / 1 / 18`. La lectura de B1 se **confirma y se
agrava**: el motor v2 no produce falsos ACCEPT, pero **en held-out no propone prácticamente
nada**: de 23 relaciones que el ground truth acepta, `baseline1` propone **0**. Como política de
producción esto no es utilizable; como modo sombra con un humano detrás, sigue siendo seguro.

## 7. Predicados emitidos

| | v1 | v2 |
|---|---|---|
| Distintos | **5** | **11** |
| Distribución (v2) | — | `MEMBER_OF` 11 · `LOCATED_IN` 9 · `PARTICIPATED_IN` 7 · `OWNS` 6 · `RELATED_TO` 6 · `LEADS` 3 · `CAUSED` 1 · `FOUNDED` 1 · `GUARDS` 1 · `KNOWS` 1 · `PARENT_OF` 1 |
| Distribución (v1) | `LOCATED_IN` 27 · `MEMBER_OF` 7 · `OWNS` 6 · `PARTICIPATED_IN` 3 · `RELATED_TO` 4 | — |

El techo mecánico sigue roto (v1 colapsa el 58 % de sus salidas en `LOCATED_IN`), pero en
held-out v2 emite **11** predicados distintos frente a los **18** de B1. Las familias que en B1
acertaba y aquí no aparecen nunca: `ALLIED_WITH`, `ENEMY_OF`, `MARRIED_TO`, `SIBLING_OF`,
`MENTOR_OF`, `ALIAS_OF`, `LIVES_IN`, `SUCCEEDED`, `TRUSTS`, `CREATED`. **Todas son familias con
expresiones léxicas que B1 contenía y H1 formula de otra manera.** Ése es el mecanismo concreto
del sobreajuste, no una hipótesis.

## 8. Acierto por predicado en held-out (v2)

| Predicado | soporte | emparejadas | acertadas |
|---|--:|--:|--:|
| `MEMBER_OF` | 8 | 7 | **7** |
| `LEADS` | 6 | 6 | 3 |
| `CAUSED` | 4 | 3 | 1 |
| `OWNS` | 4 | 4 | 2 |
| `PARTICIPATED_IN` | 3 | 3 | **3** |
| `NO_RELATION` *(centinela)* | 3 | 1 | 0 |
| `GUARDS` | 2 | 2 | 0 |
| `LIVES_IN` | 2 | 2 | 0 |
| `LOCATED_IN` | 2 | 2 | **2** |
| `PARENT_OF` | 2 | 1 | 1 |
| `ALIAS_OF`, `ALLIED_WITH`, `MARRIED_TO`, `MENTOR_OF`, `SIBLING_OF` | 1 c/u | 1 c/u | **0** |
| `ENEMY_OF` | 1 | 0 (FN) | 0 |
| `FOUNDED`, `KNOWS` | 1 c/u | 1 c/u | **1** |
| `SPONSORS` *(centinela)* | 1 | 1 | 0 |

## 9. Lectura por caso (`baseline1`, predicado)

| Caso | Qué prueba | v1 | **v2** | FN |
|---|---|--:|--:|--:|
| H-01 alianza que termina → enemistad | relación que cambia, simétricas | 0/1 | **0/1** | 1 |
| H-02 voz pasiva, sujeto/objeto invertidos | pasiva | 0/2 | **1/2** | 0 |
| H-03 rumor que nunca se vuelve hecho | rumor + negación | 0/2 | **2/2** | 0 |
| H-04 culpable exonerado después | negación, causa real | 0/2 | **1/2** | 1 |
| H-05 salto de tres meses, relevo de mando | salto temporal | 0/2 | **2/2** | 0 |
| H-06 flashback | dos marcos temporales | 0/2 | **1/2** | 0 |
| H-07 conversación no relacionada | ruido | 0/1 | **0/1** | 2 |
| H-08 mismo nombre en dos workspaces | homonimia | 1/3 | **2/3** | 0 |
| H-09 Unicode y puntuación | `Заря-7`, `Ὠκεανός`, «…», — | 1/2 | **2/2** | 0 |
| H-10 texto repetido literalmente | deduplicación | 0/1 | **0/1** | 0 |
| H-11 frase muy larga | una relación al final | 0/1 | **0/1** | 0 |
| H-12 fragmento ambiguo | pronombre sin referente | — | — | 1 |
| H-13 hipótesis de jugador | fuera de ficción | 0/1 | **1/1** | 0 |
| H-14 fecha vaga | temporalidad sin fecha | 1/1 | **1/1** | 0 |
| H-15 predicado desconocido | cobertura de ontología | 0/1 | **0/1** | 0 |
| H-16 descubrimiento posterior | hecho antiguo, hallazgo nuevo | 0/1 | **0/1** | 0 |
| H-17 confirmado por dos fuentes | redundancia | 0/2 | **1/2** | 0 |
| H-18 relación contradicha | conflicto entre fuentes | 0/2 | **0/2** | 0 |
| H-19 fuente retirada del canon | descanonización | 1/1 | **1/1** | 0 |
| H-20 escena en varias sesiones | continuidad + coocurrencia engañosa | 0/3 | **3/3** | 0 |
| H-21 entidades repetidas | 5 menciones, 3 relaciones | 1/3 | **1/3** | 0 |
| H-22 familia en voz activa | simétricas, filiación implícita | 0/2 | **0/2** | 1 |
| H-23 intención futura | `INTENDED` + `FUTURE` | 0/1 | **1/1** | 0 |
| H-24 alias y localización débil | alias simétrico | 1/2 | **1/2** | 0 |

Dónde v2 **generaliza bien**: escenas partidas, saltos temporales, rumores, homonimia entre
workspaces, Unicode y puntuación, hipótesis de jugador, fuente retirada. Dónde **no**:
relaciones simétricas expresadas con verbos nuevos (H-01, H-22, H-24), predicados de familia
(`MARRIED_TO`, `SIBLING_OF`, `MENTOR_OF`), causalidad (H-04), contradicción entre fuentes
(H-18), texto repetido (H-10) y frases largas (H-11).

## 10. ¿Hay sobreajuste? Sí. ¿Cuánto?

**Cuánta ganancia reproduce fuera del corpus** (misma métrica, mismo arnés, mismo motor):

| Métrica | Ganancia v1→v2 en B1 | Ganancia v1→v2 en H1 | % que generaliza |
|---|--:|--:|--:|
| `predicate_correct` | +0.6047 | +0.3847 | **64 %** |
| `predicate_correct` (sin centinelas) | +0.6047 | +0.4054 | **67 %** |
| `strict_predicate.f1` | +0.4906 | +0.3261 | **66 %** |
| `temporal_correct` | +0.4418 | +0.1538 | **35 %** |
| `direction_correct` | +0.3023 | +0.0512 | 17 % (v1 ya partía de 0.846: hay techo) |

**Dónde cae el 0.81 dentro del rango honesto [0.42, 0.81].** El held-out lo sitúa en
**0.54–0.57**, es decir a un **30–37 %** del recorrido entre el suelo y el techo declarados.
**Está mucho más cerca del suelo que del techo.** El rango publicado en
`relation-engine-v2-results.md` §8.2 era correcto y su advertencia — *"no apoyar decisiones de
producción en el 0.81"* — queda **confirmada por medición**, no por prudencia.

**Lectura honesta, sin suavizar:**

1. **El 0.8140 no es el rendimiento del motor.** Es el rendimiento del motor *sobre el corpus
   con el que se construyó*. Fuera de él, **~0.54**. Quien haya usado 0.81 para una decisión,
   ha usado una cifra inflada en **+0.27 absolutos**.
2. **Pero el motor v2 no es humo.** Dos tercios de la ganancia de predicado y de `strict_F1`
   **sobreviven** a un corpus que no vio nunca, escrito con otras entidades y otras expresiones.
   Pasar de 0.15 a 0.54 en terreno virgen es una mejora grande y real.
3. **La temporalidad es lo que peor generaliza** (35 %). El 0.8837 de B1 no es defendible: en
   held-out es 0.5641. `temporal_v2` está mucho más pegado al corpus de desarrollo de lo que
   sus cifras sugerían.
4. **El mecanismo del sobreajuste es identificable**, no misterioso: las familias de predicado
   que desaparecen en held-out son exactamente aquéllas cuyas expresiones léxicas B1 contenía
   y H1 formula de otro modo (§7). Es cobertura léxica, no arquitectura.
5. **Lo que NO se degrada** es tan informativo como lo que sí: `pair_F1` **sube** (0.8113 →
   0.8478), `offsets_correct` es **perfecto** (1.0000), los tipos son perfectos, la negación se
   mantiene y **los falsos ACCEPT siguen siendo 0**. La propiedad de seguridad de v2 —*no
   afirma lo que no debe*— **generaliza**. Ésa es la parte del programa que aguanta.
6. **La decisión empeora en held-out** (0.3488 → 0.2564 en `baseline1`; 0.4651 → 0.3590 en
   `ensemble`) y la abstención se vuelve casi total: **0 propuestas ACCEPT de 23 posibles**.
   La condición del supervisor —"antes de activar v2 hay que comprobar que el flujo de revisión
   soporta ese volumen"— **se endurece**: en held-out el volumen es el 100 %.
7. **El gate `predicate_structural` pasa por 0.04.** Una relación más fallada y el motor v2
   **no** pasaría su propio gate en held-out. La holgura de B1 (0.31 sobre el umbral) era, en
   buena medida, ajuste al corpus.

**Lo que este resultado NO dice.** No dice que el motor rinda 0.54 en producción: H1 es
sintético, n=45, y lo escribió el mismo programa que mide. Convierte el rango [0.42, 0.81] en
una estimación **mucho más estrecha y mucho más baja**, pero no en una cifra de producción.
Para eso hace falta el material real de §7 de `HELDOUT_POLICY.md`.

## 11. Qué NO se ha podido medir

- **Nada con proveedores reales.** Ollama y NVIDIA: `NOT_EXECUTED`, 0 llamadas. Se necesita la
  doble llave del arnés y autorización explícita del operador.
- **Nada sobre material real** (PDFs de rol, vídeos de partidas). Sin acceso a vm100 y sin
  intentarlo: §7 de la política es plan, no resultado.
- **Ninguna comparación con spaCy/Stanza**: no están instalados y no se descarga nada.
- **`rumors`, `hipótesis`, `intención`**: n = 2, 1 y 1 respectivamente. Se reportan porque la
  cobertura lo exigía, pero **no soportan ninguna conclusión**.
- **La calidad del ground truth de H1**: es anotación de **un solo pase** (B1 tuvo doble pase).
  Las notas por relación están, pero no hay segundo anotador ni medida de acuerdo. Es la
  limitación metodológica más seria de esta medición y se declara aquí, no en una nota al pie.
- **El conjunto de validación intermedio** no existe todavía: hoy sólo hay dev (B1) y held-out
  final (H1). Elegir entre variantes usando H1 lo quemaría (regla R12).
- **`decision_correct` con la política de consenso real de producción**: sólo se han medido
  `auto` (`baseline1`) y el recalibrado `ensemble_offline`.

## 12. Reproducción

```bash
cd data-engine/app
for mode in baseline1 ensemble_offline; do
  for sel in v1 v2; do
    PYTHONDONTWRITEBYTECODE=1 python3 -m relations.benchmark.cli \
      --mode "$mode" --predicate-selector "$sel" \
      --corpus-dir tests/data/relation_heldout \
      --out-json "/tmp/ho_${mode}_${sel}.json"
  done
done
```

Integridad y sellado: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_relation_heldout_corpus.py -q`
(23 tests). El corpus B1 queda intacto: su test sigue en verde (23 tests) y su `git diff` es vacío.
