# 03 — Subsistema EXTRACTOR (S9-Knowledge V3)

Rama `feat/v3-extractor`. Base: `36439a2` (contratos congelados
`v3-contracts-frozen-1.0.0`).
Codigo: `data-engine/app/knowledge_v3/extraction/`.
Tests: `data-engine/app/tests/test_knowledge_v3_extraction.py` y
`test_knowledge_v3_extraction_ollama.py`.

---

## 1. Que hace y que NO hace

```text
SourceEpisode + EvidenceFragment  →  [extractores]  →  EntityMention + ClaimProposal
```

Y se acaba ahi. El extractor **no** escribe en Neo4j, **no** decide identidad,
**no** canoniza predicados, **no** cierra vigencias y **no** aprueba nada. Emite
propuestas; el motor local decide. La salida **nunca** es un grafo: los dos
unicos contratos que salen de aqui son `entity-mention/v3-internal-v1` y
`claim-proposal/v3-internal-v1`.

Los contratos estan **congelados**: este subsistema no ha tocado ni un schema ni
un modelo. No ha hecho falta ningun campo que no existiera.

### Las tres invariantes

| Invariante | Como se garantiza | Donde se prueba |
|---|---|---|
| **Anclaje real** | Nada sale sin un `EvidenceFragment` existente que lo sostenga. Las citas de los modelos se verifican contra el texto literal **y contra su contexto** | `TestAntiHallucination`, `TestTextAndAnchoring`, `TestQuoteInContext` |
| **Traza veraz** | `provider_trace` + `produced_by_step` dicen quien produjo cada cosa. Una salida externa nunca se disfraza de local | `test_produced_by_step_apunta_al_paso_real`, `test_las_propuestas_externas_se_trazan_como_externas` |
| **Abstencion legitima** | `abstained=True` + `confidence=0` es salida de primera clase, con codigos de razon estables en `metadata.abstention_reasons` | `test_abstencion_no_lleva_predicado_ni_confianza` |

Ultima barrera: `base.emit()` valida **todo** documento contra el JSON Schema y
las reglas semanticas antes de emitirlo. Lo que no valida no sale: se convierte
en diagnostico `CONTRACT_VIOLATION`.

---

## 2. Arquitectura

```text
extraction/
  text.py          tokenizacion con offsets reales + EvidenceIndex (anclaje)
  base.py          interfaz Extractor, ExtractionContext/Output, constructores
  lexicon.py       puente de solo lectura con el glosario V1 y el GameProfile
  payload.py       frontera de confianza: payload de modelo -> propuestas
  deterministic.py glosario + patrones + reglas de evidencia inequivoca
  table.py         estructura fila-columna de un episodio TABLE
  temporal.py      expresiones temporales ancladas, con calendar_id del perfil
  coreference.py   pronombres y primera persona -> menciones enlazadas
  ollama_client.py cliente Ollama (env-configurable, transporte inyectable)
  ollama.py        prompts JSON estrictos + reintento + abstencion
  external.py      SOLO punto de enganche hacia el subsistema de proveedores
  visual.py        interfaz + stub honesto (VISUAL_INFERRED pendiente)
  pipeline.py      orquestacion (determinista → tabla → temporal → correferencia)
```

Piezas transversales que conviene conocer antes de tocar nada:

- **`text.tokenize`**: se empareja siempre por TOKENS normalizados uno a uno,
  nunca sobre el texto entero normalizado. La normalizacion NFKD cambia la
  longitud de la cadena; normalizando token a token, el `(start, end)` que se
  emite sigue apuntando al texto original. La normalizacion se **importa** de
  `glossary.glossary_store.normalize_term` (V1): no se duplica.
- **`text.EvidenceIndex`**: el anclaje. Un `fragment_id` solo vale si lo creo el
  sistema local; una cita solo vale si aparece literalmente en ese fragmento. Si
  el proveedor propone un id que no existe, se intenta **reanclar por
  contenido** y se marca `FRAGMENT_ID_NOT_FOUND` / `REANCHORED_BY_CONTENT`; si
  la cita tampoco existe en ningun fragmento, la propuesta se cae.
- **base de offsets**: cuando el episodio tiene texto, los offsets son del
  episodio; cuando no (TABLE, IMAGE), son del texto literal del fragmento que
  ancla. Se declara SIEMPRE en `metadata.offset_basis` (+ `offset_fragment_id`).

---

## 3. Que extractor emite que

| Extractor | Paso (`produced_by_step`) | Provider | Emite | Estado |
|---|---|---|---|---|
| Determinista | `extract.deterministic` | `local` | menciones (glosario, alias, patron de titulo) + claims con evidencia inequivoca + abstenciones | **real** |
| Tabla | `extract.table` | `local` | menciones de celda + claims fila-columna + abstenciones | **real** |
| Temporal | `extract.temporal` | `local` | `temporal_expressions` (dentro de los claims del determinista y como claim abstenido suelto) | **real** |
| Correferencia | `extract.coreference` | `local` | menciones de pronombre con `coreference_candidates` | **real** |
| Ollama | `extract.ollama` | `ollama` | menciones + claims (tope 0.7, `review_required` siempre) | **real** (verificado contra el servidor, §6) |
| Externo | `extract.external` | `external` | igual que Ollama, tope 0.6 | **solo interfaz**: el transporte vive en el subsistema de proveedores |
| Visual | `extract.visual` | — | nada | **stub honesto**: sin proveedor de vision, 0 propuestas + `VISION_PROVIDER_NOT_AVAILABLE` |

### 3.1. Determinista — precision, no cobertura

Es la leccion literal del PR #106: un clasificador lexico afinado sobre su
propio corpus dio `predicate 0.81` con dev==test y **0.24** sobre material real.
Este extractor no intenta tapar eso subiendo la cobertura; prefiere no emitir.

Un claim solo sale si se cumplen **todas** estas condiciones:

1. sujeto y objeto son menciones ancladas a fragmentos reales;
2. la frase de relacion esta en la MISMA frase, entre sujeto y objeto;
3. no hay coordinacion ni puntuacion debil entre los argumentos y la frase —
   incluida la coordinacion **dentro** del sintagma ("Elara y Kael viven en
   Valdor" no afirma nada de uno solo). Se busca en VENTANA
   (`COORDINATION_WINDOW`) y con formas de varias palabras
   (`COORDINATION_PHRASES`: "y tambien", "asi como", "ni siquiera", "junto a",
   "o a"…), porque la coordinacion casi nunca es adyacente;
4. la distancia sujeto/frase/objeto no supera `MAX_ARGUMENT_GAP` (2 tokens);
5. ningun argumento es un MODIFICADOR de otro nucleo: una mencion precedida de
   "de", "del", "por", "segun"… ("el hermano **de** Kael vive en Valdor" no dice
   donde vive Kael) — `SUBJECT_IS_MODIFIER` / `OBJECT_IS_MODIFIER`;
6. no hay varias menciones candidatas a sujeto antes de la frase
   (`MULTIPLE_SUBJECT_CANDIDATES`): elegir por proximidad es elegir a ciegas;
7. el contexto es FACTIVO (§3.1.1);
8. si hay `GameProfile`: el predicado esta en el perfil y los tipos encajan con
   su dominio/rango.

Si algo falla, o no se emite nada, o se emite una **abstencion** con su codigo
(`COORDINATED_SUBJECT`, `ARGUMENT_TOO_FAR`, `PREDICATE_NOT_IN_PROFILE`,
`TYPE_INCOMPATIBLE_WITH_PROFILE`, `OBJECT_TYPE_MISMATCH`…).

#### 3.1.1. Factividad (`cues.py`)

Que una frase contenga "Kael vive en Valdor" no significa que lo afirme:

| Contexto | Ejemplo | Salida |
|---|---|---|
| Falsedad | "Es falso que Kael vive en Valdor", "Nadie cree que…", "afirmo falsamente que…" | **abstencion** `NON_FACTIVE_CONTEXT` + `FALSITY_CONTEXT` |
| Interrogativa | "¿Kael vive en Valdor?" | **abstencion** `INTERROGATIVE_CONTEXT` |
| Condicional | "Si Kael vive en Valdor…", "salvo que…", "a menos que…" | claim con `HYPOTHETICAL` + `review_required=True` |
| Negacion | "Kael no vive en Valdor", "Ni siquiera Kael vive en Valdor" | claim con `negated=True` + `review_required=True` |

Lo negado **si** se propone: leer "no vive" y proponer `LIVES_IN` marcado como
negado es leer bien el texto. Lo que no puede pasar es que salga como afirmacion
plana.

Ademas lee el contexto: negacion (`NEGATION_CUES` en los 3 tokens previos),
epistemicidad (`se rumorea`, `quiza`, `planea`… → `RUMORED` / `HYPOTHETICAL` /
`INTENDED`, siempre con `review_required=True`) y temporalidad de la frase.

**Las confianzas son priores escritos a mano, no probabilidades medidas.** Su
unico compromiso es el orden relativo (canonico > alias, regla estricta > laxa).
El valor absoluto no significara nada hasta que lo mida el benchmark.

### 3.2. Tabla

La primera columna (o la que el encabezado identifique como sujeto) es el sujeto
de la fila; cada columna con encabezado **mapeado** produce un claim. La
direccion es explicita en la regla: una columna "Lider" afirma que el objeto
lidera al sujeto (`OBJECT_TO_SUBJECT`), y confundirlo invertiria el grafo.
Encabezado no mapeado = diagnostico, no invencion. Celda multivalor
("Kael, Aldric") = abstencion `TABLE_MULTIVALUE_CELL`.

### 3.3. Temporal

Expresiones POINT / INTERVAL / DURATION / RELATIVE, ancladas a fragmento.
`calendar_id` se rellena solo si el `GameProfile` declara ese calendario y su
`epoch_label` o alguna `unit` acompana a la expresion (hasta 6 tokens despues).
**`valid_from` / `valid_to` solo se rellenan con fechas ISO reales**: "el ano 300
de la Tercera Era" no tiene traduccion a UTC y fingirla seria inventar un dato.
Las expresiones sueltas salen como claim **abstenido** que las conserva anclada
y trazada, sin que nadie las confunda con algo aprobable.

### 3.4. Correferencia

Intra-episodio y nada mas (las cadenas entre episodios son del subsistema de
resolucion). Pronombres personales (`él`, `ella`, `ellos`, `ellas`) exigen
antecedente de tipo `Character`; sin ese filtro, "Kael entro en Valdor. Él vive
alli" resolveria a Valdor, que es la mencion mas cercana. La comparacion se hace
sobre el texto **original en minusculas**, no sobre la forma normalizada: al
quitar tildes, el articulo "el" y el pronombre "él" son indistinguibles y el
extractor generaria una mencion espuria en cada sintagma.

Primera persona solo se resuelve con `speaker` (diarizacion) cuya etiqueta
coincida con una mencion real. Varios antecedentes compatibles = `PRONOUN_AMBIGUOUS`
y no se resuelve: una identidad mal propagada contamina todo lo que cuelgue.

### 3.5. Ollama

`S9K_OLLAMA_URL` (defecto `http://192.168.1.157:11434`), `S9K_OLLAMA_MODEL`
(defecto `qwen2.5:7b`), `S9K_OLLAMA_TIMEOUT` (defecto **300 s**, medido, ver §6),
`S9K_OLLAMA_RETRIES`. Sin IP cableada en la logica (defecto D12 de la auditoria:
`review/llm_extractor.py:55`).

Se le pasan los `fragment_id` **reales** y se le pide que cite literalmente. Su
respuesta se verifica igual:

- **los offsets del modelo se ignoran por completo**: los calcula el motor local
  buscando la superficie en el texto real;
- una superficie que no aparece literalmente en ningun fragmento se descarta
  (`HALLUCINATED_MENTION`);
- una cita inexistente tumba la propuesta (`HALLUCINATED_QUOTE`);
- **la cita es obligatoria** para afirmar (`CLAIM_WITHOUT_QUOTE`): dos menciones
  ancladas no sostienen la relacion entre ellas;
- **la cita se verifica EN CONTEXTO**: si el texto real que rodea al ancla niega
  ("Kael **no** sirve a la Orden" citado como "sirve a la Orden"), condiciona,
  pregunta o desmiente, el claim se abstiene (`NEGATION_CONTEXT_MISMATCH`,
  `NON_FACTIVE_CONTEXT`). Si el contexto solo degrada la epistemicidad, manda el
  texto sobre lo que dijera el modelo;
- una cita presente en DOS fragmentos (`AMBIGUOUS_ANCHOR`) tampoco vale para
  afirmar: puede estar afirmada en uno y negada en el otro;
- los offsets se buscan **dentro del fragmento elegido**, nunca en el episodio
  entero: un documento no puede decir que esta anclado en A con offsets de B;
- un claim cuyos argumentos no son menciones ancladas se descarta
  (`SUBJECT_NOT_GROUNDED` / `OBJECT_NOT_GROUNDED`). **Nunca** se crea una mencion
  de apoyo para salvar un claim: seria fabricar la evidencia que faltaba;
- JSON invalido → **un** reintento con instruccion correctiva → **abstencion**
  explicita. La reparacion admitida es solo sintactica (vallas markdown, recorte
  al primer objeto `{...}`): no se completan campos ni se adivinan valores;
- confianza limitada a 0.7 y `review_required=True` **siempre**. Ollama propone;
  no aprueba.

### 3.6. Externo y visual

`ExternalExtractor` implementa la frontera y **nada mas**: `ExternalProposalPort`
(una operacion, fail-closed) y la normalizacion por el mismo filtro
anti-alucinacion, con `provider: "external"` en la traza y tope 0.6. El
transporte (enrutado, cuotas, coste, redaccion de credenciales) es del subsistema
de proveedores: si viviera tambien aqui, la politica quedaria duplicada y una de
las dos copias se quedaria vieja. Sin puerto enganchado no falla ni finge: emite
`EXTERNAL_PROVIDER_NOT_BOUND` y devuelve vacio.

`VisualExtractor` es un **stub honesto**: 0 propuestas. Lo que si deja fijado y
probado es la regla de nacimiento de lo visual: cualquier claim inferido de una
imagen nace con `epistemic_status_hint=VISUAL_INFERRED` y `review_required=True`
(dosier 7.6), forzado en el codigo aunque el proveedor diga otra cosa. Un stub
que devolviera menciones plausibles seria mucho peor que uno vacio: el benchmark
las mediria como extraccion real.

---

## 4. Reutilizacion de V1/V2 (sin tocar nada)

| Se reutiliza | Como | Por que asi |
|---|---|---|
| `glossary.glossary_store.normalize_term` | import diferido, solo lectura | la normalizacion no se duplica: si cambia, cambia en un sitio |
| `glossary.glossary_models.GlossaryTerm` | puente `Lexicon.from_glossary_terms` (duck-typed) | V3 copia lo que necesita; no muta el glosario ni depende de su esquema |
| Validador de contratos v3 | `contracts/knowledge-v3/v1/validator.py` (orden canonico de candidatos) | el orden total lo define el contrato, no el extractor |

No se ha modificado ni una linea de `relations/`, `review/`, `glossary/`,
`external_ai/` ni de ningun otro paquete V1/V2. Tampoco `ci.yml` ni `pytest.ini`.
Las `error_forms` del glosario se excluyen a proposito: son errores conocidos de
transcripcion, utiles para ASR, pero aceptarlas como superficie de entidad
meteria falsos positivos en un extractor cuyo objetivo declarado es la precision.

---

## 5. Tests

| Fichero | Tests | Contenido |
|---|---|---|
| `test_knowledge_v3_extraction.py` | 144 | texto/anclaje, lexico, cumplimiento de contratos, precision determinista sobre GOLD, anti-alucinacion, factividad, coordinacion y modificadores, temporal, correferencia, tablas, externo/visual, pipeline, **mutaciones**, **mini-corpus trampa** |
| `test_knowledge_v3_extraction_ollama.py` | 23 + 2 humo | configuracion, cliente mockeado, parseo JSON, extractor Ollama; `@pytest.mark.live_ollama` (skip salvo `S9K_LIVE_OLLAMA=1`) |

**167 tests, 0 fallos** (mas 2 de humo, saltados por defecto).

`TRAP_CORPUS` (17 frases construidas para engañar a un extractor lexico:
coordinaciones no adyacentes, sujetos-modificador, condicionales,
interrogativas, desmentidos y negaciones) se mide por **afirmaciones
equivocadas: cero**. Callar o abstenerse cuenta como acierto; proponer algo
negado o hipotetico solo cuenta si sale marcado y pidiendo revision.

Las fixtures GOLD son seis episodios propios con verdad de campo escrita a mano
(`GOLD_CLAIMS`). Sirven para fijar el **comportamiento**, no para estimar
calidad: se exige **precision 1.0** (cero falsos positivos) y la cobertura se
reporta con un umbral bajo a proposito. Convertir seis frases escritas por
nosotros en un objetivo de calidad seria repetir exactamente el error del PR
#106 (dev == test).

Mutaciones incluidas (si al romper la regla la suite sigue verde, esa regla no
sostenia nada): guarda de coordinacion, marcas de negacion, marcas epistemicas,
verificacion de citas (al desactivarla, una entidad inventada entra en el
sistema), distancia maxima del pronombre, **guarda de misma-frase** (al
relajarla, "Kael descanso. Vive en Valdor." produce un claim) y **exactitud de
la contencion de citas** (una cita que se parece un 0.98 no es la cita:
"Valdorr", "Valdar" y "no vive en Valdor" no anclan).

La suite unitaria **no abre sockets**: hay un test que sustituye `urlopen` por
una bomba y ejecuta el pipeline local completo.

---

## 6. Humo REAL contra Ollama (2026-07-27)

Ejecutado de verdad contra `http://192.168.1.157:11434`, modelo `qwen2.5:7b`
(unico instalado). Solo inferencia: no se escribio en ningun sitio.

| Aspecto | Resultado real |
|---|---|
| `/api/tags` | responde; `qwen2.5:7b` presente |
| Latencia de una extraccion de UNA frase | **111 s – 190 s** por episodio (4 ejecuciones) |
| Salida (3 de 4 ejecuciones) | 3 menciones correctas (`Kael`/Character, `Valdor`/Location, `Orden del Alba`/Faction) y 2 claims correctos (`LIVES_IN`, `SERVES`), todos anclados a `frag:ep:live:0`, offsets verificados contra el texto |
| Salida (1 de 4) | 1 mencion y **0 claims**: el modelo propuso un claim con un objeto que no habia anclado y el filtro lo rechazo (`OBJECT_NOT_GROUNDED`) |
| Contratos | todos los documentos emitidos validan; ningun `fragment_id` fuera de los reales |

Tres hallazgos honestos de esta medicion:

1. **el timeout por defecto era erroneo**. Con 60 s el extractor se abstenia por
   `OLLAMA_UNAVAILABLE` con el servidor perfectamente vivo — el peor falso
   negativo, porque parece fallo del modelo y es de configuracion. Corregido a
   **300 s** con el numero medido documentado en el codigo;
2. **`qwen2.5:7b` devuelve `confidence: 0.0`**, copiando el valor del ejemplo del
   prompt. Se añadio una instruccion explicita para que no lo copie y **siguio
   haciendolo**. Es un dato del modelo, no un fallo del extractor: la confianza
   de Ollama, hoy, no informa de nada. Otra razon mas para el tope y para
   `review_required=True`;
3. **la salida no es estable entre ejecuciones** aun con `temperature=0`. La
   variacion no rompio nada porque el filtro anti-alucinacion es determinista y
   local: lo que no esta anclado, no entra.

---

## 6.bis. Ronda de revision independiente (NO CONFORME -> corregido)

Una revision independiente demostro lo que ninguna de las pruebas propias veia:
**un claim afirmado podia anclarse a evidencia que no decia lo que afirmaba**.
Su mini-corpus trampa dejo la precision del determinista en 0.40. Lo corregido:

| # | Hallazgo | Correccion |
|---|---|---|
| B1 | Un claim de modelo SIN cita se emitia sin verificar nada (`SERVES` inventado sobre dos menciones reales, `abstained=False`, 0 diagnosticos) | La cita es **obligatoria** para afirmar; sin ella, abstencion `CLAIM_WITHOUT_QUOTE` |
| B2 | Cita parcial que invierte el sentido: "Kael **no** sirve a la Orden" citado como "sirve a la Orden" salia `SERVES, negated=False` | Verificacion **en contexto** (`cues.analyze_context` sobre el texto real que rodea al ancla); discrepancia -> abstencion `NEGATION_CONTEXT_MISMATCH` |
| B3 | El reanclaje elegia `matches[0]` y podia anclar al fragmento negado; `AMBIGUOUS_ANCHOR` era decorativo | Un claim con `AMBIGUOUS_ANCHOR` se abstiene |
| B4 | Contextos no factivos (condicional, interrogativa, "Es falso que", "Nadie cree que", "afirmo falsamente", "salvo que") salian `ASSERTED` con `review_required=False` | Guardas de factividad: falsedad e interrogativa -> abstencion; condicional -> `HYPOTHETICAL` + revision. Los 6 casos, con test |
| B5 | La coordinacion se burlaba con un token intercalado ("Kael y tambien Mira") y el sujeto se tomaba por proximidad ("El hermano de Kael vive…" -> `LIVES_IN(Kael)`) | Coordinacion en ventana + formas de varias palabras; rechazo de sujeto/objeto **modificador**; abstencion con varias menciones candidatas. Los 8 casos, con test |
| B6 | Dos mutantes sobrevivian a la suite: relajar la guarda de misma-frase y una contencion de citas difusa (>=0.9) | Un test por mutante (§5) |
| A1 | `_locate` buscaba la cita en el episodio entero: offsets que caian en OTRO fragmento, en silencio | Busqueda acotada al rango del fragmento elegido; si no aparece ahi, se trata como reanclaje |
| A2 | `"confidence": "alta"` escapaba como `ValueError` y tumbaba el lote entero | `clamp` a prueba de tipos + `except (ValueError, TypeError)` en los extractores -> abstencion del episodio, nunca del lote. Diagnostico `INVALID_CONFIDENCE` |
| A3 | `confidence_cap` de Ollama sin acotar (`cap=1.0` emitia 0.99) | `min(cap, DEFAULT_CONFIDENCE_CAP)`, como ya hacia el externo |
| A4 | La tabla **inventaba** el tipo de la celda (`Elara` -> `Location` porque la columna se llamaba "Ubicacion") y no consultaba `profile.allows` | El tipo solo se pone si lo **confirma** el lexico; con perfil cargado y tipos no confirmables, abstencion `TYPES_NOT_CONFIRMABLE`; sin perfil, `review_required=True` |

Menores: el test de cobertura ahora **reporta** en vez de exigir; docstring de la
guarda 4 corregido; cabecera de `ollama_client.py` con el timeout real (300 s);
saneado de `name`/`version` del proveedor externo (charset, longitud y espacio
reservado `s9k.extraction.*`, que un externo ya no puede usar para hacerse pasar
por local); dos menciones de la misma superficie con tipos contradictorios ->
`CONFLICTING_MENTION_TYPES`.

Resultado sobre el mini-corpus trampa tras las correcciones: **0 afirmaciones
equivocadas de 17 frases**. El coste, medido y aceptado: una lectura legitima
("Segun Kael, Mira vive en Nara") ahora se abstiene. Es la direccion en la que
este subsistema prefiere equivocarse.

Comprobado ademas **en vivo** con `qwen2.5:7b`: sobre "Kael no sirve a la Orden
del Alba", el modelo propuso un claim y el filtro lo rechazo
(`OBJECT_NOT_GROUNDED`); sobre la frase afirmativa siguio emitiendo sus dos
claims correctos (65-112 s).

### Segunda ronda (CONFORME con observaciones)

| # | Observacion | Correccion |
|---|---|---|
| O1 | `OBJECT_IS_MODIFIER` no distinguia el "de" que CIERRA el predicado ("es padre **de** Mira") del que introduce un modificador ajeno. Consecuencia: `PARENT_OF`, `CHILD_OF`, `SIBLING_OF`, `ALLY_OF` y `ENEMY_OF` estaban **inertes** para persona->persona | La comprobacion se ignora cuando la preposicion cae dentro de la frase de relacion emparejada. Los 6 casos afirman; "el hermano de Kael vive en Valdor" y "Kael vive en la casa de Mira" siguen absteniendose |
| O2 | Una `confidence` mal tipada en un claim degradaba a 0.0 **en silencio** (las menciones si lo diagnosticaban) | `INVALID_CONFIDENCE` tambien a nivel de claim |
| O3 | `{"surface": ["Kael"]}` acababa como la superficie `"['Kael']"` | `TEXT_FIELDS` se exigen `str`; si no lo son, la propuesta se rechaza con `NON_TEXT_FIELD`. No se convierte nada con `str()` |

O1 era una perdida de cobertura silenciosa, no un falso positivo: el subsistema
callaba en toda una familia de relaciones sin que ninguna prueba lo notara.

---

## 7. Limites conocidos (lo que solo sabra el benchmark)

Esto es lo que **no** se sabe todavia, dicho antes de que nadie lo pregunte:

1. **La calidad real del determinista se desconoce.** Precision 1.0 sobre seis
   frases propias no es una metrica: es una prueba de comportamiento. `mention
   P/R/F1`, `claim P/R/F1`, `type accuracy`, `coreference F1` y `false candidates`
   los tiene que dar el benchmark con corpus **held-out**, no con estas fixtures.
2. **La cobertura sera baja y es una decision, no un accidente.** Las cinco
   guardas del §3.1 estan calibradas para no afirmar. Cuanto cuesta esa
   precision en cobertura es exactamente lo que hay que medir.
3. **El lexico de relaciones es corto y monolingue (es).** 14 reglas escritas a
   mano. Cada frase añadida es una apuesta de precision que el benchmark tendra
   que pagar; no se amplia "por si acaso".
4. **Ollama no esta caracterizado.** Cuatro ejecuciones sobre una frase no dicen
   nada de su P/R. Y con ~150 s por episodio, el coste de pasarlo por un corpus
   entero es un problema real de planificacion, no un detalle.
5. **La correferencia solo cubre pronombres personales y primera persona.**
   Posesivos, elipsis y correferencia entre episodios quedan fuera.
6. **Lo visual no existe.** `VISUAL_INFERRED` no se ha producido nunca porque no
   hay proveedor de vision. Cualquier metrica visual en el benchmark seria cero
   por construccion, no por calidad.
7. **Los mapeos de tabla son un catalogo corto de encabezados en castellano.**
   Una tabla con encabezados distintos produce `TABLE_COLUMN_NOT_MAPPED` y cero
   claims.
8. **El anclaje de celdas repetidas es heuristico**: si hay tantos fragmentos
   como filas se prueba primero el de esa fila; si no, dos filas con el mismo
   valor colapsan en la misma mencion.
9. **Las confianzas no estan calibradas.** Ninguna. Ni las del determinista, ni
   el tope de Ollama, ni el del externo. Son ordenes relativos, y hasta que el
   benchmark los mida no deben usarse como umbral de decision en ningun sitio.

---

## 8. Bloqueos

Ninguno de contrato: los contratos congelados cubrieron todo lo que el subsistema
necesitaba emitir y **no falto ni un campo**. La abstencion, la traza de
proveedor, `calendar_id`, `speaker`, `table` y `VISUAL_INFERRED` estaban todos.

Dependencias externas pendientes, por diseño:

- **subsistema de proveedores**: `ExternalProposalPort` esta esperando
  implementacion; hasta entonces el extractor externo devuelve vacio;
- **proveedor de vision**: `VisionPort` idem;
- **benchmark**: sin el, ninguna de las cifras de este documento debe leerse
  como calidad del sistema.
