# 59 — La sesión de revelación, del mando a Neo4j (EQUIPO 6C)

> Repo `pjclavero/S9-Knowledge` · rama `worktree-agent-a829237f0647a2599`
> base `integracion/tanda5` = `5808a40544444a5ba2214315654754494e58950c`

## El defecto

`writer/visibility.py::revelacion_props` exige `known_from_session` para todo
lo que se escribe en ámbito `PARTIDA`, y `writer/executor.py` lo busca en
`op["payload"]`. **Ningún constructor de operaciones lo ponía nunca ahí**:
`known_from_session` no aparecía ni una vez en `pipeline/` ni en
`engine/planner.py`, y ningún mando lo declaraba.

Mientras la CLI no supo producir ámbito de partida, eso no se notaba y se
archivó como deuda declarada («no bloquea, porque el CLI no puede producir
ámbito de partida»). En cuanto EQUIPO 5A abrió la ruta `--partida`, **todo
plan de partida abortaba con `EXEC_REVELACION_NO_DECLARADA`** y el ámbito de
partida quedó inalcanzable desde el producto — con él, la prueba de las dos
partidas.

Es el mismo patrón por cuarta vez en el programa: **la guardia existe, pero el
dato que debía llegar a ella no llega.** La guardia era correcta; lo que
faltaba era la carretera.

## Carencia declarada, no contrato inventado

`known_from_session` **no está en ningún contrato congelado**. No es un
descuido y no se ha añadido a ninguno:

- `contracts/knowledge-visibility/v1/README.md` (§ *Frontera de uso*) dice
  literalmente que las demás dimensiones del motor — «`party`,
  `session_index`, `workspace`, `partida_id`…» — **siguen siendo
  responsabilidad de quien construye el nodo**. Es decir: es una propiedad de
  nodo legítima, deliberadamente fuera del contrato de visibilidad.
- `contracts/.../graph-mutation-plan` está congelado en `1.0.0` con una prueba
  que lo verifica byte a byte. El `payload` de una operación declara
  `additionalProperties: true` **por diseño** (depende del tipo de operación y
  de la ontología), y es el punto de extensión documentado que el propio
  `executor` ya usaba para leer este dato.
- `docs/v3/49-multipartida-diseno.md` ya había medido y escrito que estas
  propiedades **no las produce nada en el pipeline V3**.

Por eso el arreglo **no amplía ningún esquema**: hace viajar el dato por el
punto de extensión que el writer ya leía.

## De dónde sale el dato y por qué es la fuente de verdad

La sesión de revelación **la declara quien ingiere**, con `--sesion N`, igual
que el ámbito (`--partida`) y que el instante (`--ahora`).

No es una comodidad: es la única fuente honesta que existe. `known_from_session`
no dice a qué episodio pertenece un texto (eso sería `session_index`), dice
**desde qué sesión de juego puede revelarse** lo que se ingiere. Si en la
sesión 12 se descubre un asesinato ocurrido cinco años antes, la barrera del
visor es 12, no la cronología del hecho. Ningún punto del software puede
deducir eso del fichero: sólo lo sabe quien dirige la partida.

`0` es una declaración **positiva** («conocido desde el inicio»), no una
ausencia — y por eso mismo **no se usa como valor por defecto** en ningún
punto de esta cadena.

## La cadena completa

```
CLI  --partida X --sesion N
  -> ingest_cli.run_ingest(partida_id=, known_from_session=)
  -> PipelineConfig.known_from_session
  -> KnowledgePipeline.decide -> engine.run(known_from_session=)
  -> PlanContext.known_from_session          (fail closed en __post_init__)
  -> planner._stampar_revelacion             (payload de CADA operación)
  -> seal_plan  (entra en la idempotency_key)
  -> writer/executor._validated_payload      (lo retira del payload…)
  -> writer/visibility.stamp                 (…y lo estampa como propiedad)
  -> Neo4j: V3Entity / V3Assertion / relación materializada
```

Dos decisiones con consecuencias:

- **Un solo punto de estampado.** El writer la exige por *operación* —dos
  hechos del mismo plan pueden revelarse en sesiones distintas—, pero hoy la
  única fuente que existe es la declaración de la corrida, que es por *plan*.
  Repartir el valor desde los cuatro constructores de operaciones (`_altas`,
  aserción, supersesión, proyección) habría dado cuatro sitios donde
  olvidarlo, que es exactamente como nació este defecto.
- **Entra en la `idempotency_key`.** El payload deriva la firma de la
  operación, así que la misma afirmación revelada en dos sesiones distintas es
  una declaración distinta y no colapsa en la misma clave. En capa juego no se
  estampa nada y el plan sale **byte a byte idéntico**, con su mismo
  `plan_hash`.

## Fail closed, en dos sitios y sin degradar

| situación | resultado |
|---|---|
| `--partida` sin `--sesion` | `PLAN_SESION_NO_DECLARADA`, antes de abrir conexión |
| ámbito de partida sin sesión en `PlanContext` | `PLAN_SESION_NO_DECLARADA` (`EnginePlanError`) |
| `--sesion` sin `--partida` | `PLAN_SESION_SIN_AMBITO` |
| sesión no entera o negativa | `PLAN_SESION_INVALIDA` |

**Nunca se degrada a capa JUEGO.** Degradar publicaría como lore compartido
algo declarado privado de una partida; poner `0` declararía «conocido desde el
inicio» en nombre del director. Y `--sesion` sin `--partida` se rechaza **en
voz alta** en vez de descartarse en silencio, porque `revelacion_props`
devuelve `{}` para `scope=juego` y quien la declaró se quedaría creyendo que
viaja al grafo.

La guardia se repite en `PlanContext` a propósito: si viviera sólo en la CLI,
cualquier otra ruta que construyese un contexto volvería a producir planes de
partida sin sesión.

## Lo medido (Neo4j real, desde vacío, sin Cypher manual de escritura)

`data-engine/app/tests/test_equipo6c_sesion_de_partida_neo4j_real.py`, 10
pruebas, contra un Neo4j efímero cuyo esquema instala el producto.

| | |
|---|---|
| `partida:A`, sesión **3** | `APPLIED`, 3 operaciones |
| `partida:B`, sesión **7** | `APPLIED`, 3 operaciones, ninguna clave compartida con A |
| `partida:A`, sesión **5** (2.ª corrida) | `APPLIED`, incluye la relación materializada `LEADS` |
| aserciones | `scope=partida`, `known_from_session` ∈ {3,5} en A y {7} en B |
| relación `LEADS` | `scope=partida`, `partida_id=partida:A`, `known_from_session=5` |
| entidades | identidad `(workspace, entity_id)` intacta, sin repetidos, ámbito declarado en todas |

Las tres declaraciones son **3, 7 y 5**: distintas entre sí y ninguna es `0`.
Un valor por defecto no puede coincidir con las tres — que es exactamente la
comprobación que este carril necesitaba, porque el defecto perseguido era un
dato que no llegaba.

**Control negativo**: neutralizando `planner._stampar_revelacion` (y sólo eso),
la misma corrida vuelve a `EXEC_REVELACION_NO_DECLARADA` y el grafo queda
vacío. El verde lo produce la propagación, no otra cosa.

## Lo que NO se ha tocado

- `authz/`, `policies/`, grants, visibilidad, política de lore. La regla T2 se
  cumple **declarando la sesión, no relajándola**.
- La identidad de `Entity`: `(workspace, entity_id)` sigue siendo
  workspace-global. Lo que el ámbito privatiza son aserciones, relaciones
  materializadas y operaciones aplicadas.
- Ningún gate nuevo, ningún meta-gate, ningún esquema congelado.

## Carencia que queda abierta

La sesión es hoy **por corrida**, no por operación. El writer admite (y exige)
el dato por operación, y el diseño lo contempla: dos hechos de la misma sesión
de juego pueden revelarse en momentos distintos. Cuando exista una fuente por
hecho —una anotación del director sobre el propio claim—, el punto de entrada
ya está: `_stampar_revelacion` es el único sitio que hay que hacer más fino, y
la guardia de `PlanContext` seguirá impidiendo que un hecho salga sin declarar.
