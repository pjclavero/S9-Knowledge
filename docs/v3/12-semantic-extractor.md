# 12. Extractor semantico episodico

**Pregunta del bloque, y ninguna otra:** ¿un extractor semantico estructurado,
guiado por ontologia y agnostico del proveedor, produce menciones y claims
utiles sobre el corpus **dev**, y con que modelo a que coste?

Este documento responde con cifras medidas. No propone desplegar nada.

---

## 1. Punto de partida (medido, no supuesto)

El extractor V3 tal y como estaba:

| hecho medido sobre dev | cifra |
|---|---|
| claims del determinista | tp 0, fn 20 (recall 0.0) |
| menciones del determinista | F1 0.817 (P 0.905 / R 0.745) |
| menciones sin glosario | 0 |
| camino Ollama: predicado | inventado por el modelo y descartado despues con `PREDICATE_NOT_IN_PROFILE` |
| camino Ollama: direccion | `SUBJECT_TO_OBJECT` **cableada** |
| camino Ollama: revision | `review_required=True` en todo, sin razon declarada |

El diagnostico es de arquitectura, no de afinado: el determinista es un
reconocedor de listas (glosario + 14 reglas lexicas) y el camino Ollama pagaba
la llamada entera para tirar la respuesta. Ademas, las reglas del determinista
usan predicados (`LIVES_IN`, `SERVES`, `RULES`, `ENEMY_OF`…) que **no estan en el
perfil `generic`** del corpus: con perfil, ninguna de sus lecturas puede
sobrevivir a la comprobacion de ontologia. Eso explica el `tp 0` mejor que
cualquier hipotesis sobre el texto.

---

## 2. Arquitectura

```
GameProfile ──compile_ontology()──► OntologySpec ──render_prompt()──► prompt
                                        │                               │
   Lexicon (glosario V1 + perfil) ───────┘                               ▼
                                                              ProviderPort.complete_json()
                                                                        │
                        Ollama (qwen2.5:7b) ─┐                          │
                        NVIDIA (llama-3.3-70b)├── mismo puerto ──────────┘
                        Mock (tests)         ─┘                          │
                                                                         ▼
                                                        normalize_semantic_payload()
                                    anclaje local + verificacion de contexto + ontologia
                                                                         │
                                                                         ▼
                                              EntityMention / ClaimProposal validados
```

Ficheros:

| fichero | responsabilidad |
|---|---|
| `extraction/provider_port.py` | puerto agnostico (`ProviderRequest` → `ProviderReply`) y tres adaptadores |
| `extraction/ontology_prompt.py` | compila el `GameProfile` en `OntologySpec` y renderiza el prompt |
| `extraction/semantic.py` | `SemanticEpisodeExtractor`: orquesta llamada, temporalidad escalonada y medicion |
| `extraction/payload.py` | `normalize_semantic_payload`: la frontera anti-alucinacion de la forma nueva |
| `extraction/temporal.py` | `resolve_locally` / `validate_model_expressions`: fases (a), (c) y (d) |
| `extraction/semantic_bench.py` | ejecuta el pipeline sobre dev y llama al arnes de `benchmarks/` |

### 2.1 Ontologia compilada, no escrita a mano

Por cada predicado del perfil se compila: **definicion**, **dominio**, **rango**,
**simetria**, **transitividad**, **funcionalidad**, **inverso** y
**confundible_con**.

- la **definicion** sale del catalogo del nucleo (`CORE_PREDICATE_DEFINITIONS`);
  si el predicado no esta, se **deriva** de su dominio y rango y se dice que es
  derivada. Ningun predicado llega al modelo sin explicar;
- **confundible_con** se **calcula**: el inverso declarado, los predicados que
  comparten dominio y rango (mismo hueco de tipos = misma trampa) y los que los
  invierten. Es lo que permite que el modelo distinga `MEMBER_OF` de `LEADS`,
  que en el perfil `generic` tienen dominio y rango identicos;
- los **tipos de entidad** salen del perfil; el catalogo canonico de
  `base.ALLOWED_ENTITY_TYPES` pasa a ser el defecto cuando el perfil no los
  declara (`base.entity_types_of`);
- el **glosario del workspace** entra como "entidades ya conocidas", con la
  instruccion explicita de que **la lista no es cerrada**.

### 2.2 Una respuesta conjunta

El modelo devuelve `mentions` + `claims` + `abstentions` en una sola llamada.
**No aporta**: ids, offsets, `fragment_id`, entidades canonicas, decisiones ni
aprobaciones. Aporta superficies, citas, candidatos y su confianza. Todo lo
demas se reconstruye y se verifica en local.

### 2.3 Candidatos, no veredictos

`predicate_candidates` y `direction_candidates` **ya existian en el contrato y
nunca se ejercitaban**: el camino anterior mandaba siempre uno solo. Ahora el
modelo propone hasta tres predicados ordenados y la direccion explicita. Un
candidato fuera de la ontologia **se cae solo el**, no el claim entero; si no
sobrevive ninguno, el claim se convierte en **abstencion** con
`PREDICATE_NOT_IN_PROFILE` y los descartados quedan en
`metadata.dropped_predicates`.

### 2.4 Temporalidad escalonada

```
(a) resolver en local lo explicito   fechas, "desde X hasta Y", "durante N", "ya no", "todavia"
(b) SOLO si queda ambiguo            segunda llamada por el MISMO puerto
(c) validar el resultado en local    la expresion tiene que estar LITERALMENTE en el texto
(d) si sigue ambiguo                 metadata.temporal_resolution_required = true
```

`resolve_locally` devuelve `RESOLVED` / `AMBIGUOUS` / `NONE`. Solo `AMBIGUOUS`
gasta una segunda llamada. Una fecha que el modelo "recuerda" y el texto no dice
se descarta con `HALLUCINATED_TEMPORAL_EXPRESSION`: es una alucinacion con
formato de dato duro, la peor clase.

### 2.5 Lo que NO se toca

- el modelo aporta **citas**; los offsets los calcula el sistema local;
- superficie que no aparece literalmente → `HALLUCINATED_MENTION`;
- cita cuyo contexto la contradice (negacion, no factividad) → **abstencion**;
- ancla ambigua → abstencion;
- la confianza del modelo se acota a `DEFAULT_CONFIDENCE_CAP = 0.7` y **no** se
  lee como probabilidad calibrada;
- ninguna salida firma ni aprueba: `review_required=True` y `produced_by_step`
  veraz;
- **el determinista no se elimina**: sigue siendo la via barata de alta
  precision y el unico gate reproducible.

### 2.6 Dos ajustes de anclaje que hubo que hacer, y por que

Ambos estan probados y ambos **endurecen** o **dejan igual** la barrera:

1. **`payload.anchor_in_episode`**. `EvidenceIndex.anchor_quote` exige que la
   cita quepa DENTRO de un fragmento. En el corpus real los fragmentos son
   tramos cortos (`"Ilaria Vandreth"`, `"dirigió la Casa del Ciervo desde el
   invierno de 1041"`), asi que una cita de frase completa —justo lo que hace
   falta para comprobar el SENTIDO— no anclaba **nunca** y toda propuesta moria
   como `HALLUCINATED_QUOTE` siendo literalmente cierta. Eso no medía
   alucinacion: medía el troceado. Ahora la cita se ancla al **texto real del
   episodio** y se exige que el tramo **solape al menos un fragmento de
   evidencia real**, cuyos ids se emiten. Los offsets los sigue calculando el
   sistema local y una cita inexistente sigue sin anclar.
2. **`payload.verify_semantic_quote_context`**. La verificacion de negacion
   miraba solo lo que hay **antes** del ancla. Con una cita de frase completa el
   foco cae en la primera palabra y detras no hay nada: *"Elara **no** pertenece
   a la Orden"* pasaba como afirmacion. Ahora el foco se lleva al final del
   tramo citado, asi que cualquier marca **dentro de la cita** cuenta. Es
   estrictamente mas prudente.

El camino determinista conserva su comportamiento anterior: el modo de anclaje
temporal por solape (`ANCHOR_OVERLAP`) es opcional y su defecto sigue siendo
`ANCHOR_CONTAINED`.

---

## 3. Ejemplo REAL del prompt generado

Prompt tal cual se envio a qwen2.5:7b para `episode:leyenda-cronica:e01`
(recortado solo en los predicados intermedios, marcados con `[…]`):

```
ONTOLOGIA DEL WORKSPACE (perfil generic, v1.0.0)

TIPOS DE ENTIDAD PERMITIDOS: Character, Location, Faction, Object, Event, Concept

PREDICADOS PERMITIDOS (elige SOLO de esta lista, o abstente):
- ALLY_OF: sujeto y objeto estan aliados; la relacion vale en los dos sentidos
    sujeto: Character, Faction | objeto: Character, Faction
    rasgos: simetrico (da igual el orden)
    no confundir con: HAS_MEMBER, LEADS, LED_BY, MEMBER_OF, RIVAL_OF, SIBLING_OF
- HAS_MEMBER: el grupo sujeto cuenta al objeto entre sus miembros
    sujeto: Faction | objeto: Character
    rasgos: inverso de MEMBER_OF
    no confundir con: ALLY_OF, LEADS, LED_BY, MEMBER_OF, RIVAL_OF
- LEADS: el sujeto dirige, manda o encabeza al objeto
    sujeto: Character | objeto: Faction
    rasgos: funcional (un solo objeto valido a la vez); inverso de LED_BY
    no confundir con: ALLY_OF, HAS_MEMBER, LED_BY, MEMBER_OF, RIVAL_OF
[…]
- MEMBER_OF: el sujeto pertenece al grupo, casa u organizacion del objeto
    sujeto: Character | objeto: Faction
    rasgos: inverso de HAS_MEMBER
    no confundir con: ALLY_OF, HAS_MEMBER, LEADS, LED_BY, RIVAL_OF
[…]

ENTIDADES YA CONOCIDAS (para RECONOCERLAS, no para limitarte a ellas;
encontrar entidades nuevas que no esten en esta lista es parte del trabajo):
  Amarra Vieja; Casa del Ciervo; Cofradia de Ambar; Consejo de Umbra; Consorcio
  Halcyon; Cooperativa Vela; Daiki Oharu; Estacion Kestrel; Gremio de Faros;
  Ilaria Vandreth; Nadir Boone; Nucleo Bruma; Puerto Quilla; Ruta Simm; Sela
  Marrec; Torv Marrec; Umbra; V4ndreth; Vado Alto; Vania Ostrow

CARGOS Y TITULOS (no son entidades por si solos): magistrado, senescal, maestra
de faros, jefa de operaciones

TERMINOS AMBIGUOS (no decidas a quien se refieren; marcalos igual como mencion):
el Consejo, la Casa, el Gremio, la Cofradia, la estacion

CALENDARIOS DEL MUNDO: Era del Ciervo (ciclo, luna); Cuenta de Mareas (marea,
temporada); Ciclo orbital (ciclo, turno)

EPISODIO: episode:leyenda-cronica:e01
MODALIDAD: TEXT

TEXTO (unica fuente admisible; copia de aqui, literalmente):
"""
Ilaria Vandreth dirigió la Casa del Ciervo desde el invierno de 1041 hasta la
caída de Vado Alto. Cuando entregó el bastón de mando, el cargo recayó en Daiki
Oharu, que lo conserva desde la primavera de 1042.
"""

TAREA:
1. Lista TODAS las entidades mencionadas en el texto, esten o no en la lista de
conocidas. Cada una con su superficie literal y su cita.
2. Lista las relaciones entre esas entidades que el texto sostenga, usando solo
predicados de la ontologia y citando la frase completa.
3. Si ves una relacion que no encaja en ningun predicado, ponla en 'abstentions'
con su cita.

Devuelve exactamente esta forma JSON:
{ "mentions": [...], "claims": [...], "abstentions": [...] }
```

Los `fragment_id` **no** aparecen en el prompt: el modelo no puede aportarlos,
asi que ensenarselos solo le daria algo mas que alucinar.

---

## 4. Configuraciones de pipeline

| configuracion | cadena | uso |
|---|---|---|
| `ExtractionPipeline.local_default()` | determinista + tabla + temporal + correferencia | **gate**: sin red, reproducible bit a bit. **INTACTO** |
| `ExtractionPipeline.production_local(port)` | lo anterior **+ semantico** (LLM local) | produccion local |
| `ExtractionPipeline.production_external(port)` | la MISMA cadena con el puerto externo | produccion con externo |

Que `production_external` sea literalmente `production_local` con otro puerto no
es pereza: **es el resultado**. Si hiciese falta otra cadena para el modelo
externo, el puerto no seria agnostico.

**Sin reconciliador todavia.** En `D` las propuestas se evaluan como **union**:
ids separados, origen conservado (`produced_by_step`), evidencia propia y
duplicados incluidos. Fundirlas aqui seria inventarse el resultado del bloque
siguiente.

---

## 5. Medicion

Ver `docs/v3/measurements/2026-07-28-semantic-extractor-dev.md`.

---

## 6. Bloqueos y limites de contrato

1. **`game-profile/v3-internal-v1` no tiene `definition` ni `confusable_with`.**
   La definicion se toma del catalogo del nucleo (o se deriva) y la
   confundibilidad se **calcula** desde dominio/rango/inverso. Si un dia el
   perfil los declara, el compilador los prefiere sin tocar el prompt. **No se
   ha anadido ningun campo a ningun schema.**
2. **`direction` no admite `UNRESOLVED`.** El enum congelado es
   `SUBJECT_TO_OBJECT | OBJECT_TO_SUBJECT | UNDIRECTED`. Cuando el modelo dice
   `UNRESOLVED` se emite **lista vacia** de `direction_candidates` (legal por
   contrato) y `metadata.direction_unresolved = true`. **No** se traduce a
   `UNDIRECTED`: eso significa "relacion simetrica", que es una afirmacion
   distinta y falsa.
3. **`temporal_resolution_required` y `untrusted_origin` no existen como
   campos** y no se han anadido: viajan en `metadata`, el unico bloque abierto
   de la familia `v3-internal-v1` (excepcion ya documentada en el schema).
4. **Un claim gold del split dev ES una abstencion**
   (`claim:leyenda-escaneo:e02:c00`). El techo de las metricas de claim ACTIVO
   es por tanto 19/20 = **0.95**, no 1.0. Se declara en
   `block_metrics.claims.gold_active_ceiling` para que nadie lo lea como fallo.

Ningun bloqueo ha impedido implementar el diseno acordado.
