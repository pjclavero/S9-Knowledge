# Corpus de benchmark de extracción de relaciones (v1)

Corpus **sintético, sanitizado y reproducible** para evaluar la extracción de
relaciones del pipeline interno (`relations/**`). Todo el contenido es **ficticio
e inventado** para este benchmark: universos de rol imaginarios
`eldoria`, `umbral` y `nova-frontier`. **No contiene corpus privado, documentos
históricos reales, secretos ni rutas absolutas.**

No sustituye ni modifica el benchmark de extracción de entidades previo
(docs/33-37): es un artefacto de datos independiente centrado en **relaciones**.

## Contenido

- **16 fuentes** pequeñas (`sources/*.txt`, UTF-8): narrativa RPG, fichas de
  personaje, cronologías, descripciones de facción/lugar, fragmentos de manual y
  eventos.
- **54 relaciones anotadas** con ground truth de doble pase
  (`ground_truth/relations.json`).
- `manifest.json`: versión, orden determinista, `sha256`/tamaño/encoding por
  fuente, y hash del ground truth.
- `schemas/`: JSON Schema del `manifest` y del `ground_truth`.
- `ground_truth/review-notes.md`: registro del doble pase (divergencias y
  resolución).

## Modelo de datos

El ground truth es compatible con el contrato interno
`relations/contracts.py::RelationCandidate`:

- **Predicados** normalizados con `normalize_predicate` (MAYÚSCULAS_CON_GUION_BAJO):
  `ALLIED_WITH`, `ENEMY_OF`, `MEMBER_OF`, `LEADS`, `OWNS`, `LOCATED_IN`,
  `LIVES_IN`, `PARENT_OF`, `SIBLING_OF`, `MARRIED_TO`, `MENTOR_OF`,
  `PARTICIPATED_IN`, `SUCCEEDED`, `CAUSED`, `FOUNDED`, `CREATED`, `GUARDS`,
  `KNOWS`, `TRUSTS`, `ALIAS_OF`.
- **Tipos de entidad** dentro de `ALLOWED_ENTITY_TYPES`
  (`Character`, `Location`, `Faction`, `Object`, `Event`, `Concept`).
- **`direction`** ∈ `Direction`
  (`SUBJECT_TO_OBJECT`, `OBJECT_TO_SUBJECT`, `UNDIRECTED`).
- **`epistemic_status`** ∈ `EpistemicStatus`
  (`ASSERTED`, `RUMORED`, `HYPOTHETICAL`, `INTENDED`).
- **`temporal_status`** (vocabulario del corpus, se mapea a `temporal_scope`):
  `PAST`, `PRESENT`, `FUTURE`, `ONGOING`, `ENDED`, `ATEMPORAL`.
- **`expected_decision`** (decisión humana esperada del benchmark):
  `ACCEPT`, `REJECT`, `REVIEW`.

### Campos de cada relación

`relation_id`, `source_id`, `workspace`, `segment_id`, `subject_id`,
`subject_text`, `subject_type`, `predicate`, `object_id`, `object_text`,
`object_type`, `evidence_text`, `evidence_start`, `evidence_end`, `negated`,
`temporal_status`, `epistemic_status`, `direction`, `expected_decision`,
`annotator_notes`.

Los offsets `evidence_start`/`evidence_end` son índices de **carácter** dentro
del texto de la fuente: se cumple `source_text[start:end] == evidence_text` de
forma exacta (verificado por el test de integridad, también sobre texto Unicode).

## Cobertura de casos difíciles

Distribuidos entre las fuentes: negación, rumor, hipótesis, posibilidad, hecho
pasado, hecho futuro, relación que termina, cambio de facción, alias, dos
entidades de nombres parecidos (`Kaelin` / `Kaelan`), pronombres, sujeto
omitido, voz pasiva, evidencia repartida en varias frases, contradicción entre
segmentos, relación N:N, relación simétrica, relación direccional, múltiples
workspaces sintéticos y texto Unicode visible (CJK `月光`, runa `ᛟ`).

## Reproducibilidad e integridad

`manifest.json` fija un orden determinista de las fuentes y su `sha256`. El test
`app/tests/test_relation_benchmark_corpus.py` recalcula los hashes, valida ambos
JSON contra sus schemas, comprueba los offsets, la unicidad de IDs, la
normalización de predicados, los tipos admitidos, la ausencia de Unicode oculto
(bidi / zero-width / BOM) y de secretos/rutas absolutas, y materializa cada
relación como un `RelationCandidate` válido del contrato.

## Ejecución

```bash
cd data-engine
python -m pytest app/tests/test_relation_benchmark_corpus.py -q
```
