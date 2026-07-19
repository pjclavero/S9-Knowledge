# Informe de validación — Bloque 3: Normalización de predicados

**Fecha:** 2026-07-19
**Rama:** `feat/relation-predicate-normalization-v1`
**Vocabulario:** `relation-vocab-1.0.0` (`relations.vocabulary`)
**Corpus:** `relation-benchmark v1` (sintético; 16 fuentes + fixtures)
**Baseline evaluada:** `baseline1` (pipeline offline determinista)
**Métrica:** `strict_predicate` (par correcto **y** predicado exacto)

## 1. Objetivo

Dejar de comparar predicados por **igualdad de string** y compararlos por su
**significado canónico**, de modo que sinónimos léxicos del mismo predicado
(`LIVES_IN` vs `LOCATED_IN`, `ENEMY_OF` vs `ENEMIES_WITH`, …) dejen de contar
como fallos en el benchmark. El cambio se limita a una **capa de normalización
semántica** nueva y a su uso en el scoring del benchmark; **no** toca el
contrato de datos, ni las plantillas de prompt, ni el corpus.

## 2. Diseño

### 2.1 Vocabulario canónico (fuente única)

`relations/vocabulary.py` define 10 predicados canónicos reutilizando
`prompts.KNOWN_PREDICATES` como **fuente única** (no se teclea a mano la
ontología):

```text
ALLIED_WITH · CAUSED · ENEMIES_WITH · KIN_OF · LOCATED_IN
MEMBER_OF · OWNS · PARTICIPATED_IN · PRECEDES · SUCCESSOR_OF
```

La compatibilidad de tipos (`TYPE_COMPATIBILITY`) se **deriva** de las propias
plantillas (`prompts.TEMPLATES`), de nuevo para no duplicar la ontología.

### 2.2 Alias SIN pérdida de información

`PREDICATE_ALIASES` mapea **solo sinónimos léxicos/morfológicos** de un canónico
ya existente, nunca matices semánticos nuevos:

| Alias | Canónico |
|---|---|
| `ENEMY_OF` / `ENEMY_WITH` | `ENEMIES_WITH` |
| `SUCCEEDED` | `SUCCESSOR_OF` |
| `LIVES_IN` | `LOCATED_IN` |
| `ALLY_OF` | `ALLIED_WITH` |
| `MEMBER` | `MEMBER_OF` |

Las claves se normalizan tipográficamente (`normalize_predicate`) antes de
comparar, por robustez ante la entrada.

### 2.3 Simétricas

`SYMMETRIC_PREDICATES = {ALLIED_WITH, ENEMIES_WITH, KIN_OF}` son predicados
**no orientados** (UNDIRECTED en las plantillas). El scoring los trata sin
penalizar la orientación sujeto↔objeto (véase §2.7).

### 2.4 Inversas (mecanismo, vacío en v1)

`INVERSE_PREDICATES` está **vacío** en v1: no hay pares de canónicos que sean
inversos limpios entre sí (`PRECEDES` y `SUCCESSOR_OF` **no** lo son — uno es
orden temporal, el otro sucesión de cargo). `inverse_of()` devuelve `None`
siempre. El mecanismo queda definido para que un v2 pueda añadir pares sin
cambiar la API.

### 2.5 `out_of_vocab_v1` → fallback humano (honesto)

`OUT_OF_VOCAB_V1` recoge predicados de dominio **conocidos pero sin canónico
limpio en v1**:

```text
MENTOR_OF · GUARDS · FOUNDED · ALIAS_OF · TRUSTS · LEADS · KNOWS
CREATED · PARENT_OF · SIBLING_OF · MARRIED_TO · CHILD_OF · SPOUSE_OF
```

**No se colapsan** contra ningún canónico porque aportan semántica que ninguno
cubre sin pérdida. En particular, los subtipos de parentesco
(`PARENT_OF`/`SIBLING_OF`/`MARRIED_TO`/`CHILD_OF`/`SPOUSE_OF`) **no** se funden
en `KIN_OF`: hacerlo fabricaría cobertura y perdería información. Estos
predicados marcan `requires_human=True` y son **candidatos a un vocab v2** que
requeriría **plantillas nuevas** (área compartida → coordinación futura).

### 2.6 Compatibilidad de tipos

`types_compatible(pred, subject_type, object_type)` valida el par de tipos
contra `TYPE_COMPATIBILITY`. Para simétricas acepta **ambos órdenes**. Tipos
`None` nunca son compatibles (no se puede verificar la ontología sin tipo).

### 2.7 Versión y trazabilidad

`VOCAB_VERSION = "relation-vocab-1.0.0"` es **independiente** de
`SCHEMA_VERSION`: ampliar el vocabulario no cambia el contrato de datos, solo
esta capa de mapeo. `canonicalize_predicate(raw)` devuelve
`PredicateCanonicalization(raw, normalized, canonical, status, rule,
vocab_version, requires_human)`, de forma que cada decisión queda **trazada**
(regla aplicada + versión del vocabulario). La canonicalización se aplica a
**ambos lados** del benchmark (predicho **y** ground truth), no solo al
predicho.

## 3. Resultados: ANTES / DESPUÉS

Benchmark `baseline1` sobre `relation-benchmark v1`, métrica `strict_predicate`
(medido por el Organizador):

| Métrica | ANTES (igualdad de string) | DESPUÉS (canonicalización) | Δ |
|---|---|---|---|
| Precision | 0.1731 | 0.2115 | +0.0384 |
| Recall | 0.1667 | 0.2037 | +0.0370 |
| F1 | 0.1698 | 0.2075 | +0.0377 |
| Exact TP | 9 | 11 | **+2** |
| `recall_exact` | 16.67 % | 20.37 % | +3.70 pp |
| `existence_tp` | 43 | 43 | 0 |

La ganancia de **+2 exact TP** procede íntegramente del alias
`LIVES_IN → LOCATED_IN` (2 casos que antes contaban como fallo de predicado).
`existence_tp` se mantiene en **43**: el emparejamiento de pares no cambia, solo
mejora la corrección del predicado exacto.

## 4. Análisis honesto: por qué la mejora es modesta

La mejora es real pero pequeña, y la causa es del **lado del pipeline**, no del
vocabulario:

- `baseline1` es un pipeline **offline determinista** que solo emite un
  subconjunto de predicados: `MEMBER_OF`, `OWNS`, `LOCATED_IN`,
  `PARTICIPATED_IN`, `RELATED_TO`.
- La **mayoría de los alias no se ejercita**: `ENEMY_OF`, `SUCCEEDED`,
  `ALLY_OF`, `MEMBER` **nunca se predicen** en esta baseline, así que el
  vocabulario no tiene ocasión de convertirlos.
- El único alias que la baseline sí dispara es `LIVES_IN → LOCATED_IN`, de ahí
  los +2 TP y nada más.

El vocabulario está **listo y a la espera** de que quien emita predicados más
ricos lo aproveche:

- **Bloque 6 (ensemble calibrado):** cuando Ollama/NVIDIA/el ensemble emitan el
  abanico completo de predicados (incluidos los que hoy se aliasan), la
  canonicalización recuperará esos aciertos sin cambios adicionales.
- **Bloque 7 (reejecución del benchmark):** medirá el efecto real del
  vocabulario ya con predicados ricos en juego.

En otras palabras: el techo actual lo pone la **cobertura de predicados de la
baseline**, no la normalización. No se ha inflado la cobertura moviendo
predicados dudosos a canónicos para «mejorar» el número — esa honestidad es
justamente lo que deja los subtipos de parentesco y los 8 predicados de dominio
en `out_of_vocab_v1`.

## 5. Garantías (qué NO se ha tocado)

- **Contrato de datos:** intacto. `SCHEMA_VERSION` no cambia; `VOCAB_VERSION` es
  una capa aparte.
- **Plantillas de prompt (`prompts.TEMPLATES`) y ontología:** no se modifican;
  se **reutilizan** como fuente única (canónicos + tipos).
- **Corpus del benchmark:** no se altera; sin corpus privado (solo sintético).
- **Áreas compartidas:** no se tocan. Promover cualquier `out_of_vocab_v1` a
  canónico exigiría plantillas nuevas y, por tanto, **coordinación** (vocab v2).
- **Alcance del cambio de código (por otros agentes):** solo `vocabulary.py`
  (nuevo) y el scoring `benchmark/matching.py` (`predicate_correct` ahora usa
  `predicates_match`, alias-aware, y trata simétricas sin penalizar
  orientación).

## 6. Estado de producción

Intacta. No se tocó VM105, Neo4j, `auth.db`, `jobs.db`, timers ni servicios.
`S9K_ALLOW_REAL_INGEST = off`. `release/rc6-candidate = 15ae1d4` (inmutable).
