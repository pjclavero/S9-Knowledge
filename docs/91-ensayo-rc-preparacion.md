# 91 · Preparación del ensayo RC (no ejecutado)

**Slice 2 · Carril C.** Base: `origin/main` = `324cb207`.

Esto **prepara** el ensayo del recorrido real completo. **No lo ejecuta**: no
despliega, no crea ninguna RC, no enciende ninguna máquina y no toca
producción. Lo que se entrega es **configuración declarada** y
**comprobaciones que se observan**.

## El recorrido que el ensayo tiene que atravesar

```
subir fichero -> el escáner lo detecta -> mapping decide workspace/ámbito/partida
             -> registra Source -> crea ingest_v3 -> progreso visible
             -> REVIEW si procede -> el operador revisa -> plan sellado -> APPLY
             -> el worker OBSERVA Neo4j real -> proyecta
             -> resultado navegable -> procedencia -> evidencia literal
```

Y lo hace **sin terminal, sin SQL, sin CLI, sin IDs internos y sin Neo4j
Browser**. Si hace falta una consola para completar un paso, ese paso no está
cubierto por el producto y el ensayo lo tiene que decir.

## Por qué la lista existe

Las rondas anteriores midieron que este recorrido **no se rompe por código: se
rompe por despliegue**. Y no da errores — da pantallas vacías:

| Lo que se separa | Lo que ve el operador |
| --- | --- |
| `review.sqlite3` en dos volúmenes | decide, y el motor no ve la decisión |
| `S9K_V3_REVIEW_PROPOSALS_DIR` distinto en escritor y visor | «Sin propuestas visibles» |
| almacén de propuestas inexistente | consola vacía y **muda** |
| `S9K_INGEST_SOURCES_DIR` vacío | el paso 1 deja de ser usable, **sin un solo error** |
| interruptor por *nombre* en vez de por *letra* | no monta nada, y no se distingue «apagado» de «no autorizado» |
| sin `S9K_ALLOW_REAL_INGEST` / `S9K_WRITER_WORKSPACE` | no hay botón; el POST contesta `APPLY_NOT_ENABLED` |

Cada fila de arriba es un punto de la lista de abajo, **ejecutable**.

## La lista: `deploy/scripts/preflight_ensayo_rc.py`

Solo lectura. Un único efecto de escritura: un fichero testigo en el almacén de
propuestas, que se borra — **la única forma de saber si el escritor podrá
escribir es escribir**.

```
python3 deploy/scripts/preflight_ensayo_rc.py --workspace <ws>

0 = todas VERDE      -> el ensayo puede empezar
1 = alguna PENDIENTE -> NO empezar: hay algo que NO SE PUDO MIRAR
2 = alguna ROJA      -> NO empezar: requisito incumplido
3 = instrumental inválido (el canario no dio rojo)
```

| Punto | Cómo se observa | Calibrado |
| --- | --- | --- |
| `canario` | sondeo con respuesta conocida: **tiene que dar ROJO**; si no, el guion aborta sin juzgar nada | sí |
| `arbol.declarado` | el `HEAD` real del árbol (leído de `.git`, sin invocar `git`) contra `S9K_ENSAYO_COMMIT` | sí (otro commit, sin declarar, HEAD ilegible) |
| `fuentes.pobladas` | se pide el catálogo **del producto** (`sources_catalog.listar_fuentes`) y se cuenta | sí |
| `paneles.por_letra` | B, C, F, G con un valor que el chasis acepta (`true`/`1`, nada más) | sí (una por letra + valor inválido) |
| `paneles.sin_nombres` | ninguna `S9K_PANEL_*_ENABLED` fuera del contrato por letra | sí |
| `resultado.navegable` | `S9K_PANEL_RESULTADO_ENABLED` encendido | sí |
| `propuestas.declarada` | declarada, absoluta y **fuera del árbol de la release** | sí |
| `propuestas.utilizable` | existe, `R\|X`, y **se escribe un testigo** que se retira *siempre* | sí (inexistente, solo-lectura, testigo residual) |
| `propuestas.derivacion_unica` | el resolvedor **canónico** (`review_paths.default_proposals_dir`) devuelve esa misma ruta | sí |
| `review_db.compartida` | el lector del motor (`review_decisions.default_decisions_db`) resuelve **el mismo fichero** que declara el visor | sí |
| `estado.persistente` | propuestas y `review.sqlite3` bajo **un** `S9K_STATE_ROOT` que no sea la raíz del sistema | sí (dos volúmenes, sin raíz, `S9K_STATE_ROOT=/`) |
| `reinicio.no_reprocesa` | estado durable del escáner declarado y fuera de la release | sí (hoy **PENDIENTE**: no hay escáner) |
| `auth.activa` | `S9K_AUTH_ENABLED=true` | sí |
| `apply.habilitado` | la **misma** declaración que lee `v3_apply._habilitado` (`=="1"` y workspace) | sí |
| `neo4j.credencial` | usuario propio (≠ `neo4j`), fichero `0600`, fuera del repo, no vacío, **el valor no se lee** | sí |
| `neo4j.transporte` | local, o cifrado con CA presente; `+ssc` es ROJO | sí |
| `worker.observa_grafo` | ver abajo: **PENDIENTE**, dependencia del carril A | sí (mock ⇒ ROJO) |
| `aislamiento.workspace` | visor, writer y ensayo hablan del mismo workspace | sí |

**Calibrado** significa que existe una prueba que pone ese punto en **rojo**
mutando exactamente el fallo que ya se midió:
`deploy/tests/test_preflight_ensayo_rc.py`. Una comprobación que nunca se ha
visto roja es una frase, no una comprobación.

El guion **no usa instrumental externo** —solo biblioteca estándar— y eso está
comprobado **parseando sus imports**, no contando texto: `jq` no está instalado
en las máquinas de trabajo y un vigía que lo usaba giró en vacío sin emitir
nada.

### El árbol desde el que se ejecuta

Se añadió tras un incidente **real**: un agente reanudado perdió su árbol de
trabajo y siguió operando sobre otro, treinta ficheros por detrás de `main`,
creyendo que era el suyo. «El proceso ejecuta el árbol que cree» es una
propiedad **observable**, y nadie la miraba. Un ensayo sobre el árbol
equivocado emite un veredicto sobre **un producto que no es el que se va a
desplegar**, y desde fuera no se distingue de uno bueno. `arbol.declarado`
compara el `HEAD` real —leído de `.git`, también el de un *worktree* enlazado,
**sin invocar `git`**— con `S9K_ENSAYO_COMMIT`. Sin declarar, PENDIENTE; y
PENDIENTE bloquea.

### La comprobación que hoy bloquea

`worker.observa_grafo`. El ensayo ya **no** puede validar sólo volúmenes
compartidos: lo que decide si el recorrido termina es si el worker, con **su**
credencial y **su** contexto, **ve el grafo**. El camino de producto hasta el
driver real lo está construyendo **el carril A**, así que aquí la comprobación
queda **PENDIENTE** y el preflight sale ≠ 0.

No se sustituye por un sondeo propio a propósito: abrir aquí una sesión con el
driver mediría **otra cosa** distinta de la que usará el worker, y saldría
verde con el camino de producto roto. Cuando el carril A cierre, se observa
así, y no antes de tener su punto de entrada:

- con el entorno del ensayo, un sondeo de **solo lectura** por el **mismo**
  camino que usa el worker abre sesión, lee el workspace declarado y devuelve
  el recuento;
- credencial ausente, sin permiso, o TLS que no valida ⇒ **fallo explícito**,
  nunca «cero nodos».

## Estado persistente y reinicio

| Estado | Dónde | Qué pasa al reiniciar |
| --- | --- | --- |
| `review.sqlite3` (decisiones, planes sellados) | `S9K_STATE_ROOT/reviews-v3/` | sobrevive; es la autoridad de la revisión |
| almacén de propuestas | `S9K_STATE_ROOT/reviews-v3/proposals` | sobrevive; la cola sigue donde estaba |
| estado del escáner | `S9K_SCANNER_STATE_PATH` | **requisito: reiniciar NO reprocesa** |

Nada de esto puede vivir bajo el árbol de la release: un redespliegue se
llevaría por delante las decisiones humanas y la cola de revisión, y el
síntoma sería otra vez una pantalla vacía sin error.

**El requisito del reinicio se declara antes de que exista el escáner**, que es
justamente cuando sirve: tras reiniciar, cero jobs nuevos para ficheros ya
ingeridos, y los ya vistos **no cambian de identidad**. El preflight lo deja
`PENDIENTE` — que **bloquea** — en vez de darlo por bueno.

## Configuración declarada

`deploy/config/ensayo-rc.env.example`. Sin un solo secreto, y sin topología: el
repositorio es público.

- **Mínimo privilegio**: usuario propio del grafo, nunca el administrador
  `neo4j`, con alcance acotado al workspace del ensayo.
- **Secretos**: gestor de secretos → fichero `0600` → *stdin* → variable
  efímera. `S9K_NEO4J_PASSWORD` **en el entorno del proceso es un defecto**, y
  el preflight lo marca ROJO. Ningún secreto en `argv`, logs, tests, UI ni
  errores HTTP; del fichero se observan existencia, modo y tamaño, **nunca el
  valor**. Esa garantía está cerrada **por los dos lados**: una prueba ejecuta
  `main()` entero y mira `stdout` y `stderr` —mirar sólo el texto de cada
  resultado dejaba pasar una fuga por `print()`—, y otra **parsea** la
  comprobación de la credencial para exigir que ahí no haya ni una lectura de
  contenido. La segunda convierte la disciplina en estructura: aunque mañana se
  añada una traza, no tendrá el valor que filtrar.
- **Fail closed** en todo: los cuatro huecos apagados por defecto, el botón de
  aplicar inexistente sin declaración explícita.

## Aislamiento: qué habrá que demostrar

El ensayo no vale si el aislamiento no se **observa**:

1. **Workspace.** Lo que el visor pinta, aquello en lo que el writer puede
   escribir y el workspace del ensayo son el mismo (comprobado antes de
   empezar). Se demuestra ingiriendo en el workspace del ensayo y comprobando
   que **otro** workspace no ve ni una afirmación nueva, **por la pantalla**.
2. **Ámbito / partida.** Dos ingestas de la misma fuente en dos partidas
   distintas producen resultados que **no se mezclan**: cada pantalla de
   resultado muestra lo de su partida, y la procedencia de cada afirmación
   apunta a la evidencia de **esa** ingesta. Cuando cierre **MULTIPARTIDA-READ**
   se añade una garantía más, y también por pantalla: una divergencia local de
   una partida se ve **sólo desde ella**, y el lore que supersede sigue intacto
   para las demás.
3. **Escritura acotada.** Con `S9K_WRITER_WORKSPACE` en otro workspace, el
   botón **no aparece** y el POST contesta `APPLY_NOT_ENABLED`. Es la
   observación negativa: si apareciera, el aislamiento es decorativo.

Todo se observa **desde la interfaz**. Si para verlo hay que abrir el Neo4j
Browser, no está demostrado por el producto.

## Qué **no** cubre el ensayo

- **No mide calidad de extracción**: ni precisión, ni cobertura, ni el motor de
  relaciones. Es un ensayo de **recorrido**, no de acierto.
- **No valida rendimiento ni volumen**: una fuente pequeña ya conocida, no un
  corpus.
- **No cubre rollback ni supersesión** más allá de que el plan sellado sea el
  que se aplica.
- **No cubre copias de seguridad ni restauración**.
- **No cubre multimodal** (manuscritos, audio, vídeo).
- **No cubre concurrencia real** de varios operadores.
- **No dice nada de producción**: el ensayo corre en el laboratorio, con datos
  del laboratorio.
- **No valida el escáner**: todavía no existe; entra en el ensayo cuando exista.

## Dependencias

| Carril | Qué aporta | Estado para este ensayo |
| --- | --- | --- |
| **A · Neo4j product path** | camino de producto hasta el driver real | **bloqueante**: `worker.observa_grafo` sale PENDIENTE hasta que cierre |
| **B · M1 (bóvedas / Nextcloud)** | el escáner que detecta el fichero subido y el mapping a workspace/ámbito/partida | **bloqueante para el paso 1**: sin él, el ensayo arranca desde el catálogo de fuentes, no desde «subir fichero» |
| **MULTIPARTIDA-READ** | el enmascarado de divergencias locales (`local_override_of`) en el camino de lectura del visor | **bloqueante para el punto 2 del aislamiento**: sin él no se puede afirmar que la parte multi-partida sea usable de extremo a extremo |

Mientras cualquiera de las tres esté abierta, el ensayo es **parcial y hay que
declararlo como parcial**. El nombre `S9K_SCANNER_STATE_PATH` es **propuesto**:
si el carril B elige otro, se renombra aquí y en el guion.

## Pendiente de autorización del operador

El laboratorio de dos nodos donde este ensayo tiene que correr está **apagado
por decisión del operador**, y este carril **no** tiene autorización para
encenderlo. Su topología vive en el repositorio privado de infraestructura y no
se nombra aquí.

Por tanto, **todo lo que exige mirar esas máquinas queda pendiente**: ejecutar
el preflight sobre el entorno real, poblar el directorio de fuentes, crear el
usuario del grafo con mínimo privilegio y su fichero de credencial, y el ensayo
mismo. Lo entregado aquí se ha calibrado **sin encenderlas**.
