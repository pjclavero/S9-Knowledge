# 42 — Cierre del programa "Puerta 4: cobertura del extractor" (B0→B5)

## 1. Veredicto final

**Veredicto de la puerta 4: PARCIAL.**

La re-medición íntegra del bloque B5 (`scripts/gate4/measure_b5.py`,
artefactos `artifacts/gate4-program/b5-final.{json,md}`) reproduce **exacto**,
cero discrepancias, contra el baseline congelado de B4
(`artifacts/gate4-program/b4-resultado.json`). Nada se movió porque B5 no
tocó `cues.py`/`deterministic.py`/`morphology.py` — es un bloque de medición,
no de reglas.

Contra los tres criterios que fijó el operador para esta puerta:

| criterio | umbral | observado | veredicto |
| --- | --- | --- | --- |
| Cobertura E2E de desarrollo | ≥ 0.60 | **0.607** (34/56) | CONFORME |
| Recall SIMPLE en desarrollo | ≥ 0.70 | **0.10** | **NO_CONFORME** |
| Generalización acompaña (familias no duras a 1.0, HARD documentada) | 1.0 | 1.0 (9/9 no duras), HARD_SCOPE_LITOTES 0.5 con causa estructural | CONFORME |

Los invariantes de precisión (`auto_approval_precision`,
`negative_edge_precision`, `negated_cessation_safety`, `evidence_grounding`
= 1.0; `false_positive_relation_from_negation` = 0) se mantienen intactos en
los seis bloques del programa: **nada se autoaprueba de más**. Ese invariante
bloqueante nunca ha fallado; por eso el veredicto es PARCIAL y no
NO_CONFORME.

## 2. La corrección de medición que hace este bloque

B2 y B4 publicaban `recall_simple = 1.0` como cifra de referencia del
programa. Esa cifra es real, pero mide el **clasificador de negación**
(`extraction.cues.analyze_raw_text`) sobre el corpus de **generalización**
(family `SIMPLE`, 8 casos con entidades nuevas nunca vistas): responde a
"¿el clasificador reconoce que esta frase está negada y de qué tipo?".

El criterio del operador dice "recall SIMPLE ≥ 0.70 **en desarrollo**". La
puerta que mide exactamente eso ya existía, congelada, en el runner E2E
(`artifacts/v3-final-validation/gate4_negation_measure.py::gates()`, la
titulada *"recall de autoaprobación SIMPLE ≥ 0.75"*, métrica
`auto_approval_recall[SIMPLE]`): no clasifica una frase suelta, mide si la
cadena completa — normalizador, extractor, reconciliador, motor, política de
auto-aprobación — llega a una decisión `AUTO_APPROVE` real sobre los casos
`SIMPLE` del corpus de desarrollo. Esa cifra es **0.10** desde B0, y **no se
ha movido en ningún bloque del programa**: B2 subió la cobertura general
(0.143 → 0.607, más casos con *alguna* decisión), pero eso no significa que
más casos SIMPLE terminen en auto-aprobación — la mayoría de los SIMPLE no
cubiertos son de origen OCR/ASR (ver §4), y de los cubiertos, la mayoría
termina en `REVIEW`, no en `ACCEPT`.

Confundir "el clasificador reconoce la negación" con "el motor auto-aprueba
la decisión" es la misma clase de error que ya costó una lección cara en el
motor de relaciones v2 (predicado 0.81 en el arnés de desarrollo, 0.24 sobre
datos reales): un número que solo se sostiene en la capa fácil, no en la
decisión completa. Este documento, y `measure_b5.py`, existen en parte para
no repetirla — declarándolo, no maquillándolo.

## 3. Qué se logró, bloque a bloque

| bloque | qué hizo | resultado medido |
| --- | --- | --- |
| B0 | Arnés de medición dev+generalización, corpus de generalización inicial (9 familias) | dev 0.143, generalización 1.0 en 9 familias |
| B1 | Carril OCR conectado (`ocr_render.py`, `TesseractVisualProvider`, `eval/ocr_lane.py`) | carril validado en VM105 con Tesseract real (11/11 episodios OCR reconocidos); localmente (sin Tesseract) el carril se degrada declarado, cero claims inventados |
| B2 | Reglas deterministas de cobertura + fusión coreferente en el reconciliador | dev 0.143 → **0.607**, generalización 1.0 (9 familias), HARD_SCOPE_LITOTES 0.5, precisión 1.0 donde decide |
| B3 | Carril semántico NVIDIA NIM en sombra (nunca escribe, nunca decide) | 0.357 de recall global — no alcanza el umbral del programa; coste real no determinable (sin precio por token verificado); estabilidad 0 reintentos/0 timeouts en una sola corrida de 60 episodios (insuficiente para decidir adopción) |
| B4 | Paradigma morfológico de conjugación regular -AR para verbos de reporte (`morphology.py`) | dev sin cambio (34/56): los 2 casos candidatos dependían de alcance de cuantificador, no de conjugación; generaliza a verbos nuevos en el corpus de generalización (`gen:scope:05`/`06`, 1.0) sin tocar literales |
| B5 | Re-medición íntegra + dictamen | reproduce exacto B4; veredicto **PARCIAL**: cobertura y generalización cumplen, recall SIMPLE en desarrollo (medido correctamente) no llega a 0.70 |

## 4. Qué quedó descartado, con causa

- **Ollama / carril local por LLM**: descartado en fases anteriores del
  programa V3 por capacidad de CPU insuficiente para el tamaño de modelo
  necesario (ver `docs/v3/28-requisitos-de-instalacion.md`); no se revisita
  en este programa.
- **NVIDIA NIM como carril semántico de producción (B3)**: insuficiente con
  números reales. Recall global 0.357 sobre el mismo corpus donde el
  determinista de B2 obtiene 0.607 — el carril semántico, tal como se probó,
  **no supera** al determinista en este dominio. La decisión de adopción
  además carece de dos datos que el operador necesitaría: precio real por
  token (no verificado en el repo ni públicamente en el momento de la
  corrida) y estabilidad más allá de una sola corrida de 60 episodios (0
  reintentos, 0 timeouts — pero una corrida no distingue un día bueno de la
  norma).
- **Coordinación de sujetos ("Runa Belisa y Beltrán Osk...")**: la guarda
  `COORDINATED_SUBJECT` se abstiene deliberadamente porque el extractor no
  tiene dependencias sintácticas (no hay parser de dependencias en el
  pipeline determinista) para decidir a cuál de los dos sujetos coordinados
  corresponde el resto de la frase. Resolverlo exigiría análisis sintáctico
  real, fuera del alcance morfológico/basado en reglas de B2-B4.
- **Doble negación mecánica** ("No es falso que..."): irreducible por
  diseño. `classify_negation` se abstiene ante dos marcas de negación a
  propósito — resolverla con una regla ad-hoc sería exactamente el tipo de
  regla frágil que el programa evita.

## 5. El techo estructural que queda (taxonomía completa en `b4-taxonomia.md`)

De los 22 casos `NO_OUTPUT` del corpus de desarrollo verificados caso a caso
en B4:

- **13 casos — arquitectura OCR/ASR**: la fuente entra por bytes/audio con
  ruido simulado (`ambar-escaneo`, OCR; `zafiro-sesion`, ASR) y el texto no
  alinea o llega corrupto al extractor. No es un problema de reglas de
  negación: es que el texto de entrada no es el que el gold espera. El
  carril OCR (B1) ataca la mitad de este problema (conectar el proveedor);
  la alineación ASR queda fuera del alcance del programa.
- **3 casos — coordinación de sujetos**: sin dependencias sintácticas, ver
  §4.
- **2 casos — correferencia** (anáfora pronominal "lo", tópico
  frontalizado): exige resolución de correferencia, no flexión verbal.
- **1 caso — relación no cubierta**: "tiene sede" no está en
  `RELATION_RULES` (brecha de vocabulario, no de negación).
- **1 caso — verbo factivo-negativo** (`bas:e04`, "desmentir que"): clase
  semántica distinta de los verbos de reporte neutro del paradigma de B4;
  pendiente de análisis propio (misma familia que el defecto de
  clasificación de `cir:e14`, "negó que + subjuntivo").
- **1 caso — doble negación**: irreducible por diseño, ver §4.
- **1 caso — cuantificador negativo** ("Nadie ha afirmado que..."): el caso
  que motivó y a la vez delimitó el paradigma morfológico de B4; conjugar el
  verbo no basta, hace falta reconocer el alcance de un cuantificador.

## 6. Recomendaciones para el operador

**Para subir del 0.607 de cobertura de desarrollo**, por orden de
palanca/coste:

1. Reparar la alineación ASR (`zafiro-sesion`, 7 de los 13 casos de
   arquitectura): probablemente el mayor tramo de ganancia por caso, y no
   toca reglas de negación en absoluto — es un problema de la capa de
   ingesta/normalización de audio transcrito.
2. Instalar Tesseract en el entorno de desarrollo/CI y correr
   `tests/test_gate4_b1_ocr_real.py` (hoy `skipped`, gateado y listo) para
   confirmar con el binario real lo que B1 validó en VM105.
3. Ampliar `RELATION_RULES` con más frases de relación equivalentes (el caso
   "tiene sede" es un ejemplo concreto, de bajo coste).
4. Coordinación de sujetos y correferencia exigen invertir en análisis
   sintáctico (parser de dependencias): cambio de orden de magnitud distinto
   a las reglas léxicas/morfológicas de B2/B4, y **decisión del operador**,
   no algo para forzar con reglas ad-hoc.

**Para decidir sobre NVIDIA** hacen falta, como mínimo, dos datos que hoy no
existen en el repo: (a) precio real contratado por token/llamada (el repo no
tiene ninguna cifra verificable), y (b) una medición de estabilidad repetida
en horarios/días distintos (la de B3 es una sola corrida de 60 episodios).
Sin esos dos datos, cualquier decisión de adopción sería prematura — y con
el dato de recall que sí existe (0.357 frente a 0.607 del determinista), la
prioridad de negocio de conseguir esos datos es baja mientras el
determinista siga siendo la opción de mejor cobertura medida.

## 7. Reproducibilidad

```
cd S9-Knowledge
PYTHONPATH=data-engine/app python3 scripts/gate4/measure_b5.py \
    --out-dir artifacts/gate4-program --out-name b5-final
```

Compara automáticamente contra `artifacts/gate4-program/b4-resultado.json` y
deriva el veredicto de puerta sin ninguna cifra escrita a mano. Tests:
`data-engine/app/tests/test_gate4_b5_final.py`.
