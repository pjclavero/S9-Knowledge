# Bloque 2 — Selector de predicados v2 y **purga del sobreajuste** (cifra honesta)

**Programa:** motor de relaciones v2 · **Rama:** `feat/relation-engine-v2-hybrid` ·
**Antecedente:** `B0-benchmark-and-reconciliation.md`, Bloque 1 (ontología, `089830b`).

Bloque 2 introdujo dos cosas: (A) la **corrección del metro** de predicado
(`matching.structural_flags` acredita con `ontology.predicate_exact_strict`, no con
`vocabulary.predicates_match`) y (B) el **selector de predicados v2** estructurado
(generación de candidatos > 5, filtro dominio/rango, puntuación, abstención por
margen/sin evidencia, fallback seguro a `RELATED_TO`), **detrás de flag y con `v1`
como default metric-neutral**.

Este documento cierra la **purga del sobreajuste** detectada por revisión externa: parte
del salto de `predicate_exact` no venía de la arquitectura del selector sino de
**expresiones activas/pasivas calcadas de frases concretas del corpus** en
`relations/ontology.py`. Con `dev == test` y `n = 54`, esas expresiones inflan la
métrica sin evidencia de que generalicen. Se han eliminado y se fija la **cifra honesta**.

Trabajo offline, sin red, sin escritura Neo4j, determinista. **No** se bajan
`THRESHOLDS`, **no** se toca el GT/corpus, **no** se relaja ningún assert. El default
`v1` sigue siendo bit-a-bit idéntico al comportamiento base.

---

## 1. Las tres cifras (metro corregido, `--mode baseline1`, corpus real n=52 predicciones)

| Configuración | predicate_exact | direction_exact | strict_F1 | evidence_correct | RELATED_TO_rate | abstention_rate |
|---|---|---|---|---|---|---|
| **base** (`--predicate-selector v1`) | 0.2093 | 0.6279 | 0.1698 | 0.9070 | 0.3077 | 0.0000 |
| **arquitectura pura** (v2 + ontología B1 `089830b`, sin expresiones B2) | 0.4186 | 0.8140 | 0.3396 | 0.9302 | 0.0962 | 0.1154 |
| **v2 tras purga** (v2 + ontología purgada) | **0.8140** | 0.8372 | **0.6604** | 0.9302 | 0.2115 | 0.3077 |
| v2 *sin purgar* (estado `7ae2f6d`, referencia del sobreajuste) | 0.9070 | 0.8837 | 0.7358 | 0.9302 | 0.1538 | 0.2500 |

`pair_F1` (existencia) = **0.8113** en las cuatro configuraciones: la purga y el selector
**no** tocan la detección de pares, sólo la etiqueta de predicado.

**Gates.** El gate experimental de B2 es `predicate_structural >= 0.50`
(`tests/test_relation_calibration_final_quality_block9.py:239`,
`tests/test_relation_v2_b2_predicate.py:327`). Tras la purga:
`predicate_exact = 0.8140 >= 0.50` → **PASA**. No hay gate numérico independiente para
`strict_F1` en B2 (informativo: 0.6604).

---

## 2. Qué se eliminó y por qué

Criterio: se **elimina** toda expresión que sea una **frase concreta del corpus**, un
**verbo nuevo no presente en B1**, un **sustantivo desnudo semánticamente débil** o una
forma **semánticamente dudosa/opuesta**. Se **conserva** sólo la **inflexión pura**
(género/número/tiempo/persona/acento) de un verbo/participio ya presente en B1 o las
variantes generales que la revisión marcó explícitamente como conservables. Ante la
duda: **eliminar** (preferimos honestidad a número alto).

| Predicado | Expresión eliminada | Motivo |
|---|---|---|
| PARENT_OF | `de esa union nacio` | Frase literal del corpus (src-12, GT "De esa unión nació Bran"). No generaliza. |
| PARENT_OF | `nacio` | "nacer" ≠ "ser progenitor de"; dirección semántica equivocada + genérica. |
| ALLIED_WITH | `su alianza con` | Calco de src-10 ("rompió su alianza con el Gremio"). |
| ALLIED_WITH | `una alianza con` | Fragmento posesivo/artículo del calco anterior. |
| ALLIED_WITH | `alianza con` (activa) | Fragmento nominal, no inflexión de un verbo B1; cobertura de alianza ya en B1 (`aliado con/de`, `en alianza con`, `sello una alianza con`). |
| ALLIED_WITH | `alianza` (pasiva) | Sustantivo desnudo: marca temática, no relacional; alto falso positivo. |
| ENEMY_OF | `enemigo declarado` | Colocación del corpus (src-13). No es inflexión de un verbo B1. |
| ENEMY_OF | `enemigo` (desnudo) | Sustantivo genérico de alto falso positivo. |
| LOCATED_IN | `se celebra en` | "celebrar" es verbo **nuevo** (no en B1); calco de src-15 ("El Torneo se celebra en la Torre"). |
| LIVES_IN | `viva en` | Subjuntivo (no aserción) calcado de src-16 ("aún viva en el Ateneo"). Las formas asertivas `vive en`/`vivia en` se conservan. |
| OWNS | `robado por` / `robada por` | "robar" = hurto, no posesión; el crédito OWNS es una lectura de anotación específica del corpus (src-14). |
| MENTOR_OF | `le enseno` | Clítico específico del corpus (src-07, "Vayra le enseñó el arte"). |
| MENTOR_OF | `enseno el` | Calco de la misma frase ("enseñó **el** arte de las runas"). |
| MENTOR_OF | `enseno a` | "enseñar" es verbo **nuevo** en la familia (B1: mentor/maestro/entrenó); se elimina toda la activa `enseñar`. |
| MENTOR_OF | `maestro` / `maestra` (desnudos) | Título polisémico sin argumento (`de X`); calco de coreferencia de src-07 ("Su maestra, la hechicera Vayra"). |
| KNOWS | `domina` | Marcado por revisión como semánticamente dudoso; calco de src-09 ("domina la Escritura Astral"). |
| SUCCEEDED | `herede` | Forma anómala calcada del token exacto del corpus (src, "Nima herede el trono"). |

## 3. Qué se conservó (variantes generales defendibles)

Se conservan por ser **inflexiones puras** de verbos/participios ya en B1 o variantes que
la revisión marcó como generales del español (aparecerían en textos **no vistos** para el
predicado):

- **FOUNDED:** `funda`, `fundada por` (inflexión de `fundo`/`fundado por`).
- **CREATED:** `forja`, `creada por`, `forjada por` (tiempo/género de `forjo`/`creado por`/`forjado por`).
- **OWNS:** `pertenece a`, `pertenece al` (marcado como general por revisión).
- **PARTICIPATED_IN:** `participaron`, `participa`, `participar` (inflexiones de `participo`); `compitio en`, `competira en` (marcado como general: `compitió en`).
- **SUCCEEDED:** `sucede a`, `hereda`, `heredar` (inflexiones de `sucedio a`/`heredo`).
- **TRUSTS:** `confio en` (tiempo de `confia en`).
- **CAUSED:** `desencadenar` (infinitivo de `desencadeno`).
- **GUARDS:** `guardada por`, `custodiada por` (género de `guardado por`/`custodiado por`).
- **LIVES_IN:** `vivia en` (tiempo de `vive en`).
- **MENTOR_OF:** `maestra de` (género de `maestro de`).
- **ALIAS_OF:** `conocido como`, `conocida como`, `apodado`, `apodada` (marcadas como generales).

---

## 4. Declaración de honestidad (magnitud y límite de generalización)

**La cifra tras purga — `predicate_exact = 0.8140`, `strict_F1 = 0.6604` — es la
magnitud honesta medible** sobre este corpus con el metro corregido, una vez retirado el
crédito por frases calcadas. Supera el gate experimental de B2 (0.50).

**Advertencia de generalización (crítica).** El corpus tiene `dev == test` y `n = 54`.
En esa condición **cada expresión conservada casa exactamente con su única instancia del
corpus**, así que la separación empírica entre "variante general" y "calco" es
**imposible** sólo con la métrica: toda forma añadida acierta su frase. Por eso la
magnitud honesta se acota, no es un punto:

- **Suelo de generalización (conservador): `0.4186`** — arquitectura del selector +
  expresiones **sólo B1**; es lo que rinde el selector si **ninguna** de las inflexiones
  conservadas generaliza a texto no visto.
- **Techo en-corpus: `0.8140`** — arquitectura + expresiones generales conservadas, cada
  una acertando su instancia del corpus.

El valor real sobre datos **held-out** es desconocido y cae en `[0.42, 0.81]`. **No puede
declararse validada la generalización sin un conjunto held-out** (o al menos `dev ≠ test`
con más volumen). Buena parte del sobreajuste retirado resultó **redundante** con las
señales (`cues`) y los priors de tipo del selector: eliminar `enemigo declarado`,
`robado por`, `se celebra en` o `alianza con` **no** hundió la métrica porque la
arquitectura recupera esas instancias por otra vía — lo que confirma que el mérito está en
el selector, no en el léxico calcado.

**Recomendación:** reportar la cifra honesta como el **rango `0.42–0.81`** con `0.42`
como suelo defendible sin held-out, no un único número optimista. La reducción de revisión
humana u otras decisiones de producción **no** deben apoyarse en `0.81` hasta disponer de
held-out.

---

## 5. Reproducción

```bash
# desde data-engine/app
python -m pytest tests/test_relation_v2_b2_predicate.py \
                 tests/test_relation_v2_b1_ontology.py \
                 tests/test_relation_calibration_final_quality_block9.py -q
python -m pytest tests/ -k relation -q
```

A/B con el metro corregido: `run_benchmark(corpus, mode="baseline1",
predicate_selector={"v1"|"v2"})` + `match_predictions` + `metrics.structural_quality`
/ `metrics.strict_metrics`. La columna "arquitectura pura" se obtiene ejecutando `v2`
contra `git show 089830b:data-engine/app/relations/ontology.py`.
