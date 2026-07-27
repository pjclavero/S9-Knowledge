# Corpus held-out H2 — material REAL

**Rol:** segundo corpus reservado del programa "Motor V2 temporal, episódico y trazable".
**Versión:** 1.0.0 · **Formato:** IDÉNTICO al de B1 y H1 · **Arnés:** el único,
`data-engine/app/relations/benchmark/`, vía `--corpus-dir`.

> **No es un segundo benchmark.** Es un tercer *corpus* para el mismo arnés. B1 (dev),
> H1 (held-out sintético) y H2 (held-out real) no se modifican entre sí.

---

## 1. Qué contiene y de dónde sale

| Obra | Páginas | Sistema | Papel |
|---|--:|---|---|
| Trudvang — libro del director | 132 | Trudvang Chronicles | libro core |
| Trudvang — libro del jugador | 254 | Trudvang Chronicles | libro core |
| Vampiro: la Mascarada, ed. 20º aniversario | 495 | Mundo de Tinieblas | libro core |
| «La Leyenda de los Cinco Anillos — El Castillo Esmeralda (8/14)» | 2 h 01 min 12 s | L5A (FFG) | sesión de juego transcrita |

**881 páginas de manual de dos sistemas distintos + una sesión de juego de dos horas.**
Los tres PDF tienen capa de texto real (verificado con `pypdf`); la transcripción es de
`faster-whisper` modelo `small`, español, con marcas `[HH:MM:SS]` y **sin puntuación ni
mayúsculas**.

### Política legal y de privacidad — INNEGOCIABLE

Los manuales son **obra con derechos de autor** y la sesión es una **grabación con voces de
personas reales**. **Ni los PDF, ni el audio, ni la transcripción completa, ni texto extenso de
los manuales están en este repositorio, y no pueden estarlo.**

Lo único que se versiona son **36 citas cortas** (máx. **400 caracteres** cada una,
**11 076 caracteres en total**), imprescindibles porque **son** la evidencia sobre la que se
anota y se mide. Eso es el **0,3 %** del texto extraído de los tres libros (3 379 513
caracteres) y una fracción equivalente de la transcripción. Cada fuente lleva en
`manifest.json` su `provenance` (obra, página, frase inicial, tamaño de ventana), de forma que
quien tenga el material original puede reconstruir el muestreo completo; quien no lo tenga, no
obtiene la obra a partir de este repositorio.

`tools/build_h2_corpus.py` **no** lee los PDF: consume el *pool* de fragmentos ya muestreado.
El pipeline completo (extracción → *pool* → selección) se describe en §2 y vive fuera del repo.

---

## 2. Método de muestreo (reproducible)

**Semilla fija: `SEED = 20260727`.** Los cuatro pasos son deterministas.

1. **Extracción.** `pypdf` página a página. Se une el guionado de fin de línea
   (`narra-\ncion` → `narracion`), se colapsa el espacio en blanco y se conserva **todo lo
   demás tal cual**, incluidos los artefactos de kerning del PDF (`arraiga - dos`, `o dian`,
   `Po der`). **No se corrige el texto:** medir sobre texto limpiado a mano sería medir otra
   cosa.
2. **Ventanas candidatas.** Por página, se parte en frases y se generan ventanas de 1, 2 y 3
   frases consecutivas con 130–400 caracteres. Total: 41 082 ventanas.
3. **Filtro de contenido relacional** (mecánico, aplicado antes de mirar nada). Se descarta la
   ventana si: no termina en frase completa; tiene < 22 palabras; densidad de dígitos > 2 %;
   < 90 % de caracteres alfabéticos o espacios; contiene léxico de tablas y mecánicas
   (`NH`, `d10`, `Nivel N`, `+N`, `Tabla`, `Tirada`, `pág.`, `✦`, `•`, `|`); contiene
   paréntesis; o tiene menos de **2 nombres propios** distintos. El filtro selecciona por
   **densidad de entidades y ausencia de reglas**, nunca por el léxico de los predicados del
   motor: filtrar por verbos que el motor conoce habría inflado el resultado.
   Superan el filtro y quedan sin solapar: 3 590 ventanas de libro.
4. **Barajado y recorrido.** El *pool* se ordena canónicamente por (obra, página, frase) y se
   baraja con `random.Random(20260727)`. Se recorre **en ese orden**, estratificado por obra
   (V20 tiene 495 páginas y sin estratificar coparía el 90 % de la muestra), y se anota el
   primer fragmento que contenga al menos una relación anotable.

**Transcripción:** las 1 813 líneas con marca de tiempo se agrupan en bloques consecutivos de
≈260–400 caracteres (296 ventanas), se barajan con la **misma semilla** y se recorren igual.

**Recorrido efectivo declarado, sin adornos:**

| Fuente | Inspeccionadas en orden barajado | Con ≥1 relación anotable | Densidad |
|---|--:|--:|--:|
| Trudvang (dos libros) | 72 | 13 | 18 % |
| Vampiro V20 | 52 | 12 | 23 % |
| Transcripción | 22 | 8 | 36 % |

Más los **3 centinelas de ruido** (`src-34`, `src-35`, `src-36`), tomados del mismo recorrido:
fragmentos donde dos entidades **coocurren sin ninguna relación**. Sirven para detectar falsos
ACCEPT y no se eligen por conveniencia.

---

## 3. Tamaño y cobertura

- **36 fuentes**, **52 relaciones**, **3 workspaces**: `trudvang` (14 fuentes / 24 rel.),
  `vampiro` (13 / 17), `leyenda` (transcripción, 9 / 11).
- **14 predicados distintos** en el ground truth, incluido el centinela `NO_RELATION`:
  `MEMBER_OF` 15 · `LOCATED_IN` 4 · `ENEMY_OF` 4 · `OWNS` 4 · `PARTICIPATED_IN` 3 ·
  `LIVES_IN` 3 · `PARENT_OF` 3 · `LEADS` 3 · `ALLIED_WITH` 3 · `NO_RELATION` 3 ·
  `CREATED` 2 · `ALIAS_OF` 2 · `MENTOR_OF` 2 · `CAUSED` 1.
- Decisión esperada: `ACCEPT` 32 · `REVIEW` 17 · `REJECT` 3. Temporalidad: `ONGOING` 17 ·
  `PAST` 11 · `ATEMPORAL` 11 · `PRESENT` 10 · `ENDED` 2 · `FUTURE` 1. Epistémico:
  `ASSERTED` 49 · `RUMORED` 2 · `INTENDED` 1. Dirección: `SUBJECT_TO_OBJECT` 37 ·
  `UNDIRECTED` 12 · `OBJECT_TO_SUBJECT` 3. Negadas: 1.
- Cobertura lingüística por caso en `cases/cases.json`: voz pasiva y complemento agente, sujeto
  elidido, nominalización, aposición a distancia, epítetos, enumeraciones de 6 y 7 miembros
  (explosión de pares), pronombre clítico, correferencia pospuesta, alias explícito, rumor
  (`se dice que`), negación por cuantificador (`ningún`), intención futura, deixis sin
  referente, pertenencia terminada, y —sólo en la transcripción— habla sin puntuación,
  tartamudeo, autocorrección, frases cortadas y **errores de ASR en nombres propios**
  (`gruya` por Grulla, `daiqui` por Daiki).

---

## 4. Calidad del ground truth — DECLARACIÓN

**La anotación es de UN SOLO PASE.** Un anotador, una pasada, sin segundo anotador y **sin
medida de acuerdo entre anotadores**. Es la misma limitación que H1 declaró, y en H2 pesa más:
el texto real es más ambiguo que el sintético.

Dónde se concentra la incertidumbre, dicho de frente:

- Los **17 casos marcados `REVIEW`** lo están porque el propio anotador no está seguro. Los
  motivos están, uno por uno, en `annotator_notes`.
- La ontología de 20 predicados **no cubre bien el material real**: «entregarse a una fe»
  (`src-09`), «Abrazar» en el sentido de V20 (`src-14`) o «maestro de bestias» (`src-05`) se
  anotan con el predicado más cercano, no con el correcto, porque el correcto no existe.
  Ese desajuste es un hallazgo, no un defecto de la anotación.
- Los `temporal_status` de manual (`ATEMPORAL` vs `ONGOING` para descripciones de lore) son la
  decisión más discutible del corpus y afectan a 27 relaciones.

**Nada de esto se ha ajustado después de ver los resultados del motor.** El corpus se selló
antes de la primera ejecución (`SEAL.json`).

---

## 5. Reproducción

```bash
cd data-engine/app
for mode in baseline1 ensemble_offline; do
  for sel in v1 v2; do
    python3 -m relations.benchmark.cli --mode "$mode" --predicate-selector "$sel" \
      --corpus-dir tests/data/relation_heldout_h2 --out-json "/tmp/h2_${mode}_${sel}.json"
  done
done
```

Integridad y sellado: `python3 -m pytest tests/test_relation_heldout_h2_corpus.py -q`.

Resultados publicados en `docs/relation-engine-v2e/HELDOUT_REAL_H2.md`.
