# Cadena completa (II): extractor `llm` / `hybrid` y resolución de entidades

**Fecha:** 2026-07-27 · **Rama:** `work/rel-v2e-b02-heldout` · **Base:** `ddc81a9`
**Documento hermano de** [`CADENA_COMPLETA_EXTRACTOR_MOTOR.md`](CADENA_COMPLETA_EXTRACTOR_MOTOR.md),
que midió la cadena **sólo con el extractor heurístico** y con el **enlazado de entidades
regalado**. Aquí se cierran esas dos lagunas: eran los puntos 1 y 2 de su §4.

**Motor:** `relation-pipeline-1.0.0`, proveedores **OFF** (`runner.MODES`) — el motor nunca abre red.
**Extractores:** `review.extractor` (heurístico), `review.llm_extractor` (**Ollama REAL**) y
`review.hybrid_filter.merge_hybrid` (híbrido) — **ninguno modificado**.
**Proveedor autorizado y usado:** Ollama `qwen2.5:7b` en `http://192.168.1.157:11434`,
`temperature=0`, `seed=42`, **en sombra**: nada de lo devuelto se escribe en Neo4j, ni se ingiere,
ni se despliega. **NVIDIA: nunca. Neo4j: nunca. VM105/vm100: nunca.**
**Drivers:** `data-engine/app/tools/chain_benchmark.py` (ampliado) y
`data-engine/app/tools/resolution_audit.py` (nuevo).
**Corpus:** B1 (16 fuentes / 54 rel.), H1 (30 / 45), H2 (36 / 52) — **sin tocar**, con
verificación sha256 en cada carga; y `tests/fixtures/benchmark/` para el arnés del extractor.

> Dos preguntas:
> **(1)** `hybrid` mide F1 de entidades **0.806** frente a **0.689** del heurístico. Como la
> alcanzabilidad exige extraer **las dos** entidades de cada relación, el efecto es multiplicativo:
> ¿salva eso la cadena?
> **(2)** Todas las cifras anteriores dieron por hecho que el sistema sabe que "Kael" y
> "el Guardián" son la misma entidad. ¿Qué hace de verdad la resolución, y cuánto cuesta?

---

## PARTE B — La resolución de entidades

### B.1 Auditoría: qué hace hoy el repositorio

Se buscó el módulo responsable y se leyó entero. Conclusiones, todas verificables en el código:

| Componente | Qué hace realmente | Consecuencia |
|---|---|---|
| `review/resolver.py` | Resuelve cada candidato **contra Neo4j** (grafo ya existente): `canonical_name` exacto, `alias` exacto, `toLower(canonical_name)`, y una comprobación de "variante EN/ES" por token compartido | **No es correferencia.** Su propio docstring lo dice: *"NO fusiona duplicados"*. La variante EN/ES sólo sirve para marcar `needs_review` |
| `review/resolver.py` sin Neo4j | `driver is None` → **todo** a `needs_review` | En este entorno (y en cualquier medición offline) la resolución **no resuelve nada** |
| `review/pipeline.py` | `segment → classify → extract → validate → resolve → decide → writer` | **No existe ningún paso de correferencia intra-documento.** Un pronombre ("ella") o una descripción definida ("el Guardián") **nunca** se enlaza con su antecedente |
| `review/workspace_aliases.py` | Tabla **manual** `config/aliases/<ws>.json`, sólo `reviewed=true`, coincidencia **exacta de cadena** | Cubre lo que un humano haya escrito a mano, nada más |
| `review/hybrid_filter.py::_ekey` | Dedupe por `name.lower()|type` | Agrupación por cadena, dentro de una misma extracción |
| `review/resolver.py::_normalize` | Minúsculas sin tildes | Repara acentos y mayúsculas |
| `glossary/glossary_matcher.py` | Búsqueda en cascada exacta → alias → `error_form` → **fuzzy (difflib, umbral 0.72)** | Es lo único que podría reparar variantes fonéticas de ASR… pero se alimenta de `state/glossary.db`, que está en `.gitignore` y **no existe aquí** (la misma ausencia que ya explicó una divergencia de medición en `docs/34`) |

**La cadena de canonicalización realmente efectiva es, por tanto:
`alias manual (exacto)` → `minúsculas sin tildes`. Nada más.**

**Hallazgo adicional (defecto real, no medición):** las consultas de `_search_neo4j` **no filtran
por `workspace`**:

```cypher
MATCH (n) WHERE n.canonical_name = $name RETURN ...
```

Dos entidades homónimas de campañas distintas colisionan. No es teórico: se observa en el corpus
H1 (§B.2). **No se ha tocado nada**; queda anotado.

### B.2 Medición de la resolución (`tools/resolution_audit.py`)

**¿Hay anotación de correferencia?** Sí, implícita y utilizable en ambos corpus, y conviene decir
exactamente de qué tipo:

- **Corpus de relaciones (B1/H1/H2):** cada mención del ground truth lleva su `subject_id` /
  `object_id`. Dos menciones con texto distinto y el mismo id **son** una anotación de
  correferencia. Lo que **no** hay es una anotación de correferencia *independiente* revisada por
  un segundo anotador: se hereda el pase de anotación del corpus (H2 es de **un solo pase**, según
  su propio `ground_truth/relations.json`).
- **Corpus del extractor (`tests/fixtures/benchmark/`):** anotación de **doble pase**
  (`annotation_pass` 2 o 3, `reviewed: true`) con listas explícitas de `aliases` por entidad.

Se mide con **B-cubed** (Bagga & Baldwin), el estándar de correferencia, comparando dos
particiones de las mismas menciones: la verdadera (por `id` del GT) y la del sistema real (por
`surface_key` = alias manual + `_normalize`). **Precisión baja = el sistema funde; recall bajo = el
sistema parte.**

| Corpus | menciones GT | ids reales | grupos del sistema | **B³ P** | **B³ R** | **B³ F1** | fusiones | divisiones |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| B1 | 93 | 46 | 55 | **1.0000** | **0.8695** | **0.9302** | 0 | 8 |
| H1 | 83 | 38 | 37 | **0.9880** | **1.0000** | **0.9939** | 1 | 0 |
| H2 (real) | 92 | 82 | 86 | **1.0000** | **0.9529** | **0.9759** | 0 | 4 |

Sin normalizar (comparando la cadena literal) H2 baja de 0.9759 a **0.9721**: **el plegado de
tildes y mayúsculas aporta 0.004**. Es todo lo que aporta hoy la "resolución".

**El catálogo completo de errores** (son pocos y se pueden leer uno a uno — ésa es la ventaja de
medir en corpus pequeños):

*Divisiones* (el sistema crearía **dos nodos** para una sola entidad):

| Corpus | id del GT | cadenas que el sistema no une |
|---|---|---|
| B1 | `ysolde` | "la reina de invierno" · "reina ysolde" · "ysolde" |
| B1 | `draven` | "draven" · "el cuervo" |
| B1 | `sela` | "le" · "sela" |
| B1 | `kaelin` | "ella" · "kaelin" |
| B1 | `vayra` | "hechicera vayra" · "vayra" |
| B1 | `reino-valmyr` | "reino de valmyr" · "trono de valmyr" |
| B1 | `conclave-estrellas` | "conclave" · "conclave de las estrellas" |
| B1 | `akio` | "akio" · "samurai ronin akio" |
| H2 | `yggdrasil` | "el antiguo arbol yggdrasil" · "yggdrasil" |
| H2 | `misa-firidge` | "la misa" · "una misa" |
| H2 | `clan-leon` | "clan leon" · "leon" |
| H2 | `daiki` | "daiki" · "daiqui" |

*Fusiones* (el sistema colapsaría **dos entidades distintas** en un nodo):

| Corpus | cadena | ids del GT que colapsa |
|---|---|---|
| H1 | `halvard` | `halvard-ferrovia` · `halvard-mareas` |

Esa única fusión es exactamente el defecto de §B.1: **dos personajes homónimos de dos workspaces
distintos**, y la consulta de Neo4j no filtra por workspace. Con un grafo compartido, esta clase de
error es sistemática, no anecdótica.

Los tipos de error que aparecen son cuatro, y **tres de ellos son irresolubles con cadenas**:
pronombres (`ella`, `le`), descripciones definidas (`el cuervo`, `la reina de invierno`), títulos
antepuestos (`hechicera vayra`, `samurai ronin akio`) y variantes fonéticas de ASR
(`daiki`/`daiqui`). Sólo la última tendría arreglo barato — con el glosario fuzzy, que **no está
poblado**.

### B.3 Cobertura de los alias del corpus del extractor (doble pase)

El corpus del extractor anota `aliases` explícitos. El comparador oficial
(`cli/benchmark_comparator.py::is_match`) **acepta cualquier alias como acierto**: también él usa
el ground truth como oráculo de enlazado. Aquí se comprueba, alias por alias, si la cadena de
canonicalización **real** lo resolvería:

| Resuelto por | nº | % |
|---|--:|--:|
| Tabla manual de alias (`config/aliases/leyenda.json`) | 6 | 27,3 % |
| Normalización (tildes/mayúsculas) | 2 | 9,1 % |
| **No resuelto por nada del sistema actual** | **14** | **63,6 %** |
| **Total de alias anotados** | **22** | |

Los 14 no resueltos son: `Toturi`→`Akodo Toturi`, `Kachiko`→`Bayushi Kachiko`, `Reika`(×2)→`Bayushi
Reika`, `el guardia del puente`→`Shinjo Haru`, `el oni`→`Oni de la Montaña Negra`, `segundo
fragmento` y `fragmentos del ritual…`→`Portador del Lamento`, y **seis variantes fonéticas de ASR**
(`Kakita Asuca`, `Asuca`, `Bayusi`, `Isaba`, `Sinjo Haru`, `Bayushi Reica`).

**Es decir: el 29 % de las entidades esperadas del corpus del extractor (21 de 72) sólo aparecen
bajo un alias, y el sistema real sabe resolver poco más de un tercio de esos alias.** Todas las
métricas de `docs/34` y `docs/36` los dan por resueltos.

### B.4 Impacto sobre la cadena: cuánto cuesta quitar el oráculo

En vez de estimarlo, se mide: `chain_benchmark.py` gana una tercera dimensión, `--resolution`, con
tres políticas que **acotan** el resultado real (`oracle` ≥ `surface` ≥ `surface_bijective`):

| Política | Regla | Qué mide |
|---|---|---|
| `oracle` | id del GT por span (lo publicado hasta hoy) | cota **optimista** (enlazado regalado) |
| `surface` | menciones agrupadas por `surface_key` **real**; cada grupo toma el id de GT mayoritario | penaliza **íntegramente las fusiones**; **repara las divisiones** (el bautizo por mayoría las arregla) |
| `surface_bijective` | igual, pero un grupo sólo recibe id del GT si la correspondencia es **biyectiva** (ni fusión ni división); si no, id sintético que jamás empareja | cota **pesimista**: penaliza fusiones **y** divisiones |

Resultado con el extractor **heurístico**, `baseline1`, selector v2:

| Corpus | Condición | Resolución | Alcanzabilidad | `pair_F1` | `predicate_correct` | `strict_predicate.f1` |
|---|---|---|--:|--:|--:|--:|
| B1 | laxa | `oracle` | 0.9259 | 0.5429 | 0.3158 | 0.1714 |
| B1 | laxa | `surface` | **0.9074** | 0.5481 | 0.3243 | 0.1778 |
| B1 | laxa | `surface_bijective` | **0.2407** | 0.0702 | 0.5000 | 0.0351 |
| B1 | estricta | `oracle` | 0.2778 | 0.0611 | 0.5714 | 0.0349 |
| B1 | estricta | `surface` | 0.2778 | 0.0614 | 0.5714 | 0.0351 |
| B1 | estricta | `surface_bijective` | 0.2778 | 0.0614 | 0.5714 | 0.0351 |
| H1 | laxa | `oracle` | 0.8667 | 0.5231 | 0.1176 | 0.0615 |
| H1 | laxa | `surface` | 0.8667 | **0.6071** | 0.1176 | 0.0714 |
| H1 | laxa | `surface_bijective` | **0.6222** | 0.3288 | 0.1667 | 0.0548 |
| H2 | laxa | `oracle` | 0.4423 | 0.1610 | 0.0526 | 0.0085 |
| H2 | laxa | `surface` | 0.4423 | 0.1645 | 0.0526 | 0.0087 |
| H2 | laxa | `surface_bijective` | **0.3846** | 0.1333 | 0.0625 | 0.0083 |
| H2 | estricta | las tres | 0.1154 | 0.0333 | 0.0000 | 0.0000 |

**Lectura, con su incertidumbre declarada:**

1. **Quitar el oráculo y poner la agrupación real (`surface`) casi no cambia nada**: la
   alcanzabilidad de H2 no se mueve (0.4423), la de B1 baja 1,9 puntos y `pair_F1` incluso **sube**
   un poco (en H1, de 0.5231 a 0.6071) porque fundir menciones reduce pares espurios. **Motivo: hay
   una sola fusión en los tres corpus.** El oráculo de enlazado no estaba inflando el resultado por
   la vía de las fusiones.
2. **La cota pesimista sí muerde, y es donde vive la incertidumbre.** Si el sistema no puede
   desambiguar nada que no sea biyectivo, la alcanzabilidad de B1 se hunde de 0.9259 a **0.2407**
   (−74 %), la de H1 de 0.8667 a **0.6222** y la de H2 de 0.4423 a **0.3846** (−13 %).
3. **El resultado real está entre las dos cotas y no se puede estrechar más con estos corpus.**
   La razón es honesta y concreta: el bautizo por mayoría de `surface` usa el GT, y sustituirlo por
   nada (`surface_bijective`) es más duro de lo que sería un sistema con glosario poblado. **La
   horquilla de la alcanzabilidad de H2 con entidades reales es [0.3846, 0.4423]**, y sobre esa
   horquilla `strict_predicate.f1` se mueve entre **0.0083 y 0.0087**: la resolución **no es hoy el
   cuello de botella** — el cuello de botella es la detección.
4. **Esta conclusión NO se puede extrapolar a producción.** Los tres corpus tienen 46, 38 y 82
   entidades. La probabilidad de colisión de nombres crece con el tamaño del grafo, y la consulta
   sin filtro de `workspace` la amplifica. Con un grafo de miles de nodos y varias campañas, las
   fusiones dejarían de ser una sola. **Lo medido acota el coste de la resolución en corpus
   pequeños; no dice nada de un grafo grande.**

---

## PARTE A — El extractor `llm` / `hybrid` en la cadena

<!-- RELLENAR -->

---

## Reproducción

```bash
# Auditoría y medición de la resolución (offline, sin red)
python data-engine/app/tools/resolution_audit.py --corpus B1 H1 H2 --out /tmp/resolution.json

# Cadena con el heurístico y las tres políticas de resolución (offline)
python data-engine/app/tools/chain_benchmark.py --corpus B1 H1 H2 --selector v1 v2 \
    --mode baseline1 --extractor heuristic --resolution oracle surface surface_bijective \
    --out /tmp/chain_heur.json

# Cadena con LLM/híbrido: primero se llena la caché (ÚNICA etapa con red), luego se evalúa
python data-engine/app/tools/chain_benchmark.py --corpus B1 H1 H2 --extractor hybrid --runs 3 \
    --prefill-only --workers 4 --llm-cache /tmp/llm_cache.json
python data-engine/app/tools/chain_benchmark.py --corpus B1 H1 H2 --selector v2 \
    --extractor llm hybrid --runs 3 --condition extractor_strict extractor_lax \
    --llm-cache /tmp/llm_cache.json --out /tmp/chain_llm.json
```
