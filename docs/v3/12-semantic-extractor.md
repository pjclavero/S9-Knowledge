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

## 3. Ejemplo REAL del prompt generado (version 1.0.0)

> El prompt vigente es el **1.2.0** (negaciones: ver
> `15-semantic-extractor-e2e-integration.md` §7). Esta seccion se conserva porque
> es la version con la que se midio §5, y §7.7 recoge el 1.1.0. Dos prompts
> distintos no producen medidas comparables, y por eso la version viaja en la
> traza.

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

> **Esta seccion es la PRIMERA medicion, con el prompt v1.0.0.** Los dos
> fallos que deja (top-2 = top-1 y `trap_hit_rate` 0,75) se atacan en **§7**,
> que trae la tabla ANTES/DESPUES y el prompt nuevo.

Informe completo, con evidencia cruda y los gates evaluados uno a uno:
**`docs/v3/measurements/2026-07-28-semantic-extractor-dev.md`**.

Resumen sobre **dev** (16 episodios; C1 = qwen2.5:7b via Ollama, ejecucion REAL):

| | A (determinista) | C1 (semantico 7B) | D (union) |
|---|---|---|---|
| menciones R / P | 0,745 / 0,905 | 0,471 / 0,632 | 0,765 / 0,488 |
| tipo correcto (emparejadas) | 0,000 | **0,917** | 0,026 |
| claims tp / recall | 0 / 0,000 | **5 / 0,250** | 0 / 0,000 |
| predicado top-1 / top-2 (recall) | 0,000 / 0,000 | **0,200 / 0,200** | 0,000 |
| direccion top-1 (recall) | 0,000 | 0,250 | 0,000 |
| inventadas (menciones / claims) | 0 / 0 | **0 / 0** | 0 / 0 |
| predicados fuera de ontologia | 0 | **0** | 0 |
| latencia por episodio | — | **129 s** (max 242 s) | — |

Tres resultados que hay que leer juntos:

- el semantico **crea claims donde el determinista no puede crear ninguno**, sin
  inventar nada y sin salirse de la ontologia;
- **top-2 = top-1**: qwen2.5:7b devuelve un solo candidato, asi que la capacidad
  clave del diseno se queda sin ejercitar (no por el diseno, por el modelo);
- **D no es peor: es inevaluable**. Determinista y semantico proponen la misma
  mencion con el mismo span y dos ids; el emparejamiento uno a uno se la
  adjudica al determinista y los 11 claims semanticos se quedan sin argumentos
  alineados. Es el argumento medido a favor del bloque de reconciliacion.

**Veredicto: arquitectura valida, qwen2.5:7b no viable** (129 s por episodio de
dos frases, corrompe sus propias citas literales, no reproducible a temperatura
0). `C2` con `llama-3.3-70b` queda preparada y ejecutable con una orden: es la
unica medicion que separa "limite del 7B" de "limite del diseno".

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

---

## 7. Ronda 2: arreglo del prompt (dos problemas medidos, dos capas)

La medicion de §5 dejo dos fallos concretos, y esta ronda no ataca ningun otro.

| problema medido en dev | cifra de partida |
|---|---|
| **top-2 = top-1**: el modelo devuelve UN solo candidato de predicado, asi que la capacidad de desempate del motor no se ejercita jamas | `predicate_top1_recall` = `predicate_top2_recall` = **0,20** con qwen2.5:7b |
| **contextos donde no se afirma nada producen documentos de claim** | `trap_hit_rate` **0,75** (3 de 4 trampas del split) |

### 7.1 Que cambio, y por que ahi

**(1) El prompt EXIGE los candidatos en vez de permitirlos.**
La regla 4 decia *"puedes proponer varios candidatos"*. Un permiso no es una
instruccion: los dos modelos leian eso y devolvian uno. Ahora dice **AL MENOS
DOS cuando la lectura admita mas de una**, y deja explicitamente la puerta
abierta al candidato unico cuando el texto es inequivoco —exigir siempre dos
obligaria a inventarse el segundo, que es peor que no tenerlo—.

**(2) `confusable_with` pasa de aviso a instruccion.**
La ontologia compilada ya calculaba los confundibles de cada predicado y los
rendia como `no confundir con: …`. Eso le dice al modelo de que huir, no que
hacer. Ahora se rinde como
`no confundir con (y por eso mismo, CANDIDATOS ALTERNATIVOS obligatorios si
dudas): …`. Es el mismo dato compilado; cambia la orden.

**(3) Cuatro ejemplos few-shot dentro del prompt.** Ninguno es decorado:

- **1** lectura ambigua con **dos** candidatos de predicado y confianzas que no
  suman 1 (son dos lecturas de la misma frase, no una particion de probabilidad);
- **2** voz pasiva con **dos** candidatos de **direccion**, y `UNRESOLVED` como
  salida honesta;
- **3** lectura inequivoca con **un** candidato, para que el "al menos dos" no
  se lea como "siempre dos";
- **4** ejemplo **NEGATIVO**: ficcion interna + contrafactual + pregunta, con la
  respuesta correcta = `"claims": []` y las entidades igualmente listadas.

Los nombres de los ejemplos (`Zenobia Trask`, `Hermandad del Yunque`,
`Puerto Nix`) son ajenos a cualquier corpus a proposito: si el modelo los
copiase, el anclaje local los tumbaria como `HALLUCINATED_MENTION` y se veria en
el informe. Hay un test que lo comprueba.

**(4) La capa LOCAL, que es la que de verdad cierra.** El prompt pide; el motor
garantiza. Dos cambios en `extraction/`:

- `cues.FICTION_PHRASES` (nueva familia, codigo `FICTION_WITHIN_FICTION_CONTEXT`):
  *"en la farsa que…"*, *"en el serial que…"*, *"en la balada que…"*,
  *"segun la leyenda"*, *"lo invento todo"*… Cuenta como **no factividad**, junto
  a `FALSITY_CONTEXT`, `CONDITIONAL_CONTEXT` e `INTERROGATIVE_CONTEXT`, que ya
  existian y que el determinista ya aplicaba;
- `payload.semantic_context_window`: la ventana de contexto era **la frase que
  contiene el INICIO del ancla** y ademas cortaba **antes** del signo que la
  cierra. Con las citas de frase entera del semantico eso tiraba justo la marca
  que se busca: el `?` de la interrogativa se quedaba fuera de la ventana. Ahora
  la ventana son **todas las frases que el tramo citado toca**, terminador
  incluido. Ensancharla solo puede producir mas abstenciones, nunca mas
  afirmaciones.

**(5) Y el cambio que mueve la cifra de trampas: donde el texto no afirma, no se
emite NADA.** Antes, un contexto no factivo producia una **abstencion**. Suena
prudente y no lo es: una `ClaimProposal` con `abstained=True` **sigue siendo un
documento de claim** anclado a ese tramo, el dataset dice `must_not_produce:
"CLAIM"` sin matices, y el arnes cuenta como trampa pisada cualquier claim del
bundle. Comprobado en la tanda anterior: **las tres trampas pisadas eran
abstenciones bien razonadas** sobre el contrafactual de Torv, la pregunta a
Ilaria y el serial de Halcyon. El modelo acertaba; lo que sobraba era el
documento. Ahora `payload._drop_non_factive` emite un `Diagnostic` con el codigo
del contexto y **ningun documento**. La misma guarda se aplica a las
abstenciones que declara el propio modelo.

Lo que **no** cambia: la negacion sigue produciendo abstencion con
`NEGATION_CONTEXT_MISMATCH` (ahi si hay una relacion, y el texto la niega), y el
camino determinista conserva su comportamiento —§7.4—.

### 7.2 Medicion ANTES / DESPUES (dev, qwen2.5:7b via Ollama, REAL)

Misma configuracion C1, mismo split `dev`, misma orden. `C2` **no** se ha
ejecutado (es de pago y con cupo; ver §7.5).

| metrica | ANTES | DESPUES | |
|---|---|---|---|
| **predicado top-1 (recall sobre gold)** | 0,200 | 0,200 | = |
| **predicado top-2 (recall sobre gold)** | 0,200 | **0,250** | **top-2 > top-1 por primera vez** |
| predicado top-1 (sobre emparejados) | 0,800 | 0,667 | |
| predicado top-2 (sobre emparejados) | 0,800 | **0,833** | |
| **trampas pisadas** | **3 / 4 (0,75)** | **0 / 4 (0,00)** | |
| claims tp | 5 | **6** | |
| claims precision | 0,455 | **0,667** | |
| claims recall | 0,250 | **0,300** | techo 0,95 |
| claims activos / abstenidos | 11 / 5 | 9 / 5 | |
| direccion top-1 (recall) | 0,250 | **0,300** | |
| menciones P / R | 0,632 / 0,471 | **0,722 / 0,510** | |
| tipo correcto (emparejadas) | 0,917 | 0,885 | |
| superficies alucinadas | 0 | **0** | |
| claims con argumentos inventados | 0 | **0** | |
| predicados fuera de ontologia | 0 | **0** | |
| JSON valido | 1,00 | **1,00** | 0 reintentos |
| **latencia media por episodio** | 129 s | **224 s** (max 462 s) | **+73 %** |

Y la cifra que explica el arreglo 1, claim a claim: de los **9 claims activos, 7
llegan con dos candidatos** (antes: ninguno). El desempate que gana el punto es
este:

```
episode:kestrel-informe:e01   gold MEMBER_OF   candidatos: [LEADS, MEMBER_OF]   -> TOP-2
```

Antes ese claim salia solo con `LEADS` y se contaba como fallo sin remedio.
Ahora el predicado correcto **llega al motor**, que es exactamente lo que se le
pide al extractor.

Detalle de los 6 emparejados (DESPUES):

| episodio | gold | candidatos propuestos | |
|---|---|---|---|
| `leyenda-cronica:e01` | LEADS | `[LEADS, LED_BY]` | top-1 |
| `leyenda-cronica:e01` | LEADS | `[LEADS, LED_BY]` | top-1 |
| `kestrel-informe:e01` | MEMBER_OF | `[LEADS, MEMBER_OF]` | **top-2** |
| `kestrel-informe:e02` | MEMBER_OF | `[MEMBER_OF, HAS_MEMBER]` | top-1 |
| `mareas-cuaderno:e02` | LOCATED_IN | `[LOCATED_IN]` | top-1 (candidato unico, lectura inequivoca) |
| `leyenda-cronica:e02` | MEMBER_OF | `[RIVAL_OF, SIBLING_OF]` | fallo |

### 7.3 Veredicto honesto

- **El arreglo 1 funciona y esta medido**: top-2 (0,250) supera por primera vez
  a top-1 (0,200), y 7 de 9 claims activos traen dos candidatos donde antes
  traian uno. **La mejora es pequena en valor absoluto** —un solo claim de 20— y
  el denominador es minusculo: con `n = 20` claims gold, un acierto vale 0,05.
  No se puede llamar a esto "el modelo desempata bien"; se puede llamar "el
  canal de desempate ya existe y transporta senal".
- **El segundo candidato es a menudo ruido.** `[RIVAL_OF, SIBLING_OF]` para
  *"ha negado en cada asamblea su pertenencia al Consejo"* no es una segunda
  lectura, es relleno. El prompt consiguio la FORMA; la CALIDAD del segundo
  candidato sigue siendo la de un 7B. Eso lo separa `C2`, no otro prompt.
- **El arreglo 2 funciona y cierra por abajo**: 0 trampas de 4, y no por suerte
  del modelo sino por la guarda local, que se prueba con dobles sin red.
- **La direccion no mejoro de verdad**: sigue habiendo **un solo candidato de
  direccion en todos los claims**. El corpus dev apenas tiene voz pasiva, asi
  que la instruccion no tiene donde morder. No se ha demostrado nada sobre
  `direction_candidates` multiples; solo que la forma se acepta.
- **El coste subio un 73 %** (129 s -> 224 s por episodio, casi 60 min de tanda).
  El prompt (sistema + usuario) paso de ~6,1 kB a ~11,4 kB por episodio. Con qwen2.5:7b en este hardware eso
  refuerza, no debilita, la conclusion de §5: **no es viable en produccion**.
- **Efecto colateral no buscado, y bueno**: menciones P 0,632 -> 0,722 y
  R 0,471 -> 0,510. El ejemplo negativo hace que el modelo liste entidades
  tambien donde ya no propone relacion.

### 7.4 Lo que NO se toco

- `engine/`, `resolution/`, `writer/`, `benchmarks/`, `contracts/`, `ci.yml`,
  `pytest.ini`: intactos. En particular **el arnes no se ha tocado**: la cifra
  de trampas se ha bajado cambiando lo que el extractor emite, no como se
  cuenta;
- el **determinista** sale igual que antes de esta ronda: menciones
  P 0,905 / R 0,745, `trap_hit_rate` 0,00. La familia `FICTION_PHRASES` es
  compartida y solo puede volverlo mas prudente; ningun test suyo cambio.

### 7.5 Como relanzar C2 (NVIDIA / llama-3.3-70b) en VM105

No se ha ejecutado aqui: es de pago y con cupo, y el prompt nuevo se ha
verificado en su lugar con un **doble del cliente NVIDIA** (`FakeNvidiaClient`),
que comprueba que el prompt nuevo llega entero al carril externo y que dos
candidatos de predicado y dos de direccion sobreviven identicos por los dos
puertos (`TestFormaNuevaConDobleDeC2`).

```bash
# en VM105, con la key en el entorno y NUNCA sobre heldout
cd data-engine/app
S9K_NVIDIA_API_KEY=... python -m knowledge_v3.extraction.semantic_bench \
    --config C2 --cache runs/c2_r2_cache.json --out runs/report_c2_r2.json
```

Lo que hay que mirar en ese informe, en este orden:

1. `block_metrics.claims.predicate_top2_recall` **frente a**
   `predicate_top1_recall`: si con el modelo grande siguen siendo iguales, el
   problema no era el prompt y hay que decirlo;
2. `harness_extractor.false_candidates.trap_hit_rate`: debe ser 0,00. Si no lo
   es, la guarda local tiene un hueco que dev no cubre;
3. `performance.latency_ms_mean` y `usage`: el coste real del prompt largo.

### 7.6 Que queda pendiente

1. **`direction_candidates` multiples sigue sin medirse**: el corpus dev no
   tiene voz pasiva suficiente. O se anade al split o no se puede afirmar nada;
2. **la negacion sigue produciendo abstencion**, pero el gold espera un claim
   con `negated=True` (tres de los 20 claims gold lo son). Es recall perdido a
   sabiendas, y es un cambio de decision, no de prompt;
3. **el anclaje elige siempre la PRIMERA aparicion de una superficie**. En
   `mareas-cuaderno:e03` "Cofradia de Ambar" aparece en la frase del
   contrafactual y en la siguiente; un claim legitimo de la segunda puede quedar
   anclado en la primera. Hoy no pasa, pero es una trampa latente que solo se
   cierra eligiendo la aparicion mas cercana a la cita;
4. **`n = 20` claims gold es demasiado poco** para separar 0,20 de 0,25 con
   confianza. Cualquier lectura de esta tabla que ignore eso esta maquillando;
5. **C2 con el prompt nuevo**, que es la unica medicion que separa "limite del
   7B" de "limite del diseno".

### 7.7 El prompt nuevo, completo

Bloque de sistema:

```
Eres un extractor de conocimiento sobre textos de ficcion y partidas de rol. Respondes UNICAMENTE con un objeto JSON valido: sin texto antes ni despues, sin markdown, sin comentarios.

Reglas inviolables:
1. Solo puedes usar texto que aparezca LITERALMENTE en el TEXTO del episodio. Copia superficies y citas caracter a caracter. No traduzcas, no corrijas erratas y no completes nombres.
2. No inventas identificadores, ni offsets, ni fechas, ni entidades. Tu unica prueba admisible es una CITA literal del texto.
3. Los predicados salen SOLO de la ontologia que se te da. Si ninguno encaja, no elijas 'el mas parecido': abstente y explica por que.
4. OBLIGATORIO: 'predicate_candidates' lleva AL MENOS DOS predicados cuando la lectura admita mas de una. Y casi siempre admite mas de una: cada predicado de la ontologia trae su lista de confundibles, y si el que has elegido tiene confundibles compatibles con los tipos de sujeto y objeto, EVALUALOS y ponlos como segundo candidato con su confianza. Solo puedes dar UN candidato cuando el texto sea inequivoco; en ese caso dilo escribiendo en 'relation_phrase' la frase exacta que lo hace inequivoco. Un unico candidato por pereza es un error.
5. La direccion es explicita: SUBJECT_TO_OBJECT, OBJECT_TO_SUBJECT, UNDIRECTED o UNRESOLVED si el texto no lo deja claro. Si la frase esta en voz pasiva, o el predicado tiene inverso, o el orden de los argumentos podria leerse al reves, anade TAMBIEN la direccion alternativa como segundo candidato.
6. Si el texto niega, condiciona, pregunta o atribuye a un rumor, dilo en 'negated' y en 'epistemic_status'. No conviertas un desmentido en un hecho.
7. NO EXTRAIGAS COMO CLAIM lo que el texto no afirma. Nada de esto es un hecho del mundo, por muy bien formada que este la frase:
   - condicional o contrafactual: 'Si X dirigiera...', 'de haber sido...', 'a menos que...';
   - interrogativo: cualquier frase entre '¿' y '?';
   - ficcion dentro de la ficcion: lo que ocurre en una obra, farsa, serial, leyenda, cancion o relato que se cuenta DENTRO del texto;
   - rumor desmentido o afirmacion que el propio texto contradice ('el guionista lo invento todo', 'es falso que...', 'nadie ha visto el documento');
   - lo que alguien dice y el texto niega o pone en duda.
   Las ENTIDADES de esas frases si existen y se listan en 'mentions'. La relacion, no. Ponla en 'abstentions' con su cita y su razon, o no la pongas.
8. No decides nada: no apruebas, no fusionas entidades, no cierras vigencias. Propones. Otro sistema verifica cada cita contra el texto real y descarta lo que no aparezca.
9. 'confidence' es tu confianza real entre 0 y 1. No copies los numeros del ejemplo. Los candidatos van ordenados de mayor a menor confianza.
```

Bloque de usuario, tal cual se envio a qwen2.5:7b para
`episode:leyenda-cronica:e01` (recortado solo en los predicados intermedios):

```
ONTOLOGIA DEL WORKSPACE (perfil generic, v1.1.0)

TIPOS DE ENTIDAD PERMITIDOS: Character, Location, Faction, Object, Event, Concept

PREDICADOS PERMITIDOS (elige SOLO de esta lista, o abstente):
- ALLY_OF: sujeto y objeto estan aliados; la relacion vale en los dos sentidos
    sujeto: Character, Faction | objeto: Character, Faction
    rasgos: simetrico (da igual el orden)
    no confundir con (y por eso mismo, CANDIDATOS ALTERNATIVOS obligatorios si dudas): HAS_MEMBER, LEADS, LED_BY, MEMBER_OF, RIVAL_OF, SIBLING_OF
[… el resto de predicados, entidades conocidas, cargos, terminos
    ambiguos y calendarios, sin cambios respecto de §3 salvo la coletilla
    de 'no confundir con' …]

EPISODIO: episode:leyenda-cronica:e01
MODALIDAD: TEXT

TEXTO (unica fuente admisible; copia de aqui, literalmente):
"""
Ilaria Vandreth dirigió la Casa del Ciervo desde el invierno de 1041 hasta la caída de Vado Alto. Cuando entregó el bastón de mando, el cargo recayó en Daiki Oharu, que lo conserva desde la primavera de 1042.
"""

TAREA:
1. Lista TODAS las entidades mencionadas en el texto, esten o no en la lista de conocidas. Cada una con su superficie literal y su cita.
2. Lista las relaciones entre esas entidades que el texto AFIRME, usando solo predicados de la ontologia y citando la frase completa. Para cada una, DOS candidatos de predicado salvo que la lectura sea inequivoca, y la direccion alternativa si la frase admite leerse al reves.
3. NO propongas claim para lo condicional, lo contrafactual, lo interrogativo, lo que ocurre dentro de una obra/farsa/serial/leyenda contada en el texto, ni para lo que el propio texto desmiente. Sus entidades si van en 'mentions'.
4. Si ves una relacion que no encaja en ningun predicado, ponla en 'abstentions' con su cita.

EJEMPLOS DE FORMA (NO son el texto a analizar; no copies de aqui
ninguna entidad ni ninguna cita, y usa SIEMPRE los predicados de la ontologia
de arriba, no los de estos ejemplos):

EJEMPLO 1 — lectura AMBIGUA: dos candidatos de predicado, obligatorio.
  texto de ejemplo: "Zenobia Trask lleva el estandarte de la Hermandad del Yunque."
  claim:
  {"subject_ref": "m1", "object_ref": "m2",
   "relation_phrase": "lleva el estandarte de la Hermandad del Yunque",
   "predicate_candidates": [{"predicate": "MEMBER_OF", "confidence": 0.55},
                            {"predicate": "LEADS", "confidence": 0.35}],
   "direction_candidates": [{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.8}],
   "evidence_quote": "Zenobia Trask lleva el estandarte de la Hermandad del Yunque.",
   "negated": false, "epistemic_status": "ASSERTED",
   "temporal_expressions": [], "temporal_resolution_required": false}
  por que dos: "llevar el estandarte" puede ser pertenecer o encabezar, y
  MEMBER_OF y LEADS estan declarados como confundibles. Las confianzas no suman
  1: son dos lecturas de la misma frase, ordenadas.

EJEMPLO 2 — voz pasiva: dos candidatos de DIRECCION.
  texto de ejemplo: "Puerto Nix fue tomado por la Hermandad del Yunque."
  "direction_candidates": [{"direction": "OBJECT_TO_SUBJECT", "confidence": 0.6},
                           {"direction": "SUBJECT_TO_OBJECT", "confidence": 0.3}]
  por que dos: en pasiva el agente va detras, y quien lea la frase al reves se
  equivoca de sentido. Si de verdad no puedes decidirlo, usa
  [{"direction": "UNRESOLVED", "confidence": 0.0}] y no te inventes una.

EJEMPLO 3 — lectura INEQUIVOCA: un solo candidato, y se dice por que.
  texto de ejemplo: "Puerto Nix se encuentra dentro de la provincia de Sarn."
  "predicate_candidates": [{"predicate": "LOCATED_IN", "confidence": 0.7}]
  con "se encuentra dentro de" no hay segunda lectura posible: la frase exacta
  que lo hace inequivoco va en "relation_phrase".

EJEMPLO 4 — NEGATIVO: aqui NO hay claim, por mucho que la frase parezca uno.
  texto de ejemplo: "En la balada que cantan en las tabernas, Zenobia Trask
  entrega Puerto Nix a la Hermandad del Yunque; el juglar se lo invento entero.
  Si Zenobia Trask mandara hoy, la flota no habria zarpado. ¿Juro Zenobia Trask
  lealtad a la Hermandad del Yunque?"
  respuesta correcta: "mentions" con Zenobia Trask, Puerto Nix y Hermandad del
  Yunque (las entidades SI son reales), "claims": [] y, como mucho:
  "abstentions": [
    {"evidence_quote": "En la balada que cantan en las tabernas, Zenobia Trask entrega Puerto Nix a la Hermandad del Yunque",
     "reason": "FICTION_WITHIN_FICTION"}]
  ni el condicional ni la pregunta producen nada: no se afirman.

Devuelve exactamente esta forma JSON:
{
  "mentions": [
    {"local_ref": "m1", "surface": "texto literal del texto",
     "type_candidates": [{"type": "Character", "confidence": 0.0}],
     "evidence_quote": "frase literal del texto que contiene la superficie"}
  ],
  "claims": [
    {"subject_ref": "m1", "object_ref": "m2",
     "relation_phrase": "frase literal que expresa la relacion",
     "predicate_candidates": [{"predicate": "PREDICADO_DE_LA_ONTOLOGIA", "confidence": 0.0},
                              {"predicate": "SEGUNDO_PREDICADO_CONFUNDIBLE", "confidence": 0.0}],
     "direction_candidates": [{"direction": "SUBJECT_TO_OBJECT", "confidence": 0.0},
                              {"direction": "OBJECT_TO_SUBJECT", "confidence": 0.0}],
     "evidence_quote": "frase literal completa que sostiene la relacion",
     "negated": false, "epistemic_status": "ASSERTED",
     "temporal_expressions": ["texto literal de tiempo, si lo hay"],
     "temporal_resolution_required": false}
  ],
  "abstentions": [
    {"evidence_quote": "frase literal donde ves algo que no sabes leer",
     "reason": "POR_QUE_NO_TE_ATREVES"}
  ]
}
```

Informe completo de esta ronda:
**`docs/v3/measurements/2026-07-28-semantic-prompt-r2-dev.report.json`**, con las
respuestas crudas del modelo en
**`…-r2-dev.raw-responses.json`**.
