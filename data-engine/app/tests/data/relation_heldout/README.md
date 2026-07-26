# Corpus HELD-OUT de relaciones (H1)

Corpus **sintético, reservado y sellado** para estimar el rendimiento del motor de
relaciones **fuera del corpus de desarrollo**. Todo el contenido es **ficticio e
inventado**: universos imaginarios `ferrovia`, `mareas` y `orbita`. **No contiene
material con derechos de autor, ni datos personales, ni transcripciones de partidas
reales, ni secretos, ni rutas absolutas.**

> **NO ES UN SEGUNDO BENCHMARK.** Es un **segundo corpus** para el arnés único
> `app/relations/benchmark/`. Se ejecuta con el mismo runner, el mismo emparejamiento
> y las mismas métricas que el corpus B1, vía `--corpus-dir`.

> **NO MODIFICA NI SUSTITUYE** al corpus B1 (`app/tests/data/relation_benchmark/`),
> que queda intacto byte a byte.

Las reglas de uso son **obligatorias** y viven en
[`docs/relation-engine-v2e/HELDOUT_POLICY.md`](../../../../../docs/relation-engine-v2e/HELDOUT_POLICY.md).
Resumen: **este corpus no se mira para escribir reglas ni para ajustar expresiones**,
sólo se ejecuta en los checkpoints previstos, y **no se modifica después de verlo**.

## Contenido

| Fichero | Qué es |
|---|---|
| `sources/*.txt` | 30 fuentes UTF-8 (narrativa de rol, actas, fichas, charla de mesa) |
| `ground_truth/relations.json` | 45 relaciones anotadas, mismo contrato que B1 |
| `cases/cases.json` | Índice de **24 casos**: cobertura, fuentes, episodios y relaciones |
| `manifest.json` | Orden determinista, `sha256`/bytes/chars por fuente, hash del GT y de los casos |
| `schemas/` | JSON Schema del manifiesto y del ground truth |
| `SEAL.json` | **Sellado**: hashes congelados + registro de ejecuciones |
| `tools/build_heldout_corpus.py` | Generador determinista (regenera hashes idénticos) |

## Compatibilidad con el arnés

`ground_truth/relations.json` usa **exactamente** los mismos campos que el corpus B1
(`relation_id`, `source_id`, `workspace`, `segment_id`, `subject_*`, `predicate`,
`object_*`, `evidence_text`, `evidence_start`, `evidence_end`, `negated`,
`temporal_status`, `epistemic_status`, `direction`, `expected_decision`,
`annotator_notes`). Los metadatos propios del held-out (**caso** y **episodio**) viven
en `cases/cases.json` **fuera** del ground truth, precisamente para no alterar el
contrato que consume el arnés.

Se cumple `source_text[evidence_start:evidence_end] == evidence_text` en las 45
relaciones (verificado por `app/tests/test_relation_heldout_corpus.py`).

## Predicados centinela (leer antes de interpretar `predicate_correct`)

| Centinela | Filas | Significado |
|---|--:|---|
| `NO_RELATION` | 3 | El par de entidades **coexiste** en el texto pero **no hay relación**. Es ruido (charla de mesa, discusión de reglas). **Ningún predicado es correcto**: el acierto es imposible por construcción y la decisión esperada es `REJECT`. |
| `SPONSORS` | 1 | Predicado que **no existe en la ontología** del motor. Mide **cobertura**, no habilidad: también es inacertable por construcción. |

Estas 4 filas **bajan** `predicate_correct` a propósito. Los informes deben publicar
**siempre** la cifra completa y, junto a ella, la cifra excluyéndolas.

## Cobertura

24 casos (`cases/cases.json`) que cubren, como mínimo, un caso por punto:

predicados no vistos literalmente · voz activa · voz pasiva · sujeto y objeto
invertidos · relaciones simétricas · frases largas · varias relaciones por segmento ·
entidades repetidas · negación · rumores · hipótesis · transiciones temporales ·
fechas vagas · relaciones que cambian · fuentes contradictorias · conversación no
relacionada (ruido) · Unicode · puntuación · texto repetido · fragmentos ambiguos ·
alianza que termina y se vuelve enemistad · culpable aparente exonerado después ·
rumor que nunca se vuelve hecho · hipótesis de jugador · escena que ocupa varias
sesiones · salto de tres meses · flashback · relación confirmada por dos fuentes ·
relación contradicha · fuente retirada · mismo nombre en dos workspaces · predicado
desconocido · descubrimiento posterior de un evento antiguo.

## Disyunción con el corpus B1 (comprobada, no prometida)

El test de integridad comprueba que **la intersección de identificadores de entidad,
de textos de mención y de tokens de más de 3 caracteres entre ambos corpus es vacía**.
Ninguna entidad de B1 (`Ysolde`, `Draven`, `Kaelin`, `Orden del Alba`, …) reaparece
aquí, y ningún workspace se comparte.

## Ejecución

```bash
cd data-engine/app
# integridad del corpus
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/test_relation_heldout_corpus.py -q

# medición con el arnés ÚNICO (proveedores desactivados por defecto)
PYTHONDONTWRITEBYTECODE=1 python3 -m relations.benchmark.cli \
    --mode baseline1 --predicate-selector v2 \
    --corpus-dir tests/data/relation_heldout \
    --out-json /tmp/heldout_baseline1_v2.json
```

Ejecutarlo **requiere un checkpoint autorizado**: ver la política.
