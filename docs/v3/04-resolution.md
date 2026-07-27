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
| Agrupar o desagrupar menciones (`SPLIT`) | La correferencia es del extractor. El contrato admite `SPLIT`, pero emitir uno que nadie ha calculado sería inventarlo. Ver §8. |
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
  │ MODIFICADORES (siempre, incluso tras cortocircuito)             │
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

Un generador corta la cascada si su mejor candidato alcanza
`short_circuit_score` (0.95) **y es el único candidato**. Con dos candidatos por
encima del umbral no se corta: seguir mirando es precisamente lo que puede
deshacer el empate. El cortocircuito es una optimización de **coste**, nunca de
resultado, y hay un test que compara la decisión con y sin él
(`test_sin_cortocircuito_el_resultado_no_cambia`).

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
| `type_override_score` | 1.01 | **Inalcanzable por diseño**: un conflicto de tipos siempre acaba en `REVIEW`. Existe para experimentar y para que las mutaciones tengan dónde morder. |
| `create_new_min_confidence` | 0.90 | Confianza mínima de la mención para acuñar un nodo canónico. |
| `create_new_max_rival_score` | 0.30 | Si algo del catálogo ya se le parece remotamente, no se acuña: se crea provisional. |
| `provisional_confidence_cap` | 0.50 | Techo de confianza de una provisional. |
| `history_min_confidence` | 0.40 | Por debajo del techo anterior, a propósito: una provisional **debe** poder alimentar el historial. |

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
- **historial**: la clave del índice **empieza** por el workspace; no es un
  filtro posterior que se pueda olvidar.

Además, un grupo con menciones de dos workspaces es un `ResolutionInputError`:
elegir uno de los dos sería arbitrario.

### 4.2. Tipos

Una mención `Character` no se enlaza con una entidad `Location`. La regla tiene
**dos cerraduras**, y hace falta forzar las dos para abrirla:

1. la penalización (`type_conflict_penalty`, −0.35) hunde la puntuación por
   debajo del umbral de enlace;
2. el umbral de anulación (`type_override_score = 1.01`, inalcanzable) manda a
   `REVIEW` antes incluso de mirar la puntuación.

Ablacionar el paso `types` quita el *bonus*, no el invariante: el conflicto se
sigue detectando y sigue mandando a `REVIEW`.

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

Efecto medido: la segunda mención de la misma superficie recorre menos pasos que
la primera (`test_el_historial_abarata_la_cascada`).

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
| `test_knowledge_v3_resolution.py` | Normalización, similitud, catálogo, glosario, identificadores, historial, configuración, cascada, workspace, tipos, estabilidad entre pasadas, contrato emitido, ablaciones. | 104 |
| `test_knowledge_v3_resolution_mutations.py` | Mutación de las reglas duras. | 21 |

**Total: 125.** Suite completa del repositorio tras el cambio (los `testpaths`
de `pytest.ini` al completo, `tests/e2e` incluido): **4299 pasan, 5 se saltan,
0 fallan**. Sin regresiones: el cambio solo añade ficheros; no se ha tocado
`ci.yml`, `pytest.ini`, `contracts/` ni ningún módulo de V1/V2.

### Pruebas de mutación

Un test que pasa no demuestra que la regla que dice comprobar sea la que sostiene
el resultado. Estas lo demuestran al revés: rompen la regla y exigen que la
comprobación se ponga **roja**.

| Mutación | Comprobación que debe romperse |
|---|---|
| `filter_workspace` deja de filtrar | El homónimo de otra bóveda entra como candidato. |
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

1. **`SPLIT` no se emite.** Este subsistema recibe los grupos ya formados y no
   los parte. Declararlo como límite es más honesto que emitir una partición que
   nadie ha calculado. Cuando el extractor entregue grupos dudosos con evidencia
   de partición, el contrato ya la soporta.
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
