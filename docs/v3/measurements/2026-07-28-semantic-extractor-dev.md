# Extractor semantico sobre dev — medicion del 2026-07-28

**Split: `dev`. NUNCA held-out.** Corpus: 6 fuentes, 16 episodios, 72 fragmentos,
51 menciones gold, 20 claims gold para el extractor (uno de ellos es una
abstencion, ver §6).

Reproducir:

```bash
cd data-engine/app
PYTHONPATH=. python3 -m knowledge_v3.extraction.semantic_bench \
    --config A --config C1 --config D \
    --cache runs/c1_cache.json --out runs/report.json
```

Evidencia cruda en este mismo directorio:

- `2026-07-28-semantic-extractor-dev.report.json` — informe completo del arnes;
- `2026-07-28-semantic-extractor-dev.raw-responses.json` — **las 16 respuestas
  literales de qwen2.5:7b**, con su latencia real. Repuntuar no exige repetir la
  tanda, y cualquiera puede comprobar que las cifras salen de ahi.

Configuraciones:

| id | que es | ejecucion |
|---|---|---|
| **A** | determinista solo (baseline) | local, sin red |
| **C1** | semantico con **qwen2.5:7b** via Ollama | **REAL**, 16 llamadas, 34,5 min |
| **C2** | semantico con **llama-3.3-70b** via NVIDIA | **NO EJECUTADA**: ver §5 |
| **D** | A + C1 como **union** sin reconciliador | derivada |

Los dos carriles reciben el **mismo lexico** (alias y facciones del
`GameProfile`, no el catalogo de entidades del benchmark) y la misma ontologia.

---

## 1. Menciones

Emparejamiento **exacto** de spans (defecto del arnes) y, declarado aparte,
**solape** con IoU ≥ 0,5 (modo explicito del arnes, `span_mode="overlap"`).

| metrica | A | C1 | D |
|---|---|---|---|
| menciones propuestas | 42 | 38 | 80 |
| tp / fp / fn (exacto) | 38 / 4 / 13 | 24 / 14 / 27 | 39 / 41 / 12 |
| **precision (exacto)** | **0,905** | 0,632 | 0,488 |
| **recall (exacto)** | **0,745** | 0,471 | **0,765** |
| precision (solape) | 0,905 | 0,811 | 0,506 |
| recall (solape) | 0,745 | 0,588 | 0,784 |
| **tipo correcto (emparejadas)** | **0,000** | **0,917** | 0,026 |
| superficies inventadas | **0** | **0** | **0** |
| menciones no ancladas | **0** | **0** | **0** |
| superficie no literal | 7 | 1 | 8 |
| superficies nuevas propuestas | 0 | 7 | 7 |
| superficies nuevas que aciertan gold | 0 | **0** | 0 |

Lectura honesta de la diferencia exacto/solape: **la mitad de los "falsos
positivos" de C1 son la misma entidad con otro corte**:

```
C1 propone            gold espera
'la Cofradía de Ámbar' → 'Cofradía de Ámbar'
'El Gremio de Faros'   → 'Gremio de Faros'
'El escriba V4ndreth'  → 'V4ndreth'
'recinto de la Casa del Ciervo' → 'Casa del Ciervo'
```

No es alucinacion (las superficies inventadas son **0** en las tres
configuraciones, comprobado contra el texto gold de forma independiente del
extractor): es una convencion de limites que el modelo no conoce. Con solape,
la precision de C1 sube de 0,632 a 0,811.

Las **7 superficies nuevas** que C1 propone y el gold no tiene son cargos y
ruido (`magistrado`, `Ciclo`, `titiriteros`…): existen en el texto, pero
**ninguna es una entidad nueva acertada**. En este corpus, con el glosario ya
cargado, el extractor semantico **no descubrio ninguna entidad que el glosario
no tuviese**.

---

## 2. Claims (el eje del bloque)

| metrica | A | C1 | D |
|---|---|---|---|
| claims activos propuestos | 0 | 11 | 11 |
| abstenciones | 0 | 5 | 5 |
| tp / fp / fn | 0 / 0 / 20 | 5 / 6 / 15 | 0 / 11 / 20 |
| precision | n/d | 0,455 | 0,000 |
| **recall** | **0,000** | **0,250** | 0,000 |
| **predicado top-1 (recall sobre gold)** | **0,000** | **0,200** | 0,000 |
| **predicado top-2 (recall sobre gold)** | **0,000** | **0,200** | 0,000 |
| predicado top-1 (sobre emparejados) | n/d | 0,800 | n/d |
| predicado top-2 (sobre emparejados) | n/d | 0,800 | n/d |
| direccion top-1 (recall sobre gold) | 0,000 | 0,250 | 0,000 |
| **predicados fuera de la ontologia** | **0** | **0** | **0** |
| claims con evidencia anclada | 0 | **16 / 16** | 16 |
| claims con argumentos inventados | **0** | **0** | **0** |

Con emparejamiento por solape, C1 sube a **tp 8, recall 0,400, top-1 y top-2
0,350, direccion 0,350**.

Tres lecturas que no se pueden esquivar:

1. **top-2 == top-1 (0,200).** La arquitectura admite hasta tres predicados
   candidatos ordenados; **qwen2.5:7b devolvio uno solo casi siempre**. La
   capacidad que el contrato ya tenia y nunca se ejercitaba sigue sin
   ejercitarse, y no por el diseno: por el modelo. Es exactamente el tipo de
   diferencia que solo se puede atribuir cambiando el adaptador (C2).
2. **Cuando el claim existe, el predicado suele ser el correcto** (0,800 sobre
   emparejados). Lo que falla no es elegir predicado, es **llegar a proponer el
   claim**: 15 de 20 no se proponen.
3. **Cero predicados fuera de la ontologia.** El filtro funciona: el modelo
   propuso `NEGATED_MEMBER_OF` (que no existe) y se descarto como candidato con
   `PREDICATE_NOT_IN_PROFILE`, sin tirar nada mas.

---

## 3. Por que C1 pierde recall: el modelo corrompe sus propias citas

Diagnosticos de C1 (16 episodios):

| codigo | veces | que significa |
|---|---|---|
| `HALLUCINATED_MENTION` | 7 | superficie que no aparece literalmente |
| `HALLUCINATED_QUOTE` | 7 | cita que no aparece literalmente |
| `SUBJECT_NOT_GROUNDED` | 5 | el claim apunta a una mencion que no sobrevivio |
| `OBJECT_NOT_GROUNDED` | 2 | idem |
| `PREDICATE_NOT_IN_PROFILE` | 1 | candidato fuera de la ontologia |

Caso literal, episodio `leyenda-cronica:e01`. El texto dice:

```
Ilaria Vandreth dirigió la Casa del Ciervo desde el invierno de 1041 hasta la
caída de Vado Alto.
```

y qwen2.5:7b cito:

```
... hasta la caúda de Vado Alto.
                  ^^^^^
```

El claim era **correcto** (`LEADS`, `Ilaria Vandreth` → `Casa del Ciervo`) y se
cayo entero porque su prueba no existe en el texto. La barrera hizo lo que debe
hacer. El episodio con el claim mas facil del corpus acabo con **1 mencion y 0
claims**.

Ademas, una comprobacion incomoda: **una tanda anterior sobre ese mismo episodio,
con el mismo prompt y `temperature=0`, cito la palabra bien**. qwen2.5:7b **no
es reproducible entre tandas** en este servidor, asi que sus cifras tienen una
varianza que este corpus (16 episodios) no permite estimar.

---

## 4. D (union sin reconciliador): el resultado que hacia falta ver

D sube el recall de menciones (0,765 frente a 0,745 de A) y **hunde los claims a
cero**. No es que el semantico empeore: es que **la union sin reconciliar es
inevaluable** por construccion.

Comprobado, no supuesto:

```
menciones alineadas con el gold, por paso:  determinista 38  |  semantico 1
claims semanticos activos: 11  →  con algun argumento NO alineado: 11
```

Determinista y semantico proponen **la misma mencion con el mismo span y dos
ids distintos**. El emparejamiento es uno a uno (y debe serlo: sin eso, repetir
una prediccion subiria el recall gratis), asi que el gold se lo lleva el
duplicado determinista y los 11 claims del semantico se quedan **sin argumentos
alineados**. Los duplicados cuentan ademas como falsos positivos y tiran la
precision de menciones a 0,488.

**Conclusion operativa: el bloque de reconciliacion no es un lujo, es un
requisito para que la union tenga sentido.** Publicar D como "peor" seria
enganoso; lo correcto es decir que D **no se puede evaluar** en claims mientras
no exista reconciliador.

---

## 5. C2 (NVIDIA / llama-3.3-70b): preparada, no ejecutada

No se ejecuto porque **la API key solo existe en VM105** y en este entorno no
esta. No se ha inventado ninguna cifra suya.

Lo que si esta comprobado aqui:

- el puerto se construye y declara `provider=external`, modelo
  `meta/llama-3.3-70b-instruct`;
- sin key **falla limpio**: `AuthError` → `ProviderUnavailable`, y el extractor
  lo convierte en abstencion, nunca en un resultado;
- con un cliente doble, el extractor produce **exactamente la misma salida** que
  con el puerto local (test
  `TestPuertoNvidia::test_el_extractor_no_distingue_el_carril`), y la traza dice
  `external`, no `local`.

Orden unica para ejecutarla donde haya key:

```bash
cd data-engine/app
S9K_NVIDIA_API_KEY=... PYTHONPATH=. python3 -m knowledge_v3.extraction.semantic_bench \
    --config C2 --cache runs/c2_cache.json --out runs/report_c2.json
```

---

## 6. Rendimiento (registrado, no maquillado)

| | A | C1 |
|---|---|---|
| tasa de JSON valido | — | **16/16 = 1,00** |
| reintentos de JSON | — | **0** |
| timeouts | — | **0** |
| llamadas al proveedor | 0 | 16 |
| segundas llamadas temporales | 0 | **0** |
| latencia media por episodio | — | **129,3 s** |
| latencia mediana | — | 123,1 s |
| latencia maxima | — | **242,2 s** |
| tiempo total | 0,085 s | **34,5 min** |

Dos cosas que salieron mejor de lo esperado y una que no:

- **JSON valido al 100 %, cero reintentos.** El formato conjunto no es el
  problema.
- **Cero segundas llamadas temporales.** El escalonado funciono: toda la
  temporalidad del corpus se resolvio en local o no existia. La segunda llamada
  para todos los claims que hacia el camino anterior era gasto puro.
- **129 s de media por episodio.** Para 16 episodios de dos frases. Es del mismo
  orden que lo ya medido (65-190 s, pico 589 s) y **no es viable en produccion**.

---

## 7. Gates del bloque, uno a uno

### Funcional

| gate | resultado | evidencia |
|---|---|---|
| produce menciones nuevas | **PARCIAL** | 7 superficies fuera del glosario, pero **0** aciertan gold |
| produce claims validos | **SI** | 11 activos, 5 tp exactos (8 con solape); A produce 0 |
| TODAS las superficies ancladas | **SI** | 0 inventadas, 0 no ancladas |
| TODOS los predicados en la ontologia | **SI** | 0 fuera; el `NEGATED_MEMBER_OF` del modelo se descarto |
| ninguna salida firma ni aprueba | **SI** | `review_required=True` en todo; traza veraz |
| mismo contrato con Ollama y NVIDIA | **SI** | misma salida con ambos puertos (probado con doble) |

### Comparativo (C1 frente a A)

| gate | resultado | cifra |
|---|---|---|
| mejora el recall de **menciones** | **NO** | 0,471 < 0,745 (con solape 0,588 < 0,745) |
| mejora el recall de **claims** | **SI** | 0,250 > 0,000 |
| mejora el recall **top-2 de predicado** | **SI** | 0,200 > 0,000 |
| sin disparar menciones inventadas | **SI** | 0 y 0 |
| sin disparar claims inventados | **SI** | 0 y 0 |

En la union D el recall de menciones **si** supera al baseline (0,765 > 0,745),
pero a costa de una precision de 0,488 y de claims inevaluables (§4).

### Rendimiento

Registrado sin maquillar (§6). **No hay gate de rendimiento que aprobar en este
bloque**: hay una cifra que declarar, y la cifra es 129 s por episodio.

---

## 8. Veredicto sobre la viabilidad de qwen2.5:7b

**La arquitectura funciona; el modelo 7B no da para produccion.** Con detalle,
porque las dos mitades importan:

*Lo que demuestra que la arquitectura es correcta:*

- pasa de **0 a 11 claims** propuestos y de **0 a 5** aciertos sobre un corpus
  donde el determinista no puede acertar ninguno;
- **0 predicados fuera de la ontologia** y **0 alucinaciones** que sobrevivan:
  el guiado por ontologia y la frontera anti-alucinacion hacen su trabajo;
- **tipo de entidad correcto en el 92 %** de las menciones emparejadas, frente
  al **0 %** del determinista (que emite menciones sin tipo);
- **100 % de JSON valido, 0 reintentos, 0 segundas llamadas temporales**;
- cuando propone un claim, **el predicado es el correcto 4 de cada 5 veces**.

*Lo que descalifica a qwen2.5:7b:*

- **129 s por episodio de dos frases** (max 242 s). 16 episodios = 34,5 min;
- **corrompe sus propias citas literales** (7 menciones y 7 citas caidas), y
  eso destruye recall en el unico sitio donde no hay recuperacion posible: la
  prueba;
- **no usa los candidatos multiples**: top-2 = top-1. La capacidad clave del
  diseno se queda sin ejercitar;
- **no es reproducible entre tandas** a temperatura 0;
- recall de menciones **por debajo** del determinista.

Es un resultado legitimo del bloque, y es el que hay: **arquitectura valida,
qwen2.5:7b no viable**. Queda pendiente la unica medicion que puede separar
"limite del 7B" de "limite del diseno": ejecutar **C2** con
`meta/llama-3.3-70b-instruct` bajo **el mismo contrato**, que esta preparada y
arranca con una sola orden.

**Lo que este bloque NO autoriza:** desplegar nada, activar el semantico en
produccion, ni tocar el gate determinista, que sigue intacto.
