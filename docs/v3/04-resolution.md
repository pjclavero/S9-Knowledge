# 04 — Subsistema C: resolución de identidad

**Rama:** `feat/v3-entity-resolution` · **Base:** `36439a2` (`v3-contracts-frozen-1.0.0`)
**Código:** `data-engine/app/knowledge_v3/resolution/`
**Pruebas:** `data-engine/app/tests/test_knowledge_v3_resolution*.py`
**Contrato de salida:** `entity-resolution/v3-internal-v1` (congelado, no modificado)

---

## 1. Qué hace y qué no hace

Convierte un **grupo de `EntityMention`** (menciones que el extractor ya ha
agrupado como correferentes) en **una `EntityResolution`**: la decisión de a qué
identidad corresponde ese grupo.

**Hace:**

- puntuar candidatos con una cascada de señales configurable;
- decidir entre `LINK_EXISTING`, `CREATE_NEW`, `CREATE_PROVISIONAL` y `REVIEW`;
- asignar identificadores deterministas a lo que crea;
- recordar lo decidido dentro de la sesión para que las menciones siguientes sean
  coherentes y baratas.

**No hace, deliberadamente:**

| No hace | Por qué |
|---|---|
| Escribir en Neo4j ni en ningún almacén | El catálogo **entra** por `EntityCatalog`; la salida es un documento que otro subsistema decidirá aplicar. |
| Agrupar o desagrupar menciones (`SPLIT`) | **Reservado**: lo emitirá el flujo de revisión humana en integración (decisión del organizador). Ni este resolutor ni el extractor lo emiten en esta ola, y **este resolutor lo rechaza si lo recibe** (`ingest_decision` lanza `ResolutionInputError`). Ver §10.1. |
| Tocar `review/resolver.py` (V1/V2) | Frontera intocable. Se lee como referencia; no se importa ni se modifica. |
| Llamar a proveedores externos o generar `timestamps` | La resolución es una función pura de sus entradas. |

---

## 2. Arquitectura de la cascada

```
                    ┌──────────────────────────────────────┐
  EntityMention[]   │  WORKSPACE  (filtro DURO, siempre)   │   EntityCatalog
        │           └──────────────────────────────────────┘   (solo lectura)
        ▼                            │
  ┌─────────────────────────────────────────────────────────────────┐
  │ GENERADORES  (orden configurable, cortocircuitables)            │
  │                                                                 │
  │   exact ─────► history ─────► alias ─────► glossary ─────► sim  │
  │   1.00         0.97           0.95         0.95 / 0.90    ≤0.88 │
  └─────────────────────────────────────────────────────────────────┘
                                   │
  ┌─────────────────────────────────────────────────────────────────┐
  │ MODIFICADORES (siempre, incluso si se cortocircuitó)            │
  │   context  +0.12        types  +0.03 / −0.35                    │
  └─────────────────────────────────────────────────────────────────┘
                                   │
  ┌─────────────────────────────────────────────────────────────────┐
  │ DECISIÓN (umbrales explícitos, desempate total)                 │
  │  LINK_EXISTING · CREATE_NEW · CREATE_PROVISIONAL · REVIEW       │
  └─────────────────────────────────────────────────────────────────┘
                                   │
                          EntityResolution
```

### 2.1. Señales generadoras

| Paso | Puntuación | `reason_code` | Qué mira |
|---|---|---|---|
| `exact` | 1.00 | `EXACT_NAME` | Nombre canónico normalizado idéntico. |
| `history` | 0.97 | `HISTORY_SESSION` | Identidad ya fijada en esta sesión para la misma superficie. |
| `alias` | 0.95 | `EXACT_ALIAS` | Alias declarado de la entidad. |
| `glossary` | 0.95 / 0.90 | `GLOSSARY_CANONICAL` / `GLOSSARY_VARIANT` | Término del glosario del workspace; forma escrita vs. forma hablada/errónea. |
| `similarity` | ≤ 0.88 | `SURFACE_SIMILARITY` | Parecido ortográfico de superficie. |

### 2.2. Modificadores

| Paso | Efecto | `reason_code` |
|---|---|---|
| `context` | +0.12 si la entidad ya está presente en el episodio/escena | `CONTEXT_SUPPORT` |
| `types` | +0.03 compatible · −0.35 en conflicto · sin efecto si algún lado no tipa | `TYPE_COMPATIBLE` / `TYPE_CONFLICT` / `TYPE_UNKNOWN` |

### 2.3. Por qué este orden y no el del prompt

El prompt maestro enumera las señales como
`exact → alias → glosario → embeddings → contexto → tipos → historial → workspace`.
Eso es el **catálogo de qué se mira**, no el orden de ejecución. Aquí:

- **`workspace` va primero**, no último: es un filtro duro sobre el universo de
  candidatos, no una señal que se pondera al final. Un candidato de otra bóveda
  no debe llegar a puntuarse *nunca*.
- **`history` va segundo**, justo detrás de `exact`: es la señal más barata
  (una consulta a un diccionario en memoria) y evita ejecutar glosario y
  similitud, que son las caras. No puede ir la primera porque **no debe pisar un
  match exacto**: si una decisión anterior fue equivocada, un nombre canónico
  idéntico debe seguir ganando. Hay test para eso
  (`test_el_historial_no_pisa_un_match_exacto`).
- **`context` y `types` van al final** porque no generan candidatos: ajustan los
  que ya hay. Se ejecutan siempre, incluso si un generador cortocircuitó.

El orden es configurable (`ResolutionConfig.step_order`), así que la decisión es
revisable y ablacionable, no un cableado.

### 2.4. Cortocircuito

**Desactivado por defecto** (`short_circuit = False`). Cuando se activa, un
generador corta la cascada si su mejor candidato alcanza `short_circuit_score`
(0.95) y es el único visto hasta ese punto.

**No es neutro, y decir lo contrario era falso** (H4 de la revisión
independiente; la versión anterior de este documento lo afirmaba). Cortar en el
paso *i* significa no ejecutar los pasos *i+1…n*, y ahí puede haber un segundo
candidato que habría activado la regla de ambigüedad. Caso concreto y probado en
`TestCortocircuito::test_cortar_convierte_una_ambiguedad_en_un_enlace`:

| | pasos ejecutados | decisión |
|---|---|---|
| `short_circuit=True` | `exact`, `history` | `LINK_EXISTING` a `entity:kaede-a` |
| `short_circuit=False` | los cinco | `REVIEW` (`AMBIGUOUS_CANDIDATES`) |

El historial puntúa 0.97 y corta antes de `alias`, donde esperaba
`entity:kaede-b` a 0.95: 0.02 de margen, muy por debajo de `ambiguity_margin`.

Con estos pesos **no existe ningún corte demostrablemente neutro**: la cota
superior de lo que un paso posterior puede alcanzar (0.97 del historial, o 0.95
de alias/glosario, más hasta 0.15 de bonus) siempre queda a menos de
`ambiguity_margin` del mejor candidato posible. No es un defecto del mecanismo:
es lo que dicen los pesos — que un alias es casi tan bueno como un nombre
exacto. Por eso el defecto es la variante conservadora: en un resolutor cuya
consigna es "ante la duda, `REVIEW`", el comportamiento por omisión no puede ser
el que convierte dudas en enlaces. Queda como palanca explícita de coste
(§9 mide el ahorro: 2 pasos en vez de 5).

### 2.5. Combinación y desempate

- La puntuación base de un candidato es el **máximo** de sus señales generadoras
  (no la suma: tres señales débiles no equivalen a una fuerte).
- Los modificadores son **aditivos** sobre esa base.
- El orden es **total**: `(−raw_score redondeado a 6 decimales, entity_id)`. El
  redondeo evita que el desempate dependa del último bit de un float; el
  `entity_id` garantiza que no queden empates sin romper.
- `raw_score` (sin recortar) es lo que se **compara**; `score` (recortado a
  `[0,1]`) es lo que se **reporta** como `confidence`. Si se ordenase por el
  recortado, 0.98 y 1.10 empatarían en 1.0 y el bonus que los separa se
  evaporaría contra el techo del contrato.

---

## 3. Umbrales y decisión

Todos en `ResolutionConfig`; ninguno cableado en un `if`.

| Parámetro | Defecto | Significado |
|---|---|---|
| `link_min_score` | 0.90 | A partir de aquí se puede enlazar. |
| `review_min_score` | 0.60 | Por debajo, el candidato ni siquiera merece un humano. |
| `ambiguity_margin` | 0.10 | Distancia mínima al segundo candidato. |
| `type_override_score` | 1.01 | Inalcanzable **porque se compara contra la puntuación recortada a [0,1]** (`score`), no contra `raw_score`, cuyo techo real es 1.15. Un conflicto de tipos siempre acaba en `REVIEW`. Existe para experimentar y para que las mutaciones tengan dónde morder. |
| `create_new_min_confidence` | 0.90 | Confianza mínima de la mención para acuñar un nodo canónico. |
| `create_new_max_rival_score` | 0.30 | Si algo del catálogo ya se le parece remotamente, no se acuña: se crea provisional. |
| `provisional_confidence_cap` | 0.50 | Techo de confianza de una provisional. |
| `history_min_confidence` | 0.40 | Por debajo del techo anterior, a propósito: una provisional **debe** poder alimentar el historial. |
| `short_circuit` | `False` | Palanca de coste, no neutra (§2.4). |

**Orden de las comprobaciones** (importa):

1. Sin candidatos → crear.
2. **Conflicto de tipos** en el mejor → `REVIEW`. Va *antes* del umbral de enlace
   porque un `Character` que puntúa 0.99 contra un `Location` no es un enlace
   bueno, es un enlace peligroso.
3. Puntuación < `review_min_score` → crear (`LOW_SUPPORT`).
4. Puntuación < `link_min_score` → `REVIEW` (`WEAK_MATCH`).
5. Margen con el segundo < `ambiguity_margin` → `REVIEW` (`AMBIGUOUS_CANDIDATES`).
6. `LINK_EXISTING`.

`CREATE_NEW` exige **todo a la vez**: tipo conocido, confianza ≥ 0.90, superficie
de ≥ 3 caracteres y ningún rival por encima de 0.30. Cualquier duda cae en
`CREATE_PROVISIONAL`, que es reversible; un nodo canónico fabricado a partir de
un error de ASR, no (dosier 10.4).

---

## 4. Las dos reglas duras

No son heurísticas ponderadas: son invariantes, y hay pruebas de mutación que lo
demuestran (§7).

### 4.1. Workspace

Un candidato de otra bóveda **jamás** entra en la cascada. La regla se aplica en
tres sitios independientes porque hay tres caminos por los que podría filtrarse:

- **catálogo**: `filter_workspace()` se aplica en `run_cascade` aunque el
  catálogo ya prometa filtrar. No es redundancia inútil — una garantía de
  aislamiento que depende de que alguien escribiera bien un `WHERE` no es una
  garantía. Hay test con un `LeakyCatalog` que devuelve todo.
- **glosario**: la clave del índice es `(workspace, superficie)`.
- **historial**: la clave del índice empieza por el workspace **y además** cada
  entrada devuelta pasa por `history_entry_allowed()`. Lo segundo se añadió tras
  la revisión independiente (H2): la clave protegía del uso normal, pero no de
  una entrada cuyo `workspace` no coincidiera con su clave ni de un `lookup` que
  ignorase el argumento — en ambos casos salía un `LINK_EXISTING` entre bóvedas.
  La cerradura comprueba dos cosas: que la entrada declare el workspace pedido y
  que el catálogo, **si puede responder** (`EntityCatalog.locate`), no atribuya
  esa entidad a otra bóveda. `locate` devolviendo `None` significa "no me
  consta" y no bloquea: una provisional recién creada no está en el catálogo y
  es legítima. Hay un `LeakyHistory` en las fixtures, hermano del
  `LeakyCatalog`, que ejercita el fallo.

Además, un grupo con menciones de dos workspaces es un `ResolutionInputError`:
elegir uno de los dos sería arbitrario.

### 4.2. Tipos

Una mención `Character` no se enlaza con una entidad `Location`. La regla tiene
**dos cerraduras**, y hace falta forzar las dos para abrirla:

1. la penalización (`type_conflict_penalty`, −0.35) hunde la puntuación por
   debajo del umbral de enlace;
2. el umbral de anulación (`type_override_score = 1.01`) manda a `REVIEW` antes
   incluso de mirar la puntuación.

Ablacionar el paso `types` quita el *bonus* y la penalización, no el invariante:
el conflicto se sigue detectando (`ScoredCandidate.type_conflict`) y sigue
mandando a `REVIEW`.

**Corrección de H1 (revisión independiente).** La versión anterior comparaba el
umbral contra `raw_score` — la puntuación *sin recortar*, cuyo techo real es
1.15, no 1.0 — y afirmaba en dos sitios que 1.01 era inalcanzable "porque las
puntuaciones viven en [0,1]". Era falso: con `disabled_steps={"types"}` (que
`__post_init__` **sí acepta**; también se afirmaba lo contrario) más
`context_entity_ids`, un candidato llegaba a 1.12, superaba el umbral y producía
`LINK_EXISTING` de una `Location` a una `Faction`, además reetiquetando
`entity_type` en silencio. La comparación usa ahora `score`, la magnitud
recortada, que es la única acotada. Cubierto por
`test_ablacionar_el_paso_de_tipos_no_abre_la_puerta`, reforzado para incluir el
bonus de contexto que lo destapaba, y por
`test_el_umbral_de_anulacion_se_compara_contra_una_magnitud_acotada`.

Compatibilidad: `None` es compatible con todo — no tipar no es afirmar nada —, y
dos tipos conocidos son compatibles solo si son el mismo. No hay jerarquía: el
catálogo congelado tiene seis tipos planos e inventar una ontología aquí sería
inventarla.

---

## 5. Identificadores deterministas

```
assigned_entity_id = prefijo + sha256(workspace \x1f superficie_normalizada \x1f tipo)[:16]
resolution_id      = "resolution:" + sha256(workspace \x1f mention_ids ordenados)[:16]
```

Los tres componentes del primero son necesarios:

- **workspace**: dos bóvedas pueden tener cada una su "Ilya" y no son la misma
  entidad;
- **superficie normalizada**: es la identidad observable de la que se parte;
- **tipo**: `Character` "Umbra" y `Location` "Umbra" son entidades distintas.

El separador `\x1f` no puede aparecer en ninguno de los tres, así que la
concatenación no es ambigua (`("ab","c")` ≠ `("a","bc")`; hay test).

Consecuencia práctica: **la misma entidad provisional recibe el mismo
identificador en dos pasadas sobre el mismo corpus**. Con un contador o un UUID,
el grafo dependería del número de veces que se ha ejecutado la ingesta y
cualquier medición sería ruido. `mention_ids` se ordena antes de mezclarlo
porque el mismo grupo en otro orden es el mismo grupo (`stable_id` del contrato
exige justamente eso).

---

## 6. Historial de sesión

`(workspace, superficie normalizada) → identidad fijada`.

- Solo memoriza acciones que **fijan** identidad (`LINK_EXISTING`, `CREATE_NEW`,
  `CREATE_PROVISIONAL`). `REVIEW` y `SPLIT` no: memorizar una duda la convertiría
  en precedente.
- Ante colisión gana la de **mayor confianza**, no la última: si ganase la
  última, el resultado dependería del orden de recorrido del corpus.
- **No comprueba tipos al leer**: el historial informa, el paso de tipos decide.
  Si "Umbra" quedó ligada a una `Faction` y ahora llega como `Location`, queremos
  ver el conflicto y mandarlo a `REVIEW`, no que el historial lo esconda.
- Invalidación: por superficie, por entidad (todas sus superficies), por
  resolución (rollback puntual), por workspace y total.
- **No se persiste.** Persistirlo arrastraría decisiones sin revisar de una
  ingesta a la siguiente, que es el fallo que `CREATE_PROVISIONAL` intenta evitar.

- **La identidad se hereda; la certeza, no.** `history_score` es plano (0.97):
  da lo mismo al eco de un `LINK_EXISTING` de 0.99 que al de una provisional de
  0.45. Si la `confidence` emitida saliera de ahí, una duda se leería como una
  certeza. Por eso, cuando **toda** la evidencia de un candidato es historial, la
  confianza reportada se rebaja a la de la decisión original y se marca con
  `INHERITED_CONFIDENCE`. Si además el nombre exacto coincide, no hay nada que
  heredar y no se rebaja nada.
- **`FROM_HISTORY`** marca los candidatos cuya identidad el catálogo del
  workspace no conoce (típicamente, provisionales de esta misma sesión), y la
  `metadata` del documento lleva `inherited_confidence` por candidato.

Efecto medido sobre el coste: con `short_circuit=True`, la segunda mención de la
misma superficie recorre 2 pasos en vez de 5
(`test_el_historial_abarata_la_cascada_solo_con_cortocircuito`). Con la
configuración por defecto el ahorro **no existe**: se recorre la cascada entera
para no cambiar decisiones (§2.4).

---

## 7. Embeddings y similitud

La interfaz es `SurfaceSimilarity.score(a, b) → [0,1]`.

**Implementación por defecto** (`TrigramJaccardSimilarity`), sin dependencias
pesadas: distancia de edición (peso 0.75) + Jaccard de trigramas de caracteres
(0.25), y por otro lado Jaccard de tokens; se toma el máximo de las dos vías.

- la **edición** ve la errata de una letra (`Tamori`/`Tamory`);
- los **trigramas** penalizan transposiciones que la edición trata con
  indulgencia;
- los **tokens** rescatan reordenamientos (`Familia Tamori`/`Tamori Familia`).

**Límite honesto, medido en los tests y no solo escrito aquí:** esto no es
semántica. `"el magistrado"` y `"Daiki"` puntúan por debajo del mínimo para ser
candidatos, pese a ser alias real uno del otro. Y `similarity_weight` (0.88) está
por debajo de `link_min_score` (0.90): **esta señal sola nunca enlaza**, como
mucho manda a revisión. Las variantes de ASR muy deformadas son trabajo del
glosario (`error_forms`), no de este paso.

**Matiz importante y medido** (señalado por la revisión independiente): que la
similitud *sola* no enlace no significa que no pueda enlazar **acompañada**.
`"Kobayashy Ryu"` contra `"Kobayashi Ryu"` puntúa 0.756 de base — `REVIEW` con
0.786 tras el bonus de tipo —, pero si la entidad ya está en el contexto del
episodio el bonus de contexto lo sube a **0.906** y enlaza. Es el
comportamiento pretendido (dos señales independientes valen más que una) y está
cubierto por `test_similitud_mas_contexto_si_puede_enlazar`, pero conviene no
leer "nunca enlaza sola" como "nunca enlaza".

**Enganche para embeddings reales:** `EmbeddingSimilarity` sí está implementada
(coseno con caché) sobre un `EmbeddingProvider` **abstracto**. Aquí no se entrega
ningún proveedor concreto: lo aporta el subsistema de proveedores. Enchufarlo es
cambiar un argumento del constructor, sin tocar la cascada. La única exigencia:
`embed` debe ser determinista para el mismo texto y modelo, o dos pasadas sobre
el mismo corpus darán grafos distintos.

---

## 8. Enganches declarados y no implementados

Se declaran la frontera y los requisitos; **no** se entrega código que nadie ha
podido ejecutar aquí. Ambos lanzan `NotImplementedError` con el motivo.

| Enganche | Por qué no se implementa | Qué debe cumplir |
|---|---|---|
| `Neo4jEntityCatalog` | No hay acceso a un Neo4j con datos reales desde esta rama; una implementación no ejecutada es una implementación no verificada. | `workspace` siempre en el `WHERE`; solo `MATCH`/`RETURN`; si el driver cae, **propagar** — degradar a "sin candidatos" convertiría una caída en una avalancha de entidades nuevas. |
| `GlossaryStoreSource` | El store real vive en un SQLite fuera del repo (`state/glossary.db`, gitignored) que ya causó una divergencia de medición documentada en `00-audit-current-system.md`. | Mapear `GlossaryStore.search_terms(workspace=…)` (solo lectura) a `InMemoryGlossarySource.add` y cachear por workspace. |

---

## 9. Pruebas

| Fichero | Contenido | Tests |
|---|---|---|
| `test_knowledge_v3_resolution_fixtures.py` | Corpus a mano: homónimos entre bóvedas, nombres casi idénticos, alias compartido, colisión de tipos, formas erróneas de ASR, `LeakyCatalog`. Sin tests. | — |
| `test_knowledge_v3_resolution.py` | Normalización, similitud, catálogo, glosario, identificadores, historial, configuración, cascada, workspace, tipos, estabilidad entre pasadas, contrato emitido, ablaciones, cortocircuito (§2.4), confianza heredada (§6), colisión de id derivado, `SPLIT` reservado. | 117 |
| `test_knowledge_v3_resolution_mutations.py` | Mutación de las reglas duras. | 25 |

**Total: 142.** Suite completa del repositorio tras el cambio (los `testpaths`
de `pytest.ini` al completo, `tests/e2e` incluido): **4316 pasan, 5 se saltan,
0 fallan**. Sin regresiones: el cambio solo añade ficheros; no se ha tocado
`ci.yml`, `pytest.ini`, `contracts/` ni ningún módulo de V1/V2.

### Pruebas de mutación

Un test que pasa no demuestra que la regla que dice comprobar sea la que sostiene
el resultado. Estas lo demuestran al revés: rompen la regla y exigen que la
comprobación se ponga **roja**.

| Mutación | Comprobación que debe romperse |
|---|---|
| `filter_workspace` deja de filtrar | El homónimo de otra bóveda entra como candidato. |
| `history_entry_allowed` deja pasar todo | Un `LeakyHistory` produce `LINK_EXISTING` a una entidad de otra bóveda. |
| El glosario ignora el workspace | Una forma errónea de `leyenda` explica una superficie de `tinieblas`. |
| El historial ignora el workspace | Una decisión de otra bóveda condiciona a esta. |
| `types_compatible` dice que todo es compatible | Un `Location` se enlaza a una `Faction`. |
| `type_override_score = 0` **y** `type_conflict_penalty = 0` | Reaparece el enlace peligroso (demuestra que hacen falta las dos cerraduras). |
| Identificador derivado no determinista | Las provisionales dejan de ser estables entre pasadas. |
| Se quita el workspace del hash del identificador | Dos bóvedas colisionan en la misma provisional. |
| `ambiguity_margin = 0` | El empate se resuelve "a dedo" en vez de ir a `REVIEW`. |

Se comprueba además que la mutación de workspace **no** rompe las
comprobaciones de tipos ni de determinismo: si una mutación rompiera todo, no
estaría midiendo la regla sino el ruido.

---

## 10. Límites conocidos

1. **`SPLIT`: reservado.** Lo emitirá el flujo de revisión humana en
   integración; este resolutor no lo emite y **lo rechaza si lo recibe**
   (`EntityResolver.ingest_decision` lanza `ResolutionInputError`). El motivo no
   es sólo de reparto de trabajo: un `SPLIT` reparte las menciones en varios
   grupos, y este historial indexa **una** identidad por superficie, así que
   aceptarlo sería fingir que se sabe qué hacer con él.
2. **Sin embeddings reales, no hay señal semántica.** La cascada resuelve alias,
   glosario y erratas ortográficas; no resuelve descripciones (`"el magistrado"`
   sin alias declarado) ni correferencia pronominal. Eso llega por
   `coreference_candidates` del extractor o por un proveedor de embeddings.
3. **`Neo4jEntityCatalog` sin implementar** (§8): hasta que exista, el
   subsistema solo funciona contra catálogos en memoria.
4. **Nada de esto está medido sobre corpus real.** No hay aquí ningún número de
   precisión o cobertura, y no lo habrá hasta ejecutarlo contra H1/H2 —
   pendiente por el acceso al corpus reservado (`00-audit-current-system.md`, D7
   y R3). Los tests demuestran **comportamiento**, no **rendimiento**. Los
   umbrales por defecto son juicios de diseño conservadores, no valores
   calibrados; calibrarlos es trabajo del bloque de benchmarks.
5. **El historial no sobrevive al proceso** (§6), por diseño.
6. **La agregación de tipos** suma confianzas entre menciones del grupo. Con
   grupos grandes y muy heterogéneos puede imponer un tipo mayoritario sobre uno
   minoritario correcto; el conflicto resultante acaba en `REVIEW`, que es el
   comportamiento seguro, pero es una fuente conocida de revisiones evitables.
7. **H3 — el `history_score` es plano.** Mitigado (§6: la confianza se rebaja a
   la original y se marca con `INHERITED_CONFIDENCE`), no eliminado: el
   *ranking* sigue usando 0.97 para cualquier eco, así que una provisional
   dudosa compite igual de fuerte que un enlace sólido a la hora de ganar la
   posición. Rebajar también el ranking rompería el objetivo del historial —
   una provisional de 0.45 dejaría de recuperarse a sí misma— y la alternativa
   correcta (ponderar el eco por la confianza original y recalibrar los
   umbrales) necesita medición sobre corpus real antes de tocarse.
8. **H6 — comparar por `raw_score` es menos conservador en la esquina
   saturada.** El orden y los márgenes se calculan sin recortar (§2.5), lo que
   es necesario para que un bonus no se evapore contra el techo; el efecto
   colateral es que dos candidatos que *reportan* 1.00 pueden tener márgenes
   reales de 0.15 y no activar la regla de ambigüedad. Es deliberado, pero
   significa que "ambos al máximo" no implica "ambiguo". Los invariantes no
   dependen de esto: el de tipos se comprueba contra la magnitud **recortada**
   precisamente por eso (§4.2).
9. **H7 — un error de correferencia se propaga.** Si el extractor agrupa mal dos
   menciones, el historial convierte ese error en el precedente de todas las
   menciones siguientes de esa superficie en el corpus. El subsistema no puede
   detectarlo (no revisa la agrupación, §1) y sólo lo hace **visible**:
   `FROM_HISTORY` en `reason_codes` e `inherited_confidence` en la `metadata`
   permiten reconstruir la cadena y `ResolutionHistory.invalidate_entity` /
   `invalidate_resolution` permiten cortarla. Es contención, no solución: la
   solución es la revisión humana en integración.

---

## 11. Bloqueos de contrato

**Ninguno.** El contrato congelado `entity-resolution/v3-internal-v1` ha bastado
para todo lo implementado: no ha hecho falta ningún campo que no existiera, y no
se ha añadido ni modificado nada en `contracts/`.

Dos puntos donde el contrato **obliga** y el resolutor obedece en vez de
apañarlo:

- `evidence` exige `minItems: 1`. Si las menciones no aportan
  `evidence_fragment_ids`, se lanza `ResolutionInputError` en lugar de fabricar
  un fragmento. Es un bloqueo de **entrada**, no de contrato.
- `assigned_entity_id` no puede coincidir con ningún `candidate_entity_id`. Si el
  identificador derivado colisionase con un candidato (no se estaría creando
  nada), la decisión se degrada a `REVIEW` con `PROVISIONAL_ID_COLLISION` en vez
  de emitir un documento que el validador rechazaría.
