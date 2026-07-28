# 10 — Split held-out (equipo independiente)

> Este documento y el directorio
> `data-engine/app/knowledge_v3/benchmarks/datasets/heldout/` son obra del
> **equipo independiente** del programa V3 (dosier §9). Quien implementó el
> extractor, el motor o la resolución no ha escrito ni una línea de este gold.
>
> La razón es un precedente concreto: el motor de relaciones v2 marcó **0.81**
> en un conjunto donde *dev == test* y **0.24** sobre material real. Nadie hizo
> entonces el trabajo que hace este split. Una cifra de `dev` en la columna de
> held-out del informe final (dosier §14) es exactamente ese error.

---

## 1. Qué es y cómo se instala

Un split hermano de `dev`, con la estructura de `docs/v3/08-benchmarks.md` §2.3
y §7. No hace falta tocar el arnés: es una copia de directorio.

```bash
# validar el gold contra los contratos congelados
python -m knowledge_v3.benchmarks.cli validate --split heldout
# medir
python -m knowledge_v3.benchmarks.cli ... --split heldout
```

Toda defensa de split está puesta: cada **fichero** declara `"split": "heldout"`
y cada **documento** lleva `metadata.benchmark.split = "heldout"`. El loader
comprueba las dos. Un bundle de predicciones que declare `dev` contra este gold
lanza.

El workspace es `bench-heldout` (el de `dev` es `bench-dev`): dos splits nunca
comparten bóveda ni por accidente.

### 1.1 Regeneración

El gold está versionado, pero se **genera**:

```bash
python3 data-engine/app/knowledge_v3/benchmarks/datasets/heldout/_authoring/build_heldout.py
python3 .../build_heldout.py --check     # ¿ha derivado?
```

Los textos y la anotación están escritos a mano; los **offsets, hashes y sobres
se calculan**. `_authoring/` es maquinaria propia: no importa
`benchmarks/authoring/` para no heredar por accidente ninguna constante de `dev`
(workspace, marca de split, catálogo). Lo único que comparte con `dev` es lo que
debe compartir: los contratos congelados y su validador.

---

## 2. Composición

3 mundos nuevos · 7 fuentes · 6 tipos de fuente · 6 modalidades.

| Fuente | Mundo | Tipo / modalidad | Ep. | Menc. | Claims | Afirm. | Neg. | Fenómenos |
|---|---|---|---:|---:|---:|---:|---:|---|
| `ferrovia-memoria` | ferrovia | MARKDOWN / TEXT | 3 | 16 | 7 | 7 | 4 | CONFLICT, COORDINATION_MISPAIR, COREFERENCE, EVENT_LOCATION, MODIFIER_MISPAIR, NEGATION, NEGATION_AT_DISTANCE, SUPERSESSION, SYMMETRIC, TEMPORALITY |
| `ferrovia-cartas` | ferrovia | TEXT / TEXT (epistolar) | 3 | 13 | 3 | 3 | 1 | ALTERNATIVE_READING, CONFLICT, DENIED_RUMOR, INVERSE_PREDICATE, NEGATION, RUMOR, SYMMETRIC |
| `ferrovia-tabla` | ferrovia | TABLE / TABLE | 1 | 8 | 4 | 2 | 0 | DUPLICATE_ACROSS_SOURCES, NEW_ENTITY, TABLE |
| `micelio-wiki` | micelio | WEB / TEXT (ficha wiki) | 3 | 19 | 10 | 9 | 3 | COREFERENCE, FICTION_WITHIN_FICTION, HYPOTHETICAL, INVERSE_PREDICATE, MODIFIER_MISPAIR, NEGATION, ONTOLOGY_VIOLATION, QUESTION, SYMMETRIC, TEMPORALITY, TRANSITIVE |
| `micelio-escaneo` | micelio | IMAGE / OCR_TEXT + DIAGRAM | 3 | 6 | 3 | 0 | 0 | ABSTENTION, DUPLICATE_ACROSS_SOURCES, OCR_NOISE, PROVISIONAL_ENTITY, VISUAL_INFERRED |
| `liga-mesa` | liga | AUDIO / SPEAKER_TURN | 3 | 11 | 5 | 5 | 1 | COREFERENCE, COUNTERFACTUAL, RUMOR, SPEAKER_COREFERENCE, SYMMETRIC, TEMPORALITY |
| `liga-audio-crudo` | liga | AUDIO / ASR_TEXT | 2 | 7 | 4 | 4 | 2 | ASR_NOISE, COORDINATION_MISPAIR, COREFERENCE, HYPOTHETICAL, SYMMETRIC |

**Totales**: 18 episodios · 115 fragmentos · 80 menciones · 42 resoluciones ·
36 claims (35 exigibles al extractor, 1 `ENGINE_ONLY`) · 30 afirmaciones ·
7 planes (6 aprobados, 1 bloqueado) · 36 decisiones · 34 operaciones ·
11 casos negativos · 330 documentos de contrato.

### 2.1 Los mundos

| Mundo | Género | Por qué |
|---|---|---|
| `ferrovia` | Histórico-industrial: vía estrecha de montaña, concesiones, túneles (s. XIX) | Nada que ver con corte medieval, archipiélago marinero ni estación orbital |
| `micelio` | Biopunk subterráneo: hermandades de cultivo, cámaras, cónclaves | Vocabulario de galerías y esporas; ni un término de `dev` |
| `liga` | Deporte contemporáneo: clubes de pelota, canchones, traspasos | Registro coloquial y hablado, muy lejos del de crónica o informe |

Vocabulario **disjunto** de `dev`: ningún nombre propio, facción, lugar ni
objeto de `leyenda`/`mareas`/`kestrel` aparece aquí, y la redacción es propia
(no se ha reutilizado ninguna formulación de `dev`).

Lo único deliberadamente **compartido** con `dev` son los **diez predicados** de
la ontología (`MEMBER_OF`, `HAS_MEMBER`, `LEADS`, `LED_BY`, `LOCATED_IN`,
`ALLY_OF`, `RIVAL_OF`, `SIBLING_OF`, `OWNS`, `OWNED_BY`). El predicado canónico
es la frontera de contrato contra la que se mide, no contenido del split:
cambiarlo mediría otra tarea. Todo lo demás del perfil (alias, títulos,
facciones, calendarios, términos ambiguos, reglas de identidad, ejemplos) es
nuevo. Se incluye también un `game_profile_narrow` para la ablación de perfil
incorrecto, con el mismo criterio que `dev`.

---

## 3. Fenómenos cubiertos

### 3.1 Exigidos por el dosier §9

| Fenómeno | Dónde | Forma concreta |
|---|---|---|
| Ficción dentro de la ficción | `micelio-wiki` e03 | "En la pantomima… el Cónclave devora la Cámara Honda" |
| Contrafactual | `liga-mesa` e03 | "Si el Rompiente hubiera pagado la cláusula, yo estaría hoy en su plantilla" |
| Pregunta | `micelio-wiki` e02 | "¿Llegó Sabel Onraita a presidir el Cónclave Lívido?" |
| Rumor **desmentido** | `ferrovia-cartas` e02 | "Se dijo… ; el libro de inventario lo desmiente" |
| Temporalidad con cambios históricos | `ferrovia-memoria` e01 | tres direcciones fechadas (1893 / 1897 / 1901) |
| Supersesión **encadenada** | `ferrovia-memoria` | `maren-leads-norte` → `iker-leads-norte` → `nerea-leads-norte` (2 eslabones) |
| Correferencia por pronombre | `ferrovia-memoria` e01 ("la"), `micelio-wiki` e03 ("ella") | |
| Correferencia nominal | "la Compañía", "la Hermandad", "Nuestro club", "el equipo" | |
| Primera persona con **dos** hablantes | `liga-mesa` e01/e02/e03 | el mismo "Yo" designa a Vero (turnos 0 y 2) y a Hektor (turno 1) |
| Simétricas | `SIBLING_OF` ×3, `RIVAL_OF` ×2, `ALLY_OF` ×1, todas `UNDIRECTED` | |
| Inversas | `OWNS` / `OWNED_BY` y `MEMBER_OF` / `HAS_MEMBER`, ambos lados usados | |
| Negación | 3 claims y 3 afirmaciones con `negated=true` | |
| Negación **a distancia** | `ferrovia-memoria` e02 | "no reconoció ninguna de las peticiones… **ni siquiera** la que firmaba…" |
| Epistemicidad | claims: `ASSERTED`, `RUMORED`, `HYPOTHETICAL`, `VISUAL_INFERRED`, `UNKNOWN`; afirmaciones: `ASSERTED`, `RUMORED`, `HYPOTHETICAL`, `CONFLICTED` | |
| Conflicto entre fuentes, **los dos signos** | `ferrovia-memoria` e03 (`negated=false`) vs `ferrovia-cartas` e03 (`negated=true`), ambos `CONFLICTED` / `CONTRADICTED` | |
| Entidad provisional | `micelio-escaneo` e02 | `0nra1ta`, compatible con **dos** Onraita del catálogo → `CREATE_PROVISIONAL` |
| Duplicado entre fuentes (`NO_OP`) | 3 operaciones: `ferrovia-tabla` ×2, `micelio-escaneo` ×1 | |
| **Coordinación** (novedad frente a `dev`) | `ferrovia-memoria` e03 ×2, `liga-audio-crudo` e01 ×2 | |
| **Sujeto-modificador** (novedad) | `ferrovia-memoria` e02, `micelio-wiki` e03 | |

Otros que el split trae además: `ABSTENTION`, `ONTOLOGY_VIOLATION`,
`NEW_ENTITY`, `TRANSITIVE`, `EVENT_LOCATION`, `ALTERNATIVE_READING`.

### 3.2 Degradación de señal

- **OCR** (`micelio-escaneo`, con `reference_text` corregido a mano):
  `m → rn` ("Cá**rn**ara", "confi**rrn**a", "**rn**argen"), `l → 1` ("**1**a"),
  `O → 0` e `i → 1` ("**0**nra**1**ta"), pérdida de tildes. La diferencia con la
  referencia es de 1–2 caracteres: degrada de verdad sin volverse ilegible.
- **ASR** (`liga-audio-crudo`, con `reference_text`): confusiones fonéticas
  ("también" → "tan bien", "hermana" → "ermana", "viene" → "biene", "fichó" →
  "ficho"), minúsculas y **sin puntuación**.

### 3.3 Los dos fenómenos nuevos, y por qué necesitaron anotación nueva

`dev` anota las trampas como **tramos** (`must_not_produce: "CLAIM"`): un span
que no debe producir ningún claim. Con la coordinación y el sujeto-modificador
esa forma no sirve, y por una razón dura:

> el tramo que contiene el par **equivocado** contiene también las menciones del
> par **correcto**. Prohibir el tramo prohibiría el claim bueno.

En "Nerea ingresó en la Compañía del Norte **y también** Iker ingresó en
Trasandina Unida", lo que está prohibido no es un trozo de texto: es **unir esas
dos menciones**. Por eso el held-out añade una segunda forma de negativo:

```json
{"must_not_produce": "CLAIM_FOR_PAIR",
 "forbidden_subject_mentions": ["mention:…"],
 "forbidden_object_mentions": ["mention:…"],
 "forbidden_predicates": ["MEMBER_OF"]}
```

Los negativos de tramo conservan `must_not_produce: "CLAIM"` y la regla de
`dev`: ningún claim gold pisa ninguno (verificado). Los de par añaden la suya:
ningún claim gold une un par prohibido, y ninguna afirmación gold registra ese
par con un predicado prohibido (verificado en los dos niveles, mención y
entidad).

Tipos de negativo presentes: `FICTION_WITHIN_FICTION`, `QUESTION`,
`COUNTERFACTUAL`, `DENIED_RUMOR`, `EVENT_LOCATION`, `COORDINATION_MISPAIR` (×4),
`MODIFIER_MISPAIR` (×2).

### 3.4 Rumor vivo ≠ rumor desmentido

`docs/v3/08-benchmarks.md` §2.2 separa rumor de caso negativo. El held-out
afila la distinción, porque no es la misma:

- **rumor vivo** ("Corre por los talleres que…", "Corre el rumor de que…") →
  **sí** produce claim, con `RUMORED`, y la afirmación nace `PROVISIONAL`;
- **rumor desmentido en su propia fuente** ("Se dijo… ; el libro lo desmiente")
  → **ningún** claim. Registrar como rumor algo que la fuente ya refutó no es
  conservar información: es conservar ruido con etiqueta de información.

Ambos casos están, y en el mismo mundo, para que no se puedan distinguir por el
contexto léxico.

### 3.5 Política de anotación de menciones

Se sigue §2.1.1 de `08-benchmarks.md`: se anota toda expresión que designa una
entidad **identificable del catálogo** (nombre propio, nominal definido
correferente, pronombre correferente, "Yo" del hablante) y **no** se anotan los
sustantivos de rol sin referente resoluble ("los cultivadores", "el libro de
inventario", "el expediente de concesión", "la cantina").

Dos decisiones propias del held-out, ambas deliberadas y verificadas:

1. **Menciones anidadas.** "el hermano de Nerea Lasalde" es una mención
   (→ Iker) y "Nerea Lasalde" dentro de ella es **otra** (→ Nerea). Sin la
   segunda no se puede anotar la trampa de sujeto-modificador; sin la primera no
   hay sujeto que resolver.
2. **Resolución por parentesco.** "el hermano de Nerea Lasalde" y "La hermana de
   Sabel Onraita" se resuelven a Iker y a Leire con
   `reason_codes: ["KINSHIP_INFERENCE"]` y confianza rebajada (0.78 / 0.82). Es
   un caso legítimamente difícil: exige el hecho `SIBLING_OF`, que el propio
   split establece.

---

## 4. Qué corrigió el segundo pase

El dataset se construyó, se cerró, y **después** se recorrió entero con ojos de
auditor: barrido automático de cada alias del catálogo sobre cada episodio en
busca de menciones sin anotar, lectura episodio a episodio buscando claims
omitidos, y revisión de qué campos del contrato el gold no estaba ejercitando
nunca. El segundo pase encontró cinco cosas y las cinco se corrigieron.

| # | Hallazgo | Corrección |
|---|---|---|
| 1 | **Menciones sin anotar.** Las tres cartas empiezan por "Portazgo, 14 de marzo de 1899". *Portazgo* designa la `Estación de Portazgo`, entidad del catálogo, y el primer pase la había descartado como "lugar de emisión". Es el mismo error que la revisión de `dev` detectó con "Umbra": dejarla sin anotar convierte en **acierto** que un extractor la ignore y en **falso positivo** que la detecte bien. | 3 menciones nuevas + su resolución (`LETTERHEAD_PLACE`). |
| 2 | **Ambigüedad sin decidir.** "Los dos hermanos discutieron el reparto **en la Estación de Portazgo**": la mención estaba anotada y ningún claim la usaba, así que el gold no decía si `LOCATED_IN` era correcto o no. Un extractor razonable lo emitiría, y el gold no podía puntuarlo. | Negativo nuevo `EVENT_LOCATION`: la sede de un evento puntual no es una ubicación persistente de sus participantes. |
| 3 | **Lecturas alternativas descartadas en silencio.** Ningún claim usaba `alternatives`, campo que el contrato tiene precisamente para no perder la segunda lectura. "se han repartido la concesión del Túnel" admite `ALLY_OF` y `OWNS`; "la locomotora pertenece a Trasandina" admite `OWNED_BY` y `OWNS` invertido. | `alternatives` en 2 claims, con `reason_codes`. De paso aparece la única `OBJECT_TO_SUBJECT` del split (§5). |
| 4 | **Información de la tabla tirada.** La columna `Turno` (noche/día) del libro de socios no llegaba a ningún sitio: el gold la leía y la perdía. | `qualifiers` `{turno: …}` en los 4 claims de la tabla. |
| 5 | **Expresión temporal no anotada.** "llevan **tres temporadas** enfrentados" es una duración explícita y el claim no la registraba; `DURATION` no aparecía en todo el split. | `temporal_expressions` con `kind: DURATION`. |

Nota metodológica, por si sirve al siguiente: **el segundo pase encontró cosas
que el primero no podía encontrar leyendo lo escrito**, porque tres de los cinco
hallazgos (1, 3, 4) salieron de preguntar *qué falta* — barrido de alias, barrido
de campos del contrato sin usar — y no de releer *qué hay*. Releer lo escrito
tiende a confirmarlo.

Lo que el segundo pase revisó y **no** cambió, para que conste:

- offsets: los 115 fragmentos, las 80 menciones y los 11 negativos se
  comprueban carácter a carácter contra el texto del episodio (`text[start:end]
  == literal`) y ninguno estaba desviado — se calculan, no se escriben;
- negativos triviales: se comprobó que ninguna trampa se detecta por una pista
  léxica que no exista también en un caso positivo del mismo mundo (rumor vivo
  vs rumor desmentido, coordinación correcta vs cruzada, pasado verbal que sí
  cierra vigencia — "dejé el Club Aldabra" → `ENDED` — frente a pasado verbal
  que no la cierra — "ingresó en la Compañía del Norte" → `ACTIVE`);
- etiquetas discutibles que se mantienen con su motivo escrito: `OWNS` para
  "explotar el Túnel" (concesión de explotación, no propiedad plena) y
  `LOCATED_IN` para "entreno en el Canchón" (adscripción, no presencia
  instantánea).

---

## 5. Límites conocidos de este split

Honestos y por delante, porque un límite callado es una trampa:

1. **Sigue siendo pequeño.** 30 afirmaciones, 36 claims, 11 negativos. Sirve
   para detectar que algo generaliza mal, **no** para estimar rendimiento. La
   supersesión encadenada tiene n = 1 cadena; el conflicto de dos signos, n = 1.
   Un intervalo de confianza sobre estos números no significa nada.
2. **Sigue siendo de autoría propia.** Mundos inventados. Es material *nuevo*
   para quien implementa, que es justo lo que se necesitaba, pero **no** es
   material real. No sustituye a la columna "V3 real" del informe.
3. **`OBJECT_TO_SUBJECT` solo aparece como lectura alternativa**, no como
   dirección elegida de ningún claim gold: las frases de estas siete fuentes son
   de sujeto inicial o simétricas. Fabricar una inversión forzada habría medido
   la fabricación, no la dirección.
4. **`UNKNOWN` epistémico** aparece una sola vez (la abstención del OCR), y
   `status` `LIMITED` y `RETRACTED` no aparecen: no había caso natural.
5. **La resolución por parentesco es exigente.** Dos menciones (`el hermano
   de…`, `La hermana de…`) requieren encadenar un `SIBLING_OF` del propio split.
   Un resolutor que las mande a revisión no está *equivocado*; está siendo
   prudente. Si esa métrica sale baja, léase junto a la de abstención.
6. **El held-out no está enganchado a ningún flujo automático.** El único test
   que lo toca comprueba que carga, valida, no duplica claves de hecho y cuadra
   con su manifiesto. Medir con él es una decisión de quien coordina.

---

## 6. Declaración de independencia

**Leído** para construir este split:

- `contracts/knowledge-v3/v1/` — los nueve schemas congelados y `validator.py`.
  El gold valida contra ese validador, no contra una copia.
- La **estructura** de `datasets/dev/` (nombres de fichero, forma del sobre, del
  manifiesto y del catálogo) y `benchmarks/loader.py`, `matching.py`,
  `harness.py` — para que el split cargue y se mida sin tocar el arnés.
- `docs/v3/08-benchmarks.md` (§2.1.1 política de anotación, §2.2 rumor vs
  negativo, §2.3 estructura en disco, §2.4 anclaje de tabla, §3.6 schemas
  propios, §3.7 `ENGINE_ONLY`, §7 procedimiento de held-out) y
  `docs/v3/01-contracts-v3.md`.

**NO leído**, a propósito, para que este gold no esté moldeado ni a favor ni en
contra de las reglas de los subsistemas:

- `data-engine/app/knowledge_v3/extraction/` — léxicos, reglas y prompts de los
  extractores;
- `data-engine/app/knowledge_v3/engine/` — motor local de decisión;
- `data-engine/app/knowledge_v3/resolution/` — resolutor de identidad.

Tampoco se ha copiado ninguna frase, nombre ni giro de las fuentes de `dev`: los
mundos, el vocabulario y la redacción son nuevos.

Consecuencia práctica y esperada: es **posible** que algún fenómeno de este
split no lo cubra ningún subsistema. Eso no es un defecto del split. Es la
información que el split existe para producir.

---

## 7. Aviso al coordinador: dos tests de `dev` se ponen rojos

Instalar el split held-out hace fallar **dos aserciones ajenas** que cablean la
lista de splits — el fichero que las contiene no es propiedad de este equipo y
no se ha tocado:

| Test | Aserción | Corrección de una línea |
|---|---|---|
| `tests/test_knowledge_v3_benchmarks_dataset.py::test_el_arnes_no_cablea_el_nombre_del_split` | `available_splits() == ["dev"]` y `load_gold("heldout")` lanza | `assert "dev" in available_splits()` y quitar el bloque `pytest.raises` (o comprobar que `load_gold("heldout").split == "heldout"`) |
| `tests/test_knowledge_v3_benchmarks_harness.py::test_cli_lista_splits_y_ablaciones` | la salida de `cli splits` es exactamente `"dev"` | comparar contra el conjunto de líneas y exigir que contenga `dev` |

Merece una nota: el primero se llama *"el arnés no cablea el nombre del split"*
y era, él mismo, el único sitio del repositorio que cableaba la lista de splits.
El arnés no lo hacía; su test sí.
