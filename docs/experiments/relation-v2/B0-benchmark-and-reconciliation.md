# Bloque 0 — Arnés de evaluación único y reconciliación GT/ontología (híbrida)

**Programa:** motor de relaciones v2 · **Rama:** `feat/relation-engine-v2-hybrid` ·
**Base:** `dcded31` (origin/main) · **Antecedente:** `docs/relation-engine-v2-audit-and-design.md`
(Etapa 1 cerrada).

Bloque **foundational**. **NO** cambia el selector de predicado
(`relations/pipeline.py:_choose_predicate` sigue emitiendo sus 5 predicados), **NO**
baja umbrales, **NO** modifica el ground truth y **NO** amaña ninguna métrica. Trabajo
offline, sin red, sin escritura Neo4j.

---

## 1. Arnés de evaluación ÚNICO

### 1.1. Fuente única

El **único arnés** de evaluación del motor de relaciones es el paquete
`data-engine/app/relations/benchmark/`:

| Componente | Fichero | Rol |
|---|---|---|
| Runner (pipeline REAL, offline) | `relations/benchmark/runner.py` (`run_benchmark`) | Ejecuta el pipeline R8 real por fuente y agrega predicciones |
| Emparejamiento pred↔GT | `relations/benchmark/matching.py` (`match_predictions`) | Empareja por par NO ORDENADO; predicado vía vocabulario canónico |
| Métricas | `relations/benchmark/metrics.py` | Global, strict, por predicado, estructural |
| Report / gates / dictamen | `relations/benchmark/report.py` (`build_report`, `THRESHOLDS`) | Gates por separado + dictamen de vocabulario cerrado |
| CLI | `relations/benchmark/cli.py` (`python -m relations.benchmark.cli`) | Punto de entrada, salidas JSON/JSONL/MD |

**No existe un segundo arnés de relaciones divergente.** La búsqueda de definiciones
`def match_predictions|def run_benchmark|def build_report` en `data-engine/app/**` da:

- `relations/benchmark/{runner,report,matching}.py` — el arnés de **relaciones** (este).
- `cli/extractor_benchmark.py` (`run_benchmark`) — arnés **distinto y de otro sujeto**:
  mide la **extracción de entidades** del extractor (corpus `tests/fixtures/benchmark/`,
  docs/33-37), no puntúa predicados de relación ni comparte corpus ni criterio. No es
  un duplicado divergente del arnés de relaciones; queda registrado aquí para que la
  distinción sea explícita.

Los tests `tests/test_relation_benchmark_*` consumen exclusivamente el arnés de
`relations/benchmark/`.

### 1.2. Hash del corpus (registro)

Corpus: `data-engine/app/tests/data/relation_benchmark/` — sintético, 16 fuentes, 54
relaciones, 3 workspaces (`eldoria`, `umbral`, `nova-frontier`).

| Artefacto | sha256 |
|---|---|
| `manifest.json` | `a2cc506f953a405db507cfe53389d2923f2d8a7015b6f7164f5a90ec825d2631` |
| `ground_truth/relations.json` | `15973d1837deb29ea339bca6bb3980d62e07ef283b196bf38d0d1e2653d9cc5c` |

El hash de `ground_truth/relations.json` está además declarado **dentro** del propio
`manifest.json` (`ground_truth.sha256`) y coincide con el fichero en disco. El hash por
fuente (`corpus_hashes`) que emite el runner coincide 1:1 con `manifest.json.sources[].sha256`.

> **El fichero de ground truth NO se toca en el Bloque 0.** Su sha256 debe quedar
> IGUAL antes y después (verificado por test). La reconciliación es sobre la
> **ontología/vocabulario**, nunca sobre el GT.

### 1.3. Umbrales intactos

`report.py::THRESHOLDS` **NO se modifica** en el Bloque 0:

```
simple_relations_recall = 0.80   evidence = 0.80   offsets = 0.90
negation = 0.80   temporality = 0.60   rumors = 0.60   predicate_structural = 0.50
```

---

## 2. Reconciliación GT ↔ ontología (HÍBRIDA)

### 2.1. Diagnóstico

El GT del corpus usa **20 tipos** de predicado; **9** NO estaban en la ontología de
contrato `ALLOWED_RELATION_TYPES` (`schemas/rpg_schema.py`):

`ALIAS_OF, CAUSED, CREATED, FOUNDED, LEADS, LIVES_IN, MARRIED_TO, SIBLING_OF, SUCCEEDED`.

### 2.2. Decisión (aprobada por el principal)

**Añadir los 9 como predicados canónicos NUEVOS** a `ALLOWED_RELATION_TYPES`, incluido
**`LIVES_IN` como canónico propio y distinto** (NO se colapsa con `LOCATED_IN`). Además
se añade su etiqueta ES en `RELATION_LABELS_ES` para mantener el invariante existente
(todo tipo permitido tiene etiqueta: 113/113 antes → 122/122 después).

Justificación por predicado (todos son relaciones legítimas del dominio RPG/narrativo,
con matiz semántico propio que ningún canónico existente cubre sin pérdida):

| Nuevo canónico | n en GT | Justificación (matiz propio) |
|---|--:|---|
| `LIVES_IN` | 3 | Residencia/morada de un ser en un lugar. **Distinto** de `LOCATED_IN` (ubicación de objeto/entidad); ver §2.3. |
| `SIBLING_OF` | 1 | Parentesco horizontal (hermano/a); ni `PARENT_OF` ni `FAMILY_OF` lo expresan sin pérdida. |
| `MARRIED_TO` | 1 | Vínculo conyugal simétrico; `SPOUSE_OF` es su sinónimo (ver hueco §2.4). |
| `FOUNDED` | 2 | Acto de fundar una organización/lugar (agente→entidad creada). |
| `SUCCEEDED` | 2 | Sucesión de cargo/título (quién sucede a quién). |
| `CAUSED` | 2 | Causalidad evento→evento/estado. |
| `LEADS` | 1 | Liderazgo/mando presente sobre grupo/organización. |
| `CREATED` | 1 | Autoría/creación de objeto/obra (agente→artefacto). |
| `ALIAS_OF` | 2 | Identidad alternativa (un nombre es alias de una entidad). |

### 2.3. `LIVES_IN` → `LOCATED_IN`: alias NO aplicado (y por qué)

El principal sugirió evaluar `LIVES_IN → LOCATED_IN`. **NO se aplica** ningún alias que
colapse `LIVES_IN` en `LOCATED_IN`. Motivo (riesgo de amaño):

- El motor actual **ya emite `LOCATED_IN`** de forma abundante (22 de 52 predicciones
  del run base). Si `LIVES_IN` (del GT) se aliasa a `LOCATED_IN`, las relaciones cuyo GT
  es `LIVES_IN` pasarían a contar como **predicado-correcto** en cuanto el motor emitiese
  `LOCATED_IN` sobre ese par — **sin ninguna mejora real del motor**. Eso inflaría
  `predicate_correct` de forma artificial: **amaño**, no señal.
- Por eso `LIVES_IN` entra como **canónico distinto**. Si en el futuro se determina que
  algún par concreto es sinónimo verdadero e inequívoco, se propondrá para revisión en
  B1 (ontología v2), no se aplica aquí.

> **HALLAZGO para revisión (B1) — alias preexistente en otra capa.**
> `relations/vocabulary.py::PREDICATE_ALIASES` ya contiene, de etapas anteriores, el
> alias `LIVES_IN → LOCATED_IN`. Esa capa (`vocabulary.py`) es la que **usa el arnés**
> para puntuar `predicate_correct` (`matching.py` → `vocabulary.predicates_match`), NO
> `ALLOWED_RELATION_TYPES`. Es decir, el arnés **ya** trata `LIVES_IN` del GT como
> `LOCATED_IN`. El Bloque 0 **no toca `vocabulary.py`**: (a) está fuera del alcance
> declarado (la reconciliación pedida es sobre `ALLOWED_RELATION_TYPES`), y (b)
> modificarlo **movería métricas**, lo que el A/B honesto de B0 prohíbe. Se **deja
> constancia** de este alias preexistente como candidato a revisión en B1: si se
> considera inflación indebida, deberá revertirse allí, midiendo el impacto A/B de forma
> aislada. El Bloque 0 lo documenta, no lo hereda en silencio ni lo amplía.

### 2.4. Dominio/rango/inversa/simetría — hueco documentado para B1

`ALLOWED_RELATION_TYPES` es un **conjunto plano** (frozenset): el esquema de contrato
**no soporta** dominio/rango/inversa/simetría por tipo. Esas propiedades viven hoy en
`relations/vocabulary.py` (`TYPE_COMPATIBILITY`, `SYMMETRIC_PREDICATES`,
`INVERSE_PREDICATES`), **derivadas de las plantillas de prompt** (`prompts.TEMPLATES`),
que son una capa distinta y fuera del alcance de B0.

Por tanto, para los nuevos canónicos B0 se añade lo único que el esquema de contrato
soporta hoy: la **etiqueta ES** (`RELATION_LABELS_ES`). Queda **documentado como hueco
de B1 (ontología v2)**:

- Simetría candidata: `MARRIED_TO` (y su sinónimo `SPOUSE_OF`) y `SIBLING_OF` son
  simétricos por naturaleza.
- Inversa candidata: `SUCCEEDED` ↔ un futuro `SUCCEEDED_BY`; `CAUSED` ↔ `CAUSED_BY`.
- Dominio/rango candidatos: `FOUNDED`/`CREATED`/`LEADS` (agente→entidad),
  `LIVES_IN`/`LOCATED_IN` (entidad→lugar), `ALIAS_OF` (entidad→entidad).

Esto se implementará en B1 sobre la capa de vocabulario/ontología v2, no en el frozenset
de contrato.

---

## 3. Matriz antes/después (cobertura ontológica)

`en_ontología` = presente en `ALLOWED_RELATION_TYPES` (`schemas/rpg_schema.py`).
`emitible_por_motor_actual` = el selector puede nombrarlo; sigue siendo el mismo conjunto
de **5** de siempre `{LOCATED_IN, MEMBER_OF, OWNS, PARTICIPATED_IN, RELATED_TO}` —
**B0 no lo cambia**.

| Predicado GT | n | En ontología (antes) | En ontología (después) | Emitible por motor actual |
|---|--:|:--:|:--:|:--:|
| MEMBER_OF | 10 | sí | sí | **sí** |
| PARTICIPATED_IN | 6 | sí | sí | **sí** |
| OWNS | 5 | sí | sí | **sí** |
| LOCATED_IN | 4 | sí | sí | **sí** |
| ALLIED_WITH | 3 | sí | sí | no |
| LIVES_IN | 3 | **NO** | **sí (nuevo)** | no |
| PARENT_OF | 3 | sí | sí | no |
| ALIAS_OF | 2 | **NO** | **sí (nuevo)** | no |
| CAUSED | 2 | **NO** | **sí (nuevo)** | no |
| ENEMY_OF | 2 | sí | sí | no |
| FOUNDED | 2 | **NO** | **sí (nuevo)** | no |
| GUARDS | 2 | sí | sí | no |
| MENTOR_OF | 2 | sí | sí | no |
| SUCCEEDED | 2 | **NO** | **sí (nuevo)** | no |
| CREATED | 1 | **NO** | **sí (nuevo)** | no |
| KNOWS | 1 | sí | sí | no |
| LEADS | 1 | **NO** | **sí (nuevo)** | no |
| MARRIED_TO | 1 | **NO** | **sí (nuevo)** | no |
| SIBLING_OF | 1 | **NO** | **sí (nuevo)** | no |
| TRUSTS | 1 | sí | sí | no |
| **Cobertura de TIPOS** | **20** | **11/20** | **20/20** | 5 emitibles (sin cambio) |

Nota: la columna "emitible por motor actual" NO mejora en B0 (es el objetivo de bloques
posteriores). Ampliar la ontología de contrato **no** cambia qué emite el motor ni cómo
puntúa el arnés (§4).

---

## 4. A/B honesto — el benchmark base NO se mueve

Hipótesis: añadir tipos a `ALLOWED_RELATION_TYPES` (`rpg_schema.py`) **no puede** cambiar
ninguna métrica del benchmark, porque:

- El motor sigue emitiendo los mismos 5 predicados (no se toca `_choose_predicate`).
- El arnés puntúa `predicate_correct` con `relations/vocabulary.py`
  (`predicates_match`), **no** con `ALLOWED_RELATION_TYPES`. `ALLOWED_RELATION_TYPES` es
  la ontología de **contrato de ingesta** (validador Pydantic `RelationshipBase`), una
  capa distinta de la de puntuación.

Si alguna métrica se moviese, sería señal de efecto colateral/amaño y habría que
investigarlo. **No se mueve** (evidencia abajo).

### 4.1. Comando

```
cd data-engine/app
python3 -m relations.benchmark.cli --mode baseline1 \
    --out-json /tmp/b0_base.json --out-jsonl /tmp/b0_base_preds.jsonl   # ANTES
python3 -m relations.benchmark.cli --mode baseline1 \
    --out-json /tmp/b0_post.json --out-jsonl /tmp/b0_post_preds.jsonl    # DESPUÉS
```

Se compara un **fingerprint** de métricas (verdict, global, strict_predicate,
structural_quality, per_predicate, gates, result_hashes, corpus_hashes, gt_sha),
excluyendo únicamente `code_sha`/`versions` (cambian por el propio commit, no son
métricas del pipeline).

### 4.2. Resultado base (ANTES)

```
mode=baseline1 verdict='APTO CON REVISION HUMANA TOTAL'
global P=0.8269 R=0.7963 F1=0.8113 TP=43 FP=9 FN=11
deterministic=True
predicate_structural gate = FAIL (value 0.2558, threshold 0.50)
predicted distribution = {LOCATED_IN: 22, MEMBER_OF: 9, OWNS: 4, PARTICIPATED_IN: 1, RELATED_TO: 16}
verdict_scope=COMPLETO
fingerprint sha256 = 9b0917a3328bcb2fd4ea0de78b83a51a6ae4963a80837dbda71765a9c1ddbf40
```

### 4.3. Resultado post-B0 (DESPUÉS) — PENDIENTE en commit 2

<!-- COMMIT-2: rellenar con la salida real post-cambio; el fingerprint sha256 debe ser IDÉNTICO al base. -->

---

## 5. Tests

`data-engine/app/tests/test_relation_v2_b0_reconciliation.py` (reales, sin skip/xfail):

- Cada predicado añadido está en `ALLOWED_RELATION_TYPES`.
- Todos los predicados del GT son válidos contra la ontología tras B0 (20/20).
- El sha256 del fichero GT NO cambió (igual al registrado en §1.2).
- El benchmark (corpus + runner) carga.
- `report.py::THRESHOLDS` sin cambios (valores exactos verificados).

---

## 6. Entrega

- **Commit 1 (arnés/doc):** este documento (arnés único, hashes de corpus, THRESHOLDS
  intactos, base A/B, matriz antes/después, hallazgo del alias de `vocabulary.py`).
- **Commit 2 (reconciliación):** `schemas/rpg_schema.py` (+9 canónicos, +9 etiquetas),
  test `test_relation_v2_b0_reconciliation.py`, y el A/B post-cambio (§4.3) demostrando
  igualdad de métricas.
</content>
</invoke>
