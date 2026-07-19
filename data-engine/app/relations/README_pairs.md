# relations.pairs -- Generador determinista de pares candidatos (A-REL-2)

`relations.pairs` genera, para un segmento y sus entidades, el conjunto de
**pares candidatos** sujeto/objeto que alimentaran la extraccion de relaciones
posterior. Es un paso puramente estructural y offline.

## Que NO hace

- No llama a ningun LLM (Ollama / NVIDIA), no usa red, no toca Neo4j.
- No escribe nada ni autoaprueba: solo calcula candidatos en memoria.
- No modifica ni depende de mutar `relations.contracts`.
- No produce todavia un `RelationCandidate`: un par es la **entrada** de la
  extraccion, no su salida.

## API

```python
from relations.pairs import generate_pairs, PairConfig

result = generate_pairs(entities, segment, config=PairConfig())
```

### Entrada

`entities`: lista de dicts, cada uno con al menos:

| clave       | tipo        | obligatorio | descripcion                                  |
|-------------|-------------|-------------|----------------------------------------------|
| `id`        | str no vacio| si          | identificador de la entidad                  |
| `start`     | int >= 0    | si          | offset de inicio de la mencion en el segmento|
| `end`       | int >= start| si          | offset de fin de la mencion                  |
| `type`      | str o None  | no          | tipo ontologico (Character, Location, ...)   |
| `workspace` | str         | no          | por defecto el del segmento                  |

`segment`: dict con al menos:

| clave         | tipo        | obligatorio | descripcion                          |
|---------------|-------------|-------------|--------------------------------------|
| `id`          | str no vacio| si          | identificador del segmento           |
| `text`        | str         | si          | texto (para frase/parrafo/tokens)    |
| `workspace`   | str no vacio| si          | workspace de procedencia             |
| `source_id`   | str         | no          | id del documento; por defecto = `id` |
| `source_page` | int o None  | no          | pagina de origen (metadato)          |

### Configuracion (`PairConfig`)

| parametro              | por defecto | descripcion                                                        |
|------------------------|-------------|--------------------------------------------------------------------|
| `context_mode`         | `"sentence"`| razon contextual: `sentence` / `paragraph` / `segment` / `distance`|
| `window`               | `"char"`    | unidad de distancia: `char` o `token`                              |
| `max_distance`         | `None`      | distancia maxima entre menciones; filtro ADICIONAL al modo         |
| `max_pairs`            | `1000`      | cota anti-explosion de pares emitidos                              |
| `strict_max_pairs`     | `False`     | si True, superar `max_pairs` lanza en vez de truncar               |
| `reflexive_predicates` | `()`        | si no vacia, permite pares con `subject_id == object_id`           |
| `emit_both_directions` | `False`     | si True, emite A->B y B->A (relacion dirigida)                     |

`context_mode="distance"` exige `max_distance` no nulo.

### Salida (`PairGenerationResult`)

- `pairs`: tupla de `CandidatePair` en orden determinista y estable.
- `truncated`: True si se aplico `max_pairs`.
- `total_before_truncation`: nº de pares deduplicados antes de truncar.
- `warnings`: avisos (p.ej. truncamiento).
- `to_json()`: serializacion determinista (claves ordenadas), util para
  comparaciones byte a byte.

Cada `CandidatePair` incluye: `pair_id`, `subject_id`, `object_id`,
`subject_type`, `object_type`, offsets de ambas menciones, `distance`,
`distance_unit`, `context_mode`, `workspace`, `source_id`, `source_segment`,
`source_page`, `reflexive`.

## Garantias

- **Determinismo**: misma entrada -> misma salida, byte a byte del JSON. Las
  entidades se ordenan por `(start, end, id)`; los `pair_id` se derivan con
  SHA-256 de una clave canonica `(workspace, subject_id, object_id, segment_id)`
  y no dependen de `PYTHONHASHSEED`.
- **Exclusion de autorrelaciones**: se descartan pares con
  `subject_id == object_id` salvo que `reflexive_predicates` no este vacia.
- **Deduplicacion**: por defecto (relacion no dirigida) un par no ordenado
  `{A, B}` se emite una sola vez, canonicalizado por orden textual (sujeto = la
  mencion que aparece antes). Ante multiples menciones de la misma pareja se
  conserva la de **menor distancia** (desempate estable por posicion e id).
- **Anti-explosion**: `max_pairs` acota la salida. Al superarse se truncan de
  forma determinista los pares mas lejanos (se conservan los mas cercanos) y se
  marca `truncated=True` con un warning; con `strict_max_pairs=True` se lanza
  `PairGenerationError` en su lugar.
- **Procedencia**: cada par preserva `workspace`, `source_id` y
  `source_segment`. Menciones de workspaces distintos no se emparejan.

## Relacion con `RelationCandidate`

Los pares son la **entrada** al extractor. Ese subsistema (fuera de este
modulo) consumira cada `CandidatePair` y asignara `predicate`, `direction`,
`confidence` y la evidencia textual, construyendo entonces el
`RelationCandidate` completo (20 campos de `relations.contracts`). Los offsets
`subject_*` / `object_*` permiten recortar `evidence_text` /
`evidence_start` / `evidence_end`; `workspace`, `source_id` y `source_segment`
se propagan sin cambios.
