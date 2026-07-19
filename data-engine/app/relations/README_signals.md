# Senales heuristicas explicables para relaciones (`relation-signals/v1`)

Modulo: `relations/signals.py`. Tests: `tests/test_relation_signals.py`.

## Que es (y que NO es)

Este modulo produce **SENALES, no DECISIONES**. Cada senal es una funcion
**pura y determinista** que, dada una evidencia, aporta una pista **explicable**
sobre un posible par de entidades. Ninguna senal decide la relacion ni el
consenso: la agregacion/decision (ensemble, consenso) es responsabilidad de
**otro subsistema (R7)**.

Restricciones cumplidas:

- SIN LLM, SIN NVIDIA, SIN red, SIN Neo4j, SIN escritura.
- SIN efectos secundarios (la clase `Signal` es `frozen`).
- Solo lee `relations.contracts` (para `ALLOWED_ENTITY_TYPES`); **no lo modifica**.

## Forma de una senal

Cada `Signal` expone exactamente cinco campos (explicabilidad garantizada):

| campo         | descripcion                                             |
|---------------|---------------------------------------------------------|
| `name`        | identificador estable de la senal                       |
| `value`       | valor **numerico o categorico** (JSON-serializable)     |
| `evidence`    | span / **cita literal** tomada del segmento             |
| `explanation` | texto breve legible por humanos                         |
| `version`     | `relation-signals-1.0.0`                                |

## Entrada: `SignalContext`

- `segment`: texto completo del segmento.
- `subject_start/end`, `object_start/end`: offsets de caracter `[start, end)`.
- `subject_type`, `object_type` (opcionales): tipos de `ALLOWED_ENTITY_TYPES`.
- `occurrences` (opcional): citas literales de cada co-ocurrencia documental de
  la misma pareja (para la senal de repeticion).

Los offsets se validan de forma determinista (rango, orden). Nada de red.

## Senales disponibles

| senal              | value                                   | evidencia               |
|--------------------|-----------------------------------------|-------------------------|
| `distance`         | `{"chars": int, "tokens": int}`         | texto entre menciones   |
| `same_sentence`    | `bool`                                  | frase(s) que las contienen |
| `same_clause`      | `bool`                                  | frase del par           |
| `type_compatibility` | lista de categorias compatibles       | `Tipo -> Tipo`          |
| `svo_pattern`      | `bool`                                  | verbo-cue literal       |
| `membership`       | `bool`                                  | marcador literal        |
| `possession`       | `bool`                                  | marcador literal        |
| `location`         | `bool`                                  | marcador literal        |
| `negation`         | `bool`                                  | marcador literal        |
| `temporality`      | `{"markers": [...], "years": [...]}`    | marcadores/fechas       |
| `modality`         | `bool`                                  | marcador literal        |
| `rumor`            | `bool`                                  | marcador literal        |
| `repetition`       | `int` (nº ocurrencias)                  | citas literales         |

`compute_all_signals(ctx)` devuelve las 13 senales en orden estable.

### Casos clave cubiertos

- **Negacion**: `no`, `nunca`, `jamas`, `ni`, `sin` marcan que la afirmacion
  positiva **no debe darse por confirmada** (la decision final NO es de la senal).
- **Temporalidad**: `antes de`, `durante`, `tras`, `desde`... y anos (`\d{3,4}`)
  se **preservan** en `value` (`markers` + `years`).
- **Rumor**: `se dice que`, `segun rumores`, `supuestamente`... marcan estado
  epistemico **RUMORED** (la senal solo marca; no fija el `epistemic_status`).

## Ontologia minima de tipos

Documentada en `TYPE_ONTOLOGY` (en `signals.py`). Es una **senal**, no una regla
dura: si un par de tipos no encaja en ninguna categoria, la senal informa
`value=[]` sin descartar la relacion. Categorias y pares admitidos:

- `MEMBERSHIP`: `(Character, Faction)`, `(Faction, Faction)`
- `LOCATION`: `(Character, Location)`, `(Object, Location)`, `(Event, Location)`, `(Faction, Location)`
- `POSSESSION`: `(Character, Object)`, `(Faction, Object)`, `(Character, Concept)`
- `PARTICIPATION`: `(Character, Event)`, `(Faction, Event)`

Todos los tipos provienen de `ALLOWED_ENTITY_TYPES`
(`Character, Location, Faction, Object, Event, Concept`).

## Determinismo

Sin aleatoriedad, sin reloj, sin red. Llamadas repetidas devuelven resultados
identicos (verificado en los tests).
